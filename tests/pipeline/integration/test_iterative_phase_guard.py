"""v0.6 step 6: iterative-phase guard against paper_drafter re-dispatch.

The third drift source from V0.6_PLAN.md change #3: the
strategist could legally re-dispatch `paper_drafter` on iterations
2+, and the specialist would rewrite the entire `paper_draft.tex`
from scratch. Even sections reviewers had already approved on
prior iterations would drift on every pass.

v0.6 step 6 closes this two ways:
- Soft: the strategist's system prompt instructs it to dispatch
  `section_writer` (scoped to a specific section) on iterations
  2+, never `paper_drafter`.
- Hard: `_dispatch` drops any `paper_drafter` work orders when
  `self._iteration >= 2`, logging a warning. Load-bearing — if
  the strategist ignores the soft instruction, the guard still
  prevents the drift.

This module pins the hard guard. The soft prompt content is
tested by its own assertions below.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.specialists.contracts import Contribution
from src.core.strategist.actions import StrategistDecision, WorkOrder
from src.core.strategist.runner import PipelineRunner


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
                "current_stage": "in_progress",
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
        mode="iterative",
        backend_name="mock",
    )


def _decision(*specialists: str) -> StrategistDecision:
    return StrategistDecision(
        action="dispatch_parallel",
        work_orders=[WorkOrder(specialist=s, focus=f"work on {s}", parallel_group=0) for s in specialists],
        rationale="test",
    )


def _successful_contribution(paper_id: str, specialist: str) -> Contribution:
    return Contribution(paper_id=paper_id, specialist=specialist, output="ok", success=True)


def _write_artifact(runner: PipelineRunner, specialist: str) -> None:
    """A genuinely-successful specialist writes its canonical artifact; the
    mocks must too, or the single-order cascade guard (assert_artifacts_written)
    correctly trips on the missing file."""
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS

    art = SPECIALIST_ARTIFACTS.get(specialist)
    if art:
        path = runner._workspace / art
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok")


# ---------------------------------------------------------------------------
# Hard guard: paper_drafter dropped on iteration >= 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_drafter_dropped_on_iteration_2(tmp_path, mock_llm, caplog):
    """The headline v0.6 step 6 contract: any paper_drafter work order
    submitted by the strategist on iteration 2+ is silently dropped
    BEFORE dispatch. Pre-v0.6 this would have rewritten the whole
    paper. Test pins the drop + the warning log."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 2

    decision = _decision("paper_drafter", "section_writer")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    async def _capture_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [_successful_contribution(runner._paper_id, o.specialist) for o in orders]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch(
            "src.core.strategist.runner.execute_with_dependencies",
            side_effect=_capture_parallel,
        ),
        caplog.at_level("WARNING"),
    ):
        await runner._dispatch(decision)

    # paper_drafter dropped, section_writer dispatched.
    assert "paper_drafter" not in dispatched, f"paper_drafter must NOT be dispatched on iteration 2; saw {dispatched}"
    assert "section_writer" in dispatched

    # Warning was logged with enough context for the operator to know
    # what happened.
    relevant_logs = [r for r in caplog.records if "Iterative-phase guard" in r.message]
    assert relevant_logs, f"Expected an 'Iterative-phase guard' warning; saw {[r.message for r in caplog.records]}"
    assert "paper_drafter" in relevant_logs[0].message


@pytest.mark.asyncio
async def test_paper_drafter_dropped_on_iteration_5(tmp_path, mock_llm):
    """Guard fires on any iteration >= 2, not just iteration 2."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 5

    decision = _decision("paper_drafter")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture):
        contributions = await runner._dispatch(decision)

    assert dispatched == []
    # When the guard drops ALL work orders, _dispatch returns early —
    # no contributions produced for this round.
    assert contributions == []


# ---------------------------------------------------------------------------
# Negative cases: guard must NOT fire when it shouldn't
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_drafter_allowed_on_iteration_0_initial_phase(tmp_path, mock_llm):
    """iteration=0 is the initial phase. paper_drafter is the
    legitimate specialist that produces the first draft. Guard
    must NOT fire — otherwise the initial phase produces no draft
    at all."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 0

    decision = _decision("paper_drafter", "abstract_writer")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    async def _capture_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [_successful_contribution(runner._paper_id, o.specialist) for o in orders]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch(
            "src.core.strategist.runner.execute_with_dependencies",
            side_effect=_capture_parallel,
        ),
    ):
        await runner._dispatch(decision)

    assert "paper_drafter" in dispatched


