"""v0.5: REJECTED is distinct from FAILED.

FAILED means the pipeline crashed (uncaught exception).
REJECTED means the pipeline ran successfully and the quality gate
returned a negative verdict (verify_numbers critical mismatch,
HARD_REJECT, MECHANISM_FAIL).

The distinction matters because:
- The dashboard renders them differently
- REJECTED is resumable (operator revises source artifacts and
  POSTs /resume); FAILED requires debugging the crash first
- v0.4.5 live tests conflated both, leaving operators unable to
  tell at a glance which kind of halt had happened
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import (
    VALID_TRANSITIONS,
    PaperStatus,
    can_transition,
)


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
    )


# ===========================================================================
# State-machine transitions
# ===========================================================================


class TestRejectedTransitions:
    def test_rejected_is_a_status(self):
        # Pinned: existence + spelling. If this fails, the v0.5 enum was
        # removed/renamed and the DB column constraint will desync.
        assert PaperStatus.REJECTED.value == "rejected"

    def test_in_progress_can_transition_to_rejected(self):
        # verify_numbers gate path: critical mismatch fires before review
        # phase enters, runner transitions IN_PROGRESS → REJECTED.
        assert can_transition(PaperStatus.IN_PROGRESS, PaperStatus.REJECTED)

    def test_review_can_transition_to_rejected(self):
        # HARD_REJECT / MECHANISM_FAIL from the aggregator.
        assert can_transition(PaperStatus.REVIEW, PaperStatus.REJECTED)

    def test_revision_can_transition_to_rejected(self):
        # The revisor's revised draft still HARD_REJECTs on re-review.
        assert can_transition(PaperStatus.REVISION, PaperStatus.REJECTED)

    def test_rejected_can_transition_to_idea(self):
        # Operator opts to restart from scratch.
        assert can_transition(PaperStatus.REJECTED, PaperStatus.IDEA)

    def test_rejected_can_transition_to_resumable_phases(self):
        # Resume support: operator revises artifacts then POSTs /resume,
        # which re-enters IN_PROGRESS / REVIEW / REVISION.
        for target in (
            PaperStatus.IN_PROGRESS,
            PaperStatus.REVIEW,
            PaperStatus.REVISION,
            PaperStatus.CANCELLED,
        ):
            assert can_transition(PaperStatus.REJECTED, target), f"REJECTED → {target} must be allowed for resume"

    def test_rejected_does_not_transition_to_completed(self):
        # Quality reject must not skip to completed without going through
        # a revision phase. The transition table should refuse it.
        assert not can_transition(PaperStatus.REJECTED, PaperStatus.COMPLETED)

    def test_rejected_is_not_failed(self):
        # The two terminal-ish reasons must remain distinct in the table.
        # Both REJECTED and FAILED are reachable from REVIEW, but FAILED's
        # outgoing set is {IDEA} only; REJECTED has broader resume options.
        rejected_out = VALID_TRANSITIONS.get(PaperStatus.REJECTED, set())
        failed_out = VALID_TRANSITIONS.get(PaperStatus.FAILED, set())
        assert rejected_out != failed_out, (
            "REJECTED and FAILED must have distinct outgoing transitions — "
            "otherwise there's no behavioural reason to keep them separate"
        )
        # Specifically, FAILED should NOT have a direct IN_PROGRESS resume
        # path (a crash needs investigation first).
        assert PaperStatus.IN_PROGRESS not in failed_out


# ===========================================================================
# verify_numbers gate → REJECTED
# ===========================================================================


@pytest.mark.asyncio
async def test_verify_numbers_critical_mismatch_yields_rejected(tmp_path, mock_llm):
    """A draft with hallucinated table numbers must not reach reviewers.

    Setup: draft cites 0.41 for log_rv coefficient; source JSON says -0.23.
    Run: _run_review_phase.
    Expect: returns REJECTED, no reviewers dispatched.
    """
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    # Hallucinated draft: claims 0.80, source says 0.50. Sign matches;
    # diff=0.30, within |draft|*0.5=0.40 so the closest-value branch fires;
    # rel_err = 0.30 / max(1, |0.50|) = 0.30 > 0.10 threshold → critical
    # mismatch (the runner gates only on critical).
    (ws / "paper_draft.tex").write_text(
        r"""
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
log RV & 0.80 & 0.10 \\
\bottomrule
\end{tabular}
"""
    )
    (ws / "estimation_results.json").write_text(json.dumps({"log_rv": {"coef": 0.50, "se": 0.10}}))

    with patch(
        "src.core.strategist.runner.execute_parallel",
        new_callable=AsyncMock,
    ) as mock_parallel:
        result = await runner._run_review_phase()

    assert result == PaperStatus.REJECTED, f"verify_numbers critical mismatch must yield REJECTED, got {result}"
    assert mock_parallel.call_count == 0, "Reviewers must NOT be dispatched when verify_numbers gate trips"

    # number_verification.json was persisted (the gate runs verify_and_save,
    # which always writes the report regardless of pass/fail).
    assert (ws / "number_verification.json").exists()


@pytest.mark.asyncio
async def test_verify_numbers_no_source_files_runs_reviewers_anyway(tmp_path, mock_llm):
    """Graceful skip: if no source JSON files exist (old paper, or analyst
    contract not yet tightened), the gate must NOT block reviewers."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace
    (ws / "paper_draft.tex").write_text(
        r"""
\begin{tabular}{lc}
x & 0.42 \\
\end{tabular}
"""
    )
    # No estimation_results.json or summary_statistics.json files.

    async def _fake_parallel(orders, *args, **kwargs):
        return [
            Contribution(
                paper_id=runner._paper_id,
                specialist=o.specialist,
                output="",
                success=True,
            )
            for o in orders
        ]

    with patch(
        "src.core.strategist.runner.execute_parallel",
        side_effect=_fake_parallel,
    ) as mock_parallel:
        result = await runner._run_review_phase()

    assert result == PaperStatus.REVIEW
    # Reviewers WERE dispatched — graceful skip means the gate doesn't block.
    assert mock_parallel.call_count == 1


