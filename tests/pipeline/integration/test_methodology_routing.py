"""v0.5: methodology-aware phase routing.

Pins the contract that `methodology="theoretical"` causes the runner
to skip data_reviewer and the replication phase. Pre-v0.5 these ran
on every paper, wastefully — paper cbe8048f burned ~$0.34 on a
data_reviewer stub over an empty contract plus ~$0.43 on a
replication packager with no replication artifacts.

The wiring is plumbed:
  CreatePaperRequest.methodology → papers.methodology →
  resume_paper / _run_pipeline → PipelineRunner(methodology=...) →
  _reviewers_for_methodology + _run_replication_phase
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.specialists.registry import REVIEWER_SPECIALISTS
from src.core.strategist.runner import PipelineRunner


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
                "methodology": "theoretical",
                "current_stage": "idea",
            }
        )
    )
    return ws


def _runner(tmp_path, mock_llm, methodology: str) -> PipelineRunner:
    paper_id = str(uuid.uuid4())
    ws = _make_workspace(tmp_path, paper_id)
    return PipelineRunner(
        paper_id=paper_id,
        workspace=ws,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
        methodology=methodology,
    )


# ---------- _reviewers_for_methodology ----------


def test_theoretical_drops_data_reviewer(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm, "theoretical")
    reviewers = runner._reviewers_for_methodology()
    assert "data_reviewer" not in reviewers
    # All other reviewers must still run — dropping data_reviewer is a
    # surgical exclusion, not a wholesale roster change.
    for r in REVIEWER_SPECIALISTS:
        if r != "data_reviewer":
            assert r in reviewers, f"{r} unexpectedly dropped for theoretical"


def test_empirical_keeps_full_reviewer_panel(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm, "empirical")
    reviewers = runner._reviewers_for_methodology()
    assert set(reviewers) == set(REVIEWER_SPECIALISTS), (
        "empirical (default) must keep all 6 reviewers — pre-v0.5 behavior"
    )


def test_mixed_keeps_full_reviewer_panel(tmp_path, mock_llm):
    # `mixed` papers have both theory and empirical content; data_reviewer
    # is still meaningful.
    runner = _runner(tmp_path, mock_llm, "mixed")
    reviewers = runner._reviewers_for_methodology()
    assert "data_reviewer" in reviewers


def test_unknown_methodology_keeps_full_panel(tmp_path, mock_llm):
    """Defensive: an unrecognised methodology string MUST NOT silently
    drop reviewers. Falls back to the full roster (empirical default)."""
    runner = _runner(tmp_path, mock_llm, "garbage_value")
    reviewers = runner._reviewers_for_methodology()
    assert set(reviewers) == set(REVIEWER_SPECIALISTS)


# ---------- _run_replication_phase ----------


@pytest.mark.asyncio
async def test_theoretical_skips_replication_phase(tmp_path, mock_llm):
    """Theoretical paper: _run_replication_phase must early-return without
    dispatching the replication_packager specialist."""
    runner = _runner(tmp_path, mock_llm, "theoretical")

    # Track whether execute_work_order is called — it shouldn't be.
    with (
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            new_callable=AsyncMock,
        ) as mock_dispatch,
        patch(
            "src.modules.data.audit.write_audit_csv",
            new_callable=AsyncMock,
        ),
        patch(
            "src.modules.data.audit.write_data_queries_sql",
            new_callable=AsyncMock,
        ),
    ):
        await runner._run_replication_phase()

    assert mock_dispatch.call_count == 0, "replication_packager dispatched for theoretical paper — v0.5 routing broken"


@pytest.mark.asyncio
async def test_empirical_runs_replication_packager(tmp_path, mock_llm):
    """Empirical paper: replication_packager IS dispatched."""
    runner = _runner(tmp_path, mock_llm, "empirical")
    paper_id = runner._paper_id

    async def _fake_dispatch(*args, **kwargs):
        return Contribution(
            paper_id=paper_id,
            specialist="replication_packager",
            output="ok",
            success=True,
        )

    with (
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_fake_dispatch,
        ) as mock_dispatch,
        patch(
            "src.modules.data.audit.write_audit_csv",
            new_callable=AsyncMock,
        ),
        patch(
            "src.modules.data.audit.write_data_queries_sql",
            new_callable=AsyncMock,
        ),
    ):
        await runner._run_replication_phase()

    assert mock_dispatch.call_count == 1
    # The dispatched work order targets replication_packager
    work_order = mock_dispatch.call_args[0][0]
    assert work_order.specialist == "replication_packager"


# ---------- methodology defaults ----------


def test_runner_default_methodology_is_empirical(tmp_path, mock_llm):
    """Backwards compat: callers that don't pass methodology must get
    the v0.4.x empirical behaviour."""
    paper_id = str(uuid.uuid4())
    ws = _make_workspace(tmp_path, paper_id)
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=ws,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )
    assert runner._methodology == "empirical"
    assert set(runner._reviewers_for_methodology()) == set(REVIEWER_SPECIALISTS)
