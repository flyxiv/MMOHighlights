"""A channel goes live, gets recorded (video + chat), goes offline, and ends up completed in the bucket.

streamlink is replaced by ffmpeg generating a 13-second test stream, and the platform by a fake.
"""

import asyncio
import gzip
import json
import shutil
import time
import uuid

import pytest

from app.chat.models import ChatMessage
from app.models import Recording
from app.platforms.base import LiveStatus
from app.recorder.pipeline import Pipeline
from app.util import utcnow

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_stream_pipeline(*args, **kwargs) -> Pipeline:
    p = Pipeline(*args, **kwargs)
    p.source_args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
        "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "13", "-c:v", "libx264", "-g", "10", "-c:a", "aac",
        "-flush_packets", "1", "-f", "mpegts", "pipe:1",
    ]  # fmt: skip
    return p


test_stream_pipeline.__test__ = False  # not a test itself


async def fake_chat():
    i = 0
    while True:
        i += 1
        yield ChatMessage(
            utcnow(), f"viewer{i % 7}", f"gg {i}", "paid" if i % 10 == 0 else "message", amount=100
        )
        await asyncio.sleep(0.2)


async def wait_for(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}")


async def test_live_to_completed(client, platforms, services, settings, monkeypatch):
    sup, poller, uploader = services.supervisor, services.poller, services.uploader
    settings.grace_period_s = 1
    sup.make_pipeline = test_stream_pipeline
    monkeypatch.setattr(sup, "_chat_source", lambda platform, pid, status: fake_chat)

    platforms.twitch.known["raidcaller_jin"] = "raidcaller_jin"
    await client.post("/api/channels", json={"url": "twitch.tv/raidcaller_jin"})
    games = {g["name"]: g for g in (await client.get("/api/games")).json()}

    platforms.twitch.live["raidcaller_jin"] = LiveStatus(
        True, stream_id="s1", title="Kefka Ultimate prog — day 3", category="Final Fantasy XIV Online"
    )
    await poller.tick()
    active = (await client.get("/api/recordings", params={"status": "active"})).json()
    assert active["total"] == 1
    rid = active["items"][0]["id"]
    assert active["items"][0]["status"] == "recording"
    channel = (await client.get("/api/channels")).json()[0]
    assert channel["status"] == "live" and channel["active_recording_id"] == rid

    # Label it while it records.
    kefka = next(t for t in games["FFXIV"]["tiers"] if t["name"] == "Kefka Ultimate")
    await client.patch(f"/api/recordings/{rid}", json={"game_id": None, "tier_id": kefka["id"]})

    await uploader.start()
    try:
        # Segments upload while the stream is still going.
        async def some_uploaded():
            r = (await client.get(f"/api/recordings/{rid}")).json()
            return r["segments_uploaded"] >= 2 and r["status"] == "recording"

        await wait_for(some_uploaded, 15, "uploads during the stream")

        # The test stream ends by itself after 13 s; the platform then reports offline.
        await asyncio.wait_for(sup.active[uuid.UUID(rid)].pipeline_task, 20)
        platforms.twitch.live.pop("raidcaller_jin")
        await poller.tick()  # first offline poll: not trusted yet
        assert (await client.get(f"/api/recordings/{rid}")).json()["status"] == "recording"
        await poller.tick()  # second: ending, and the grace period starts
        assert (await client.get(f"/api/recordings/{rid}")).json()["status"] == "ending"
        await asyncio.sleep(1.1)
        await poller.tick()  # grace period over: finalize

        async def completed():
            return (await client.get(f"/api/recordings/{rid}")).json()["status"] == "completed"

        await wait_for(completed, 20, "the recording to complete")
    finally:
        await uploader.stop()

    detail = (await client.get(f"/api/recordings/{rid}")).json()
    videos = [s for s in detail["segments"] if s["kind"] == "video"]
    chats = [s for s in detail["segments"] if s["kind"] == "chat"]
    assert len(videos) >= 6 and all(s["status"] == "uploaded" for s in detail["segments"])
    assert chats, "chat files should be uploaded next to the video"
    assert detail["segments_closed"] == detail["segments_uploaded"] == len(videos)
    assert detail["chat_messages"] > 20 and sum(m["messages"] for m in detail["chat_minutes"]) > 20
    assert detail["gcs_uri"].startswith("gs://mmohighlights/archives/twitch/raidcaller_jin/")

    # Files landed in the (local stand-in for the) bucket, and the spool is empty.
    folder = (
        settings.local_storage_dir / "mmohighlights" / detail["gcs_uri"].removeprefix("gs://mmohighlights/")
    )
    assert sorted(p.name for p in folder.glob("seg_*.ts")) == [
        f"seg_{s['seq']:05d}.ts" for s in sorted(videos, key=lambda s: s["seq"])
    ]
    playlist = (folder / "index.m3u8").read_text()
    assert playlist.rstrip().endswith("#EXT-X-ENDLIST")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert (
        manifest["status"] == "completed"
        and manifest["tier"] == "Kefka Ultimate"
        and manifest["game"] == "FFXIV"
    )
    with gzip.open(next(folder.glob("chat_*.jsonl.gz")), "rt", encoding="utf-8") as f:
        first = json.loads(f.readline())
    assert first["user"].startswith("viewer") and first["t"] >= settings.chat_offset_twitch_s
    assert not list((settings.spool_dir / rid).glob("seg_*.ts"))

    channel = (await client.get("/api/channels")).json()[0]
    assert channel["status"] == "offline" and channel["last_live_ended_at"] is not None
    assert channel["active_recording_id"] is None

    # The channel remembers the labels for its next broadcast.
    platforms.twitch.live["raidcaller_jin"] = LiveStatus(True, stream_id="s2", title="day 4")
    sup.make_pipeline = test_stream_pipeline
    await poller.tick()
    async with services.sessions() as s:
        newest = (await s.execute(Recording.__table__.select().where(Recording.status == "recording"))).one()
    assert newest.tier_id == kefka["id"] and newest.labels_source == "channel_default"
    await sup.stop_manually(newest.id)
