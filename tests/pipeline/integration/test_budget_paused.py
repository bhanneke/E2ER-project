"""v0.5: BudgetExceededError mid-run → PAUSED, not FAILED.

Pre-v0.5, hitting the per-paper cost cap mid-pipeline crashed out as
FAILED, indistinguishable from a real bug. The operator had no clear
resume path and the workspace was orphaned.

v0.5 catches BudgetExceededError in PipelineRunner.run(), persists
state, logs paused_budget with {spent, cap}, sets status=PAUSED, and
returns a structured envelope so the API can render the outcome and
the operator can raise --max-cost and POST /api/papers/{id}/resume.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import BudgetExceededError, PaperStatus


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
                "methodology": "empirical",
                "current_stage": "idea",
            }
        )
    )
    return ws


def _runner(tmp_path, mock_llm) -> PipelineRunner:
    paper_id = str(uuid.uuid4())
    ws = _make_workspace(tmp_path, paper_id)
    return PipelineRunner(
        paper_id=paper_id,
        workspace=ws,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
        max_cost_usd=5.0,
    )


# ---------- BudgetExceededError raised inside run() ----------


@pytest.mark.asyncio
async def test_budget_exhausted_returns_paused_envelope(tmp_path, mock_llm):
    """When check_budget raises BudgetExceededError mid-run, run() must:
    1. NOT propagate the exception (no crash to FAILED).
    2. Return {status: 'paused', reason: 'budget_exhausted', spent, cap}.
    3. Set DB status to PAUSED.
    4. Persist state to disk so the next /resume picks up correctly.
    """
    runner = _runner(tmp_path, mock_llm)

    # Capture every status the runner pushes to the DB so we can assert
    # the final one is PAUSED (not FAILED).
    seen_statuses: list[str] = []

    async def _capture_execute(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            seen_statuses.append(params["s"])

    with (
        # Make the very first phase's budget check trip. The runner calls
        # check_budget at the head of _phase(); raising there exercises
        # the new except-BudgetExceededError branch directly.
        patch(
            "src.modules.tracking.usage.check_budget",
            side_effect=BudgetExceededError(spent=7.5, cap=5.0),
        ),
        patch(
            "src.db.client.execute",
            side_effect=_capture_execute,
        ),
    ):
        result = await runner.run()

    # 1. Structured envelope returned, not a crash
    assert result["status"] == "paused"
    assert result["reason"] == "budget_exhausted"
    assert result["spent"] == pytest.approx(7.5)
    assert result["cap"] == pytest.approx(5.0)

    # 2. Final DB status set to PAUSED, not FAILED
    assert "paused" in seen_statuses, f"PAUSED status never written; saw {seen_statuses}"
    assert "failed" not in seen_statuses, (
        f"FAILED status written — budget exhaustion must NOT mark FAILED; saw {seen_statuses}"
    )

    # 3. State file persisted on disk for resume
    state_file = runner._workspace / ".pipeline_state.json"
    assert state_file.exists(), "state.json must be saved on budget pause"


@pytest.mark.asyncio
async def test_budget_exhausted_logs_paused_budget_event(tmp_path, mock_llm):
    """The structured `paused_budget` event must carry {spent, cap} so
    the dashboard can render the cost breakdown without parsing prose."""
    runner = _runner(tmp_path, mock_llm)

    events: list[tuple[str, dict | None]] = []

    async def _capture_event(paper_id, event_type, *, payload=None, stage=None):
        events.append((event_type, payload))

    with (
        patch(
            "src.modules.tracking.usage.check_budget",
            side_effect=BudgetExceededError(spent=6.0, cap=5.0),
        ),
        patch(
            "src.db.events.log_event",
            side_effect=_capture_event,
        ),
    ):
        await runner.run()

    paused = [(t, p) for t, p in events if t == "paused_budget"]
    assert paused, f"paused_budget event not logged; saw {events}"
    _, payload = paused[0]
    assert payload is not None
    assert payload["spent"] == pytest.approx(6.0)
    assert payload["cap"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_budget_pause_is_distinct_from_circuit_breaker_pause(tmp_path, mock_llm):
    """Both reach PAUSED, but the `reason` field must distinguish them
    so the operator's resume action differs (raise cap vs. fix specialist)."""
    runner = _runner(tmp_path, mock_llm)

    with patch(
        "src.modules.tracking.usage.check_budget",
        side_effect=BudgetExceededError(spent=10.0, cap=5.0),
    ):
        result = await runner.run()

    assert result["status"] == "paused"
    assert result["reason"] == "budget_exhausted"
    # circuit_breaker is the OTHER pause reason; must not collide
    assert result["reason"] != "circuit_breaker"


# ---------- PaperStatus.PAUSED transition coverage ----------


def test_paused_can_resume_into_in_progress():
    """Resume from a budget-paused paper re-enters the pipeline; the
    transition table must permit PAUSED → IN_PROGRESS."""
    from src.core.strategist.state import can_transition

    assert can_transition(PaperStatus.PAUSED, PaperStatus.IN_PROGRESS)


def test_paused_can_be_cancelled():
    """Operator gives up on a paused paper instead of resuming."""
    from src.core.strategist.state import can_transition

    assert can_transition(PaperStatus.PAUSED, PaperStatus.CANCELLED)
