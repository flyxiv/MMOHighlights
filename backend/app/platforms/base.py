from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class UnsupportedUrl(ValueError):
    """The URL isn't a Twitch, YouTube or Chzzk channel URL."""


class ChannelNotFound(LookupError):
    """The URL looked right, but the platform has no such channel."""


class PlatformError(RuntimeError):
    """The platform returned something we couldn't use (timeout, 5xx, changed format)."""


class NotConfigured(PlatformError):
    """Credentials this platform needs aren't set."""


@dataclass(frozen=True)
class ParsedUrl:
    platform: str
    # Twitch login, YouTube channel id ("UC…") or handle ("@name"), or Chzzk channel hash.
    key: str


@dataclass(frozen=True)
class ChannelInfo:
    platform: str
    platform_id: str
    display_name: str
    url: str
    thumbnail_url: str | None


@dataclass(frozen=True)
class LiveStatus:
    is_live: bool
    stream_id: str | None = None
    title: str | None = None
    started_at: datetime | None = None
    # Twitch game name / Chzzk category; used to suggest labels.
    category: str | None = None
    # Chzzk only: needed to join the chat.
    chat_channel_id: str | None = None


class PlatformAdapter(Protocol):
    platform: str

    async def resolve(self, parsed: ParsedUrl) -> ChannelInfo: ...

    async def check(self, platform_ids: list[str]) -> dict[str, LiveStatus]:
        """Live status for each id. Ids that failed to check are left out."""
        ...

    def stream_url(self, platform_id: str) -> str:
        """URL passed to streamlink."""
        ...


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=httpx.Timeout(10.0),
        follow_redirects=True,
    )
