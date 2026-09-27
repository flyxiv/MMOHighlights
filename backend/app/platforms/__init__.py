import httpx

from app.config import Settings
from app.platforms.base import PlatformAdapter, make_client
from app.platforms.chzzk import ChzzkAdapter
from app.platforms.twitch import TwitchAdapter
from app.platforms.youtube import YouTubeAdapter


class Platforms:
    """One adapter per platform, sharing an HTTP client."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.client = client or make_client()
        self.twitch = TwitchAdapter(self.client, settings.twitch_client_id, settings.twitch_client_secret)
        self.youtube = YouTubeAdapter(self.client, settings.youtube_api_key)
        self.chzzk = ChzzkAdapter(self.client, settings.chzzk_nid_aut, settings.chzzk_nid_ses)

    def get(self, platform: str) -> PlatformAdapter:
        return {"twitch": self.twitch, "youtube": self.youtube, "chzzk": self.chzzk}[platform]

    async def aclose(self) -> None:
        await self.client.aclose()
