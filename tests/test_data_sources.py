"""The data architect declares only tables an available source can load (live E2E-01, 2026-10-04)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.specialists.contract_check import check_specialist_artifacts
from src.core.specialists.data_sources import check_declared_sources, sources_block


def _settings(**kw):
    return SimpleNamespace(**{"fred_api_key": None, "allium_api_key": None, "local_data_dir": None, **kw})


def _dictionary(ws: Path, tables: list[dict]) -> None:
    (ws / "data_dictionary.json").write_text(json.dumps({"tables": tables}))


def test_tables_from_unavailable_sources_are_violations_with_the_reason(tmp_path: Path):
    _dictionary(
        tmp_path,
        [
            {"name": "crsp_market_daily", "source": "crsp"},
            {"name": "dgs2", "source": "fred", "series": "DGS2"},
            {"name": "ff_factors_daily", "source": "file", "file": "ff.csv"},
            {"name": "spy_prices", "source": "yfinance", "series": "SPY"},
        ],
    )
    [check] = check_declared_sources(tmp_path, _settings())
    assert not check.ok and check.artifact == "data_dictionary.json"
    assert "table crsp_market_daily (source crsp): e2er has no connector for crsp" in check.reason
    assert "table dgs2 (source fred): fred needs FRED_API_KEY, which is not set" in check.reason
    assert "table ff_factors_daily (source file)" in check.reason and "holds no data files" in check.reason
    assert "spy_prices" not in check.reason
    assert "Available now: yfinance, gmd; no data files." in check.reason


def test_available_connectors_and_local_files_pass(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ff.csv").write_text("date,mkt\n2020-01-02,0.1\n")
    _dictionary(
        tmp_path,
        [
            {"name": "dgs2", "source": "FRED", "series": "DGS2"},
            {"name": "gmd_macro", "source": "gmd"},
            {"name": "ff_factors_daily", "source": "file", "file": "ff.csv"},
            {"name": "spy_prices", "source": "Yahoo Finance"},
        ],
    )
    assert all(c.ok for c in check_declared_sources(tmp_path, _settings(fred_api_key="k")))


def test_a_file_in_local_data_dir_counts(tmp_path: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "banks.csv").write_text("a\n1\n")
    ws = tmp_path / "ws"
    ws.mkdir()
    _dictionary(ws, [{"name": "banks", "source": "local", "file": "banks.csv"}])
    assert all(c.ok for c in check_declared_sources(ws, _settings(local_data_dir=str(shared))))


def test_the_prompt_lists_exactly_the_available_sources(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ff.csv").write_text("x\n")
    block = sources_block(tmp_path, _settings())
    assert "- `yfinance` (no key needed)" in block and "- `gmd` (no key needed)" in block
    assert "not available: `fred` (needs FRED_API_KEY, which is not set)" in block
    assert "not available: `allium` (needs ALLIUM_API_KEY, which is not set)" in block
    assert "`ff.csv`" in block
    assert "(its key FRED_API_KEY is set)" in sources_block(tmp_path, _settings(fred_api_key="k"))


def test_the_architects_contract_runs_the_source_check(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("src.config.get_settings", lambda: _settings())
    _dictionary(tmp_path, [{"name": "call_report", "source": "ffiec"}])
    failing = [c for c in check_specialist_artifacts(tmp_path, "data_architect") if not c.ok]
    assert failing and "call_report" in failing[0].reason


async def test_after_the_last_attempt_the_pause_lists_the_missing_sources(tmp_path: Path, monkeypatch):
    """The architect keeps declaring CRSP and FRED without a key: the run stops for the researcher with each reason."""
    from unittest.mock import AsyncMock, patch

    from src.config import get_settings
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import ContractFailureError, execute_parallel
    from src.modules.llm.base import ToolLoopResult
    from src.modules.tracking.usage import TokenUsage
    from tests.conftest import MockLLMBackend

    for var in ("FRED_API_KEY", "ALLIUM_API_KEY", "LOCAL_DATA_DIR"):
        monkeypatch.setenv(var, "")
    get_settings.cache_clear()

    class _Architect(MockLLMBackend):
        async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
            await tool_handler.handle(
                "write_file",
                {
                    "path": "data_dictionary.json",
                    "content": json.dumps(
                        {
                            "tables": [
                                {"name": "crsp_bank_daily", "source": "crsp"},
                                {"name": "vixcls", "source": "fred", "series": "VIXCLS"},
                            ]
                        }
                    ),
                },
            )
            return ToolLoopResult(success=True, output="ok", usage=TokenUsage(), tool_calls_made=1)

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
        pytest.raises(ContractFailureError) as exc,
    ):
        await execute_parallel(
            [WorkOrder(paper_id="p", specialist="data_architect", focus="plan")],
            _Architect(),
            tmp_path,
            "m",
            [],
            [],
            "mock",
        )
    from src.core.pipeline.researcher import contract_reasons

    get_settings.cache_clear()
    reasons = contract_reasons(exc.value.failures)
    assert len(reasons) == 3
    assert all("crsp_bank_daily (source crsp)" in r and "fred needs FRED_API_KEY" in r for r in reasons)


def test_a_supplied_table_matches_a_file_of_its_name(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fomc_dates.csv").write_text("date\n2015-12-16\n")
    _dictionary(tmp_path, [{"name": "fomc_dates", "source": "researcher-supplied"}])
    assert all(c.ok for c in check_declared_sources(tmp_path, _settings()))
    _dictionary(tmp_path, [{"name": "other_dates", "source": "researcher-supplied"}])
    [bad] = check_declared_sources(tmp_path, _settings())
    assert "files there: fomc_dates.csv" in bad.reason
