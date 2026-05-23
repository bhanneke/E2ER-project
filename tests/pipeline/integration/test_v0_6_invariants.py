"""v0.6 architecture invariants — cross-step assertions.

V0.6_PLAN.md lists five architecture invariants that must hold for
the targeted-revision design to deliver on its "no drift" promise.
Each is primarily pinned by a step-specific regression test. This
module:

1. Documents the full set in one place, with pointers to the
   primary pin tests.
2. Adds cross-step assertions that span multiple v0.6 changes —
   the kind that would silently regress if any one step were
   reverted in isolation.

Primary pins by step:
- Invariant 1 (paper_drafter at most once after init):
  tests/pipeline/integration/test_iterative_phase_guard.py
- Invariant 2 (revisions dispatched serially against paper_draft.tex):
  tests/pipeline/integration/test_self_attack_patch_wiring.py::
    test_critical_findings_dispatch_one_patch_revisor_not_parallel_revisors
- Invariant 3 (revisor receives structured Findings, not prose):
  tests/pipeline/integration/test_patch_revision_wiring.py::
    test_findings_serialised_into_patch_revisor_focus
- Invariant 4 (verify_numbers runs twice on auto-patchable mismatches):
  tests/pipeline/integration/test_verify_numbers_auto_patch.py::
    test_verification_report_overwritten_on_second_pass
- Invariant 5 (merger refuses edits whose target isn't in findings):
  tests/pipeline/test_patch_merger.py::TestValidateTargets::
    test_out_of_scope_edit_rejected

Cross-step assertions added here:
- The legacy `revisor` specialist is NEVER dispatched by v0.6
  code paths (steps 3+4 combined).
- When both review and verify_numbers have findings, BOTH source
  types reach patch_revisor's focus (step 3+5 combined).
- The merger's scope-enforcement holds regardless of which v0.6
  dispatch site invoked patch_revisor (steps 3, 4, 5).
- patch_revisor's primary artifact in the registry is the patch
  file, not paper_draft.tex (prevents a regression that would
  re-introduce direct draft writes).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.specialists.registry import SPECIALIST_ARTIFACTS
from src.core.strategist.actions import SelfAttackFinding, SelfAttackReport
from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import PaperStatus

_DRAFT = r"""\documentclass{article}
\begin{document}

\begin{abstract}
The treatment effect is 0.80 according to our estimates.
\end{abstract}

\section{Identification Strategy}
The parallel-trends assumption holds.

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
                "mode": "iterative",
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
        mode="iterative",
        backend_name="mock",
    )


def _review_file(ws: Path, reviewer: str, score: float, recommendation: str) -> None:
    artifact = {
        "identification_reviewer": "review_identification.md",
        "technical_reviewer": "review_technical.md",
        "mechanism_reviewer": "review_mechanism.md",
        "literature_reviewer": "review_literature.md",
        "data_reviewer": "review_data.md",
        "writing_reviewer": "review_writing.md",
    }[reviewer]
    (ws / artifact).write_text(
        f"# Review from {reviewer}\n\nIssues.\n\nOVERALL SCORE: {score:.1f}/10\nRECOMMENDATION: {recommendation}\n"
    )


# ---------------------------------------------------------------------------
# Registry invariants — static
# ---------------------------------------------------------------------------


class TestRegistryInvariants:
    def test_patch_revisor_output_is_the_patch_file_not_draft(self):
        """patch_revisor's primary artifact MUST be
        paper_draft.tex.edits.json (the patch file the merger
        consumes), NOT paper_draft.tex directly. If a refactor
        accidentally changed this to paper_draft.tex, the merger
        would never run and the v0.6 scope-enforcement invariant
        would silently disappear."""
        assert SPECIALIST_ARTIFACTS["patch_revisor"] == "paper_draft.tex.edits.json"

    def test_legacy_revisor_still_registered_for_deprecation(self):
        """Per V0.6_PLAN.md, the legacy `revisor` entry stays in the
        registry for one release cycle. Tests + downstream tooling
        may still reference it; removing the entry would break them.
        The v0.6 runner just stops DISPATCHING it (asserted below)."""
        assert "revisor" in SPECIALIST_ARTIFACTS


