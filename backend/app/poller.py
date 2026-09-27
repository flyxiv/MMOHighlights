"""Checks every tracked channel every 30 seconds and drives recordings through their lifecycle."""

import asyncio
import logging
import random
import time
from datetime import datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import views
from app.config import Settings
from app.events import EventBus
from app.models import Channel, Recording
from app.platforms import Platforms
from app.platforms.base import ChannelNotFound, LiveStatus, PlatformError
from app.recorder.lifecycle import Action, RecordingState, decide
from app.recorder.supervisor import Supervisor
from app.util import ACTIVE_RECORDING_STATUSES, utcnow

log = logging.getLogger(__name__)


class Poller:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        platforms: Platforms,
        supervisor: Supervisor,
        bus: EventBus,
    ):
        self.s = settings
        self.sessions = sessions
        self.platforms = platforms
        self.supervisor = supervisor
        self.bus = bus
        self.last_run_at: datetime | None = None
        self._next_run_mono: float | None = None
        self._task: asyncio.Task | None = None
        self._kick = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def kick(self) -> None:
        """Check right away (e.g. after a channel is added)."""
        self._kick.set()

    @property
    def next_poll_in_s(self) -> float | None:
        if self._next_run_mono is None:
            return None
        return max(self._next_run_mono - time.monotonic(), 0.0)

    async def _loop(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a bad tick must not stop polling
                log.exception("poll tick failed")
            delay = self.s.poll_interval_s + random.uniform(-self.s.poll_jitter_s, self.s.poll_jitter_s)
            delay = max(delay - (time.monotonic() - started), 1.0)
            self._next_run_mono = time.monotonic() + delay
            self._kick.clear()
            try:
                await asyncio.wait_for(self._kick.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def tick(self) -> None:
        async with self.sessions() as session:
            channels = (
                (await session.execute(select(Channel).where(Channel.deleted_at.is_(None)))).scalars().all()
            )
        by_platform: dict[str, list[Channel]] = {}
        for c in channels:
            by_platform.setdefault(c.platform, []).append(c)

        results = await asyncio.gather(
            *(self._check_platform(p, cs) for p, cs in by_platform.items()), return_exceptions=True
        )
        for (platform, cs), res in zip(by_platform.items(), results, strict=True):
            error: BaseException | None = None
            if isinstance(res, BaseException):
                log.warning("%s check failed: %s", platform, res)
                error, res = res, {}
            for c in cs:
                status = res.get(c.platform_id)
                try:
                    await self._apply(c, status, None if status is not None else _describe(error, platform))
                except Exception:  # noqa: BLE001
                    log.exception("applying status for %s/%s failed", c.platform, c.platform_id)
        await self._finalize_expired()
        self.last_run_at = utcnow()

    async def _check_platform(self, platform: str, channels: list[Channel]) -> dict[str, LiveStatus]:
        adapter = self.platforms.get(platform)
        return await adapter.check([c.platform_id for c in channels])

    async def _apply(self, channel: Channel, status: LiveStatus | None, error: str | None) -> None:
        now = utcnow()
        async with self.sessions() as session:
            c = await session.get(Channel, channel.id)
            if c is None or c.deleted_at is not None:
                return
            c.last_checked_at = now
            if status is None:
                c.check_failures += 1
                c.last_error = error
                if c.check_failures >= self.s.checks_failed_before_error:
                    c.status = "error"
                await session.commit()
                await self._publish_channel(c.id)
                return  # keep the last known live state; don't end a recording on a failed check
            c.check_failures = 0
            c.last_error = None
            was_live = c.status == "live"
            c.status = "live" if status.is_live else "offline"
            if status.is_live:
                c.live_title = status.title
                c.live_category = status.category
                if not was_live or c.last_live_started_at is None:
                    c.last_live_started_at = status.started_at or now
            elif c.skip_stream_id is not None:
                c.skip_stream_id = None  # the stopped broadcast is over
            rec = (
                await session.execute(
                    select(Recording)
                    .where(Recording.channel_id == c.id, Recording.status.in_(ACTIVE_RECORDING_STATUSES))
                    .order_by(Recording.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if rec is not None and status.is_live and status.title and rec.title != status.title:
                rec.title = status.title
            await session.commit()

        action = decide(
            is_live=status.is_live,
            stream_id=status.stream_id,
            skip_stream_id=c.skip_stream_id,
            recording=None
            if rec is None
            else RecordingState(
                rec.status, rec.offline_polls, rec.ending_since, self.supervisor.pipeline_running(rec.id)
            ),
            now=now,
            offline_polls_to_end=self.s.offline_polls_to_end,
            grace_period_s=self.s.grace_period_s,
        )
        if action != Action.NOTHING:
            log.info("%s/%s: %s", c.platform, c.platform_id, action)
        match action:
            case Action.START:
                await self.supervisor.start(c, status)
            case Action.RESUME:
                await self.supervisor.resume(rec, c, status)
            case Action.RESTART_PIPELINE:
                await self.supervisor.restart_pipeline(rec, c, status)
            case Action.COUNT_OFFLINE:
                async with self.sessions() as session:
                    await session.execute(
                        update(Recording)
                        .where(Recording.id == rec.id)
                        .values(offline_polls=Recording.offline_polls + 1)
                    )
                    await session.commit()
            case Action.BEGIN_ENDING:
                await self.supervisor.begin_ending(rec)
            case Action.FINALIZE:
                await self.supervisor.finalize(rec.id)
        await self._publish_channel(c.id)

    async def _finalize_expired(self) -> None:
        """Recordings in "ending" whose channel failed its checks still need to finish eventually."""
        async with self.sessions() as session:
            recs = (
                (await session.execute(select(Recording).where(Recording.status == "ending"))).scalars().all()
            )
        now = utcnow()
        for r in recs:
            if r.ending_since and (now - r.ending_since).total_seconds() >= self.s.grace_period_s * 3:
                await self.supervisor.finalize(r.id)

    async def _publish_channel(self, channel_id) -> None:
        async with self.sessions() as session:
            out = await views.channels_out(session, [channel_id])
        if out:
            self.bus.publish("channel.updated", out[0])


def _describe(error: BaseException | None, platform: str) -> str:
    if isinstance(error, PlatformError | ChannelNotFound):
        return str(error)
    if isinstance(error, httpx.HTTPError):
        return f"Couldn't reach {platform}: {type(error).__name__}"
    if error is not None:
        return f"{platform} check failed: {type(error).__name__}"
    return f"The {platform} check didn't return this channel."
