"""Every data connector records its loads in data_sources.json, with terms and citation.

Hermetic: FRED is mocked with respx, yfinance and Allium by replacing the
provider call, Zenodo by a fake client. Pins, for each connector:
  - the entry names the source, what was loaded, where it went, when;
  - the short terms, the full terms and their address;
  - the citation and whether the source publishes its format (`citation_by`);
  - the dossier keeps these keys, and files read from a local folder (path).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.modules.data import cli
from src.modules.data.load_record import FRED, YFINANCE, fred_citation, record_load

PID = "rec-test"
FRED_BASE = "https://api.stlouisfed.org/fred"


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("FRED_API_KEY", "k" * 32)
    from src.config import get_settings

    get_settings.cache_clear()
    w = tmp_path / "ws" / PID
    w.mkdir(parents=True)
    yield w
    get_settings.cache_clear()


def _loads(ws: Path) -> list[dict[str, Any]]:
    return json.loads((ws / "data_sources.json").read_text())["loads"]


@respx.mock
def test_fred_load_records_series_terms_and_freds_own_citation(ws: Path, capsys, monkeypatch) -> None:
    import src.modules.data.fred_provider as fp

    monkeypatch.setattr(fp, "_MIN_REQUEST_SPACING_SEC", 0)
    respx.get(f"{FRED_BASE}/series/observations").mock(
        return_value=httpx.Response(
            200, json={"observations": [{"date": "2020-01-02", "value": "1.58", "realtime_start": "2026-10-04"}]}
        )
    )
    respx.get(f"{FRED_BASE}/series").mock(
        return_value=httpx.Response(
            200,
            json={
                "seriess": [
                    {
                        "id": "DGS2",
                        "title": "Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity",
                        "last_updated": "2026-10-03 15:16:02-05",
                    }
                ]
            },
        )
    )
    respx.get(f"{FRED_BASE}/series/release").mock(return_value=httpx.Response(200, json={"releases": [{"id": 18}]}))
    respx.get(f"{FRED_BASE}/release/sources").mock(
        return_value=httpx.Response(
            200, json={"sources": [{"name": "Board of Governors of the Federal Reserve System (US)"}]}
        )
    )
    code = cli.main(
        ["--paper-id", PID, "--specialist", "data_analyst", "fred", "series", "--series-id", "DGS2", "--table", "dgs2"]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["recorded_in"] == ["data_sources.json"]
    [load] = _loads(ws)
    assert load["connector"] == "fred" and load["dataset"] == FRED.dataset
    assert load["series"] == "DGS2" and load["table"] == "dgs2" and load["rows"] == 1
    assert load["terms"] == "https://fred.stlouisfed.org/legal/" and "copyright status" in load["terms_summary"]
    assert load["citation_by"] == "source" and load["last_updated"].startswith("2026-10-03")
    assert load["citation"].startswith(
        "Board of Governors of the Federal Reserve System (US), Market Yield on U.S. Treasury Securities at "
        "2-Year Constant Maturity [DGS2], retrieved from FRED, Federal Reserve Bank of St. Louis; "
        "https://fred.stlouisfed.org/series/DGS2, "
    )


def test_fred_citation_without_details_still_names_the_series_and_date() -> None:
    assert fred_citation("UNRATE", "2026-01-05T10:00:00Z") == (
        "[UNRATE], retrieved from FRED, Federal Reserve Bank of St. Louis; "
        "https://fred.stlouisfed.org/series/UNRATE, January 5, 2026."
    )


def test_yfinance_load_records_terms_and_an_e2er_citation(ws: Path, capsys, monkeypatch) -> None:
    from src.modules.data.yfinance_provider import YFinanceProvider

    async def history(self, ticker, start=None, end=None, interval="1d", auto_adjust=True):
        return {"source": "yfinance", "items": [{"date": "2020-01-02", "close": 1.0}], "error": None, "ticker": ticker}

    monkeypatch.setattr(YFinanceProvider, "history", history)
    code = cli.main(["--paper-id", PID, "yfinance", "history", "--ticker", "SPY", "--table", "spy_prices"])
    capsys.readouterr()
    assert code == 0
    [load] = _loads(ws)
    assert load["connector"] == "yfinance" and load["dataset"] == YFINANCE.dataset
    assert load["series"] == "SPY daily prices" and load["table"] == "spy_prices"
    assert "personal use" in load["terms_summary"] and load["terms"].startswith("https://legal.yahoo.com/")
    assert load["citation_by"] == "e2er" and load["citation"].startswith("Yahoo Finance, SPY daily prices, retrieved")


def test_a_failed_load_records_nothing(ws: Path, capsys, monkeypatch) -> None:
    from src.modules.data.yfinance_provider import YFinanceProvider

    async def history(self, ticker, **kw):
        return {"source": "yfinance", "items": [], "error": "blocked", "ticker": ticker}

    monkeypatch.setattr(YFinanceProvider, "history", history)
    cli.main(["--paper-id", PID, "yfinance", "history", "--ticker", "SPY"])
    capsys.readouterr()
    assert not (ws / "data_sources.json").exists()


async def test_fetch_data_records_the_load_too(tmp_path: Path, monkeypatch) -> None:
    """The API backends load through fetch_data; the record is the same."""
    from src.modules.data.discovery_tools import SeriesDataToolHandler
    from src.modules.data.yfinance_provider import YFinanceProvider

    async def history(self, ticker, start=None, end=None, interval="1d", auto_adjust=True):
        return {"source": "yfinance", "items": [{"date": "2020-01-02", "close": 1.0}], "error": None}

    monkeypatch.setattr(YFinanceProvider, "history", history)
    h = SeriesDataToolHandler(tmp_path)
    out = json.loads(
        await h.handle("fetch_data", {"provider": "yfinance", "method": "history", "params": {"ticker": "KBE"}})
    )
    assert out["recorded_in"] == ["data_sources.json"]
    [load] = _loads(tmp_path)
    assert load["series"] == "KBE daily prices" and load["citation_by"] == "e2er"


def test_loads_of_different_series_are_kept_and_the_same_table_replaced(tmp_path: Path) -> None:
    record_load(tmp_path, {"connector": "fred", "series": "DGS2"})
    record_load(tmp_path, {"connector": "fred", "series": "DGS10"})
    record_load(tmp_path, {"connector": "fred", "series": "DGS10"})
    record_load(tmp_path, {"connector": "gmd", "table": "macro", "version": "2026_06"})
    record_load(tmp_path, {"connector": "gmd", "table": "macro", "version": "2026_09"})
    assert [(x["connector"], x.get("series"), x.get("version")) for x in _loads(tmp_path)] == [
        ("fred", "DGS2", None),
        ("fred", "DGS10", None),
        ("gmd", None, "2026_09"),
    ]


def test_the_data_folder_records_each_file_with_its_hash(tmp_path: Path) -> None:
    from src.modules.data.byod_import import _import_corpus_sync

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fomc_dates.csv").write_text("date\n2015-12-16\n")
    _import_corpus_sync(tmp_path, 1000)
    [load] = _loads(tmp_path)
    assert load["connector"] == "data-folder" and load["series"] == "fomc_dates.csv"
    assert load["files"][0]["path"] == "data/fomc_dates.csv" and len(load["files"][0]["sha256"]) == 64
    assert "does not know the terms" in load["terms_summary"] and "citation" not in load


def test_a_zenodo_package_records_its_licence_doi_and_citation(tmp_path: Path) -> None:
    from src.modules.data.load_record import zenodo_load

    entry = zenodo_load(
        {
            "record_id": "123",
            "doi": "10.5281/zenodo.123",
            "url": "https://zenodo.org/records/123",
            "title": "Replication package",
            "creators": ["Doe, Jane", "Roe, Rob"],
            "licence": "cc-by-4.0",
            "publication_date": "2024-05-01",
            "version": "v2",
            "files": [{"key": "pkg.zip", "sha256": "b" * 64}],
        },
        "2026-10-04T10:00:00+00:00",
    )
    assert (
        entry["citation"]
        == "Doe, Jane; Roe, Rob (2024). Replication package (v2). Zenodo. https://doi.org/10.5281/zenodo.123"
    )
    assert entry["version"] == "v2" and entry["terms_summary"] == "Published on Zenodo under the licence cc-by-4.0."
    assert entry["files"] == [{"url": "https://zenodo.org/records/123/files/pkg.zip", "sha256": "b" * 64}]


async def test_an_allium_query_that_returns_rows_is_recorded(tmp_path: Path, monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from src.modules.data import audit
    from src.modules.data.allium import AlliumProvider
    from src.modules.data.guardrails import QueryValidator, ValidationResult
    from src.modules.data.tools import AlliumToolHandler

    monkeypatch.setenv("ALLIUM_API_KEY", "k")
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(QueryValidator, "validate_all", AsyncMock(return_value=ValidationResult(valid=True)))
    monkeypatch.setattr(audit, "log_query", AsyncMock(return_value="q1"))
    monkeypatch.setattr(audit, "mark_approved", AsyncMock())
    monkeypatch.setattr(audit, "mark_executed", AsyncMock())
    monkeypatch.setattr(AlliumProvider, "execute_raw", AsyncMock(return_value={"rows": [{"a": 1}], "columns": ["a"]}))
    h = AlliumToolHandler("p", "data_analyst", None, workspace=tmp_path)
    await h.handle(
        "query_allium",
        {
            "sql": "SELECT a FROM ethereum.dex.trades",
            "query_type": "feasibility",
            "aggregation_level": "daily",
            "primary_table": "ethereum.dex.trades",
        },
    )
    get_settings.cache_clear()
    [load] = _loads(tmp_path)
    assert load["connector"] == "allium" and load["series"] == "ethereum.dex.trades" and "LIMIT 1000" in load["query"]
    assert load["citation_by"] == "e2er" and "Allium" in load["terms_summary"]


def test_the_dossier_keeps_what_a_study_page_shows(tmp_path: Path) -> None:
    from src.core.dossier import _data_sources

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data_sources.json").write_text(
        json.dumps(
            {
                "loads": [
                    {
                        "connector": "fred",
                        "dataset": FRED.dataset,
                        "series": "DGS2",
                        "retrieved_at": "2026-10-04T10:00:00Z",
                        "terms_summary": "short",
                        "terms": "https://fred.stlouisfed.org/legal/",
                        "citation": "cite",
                        "citation_by": "source",
                        "link": "https://fred.stlouisfed.org/series/DGS2",
                        "rows": 5,
                        "specialist": "data_analyst",
                    },
                    {
                        "connector": "data-folder",
                        "series": "a.csv",
                        "files": [{"path": "data/a.csv", "sha256": "c" * 64}],
                    },
                ]
            }
        )
    )
    fred, folder = _data_sources(tmp_path)
    assert fred == {
        "connector": "fred",
        "dataset": FRED.dataset,
        "terms": "https://fred.stlouisfed.org/legal/",
        "citation": "cite",
        "series": "DGS2",
        "retrieved_at": "2026-10-04T10:00:00Z",
        "terms_summary": "short",
        "citation_by": "source",
        "link": "https://fred.stlouisfed.org/series/DGS2",
        "files": [],
    }
    assert folder["files"] == [{"path": "data/a.csv", "sha256": "c" * 64}]
