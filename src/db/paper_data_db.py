"""Per-paper SQLite data warehouse (``workspace/<paper_id>/data.db``).

Separate from the metadata DB (``src/db/client.py``): the researcher's BYOD
tabular files and any materialized external-source pulls (FRED/yfinance/Allium)
live here as queryable tables, so specialists can run real SQL via the
``query_data`` tool instead of only reading CSVs into pandas via ``read_file``.

**Why a separate file.** The metadata client is globally bound to
``settings.resolved_database_url`` — Postgres in production, the *shared*
``~/.e2er/papers.db`` on SQLite. Per-paper data tables there would collide
across papers and bloat the metadata DB. One file per paper keeps the data
isolated, disposable, and colocated with the workspace it belongs to.

**Read path is hard-sandboxed.** ``read_only_query`` opens the file with a
``file:…?mode=ro`` URI *and* ``PRAGMA query_only=ON``, so even a creative SELECT
cannot mutate anything. Writes happen only through ``materialize_dataframe`` /
``materialize_rows`` (import + external materialization), never through
agent-issued SQL.

All public functions have a sync core (plain ``sqlite3``) wrapped for async
callers via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..logging_config import get_logger

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)

DATA_DB_FILENAME = "data.db"

# Cap rows returned to the model from a single query_data call. The data.db can
# hold millions of rows; the model only needs a window or an aggregate.
MAX_RESULT_ROWS = 1000

# Insert chunk size for materialization (memory bound; uses executemany, so the
# SQLite variable limit doesn't apply).
_INSERT_CHUNK = 10_000

# Statements that must never run through the agent-facing query path. The
# engine-level mode=ro is the real guarantee; this is defense-in-depth + a
# clearer error than a raw sqlite "attempt to write a readonly database".
_FORBIDDEN_SQL = re.compile(
    r"(?i)\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"reindex|vacuum|pragma|begin|commit|rollback|truncate|grant|revoke)\b"
)


# ── paths + identifiers ──────────────────────────────────────────────────────


def data_db_path(workspace: Path) -> Path:
    """Path to this paper's data warehouse file (may not exist yet)."""
    return Path(workspace) / DATA_DB_FILENAME


def has_data_db(workspace: Path) -> bool:
    return data_db_path(workspace).is_file()


def sanitize_table_name(raw: str) -> str:
    """Turn a filename / relative path into a safe, stable SQLite identifier.

    ``raw/Friend.Tech Trades.csv`` → ``raw_friend_tech_trades``. Lowercased,
    non-alphanumerics collapsed to ``_``, leading digits prefixed with ``t_``
    (SQLite identifiers can't start with a digit without quoting).
    """
    # Drop the extension but keep directory structure as a prefix so
    # `raw/trades.csv` and `trades.csv` don't both collapse to `trades`.
    p = Path(raw)
    stem = p.with_suffix("").as_posix()
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", stem).strip("_").lower()
    if not cleaned:
        cleaned = "table"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned


def unique_table_name(raw: str, existing: set[str]) -> str:
    """A sanitized table name guaranteed not to collide with ``existing``."""
    base = sanitize_table_name(raw)
    name = base
    n = 2
    while name in existing:
        name = f"{base}_{n}"
        n += 1
    existing.add(name)
    return name


# ── write path (materialization) ─────────────────────────────────────────────


def _materialize_dataframe_sync(
    db_path: Path,
    table: str,
    df: pd.DataFrame,
    *,
    if_exists: Literal["fail", "replace", "append"] = "replace",
) -> int:
    from ..modules.data.normalize import normalize_for_materialization

    # tz-aware timestamps in, tz-naive UTC out. Generated analysis code
    # compares against plain `pd.Timestamp(...)` and crashes otherwise.
    df, _ = normalize_for_materialization(df)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # method=None → executemany (no SQLite-variable-limit issues on wide
        # tables); chunksize bounds peak memory for large frames.
        df.to_sql(table, conn, if_exists=if_exists, index=False, chunksize=_INSERT_CHUNK, method=None)
        conn.commit()
    finally:
        conn.close()
    return int(len(df))