# ---------------------------------------------------------------------------
# Legacy `revisor` specialist is never dispatched in v0.6 code paths
# ---------------------------------------------------------------------------


class TestLegacyRevisorNeverDispatched:
    """The two dispatch sites that previously used `revisor` are
    `_run_revision_phase` (MAJOR_REVISION branch) and
    `_run_self_attack_phase` (critical-findings branch). v0.6
    replaces both with `patch_revisor`. This class pins the
    cross-step assertion: regardless of which path fires, the
    legacy revisor is never the specialist dispatched."""

    @pytest.mark.asyncio
    async def test_major_revision_does_not_dispatch_legacy_revisor(self, tmp_path, mock_llm):
        runner = _runner(tmp_path, mock_llm)
        ws = runner._workspace
        _review_file(ws, "identification_reviewer", 3.0, "Major Revision")

        dispatched: list[str] = []

        async def _capture(work_order, *args, **kwargs):
            dispatched.append(work_order.specialist)
            if work_order.specialist == "patch_revisor":
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
            rationale = "weak"

        with (
            patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
            patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        ):
            await runner._run_revision_phase(PaperStatus.REVIEW)

        assert "revisor" not in dispatched, (
            f"Legacy revisor dispatched on MAJOR_REVISION; v0.6 must use patch_revisor exclusively. Saw {dispatched}."
        )

    @pytest.mark.asyncio
    async def test_self_attack_does_not_dispatch_legacy_revisor(self, tmp_path, mock_llm):
        runner = _runner(tmp_path, mock_llm)
        ws = runner._workspace
        report = SelfAttackReport(
            findings=[
                SelfAttackFinding(
                    severity=9,
                    category="identification",
                    description="x",
                    suggested_fix="",
                )
            ],
            overall_severity=9,
        )

        dispatched: list[str] = []

        async def _capture(work_order, *args, **kwargs):
            dispatched.append(work_order.specialist)
            if work_order.specialist == "patch_revisor":
                (ws / "paper_draft.tex.edits.json").write_text("[]")
            return Contribution(
                paper_id=runner._paper_id,
                specialist=work_order.specialist,
                output="ok",
                success=True,
            )

        with (
            patch.object(
                runner._strategist,
                "run_self_attack",
                new=AsyncMock(return_value=report),
            ),
            patch(
                "src.core.specialists.dispatcher.execute_work_order",
                side_effect=_capture,
            ),
        ):
            await runner._run_self_attack_phase()

        assert "revisor" not in dispatched, (
            f"Legacy revisor dispatched in self-attack; v0.6 must use patch_revisor exclusively. Saw {dispatched}."
        )

    @pytest.mark.asyncio
    async def test_verify_numbers_auto_patch_does_not_dispatch_legacy_revisor(self, tmp_path, mock_llm):
        runner = _runner(tmp_path, mock_llm)
        ws = runner._workspace
        # Force verify_numbers to find a critical mismatch
        (ws / "estimation_results.json").write_text(json.dumps({"main": {"coef": 0.50, "se": 0.10}}))

        dispatched: list[str] = []

        async def _capture(work_order, *args, **kwargs):
            dispatched.append(work_order.specialist)
            return Contribution(
                paper_id=runner._paper_id,
                specialist=work_order.specialist,
                output="ok",
                success=True,
            )

        with patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_capture,
        ):
            await runner._run_review_phase()

        # patch_revisor IS expected (one auto-patch attempt); revisor
        # MUST NOT be.
        assert "revisor" not in dispatched, (
            f"Legacy revisor dispatched in verify_numbers auto-patch; "
            f"v0.6 must use patch_revisor exclusively. Saw {dispatched}."
        )


