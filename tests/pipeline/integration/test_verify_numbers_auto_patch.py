"""v0.6 step 5: verify_numbers auto-patch loop.

V0.5's anti-hallucination gate was purely defensive: critical
mismatch → REJECTED, operator manually revises the source JSON
or the draft, POSTs /resume. V0.6 makes the gate proactive: when
a critical mismatch is found, dispatch patch_revisor with the
mismatch findings, re-run verify_numbers, and only transition to
REJECTED if the second pass still has criticals. The detect →
patch → re-detect loop was the missing piece in V0.5_PLAN.md.

This module pins:
1. Critical mismatch + successful patch → reviewers run.
2. Critical mismatch + partial patch (some criticals remain) → REJECTED.
3. Critical mismatch + patch_revisor produced no patch file → REJECTED.
4. No mismatches → original review flow unchanged (no auto-patch invoked).
5. Auto-patch budget = 0 → falls through to REJECTED immediately.
6. number_verification.json is re-written on the second verify pass.
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


def _draft_with_value(value: str) -> str:
    """Build a minimal LaTeX draft where the main table cites `value`
    in the coefficient column."""
    return (
        r"""\documentclass{article}
\begin{document}

\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
log RV & """
        + value
        + r""" & 0.10 \\
\bottomrule
\end{tabular}

