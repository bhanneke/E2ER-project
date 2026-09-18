"""Deterministic estimation phase gate.

Run D (2026-07-07) regression: econometrics failed its output contract once,
the strategist moved on anyway, and the pipeline spent self-attack / polish /
review tokens drafting a paper around ``estimation_results.json == {}`` — the
M4 failure shape one level up. The gate blocks every drafting-dependent phase
for empirical papers with a populated data warehouse until the estimation is
contract-clean, re-dispatching econometrics (coached by its consume-once
contract feedback) and tripping the circuit breaker into a resumable PAUSED
instead of producing a hollow paper."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.strategist.state import CircuitBreakerError


def _runner(tmp_path: Path, methodology: str = "empirical"):
    from src.core.strategist.runner import PipelineRunner

    return PipelineRunner(
        paper_id="p1",
        workspace=tmp_path,
        backend=MagicMock(),
        model="test-model",
        mode="iterative",
        backend_name="claude_code",
        max_cost_usd=5.0,
        methodology=methodology,
    )


def _write_clean_econometrics(ws: Path) -> None:
    (ws / "econometric_spec.md").write_text("# Spec\n" + "content " * 30, encoding="utf-8")
    (ws / "estimation_results.json").write_text(
        json.dumps(
            {
                "main": {
                    "coefficients": {"treat": {"estimate": 0.1, "se": 0.02}},
                    "diagnostics": {"n_observations": 100},
                }
            }
        ),
        encoding="utf-8",
    )


def _contribution(success: bool) -> Contribution:
    return Contribution(
        paper_id="p1",
        specialist="econometrics_specialist",
        output="done",
        success=success,
        error="" if success else "contract violation: estimation_results.json: empty JSON ('{}')",
    )


async def test_gate_noop_for_theoretical(tmp_path: Path):
    runner = _runner(tmp_path, methodology="theoretical")
    (tmp_path / "data.db").write_text("x", encoding="utf-8")
    with patch("src.core.specialists.dispatcher.execute_work_order", new=AsyncMock()) as ew:
        await runner._enforce_estimation_gate()
    ew.assert_not_awaited()


async def test_gate_noop_without_data_warehouse(tmp_path: Path):
    runner = _runner(tmp_path)
    with patch("src.core.specialists.dispatcher.execute_work_order", new=AsyncMock()) as ew:
        await runner._enforce_estimation_gate()
    ew.assert_not_awaited()


async def test_gate_passes_clean_estimation_without_dispatch(tmp_path: Path):
    runner = _runner(tmp_path)
    (tmp_path / "data.db").write_text("x", encoding="utf-8")
    _write_clean_econometrics(tmp_path)
    with patch("src.core.specialists.dispatcher.execute_work_order", new=AsyncMock()) as ew:
        await runner._enforce_estimation_gate()
    ew.assert_not_awaited()


async def test_gate_redispatches_until_clean(tmp_path: Path):
    """Empty {} estimation → one re-dispatch that fixes it → gate opens."""
    runner = _runner(tmp_path)
    (tmp_path / "data.db").write_text("x", encoding="utf-8")
    (tmp_path / "econometric_spec.md").write_text("# Spec\n" + "content " * 30, encoding="utf-8")
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")

    async def _fix(order, *args, **kwargs):
        _write_clean_econometrics(tmp_path)
        return _contribution(success=True)

    with patch("src.core.specialists.dispatcher.execute_work_order", new=AsyncMock(side_effect=_fix)) as ew:
        await runner._enforce_estimation_gate()
    assert ew.await_count == 1
    order = ew.await_args.args[0]
    assert order.specialist == "econometrics_specialist"
    assert runner._failure_counts.get("econometrics_specialist", 0) == 0  # success resets
    assert len(runner._contributions) == 1


async def test_gate_trips_breaker_after_cap(tmp_path: Path):
    """Re-dispatches that never fix the estimation end in CircuitBreakerError
    (→ resumable PAUSED), not an infinite loop and not a hollow paper."""
    runner = _runner(tmp_path)
    (tmp_path / "data.db").write_text("x", encoding="utf-8")
    (tmp_path / "econometric_spec.md").write_text("# Spec\n" + "content " * 30, encoding="utf-8")
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")

    with patch(
        "src.core.specialists.dispatcher.execute_work_order",
        new=AsyncMock(return_value=_contribution(success=False)),
    ) as ew:
        with pytest.raises(CircuitBreakerError):
            await runner._enforce_estimation_gate()
    # attempts 0,1,2 dispatch; at 3 the breaker trips before a 4th call
    assert ew.await_count == 3


async def test_gate_respects_preexisting_failure_count(tmp_path: Path):
    """Failures accumulated during the iterative phase count toward the cap."""
    runner = _runner(tmp_path)
    (tmp_path / "data.db").write_text("x", encoding="utf-8")
    (tmp_path / "econometric_spec.md").write_text("# Spec\n" + "content " * 30, encoding="utf-8")
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")
    runner._failure_counts["econometrics_specialist"] = 3

    with patch("src.core.specialists.dispatcher.execute_work_order", new=AsyncMock()) as ew:
        with pytest.raises(CircuitBreakerError):
            await runner._enforce_estimation_gate()
    ew.assert_not_awaited()
