"""v0.6 step 4: wire self-attack critical findings through patch_revisor.

Pre-v0.6 the self-attack phase dispatched up to 3 parallel `revisor`
calls writing to `paper_draft.tex` — a write race where last-writer
won and the other two revisions were silently discarded.
V0.6_PLAN.md change #2.

This module pins:
1. Top-N critical findings → ONE patch_revisor call with all
   findings batched (no parallel writes).
2. Patch failures are advisory at this stage — they're logged but
   do NOT transition status; the downstream review phase catches
   remaining issues.
3. Empty critical_findings list → no dispatch (existing behaviour
   preserved).
4. The legacy parallel-revisor dispatch is gone.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.strategist.actions import SelfAttackFinding, SelfAttackReport
from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import PaperStatus

_DRAFT = r"""\documentclass{article}
\begin{document}

\section{Identification Strategy}
The parallel-trends assumption holds, as we verify in our setting.

\section{Mechanism}
We argue the trader-composition channel dominates.

\section{Results}
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
log RV & 0.42 & 0.10 \\
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
                "current_stage": "self_attack",
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


def _report(*findings: SelfAttackFinding) -> SelfAttackReport:
    severities = [f.severity for f in findings] or [0]
    return SelfAttackReport(findings=list(findings), overall_severity=max(severities))


# ---------------------------------------------------------------------------
# Single dispatch, not parallel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critical_findings_dispatch_one_patch_revisor_not_parallel_revisors(tmp_path, mock_llm):
    """v0.6 invariant: when self-attack has critical findings, the
    runner dispatches EXACTLY ONE patch_revisor call carrying all of
    them. Pre-v0.6 this was three parallel `revisor` calls writing
    to paper_draft.tex (a write race). Regression test pinned per
    V0.6_PLAN.md invariant #2."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    report = _report(
        SelfAttackFinding(
            severity=9,
            category="identification",
            description="Pre-trends not visually inspected.",
            suggested_fix="Add Figure 2.",
        ),
        SelfAttackFinding(
            severity=8,
            category="mechanism",
            description="Trader composition not established.",
            suggested_fix="Cite Lou (2019).",
        ),
        SelfAttackFinding(
            severity=7,
            category="numerics",
            description="Treatment coefficient sign ambiguous.",
            suggested_fix="Clarify sign convention in Section 5.",
        ),
    )

    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
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

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_capture,
        ),
    ):
        result = await runner._run_self_attack_phase()

    assert result == PaperStatus.SELF_ATTACK
    # Exactly one dispatch, and it's patch_revisor (not legacy revisor)
    assert dispatched == ["patch_revisor"], (
        f"Expected one patch_revisor call; saw {dispatched}. "
        f"Pre-v0.6 dispatched 3 parallel `revisor` calls — the v0.6 "
        f"invariant is one patch_revisor with batched findings."
    )
    # Patch landed
    patched = (ws / "paper_draft.tex").read_text()
    assert "is examined in Figure 2" in patched


@pytest.mark.asyncio
async def test_findings_batched_into_single_focus(tmp_path, mock_llm):
    """All critical findings (up to top 3) must appear in the single
    patch_revisor's focus — that's the whole point of consolidation,
    otherwise each finding would still need its own call."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    report = _report(
        SelfAttackFinding(severity=9, category="identification", description="x", suggested_fix=""),
        SelfAttackFinding(severity=8, category="mechanism", description="y", suggested_fix=""),
        SelfAttackFinding(severity=7, category="bibliography", description="z", suggested_fix=""),
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

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_capture,
        ),
    ):
        await runner._run_self_attack_phase()

    focus = captured_focus[0]
    # All three targets appear in the same focus block
    assert "section:identification" in focus
    assert "section:mechanism" in focus
    assert "references" in focus  # bibliography → references target


