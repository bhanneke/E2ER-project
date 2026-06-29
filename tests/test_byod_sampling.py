"""Importer row-cap = representative systematic sample, not head(N).

Regression for the run-2 rejection: head(N) on a 16 GB time-ordered NFT file
kept only the earliest ~200k rows (all 2021, pre-aggregator) → the model built a
bogus proxy. Capping must span the whole file."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.paper_data_db import read_only_query
from src.modules.data.byod_import import _systematic_sample, import_corpus_into_data_db


def test_systematic_sample_helper_spans_and_caps():
    df = pd.DataFrame({"t": range(100)})
    out = _systematic_sample(df, 10)
    assert len(out) <= 10
    assert out["t"].min() == 0
    assert out["t"].max() >= 80  # spans into the late period, not just 0..9


def test_systematic_sample_noop_under_cap():
    df = pd.DataFrame({"t": range(5)})
    out = _systematic_sample(df, 1000)
    assert list(out["t"]) == [0, 1, 2, 3, 4]


async def test_csv_cap_spans_full_range(tmp_path: Path):
    ws = tmp_path / "p"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "ts.csv").write_text("t\n" + "\n".join(str(i) for i in range(100)) + "\n")
    await import_corpus_into_data_db(ws, max_rows=10)
    res = await read_only_query(ws, "SELECT COUNT(*) n, MIN(t) mn, MAX(t) mx FROM ts")
    n, mn, mx = res["rows"][0]
    assert n <= 10
    assert mn == 0
    assert mx >= 80, f"head-bias not fixed: max={mx} (should span toward 99)"


async def test_csv_under_cap_imported_fully(tmp_path: Path):
    ws = tmp_path / "p"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "small.csv").write_text("t\n0\n1\n2\n3\n4\n")
    await import_corpus_into_data_db(ws, max_rows=1000)
    res = await read_only_query(ws, "SELECT COUNT(*) n, MAX(t) mx FROM small")
    assert res["rows"][0] == [5, 4]


async def test_jsonl_cap_spans(tmp_path: Path):
    ws = tmp_path / "p"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "ev.jsonl").write_text("\n".join(f'{{"t": {i}}}' for i in range(100)) + "\n")
    await import_corpus_into_data_db(ws, max_rows=10)
    res = await read_only_query(ws, "SELECT COUNT(*) n, MAX(t) mx FROM ev")
    n, mx = res["rows"][0]
    assert n <= 10
    assert mx >= 80
