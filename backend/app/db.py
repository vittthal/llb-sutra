"""asyncpg connection pool, shared by the API and the ingest CLI."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import asyncpg

from backend.app.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.dsn, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@contextlib.asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    async with connection() as conn:
        async with conn.transaction():
            yield conn
