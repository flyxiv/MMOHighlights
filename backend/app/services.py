"""Wires the long-running parts together and runs the small periodic jobs."""

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import schemas
from app.config import Settings
from app.db import raw_connect
from app.events import EventBus, EventRelay
from app.models import Channel, Recording
from app.platforms import Platforms
from app.poller import Poller
from app.recorder.supervisor import Supervisor, reconcile_on_startup
from app.storage import Storage
from app.uploader import Uploader
from app.util import ACTIVE_RECORDING_STATUSES, utcnow

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    bus: EventBus
    platforms: Platforms
    storage: Storage
    uploader: Uploader
    supervisor: Supervisor
    poller: Poller
    relay: EventRelay
    _tasks: list[asyncio.Task] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        storage: Storage,
        platforms: Platforms | None = None,
    ) -> "Services":
        bus = EventBus()
        platforms = platforms or Platforms(settings)
        uploader = Uploader(settings, sessions, storage, bus)
        supervisor = Supervisor(settings, sessions, platforms, bus, uploader.wake)
        supervisor.after_finalize = uploader.after_upload
        poller = Poller(settings, sessions, platforms, supervisor, bus)
        relay = EventRelay(bus, raw_connect)
        return cls(settings, sessions, bus, platforms, storage, uploader, supervisor, poller, relay)

    @property
    def is_viewer(self) -> bool:
        return self.settings.role == "viewer"

    async def start(self) -> None:
        self.relay.start()
        if self.is_viewer:
            return  # page and API only; the recorder machine does the rest
        self.settings.spool_dir.mkdir(parents=True, exist_ok=True)
        await reconcile_on_startup(self.sessions, self.settings.spool_dir)
        await self.uploader.start()
        self.poller.start()
        self._tasks.append(asyncio.create_task(self._health_loop(), name="health"))
        self._tasks.append(asyncio.create_task(self._purge_loop(), name="purge"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.relay.stop()
        await self.poller.stop()
        await self.supervisor.shutdown()
        await self.uploader.stop()
        await self.platforms.aclose()

    async def health(self) -> schemas.HealthOut:
        if self.is_viewer and self.bus.remote_health:
            # The recorder machine's figures (poller, spool, backlog), at most ~10 s old.
            return schemas.HealthOut.model_validate_json(self.bus.remote_health)
        async with self.sessions() as session:
            tracked, live = (
                await session.execute(
                    select(func.count(), func.count().filter(Channel.status == "live"))
                    .select_from(Channel)
                    .where(Channel.deleted_at.is_(None))
                )
            ).one()
            rec_count, chat, size = (
                await session.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(Recording.chat_messages), 0),
                        func.coalesce(func.sum(Recording.bytes_recorded), 0),
                    ).where(Recording.status.in_(ACTIVE_RECORDING_STATUSES))
                )
            ).one()
        spool = self.settings.spool_dir
        free = shutil.disk_usage(spool if spool.exists() else ".").free
        return schemas.HealthOut(
            poll_last_run_at=self.poller.last_run_at,
            next_poll_in_s=self.poller.next_poll_in_s,
            spool_free_bytes=free,
            upload_backlog=await self.uploader.backlog(),
            tracked_count=tracked,
            max_channels=self.settings.max_channels,
            live_count=live,
            recording_count=rec_count,
            chat_messages_active=int(chat),
            bytes_active=int(size),
        )

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            # Always published: pages on viewer machines get the recorder's health through the relay.
            try:
                self.bus.publish("health", await self.health())
            except Exception:  # noqa: BLE001
                log.exception("health event failed")

    async def _purge_loop(self) -> None:
        """Marks recordings whose files the bucket lifecycle rule has deleted."""
        while True:
            try:
                cutoff = utcnow() - timedelta(days=self.settings.retention_days)
                async with self.sessions() as session:
                    await session.execute(
                        update(Recording)
                        .where(
                            Recording.status.in_(("completed", "failed")),
                            Recording.started_at < cutoff,
                            Recording.purged_at.is_(None),
                        )
                        .values(purged_at=utcnow())
                    )
                    await session.commit()
            except Exception:  # noqa: BLE001
                log.exception("purge job failed")
            await asyncio.sleep(6 * 3600)


def get_services(request: Request) -> Services:
    return request.app.state.services
