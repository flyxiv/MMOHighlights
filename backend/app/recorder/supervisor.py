"""Starts, resumes and stops recordings. Owns the running pipelines and chat loggers.

All state that matters lives in Postgres; the in-memory map only tracks processes, so a
restart can pick up where it left off (see `reconcile_on_startup`).
"""

import asyncio
import logging
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import views
from app.archive import recording_prefix
from app.chat.chzzk import chzzk_chat
from app.chat.logger import ChatLogger, ChatWriter
from app.chat.models import ChatMessage
from app.chat.twitch import twitch_chat
from app.chat.youtube import youtube_chat
from app.config import Settings
from app.events import EventBus
from app.models import Channel, ChatMinute, Recording, Segment
from app.platforms import Platforms
from app.platforms.base import LiveStatus
from app.recorder.pipeline import ClosedSegment, Pipeline
from app.util import utcnow

log = logging.getLogger(__name__)
WORKER_ID = socket.gethostname()


@dataclass
class Active:
    recording_id: uuid.UUID
    channel_id: uuid.UUID
    platform: str
    platform_id: str
    out_dir: Path
    next_seq: int
    writer: ChatWriter
    chat: ChatLogger | None = None
    pipeline: Pipeline | None = None
    pipeline_task: asyncio.Task | None = None
    # Seconds from recording start to this pipeline's start; added to ffmpeg's segment times.
    pipeline_offset_s: float = 0.0


