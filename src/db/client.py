"""Async DB client — dispatches between Postgres (psycopg) and SQLite (aiosqlite).

Default for local installs: SQLite at ``~/.e2er/papers.db``. Postgres opt-in
via ``DATABASE_URL=postgresql://…`` for production / multi-user deployments
that need pgvector + concurrent writes.

The same ``execute / fetch_one / fetch_all`` interface works on both.
Parameters are written in psycopg's ``%(name)s`` style throughout the
codebase; for SQLite we translate to ``:name`` + strip Postgres
``::type`` casts on the fly. Most existing call sites need zero changes.

Limitations on SQLite:
  - pgvector tables (literature_files, knowledge_chunks) are NOT created
    on SQLite. The literature KB feature degrades to "disabled".
  - JSONB columns store JSON strings; agents read with ``json.loads(...)``
    if needed.
  - No ``uuid_generate_v4()`` — callers MUST generate UUIDs client-side
    and include them in the INSERT. (This is already the pattern in
    api/app.py and most call sites; the few exceptions are noted in
    each module's docstring.)
"""

from __future__ import annotations

import re
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

_pool = None
_backend: str = ""  # "postgres" or "sqlite"; resolved lazily on first connect


def _resolve_backend(database_url: str) -> str:
    """Detect which DB backend a connection-string targets."""
    if not database_url or database_url.startswith("sqlite"):
        return "sqlite"
    if database_url.startswith(("postgres://", "postgresql://")):
        return "postgres"
    raise ValueError(
        f"Unsupported DATABASE_URL scheme: {database_url[:30]!r}. "
        "Expected sqlite:///path/to.db or postgresql://user:pw@host/db."
    )


def _sqlite_path(database_url: str) -> str:
    """Extract a filesystem path from a sqlite:///… URL.

    Handles the three-slash form ``sqlite:///abs/path``, the user-home
    expansion ``sqlite:///~/.e2er/x.db``, and the unset default which
    resolves to ``~/.e2er/papers.db``.
    """
    from pathlib import Path

    if not database_url:
        return str((Path.home() / ".e2er" / "papers.db").expanduser())
    if database_url.startswith("sqlite:///"):
        raw = database_url[len("sqlite:///") :]
        return str(Path(raw).expanduser())
    if database_url.startswith("sqlite://"):
        raw = database_url[len("sqlite://") :]
        return str(Path(raw).expanduser())
    raise ValueError(f"not a sqlite URL: {database_url!r}")


# ---------- Parameter-style translation: %(name)s → :name ----------

_PARAM_RE = re.compile(r"%\(([a-zA-Z_][a-zA-Z0-9_]*)\)s")
_CAST_RE = re.compile(
    r"::(uuid|jsonb|timestamptz|timestamp|json|interval|date|time|text"
    r"|int|integer|bigint|smallint|float|float8|float4|double|numeric|decimal|real|boolean|bool)"
)
_NOW_RE = re.compile(r"\bNOW\(\)")


def _translate_to_sqlite(sql: str) -> str:
    """Translate Postgres-flavoured SQL to SQLite-flavoured.

    - ``%(name)s`` placeholders → ``:name`` (sqlite3 / aiosqlite syntax).
    - ``::uuid``, ``::jsonb``, ``::timestamptz``, etc. casts are stripped —
      SQLite is typeless enough that the bare value works.
    - ``NOW()`` → ``CURRENT_TIMESTAMP`` so timestamp defaults in UPDATEs
      work on both backends. Pre-v0.4 we missed this and silent UPDATEs
      on SQLite left ``papers.status`` stuck at 'idea'.
    """
    sql = _PARAM_RE.sub(r":\1", sql)
    sql = _CAST_RE.sub("", sql)
    sql = _NOW_RE.sub("CURRENT_TIMESTAMP", sql)
    return sql


# ---------- Public API ----------