@pytest.mark.asyncio
async def test_verify_numbers_no_draft_runs_reviewers_anyway(tmp_path, mock_llm):
    """If paper_draft.tex is missing (single_pass that never generated one),
    the gate must NOT block — the cascade-detection elsewhere handles that."""
    runner = _runner(tmp_path, mock_llm)

    async def _fake_parallel(orders, *args, **kwargs):
        return [
            Contribution(
                paper_id=runner._paper_id,
                specialist=o.specialist,
                output="",
                success=True,
            )
            for o in orders
        ]

    with patch(
        "src.core.strategist.runner.execute_parallel",
        side_effect=_fake_parallel,
    ) as mock_parallel:
        result = await runner._run_review_phase()

    assert result == PaperStatus.REVIEW
    assert mock_parallel.call_count == 1


# ===========================================================================
# Aggregator HARD_REJECT → REJECTED (not FAILED)
# ===========================================================================


@pytest.mark.asyncio
async def test_hard_reject_verdict_yields_rejected_not_failed(tmp_path, mock_llm):
    """When the review aggregator emits HARD_REJECT, the revision phase
    must transition to REJECTED. Pre-v0.5 this was FAILED, which masked
    the distinction between 'reviewers rejected it' and 'pipeline crashed'."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    # Write reviewer files that the aggregator will parse as HARD_REJECT.
    # The aggregator's 3-rule system fires HARD_REJECT when the weighted
    # average is low enough or specific reject-marker rules trigger.
    # We bypass the aggregator entirely by patching it.
    from src.core.strategist import review_aggregator

    class _ScoreStub:
        specialist = "technical_reviewer"
        score = 2
        recommendation = "Reject"

    class _Result:
        verdict = "HARD_REJECT"
        weighted_avg = 2.0
        rule_triggered = "technical_reviewer score <= 3"
        rationale = "fundamental flaws"

    # Write one reviewer file so the file-on-disk reader path picks up
    # at least one parseable score.
    (ws / "review_technical.md").write_text("Technical review.\n\nOVERALL SCORE: 2/10\nRECOMMENDATION: Reject\n")

    with (
        patch.object(
            review_aggregator,
            "parse_review_output",
            return_value=_ScoreStub(),
        ),
        patch.object(
            review_aggregator,
            "aggregate_reviews",
            return_value=_Result(),
        ),
        patch(
            "src.core.strategist.runner.aggregate_reviews",
            return_value=_Result(),
        ),
        patch(
            "src.core.strategist.runner.parse_review_output",
            return_value=_ScoreStub(),
        ),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    assert result == PaperStatus.REJECTED, f"HARD_REJECT must yield REJECTED (not FAILED), got {result}"
