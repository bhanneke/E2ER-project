"""The suite's shared stubs: the recording database stub and the settings reset before every test."""

from __future__ import annotations

from pathlib import Path

from src.config import get_settings
from src.core.pipeline.state import PipelineState
from src.core.strategist.state import PaperStatus
from tests.test_run_status_2026_10_15 import PID, _runner


async def test_the_db_stub_records_a_runner_s_status_write(tmp_path: Path, db_stub):
    """A runner test without its own database fixture sees the status the runner wrote (or did not)."""
    r = _runner(tmp_path, PipelineState(paper_id=PID, mode="single_pass"))
    assert db_stub.statuses() == []
    await r._update_status(PaperStatus.PAUSED, error="Stopped for you")
    assert db_stub.statuses() == ["paused"]
    (sql, params), *_ = db_stub.writes("UPDATE papers SET status")
    assert params["e"] == "Stopped for you"


async def test_each_test_gets_its_own_db_stub(db_stub):
    assert db_stub.statuses() == [] and db_stub.writes() == []


def test_settings_set_by_one_test(monkeypatch):
    monkeypatch.setenv("DEFAULT_MAX_COST_USD", "7.5")
    assert get_settings().default_max_cost_usd == 7.5  # no cache_clear: the reset before the test did it


def test_are_not_seen_by_the_next():
    """Runs after the test above (file order): its setting is gone with its environment."""
    assert get_settings().default_max_cost_usd == 25.0
