"""The iterative mode's record of itself: rounds, ceiling checks, the change of approach, the self-critique.

The whole mode runs end to end at the replay level
(tests/test_replay_level.py, scenario fomc-iterative); these tests pin the
parts on their own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.core import labels
from src.modules.llm.base import LLMBackend, ToolLoopResult


class _Answer(LLMBackend):
    """A backend that answers every call with one text."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw) -> ToolLoopResult:  # type: ignore[override]
        return ToolLoopResult(success=True, output=self.text)


@pytest.mark.parametrize(
    "answer, verdict",
    [
        ('{"verdict": "Continue", "reason": "more"}', "continue"),
        ('{"verdict": "proceed to review"}', "proceed_to_review"),
        ('{"verdict": "stop", "reason": "done"}', "proceed_to_review"),
        ('{"verdict": "pivot", "reason": null, "suggested_pivots": []}', "pivot"),
        ("no JSON at all", "proceed_to_review"),
    ],
)
async def test_a_ceiling_verdict_outside_the_three_does_not_fail_the_run(tmp_path: Path, answer: str, verdict: str):
    """Before 0.15.1 a verdict such as "stop" failed the CeilingCheckResult model, and with it the run."""
    from src.core.strategist.engine import StrategistEngine

    engine = StrategistEngine(_Answer(answer), tmp_path, "p-1")
    result = await engine.ceiling_check(1, 0)
    assert result.verdict == verdict and isinstance(result.reason, str)


async def test_each_round_its_ceiling_check_and_the_one_pivot_are_recorded(tmp_path: Path, monkeypatch):
    from src.core.strategist.actions import CeilingCheckResult, StrategistDecision
    from src.core.strategist.runner import PipelineRunner
    from src.db import events

    logged: list[tuple[str, dict[str, Any]]] = []

    async def log_event(paper_id, event_type, stage=None, specialist=None, payload=None):
        logged.append((event_type, payload or {}))

    monkeypatch.setattr(events, "log_event", log_event)
    runner = PipelineRunner("p-1", tmp_path, _Answer(""), "m", mode="iterative", backend_name="mock", max_cost_usd=10)
    runner._strategist.decide = AsyncMock(  # type: ignore[method-assign]
        return_value=StrategistDecision(action="dispatch_parallel", work_orders=[], rationale="why")
    )
    verdicts = iter(
        [
            CeilingCheckResult(verdict="continue", reason="more"),
            CeilingCheckResult(verdict="pivot", reason="other step"),
        ]
    )
    runner._strategist.ceiling_check = AsyncMock(side_effect=lambda *a, **k: next(verdicts))  # type: ignore[method-assign]
    await runner._run_iterative_phase()
    kinds = [(et, p.get("round"), p.get("verdict")) for et, p in logged]
    assert kinds == [
        ("improvement_round", 1, None),
        ("ceiling_check", 1, "continue"),
        ("improvement_round", 2, None),
        ("ceiling_check", 2, "pivot"),
        ("pivot", 2, None),
    ]
    assert runner._pivot_count == 1

    # A second pivot in the same study is refused, and the record says so.
    logged.clear()
    runner._strategist.ceiling_check = AsyncMock(  # type: ignore[method-assign]
        return_value=CeilingCheckResult(verdict="pivot", reason="again")
    )
    await runner._run_iterative_phase()
    assert [et for et, _ in logged] == ["improvement_round", "ceiling_check"]
    assert logged[1][1]["pivot_refused"] == "one change of approach per study"

    # The strategist ends the rounds: recorded too.
    logged.clear()
    runner._strategist.decide = AsyncMock(  # type: ignore[method-assign]
        return_value=StrategistDecision(action="complete", work_orders=[], rationale="nothing left")
    )
    await runner._run_iterative_phase()
    assert logged == [("improvement_stopped", {"round": 1, "reason": "nothing left"})]


