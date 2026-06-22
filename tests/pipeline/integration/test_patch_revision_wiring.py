"""v0.6 step 3: wire MAJOR_REVISION through patch_revisor.

Pre-v0.6, MAJOR_REVISION dispatched the generic `revisor` which
rewrote `paper_draft.tex` from scratch based on the aggregator's
prose rationale. v0.6 replaces this with the scoped `patch_revisor`
which writes a structured patch file; the merger applies only the
in-scope edits.

This module pins:
1. MAJOR_REVISION dispatches `patch_revisor`, NOT `revisor`.
2. Findings are collected from review scores + (when present)
   the verify_numbers report; serialised into the work order's
   `focus` so the patch_revisor can read them.
3. Merger applies the patch → COMPLETED.
4. Patch achieves nothing (missing patch file, or zero edits applied)
   → REJECTED with a structured error.
4b. Partial application (some in-scope edits apply; others dropped as
   out-of-scope or unmatchable) → COMPLETED — progress is not failure.
5. MAJOR_REVISION with no actionable findings → COMPLETED with a
   warning (skipped patch_revisor entirely).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import PaperStatus

_DRAFT = r"""\documentclass{article}
\begin{document}

\begin{abstract}
The treatment effect is 0.80 according to our estimates.
\end{abstract}

\section{Identification Strategy}
The parallel-trends assumption holds, as we verify in our setting.

\section{Results}
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
log RV & 0.80 & 0.10 \\
\bottomrule
\end{tabular}

\end{document}
"""


def _make_workspace(tmp_path: Path, paper_id: str) -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": paper_id,
                "title": "Test",
                "research_question": "test?",
                "datasets": [],
                "mode": "single_pass",
                "methodology": "empirical",
                "current_stage": "review",
            }
        )
    )
    (ws / "paper_draft.tex").write_text(_DRAFT)
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


def _review_file(ws: Path, reviewer: str, score: float, recommendation: str) -> None:
    """Write a minimal review file the existing parser will accept."""
    artifact = {
        "identification_reviewer": "review_identification.md",
        "technical_reviewer": "review_technical.md",
        "mechanism_reviewer": "review_mechanism.md",
        "literature_reviewer": "review_literature.md",
        "data_reviewer": "review_data.md",
        "writing_reviewer": "review_writing.md",
    }[reviewer]
    (ws / artifact).write_text(
        f"# Review from {reviewer}\n\nThe paper has issues.\n\n"
        f"OVERALL SCORE: {score:.1f}/10\nRECOMMENDATION: {recommendation}\n"
    )


# ---------------------------------------------------------------------------
# Happy path: MAJOR_REVISION → patch_revisor → merger applies → COMPLETED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_major_revision_dispatches_patch_revisor_not_legacy_revisor(tmp_path, mock_llm):
    """Pre-v0.6 dispatched specialist='revisor'; v0.6 dispatches
    specialist='patch_revisor'. Pinned so any regression that
    re-introduces the full-rewrite revisor fails this test."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    # Write a reviewer file that triggers MAJOR_REVISION via aggregator
    # (one reviewer at score 4.5 — below the 5 average but above
    # HARD_REJECT and MECHANISM_FAIL thresholds).
    _review_file(ws, "identification_reviewer", 4.5, "Major Revision")
    _review_file(ws, "technical_reviewer", 5.5, "Major Revision")
    _review_file(ws, "mechanism_reviewer", 6.0, "Minor Revision")

    # Track which specialist gets dispatched
    dispatched_specialists: list[str] = []

    async def _capture_dispatch(work_order, *args, **kwargs):
        dispatched_specialists.append(work_order.specialist)
        # Simulate patch_revisor writing a valid patch file
        if work_order.specialist == "patch_revisor":
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "section:identification",
                            "edit_type": "replace_text",
                            "find": "The parallel-trends assumption holds",
                            "replace": "The parallel-trends assumption is examined in Figure 2",
                        }
                    ]
                )
            )
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    # Mock aggregator to force MAJOR_REVISION (so we don't have to
    # carefully tune scores against the aggregator's rule order).
    class _Result:
        verdict = "MAJOR_REVISION"
        weighted_avg = 4.5
        rule_triggered = "weighted_avg < 5"
        rationale = "identification weak"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture_dispatch),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    assert result == PaperStatus.COMPLETED
    assert dispatched_specialists == ["patch_revisor"], (
        f"v0.6 must dispatch patch_revisor; saw {dispatched_specialists}"
    )
    # Patch was applied: draft now contains the new phrase and not the old one
    patched = (ws / "paper_draft.tex").read_text()
    assert "The parallel-trends assumption is examined in Figure 2" in patched
    assert "The parallel-trends assumption holds" not in patched
    # Diff side artifact emitted
    assert (ws / "paper_draft.tex.applied.diff").is_file()


