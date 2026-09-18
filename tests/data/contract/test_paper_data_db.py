"""Per-paper data.db: BYOD import, read-only query enforcement, catalog.

Hermetic — operates on a workspace-local data.db, no global DB/network/LLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db.paper_data_db import (
    DataQueryError,
    data_db_path,
    list_tables_catalog_sync,
    read_only_query,
    sanitize_table_name,
)
from src.modules.data.byod_import import import_corpus_into_data_db


def _write_csv(ws: Path, rel: str, text: str) -> None:
    p = ws / "data" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_sanitize_table_name():
    assert sanitize_table_name("raw/Friend.Tech Trades.csv") == "raw_friend_tech_trades"
    assert sanitize_table_name("2024data.csv").startswith("t_")
    assert sanitize_table_name("!!!.csv") == "table"


async def test_import_creates_tables_and_handles_collision(tmp_path: Path):
    ws = tmp_path / "paper"
    _write_csv(ws, "nft_trades.csv", "trader,price,day\nalice,10,1\nbob,20,1\nalice,30,2\n")
    _write_csv(ws, "raw/nft_trades.csv", "x,y\n1,2\n3,4\n")  # basename collision

    imported = await import_corpus_into_data_db(ws, max_rows=1_000_000)
    tables = {r["table"]: r["rows"] for r in imported}
    assert tables == {"nft_trades": 3, "raw_nft_trades": 2}
    assert data_db_path(ws).is_file()


async def test_query_data_aggregation(tmp_path: Path):
    ws = tmp_path / "paper"
    _write_csv(ws, "nft_trades.csv", "trader,price\nalice,10\nbob,20\nalice,30\n")
    await import_corpus_into_data_db(ws, max_rows=1_000_000)

    sql = "SELECT trader, SUM(price) AS tot FROM nft_trades GROUP BY trader ORDER BY tot DESC"
    res = await read_only_query(ws, sql)
    assert res["columns"] == ["trader", "tot"]
    assert res["rows"] == [["alice", 40], ["bob", 20]]


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM nft_trades",
        "UPDATE nft_trades SET price = 0",
        "DROP TABLE nft_trades",
        "SELECT 1; DROP TABLE nft_trades",
        "PRAGMA table_info(nft_trades)",
        "INSERT INTO nft_trades VALUES ('x', 1)",
        "ATTACH DATABASE 'x.db' AS y",
    ],
)
async def test_query_data_rejects_writes(tmp_path: Path, bad_sql: str):
    ws = tmp_path / "paper"
    _write_csv(ws, "nft_trades.csv", "trader,price\nalice,10\n")
    await import_corpus_into_data_db(ws, max_rows=1_000_000)

    with pytest.raises(DataQueryError):
        await read_only_query(ws, bad_sql)


async def test_query_data_no_db_is_clear_error(tmp_path: Path):
    with pytest.raises(DataQueryError, match="no data warehouse"):
        await read_only_query(tmp_path / "empty", "SELECT 1")


async def test_row_cap_truncates(tmp_path: Path):
    ws = tmp_path / "paper"
    rows = "\n".join(f"{i}" for i in range(50))
    _write_csv(ws, "nums.csv", "n\n" + rows + "\n")
    await import_corpus_into_data_db(ws, max_rows=1_000_000)
    res = await read_only_query(ws, "SELECT n FROM nums", max_rows=10)
    assert res["truncated"] is True
    assert len(res["rows"]) == 10


async def test_max_rows_cap_on_import(tmp_path: Path):
    ws = tmp_path / "paper"
    body = "\n".join(f"{i},{i}" for i in range(100))
    _write_csv(ws, "big.csv", "a,b\n" + body + "\n")
    imported = await import_corpus_into_data_db(ws, max_rows=25)
    assert imported[0]["rows"] == 25


def test_catalog_describes_tables(tmp_path: Path):
    import asyncio

    ws = tmp_path / "paper"
    _write_csv(ws, "nft_trades.csv", "trader,price\nalice,10\nbob,20\n")
    asyncio.run(import_corpus_into_data_db(ws, max_rows=1_000_000))

    catalog = list_tables_catalog_sync(ws)
    assert len(catalog) == 1
    tbl = catalog[0]
    assert tbl["table"] == "nft_trades"
    assert {c["name"] for c in tbl["columns"]} == {"trader", "price"}
    assert tbl["row_count"] == 2
    assert len(tbl["samples"]) == 2


def test_catalog_empty_without_db(tmp_path: Path):
    assert list_tables_catalog_sync(tmp_path / "nope") == []