@pytest.mark.asyncio
async def test_paper_drafter_allowed_on_iteration_1(tmp_path, mock_llm):
    """Iteration 1 is the FIRST iterative pass. The strategist may
    legitimately want to dispatch paper_drafter once at this point
    if the initial phase produced no draft (or the user resumed
    mid-pipeline). Only iteration >= 2 is guarded."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 1

    decision = _decision("paper_drafter")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture):
        await runner._dispatch(decision)

    assert dispatched == ["paper_drafter"]


@pytest.mark.asyncio
async def test_legitimate_specialists_not_dropped_on_iteration_2(tmp_path, mock_llm):
    """The guard must be specific to full-rewrite specialists
    (`paper_drafter` and, from v0.6.1, `revisor`). `section_writer`
    is the LEGITIMATE writing specialist on iterations 2+; design
    specialists like `data_analyst` are likewise legitimate. Dropping
    them would defeat the whole step-6 design."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 2

    # v0.6.1: `revisor` IS now dropped (full-rewrite); replaced by
    # `econometrics_specialist` here to keep the test's intent of
    # "legitimate iter-2+ specialists survive the guard".
    decision = _decision("section_writer", "econometrics_specialist", "data_analyst")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    async def _capture_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [_successful_contribution(runner._paper_id, o.specialist) for o in orders]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch(
            "src.core.strategist.runner.execute_with_dependencies",
            side_effect=_capture_parallel,
        ),
    ):
        await runner._dispatch(decision)

    assert set(dispatched) == {"section_writer", "econometrics_specialist", "data_analyst"}


# ---------------------------------------------------------------------------
# Mixed decisions: keep the non-paper_drafter work orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_decision_keeps_non_drafter_work_orders(tmp_path, mock_llm):
    """When the strategist submits paper_drafter alongside legitimate
    iteration 2+ specialists, only paper_drafter is dropped — the
    rest dispatch normally."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 3

    decision = _decision(
        "paper_drafter",  # DROPPED
        "section_writer",  # KEPT
        "econometrics_specialist",  # KEPT
        "paper_drafter",  # DROPPED (multiple drafter orders are all dropped)
    )
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    async def _capture_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [_successful_contribution(runner._paper_id, o.specialist) for o in orders]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch(
            "src.core.strategist.runner.execute_with_dependencies",
            side_effect=_capture_parallel,
        ),
    ):
        await runner._dispatch(decision)

    assert "paper_drafter" not in dispatched
    assert sorted(dispatched) == ["econometrics_specialist", "section_writer"]


# ---------------------------------------------------------------------------
# Soft side: strategist prompt teaches the rule
# ---------------------------------------------------------------------------


def test_strategist_prompt_mentions_iteration_rule():
    """The strategist's system prompt must tell it not to dispatch
    paper_drafter on iterations 2+. Without the prompt update, the
    strategist would keep doing it, the hard guard would keep
    dropping the calls, and the operator would see warning spam.
    The prompt instruction trains the model to pick section_writer
    on its own."""
    from src.core.strategist.engine import _STRATEGIST_SYSTEM

    assert "paper_drafter" in _STRATEGIST_SYSTEM
    assert "section_writer" in _STRATEGIST_SYSTEM
    # The specific rule
    assert "iteration" in _STRATEGIST_SYSTEM.lower()
    # The hard-check warning is mentioned so the strategist knows
    # the runner will catch violations
    assert "dropped" in _STRATEGIST_SYSTEM.lower() or "drop" in _STRATEGIST_SYSTEM.lower()


# ---------------------------------------------------------------------------
# v0.6.1: revisor also blocked on iter >= 2 (surfaced by live run 3bc58e8d)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revisor_dropped_on_iteration_2(tmp_path, mock_llm, caplog):
    """v0.6.1: the legacy `revisor` rewrites paper_draft.tex from
    scratch, same as paper_drafter — so the same iterative-phase
    guard must apply to it. v0.6.0's live run (paper 3bc58e8d)
    surfaced the gap: the strategist dispatched revisor during
    iterative phase even though paper_drafter was correctly
    skipped. v0.6.1 closes that door."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 2

    decision = _decision("revisor", "section_writer")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    async def _capture_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [_successful_contribution(runner._paper_id, o.specialist) for o in orders]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch(
            "src.core.strategist.runner.execute_with_dependencies",
            side_effect=_capture_parallel,
        ),
        caplog.at_level("WARNING"),
    ):
        await runner._dispatch(decision)

    assert "revisor" not in dispatched, f"revisor must NOT be dispatched on iteration 2; saw {dispatched}"
    assert "section_writer" in dispatched
    # Warning mentions revisor specifically
    relevant_logs = [r for r in caplog.records if "Iterative-phase guard" in r.message]
    assert relevant_logs
    assert "revisor" in relevant_logs[0].message


