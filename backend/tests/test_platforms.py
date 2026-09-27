"""Parsing of platform responses. Fixtures are trimmed copies of real response shapes."""

import json

import httpx
import pytest
import respx

from app.platforms.base import ChannelNotFound, ParsedUrl
from app.platforms.chzzk import ChzzkAdapter, parse_live_status
from app.platforms.twitch import TwitchAdapter, parse_stream
from app.platforms.youtube import parse_channel_page, parse_live_page


def test_twitch_parse_stream():
    s = parse_stream(
        {
            "id": "318442907113",
            "user_login": "raidcaller_jin",
            "type": "live",
            "title": "Kefka Ultimate prog — day 3",
            "game_name": "Final Fantasy XIV Online",
            "started_at": "2026-09-25T03:01:00Z",
        }
    )
    assert s.is_live and s.stream_id == "318442907113"
    assert s.category == "Final Fantasy XIV Online"
    assert s.started_at is not None and s.started_at.utcoffset().total_seconds() == 0


@respx.mock
async def test_twitch_check_batches_and_marks_missing_offline():
    respx.post("https://id.twitch.tv/oauth2/token").respond(json={"access_token": "t", "expires_in": 3600})
    route = respx.get("https://api.twitch.tv/helix/streams").respond(
        json={"data": [{"id": "1", "user_login": "a", "type": "live", "title": "x"}]}
    )
    async with httpx.AsyncClient() as client:
        result = await TwitchAdapter(client, "id", "secret").check(["a", "b"])
    assert result["a"].is_live and not result["b"].is_live
    assert route.calls.last.request.url.params.get_list("user_login") == ["a", "b"]


@respx.mock
async def test_twitch_resolve_unknown_login():
    respx.post("https://id.twitch.tv/oauth2/token").respond(json={"access_token": "t", "expires_in": 3600})
    respx.get("https://api.twitch.tv/helix/users").respond(json={"data": []})
    async with httpx.AsyncClient() as client:
        with pytest.raises(ChannelNotFound):
            await TwitchAdapter(client, "id", "secret").resolve(ParsedUrl("twitch", "nobody_here"))


def test_chzzk_live_status_open_and_close():
    s = parse_live_status(
        {
            "status": "OPEN",
            "liveId": 1234567,
            "liveTitle": "레이드 클리어 방송",
            "openDate": "2026-09-25 12:01:00",
            "chatChannelId": "N1abcd",
            "liveCategoryValue": "World of Warcraft",
        }
    )
    assert s.is_live and s.stream_id == "1234567" and s.chat_channel_id == "N1abcd"
    assert s.started_at is not None and s.started_at.utcoffset().total_seconds() == 9 * 3600
    assert not parse_live_status({"status": "CLOSE"}).is_live


@respx.mock
async def test_chzzk_check_skips_channels_that_error():
    respx.get(url__regex=r".*/polling/v2/channels/good/live-status").respond(
        json={"code": 200, "content": {"status": "CLOSE"}}
    )
    respx.get(url__regex=r".*/polling/v2/channels/bad/live-status").respond(status_code=500)
    async with httpx.AsyncClient() as client:
        result = await ChzzkAdapter(client).check(["good", "bad"])
    assert set(result) == {"good"}


def _watch_page(live: bool, upcoming: bool = False) -> str:
    player = {
        "videoDetails": {"title": "Patch 8.1 first look", "isLive": live, "isUpcoming": upcoming},
        "microformat": {
            "playerMicroformatRenderer": {
                "liveBroadcastDetails": {"isLiveNow": live, "startTimestamp": "2026-09-25T10:00:00+00:00"}
            }
        },
    }
    return (
        '<html><head><link rel="canonical" href="https://www.youtube.com/watch?v=abcdefghijk">'
        f"<script>var ytInitialPlayerResponse = {json.dumps(player)};var meta = 1;</script></head></html>"
    )


def test_youtube_live_page():
    s = parse_live_page(_watch_page(live=True))
    assert s.is_live and s.stream_id == "abcdefghijk" and s.title == "Patch 8.1 first look"


def test_youtube_upcoming_or_channel_page_is_offline():
    assert not parse_live_page(_watch_page(live=False, upcoming=True)).is_live
    assert not parse_live_page('<link rel="canonical" href="https://www.youtube.com/channel/UCx">').is_live


def test_youtube_channel_page_ignores_other_channels_mentioned_first():
    page = (
        '<script>{"channelId":"UCaaaaaaaaaaaaaaaaaaaaaa"}</script>'
        '<link rel="canonical" href="https://www.youtube.com/channel/UCSJ4gkVC6NrvII8umztf0Ow">'
    )
    info = parse_channel_page(page)
    assert info is not None and info.platform_id == "UCSJ4gkVC6NrvII8umztf0Ow"


def test_youtube_channel_page():
    page = (
        '<meta property="og:title" content="Aether &amp; Watch">'
        '<meta property="og:image" content="https://yt3.ggpht.com/abc">'
        '<script>{"externalId":"UC1234567890abcdefghijkl"}</script>'
    )
    info = parse_channel_page(page)
    assert info is not None
    assert info.platform_id == "UC1234567890abcdefghijkl" and info.display_name == "Aether & Watch"
    assert info.url == "https://www.youtube.com/channel/UC1234567890abcdefghijkl"


async def test_twitch_without_credentials_says_what_to_set():
    from app.platforms.base import NotConfigured

    async with httpx.AsyncClient() as client:
        with pytest.raises(NotConfigured, match="TWITCH_CLIENT_ID"):
            await TwitchAdapter(client, "", "").check(["a"])
