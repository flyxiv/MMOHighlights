"""Writes one recording's chat to gzipped JSON-lines files that line up with the video segments.

Messages go into chat_<seq>.jsonl.gz for the video segment currently being written. When video
segment N closes, `rollover(N)` closes chat_N and it joins the upload queue. Per-minute counts
are kept in memory and flushed to chat_minutes periodically.
"""

import asyncio
import gzip
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO

from app.archive import chat_name
from app.chat.models import ChatMessage
from app.util import utcnow

log = logging.getLogger(__name__)

ChatSourceFactory = Callable[[], AsyncIterator[ChatMessage]]
ClosedChatFile = Callable[[int, Path], Awaitable[None]]


@dataclass
class MinuteCounts:
    messages: int = 0
    chatters: set[str] = field(default_factory=set)
    paid_messages: int = 0
    paid_amount: float = 0.0


class ChatWriter:
    def __init__(self, out_dir: Path, recording_start: datetime, chat_offset_s: float, seq: int):
        self.out_dir = out_dir
        self.recording_start = recording_start
        self.chat_offset_s = chat_offset_s
        self.seq = seq
        self._file: IO[str] | None = None
        self._file_seq: int | None = None
        self.total = 0
        # Messages stored before this process picked the recording up.
        self.base_total = 0
        self.minutes: dict[int, MinuteCounts] = defaultdict(MinuteCounts)
        self.dirty_minutes: set[int] = set()

    def write(self, msg: ChatMessage) -> None:
        line = msg.to_line(self.recording_start, self.chat_offset_s)
        if self._file is None or self._file_seq != self.seq:
            self._close()
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self._file = gzip.open(self.out_dir / chat_name(self.seq), "at", encoding="utf-8")
            self._file_seq = self.seq
        self._file.write(json.dumps(line, ensure_ascii=False) + "\n")
        if msg.kind == "gap":
            return
        self.total += 1
        minute = max(int(line["t"] // 60), 0)
        m = self.minutes[minute]
        m.messages += 1
        m.chatters.add(msg.user)
        if msg.kind == "paid":
            m.paid_messages += 1
            m.paid_amount += msg.amount or 0.0
        self.dirty_minutes.add(minute)

    def rollover(self, closed_seq: int) -> Path | None:
        """Video segment `closed_seq` closed. Returns the chat file to upload, if any messages went in it."""
        path = None
        if self._file is not None and self._file_seq == closed_seq:
            self._close()
            path = self.out_dir / chat_name(closed_seq)
        self.seq = closed_seq + 1
        return path

    def close(self) -> tuple[int, Path] | None:
        seq = self._file_seq
        had_file = self._file is not None
        self._close()
        if had_file and seq is not None:
            return seq, self.out_dir / chat_name(seq)
        return None

    def _close(self) -> None:
        if self._file is not None:
            self._file.close()
        self._file = None


class ChatLogger:
    def __init__(self, writer: ChatWriter, source: ChatSourceFactory, *, name: str):
        self.writer = writer
        self._source = source
        self._name = name
        self._task: asyncio.Task | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"chat-{self._name}")

    async def _run(self) -> None:
        delay = 2.0
        while True:
            try:
                async for msg in self._source():
                    self.writer.write(msg)
                    delay = 2.0
                log.info("chat %s: source ended, reconnecting", self._name)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — any source failure means reconnect
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("chat %s: %s", self._name, self.last_error)
            self.writer.write(ChatMessage(utcnow(), "", "chat connection lost; reconnecting", "gap"))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
