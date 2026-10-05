"""The README promises .parquet and .xlsx in the data folder: both must load, and a missing reader must say so."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.paper_data_db import read_only_query
from src.modules.data.byod_import import import_corpus_into_data_db


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "p"
    (ws / "data").mkdir(parents=True)
    return ws


async def test_parquet_loads(tmp_path: Path):
    ws = _ws(tmp_path)
    pd.DataFrame({"t": [1, 2, 3], "x": [0.5, 1.5, 2.5]}).to_parquet(ws / "data" / "prices.parquet")
    await import_corpus_into_data_db(ws, max_rows=1000)
    res = await read_only_query(ws, "SELECT COUNT(*) n, SUM(x) s FROM prices")
    assert res["rows"][0] == [3, 4.5]


async def test_xlsx_loads(tmp_path: Path):
    ws = _ws(tmp_path)
    pd.DataFrame({"firm": ["a", "b"], "size": [10, 20]}).to_excel(ws / "data" / "firms.xlsx", index=False)
    await import_corpus_into_data_db(ws, max_rows=1000)
    res = await read_only_query(ws, "SELECT COUNT(*) n, SUM(size) s FROM firms")
    assert res["rows"][0] == [2, 30]


async def test_missing_reader_is_loud(tmp_path: Path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    pd.DataFrame({"t": [1]}).to_parquet(ws / "data" / "a.parquet")
    import importlib.util

    orig = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "pyarrow" else orig(name, *a))
    await import_corpus_into_data_db(ws, max_rows=1000)
    err = capsys.readouterr().err
    assert "a.parquet was not loaded" in err
    assert "pip install pyarrow" in err
