"""Change events for the page's live updates (Server-Sent Events).

Each backend fans events out to its own SSE clients. With a shared database, the relay also sends
them through Postgres NOTIFY so pages served by other machines (viewers) update live too.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)

CHANNEL = "recorder_events"
# NOTIFY payloads are limited to 8000 bytes; bigger events are only delivered locally.
MAX_PAYLOAD = 7900


class EventBus:
    def __init__(self, queue_size: int = 256):
        self._subscribers: set[asyncio.Queue[tuple[str, str]]] = set()
        self._queue_size = queue_size
        # Set by the relay; called with (event, json payload) for every locally published event.
        self.forward: Callable[[str, str], None] | None = None
        # Latest health event received from another machine (viewers show the recorder's health).
        self.remote_health: str | None = None

    def publish(self, event: str, data: BaseModel | dict[str, Any]) -> None:
        payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data, default=str)
        self.publish_local(event, payload)
        if self.forward is not None:
            self.forward(event, payload)

    def publish_local(self, event: str, payload: str) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait((event, payload))
            except asyncio.QueueFull:
                # A stalled client loses events; it refetches on reconnect.
                pass

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[tuple[str, str]]]:
        q: asyncio.Queue[tuple[str, str]] = asyncio.Queue(self._queue_size)
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class EventRelay:
    """Shares a bus's events with every other backend on the same database via LISTEN/NOTIFY."""

    def __init__(self, bus: EventBus, connect):
        self.bus = bus
        self._connect = connect
        self.origin = uuid.uuid4().hex[:12]
        self._outbox: asyncio.Queue[str] = asyncio.Queue(1000)
        self._task: asyncio.Task | None = None
        self.connected = asyncio.Event()

    def start(self) -> None:
        self.bus.forward = self._enqueue
        self._task = asyncio.create_task(self._run(), name="event-relay")

    async def stop(self) -> None:
        self.bus.forward = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def _enqueue(self, event: str, payload: str) -> None:
        message = json.dumps({"o": self.origin, "e": event, "d": payload})
        if len(message.encode("utf-8")) > MAX_PAYLOAD:
            return
        try:
            self._outbox.put_nowait(message)
        except asyncio.QueueFull:
            pass

    def _received(self, _conn, _pid, _channel, message: str) -> None:
        try:
            m = json.loads(message)
        except json.JSONDecodeError:
            return
        if m.get("o") == self.origin:
            return
        if m.get("e") == "health":
            self.bus.remote_health = m["d"]
        self.bus.publish_local(m["e"], m["d"])

    async def _run(self) -> None:
        delay = 1.0
        while True:
            conn = None
            try:
                conn = await self._connect()
                await conn.add_listener(CHANNEL, self._received)
                self.connected.set()
                delay = 1.0
                while True:
                    message = await self._outbox.get()
                    await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, message)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — reconnect on any connection failure
                self.connected.clear()
                log.warning("event relay disconnected (%s); retrying in %.0f s", e, delay)
            finally:
                if conn is not None:
                    try:
                        await conn.close(timeout=2)
                    except Exception:  # noqa: BLE001
                        pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


def sse_format(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"
