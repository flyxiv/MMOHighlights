"""Database-backed tests run against TEST_DATABASE_URL (a throwaway database; its schema is reset)."""

import os

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://recorder:recorder@localhost:5433/recorder_test?ssl=disable"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["RUN_WORKERS"] = "false"
os.environ["STORAGE_BACKEND"] = "local"

from collections.abc import AsyncIterator  # noqa: E402
from pathlib import Path  # noqa: E402

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app import db  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.platforms.base import ChannelInfo, ChannelNotFound, LiveStatus, ParsedUrl  # noqa: E402
from app.platforms.urls import canonical_url  # noqa: E402
from app.storage import LocalStorage  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent


class FakeAdapter:
    """Stands in for a platform. Tests set `live[...]` to control what the poller sees."""

    def __init__(self, platform: str):
        self.platform = platform
        self.known: dict[str, str] = {}
        self.live: dict[str, LiveStatus] = {}

    async def resolve(self, parsed: ParsedUrl) -> ChannelInfo:
        if parsed.key not in self.known:
            raise ChannelNotFound(f"No {self.platform} channel named “{parsed.key}”.")
        return ChannelInfo(
            self.platform, parsed.key, self.known[parsed.key], canonical_url(self.platform, parsed.key), None
        )

    async def check(self, platform_ids: list[str]) -> dict[str, LiveStatus]:
        return {pid: self.live.get(pid, LiveStatus(is_live=False)) for pid in platform_ids}

    def stream_url(self, platform_id: str) -> str:
        return f"fake://{platform_id}"


class FakePlatforms:
    def __init__(self):
        self.twitch = FakeAdapter("twitch")
        self.youtube = FakeAdapter("youtube")
        self.chzzk = FakeAdapter("chzzk")

    def get(self, platform: str) -> FakeAdapter:
        return getattr(self, platform)

    async def aclose(self) -> None:
        pass


def _db_available() -> bool:
    import asyncio

    async def probe() -> bool:
        try:
            conn = await db.raw_connect(timeout=3)
        except (OSError, asyncpg.PostgresError):
            return False
        await conn.close()
        return True

    return asyncio.run(probe())


@pytest.fixture(scope="session")
def migrated_db():
    get_settings.cache_clear()
    if not _db_available():
        pytest.skip("TEST_DATABASE_URL is not reachable")
    import asyncio

    async def reset() -> None:
        conn = await db.raw_connect()
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()

    asyncio.run(reset())
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture
async def clean_db(migrated_db) -> AsyncIterator[None]:
    conn = await db.raw_connect()
    await conn.execute("TRUNCATE chat_minutes, segments, recordings, channels RESTART IDENTITY CASCADE")
    await conn.execute("DELETE FROM tiers WHERE name NOT IN ('Kefka Ultimate', 'Curse of U''latek')")
    await conn.close()
    yield
    await db.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    get_settings.cache_clear()
    s = get_settings()
    s.spool_dir = tmp_path / "spool"
    s.local_storage_dir = tmp_path / "bucket"
    s.segment_seconds = 2
    s.grace_period_s = 0
    s.offline_polls_to_end = 2
    return s


@pytest.fixture
def platforms() -> FakePlatforms:
    return FakePlatforms()


@pytest.fixture
async def app(clean_db, settings, platforms, tmp_path):
    from app.main import create_app

    application = create_app(
        settings, storage=LocalStorage(settings.local_storage_dir / settings.gcs_bucket), platforms=platforms
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def services(app):
    return app.state.services