# ---------------------------------------------------------------------------
# Caps to top 3 — bounded spend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capped_at_top_three_critical(tmp_path, mock_llm):
    """Self-attack may surface more than 3 critical findings. The
    runner caps the patch_revisor's findings list to the top 3 by
    severity — matches the pre-v0.6 limit on parallel revisor calls
    (which was the same number). Bounds spend on noisy adversarial
    runs."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    # Five critical findings; only top 3 should reach the work order.
    findings = [
        SelfAttackFinding(severity=10, category="identification", description="a", suggested_fix=""),
        SelfAttackFinding(severity=9, category="mechanism", description="b", suggested_fix=""),
        SelfAttackFinding(severity=8, category="numerics", description="c", suggested_fix=""),
        SelfAttackFinding(severity=7, category="bibliography", description="d", suggested_fix=""),
        SelfAttackFinding(severity=7, category="framing", description="e", suggested_fix=""),
    ]
    report = _report(*findings)

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

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_capture,
        ),
    ):
        await runner._run_self_attack_phase()

    focus = captured_focus[0]
    # Header reports 3 items
    assert "FINDINGS (3 items" in focus, (
        f"top-3 cap not enforced — focus header: {focus.splitlines()[3] if focus else '(empty)'}"
    )
    # Top 3 by severity present
    assert "section:identification" in focus  # severity 10
    assert "section:mechanism" in focus  # severity 9
    assert "section:results" in focus  # numerics severity 8
    # Below-top-3 NOT present
    assert "references" not in focus  # severity 7, dropped
    assert "section:introduction" not in focus  # framing severity 7, dropped


# ---------------------------------------------------------------------------
# Empty / non-critical paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_critical_findings_no_dispatch(tmp_path, mock_llm):
    """If the self-attack returns only sub-critical findings (severity
    < 7), patch_revisor is NOT dispatched — same as pre-v0.6."""
    runner = _runner(tmp_path, mock_llm)

    report = _report(
        SelfAttackFinding(severity=5, category="numerics", description="x", suggested_fix=""),
        SelfAttackFinding(severity=4, category="framing", description="y", suggested_fix=""),
    )

    dispatch_count = 0

    async def _count_dispatch(work_order, *args, **kwargs):
        nonlocal dispatch_count
        dispatch_count += 1
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_count_dispatch,
        ),
    ):
        result = await runner._run_self_attack_phase()

    assert result == PaperStatus.SELF_ATTACK
    assert dispatch_count == 0


@pytest.mark.asyncio
async def test_no_findings_at_all_no_dispatch(tmp_path, mock_llm):
    """Self-attack returns zero findings — phase exits cleanly."""
    runner = _runner(tmp_path, mock_llm)
    report = _report()

    dispatch_count = 0

    async def _count(work_order, *args, **kwargs):
        nonlocal dispatch_count
        dispatch_count += 1
        return Contribution(paper_id=runner._paper_id, specialist=work_order.specialist, output="ok", success=True)

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_count),
    ):
        result = await runner._run_self_attack_phase()

    assert result == PaperStatus.SELF_ATTACK
    assert dispatch_count == 0


# ---------------------------------------------------------------------------
# Failure mode: patch fails, phase still returns SELF_ATTACK (advisory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_patch_does_not_reject_phase(tmp_path, mock_llm):
    """Self-attack patches are advisory at this stage of the pipeline
    — the review phase will catch what remains. A failed patch
    (target not found, find ambiguous, missing patch file) must NOT
    transition the paper to REJECTED. It's logged + the phase
    returns SELF_ATTACK normally."""
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace

    report = _report(
        SelfAttackFinding(severity=9, category="identification", description="x", suggested_fix=""),
    )

    async def _bad_patch(work_order, *args, **kwargs):
        if work_order.specialist == "patch_revisor":
            # Patch references text that doesn't exist in the draft
            (ws / "paper_draft.tex.edits.json").write_text(
                json.dumps(
                    [
                        {
                            "target": "section:identification",
                            "edit_type": "replace_text",
                            "find": "this string does not appear anywhere",
                            "replace": "y",
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

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_bad_patch),
    ):
        result = await runner._run_self_attack_phase()

    # Phase still returns SELF_ATTACK — advisory failure path.
    assert result == PaperStatus.SELF_ATTACK


@pytest.mark.asyncio
async def test_missing_patch_file_does_not_reject_phase(tmp_path, mock_llm):
    """patch_revisor's LLM call succeeds but doesn't produce the
    patch file. Same advisory contract: log + continue, no
    REJECTED."""
    runner = _runner(tmp_path, mock_llm)

    report = _report(
        SelfAttackFinding(severity=9, category="identification", description="x", suggested_fix=""),
    )

    async def _no_patch(work_order, *args, **kwargs):
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="ok",
            success=True,
        )

    with (
        patch.object(runner._strategist, "run_self_attack", new=AsyncMock(return_value=report)),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_no_patch),
    ):
        result = await runner._run_self_attack_phase()

    assert result == PaperStatus.SELF_ATTACK