def test_the_rounds_in_plain_words_whatever_the_order_of_the_log():
    rows = [
        {"event_type": "pivot", "payload": json.dumps({"round": 2, "specialists": ["abstract_writer"]})},
        {"event_type": "ceiling_check", "payload": {"round": 2, "verdict": "pivot", "reason": "r2"}},
        {"event_type": "improvement_round", "payload": {"round": 2, "specialists": ["section_writer"]}},
        {"event_type": "ceiling_check", "payload": {"round": 1, "verdict": "continue"}},
        {"event_type": "improvement_round", "payload": {"round": 1, "specialists": ["econometrics_specialist"]}},
        {"event_type": "phase_start", "payload": "{}"},
        {"event_type": "ceiling_check", "payload": "not json"},
    ]
    assert labels.round_summary(rows) == [
        {"round": 1, "specialists": ["Estimation"], "reason": "", "ceiling": "another round", "ceiling_reason": ""},
        {
            "round": 2,
            "specialists": ["Sections and table layout"],
            "reason": "",
            "ceiling": "a change of approach",
            "ceiling_reason": "r2",
            "pivot": ["Abstract"],
        },
    ]
    assert labels.ceiling_verdict("proceed_to_review") == "ready for review"


def _runner(tmp_path: Path, monkeypatch) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    from src.core.strategist.runner import PipelineRunner
    from src.db import events

    logged: list[tuple[str, dict[str, Any]]] = []

    async def log_event(paper_id, event_type, stage=None, specialist=None, payload=None):
        logged.append((event_type, payload or {}))

    monkeypatch.setattr(events, "log_event", log_event)
    runner = PipelineRunner("p-1", tmp_path, _Answer(""), "m", mode="iterative", backend_name="mock", max_cost_usd=10)
    return runner, logged


async def _pivot_once(runner: Any, pivots: list[Any]) -> None:
    from src.core.strategist.actions import CeilingCheckResult, StrategistDecision

    runner._strategist.decide = AsyncMock(  # type: ignore[method-assign]
        return_value=StrategistDecision(action="dispatch_parallel", work_orders=[], rationale="why")
    )
    runner._strategist.ceiling_check = AsyncMock(  # type: ignore[method-assign]
        return_value=CeilingCheckResult(verdict="pivot", reason="other step", suggested_pivots=pivots)
    )
    await runner._run_iterative_phase()


async def test_a_pivot_that_would_rewrite_the_whole_draft_is_refused_and_recorded(tmp_path: Path, monkeypatch):
    """A change of approach runs through the round's guarded dispatch: no full rewrite, said in plain words."""
    from src.core.strategist.actions import WorkOrder
    from src.core.strategist.runner import FULL_REWRITE_REFUSED

    runner, logged = _runner(tmp_path, monkeypatch)
    ran: list[list[str]] = []

    async def execute(orders):
        ran.append([o.specialist for o in orders])
        return []

    runner._execute_orders = execute  # type: ignore[method-assign]
    pivots = [
        WorkOrder(specialist="paper_drafter", focus="Rewrite it all."),
        WorkOrder(specialist="abstract_writer", focus="Lead with the pre-registered window."),
    ]
    await _pivot_once(runner, pivots)
    assert ran == [["abstract_writer"]]
    pivot = dict(logged)["pivot"]
    assert pivot["specialists"] == ["abstract_writer"]
    assert pivot["refused"] == [{"specialist": "paper_drafter", "note": FULL_REWRITE_REFUSED}]
    rounds = labels.round_summary([{"event_type": et, "payload": p} for et, p in logged])
    assert rounds[0]["pivot"] == ["Abstract"] and rounds[0]["pivot_refused"] == ["Paper draft"]