\end{document}
"""
    )


def _make_workspace(tmp_path: Path, paper_id: str, draft: str) -> Path:
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
    (ws / "paper_draft.tex").write_text(draft)
    # Source JSON with the *correct* value — drafter cited 0.80 (wrong),
    # estimation says 0.50 (right). Critical mismatch (rel-err = 60%).
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"coef": 0.50, "se": 0.10}}))
    return ws


def _runner(tmp_path, mock_llm, draft: str) -> PipelineRunner:
    paper_id = str(uuid.uuid4())
    ws = _make_workspace(tmp_path, paper_id, draft)
    return PipelineRunner(
        paper_id=paper_id,
        workspace=ws,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )


# ---------------------------------------------------------------------------
# Happy path: critical mismatch → patch succeeds → reviewers run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critical_mismatch_auto_patched_then_reviewers_run(tmp_path, mock_llm):
    """The headline v0.6 step 5 outcome: drafter cites the wrong
    number, the gate catches it, patch_revisor fixes the cell, the
    second verify pass is clean, reviewers run normally."""
    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.80"))
    ws = runner._workspace

    review_dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            # Patch the table cell from 0.80 → 0.50 (matches source JSON)
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "table:tab:main",
                            "edit_type": "replace_text",
                            "find": "log RV & 0.80 & 0.10",
                            "replace": "log RV & 0.50 & 0.10",
                        }
                    ]
                )
            )
        else:
            review_dispatched.append(work_order.specialist)
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    async def _fake_parallel(orders, *args, **kwargs):
        return [
            Contribution(
                paper_id=runner._paper_id,
                specialist=o.specialist,
                output="ok",
                success=True,
            )
            for o in orders
        ]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch("src.core.strategist.runner.execute_parallel", side_effect=_fake_parallel),
    ):
        result = await runner._run_review_phase()

    # Reviewers DID run — auto-patch succeeded, gate cleared.
    assert result == PaperStatus.REVIEW
    # patch_revisor was invoked
    assert (ws / "paper_draft.tex.edits.json").exists()
    # Draft was patched on disk
    patched = (ws / "paper_draft.tex").read_text()
    assert "log RV & 0.50" in patched
    assert "log RV & 0.80" not in patched
    # verify_numbers report on disk is now clean (second pass overwrote)
    verify = json.loads((ws / "number_verification.json").read_text())
    assert not [m for m in verify["mismatches"] if m.get("severity") == "critical"]


# ---------------------------------------------------------------------------
# Failure modes: each must transition to REJECTED with v0.5-equivalent error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_residual_critical_after_patch_yields_rejected(tmp_path, mock_llm):
    """patch_revisor's edit applies but the value it wrote in is
    ALSO wrong, so the second verify pass still finds a critical
    mismatch. Fall through to REJECTED with the new mismatch
    surfaced in last_error."""
    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.80"))
    ws = runner._workspace

    async def _patch_with_wrong_value(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            # Patch 0.80 → 0.95 — still wrong (source is 0.50)
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "table:tab:main",
                            "edit_type": "replace_text",
                            "find": "log RV & 0.80 & 0.10",
                            "replace": "log RV & 0.95 & 0.10",
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

    with patch(
        "src.core.specialists.dispatcher.execute_work_order",
        side_effect=_patch_with_wrong_value,
    ):
        result = await runner._run_review_phase()

    assert result == PaperStatus.REJECTED


@pytest.mark.asyncio
async def test_patch_revisor_emits_no_patch_file_yields_rejected(tmp_path, mock_llm):
    """patch_revisor's LLM call returns but doesn't write the patch
    file. The auto-patch helper falls through to REJECTED with the
    original mismatch error (the operator still sees what was
    wrong)."""
    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.80"))

    async def _no_patch(work_order, *args, **kwargs):
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_no_patch):
        result = await runner._run_review_phase()

    assert result == PaperStatus.REJECTED


@pytest.mark.asyncio
async def test_partial_patch_resolving_all_criticals_proceeds_to_review(tmp_path, mock_llm):
    """Two critical mismatches, patch_revisor's patch file fixes both
    in one edit each but one of the edits has a bad find string and
    fails to apply. If the surviving edit happens to fix all
    criticals (the second mismatch was downstream of the first), the
    paper proceeds to REVIEW."""
    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.80"))
    ws = runner._workspace

    async def _capture(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            # Two edits: one valid (fixes the only critical), one with
            # a bad find that fails the merger but doesn't affect the
            # downstream verify pass.
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "table:tab:main",
                            "edit_type": "replace_text",
                            "find": "log RV & 0.80 & 0.10",
                            "replace": "log RV & 0.50 & 0.10",
                        },
                        {
                            "target": "table:tab:main",
                            "edit_type": "replace_text",
                            "find": "this string does not appear in the draft",
                            "replace": "y",
                        },
                    ]
                )
            )
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    async def _fake_parallel(orders, *args, **kwargs):
        return [
            Contribution(
                paper_id=runner._paper_id,
                specialist=o.specialist,
                output="ok",
                success=True,
            )
            for o in orders
        ]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch("src.core.strategist.runner.execute_parallel", side_effect=_fake_parallel),
    ):
        result = await runner._run_review_phase()

    # The valid edit cleared the critical → reviewers run.
    assert result == PaperStatus.REVIEW


# ---------------------------------------------------------------------------
# Auto-patch is skipped when there's nothing to patch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_critical_mismatches_no_auto_patch(tmp_path, mock_llm):
    """When verify_numbers passes (no criticals), the auto-patch
    helper is not invoked and patch_revisor is not dispatched."""
    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.50"))  # matches source

    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    async def _fake_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [
            Contribution(
                paper_id=runner._paper_id,
                specialist=o.specialist,
                output="ok",
                success=True,
            )
            for o in orders
        ]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch("src.core.strategist.runner.execute_parallel", side_effect=_fake_parallel),
    ):
        result = await runner._run_review_phase()

    assert result == PaperStatus.REVIEW
    assert "patch_revisor" not in dispatched, (
        f"patch_revisor must NOT be dispatched when there are no critical mismatches; saw {dispatched}"
    )


# ---------------------------------------------------------------------------
# Budget = 0 → original v0.5 REJECT behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_budget_falls_through_to_reject_immediately(tmp_path, mock_llm, monkeypatch):
    """Operators can disable the auto-patch loop by setting the
    budget to 0. The runner falls through to the original v0.5
    REJECT path immediately without dispatching patch_revisor."""
    monkeypatch.setattr("src.core.strategist.runner._VERIFY_NUMBERS_AUTO_PATCH_BUDGET", 0)

    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.80"))

    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture):
        result = await runner._run_review_phase()

    assert result == PaperStatus.REJECTED
    assert dispatched == [], f"With budget=0 no specialist should be dispatched; saw {dispatched}"


# ---------------------------------------------------------------------------
# number_verification.json reflects post-patch state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verification_report_overwritten_on_second_pass(tmp_path, mock_llm):
    """The persisted number_verification.json must reflect the
    POST-patch state, not the pre-patch state — otherwise the
    dashboard would render stale mismatches for a paper that's
    actually clean."""
    runner = _runner(tmp_path, mock_llm, _draft_with_value("0.80"))
    ws = runner._workspace

    async def _good_patch(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "table:tab:main",
                            "edit_type": "replace_text",
                            "find": "log RV & 0.80 & 0.10",
                            "replace": "log RV & 0.50 & 0.10",
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

    async def _fake_parallel(orders, *args, **kwargs):
        return [
            Contribution(
                paper_id=runner._paper_id,
                specialist=o.specialist,
                output="ok",
                success=True,
            )
            for o in orders
        ]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_good_patch),
        patch("src.core.strategist.runner.execute_parallel", side_effect=_fake_parallel),
    ):
        await runner._run_review_phase()

    report = json.loads((ws / "number_verification.json").read_text())
    # After patch, no critical mismatches in the persisted report
    crits = [m for m in report["mismatches"] if m.get("severity") == "critical"]
    assert crits == []
    # And the matched count is non-zero (the patched 0.50 matches the source 0.50)
    assert report["matched"] >= 1