async def materialize_dataframe(
    workspace: Path, table: str, df: pd.DataFrame, *, if_exists: Literal["fail", "replace", "append"] = "replace"
) -> int:
    """Write a DataFrame into the paper's data.db as ``table``. Returns row count."""
    return await asyncio.to_thread(_materialize_dataframe_sync, data_db_path(workspace), table, df, if_exists=if_exists)


def _rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame(rows)


async def materialize_rows(
    workspace: Path,
    table: str,
    rows: list[dict[str, Any]],
    *,
    if_exists: Literal["fail", "replace", "append"] = "replace",
) -> int:
    """Materialize a list of uniform dict rows (e.g. a provider ``items`` list)
    into the data.db as ``table``. Returns the number of rows written."""
    if not rows:
        return 0
    df = await asyncio.to_thread(_rows_to_dataframe, rows)
    return await materialize_dataframe(workspace, table, df, if_exists=if_exists)


# ── read path (sandboxed) ────────────────────────────────────────────────────


class DataQueryError(ValueError):
    """Raised for a rejected or failed query_data call (message is model-safe)."""


def _validate_read_only(sql: str) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise DataQueryError("empty SQL")
    # Single statement only — a trailing ';' is fine, an embedded one is not.
    if ";" in stripped:
        raise DataQueryError("only a single SELECT statement is allowed (no ';' chaining)")
    if _FORBIDDEN_SQL.search(stripped):
        raise DataQueryError(
            "query_data is read-only: only SELECT/WITH queries are allowed (no INSERT/UPDATE/DELETE/DDL/PRAGMA/ATTACH)."
        )
    head = stripped.lstrip("(").lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise DataQueryError("query must begin with SELECT or WITH")
    return stripped


def _read_only_query_sync(db_path: Path, sql: str, max_rows: int) -> dict[str, Any]:
    if not db_path.is_file():
        raise DataQueryError(
            "no data warehouse exists for this paper yet. Import data files (they "
            "auto-import at paper creation) or materialize an external source first."
        )
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        try:
            cur = conn.execute(sql)
        except sqlite3.Error as e:
            raise DataQueryError(f"SQL error: {e}") from e
        columns = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [list(r) for r in fetched[:max_rows]]
        return {"columns": columns, "rows": rows, "truncated": truncated, "row_count": len(rows)}
    finally:
        conn.close()


async def read_only_query(workspace: Path, sql: str, *, max_rows: int = MAX_RESULT_ROWS) -> dict[str, Any]:
    """Run a validated read-only query against the paper's data.db.

    Raises ``DataQueryError`` (model-safe message) on rejection or SQL error.
    """
    stripped = _validate_read_only(sql)
    return await asyncio.to_thread(_read_only_query_sync, data_db_path(workspace), stripped, max_rows)


# ── catalog (for context injection) ──────────────────────────────────────────


def list_tables_catalog_sync(workspace: Path, sample_rows: int = 3) -> list[dict[str, Any]]:
    """Describe every table in the paper's data.db: name, columns+types, row
    count, and a few sample rows. Returns ``[]`` when there's no data.db.

    Sync so the (sync) context builders can call it directly.
    """
    db_path = data_db_path(workspace)
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        logger.warning("could not open data.db catalog at %s: %s", db_path, e)
        return []
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        out: list[dict[str, Any]] = []
        for t in tables:
            cols = [(row[1], row[2]) for row in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
            try:
                count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error:
                count = None
            try:
                samples = [list(r) for r in conn.execute(f'SELECT * FROM "{t}" LIMIT {int(sample_rows)}').fetchall()]
            except sqlite3.Error:
                samples = []
            out.append(
                {
                    "table": t,
                    "columns": [{"name": c[0], "type": c[1]} for c in cols],
                    "row_count": count,
                    "samples": samples,
                }
            )
        return out
    finally:
        conn.close()


async def list_tables_catalog(workspace: Path, sample_rows: int = 3) -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_tables_catalog_sync, workspace, sample_rows)
