"""YouTube live detection without spending API quota.

Each check loads youtube.com/channel/<id>/live. When the channel is live that page is the
watch page of the live video; otherwise it's the channel page or an upcoming stream. If a
YouTube API key is configured, a live result is confirmed with videos.list (1 quota unit).
"""

import asyncio
import html
import json
import re
from datetime import datetime

import httpx

from app.platforms.base import ChannelInfo, ChannelNotFound, LiveStatus, ParsedUrl, PlatformError
from app.platforms.urls import canonical_url

# Skips the EU cookie consent interstitial.
CONSENT_COOKIES = {"SOCS": "CAI", "CONSENT": "YES+"}

_CANONICAL = re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"')
# In order of reliability. A bare "channelId" is not used: channel pages mention other channels too.
_CHANNEL_ID_PATTERNS = (
    re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"'),
    re.compile(r'<meta itemprop="identifier" content="(UC[\w-]{22})"'),
    re.compile(r'"externalId":"(UC[\w-]{22})"'),
)
_OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
_OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]*)"')
_PLAYER = re.compile(r"ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;\s*(?:var|</script>)", re.S)


class YouTubeAdapter:
    platform = "youtube"

    def __init__(self, client: httpx.AsyncClient, api_key: str = ""):
        self._client = client
        self._api_key = api_key

    async def _page(self, url: str) -> str:
        r = await self._client.get(url, cookies=CONSENT_COOKIES)
        if r.status_code == 404:
            raise ChannelNotFound("No YouTube channel at that URL.")
        if r.status_code != 200:
            raise PlatformError(f"YouTube returned {r.status_code}.")
        return r.text

    async def resolve(self, parsed: ParsedUrl) -> ChannelInfo:
        path = parsed.key if parsed.key.startswith("@") else f"channel/{parsed.key}"
        page = await self._page(f"https://www.youtube.com/{path}")
        info = parse_channel_page(page)
        if info is None:
            raise ChannelNotFound("No YouTube channel at that URL.")
        return info

    async def live_status(self, channel_id: str) -> LiveStatus:
        page = await self._page(f"https://www.youtube.com/channel/{channel_id}/live")
        status = parse_live_page(page)
        if status.is_live and self._api_key and status.stream_id:
            status = await self._confirm(status)
        return status

    async def _confirm(self, status: LiveStatus) -> LiveStatus:
        r = await self._client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,liveStreamingDetails", "id": status.stream_id, "key": self._api_key},
        )
        if r.status_code != 200:
            return status  # keep the page result; the API is only a cross-check
        items = r.json().get("items") or []
        if not items or items[0]["snippet"].get("liveBroadcastContent") != "live":
            return LiveStatus(is_live=False)
        started = items[0].get("liveStreamingDetails", {}).get("actualStartTime")
        return LiveStatus(
            is_live=True,
            stream_id=status.stream_id,
            title=items[0]["snippet"].get("title") or status.title,
            started_at=datetime.fromisoformat(started.replace("Z", "+00:00"))
            if started
            else status.started_at,
        )

    async def check(self, platform_ids: list[str]) -> dict[str, LiveStatus]:
        sem = asyncio.Semaphore(4)

        async def one(pid: str) -> tuple[str, LiveStatus | None]:
            async with sem:
                try:
                    return pid, await self.live_status(pid)
                except (PlatformError, ChannelNotFound, httpx.HTTPError):
                    return pid, None

        results = await asyncio.gather(*(one(pid) for pid in platform_ids))
        return {pid: s for pid, s in results if s is not None}

    def stream_url(self, platform_id: str) -> str:
        return f"https://www.youtube.com/channel/{platform_id}/live"


def parse_channel_page(page: str) -> ChannelInfo | None:
    cid = next((m.group(1) for p in _CHANNEL_ID_PATTERNS if (m := p.search(page))), None)
    if cid is None:
        return None
    title = _OG_TITLE.search(page)
    image = _OG_IMAGE.search(page)
    return ChannelInfo(
        platform="youtube",
        platform_id=cid,
        display_name=html.unescape(title.group(1)) if title else cid,
        url=canonical_url("youtube", cid),
        thumbnail_url=html.unescape(image.group(1)) if image else None,
    )


def parse_live_page(page: str) -> LiveStatus:
    video = _CANONICAL.search(page)
    if not video:
        return LiveStatus(is_live=False)
    player = _extract_player(page)
    details = (player.get("microformat", {}).get("playerMicroformatRenderer", {}) or {}).get(
        "liveBroadcastDetails"
    ) or {}
    video_details = player.get("videoDetails", {}) or {}
    is_live = bool(details.get("isLiveNow")) or (
        bool(video_details.get("isLive")) and not video_details.get("isUpcoming")
    )
    if not is_live:
        return LiveStatus(is_live=False)
    started = details.get("startTimestamp")
    return LiveStatus(
        is_live=True,
        stream_id=video.group(1),
        title=video_details.get("title"),
        started_at=datetime.fromisoformat(started) if started else None,
    )


def _extract_player(page: str) -> dict:
    m = _PLAYER.search(page)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
