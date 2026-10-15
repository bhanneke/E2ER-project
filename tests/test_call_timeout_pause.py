"""A specialist call that runs into its time limit pauses the run (2026-10-14 text-analysis demo).

Live, on Claude Code: the data analyst's third attempt was stopped at 1,800 s
while it loaded Gutenberg texts, and the whole study failed. Pinned here: the
CLI reports the wall-clock deadline as ``stop_reason="timeout"``; a template's
``[timeouts]`` or a step's ``timeout_minutes`` sets the limit, and the data
analyst gets at least 60 minutes; the timed-out call is recorded once and the
run pauses with a plain sentence (``paused_timeout``), resumable, the specialist
getting a fresh attempt; a reviewer's lost call is tolerated as before.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.pipeline import components
from src.core.pipeline.spec import PipelineError, spec_from_dict
from src.modules.llm.base import ToolLoopResult
from src.modules.llm.cli_support import call_timeout, effective_timeout
from src.modules.llm.plan_limit import CallTimedOutError, PlanLimitReachedError

STEPS = [
    {"kind": "strategist", "name": "initial", "timeout_minutes": 45},
    {"kind": "aggregate", "name": "review", "run": ["methods_reviewer"]},
]


# ── where the limit comes from ──────────────────────────────────────────────


def test_a_template_sets_the_limit_per_specialist_and_per_step():
    spec = spec_from_dict({"name": "t", "steps": STEPS, "timeouts": {"econometrics_specialist": 90}})
    assert spec.timeouts == {"econometrics_specialist": 90} and spec.step("initial").timeout_minutes == 45
    components.enter_step("initial")
    try:
        assert components.timeout_for("econometrics_specialist", spec) == (5400, False)  # the specialist's entry
        assert components.timeout_for("paper_drafter", spec) == (2700, False)  # the step's
        components.enter_step("review")
        assert components.timeout_for("paper_drafter", spec) is None  # the backend's setting
        assert components.timeout_for("data_analyst", spec) == (3600, True)  # at least an hour
    finally:
        components.enter_step(None)
    assert components.timeout_for("data_analyst", None) == (3600, True)


@pytest.mark.parametrize(
    "data, why",
    [
        ({"timeouts": {"nobody": 10}}, "unknown specialist"),
        ({"timeouts": {"data_analyst": 0}}, "whole minutes"),
        ({"timeouts": {"data_analyst": "90"}}, "whole minutes"),
        ({"timeouts": ["data_analyst"]}, "table of specialist = minutes"),
    ],
)
def test_bad_timeouts_are_refused_at_load(data, why):
    with pytest.raises(PipelineError, match=why):
        spec_from_dict({"name": "t", "steps": STEPS, **data})


def test_a_step_timeout_needs_a_step_that_dispatches():
    with pytest.raises(PipelineError, match="steps that dispatch"):
        spec_from_dict({"name": "t", "steps": [{"kind": "researcher", "name": "r", "timeout_minutes": 5}]})


def test_the_backend_uses_the_limit_of_the_call():
    assert effective_timeout(1800) == 1800
    token = call_timeout.set((3600, True))
    try:
        assert effective_timeout(1800) == 3600 and effective_timeout(7200) == 7200  # at least
    finally:
        call_timeout.reset(token)
    token = call_timeout.set((600, False))
    try:
        assert effective_timeout(1800) == 600  # the template's value is the limit
    finally:
        call_timeout.reset(token)


async def test_claude_code_marks_the_deadline_as_a_timeout(monkeypatch, tmp_path):
    from tests.test_claude_code_backend import _timeout_result

    result, _proc = await _timeout_result(monkeypatch, tmp_path, timeout=0)
    assert result.stop_reason == "timeout"
    inner, _proc = await _timeout_result(monkeypatch, tmp_path, timeout=1800)
    assert inner.stop_reason != "timeout"  # a pipe timeout well inside the limit is not the deadline


async def test_claude_code_runs_with_the_limit_of_the_call(monkeypatch, tmp_path):
    from tests.test_claude_code_backend import _settings_for_cli

    _settings_for_cli(monkeypatch, tmp_path)
    from src.modules.llm import claude_code

    seen: dict = {}

    async def invoke(**kw):
        seen["timeout"] = kw["timeout"]
        return ToolLoopResult(success=True, output="ok")

    monkeypatch.setattr(claude_code, "_invoke_cli", invoke)
    token = call_timeout.set((3600, True))
    try:
        await claude_code.ClaudeCodeBackend().tool_loop(
            system="s", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None, max_turns=1
        )
    finally:
        call_timeout.reset(token)
    assert seen["timeout"] == 3600  # CLAUDE_CODE_TIMEOUT=60 here: the hour wins


# ── the specialist: the call is recorded once, the run pauses ───────────────


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, specialist=None, payload=None, **kw):
        log.append((kind, specialist, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


class _TimingOut:
    """A CLI backend whose call runs past its limit; records the limit it was given."""

    def __init__(self):
        self.limits: list = []

    async def tool_loop(self, **kw):
        self.limits.append(call_timeout.get())
        return ToolLoopResult(
            success=False, output="", error="Claude Code timed out after 1801s (limit 1800s)", stop_reason="timeout"
        )


async def test_a_timed_out_call_pauses_the_run_and_is_recorded_once(tmp_path, events, monkeypatch):
    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import WorkOrder

    monkeypatch.setattr("src.modules.tracking.usage.check_budget_by_paper_id", AsyncMock())
    backend = _TimingOut()
    order = WorkOrder(paper_id="p", specialist="data_analyst", focus="load the texts")
    with pytest.raises(CallTimedOutError) as caught:
        await dispatcher.run_with_attempts(order, backend, tmp_path, "m", backend_name="claude_code")
    assert len(backend.limits) == 1  # no second 30-minute attempt: the run pauses at once
    assert backend.limits == [(3600, True)]  # the data analyst's hour
    assert isinstance(caught.value, PlanLimitReachedError) and caught.value.specialist == "data_analyst"
    assert caught.value.event == "paused_timeout"
    assert str(caught.value).startswith(
        "Paused: one call ran into its time limit (30 minutes, 1,800 s) and was stopped "
        "(Data and descriptive analysis)."
    )
    assert "Press Resume" in str(caught.value) and "[timeouts] data_analyst" in str(caught.value)
    failed = [e for e in events if e[0] == "specialist_failed"]
    assert len(failed) == 1 and failed[0][2]["timed_out"] is True


async def test_a_reviewers_timed_out_call_is_tolerated(tmp_path, events, monkeypatch):
    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import WorkOrder

    order = WorkOrder(paper_id="p", specialist="methods_reviewer", focus="review")
    c = await dispatcher.execute_work_order(order, _TimingOut(), tmp_path, "m", backend_name="claude_code")
    assert c.success is False and "timed out" in c.error


async def test_the_runner_pauses_with_the_sentence(tmp_path, events):
    from src.core.strategist.runner import PipelineRunner

    paper_id = str(uuid.uuid4())
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": paper_id, "title": "T", "research_question": "Q?", "mode": "single_pass"})
    )
    runner = PipelineRunner(
        paper_id=paper_id, workspace=ws, backend=MagicMock(), model="m", mode="single_pass", backend_name="claude_code"
    )
    statuses: list[tuple[str, str | None]] = []

    async def _execute(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            statuses.append((params["s"], params.get("e")))

    sentence = "Paused: one call ran into its time limit (30 minutes, 1,800 s) and was stopped (Data analysis)."

    async def _initial(self):
        raise CallTimedOutError("claude_code", "Claude Code timed out after 1801s", sentence, "data_analyst")

    with (
        patch("src.db.client.execute", side_effect=_execute),
        patch("src.core.strategist.runner.PipelineRunner._run_initial_phase", _initial),
    ):
        result = await runner.run()
    assert result["status"] == "paused" and result["reason"] == "timeout"
    assert statuses[-1] == ("paused", sentence)
    kinds = [k for k, _sp, _p in events]
    assert "paused_timeout" in kinds and "failed" not in kinds
    state = json.loads((ws / ".pipeline_state.json").read_text())
    assert "initial" not in state["completed_stages"]  # Resume runs the step (and the analyst) again
