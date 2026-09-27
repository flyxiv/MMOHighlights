import json
import uuid
from datetime import UTC, datetime

from app.archive import UploadedVideo, build_manifest, build_playlist, console_url, recording_prefix


def test_recording_prefix_under_archives():
    rid = uuid.UUID("9f2c41e0-0000-4000-8000-000000000000")
    p = recording_prefix("archives/", "twitch", "raidcaller_jin", datetime(2026, 9, 25, tzinfo=UTC), rid)
    assert p == f"archives/twitch/raidcaller_jin/2026-09-25/{rid}/"
    assert console_url("mmohighlights", p).startswith(
        "https://console.cloud.google.com/storage/browser/mmohighlights/archives/twitch/"
    )


def test_playlist_event_then_vod_with_gap():
    segs = [UploadedVideo(0, 0, 300, 1), UploadedVideo(1, 300, 600.5, 1), UploadedVideo(3, 1200, 1500, 1)]
    live = build_playlist(segs, finished=False)
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in live and "#EXT-X-ENDLIST" not in live
    done = build_playlist(segs, finished=True)
    assert done.endswith("#EXT-X-ENDLIST\n")
    assert "#EXT-X-TARGETDURATION:301" in done
    # seq 2 is missing (lost), so the player must be told about the discontinuity
    assert done.index("#EXT-X-DISCONTINUITY") < done.index("seg_00003.ts")


def test_manifest_lists_files_and_labels():
    body = json.loads(
        build_manifest(
            {"title": "레이드", "game": "WoW", "tier": "Curse of U'latek"},
            [UploadedVideo(0, 0, 300, 10)],
            [0],
        )
    )
    assert body["title"] == "레이드" and body["tier"] == "Curse of U'latek"
    assert body["segments"][0]["file"] == "seg_00000.ts"
    assert body["chat_files"] == ["chat_00000.jsonl.gz"]


def test_prefix_keeps_youtube_channel_id_case():
    p = recording_prefix(
        "archives/", "youtube", "UCSJ4gkVC6NrvII8umztf0Ow", datetime(2026, 9, 25, tzinfo=UTC), "r"
    )
    assert "/UCSJ4gkVC6NrvII8umztf0Ow/" in p
