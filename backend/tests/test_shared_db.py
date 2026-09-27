"""Running against a shared (remote) database: TLS settings, events across machines, viewer mode."""

import asyncio
import json
import ssl
import uuid

from app import db
from app.events import EventBus, EventRelay
from app.models import Channel, Recording
from app.util import utcnow


def test_ssl_modes():
    url, kw = db.split_ssl("postgresql+asyncpg://u:p@localhost:5433/recorder?ssl=disable")
    assert url == "postgresql+asyncpg://u:p@localhost:5433/recorder" and kw == {"ssl": False}
    # Remote hosts default to TLS without certificate checks (libpq's sslmode=require).
    url, kw = db.split_ssl("postgresql+asyncpg://u:p@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres")
    assert isinstance(kw["ssl"], ssl.SSLContext) and kw["ssl"].verify_mode == ssl.CERT_NONE
    _, kw = db.split_ssl("postgresql+asyncpg://u:p@db.example.com/x?sslmode=verify-full&application_name=r")
    assert kw["ssl"].verify_mode == ssl.CERT_REQUIRED and kw["ssl"].check_hostname
    assert db.split_ssl("postgresql+asyncpg://u:p@h/x?sslmode=require&a=b")[0].endswith("/x?a=b")
    # Local Postgres without an explicit setting: no TLS.
    assert db.split_ssl("postgresql+asyncpg://u:p@127.0.0.1/x")[1] == {"ssl": False}


async def _next(q, timeout=5.0):
    return await asyncio.wait_for(q.get(), timeout)


async def test_events_reach_other_machines(migrated_db):
    recorder_bus, viewer_bus = EventBus(), EventBus()
    recorder, viewer = EventRelay(recorder_bus, db.raw_connect), EventRelay(viewer_bus, db.raw_connect)
    recorder.start()
    viewer.start()
    try:
        await asyncio.wait_for(asyncio.gather(recorder.connected.wait(), viewer.connected.wait()), 10)
        async with recorder_bus.subscribe() as mine, viewer_bus.subscribe() as theirs:
            recorder_bus.publish("recording.updated", {"id": "r1", "title": "레이드"})
            event, data = await _next(theirs)
            assert event == "recording.updated" and json.loads(data) == {"id": "r1", "title": "레이드"}
            assert (await _next(mine))[0] == "recording.updated"
            # The recorder doesn't get its own event back through the database.
            await asyncio.sleep(0.5)
            assert mine.empty()

            recorder_bus.publish("health", {"tracked_count": 3})
            await _next(theirs)
            assert viewer_bus.remote_health == '{"tracked_count": 3}'

            # Oversized payloads stay local instead of failing the NOTIFY.
            recorder_bus.publish("recording.updated", {"blob": "x" * 9000})
            await asyncio.sleep(0.5)
            assert theirs.empty()
    finally:
        await recorder.stop()
        await viewer.stop()


async def test_viewer_cannot_stop_recordings(client, services, settings):
    settings.role = "viewer"
    async with services.sessions() as s:
        ch = Channel(platform="twitch", platform_id="x", url="https://www.twitch.tv/x", display_name="x")
        s.add(ch)
        await s.flush()
        rid = uuid.uuid4()
        s.add(
            Recording(
                id=rid,
                channel_id=ch.id,
                title="t",
                status="recording",
                started_at=utcnow(),
                gcs_prefix="archives/x/",
            )
        )
        await s.commit()
        channel_id = ch.id

    r = await client.post(f"/api/recordings/{rid}/stop")
    assert r.status_code == 409 and "recording PC" in r.json()["detail"]
    r = await client.delete(f"/api/channels/{channel_id}", params={"stop_recording": "true"})
    assert r.status_code == 409 and "recording PC" in r.json()["detail"]
    # Labelling still works from any machine.
    games = (await client.get("/api/games")).json()
    r = await client.patch(f"/api/recordings/{rid}", json={"game_id": games[0]["id"], "tier_id": None})
    assert r.status_code == 200
