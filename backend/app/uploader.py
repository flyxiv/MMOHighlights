"""Uploads closed segments from the spool to the bucket.

The `segments` table is the queue. Workers claim one row at a time with
FOR UPDATE SKIP LOCKED, so several workers (or later, several VMs) never take the same file.
Workers wake on NOTIFY segment_ready, on local inserts, and every 30 s as a fallback.
"""

import asyncio
import logging
import uuid
from datetime import timedelta
from pathlib import Path

import asyncpg
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import views
from app.archive import UploadedVideo, build_manifest, build_playlist
from app.config import Settings
from app.db import raw_connect
from app.events import EventBus
from app.models import Recording, Segment
from app.storage import Storage
from app.util import upload_backoff_s, utcnow

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 20

CLAIM_SQL = text(
    """
    UPDATE segments SET status = 'uploading', attempts = attempts + 1
    WHERE (recording_id, kind, seq) = (
        SELECT recording_id, kind, seq FROM segments
        WHERE status = 'pending' AND next_attempt_at <= now()
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1)
    RETURNING recording_id, kind, seq, local_path, attempts
    """
)


def is_setup_problem(err: BaseException) -> bool:
    """Credentials missing, expired or lacking permission: fixed by setup, not by retrying the file."""
    name = type(err).__name__
    text = str(err)
    return (
        name in ("DefaultCredentialsError", "RefreshError")
        or (name == "Forbidden" and "storage.objects" in text)
        or "Project was not passed" in text
    )