@pytest.mark.asyncio
async def test_revisor_allowed_on_iteration_1(tmp_path, mock_llm):
    """Iteration 1 is the first iterative pass. revisor may
    legitimately reconcile the draft once at this point (e.g.
    after upstream artifacts changed). Only iteration >= 2 is
    guarded."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 1

    decision = _decision("revisor")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture):
        await runner._dispatch(decision)

    assert dispatched == ["revisor"]


@pytest.mark.asyncio
async def test_revisor_and_paper_drafter_both_dropped(tmp_path, mock_llm, caplog):
    """When the strategist submits BOTH legacy full-rewrite specialists
    on iter >= 2, the guard drops both and keeps the rest."""
    runner = _runner(tmp_path, mock_llm)
    runner._iteration = 3

    decision = _decision("paper_drafter", "revisor", "section_writer", "data_analyst")
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        _write_artifact(runner, work_order.specialist)
        return _successful_contribution(runner._paper_id, work_order.specialist)

    async def _capture_parallel(orders, *args, **kwargs):
        for o in orders:
            dispatched.append(o.specialist)
        return [_successful_contribution(runner._paper_id, o.specialist) for o in orders]

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch(
            "src.core.strategist.runner.execute_with_dependencies",
            side_effect=_capture_parallel,
        ),
        caplog.at_level("WARNING"),
    ):
        await runner._dispatch(decision)

    # Both full-rewrite specialists dropped, others kept.
    assert "paper_drafter" not in dispatched
    assert "revisor" not in dispatched
    assert sorted(dispatched) == ["data_analyst", "section_writer"]


def test_strategist_prompt_mentions_revisor_in_iter_rule():
    """The prompt's iterative-phase rule must name `revisor` explicitly
    so the strategist knows BOTH full-rewrite specialists are
    forbidden on iter 2+. Without naming it, the strategist might
    pick revisor as a 'workaround' for the paper_drafter ban."""
    from src.core.strategist.engine import _STRATEGIST_SYSTEM

    # Grab the iterative-phase rule section
    assert "Iterative-phase rule" in _STRATEGIST_SYSTEM
    # revisor must be named in the same context as paper_drafter — i.e.
    # both listed as forbidden on iter 2+.
    rule_section = _STRATEGIST_SYSTEM[_STRATEGIST_SYSTEM.index("Iterative-phase rule") :]
    assert "paper_drafter" in rule_section
    assert "revisor" in rule_section
    # And the patch_revisor escape valve is mentioned as the
    # legitimate way to do scoped revisions
    assert "patch_revisor" in rule_section