# ---------------------------------------------------------------------------
# Multi-source findings reach patch_revisor's focus (steps 3 + 5 combined)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_plus_verify_numbers_findings_both_reach_patch_revisor(tmp_path, mock_llm):
    """Cross-step invariant: when MAJOR_REVISION fires AND
    `number_verification.json` exists with mismatches, BOTH source
    types must appear in patch_revisor's focus. If the runner
    accidentally serialised only one source, the patch_revisor
    would only address half the issues — silent loss of revision
    coverage.

    Spans steps 3 (MAJOR_REVISION wiring) + 5 (verify_numbers
    findings collector)."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    _review_file(ws, "identification_reviewer", 3.0, "Major Revision")
    # Persist a verify_numbers report (as v0.5+ does after the gate)
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

    captured = [""]

    async def _capture(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            captured[0] = work_order.focus
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
        rationale = "weak"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_capture,
        ),
    ):
        await runner._run_revision_phase(PaperStatus.REVIEW)

    focus = captured[0]
    assert focus, "patch_revisor was never dispatched"
    # Both source labels present in the serialised findings
    assert '"source": "review"' in focus
    assert '"source": "verify_numbers"' in focus
    # Source-priority order: verify_numbers comes first (per
    # combine_findings tie-breaker).
    verify_idx = focus.index('"source": "verify_numbers"')
    review_idx = focus.index('"source": "review"')
    assert verify_idx < review_idx, (
        "verify_numbers findings must come before review findings in the "
        "patch_revisor focus — they're more mechanical to fix and have "
        "stronger correctness signal (combine_findings tie-breaker)"
    )


# ---------------------------------------------------------------------------
# Merger scope enforcement holds at every dispatch site
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merger_refuses_out_of_scope_edit_from_major_revision_site(tmp_path, mock_llm):
    """patch_revisor emits an edit targeting a section that's NOT
    in its findings list. The merger MUST refuse to apply it,
    regardless of which dispatch site invoked patch_revisor.
    Cross-step invariant: scope-enforcement is a property of the
    merger, not of any specific caller.

    This test exercises the MAJOR_REVISION dispatch site
    specifically (step 3 path); the same invariant must hold at
    every dispatch site, hence the named-by-site test naming."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace
    _review_file(ws, "identification_reviewer", 3.0, "Major Revision")

    async def _capture(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            # Emit an edit targeting a section NOT in findings.
            # collect_review_findings emits "section:identification"
            # for identification_reviewer; the conclusion section is
            # out of scope.
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "section:conclusion",  # OUT OF SCOPE
                            "edit_type": "replace_text",
                            "find": "something",
                            "replace": "something else",
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
        rationale = "weak"

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Result()),
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_capture,
        ),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)

    # The merger rejected the out-of-scope edit → 0 applied + 1
    # failed → REJECTED.
    assert result == PaperStatus.REJECTED
    # The draft was NOT modified
    assert (ws / "paper_draft.tex").read_text() == _DRAFT


# ---------------------------------------------------------------------------
# Combined-source priority and severity ordering
# ---------------------------------------------------------------------------


def test_combine_findings_priority_matches_v0_6_doc():
    """V0.6_PLAN.md commits to: severity DESC, ties broken by source
    priority verify_numbers > self_attack > review. Pin the
    documented behaviour here — a refactor that re-ordered the
    priority would silently change which findings the
    patch_revisor sees first."""
    from src.core.strategist.findings import Finding, combine_findings

    same_sev = [
        Finding(
            source="review",
            source_detail="r",
            target="paper:full",
            severity=7,
            problem="x",
            suggested_fix="y",
        ),
        Finding(
            source="verify_numbers",
            source_detail="v",
            target="paper:full",
            severity=7,
            problem="x",
            suggested_fix="y",
        ),
        Finding(
            source="self_attack",
            source_detail="s",
            target="paper:full",
            severity=7,
            problem="x",
            suggested_fix="y",
        ),
    ]
    out = combine_findings(same_sev)
    assert [f.source for f in out] == ["verify_numbers", "self_attack", "review"]