class Supervisor:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        platforms: Platforms,
        bus: EventBus,
        wake_uploader: Callable[[], None],
    ):
        self.s = settings
        self.sessions = sessions
        self.platforms = platforms
        self.bus = bus
        self.wake_uploader = wake_uploader
        self.active: dict[uuid.UUID, Active] = {}
        self._flush_task: asyncio.Task | None = None
        self.after_finalize: Callable[[uuid.UUID], Awaitable[None]] | None = None
        # Swappable in tests (a generated video instead of streamlink).
        self.make_pipeline: Callable[..., Pipeline] = Pipeline

    # ---------- lifecycle actions (called by the poller) ----------

    def pipeline_running(self, recording_id: uuid.UUID) -> bool:
        a = self.active.get(recording_id)
        return bool(a and a.pipeline_task and not a.pipeline_task.done())

    async def start(self, channel: Channel, status: LiveStatus) -> uuid.UUID:
        now = utcnow()
        rid = uuid.uuid4()
        async with self.sessions() as session:
            rec = Recording(
                id=rid,
                channel_id=channel.id,
                platform_stream_id=status.stream_id,
                title=status.title or "",
                status="recording",
                started_at=now,
                gcs_prefix=recording_prefix(
                    self.s.normalized_prefix, channel.platform, channel.platform_id, now, rid
                ),
                quality=self.s.quality.split(",")[0],
                chat_offset_s=self._chat_offset(channel.platform),
                worker_id=WORKER_ID,
                game_id=channel.default_game_id,
                tier_id=channel.default_tier_id,
                labels_source="channel_default" if channel.default_game_id else None,
            )
            session.add(rec)
            await session.commit()
        a = self._make_active(rec, channel.platform, channel.platform_id, next_seq=0)
        self._start_chat(a, rec, status)
        await self._start_pipeline(a, rec)
        await self.publish_recording(rid)
        log.info("recording %s started for %s/%s", rid, channel.platform, channel.platform_id)
        return rid

    async def resume(self, rec: Recording, channel: Channel, status: LiveStatus) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(Recording)
                .where(Recording.id == rec.id)
                .values(status="recording", ending_since=None, offline_polls=0, last_error=None)
            )
            await session.commit()
        a = self.active.get(rec.id)
        if a is None:
            a = self._make_active(rec, channel.platform, channel.platform_id, await self._next_seq(rec.id))
        if a.chat is None:
            self._start_chat(a, rec, status)
        await self._start_pipeline(a, rec)
        await self.publish_recording(rec.id)

    async def restart_pipeline(self, rec: Recording, channel: Channel, status: LiveStatus) -> None:
        a = self.active.get(rec.id)
        if a is None:
            a = self._make_active(rec, channel.platform, channel.platform_id, await self._next_seq(rec.id))
            self._start_chat(a, rec, status)
        await self._start_pipeline(a, rec)

    async def begin_ending(self, rec: Recording) -> None:
        a = self.active.get(rec.id)
        if a is not None and a.pipeline is not None:
            await a.pipeline.stop()
            if a.pipeline_task is not None:
                await asyncio.gather(a.pipeline_task, return_exceptions=True)
        async with self.sessions() as session:
            await session.execute(
                update(Recording)
                .where(Recording.id == rec.id)
                .values(status="ending", ending_since=utcnow(), offline_polls=0)
            )
            await session.commit()
        await self.publish_recording(rec.id)

    async def finalize(self, rec_id: uuid.UUID, *, ended_at=None) -> None:
        a = self.active.pop(rec_id, None)
        if a is not None:
            if a.pipeline is not None:
                await a.pipeline.stop()
            if a.pipeline_task is not None:
                await asyncio.gather(a.pipeline_task, return_exceptions=True)
            if a.chat is not None:
                await a.chat.stop()
            closed = a.writer.close()
            await self._flush_chat(a)
            if closed:
                await self._add_segment(rec_id, "chat", closed[0], closed[1], None, None)
        async with self.sessions() as session:
            rec = await session.get(Recording, rec_id)
            if rec is None:
                return
            end = ended_at or rec.ending_since or utcnow()
            has_video = (
                await session.execute(
                    select(func.count())
                    .select_from(Segment)
                    .where(Segment.recording_id == rec_id, Segment.kind == "video")
                )
            ).scalar_one()
            rec.ended_at = end
            rec.status = "finalizing" if has_video else "failed"
            if not has_video and not rec.last_error:
                rec.last_error = "No video was captured."
            await session.execute(
                update(Channel).where(Channel.id == rec.channel_id).values(last_live_ended_at=end)
            )
            await session.commit()
        self.wake_uploader()
        if self.after_finalize is not None:
            # Completes the recording right away if every segment is already uploaded.
            await self.after_finalize(rec_id)
        await self.publish_recording(rec_id)
        log.info("recording %s finalizing", rec_id)

    async def stop_manually(self, rec_id: uuid.UUID) -> None:
        async with self.sessions() as session:
            rec = await session.get(Recording, rec_id)
            if rec is None:
                return
            await session.execute(
                update(Channel)
                .where(Channel.id == rec.channel_id)
                .values(skip_stream_id=rec.platform_stream_id)
            )
            await session.commit()
        await self.finalize(rec_id, ended_at=utcnow())

    async def shutdown(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        for rid in list(self.active):
            a = self.active[rid]
            if a.pipeline is not None:
                await a.pipeline.stop(timeout=10)
            if a.chat is not None:
                await a.chat.stop()
            a.writer.close()
            await self._flush_chat(a)

    # ---------- internals ----------

    def _chat_offset(self, platform: str) -> float:
        return {
            "twitch": self.s.chat_offset_twitch_s,
            "youtube": self.s.chat_offset_youtube_s,
            "chzzk": self.s.chat_offset_chzzk_s,
        }[platform]

    def _make_active(self, rec: Recording, platform: str, platform_id: str, next_seq: int) -> Active:
        out_dir = self.s.spool_dir / str(rec.id)
        writer = ChatWriter(out_dir, rec.started_at, rec.chat_offset_s, next_seq)
        writer.base_total = rec.chat_messages or 0
        a = Active(rec.id, rec.channel_id, platform, platform_id, out_dir, next_seq, writer)
        self.active[rec.id] = a
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())
        return a

    async def _next_seq(self, rec_id: uuid.UUID) -> int:
        async with self.sessions() as session:
            m = (
                await session.execute(
                    select(func.max(Segment.seq)).where(
                        Segment.recording_id == rec_id, Segment.kind == "video"
                    )
                )
            ).scalar_one()
        return 0 if m is None else m + 1

    def _chat_source(
        self, platform: str, platform_id: str, status: LiveStatus
    ) -> Callable[[], AsyncIterator[ChatMessage]]:
        if platform == "twitch":
            return lambda: twitch_chat(platform_id)
        if platform == "youtube":
            video_id = status.stream_id or ""
            return lambda: youtube_chat(video_id)
        chzzk = self.platforms.chzzk

        async def chzzk_source() -> AsyncIterator[ChatMessage]:
            live = await chzzk.live_status(platform_id)
            if not live.chat_channel_id:
                raise RuntimeError("Chzzk live status has no chat channel id.")
            token = await chzzk.chat_access_token(live.chat_channel_id)
            async for msg in chzzk_chat(live.chat_channel_id, token):
                yield msg

        return chzzk_source

    def _start_chat(self, a: Active, rec: Recording, status: LiveStatus) -> None:
        if a.platform == "youtube" and not status.stream_id:
            return
        a.chat = ChatLogger(
            a.writer, self._chat_source(a.platform, a.platform_id, status), name=str(rec.id)[:8]
        )
        a.chat.start()

    async def _start_pipeline(self, a: Active, rec: Recording) -> None:
        if a.pipeline_task is not None and not a.pipeline_task.done():
            return
        adapter = self.platforms.get(a.platform)
        cookies = None
        if a.platform == "chzzk" and self.s.chzzk_nid_aut:
            cookies = {"NID_AUT": self.s.chzzk_nid_aut, "NID_SES": self.s.chzzk_nid_ses}
        a.pipeline = self.make_pipeline(
            adapter.stream_url(a.platform_id),
            a.out_dir,
            quality=self.s.quality,
            segment_seconds=self.s.segment_seconds,
            start_number=a.next_seq,
            twitch=a.platform == "twitch",
            cookies=cookies,
        )
        a.pipeline_offset_s = (utcnow() - rec.started_at).total_seconds()
        a.writer.seq = a.next_seq
        try:
            await a.pipeline.start()
        except OSError as e:
            await self._set_error(rec.id, f"Couldn't start the recorder: {e}")
            a.pipeline = None
            return
        a.pipeline_task = asyncio.create_task(self._consume(a), name=f"pipeline-{str(rec.id)[:8]}")

    async def _consume(self, a: Active) -> None:
        pipeline = a.pipeline
        assert pipeline is not None
        async for seg in pipeline.closed_segments():
            await self._on_video_closed(a, seg)
        code = await pipeline.wait()
        # Backup signal: any segment file ffmpeg finished without reporting it.
        for path in sorted(a.out_dir.glob("seg_*.ts")):
            try:
                seq = int(path.stem.removeprefix("seg_"))
            except ValueError:
                continue
            if seq >= a.next_seq and path.stat().st_size > 0:
                await self._on_video_closed(a, ClosedSegment(seq, path, 0.0, 0.0), estimated=True)
        if code != 0:
            await self._set_error(
                a.recording_id, "\n".join(pipeline.stderr_tail[-5:]) or f"ffmpeg exited with {code}"
            )
        a.pipeline = None

    async def _on_video_closed(self, a: Active, seg: ClosedSegment, estimated: bool = False) -> None:
        start = None if estimated else a.pipeline_offset_s + seg.start_s
        end = None if estimated else a.pipeline_offset_s + seg.end_s
        inserted = await self._add_segment(a.recording_id, "video", seg.seq, seg.path, start, end)
        a.next_seq = max(a.next_seq, seg.seq + 1)
        chat_path = a.writer.rollover(seg.seq)
        if chat_path is not None:
            await self._add_segment(a.recording_id, "chat", seg.seq, chat_path, start, end)
        if inserted:
            await self.publish_recording(a.recording_id)

    async def _add_segment(
        self, rec_id: uuid.UUID, kind: str, seq: int, path: Path, start: float | None, end: float | None
    ) -> bool:
        size = path.stat().st_size if path.exists() else 0
        async with self.sessions() as session:
            res = await session.execute(
                insert(Segment)
                .values(
                    recording_id=rec_id,
                    kind=kind,
                    seq=seq,
                    local_path=str(path),
                    start_s=start,
                    end_s=end,
                    size_bytes=size,
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=["recording_id", "kind", "seq"])
            )
            inserted = res.rowcount > 0
            if inserted and kind == "video":
                await session.execute(
                    update(Recording)
                    .where(Recording.id == rec_id)
                    .values(bytes_recorded=Recording.bytes_recorded + size)
                )
            if inserted:
                await session.execute(text("NOTIFY segment_ready"))
            await session.commit()
        if inserted:
            self.wake_uploader()
        return inserted

    async def _set_error(self, rec_id: uuid.UUID, message: str) -> None:
        log.warning("recording %s: %s", rec_id, message)
        async with self.sessions() as session:
            await session.execute(
                update(Recording).where(Recording.id == rec_id).values(last_error=message[:2000])
            )
            await session.commit()
        await self.publish_recording(rec_id)

    async def _flush_loop(self) -> None:
        while self.active:
            await asyncio.sleep(15)
            for a in list(self.active.values()):
                try:
                    await self._flush_chat(a)
                except Exception:  # noqa: BLE001
                    log.exception("chat flush failed")

    async def _flush_chat(self, a: Active) -> None:
        w = a.writer
        if not w.dirty_minutes:
            return
        rows = [
            {
                "recording_id": a.recording_id,
                "minute": m,
                "messages": w.minutes[m].messages,
                "unique_chatters": len(w.minutes[m].chatters),
                "paid_messages": w.minutes[m].paid_messages,
                "paid_amount": w.minutes[m].paid_amount,
            }
            for m in sorted(w.dirty_minutes)
        ]
        w.dirty_minutes.clear()
        async with self.sessions() as session:
            stmt = insert(ChatMinute).values(rows)
            # GREATEST: after a restart, in-memory counts for the current minute start again from zero.
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["recording_id", "minute"],
                    set_={
                        k: func.greatest(getattr(ChatMinute, k), stmt.excluded[k])
                        for k in ("messages", "unique_chatters", "paid_messages", "paid_amount")
                    },
                )
            )
            # The writer counts messages since this process picked the recording up.
            await session.execute(
                update(Recording)
                .where(Recording.id == a.recording_id)
                .values(chat_messages=w.total + w.base_total)
            )
            await session.commit()

    async def publish_recording(self, rec_id: uuid.UUID) -> None:
        async with self.sessions() as session:
            out = await views.recording_by_id(session, rec_id)
            if out is None:
                return
            self.bus.publish("recording.updated", out)
            ch = await views.channels_out(session, [out.channel.id])
        if ch:
            self.bus.publish("channel.updated", ch[0])


