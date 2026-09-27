import shutil
import time
from pathlib import Path

import pytest

from app.recorder.pipeline import Pipeline, ffmpeg_args, parse_segment_line, streamlink_args


def test_parse_segment_line():
    seg = parse_segment_line("seg_00012.ts,3600.000000,3900.000000\n", Path("/spool/r"))
    assert seg is not None
    assert seg.seq == 12 and seg.start_s == 3600.0 and seg.end_s == 3900.0
    assert seg.path == Path("/spool/r/seg_00012.ts")
    assert parse_segment_line("garbage", Path(".")) is None
    assert parse_segment_line("seg_x.ts,1,2", Path(".")) is None


def test_streamlink_args_quality_and_twitch_flags():
    args = streamlink_args(
        "https://www.twitch.tv/x", "1080p60,1080p,best", twitch=True, cookies={"NID_AUT": "a"}
    )
    assert args[-2:] == ["https://www.twitch.tv/x", "1080p60,1080p,best"]
    assert "--twitch-disable-ads" in args
    assert "--http-cookie" in args and "NID_AUT=a" in args


def test_ffmpeg_args_write_segment_list_to_stdout():
    args = ffmpeg_args(Path("out"), 300, 7)
    assert args[args.index("-segment_list") + 1] == "pipe:1"
    assert args[args.index("-segment_start_number") + 1] == "7"
    assert "-c" in args and args[args.index("-c") + 1] == "copy"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_ffmpeg_reports_each_segment_as_it_closes(tmp_path: Path):
    """The recorder relies on ffmpeg printing a list line per closed segment, before exiting."""
    p = Pipeline("unused", tmp_path, quality="best", segment_seconds=2, start_number=5, twitch=False)
    p.source_args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
        "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "13", "-c:v", "libx264", "-g", "10", "-c:a", "aac",
        "-flush_packets", "1", "-f", "mpegts", "pipe:1",
    ]  # fmt: skip
    await p.start()
    closed, arrived = [], []
    async for s in p.closed_segments():
        closed.append(s)
        arrived.append(time.monotonic())
    assert await p.wait() == 0
    assert [s.seq for s in closed] == list(range(5, 12))
    assert all(s.path.exists() and s.path.stat().st_size > 0 for s in closed)
    # Segments cut on keyframes, so boundaries land near (not exactly on) 2 s.
    assert closed[1].start_s == pytest.approx(2.0, abs=0.5)
    # ffmpeg first analyses ~5 s of input, then reports each segment as it closes, in real time
    # (-re), rather than all at once on exit.
    later = arrived[3:]
    assert later[-1] - later[0] > 3
