"""`e2er-data query` — the CLI-backend path to query_data (claude_code can't see
the in-process SDK tool, so this Bash wrapper is what actually runs)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.db.paper_data_db import materialize_rows
from src.modules.data.cli import _run_query_sql, _run_query_tables


async def _setup(tmp_path: Path, monkeypatch) -> str:
    pid = "paper1"
    ws = tmp_path / pid
    ws.mkdir()
    await materialize_rows(
        ws,
        "trades",
        [{"agg": "Blur", "fee": 0}, {"agg": "Direct", "fee": 5}, {"agg": "Blur", "fee": 0}],
    )
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    return pid


def _args(pid: str, **kw) -> argparse.Namespace:
    return argparse.Namespace(paper_id=pid, specialist="data_analyst", **kw)


async def test_query_sql_returns_real_results(tmp_path: Path, monkeypatch):
    pid = await _setup(tmp_path, monkeypatch)
    out = await _run_query_sql(_args(pid, sql="SELECT agg, COUNT(*) AS n FROM trades GROUP BY agg ORDER BY n DESC"))
    d = json.loads(out)
    assert d["columns"] == ["agg", "n"]
    assert ["Blur", 2] in d["rows"]
    assert ["Direct", 1] in d["rows"]


async def test_query_sql_is_read_only(tmp_path: Path, monkeypatch):
    pid = await _setup(tmp_path, monkeypatch)
    for bad in ("DELETE FROM trades", "DROP TABLE trades", "UPDATE trades SET fee=9"):
        d = json.loads(await _run_query_sql(_args(pid, sql=bad)))
        assert "error" in d


async def test_query_tables_lists_catalog(tmp_path: Path, monkeypatch):
    pid = await _setup(tmp_path, monkeypatch)
    d = json.loads(await _run_query_tables(_args(pid)))
    assert d["tables"][0]["table"] == "trades"
    assert {c["name"] for c in d["tables"][0]["columns"]} == {"agg", "fee"}


async def test_query_no_data_db_is_clean_message(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "empty").mkdir()
    d = json.loads(await _run_query_sql(_args("empty", sql="SELECT 1")))
    assert "error" in d and "data warehouse" in d["error"]


def test_query_source_registered_in_dispatch():
    from src.modules.data.cli import _DISPATCH

    assert set(_DISPATCH["query"]) == {"sql", "tables"}
