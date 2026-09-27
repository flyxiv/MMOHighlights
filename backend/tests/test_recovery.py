import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.models import Channel, Recording, Segment
from app.recorder.supervisor import reconcile_on_startup
from app.util import utcnow


async def _setup(services, status="recording"):
    async with services.sessions() as s:
        ch = Channel(platform="twitch", platform_id="x", url="https://www.twitch.tv/x", display_name="x")
        s.add(ch)
        await s.flush()
        rec = Recording(
            id=uuid.uuid4(),
            channel_id=ch.id,
            title="t",
            status=status,
            started_at=utcnow(),
            gcs_prefix="archives/twitch/x/2026-09-25/r/",
        )
        s.add(rec)
        await s.commit()
        return rec.id


async def test_restart_recovers_recordings_and_orphan_files(services, settings):
    rid = await _setup(services)
    spool: Path = settings.spool_dir / str(rid)
    spool.mkdir(parents=True)
    (spool / "seg_00000.ts").write_bytes(b"x" * 10)
    (spool / "chat_00000.jsonl.gz").write_bytes(b"y")
    (spool / "seg_00001.ts").write_bytes(b"")  # empty: ffmpeg never wrote to it
    async with services.sessions() as s:
        s.add(Segment(recording_id=rid, kind="video", seq=5, local_path="p", status="uploading"))
        await s.commit()

    await reconcile_on_startup(services.sessions, settings.spool_dir)

    async with services.sessions() as s:
        rec = await s.get(Recording, rid)
        segs = {(x.kind, x.seq): x.status for x in (await s.execute(select(Segment))).scalars()}
    assert rec.status == "ending" and rec.ending_since is not None
    assert segs == {("video", 5): "pending", ("video", 0): "pending", ("chat", 0): "pending"}


async def test_sweep_deletes_only_uploaded_files(services, settings):
    rid = await _setup(services, status="finalizing")
    d = settings.spool_dir / str(rid)
    d.mkdir(parents=True)
    done, waiting = d / "seg_00000.ts", d / "seg_00001.ts"
    done.write_bytes(b"x")
    waiting.write_bytes(b"x")
    async with services.sessions() as s:
        s.add(Segment(recording_id=rid, kind="video", seq=0, local_path=str(done), status="uploaded"))
        s.add(Segment(recording_id=rid, kind="video", seq=1, local_path=str(waiting), status="pending"))
        await s.commit()
    assert await services.uploader.sweep_spool() == 1
    assert not done.exists() and waiting.exists()


class DefaultCredentialsError(Exception):
    """Same name as google.auth's; the uploader matches on the name."""


class NoCredentialsStorage:
    async def upload_file(self, local, name, content_type):
        raise DefaultCredentialsError("Your default credentials were not found.")

    async def upload_text(self, data, name, content_type):
        pass


async def test_missing_credentials_do_not_use_up_attempts(services, settings):
    rid = await _setup(services, status="finalizing")
    f = settings.spool_dir / str(rid) / "seg_00000.ts"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    async with services.sessions() as s:
        s.add(Segment(recording_id=rid, kind="video", seq=0, local_path=str(f), size_bytes=1, attempts=19))
        await s.commit()
    services.uploader.storage = NoCredentialsStorage()

    assert await services.uploader.process_one() is True
    async with services.sessions() as s:
        seg = (await s.execute(select(Segment))).scalar_one()
    # One more failure would have been its 20th and final attempt; credentials errors don't count.
    assert seg.status == "pending" and seg.attempts == 19
    assert seg.next_attempt_at > utcnow() + timedelta(minutes=4)


class FlakyStorage:
    def __init__(self):
        self.calls = 0

    async def upload_file(self, local, name, content_type):
        self.calls += 1
        raise ConnectionError("network down")

    async def upload_text(self, data, name, content_type):
        pass


async def test_failed_upload_is_retried_later(services, settings):
    rid = await _setup(services, status="finalizing")
    f = settings.spool_dir / str(rid) / "seg_00000.ts"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    async with services.sessions() as s:
        s.add(Segment(recording_id=rid, kind="video", seq=0, local_path=str(f), size_bytes=1))
        await s.commit()
    services.uploader.storage = FlakyStorage()

    assert await services.uploader.process_one() is True
    async with services.sessions() as s:
        seg = (await s.execute(select(Segment))).scalar_one()
    assert seg.status == "pending" and seg.attempts == 1 and "network down" in seg.last_error
    assert seg.next_attempt_at > utcnow() + timedelta(seconds=5)
    assert f.exists()  # kept for the retry
    # Not claimable again until the backoff passes.
    assert await services.uploader.process_one() is False
