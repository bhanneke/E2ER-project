"""Lane A — circuit breaker on specialist re-dispatch.

Pins the fix for run #14's failure mode: when Allium was unrecoverably
down, the strategist re-dispatched data_analyst 3+ times and the pipeline
burned 13 specialist invocations before manual cancel.

The breaker now halts after _MAX_SPECIALIST_ATTEMPTS=3 consecutive
failures on a non-tolerant specialist, sets status=PAUSED, and returns
a structured envelope so the operator (or /api/papers/{id}/resume) can
recover from a known checkpoint.

Tolerant specialists (reviewers, polish) are exempt — their failures
should not block downstream work.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.strategist.actions import StrategistDecision, WorkOrder
from src.core.strategist.runner import _MAX_SPECIALIST_ATTEMPTS, PipelineRunner
from src.core.strategist.state import CircuitBreakerError


def _make_workspace(tmp_path: Path, paper_id: str) -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": paper_id,
                "title": "Test",
                "research_question": "Test?",
                "datasets": [],
                "mode": "single_pass",
                "current_stage": "idea",
            }
        )
    )
    return ws


def _failing_contribution(specialist: str, paper_id: str) -> Contribution:
    return Contribution(
        paper_id=paper_id,
        specialist=specialist,
        output="",
        success=False,
        error="Allium 429 retries exhausted; data layer unrecoverable.",
    )


def _successful_contribution(specialist: str, paper_id: str) -> Contribution:
    return Contribution(
        paper_id=paper_id,
        specialist=specialist,
        output="ok",
        success=True,
    )


# ---------- direct unit tests on the breaker ----------


def test_failure_counter_increments_on_non_tolerant_failure(tmp_path, mock_llm):
    """Non-tolerant specialist failing increments its counter."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id)
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )

    runner._update_failure_counts([_failing_contribution("data_analyst", paper_id)])
    runner._update_failure_counts([_failing_contribution("data_analyst", paper_id)])

    assert runner._failure_counts["data_analyst"] == 2


def test_failure_counter_resets_on_success(tmp_path, mock_llm):
    """A specialist that recovers (success after failures) resets to 0."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id)
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )

    runner._update_failure_counts([_failing_contribution("data_analyst", paper_id)])
    runner._update_failure_counts([_failing_contribution("data_analyst", paper_id)])
    runner._update_failure_counts([_successful_contribution("data_analyst", paper_id)])

    assert "data_analyst" not in runner._failure_counts


def test_failure_counter_ignores_tolerant_specialists(tmp_path, mock_llm):
    """Reviewer + polish failures must NOT increment a counter.

    Reviewers are expected to occasionally fail (model returns malformed
    output, etc.). They have an aggregator + cascade tolerance built in;
    treating their failures as breaker-eligible would halt the pipeline
    every time one reviewer hiccupped.
    """
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id)
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )

    for _ in range(5):
        runner._update_failure_counts([_failing_contribution("mechanism_reviewer", paper_id)])
        runner._update_failure_counts([_failing_contribution("polish_formula", paper_id)])

    assert runner._failure_counts == {}, f"Tolerant specialists should not be tracked: {runner._failure_counts}"


@pytest.mark.asyncio
async def test_dispatch_trips_breaker_after_max_attempts(tmp_path, mock_llm):
    """After 3 consecutive failures, _dispatch raises CircuitBreakerError."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id)
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )

    # Manually drive the counter to the threshold — same effect as 3 real
    # failed dispatches, without the cost of running them.
    runner._failure_counts["data_analyst"] = _MAX_SPECIALIST_ATTEMPTS
    runner._last_specialist_errors["data_analyst"] = "Allium degraded"

    decision = StrategistDecision(
        action="dispatch_parallel",
        work_orders=[WorkOrder(specialist="data_analyst", focus="retry", parallel_group=0)],
        rationale="strategist is hopeful, breaker should disagree",
    )

    with pytest.raises(CircuitBreakerError) as exc:
        await runner._dispatch(decision)

    assert exc.value.specialist == "data_analyst"
    assert exc.value.attempts == _MAX_SPECIALIST_ATTEMPTS
    assert exc.value.last_error == "Allium degraded"


@pytest.mark.asyncio
async def test_dispatch_does_not_trip_for_tolerant_specialist(tmp_path, mock_llm):
    """Even with high failure count, a tolerant specialist must not trip the breaker.

    The dispatcher's existing cascade-tolerance is the right layer to
    handle reviewer / polish failures; the breaker is one level up and
    must not duplicate that policy.
    """
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id)
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )

    # Pre-load counters as if mechanism_reviewer had failed 10 times — should
    # never have been tracked in real life, but the breaker must also be
    # robust to manual / scripted counter manipulation.
    runner._failure_counts["mechanism_reviewer"] = 10
    decision = StrategistDecision(
        action="dispatch_parallel",
        work_orders=[WorkOrder(specialist="mechanism_reviewer", focus="review", parallel_group=0)],
        rationale="re-running reviewer",
    )

    # Patch out the actual specialist execution so this test runs in <1ms.
    with patch(
        "src.core.specialists.dispatcher.execute_work_order",
        new=AsyncMock(return_value=_successful_contribution("mechanism_reviewer", paper_id)),
    ):
        contributions = await runner._dispatch(decision)

    # Got past the breaker check, dispatch returned normally.
    assert len(contributions) == 1
    assert contributions[0].success is True


# ---------- end-to-end: runner halts cleanly with PAUSED ----------


@pytest.mark.asyncio
async def test_runner_run_halts_at_paused_on_breaker(tmp_path, mock_llm):
    """When the breaker trips inside run(), the runner returns
    {"status": "paused", "reason": "circuit_breaker", ...} and the paper
    status is PAUSED, not FAILED.

    Without this, the run #14 failure mode looks identical to "real" bugs
    in the events table — and operators have no resume path.
    """
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id)

    # Patch dispatcher so the FIRST decision dispatch fails 3 times via
    # _update_failure_counts, then on the next iteration the breaker fires.
    # Easiest path: prime the counter, then make the strategist re-dispatch
    # the same specialist.
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )
    runner._failure_counts["data_analyst"] = _MAX_SPECIALIST_ATTEMPTS
    runner._last_specialist_errors["data_analyst"] = "Allium 429s"

    decision = StrategistDecision(
        action="dispatch_parallel",
        work_orders=[WorkOrder(specialist="data_analyst", focus="retry", parallel_group=0)],
        rationale="",
    )

    from src.core.strategist.engine import StrategistEngine

    with (
        patch.object(StrategistEngine, "decide", return_value=decision),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        result = await runner.run()

    assert result["status"] == "paused"
    assert result["reason"] == "circuit_breaker"
    assert result["specialist"] == "data_analyst"
    assert result["attempts"] == _MAX_SPECIALIST_ATTEMPTS