def _detect_backend_from_settings() -> str:
    """One-shot backend resolution from settings; safe to call repeatedly."""
    global _backend
    if not _backend:
        from ..config import get_settings

        _backend = _resolve_backend(get_settings().resolved_database_url)
    return _backend


def current_backend() -> str:
    """Public accessor for the active DB backend ("postgres" or "sqlite").

    Lets call sites (literature storage, BYOD ingestion) branch on the backend
    without importing the underscore-prefixed internal helper.
    """
    return _detect_backend_from_settings()


async def get_pool():
    """Postgres connection pool. Returns None on SQLite mode."""
    global _pool
    backend = _detect_backend_from_settings()
    if backend == "sqlite":
        return None
    if _pool is None:
        import psycopg_pool

        from ..config import get_settings

        _pool = psycopg_pool.AsyncConnectionPool(
            conninfo=get_settings().resolved_database_url,
            min_size=1,
            max_size=10,
            open=False,
        )
        await _pool.open()
    return _pool


async def execute(sql: str, params: dict[str, Any] | None = None) -> None:
    if _detect_backend_from_settings() == "sqlite":
        await _sqlite_execute(sql, params)
        return
    pool = await get_pool()
    async with pool.connection() as conn:  # type: ignore[union-attr]
        await conn.execute(sql, params or {})


async def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if _detect_backend_from_settings() == "sqlite":
        rows = await _sqlite_fetch_all(sql, params)
        return rows[0] if rows else None
    from psycopg.rows import dict_row

    pool = await get_pool()
    async with pool.connection() as conn:  # type: ignore[union-attr]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params or {})
            return await cur.fetchone()


async def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if _detect_backend_from_settings() == "sqlite":
        return await _sqlite_fetch_all(sql, params)
    from psycopg.rows import dict_row

    pool = await get_pool()
    async with pool.connection() as conn:  # type: ignore[union-attr]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params or {})
            return await cur.fetchall()


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ---------- SQLite implementation ----------

_sqlite_bootstrapped = False


async def _ensure_sqlite_schema() -> None:
    """Create core tables on first connect. Idempotent — uses IF NOT EXISTS."""
    from pathlib import Path

    import aiosqlite

    from ..config import get_settings

    path = Path(_sqlite_path(get_settings().resolved_database_url))
    path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).resolve().parent.parent.parent / "sql" / "sqlite" / "schema.sql"
    if not schema_path.exists():
        logger.warning("SQLite schema file missing at %s; skipping auto-bootstrap", schema_path)
        return

    async with aiosqlite.connect(str(path)) as conn:
        await conn.executescript(schema_path.read_text(encoding="utf-8"))
        await conn.commit()


async def _sqlite_connect():
    """Open a fresh aiosqlite connection. Bootstraps the schema on first call."""
    global _sqlite_bootstrapped
    import aiosqlite

    from ..config import get_settings

    path = _sqlite_path(get_settings().resolved_database_url)
    if not _sqlite_bootstrapped:
        await _ensure_sqlite_schema()
        _sqlite_bootstrapped = True
    conn = await aiosqlite.connect(path)
    await conn.execute("PRAGMA foreign_keys = ON")

    # Return rows as dicts for parity with psycopg's dict_row.
    def _dict_row(cur, row):
        return {d[0]: row[i] for i, d in enumerate(cur.description)}

    conn.row_factory = _dict_row
    return conn


async def _sqlite_execute(sql: str, params: dict[str, Any] | None = None) -> None:
    sql = _translate_to_sqlite(sql)
    conn = await _sqlite_connect()
    try:
        await conn.execute(sql, params or {})
        await conn.commit()
    finally:
        await conn.close()


async def _sqlite_fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    sql = _translate_to_sqlite(sql)
    conn = await _sqlite_connect()
    try:
        cur = await conn.execute(sql, params or {})
        try:
            return list(await cur.fetchall())
        finally:
            await cur.close()
    finally:
        await conn.close()
