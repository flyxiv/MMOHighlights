import uuid
from datetime import timedelta

from app.models import Channel, Recording
from app.util import utcnow


async def add(client, platforms, platform="twitch", key="raidcaller_jin", name="raidcaller_jin"):
    platforms.get(platform).known[key] = name
    url = {"twitch": f"twitch.tv/{key}", "chzzk": f"chzzk.naver.com/{key}", "youtube": f"youtube.com/@{key}"}[
        platform
    ]
    return await client.post("/api/channels", json={"url": url})


async def test_add_list_remove_channel(client, platforms):
    r = await add(client, platforms)
    assert r.status_code == 201, r.text
    ch = r.json()
    assert ch["display_name"] == "raidcaller_jin" and ch["status"] == "offline"
    assert ch["active_recording_id"] is None

    assert (await add(client, platforms)).status_code == 409
    assert [c["id"] for c in (await client.get("/api/channels")).json()] == [ch["id"]]

    assert (await client.delete(f"/api/channels/{ch['id']}")).status_code == 204
    assert (await client.get("/api/channels")).json() == []

    # Adding it back restores the same channel (its old recordings keep pointing at it).
    again = await add(client, platforms)
    assert again.status_code == 201 and again.json()["id"] == ch["id"]


async def test_add_channel_errors_are_readable(client, platforms):
    r = await client.post("/api/channels", json={"url": "https://kick.com/raidcaller_jin"})
    assert r.status_code == 422 and "Only Twitch, YouTube and Chzzk" in r.json()["detail"]
    r = await client.post("/api/channels", json={"url": "twitch.tv/nobody_here"})
    assert r.status_code == 422 and "nobody_here" in r.json()["detail"]


async def test_channel_limit(client, platforms, settings):
    settings.max_channels = 2
    for i in range(2):
        assert (await add(client, platforms, key=f"ch_{i}", name=f"ch_{i}")).status_code == 201
    r = await add(client, platforms, key="ch_x", name="ch_x")
    assert r.status_code == 422 and "limit" in r.json()["detail"]


async def _recording(services, channel_id, status="completed", days_ago=0, **kw):
    async with services.sessions() as s:
        rec = Recording(
            id=uuid.uuid4(),
            channel_id=channel_id,
            title=kw.pop("title", "Kefka Ultimate prog — day 2"),
            status=status,
            started_at=utcnow() - timedelta(days=days_ago, hours=5),
            ended_at=utcnow() - timedelta(days=days_ago),
            gcs_prefix="archives/twitch/x/2026-09-25/r/",
            **kw,
        )
        s.add(rec)
        await s.commit()
        return rec.id


async def test_labels_and_filters(client, platforms, services):
    ch = (await add(client, platforms)).json()
    games = {g["name"]: g for g in (await client.get("/api/games")).json()}
    ffxiv, wow = games["FFXIV"], games["WoW"]
    kefka = next(t for t in ffxiv["tiers"] if t["name"] == "Kefka Ultimate")

    rid = await _recording(services, uuid.UUID(ch["id"]))
    other = await _recording(services, uuid.UUID(ch["id"]), days_ago=2, title="Raid night")

    # Tier alone implies its game.
    r = await client.patch(f"/api/recordings/{rid}", json={"game_id": None, "tier_id": kefka["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["game"]["name"] == "FFXIV" and body["tier"]["name"] == "Kefka Ultimate"
    assert body["labels_source"] == "manual"

    # The channel now pre-fills FFXIV / Kefka Ultimate for its next recording.
    chan = (await client.get("/api/channels")).json()[0]
    assert chan["default_game"]["name"] == "FFXIV" and chan["default_tier"]["name"] == "Kefka Ultimate"

    r = await client.patch(f"/api/recordings/{other}", json={"game_id": wow["id"], "tier_id": kefka["id"]})
    assert r.status_code == 422 and "different game" in r.json()["detail"]

    page = (
        await client.get("/api/recordings", params={"status": "completed", "game_id": ffxiv["id"]})
    ).json()
    assert page["total"] == 1 and page["items"][0]["id"] == str(rid)
    all_done = (await client.get("/api/recordings", params={"status": "completed", "page_size": 1})).json()
    assert all_done["total"] == 2 and len(all_done["items"]) == 1
    assert all_done["items"][0]["title"] == "Kefka Ultimate prog — day 2"  # newest first

    new_tier = await client.post("/api/tiers", json={"game_id": wow["id"], "name": "Manaforge Omega"})
    assert new_tier.status_code == 201
    dup = await client.post("/api/tiers", json={"game_id": wow["id"], "name": "Manaforge Omega"})
    assert dup.status_code == 409
    archived = await client.patch(f"/api/tiers/{new_tier.json()['id']}", json={"archived": True})
    assert archived.json()["archived"] is True


async def test_remove_recording_channel_needs_confirmation(client, platforms, services):
    ch = (await add(client, platforms)).json()
    await _recording(services, uuid.UUID(ch["id"]), status="ending", ending_since=utcnow())
    r = await client.delete(f"/api/channels/{ch['id']}")
    assert r.status_code == 409 and "is recording" in r.json()["detail"]
    r = await client.delete(f"/api/channels/{ch['id']}", params={"stop_recording": "true"})
    assert r.status_code == 204
    # The recording survives the channel's removal.
    done = (await client.get("/api/recordings", params={"status": "completed"})).json()
    assert done["total"] == 1 and done["items"][0]["status"] == "failed"  # no video was captured
    async with services.sessions() as s:
        assert (await s.get(Channel, uuid.UUID(ch["id"]))).deleted_at is not None


async def test_health(client):
    h = (await client.get("/api/health")).json()
    assert h["tracked_count"] == 0 and h["max_channels"] == 10 and h["upload_backlog"] == 0
