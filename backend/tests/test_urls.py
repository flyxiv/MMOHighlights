import pytest

from app.platforms.base import ParsedUrl, UnsupportedUrl
from app.platforms.urls import canonical_url, parse_channel_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.twitch.tv/RaidCaller_Jin", ParsedUrl("twitch", "raidcaller_jin")),
        ("twitch.tv/raidcaller_jin/videos", ParsedUrl("twitch", "raidcaller_jin")),
        ("https://m.twitch.tv/healbot_sora?x=1", ParsedUrl("twitch", "healbot_sora")),
        ("https://www.youtube.com/@aetherwatch", ParsedUrl("youtube", "@aetherwatch")),
        ("https://youtube.com/@aetherwatch/streams", ParsedUrl("youtube", "@aetherwatch")),
        (
            "https://www.youtube.com/channel/UC1234567890abcdefghijkl",
            ParsedUrl("youtube", "UC1234567890abcdefghijkl"),
        ),
        (
            "https://chzzk.naver.com/8a1f3c9e0b7d4e2fa6c1d0e9b8a7f6e5",
            ParsedUrl("chzzk", "8a1f3c9e0b7d4e2fa6c1d0e9b8a7f6e5"),
        ),
        (
            "chzzk.naver.com/live/8a1f3c9e0b7d4e2fa6c1d0e9b8a7f6e5",
            ParsedUrl("chzzk", "8a1f3c9e0b7d4e2fa6c1d0e9b8a7f6e5"),
        ),
    ],
)
def test_parse_supported(url, expected):
    assert parse_channel_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://kick.com/raidcaller_jin",
        "https://www.twitch.tv/directory",
        "https://www.twitch.tv/",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://chzzk.naver.com/not-a-channel",
    ],
)
def test_parse_rejects(url):
    with pytest.raises(UnsupportedUrl):
        parse_channel_url(url)


def test_unsupported_site_message_names_the_platforms():
    with pytest.raises(UnsupportedUrl, match="Only Twitch, YouTube and Chzzk"):
        parse_channel_url("https://kick.com/x")


def test_canonical_url():
    assert canonical_url("twitch", "abc") == "https://www.twitch.tv/abc"
    assert canonical_url("chzzk", "f" * 32) == f"https://chzzk.naver.com/{'f' * 32}"
