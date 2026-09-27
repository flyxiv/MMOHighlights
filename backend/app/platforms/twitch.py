import time
from datetime import datetime

import httpx

from app.platforms.base import (
    ChannelInfo,
    ChannelNotFound,
    LiveStatus,
    NotConfigured,
    ParsedUrl,
    PlatformError,
)
from app.platforms.urls import canonical_url

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class TwitchAdapter:
    platform = "twitch"

    def __init__(self, client: httpx.AsyncClient, client_id: str, client_secret: str):
        self._client = client
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires = 0.0

    async def _auth_headers(self) -> dict[str, str]:
        if not self._client_id or not self._client_secret:
            raise NotConfigured(
                "Twitch channels need TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET. "
                "Register an app at dev.twitch.tv/console and add them to backend/.env."
            )
        if self._token is None or time.monotonic() > self._token_expires - 60:
            r = await self._client.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
            if r.status_code != 200:
                raise PlatformError(f"Twitch token request failed ({r.status_code}).")
            body = r.json()
            self._token = body["access_token"]
            self._token_expires = time.monotonic() + float(body.get("expires_in", 3600))
        return {"Client-Id": self._client_id, "Authorization": f"Bearer {self._token}"}

    async def _get(self, path: str, params: list[tuple[str, str]]) -> dict:
        for attempt in range(2):
            r = await self._client.get(f"{HELIX}{path}", params=params, headers=await self._auth_headers())
            if r.status_code == 401 and attempt == 0:
                self._token = None
                continue
            if r.status_code != 200:
                raise PlatformError(f"Twitch {path} returned {r.status_code}.")
            return r.json()
        raise PlatformError("Twitch authentication failed.")

    async def resolve(self, parsed: ParsedUrl) -> ChannelInfo:
        body = await self._get("/users", [("login", parsed.key)])
        users = body.get("data") or []
        if not users:
            raise ChannelNotFound(f"No Twitch channel named “{parsed.key}”.")
        u = users[0]
        login = u["login"]
        return ChannelInfo(
            platform="twitch",
            platform_id=login,
            display_name=u.get("display_name") or login,
            url=canonical_url("twitch", login),
            thumbnail_url=u.get("profile_image_url"),
        )

    async def check(self, platform_ids: list[str]) -> dict[str, LiveStatus]:
        result = {pid: LiveStatus(is_live=False) for pid in platform_ids}
        for i in range(0, len(platform_ids), 100):
            chunk = platform_ids[i : i + 100]
            body = await self._get(
                "/streams", [("user_login", login) for login in chunk] + [("first", "100")]
            )
            for s in body.get("data") or []:
                if s.get("type") != "live":
                    continue
                result[s["user_login"].lower()] = parse_stream(s)
        return result

    def stream_url(self, platform_id: str) -> str:
        return canonical_url("twitch", platform_id)


def parse_stream(s: dict) -> LiveStatus:
    started = s.get("started_at")
    return LiveStatus(
        is_live=True,
        stream_id=s.get("id"),
        title=s.get("title"),
        started_at=datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None,
        category=s.get("game_name") or None,
    )
