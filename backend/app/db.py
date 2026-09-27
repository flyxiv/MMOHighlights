import ssl
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def split_ssl(url: str) -> tuple[str, dict[str, Any]]:
    """Take `ssl` / `sslmode` out of the URL and turn it into an explicit asyncpg `ssl` argument.

    Left to itself, asyncpg looks for client certificates under the home directory, which fails
    when that path isn't ASCII (as on this project's Windows host). An explicit value skips that.
      disable            → no TLS (local Postgres)
      require (default)  → TLS without certificate checks, like libpq's sslmode=require
      verify-full        → TLS with the system CA store and hostname check
    """
    parts = urlsplit(url)
    query = parse_qsl(parts.query)
    mode = next((v for k, v in query if k in ("ssl", "sslmode")), None)
    rest = [(k, v) for k, v in query if k not in ("ssl", "sslmode")]
    clean = urlunsplit(parts._replace(query=urlencode(rest)))
    host = parts.hostname or ""
    if mode is None:
        mode = "disable" if host in ("localhost", "127.0.0.1", "::1") else "require"
    if mode in ("disable", "false"):
        return clean, {"ssl": False}
    if mode in ("verify-full", "verify-ca"):
        return clean, {"ssl": ssl.create_default_context()}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return clean, {"ssl": ctx}


def engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        url, connect_args = split_ssl(s.database_url)
        _engine = create_async_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def raw_connect(timeout: float = 10) -> asyncpg.Connection:
    """A plain asyncpg connection (for LISTEN/NOTIFY), with the same TLS settings as the engine."""
    url, kwargs = split_ssl(get_settings().database_url)
    return await asyncpg.connect(
        url.replace("postgresql+asyncpg://", "postgresql://", 1), timeout=timeout, **kwargs
    )