class Uploader:
    def __init__(
        self, settings: Settings, sessions: async_sessionmaker[AsyncSession], storage: Storage, bus: EventBus
    ):
        self.s = settings
        self.sessions = sessions
        self.storage = storage
        self.bus = bus
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._listen_conn: asyncpg.Connection | None = None
        self._manifest_locks: dict[uuid.UUID, asyncio.Lock] = {}

    def wake(self) -> None:
        self._wake.set()

    async def start(self) -> None:
        try:
            self._listen_conn = await raw_connect()
            await self._listen_conn.add_listener("segment_ready", lambda *_: self.wake())
        except (OSError, asyncpg.PostgresError) as e:
            log.warning("LISTEN segment_ready unavailable (%s); polling every 30 s", e)
        for i in range(self.s.upload_workers):
            self._tasks.append(asyncio.create_task(self._worker(i), name=f"uploader-{i}"))
        self._tasks.append(asyncio.create_task(self._sweep_loop(), name="spool-sweeper"))

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.sweep_spool()
            except Exception:  # noqa: BLE001
                log.exception("spool sweep failed")

    async def sweep_spool(self) -> int:
        """Delete spool files that are already uploaded.

        Deleting right after upload can fail on Windows while another process (ffmpeg, antivirus)
        still has the new file open for a moment, so this retries later.
        """
        async with self.sessions() as session:
            paths = (
                (await session.execute(select(Segment.local_path).where(Segment.status == "uploaded")))
                .scalars()
                .all()
            )
        removed = 0
        for p in paths:
            path = Path(p)
            if path.exists():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._listen_conn is not None:
            await self._listen_conn.close()

    async def _worker(self, n: int) -> None:
        while True:
            try:
                did_work = await self.process_one()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep the worker alive
                log.exception("uploader-%d crashed on a segment", n)
                did_work = False
            if not did_work:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=30)
                except TimeoutError:
                    pass

    async def process_one(self) -> bool:
        async with self.sessions() as session:
            row = (await session.execute(CLAIM_SQL)).first()
            await session.commit()
        if row is None:
            return False
        rid, kind, seq, local_path, attempts = row
        path = Path(local_path)
        async with self.sessions() as session:
            rec = await session.get(Recording, rid)
        if rec is None:
            return True
        name = f"{rec.gcs_prefix}{path.name}"
        content_type = "video/mp2t" if kind == "video" else "application/gzip"
        try:
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing from the spool")
            await self.storage.upload_file(path, name, content_type)
        except Exception as e:  # noqa: BLE001 — every failure is retried with backoff
            await self._failed(rid, kind, seq, attempts, e)
            return True

        async with self.sessions() as session:
            await session.execute(
                update(Segment)
                .where(Segment.recording_id == rid, Segment.kind == kind, Segment.seq == seq)
                .values(status="uploaded", uploaded_at=utcnow(), last_error=None)
            )
            await session.commit()
        try:
            path.unlink()
        except OSError as e:
            log.info("couldn't delete %s yet (%s); the spool sweep retries", path.name, e)
        await self.after_upload(rid)
        return True

    async def _failed(self, rid, kind, seq, attempts: int, err: Exception) -> None:
        message = f"{type(err).__name__}: {err}"[:1000]
        values: dict = {"status": "pending", "last_error": message}
        if is_setup_problem(err):
            # Missing or expired credentials aren't this file's fault: don't use up its attempts,
            # just try again every 5 minutes until access is set up.
            values["attempts"] = Segment.attempts - 1
            values["next_attempt_at"] = utcnow() + timedelta(minutes=5)
        else:
            if attempts >= MAX_ATTEMPTS or isinstance(err, FileNotFoundError):
                values["status"] = "failed"
            values["next_attempt_at"] = utcnow() + timedelta(seconds=upload_backoff_s(attempts))
        log.warning("upload %s/%s/%d failed (attempt %d): %s", rid, kind, seq, attempts, message)
        async with self.sessions() as session:
            await session.execute(
                update(Segment)
                .where(Segment.recording_id == rid, Segment.kind == kind, Segment.seq == seq)
                .values(**values)
            )
            await session.commit()
        await self._publish(rid)

    async def after_upload(self, rid: uuid.UUID) -> None:
        """Rewrite manifest.json and index.m3u8, and complete the recording if nothing is left."""
        lock = self._manifest_locks.setdefault(rid, asyncio.Lock())
        async with lock:
            async with self.sessions() as session:
                rec = await views.load_recording(session, rid)
                if rec is None:
                    return
                segs = (
                    (
                        await session.execute(
                            select(Segment).where(Segment.recording_id == rid).order_by(Segment.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                remaining = sum(1 for s in segs if s.status in ("pending", "uploading"))
                failed = sum(1 for s in segs if s.status == "failed")
                done = rec.status == "finalizing" and remaining == 0
                if done:
                    rec.status = "completed"
                    if failed:
                        rec.last_error = f"{failed} segment{'s' if failed != 1 else ''} lost"
                    await session.commit()
            videos = [
                UploadedVideo(s.seq, s.start_s, s.end_s, s.size_bytes)
                for s in segs
                if s.kind == "video" and s.status == "uploaded"
            ]
            chats = [s.seq for s in segs if s.kind == "chat" and s.status == "uploaded"]
            meta = {
                "recording_id": str(rec.id),
                "platform": rec.channel.platform,
                "channel": rec.channel.display_name,
                "channel_id": rec.channel.platform_id,
                "stream_id": rec.platform_stream_id,
                "title": rec.title,
                "status": rec.status,
                "started_at": rec.started_at,
                "ended_at": rec.ended_at,
                "quality": rec.quality,
                "chat_offset_s": rec.chat_offset_s,
                "game": rec.game.name if rec.game else None,
                "tier": rec.tier.name if rec.tier else None,
            }
            finished = rec.status in ("completed", "failed")
            try:
                await self.storage.upload_text(
                    build_manifest(meta, videos, chats), f"{rec.gcs_prefix}manifest.json", "application/json"
                )
                if videos:
                    await self.storage.upload_text(
                        build_playlist(videos, finished),
                        f"{rec.gcs_prefix}index.m3u8",
                        "application/vnd.apple.mpegurl",
                    )
            except Exception as e:  # noqa: BLE001 — the next upload rewrites them anyway
                log.warning("manifest upload for %s failed: %s", rid, e)
        await self._publish(rid)

    async def backlog(self) -> int:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(Segment)
                    .where(Segment.status.in_(("pending", "uploading")))
                )
            ).scalar_one()

    async def _publish(self, rid: uuid.UUID) -> None:
        async with self.sessions() as session:
            out = await views.recording_by_id(session, rid)
        if out is not None:
            self.bus.publish("recording.updated", out)