async def reconcile_on_startup(sessions: async_sessionmaker[AsyncSession], spool_dir: Path) -> None:
    """Recover from a crash or restart.

    - Recordings still marked "recording" lost their process: move them to "ending" so the poller
      resumes them if the stream is still live, or finalizes them after the grace period.
    - Segments stuck in "uploading" go back to "pending".
    - Closed files in the spool without a row get one.
    """
    now = utcnow()
    async with sessions() as session:
        await session.execute(
            update(Recording).where(Recording.status == "recording").values(status="ending", ending_since=now)
        )
        await session.execute(update(Segment).where(Segment.status == "uploading").values(status="pending"))
        known = {
            (rid, kind, seq)
            for rid, kind, seq in await session.execute(
                select(Segment.recording_id, Segment.kind, Segment.seq)
            )
        }
        rec_ids = {r for (r,) in await session.execute(select(Recording.id))}
        if spool_dir.exists():
            for d in spool_dir.iterdir():
                try:
                    rid = uuid.UUID(d.name)
                except ValueError:
                    continue
                if rid not in rec_ids:
                    continue
                for path in d.iterdir():
                    kind, seq = _classify(path)
                    if kind is None or (rid, kind, seq) in known or path.stat().st_size == 0:
                        continue
                    await session.execute(
                        insert(Segment)
                        .values(
                            recording_id=rid,
                            kind=kind,
                            seq=seq,
                            local_path=str(path),
                            size_bytes=path.stat().st_size,
                            status="pending",
                        )
                        .on_conflict_do_nothing(index_elements=["recording_id", "kind", "seq"])
                    )
        await session.commit()


def _classify(path: Path) -> tuple[str | None, int]:
    name = path.name
    try:
        if name.startswith("seg_") and name.endswith(".ts"):
            return "video", int(name[4:-3])
        if name.startswith("chat_") and name.endswith(".jsonl.gz"):
            return "chat", int(name[5 : -len(".jsonl.gz")])
    except ValueError:
        pass
    return None, 0
