"""Governance regime + shadow mode (WS-B).

The regime (off | contracts | full) is the experiment's treatment variable:
it selects which gates BLOCK. Non-blocking gates still compute their verdict
and log a `gate_shadow` event, so fabrication that the full stack would have
caught is measured, not merely absent.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.core.strategist.runner import PipelineRunner


def _bare_runner(governance: str) -> PipelineRunner:
    """A PipelineRunner with only the attributes the gate logic touches —
    avoids constructing a real backend / StrategistEngine."""
    r = PipelineRunner.__new__(PipelineRunner)
    r._governance = governance
    r._paper_id = "p-test"
    r._methodology = "empirical"
    r._failure_counts = {}
    return r


# ── config + request model ──────────────────────────────────────────────────


def test_config_default_is_full():
    from src.config import Settings

    assert Settings().governance == "full"


def test_config_accepts_regimes():
    from src.config import Settings

    for regime in ("off", "contracts", "full"):
        assert Settings(governance=regime).governance == regime


def test_config_rejects_bad_regime():
    from src.config import Settings

    with pytest.raises(Exception):
        Settings(governance="lenient")


def test_request_governance_field():
    from src.api.app import CreatePaperRequest

    default = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q"})
    assert default.governance is None
    given = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q", "governance": "off"})
    assert given.governance == "off"


# ── enforcement matrix ──────────────────────────────────────────────────────


def test_enforcement_matrix_full():
    r = _bare_runner("full")
    for gate in ("contracts", "estimation", "numbers", "citations"):
        assert r._governance_enforces(gate) is True


def test_enforcement_matrix_contracts():
    r = _bare_runner("contracts")
    assert r._governance_enforces("contracts") is True
    for gate in ("estimation", "numbers", "citations"):
        assert r._governance_enforces(gate) is False


def test_enforcement_matrix_off():
    r = _bare_runner("off")
    for gate in ("contracts", "estimation", "numbers", "citations"):
        assert r._governance_enforces(gate) is False


def test_unknown_regime_falls_back_to_full():
    r = _bare_runner("bogus")
    assert r._governance_enforces("numbers") is True


# ── _record_gate: event type + return value ─────────────────────────────────


async def test_record_gate_shadow_when_not_enforced():
    r = _bare_runner("off")
    with patch("src.db.events.log_event", new=AsyncMock()) as le:
        enforced = await r._record_gate("numbers", passed=False, detail="2 mismatches")
    assert enforced is False
    (_pid, event_type), kwargs = le.call_args[0], le.call_args[1]
    assert event_type == "gate_shadow"
    assert kwargs["payload"]["gate"] == "numbers"
    assert kwargs["payload"]["passed"] is False
    assert kwargs["payload"]["regime"] == "off"


async def test_record_gate_enforced_when_enforced():
    r = _bare_runner("full")
    with patch("src.db.events.log_event", new=AsyncMock()) as le:
        enforced = await r._record_gate("numbers", passed=False, detail="x")
    assert enforced is True
    assert le.call_args[0][1] == "gate_enforced"


# ── behavioral: estimation-gate shadow does not re-dispatch or raise ─────────


async def test_estimation_gate_shadow_does_not_dispatch_for_verification(tmp_path: Path):
    """In a non-enforcing regime a failing VERIFICATION contract is logged and
    the run continues — no re-dispatch, no circuit breaker."""
    from src.core.specialists.contract_check import KIND_VERIFICATION, ContractCheck

    r = _bare_runner("off")
    r._workspace = tmp_path

    failing = [ContractCheck("estimation_results.json", False, "no coefficients block", kind=KIND_VERIFICATION)]
    dispatch = AsyncMock(side_effect=AssertionError("must not re-dispatch in shadow mode"))
    with (
        patch("src.db.paper_data_db.has_data_db", return_value=True),
        patch("src.core.specialists.contract_check.check_specialist_artifacts", return_value=failing),
        patch("src.core.specialists.dispatcher.execute_work_order", new=dispatch),
        patch("src.db.events.log_event", new=AsyncMock()) as le,
    ):
        await r._enforce_estimation_gate()  # returns cleanly, no raise
    assert le.call_args[0][1] == "gate_shadow"
    assert le.call_args[1]["payload"]["gate"] == "estimation"
    assert le.call_args[1]["payload"]["passed"] is False


async def test_estimation_gate_repairs_reliability_even_under_off(tmp_path: Path):
    """An EMPTY estimation file is a broken run, not an ungoverned one, so the
    gate re-dispatches to repair it in every regime.

    This test previously asserted the opposite. Letting `{}` through under
    `off` is what produced the 2026-08-05 cell: the crashed script's traceback
    was never fed back, and the drafter wrote four tables over the hole.
    """
    from src.core.specialists.contract_check import KIND_RELIABILITY, ContractCheck

    r = _bare_runner("off")
    r._workspace = tmp_path
    # The repair path actually dispatches, so it needs the dispatch arguments
    # and the circuit-breaker bookkeeping.
    r._backend = None
    r._model = "claude-test"
    r._extra_tools = []
    r._extra_handlers = []
    r._backend_name = "mock"
    r._contributions = []
    r._last_specialist_errors = {}

    empty = [ContractCheck("estimation_results.json", False, "empty JSON ('{}')", kind=KIND_RELIABILITY)]
    dispatch = AsyncMock(
        return_value=SimpleNamespace(success=True, error=None, specialist="econometrics_specialist", paper_id="p-test")
    )
    with (
        patch("src.db.paper_data_db.has_data_db", return_value=True),
        patch(
            "src.core.specialists.contract_check.check_specialist_artifacts",
            side_effect=[empty, empty, []],
        ),
        patch("src.core.specialists.dispatcher.execute_work_order", new=dispatch),
        patch("src.db.events.log_event", new=AsyncMock()),
    ):
        await r._enforce_estimation_gate()

    assert dispatch.await_count == 1, "a hollow estimation file must be repaired, even under `off`"


async def test_estimation_gate_skips_non_empirical():
    r = _bare_runner("off")
    r._methodology = "theoretical"
    # Returns immediately, before touching has_data_db.
    await r._enforce_estimation_gate()