# ---------------------------------------------------------------------------
# Findings serialised into the focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_findings_serialised_into_patch_revisor_focus(tmp_path, mock_llm):
    """The patch_revisor needs to see the structured findings in its
    work order so it knows what to fix. v0.6 contract: findings
    appear as a JSON block in the focus."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    _review_file(ws, "identification_reviewer", 3.0, "Reject")

    captured_focus = [""]

    async def _capture_focus(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            captured_focus[0] = work_order.focus
            (ws / "paper_draft.tex.edits.json").write_text("[]")
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    class _Result:
        verdict = "MAJOR_REVISION"
        weighted_avg = 3.0
        rule_triggered = "weighted_avg < 5"
        rationale = "identification critical"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture_focus),
    ):
        await runner._run_revision_phase(PaperStatus.REVIEW)

    focus = captured_focus[0]
    assert "FINDINGS" in focus
    assert "section:identification" in focus
    assert "identification_reviewer" in focus
    # Must be valid embedded JSON (fenced)
    assert "```json" in focus
    assert "```" in focus


# ---------------------------------------------------------------------------
# Failure modes → REJECTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_patch_file_yields_rejected(tmp_path, mock_llm):
    """patch_revisor succeeds (the LLM call returns) but doesn't write
    the patch file. Merger raises FileNotFoundError; runner transitions
    to REJECTED with a clear error rather than crashing as FAILED."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    _review_file(ws, "identification_reviewer", 3.0, "Major Revision")

    async def _no_patch_file(work_order, *args, **kwargs):
        # Deliberately do NOT write paper_draft.tex.edits.json
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    class _Result:
        verdict = "MAJOR_REVISION"
        weighted_avg = 3.0
        rule_triggered = "weighted_avg < 5"
        rationale = "test"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_no_patch_file),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    assert result == PaperStatus.REJECTED


@pytest.mark.asyncio
async def test_failed_edits_yield_rejected_with_structured_error(tmp_path, mock_llm, monkeypatch):
    """When the patch_revisor emits edits that fail to apply (target
    not found, find ambiguous, etc.), the runner transitions to
    REJECTED with the first failures named in last_error so the
    operator can fix them without parsing the events log."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    _review_file(ws, "identification_reviewer", 3.0, "Major Revision")

    # Capture status updates so we can read what was written
    seen: list[tuple[str, str | None]] = []

    async def _capture_status(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            seen.append((params["s"], params.get("e")))

    async def _bad_patch(work_order, *args, **kwargs):
        # Patch references a phantom section
        if work_order.specialist == "patch_revisor":
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "section:identification",  # in scope
                            "edit_type": "replace_text",
                            "find": "never appears in the draft text",
                            "replace": "x",
                        }
                    ]
                )
            )
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    class _Result:
        verdict = "MAJOR_REVISION"
        weighted_avg = 3.0
        rule_triggered = "weighted_avg < 5"
        rationale = "test"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_bad_patch),
        patch("src.db.client.execute", side_effect=_capture_status),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    assert result == PaperStatus.REJECTED
    # Error message names the failure
    rejected_rows = [(s, e) for s, e in seen if s == "rejected"]
    assert rejected_rows, f"no rejected status written; saw {seen}"
    _, error = rejected_rows[-1]
    assert error is not None
    assert "patch_revisor" in error
    assert "[section:identification]" in error
    assert "not found" in error.lower()


# ---------------------------------------------------------------------------
# Partial application (in-scope edit applies, out-of-scope edit dropped) →
# COMPLETED. Regression for the M5 run that REJECTED a paper because
# patch_revisor over-reached with one `paper:full` edit alongside good ones.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_application_with_out_of_scope_edit_completes(tmp_path, mock_llm):
    """patch_revisor emits an in-scope edit that applies PLUS an over-reaching
    out-of-scope `paper:full` edit. The merger drops the out-of-scope one
    (scope enforcement), but the in-scope edit revised the draft — so the
    paper COMPLETES, not REJECTED. Rejecting over one dropped edit threw away
    a near-complete paper (M5 run 0495a50d)."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace
    _review_file(ws, "identification_reviewer", 3.0, "Major Revision")

    seen: list[tuple[str, str | None]] = []

    async def _capture_status(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            seen.append((params["s"], params.get("e")))

    async def _mixed_patch(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "section:identification",  # in scope, applies
                            "edit_type": "replace_text",
                            "find": "parallel-trends assumption holds",
                            "replace": "parallel-trends assumption is tested",
                        },
                        {
                            "target": "paper:full",  # out-of-scope over-reach → dropped
                            "edit_type": "replace_text",
                            "find": "0.80",
                            "replace": "0.50",
                        },
                    ]
                )
            )
        return Contribution(paper_id=runner._paper_id, specialist=work_order.specialist, output="ok", success=True)

    class _Result:
        verdict = "MAJOR_REVISION"
        weighted_avg = 3.0
        rule_triggered = "weighted_avg < 5"
        rationale = "test"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_mixed_patch),
        patch("src.db.client.execute", side_effect=_capture_status),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    assert result == PaperStatus.COMPLETED
    # The in-scope edit landed; the out-of-scope one was dropped (draft unchanged there).
    draft = (ws / "paper_draft.tex").read_text()
    assert "parallel-trends assumption is tested" in draft
    assert "0.80" in draft  # the paper:full edit was NOT applied
    assert not [s for s, _e in seen if s == "rejected"]


