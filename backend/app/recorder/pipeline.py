"""One streamlink → ffmpeg process pair writing 5-minute MPEG-TS segments.

ffmpeg prints one CSV line to stdout ("seg_00012.ts,3600.000,3900.000") each time a segment
closes (`-segment_list pipe:1`). Those lines are the signal that a file is complete.
"""

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from app.recorder.procgroup import bind_to_parent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClosedSegment:
    seq: int
    path: Path
    start_s: float
    end_s: float


def parse_segment_line(line: str, out_dir: Path) -> ClosedSegment | None:
    parts = line.strip().split(",")
    if len(parts) < 3 or not parts[0].startswith("seg_"):
        return None
    try:
        seq = int(parts[0].removeprefix("seg_").split(".")[0])
        return ClosedSegment(seq, out_dir / parts[0], float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def streamlink_args(stream_url: str, quality: str, twitch: bool, cookies: dict[str, str] | None) -> list[str]:
    args = [
        sys.executable,
        "-m",
        "streamlink",
        "--stdout",
        "--loglevel",
        "warning",
        "--retry-streams",
        "5",
        "--retry-max",
        "10",
        "--retry-open",
        "3",
        "--stream-segment-threads",
        "2",
    ]
    if twitch:
        args += ["--twitch-disable-ads"]
    for k, v in (cookies or {}).items():
        args += ["--http-cookie", f"{k}={v}"]
    return [*args, stream_url, quality]


def ffmpeg_args(out_dir: Path, segment_seconds: int, start_number: int) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        "pipe:0",
        "-map",
        "0",
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-segment_start_number",
        str(start_number),
        "-reset_timestamps",
        "1",
        "-segment_list",
        "pipe:1",
        "-segment_list_type",
        "csv",
        "-segment_list_flags",
        "live",
        str(out_dir / "seg_%05d.ts"),
    ]


class Pipeline:
    def __init__(
        self,
        stream_url: str,
        out_dir: Path,
        *,
        quality: str,
        segment_seconds: int,
        start_number: int,
        twitch: bool,
        cookies: dict[str, str] | None = None,
    ):
        self.stream_url = stream_url
        self.out_dir = out_dir
        self.quality = quality
        self.segment_seconds = segment_seconds
        self.start_number = start_number
        self.twitch = twitch
        self.cookies = cookies
        # Tests replace streamlink with any command that writes MPEG-TS to stdout.
        self.source_args: list[str] | None = None
        self._streamlink: asyncio.subprocess.Process | None = None
        self._ffmpeg: asyncio.subprocess.Process | None = None
        self.stderr_tail: list[str] = []

    async def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        read_fd, write_fd = os.pipe()
        try:
            self._streamlink = await asyncio.create_subprocess_exec(
                *(
                    self.source_args
                    or streamlink_args(self.stream_url, self.quality, self.twitch, self.cookies)
                ),
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
            self._ffmpeg = await asyncio.create_subprocess_exec(
                *ffmpeg_args(self.out_dir, self.segment_seconds, self.start_number),
                stdin=read_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            os.close(read_fd)
            os.close(write_fd)
        for proc in (self._streamlink, self._ffmpeg):
            bind_to_parent(proc.pid)
        asyncio.create_task(self._drain(self._streamlink.stderr, "streamlink"))
        asyncio.create_task(self._drain(self._ffmpeg.stderr, "ffmpeg"))

    async def _drain(self, stream: asyncio.StreamReader | None, name: str) -> None:
        if stream is None:
            return
        async for raw in stream:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.stderr_tail = [*self.stderr_tail[-19:], f"{name}: {line}"]
                log.info("%s [%s] %s", name, self.out_dir.name, line)

    async def closed_segments(self) -> AsyncIterator[ClosedSegment]:
        assert self._ffmpeg is not None and self._ffmpeg.stdout is not None
        async for raw in self._ffmpeg.stdout:
            seg = parse_segment_line(raw.decode("utf-8", "replace"), self.out_dir)
            if seg is not None:
                yield seg

    async def wait(self) -> int:
        assert self._ffmpeg is not None and self._streamlink is not None
        code = await self._ffmpeg.wait()
        if self._streamlink.returncode is None:
            self._streamlink.terminate()
            await self._streamlink.wait()
        return code

    @property
    def running(self) -> bool:
        return self._ffmpeg is not None and self._ffmpeg.returncode is None

    async def stop(self, timeout: float = 20.0) -> None:
        """End the stream input; ffmpeg then closes the current segment and exits."""
        if self._streamlink is not None and self._streamlink.returncode is None:
            self._streamlink.terminate()
        if self._ffmpeg is None:
            return
        try:
            await asyncio.wait_for(self._ffmpeg.wait(), timeout)
        except TimeoutError:
            self._ffmpeg.kill()
            await self._ffmpeg.wait()
