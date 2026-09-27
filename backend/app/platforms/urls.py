import re
from urllib.parse import urlparse

from app.platforms.base import ParsedUrl, UnsupportedUrl

_TWITCH_LOGIN = re.compile(r"^[a-zA-Z0-9_]{3,25}$")
_TWITCH_RESERVED = {"directory", "videos", "settings", "subscriptions", "inventory", "wallet", "p", "search"}
_YT_CHANNEL_ID = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")
_YT_HANDLE = re.compile(r"^@[\w.\-·]{3,30}$")
_CHZZK_ID = re.compile(r"^[0-9a-f]{32}$")

SUPPORTED_HINT = (
    "Only Twitch, YouTube and Chzzk channel URLs are supported. Examples: twitch.tv/name, "
    "youtube.com/@handle, chzzk.naver.com/<channel id>"
)


def parse_channel_url(raw: str) -> ParsedUrl:
    text = raw.strip()
    if not text:
        raise UnsupportedUrl("Paste a channel URL.")
    if "://" not in text:
        text = "https://" + text
    u = urlparse(text)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    parts = [p for p in u.path.split("/") if p]

    if host == "twitch.tv":
        if parts and _TWITCH_LOGIN.match(parts[0]) and parts[0].lower() not in _TWITCH_RESERVED:
            return ParsedUrl("twitch", parts[0].lower())
        raise UnsupportedUrl("That Twitch URL doesn't point to a channel. Use twitch.tv/<name>.")

    if host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com"):
        if parts and parts[0].startswith("@") and _YT_HANDLE.match(parts[0]):
            return ParsedUrl("youtube", parts[0])
        if len(parts) >= 2 and parts[0] == "channel" and _YT_CHANNEL_ID.match(parts[1]):
            return ParsedUrl("youtube", parts[1])
        raise UnsupportedUrl(
            "That YouTube URL doesn't point to a channel. Use youtube.com/@handle or youtube.com/channel/UC…"
        )

    if host == "chzzk.naver.com":
        candidates = parts[1:2] if parts[:1] == ["live"] else parts[:1]
        if candidates and _CHZZK_ID.match(candidates[0]):
            return ParsedUrl("chzzk", candidates[0])
        raise UnsupportedUrl("That Chzzk URL doesn't point to a channel. Use chzzk.naver.com/<channel id>.")

    raise UnsupportedUrl(SUPPORTED_HINT)


def canonical_url(platform: str, platform_id: str) -> str:
    if platform == "twitch":
        return f"https://www.twitch.tv/{platform_id}"
    if platform == "youtube":
        return f"https://www.youtube.com/channel/{platform_id}"
    if platform == "chzzk":
        return f"https://chzzk.naver.com/{platform_id}"
    raise ValueError(platform)