# ---------------------------------------------------------------------------
# No-actionable-findings shortcut → COMPLETED without dispatching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_major_revision_with_no_findings_completes_without_dispatch(tmp_path, mock_llm):
    """Edge case: aggregator says MAJOR_REVISION but no reviewer
    crossed the Finding score floor (e.g. weighted-average computation
    produces a low avg from many marginal scores). v0.6 contract:
    transition to COMPLETED with a warning rather than dispatching
    patch_revisor with an empty findings list."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    # All reviewers above the score floor (6.0) — collect_review_findings
    # will emit zero Findings.
    _review_file(ws, "identification_reviewer", 7.0, "Minor Revision")
    _review_file(ws, "technical_reviewer", 7.0, "Minor Revision")

    dispatch_count = 0

    async def _track_dispatch(work_order, *args, **kwargs):
        nonlocal dispatch_count
        dispatch_count += 1
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    class _Result:
        verdict = "MAJOR_REVISION"  # forced
        weighted_avg = 6.5
        rule_triggered = "weighted_avg < 7"
        rationale = "minor issues"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_track_dispatch),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    assert result == PaperStatus.COMPLETED
    assert dispatch_count == 0, (
        "patch_revisor must NOT be dispatched when no findings — burning "
        "an LLM call on an empty findings list is wasted spend"
    )


# ---------------------------------------------------------------------------
# verify_numbers findings rolled in alongside review findings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_numbers_findings_included_in_patch_revisor_focus(tmp_path, mock_llm):
    """When `number_verification.json` exists and has mismatches at the
    major+ severity threshold, those Findings must be combined with
    review Findings in the patch_revisor's work order. Otherwise the
    revisor can't address numeric drift the gate didn't trip on."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    _review_file(ws, "identification_reviewer", 4.0, "Major Revision")

    # Write a number_verification.json with a major mismatch
    (ws / "number_verification.json").write_text(
        json.dumps(
            {
                "passed": False,
                "mismatches": [
                    {
                        "draft_value": "0.80",
                        "source_key": "estimation_results.main.coef",
                        "source_value": "0.50",
                        "table_context": "tab:main, row 1, col 2",
                        "severity": "critical",
                    }
                ],
            }
        )
    )

    captured_focus = [""]

    async def _capture(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            captured_focus[0] = work_order.focus
            (ws / "paper_draft.tex.edits.json").write_text("[]")
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    class _Result:
        verdict = "MAJOR_REVISION"
        weighted_avg = 4.0
        rule_triggered = "weighted_avg < 5"
        rationale = "weak"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
    ):
        await runner._run_revision_phase(PaperStatus.REVIEW)

    focus = captured_focus[0]
    # Both sources represented
    assert "verify_numbers" in focus
    assert "review" in focus
    # Specific verify_numbers content
    assert "table:tab:main" in focus
    assert "estimation_results.main.coef" in focus
