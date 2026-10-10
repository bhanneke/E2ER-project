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