async def test_the_circuit_breaker_counts_a_pivot(tmp_path: Path, monkeypatch):
    """A specialist that has failed its attempts is not run again as the change of approach."""
    from src.core.strategist.actions import WorkOrder
    from src.core.strategist.runner import _MAX_SPECIALIST_ATTEMPTS, CircuitBreakerError

    runner, _ = _runner(tmp_path, monkeypatch)
    runner._failure_counts["abstract_writer"] = _MAX_SPECIALIST_ATTEMPTS
    runner._execute_orders = AsyncMock(return_value=[])  # type: ignore[method-assign]
    with pytest.raises(CircuitBreakerError):
        await _pivot_once(
            runner, [WorkOrder(specialist="abstract_writer", focus="Lead with the pre-registered window.")]
        )
    runner._execute_orders.assert_not_called()


class _Merge:
    def __init__(self, applied: int, failed: int = 0) -> None:
        from types import SimpleNamespace

        edit = SimpleNamespace(find="2.5", replace="2.4", source_finding="polish:polish_numerics", target="paper:full")
        self.applied = [SimpleNamespace(edit=edit)] * applied
        self.failed = [SimpleNamespace(edit=edit, error="find string not found")] * failed
        self.n_applied, self.n_failed, self.diff = applied, failed, "-2.5\n+2.4\n"


@pytest.mark.parametrize(
    "applied, failed, after, decision, changed",
    [
        (1, 0, (0, 2), "applied", True),
        (1, 0, (1, 2), "undone: the corrected draft had more numbers that differ from the results", False),
        (0, 0, (0, 2), "no change: the notes asked for nothing the draft needs", False),
        (0, 1, (0, 2), "no change: the corrections could not be applied", False),
    ],
)
async def test_a_polish_note_changes_the_draft_or_leaves_a_recorded_decision(
    tmp_path: Path, monkeypatch, applied, failed, after, decision, changed
):
    """The polish notes go to the targeted corrections; the number check undoes corrections that make numbers worse."""
    from types import SimpleNamespace

    from src.core.pipeline import verify_numbers

    runner, logged = _runner(tmp_path, monkeypatch)
    (tmp_path / "paper_draft.tex").write_text("SD about 2.5 to 3.0.\n", encoding="utf-8")
    (tmp_path / "polish_numerics.md").write_text("Write 2.4 to 2.9 for the SD range.\n", encoding="utf-8")
    seen: list[Any] = []

    async def patch(findings):
        seen.extend(findings)
        if applied:
            (tmp_path / "paper_draft.tex").write_text("SD about 2.4 to 2.9.\n", encoding="utf-8")
        return _Merge(applied, failed)

    counts = iter([(0, 2), after])

    def verify(draft, ws):
        t, x = next(counts)
        return SimpleNamespace(critical_mismatches=[object()] * t, prose_mismatched=x)

    monkeypatch.setattr(verify_numbers, "verify", verify)
    runner._dispatch_patch_revisor = patch  # type: ignore[method-assign]
    await runner._apply_polish_notes(["polish_numerics"])
    assert [(f.source, f.source_detail, f.target) for f in seen] == [("polish", "polish_numerics", "paper:full")]
    assert "Write 2.4 to 2.9" in seen[0].problem
    record = json.loads((tmp_path / "polish_corrections.json").read_text(encoding="utf-8"))
    assert record["decision"] == decision and record["notes"] == ["polish_numerics"]
    assert ("2.4" in (tmp_path / "paper_draft.tex").read_text(encoding="utf-8")) is changed
    assert logged == [
        ("polish_applied", {"notes": ["polish_numerics"], "decision": decision, "changes_made": int(changed)})
    ]


async def test_without_polish_notes_nothing_is_dispatched(tmp_path: Path, monkeypatch):
    runner, logged = _runner(tmp_path, monkeypatch)
    runner._dispatch_patch_revisor = AsyncMock()  # type: ignore[method-assign]
    await runner._apply_polish_notes(["polish_formula"])  # its note was not written
    runner._dispatch_patch_revisor.assert_not_called()
    assert not logged and not (tmp_path / "polish_corrections.json").exists()
