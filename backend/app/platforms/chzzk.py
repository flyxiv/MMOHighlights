"""Chzzk uses unofficial endpoints (the same ones its web player and streamlink use)."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.platforms.base import ChannelInfo, ChannelNotFound, LiveStatus, ParsedUrl, PlatformError
from app.platforms.urls import canonical_url

API = "https://api.chzzk.naver.com"
KST = timezone(timedelta(hours=9), "KST")  # Korea has no daylight saving time


class ChzzkAdapter:
    platform = "chzzk"

    def __init__(self, client: httpx.AsyncClient, nid_aut: str = "", nid_ses: str = ""):
        self._client = client
        self._cookies = {"NID_AUT": nid_aut, "NID_SES": nid_ses} if nid_aut and nid_ses else None

    async def _get(self, path: str) -> dict:
        r = await self._client.get(f"{API}{path}", cookies=self._cookies)
        if r.status_code == 404:
            raise ChannelNotFound("No Chzzk channel with that id.")
        if r.status_code != 200:
            raise PlatformError(f"Chzzk {path} returned {r.status_code}.")
        body = r.json()
        if body.get("code") not in (200, None):
            raise PlatformError(f"Chzzk {path} returned code {body.get('code')}.")
        return body.get("content") or {}

    async def resolve(self, parsed: ParsedUrl) -> ChannelInfo:
        c = await self._get(f"/service/v1/channels/{parsed.key}")
        if not c.get("channelId"):
            raise ChannelNotFound("No Chzzk channel with that id.")
        return ChannelInfo(
            platform="chzzk",
            platform_id=c["channelId"],
            display_name=c.get("channelName") or c["channelId"],
            url=canonical_url("chzzk", c["channelId"]),
            thumbnail_url=c.get("channelImageUrl") or None,
        )

    async def live_status(self, channel_id: str) -> LiveStatus:
        return parse_live_status(await self._get(f"/polling/v2/channels/{channel_id}/live-status"))

    async def check(self, platform_ids: list[str]) -> dict[str, LiveStatus]:
        sem = asyncio.Semaphore(5)

        async def one(pid: str) -> tuple[str, LiveStatus | None]:
            async with sem:
                try:
                    return pid, await self.live_status(pid)
                except (PlatformError, ChannelNotFound, httpx.HTTPError):
                    return pid, None

        results = await asyncio.gather(*(one(pid) for pid in platform_ids))
        return {pid: s for pid, s in results if s is not None}

    def stream_url(self, platform_id: str) -> str:
        return f"https://chzzk.naver.com/live/{platform_id}"

    async def chat_access_token(self, chat_channel_id: str) -> str:
        r = await self._client.get(
            "https://comm-api.game.naver.com/nng_main/v1/chats/access-token",
            params={"channelId": chat_channel_id, "chatType": "STREAMING"},
            cookies=self._cookies,
        )
        if r.status_code != 200:
            raise PlatformError(f"Chzzk chat token returned {r.status_code}.")
        return (r.json().get("content") or {})["accessToken"]


def parse_live_status(content: dict) -> LiveStatus:
    if content.get("status") != "OPEN":
        return LiveStatus(is_live=False)
    opened = content.get("openDate")
    started = None
    if opened:
        try:
            started = datetime.strptime(opened, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except ValueError:
            started = None
    return LiveStatus(
        is_live=True,
        stream_id=str(content["liveId"]) if content.get("liveId") is not None else opened,
        title=content.get("liveTitle"),
        started_at=started,
        category=content.get("liveCategoryValue") or None,
        chat_channel_id=content.get("chatChannelId"),
    )
