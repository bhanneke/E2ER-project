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


def test_no_test_downloads_a_study_package_from_the_web(tmp_path: Path):
    """`e2er fetch` downloads through study_package.download_client: refused in every test that does not fake it."""
    import pytest

    from src.core import study_package as sp

    # Refused twice over: by e2er's own test guard (src/core/test_guard.py), and by the client conftest puts in.
    with pytest.raises(sp.PackageHostError, match="sends nothing|a test reached a real platform"):
        sp.download(
            "https://github.com/ada/demos/releases/download/demo-v1/demo-v1.e2er",
            tmp_path / "demo-v1.e2er",
            expect_bytes=10,
            expect_sha256="0" * 64,
        )
    assert not (tmp_path / "demo-v1.e2er").exists()
    sp_check = sp._check_hop
    try:
        sp._check_hop = lambda url: None  # past the guard: the conftest client still refuses
        with pytest.raises(sp.PackageHostError, match="a test reached a real platform"):
            sp.download(
                "https://github.com/x/y/releases/download/t/f.e2er",
                tmp_path / "f.e2er",
                expect_bytes=1,
                expect_sha256="0" * 64,
            )
    finally:
        sp._check_hop = sp_check


def test_no_test_reads_a_real_platform_for_a_package(tmp_path: Path):
    import pytest

    from src.cli_fetch import FetchError, resolve

    with pytest.raises(FetchError, match="a test reached a real platform"):
        resolve("https://e2er.org/bhanneke/spot-bitcoin-etf-comovement")
