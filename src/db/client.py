"""Async PostgreSQL client using psycopg3 connection pool."""
from __future__ import annotations

from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        import psycopg_pool
        from ..config import get_settings
        settings = get_settings()
        _pool = psycopg_pool.AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            open=False,
        )
        await _pool.open()
    return _pool


async def execute(sql: str, params: dict[str, Any] | None = None) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(sql, params or {})


async def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    from psycopg.rows import dict_row
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params or {})
            return await cur.fetchone()


async def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params or {})
            return await cur.fetchall()


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
