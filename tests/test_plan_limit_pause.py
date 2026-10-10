"""A subscription plan's usage limit pauses the run; it does not fail it.

Live, 2026-10-11 (e2er 0.15.2, Codex CLI): "status failed: RuntimeError: All
specialists failed in parallel batch: idea_developer: Codex failed (exit 1):
You’ve hit your usage limit. Upgrade to Pro …". Nothing was broken: the ChatGPT
plan's limit was used up and every call would fail until it reset.

Pinned here: the CLIs' own wording is recognised (Codex, Claude Code, Gemini)
with the reset time when stated; the backends raise PlanLimitReachedError without
retrying; the dispatcher lets the rest of a parallel batch finish and counts no
attempt; the runner pauses (``paused_plan_limit``) with a plain sentence, marks
no step failed, and a resume runs the interrupted specialist again; the dossier,
the dashboard and `e2er status` say so plainly.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.llm.plan_limit import (
    PAUSE_TAIL,
    PlanLimitReachedError,
    detect,
    is_plan_limit_status,
    status_text,
)

#: The live message (2026-10-11), as the run recorded it (clipped by the status line).
LIVE_CODEX = (
    "Codex failed (exit 1): You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
    "visit https://chatgpt.com/co…"
)


# ── recognising the CLIs' wording ───────────────────────────────────────────


@pytest.mark.parametrize(
    "text, resets",
    [
        (LIVE_CODEX, None),
        (
            "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
            "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 2:30 PM.",
            "at 2:30 PM",
        ),
        ("You've hit your usage limit. Try again in 3 hours 12 minutes.", "in 3 hours 12 minutes"),
        ('{"type":"error","message":"usage_limit_reached"}', None),
    ],
)
def test_codex_limit_wording(text, resets):
    limit = detect("codex", text)
    assert isinstance(limit, PlanLimitReachedError) and limit.backend == "codex" and limit.resets == resets


@pytest.mark.parametrize(
    "text, resets",
    [
        ("Claude usage limit reached. Your limit will reset at 2pm (Europe/Berlin).", "at 2pm, Europe/Berlin"),
        ("5-hour limit reached ∙ resets 3pm", "at 3pm"),
        ("You've hit your limit · resets 2pm (Europe/Berlin)", "at 2pm, Europe/Berlin"),
        ("Weekly limit reached ∙ resets Oct 14, 9am", "at Oct 14, 9am"),
        ("Opus weekly limit reached ∙ resets Oct 14, 9am", "at Oct 14, 9am"),
        ("Claude AI usage limit reached", None),
    ],
)
def test_claude_limit_wording(text, resets):
    limit = detect("claude_code", text)
    assert isinstance(limit, PlanLimitReachedError) and limit.resets == resets


def test_claude_unix_reset_time_is_shown_as_local_time():
    ts = int(datetime.now().replace(hour=14, minute=30, second=0, microsecond=0).timestamp())
    limit = detect("claude_code", f"Claude AI usage limit reached|{ts}")
    assert limit is not None and limit.resets == "at 14:30"


def test_gemini_daily_quota_is_a_limit_a_rate_limit_is_not():
    assert detect("gemini", "You have exhausted your daily quota on this model.") is not None
    assert detect("gemini", "Quota exceeded for quota metric 'Generate Content API requests per minute'") is None


@pytest.mark.parametrize(
    "backend, text",
    [
        ("codex", "stream disconnected before completion: error sending request"),
        ("codex", "not logged in"),
        ("claude_code", 'API Error: {"api_error_status":529,"type":"overloaded_error"}'),
        ("claude_code", "spending limit reached: $1.00 of $1.00"),
        ("claude_code", "Claude Code returned error_max_turns (max_turns=80, tool_calls=80)"),
        ("codex", ""),
    ],
)
def test_other_errors_are_not_a_plan_limit(backend, text):
    assert detect(backend, text) is None


def test_the_status_sentence():
    assert status_text("codex", "at 14:30") == (
        "Your ChatGPT plan's usage limit is reached (resets at 14:30). "
        "The run is paused; press Resume when the limit has reset."
    )
    assert status_text("claude_code") == (
        "Your Claude plan's usage limit is reached. The run is paused; press Resume when the limit has reset."
    )
    assert is_plan_limit_status(status_text("gemini")) and not is_plan_limit_status("BudgetExceededError: x")


# ── the backends raise, once, without retrying ──────────────────────────────


def _summary(result: str, is_error: bool = True) -> str:
    return json.dumps({"type": "result", "is_error": is_error, "result": result})


def _proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = None
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.wait = AsyncMock()
    return proc


async def _call(backend):
    return await backend.tool_loop(
        system="s", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None, max_turns=1
    )


async def test_codex_raises_on_the_live_message_and_does_not_retry():
    from src.modules.llm.codex import CodexBackend

    events = (
        json.dumps(
            {"type": "error", "message": "You’ve hit your usage limit. Upgrade to Pro (…), try again at 2:30 PM."}
        )
        + "\n"
        + json.dumps({"type": "turn.failed", "error": {"message": "You’ve hit your usage limit."}})
    )
    spawn = AsyncMock(return_value=_proc(1, events.encode()))
    with (
        patch("src.modules.llm.codex.asyncio.create_subprocess_exec", spawn),
        patch("src.modules.llm.codex.asyncio.sleep", AsyncMock()),
        pytest.raises(PlanLimitReachedError) as caught,
    ):
        await _call(CodexBackend())
    assert spawn.await_count == 1
    assert caught.value.backend == "codex"
    assert str(caught.value).startswith("Your ChatGPT plan's usage limit is reached")


@pytest.mark.parametrize(
    "returncode, stdout, stderr",
    [
        # The JSON summary of a failed call (exit 1), older wording with a Unix time.
        (1, _summary("Claude AI usage limit reached|1760190000"), ""),
        # The same on stderr: stdout's JSON is not lost when stderr has text.
        (1, _summary("5-hour limit reached ∙ resets 3pm"), "x"),
        # Exit 0 with is_error.
        (0, _summary("You've hit your limit · resets 2pm"), ""),
        # Exit 0, the whole answer is the notice (older CLIs).
        (
            0,
            _summary("Claude AI usage limit reached|1760190000", is_error=False),
            "",
        ),
        (1, "", "Claude usage limit reached. Your limit will reset at 2pm (Europe/Berlin)."),
    ],
)
async def test_claude_code_raises_on_its_limit_messages(monkeypatch, tmp_path, returncode, stdout, stderr):
    monkeypatch.setenv("CLAUDE_CODE_PATH", "/usr/local/bin/claude")
    monkeypatch.setenv("CLAUDE_CODE_CWD", str(tmp_path))
    from src.config import get_settings

    get_settings.cache_clear()
    from src.modules.llm.claude_code import ClaudeCodeBackend

    spawn = AsyncMock(return_value=_proc(returncode, stdout.encode(), stderr.encode()))
    with (
        patch("asyncio.create_subprocess_exec", spawn),
        patch("asyncio.sleep", AsyncMock()),
        pytest.raises(PlanLimitReachedError) as caught,
    ):
        await _call(ClaudeCodeBackend())
    assert spawn.await_count == 1 and caught.value.backend == "claude_code"
    assert str(caught.value).startswith("Your Claude plan's usage limit is reached")


async def test_gemini_raises_on_a_used_up_daily_quota():
    from src.modules.llm.gemini import GeminiBackend

    spawn = AsyncMock(return_value=_proc(1, b"", b"You have exhausted your daily quota on this model."))
    with (
        patch("src.modules.llm.gemini.asyncio.create_subprocess_exec", spawn),
        patch("src.modules.llm.gemini._probe_gemini_flags", lambda _p: ("yolo", "json")),
        pytest.raises(PlanLimitReachedError),
    ):
        await _call(GeminiBackend())


# ── the dispatcher: no attempt counted, the batch's others finish ───────────


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, specialist=None, payload=None, **kw):
        log.append((kind, specialist, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


async def test_a_parallel_batch_finishes_the_others_then_raises(tmp_path, events, monkeypatch):
    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import Contribution, WorkOrder

    calls: list[str] = []

    async def fake_run_specialist(*, work_order, **kw):
        calls.append(work_order.specialist)
        if work_order.specialist == "idea_developer":
            raise PlanLimitReachedError("codex", LIVE_CODEX)
        return Contribution(paper_id=work_order.paper_id, specialist=work_order.specialist, output="", success=True)

    monkeypatch.setattr(dispatcher, "run_specialist", fake_run_specialist)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget_by_paper_id", AsyncMock())
    done: list[str] = []
    token = dispatcher.specialist_done.set(lambda wo: done.append(wo.specialist))
    orders = [
        WorkOrder(paper_id="p", specialist="idea_developer", focus="plan"),
        WorkOrder(paper_id="p", specialist="literature_scanner", focus="lit"),
    ]
    try:
        with pytest.raises(PlanLimitReachedError) as caught:
            await dispatcher.execute_parallel(orders, MagicMock(), tmp_path, "m", backend_name="codex")
    finally:
        dispatcher.specialist_done.reset(token)
    # One call each: the limit is not retried, the other specialist finished and is recorded as done.
    assert sorted(calls) == ["idea_developer", "literature_scanner"]
    assert done == ["literature_scanner"]
    assert caught.value.specialist == "idea_developer"
    assert not [e for e in events if e[0] == "specialist_failed"]


# ── the runner: paused, never failed; resume reruns the interrupted specialist ─


def _runner(tmp_path: Path):
    from src.core.strategist.runner import PipelineRunner

    paper_id = str(uuid.uuid4())
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": paper_id,
                "title": "T",
                "research_question": "Q?",
                "datasets": [],
                "mode": "single_pass",
                "methodology": "empirical",
                "current_stage": "idea",
            }
        )
    )
    return PipelineRunner(
        paper_id=paper_id, workspace=ws, backend=MagicMock(), model="m", mode="single_pass", backend_name="codex"
    )


async def test_the_run_pauses_with_the_sentence_and_no_step_failed(tmp_path, events):
    runner = _runner(tmp_path)
    statuses: list[tuple[str, str | None]] = []

    async def _execute(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            statuses.append((params["s"], params.get("e")))

    async def _initial(self):
        raise PlanLimitReachedError("codex", LIVE_CODEX + " try again at 14:30.", "at 14:30", "idea_developer")

    with (
        patch("src.db.client.execute", side_effect=_execute),
        patch("src.core.strategist.runner.PipelineRunner._run_initial_phase", _initial),
    ):
        result = await runner.run()

    assert result == {
        "status": "paused",
        "reason": "plan_limit",
        "backend": "codex",
        "resets": "at 14:30",
        "specialist": "idea_developer",
    }
    final = statuses[-1]
    assert final == ("paused", status_text("codex", "at 14:30"))
    assert "failed" not in [s for s, _ in statuses]
    kinds = [k for k, _sp, _p in events]
    assert "paused_plan_limit" in kinds and "failed" not in kinds and "specialist_failed" not in kinds
    payload = next(p for k, _sp, p in events if k == "paused_plan_limit")
    assert payload["backend"] == "codex" and payload["resets"] == "at 14:30"
    assert payload["specialist"] == "idea_developer" and payload["status"].endswith(PAUSE_TAIL)
    state = json.loads((runner._workspace / ".pipeline_state.json").read_text())
    assert "initial" not in state["completed_stages"]
    assert runner._failure_counts.get("idea_developer", 0) == 0


async def test_resume_runs_the_interrupted_specialist_again(tmp_path, events, monkeypatch):
    """Same record as the spending-limit pause: the finished work orders are kept, the rest runs on resume."""
    from src.core.pipeline.state import PipelineState
    from src.core.specialists import contract_check
    from src.core.specialists.contracts import Contribution
    from src.core.specialists.dispatcher import specialist_done
    from tests.test_researcher_step import PID
    from tests.test_researcher_step import _runner as step_runner

    r = step_runner(tmp_path, [{"kind": "strategist", "name": "initial"}])
    r._triggers = []
    planned = [
        SimpleNamespace(specialist="idea_developer", focus="plan", parallel_group=0, context_tier=1),
        SimpleNamespace(specialist="literature_scanner", focus="lit", parallel_group=0, context_tier=1),
        SimpleNamespace(specialist="data_analyst", focus="data", parallel_group=1, context_tier=1),
    ]
    r._strategist = SimpleNamespace(
        decide=AsyncMock(return_value=SimpleNamespace(action="dispatch", work_orders=planned, rationale=""))
    )

    async def first_dispatch(decision):
        # literature_scanner finishes; idea_developer hits the ChatGPT plan's limit.
        orders = r._to_contract_orders(decision.work_orders)
        specialist_done.get()(orders[1])
        raise PlanLimitReachedError("codex", LIVE_CODEX, specialist="idea_developer")

    r._dispatch = first_dispatch
    with pytest.raises(PlanLimitReachedError):
        await r._run_initial_phase()

    monkeypatch.setattr(
        contract_check,
        "check_specialist_artifacts",
        lambda ws, sp: [SimpleNamespace(ok=sp == "literature_scanner")],
    )
    resumed = step_runner(tmp_path, [{"kind": "strategist", "name": "initial"}])
    resumed._triggers = []
    resumed._state = PipelineState.load(tmp_path, PID, "single_pass")
    resumed._strategist = SimpleNamespace(decide=AsyncMock(side_effect=AssertionError("planned again")))
    ran: list[list[str]] = []

    async def execute(orders):
        ran.append([o.specialist for o in orders])
        return [Contribution(paper_id=PID, specialist=o.specialist, output="", success=True) for o in orders]

    resumed._execute_orders = execute
    await resumed._run_initial_phase()
    assert ran == [["idea_developer", "data_analyst"]]


# ── the dossier, the dashboard text, `e2er status` ──────────────────────────


def test_the_dossier_records_the_pause_plainly(tmp_path):
    from src.core.dossier import read_run
    from tests.test_dossier_run import PID, _db

    text = status_text("codex", "at 14:30")
    db = _db(
        tmp_path,
        [
            (
                "paused_plan_limit",
                None,
                None,
                {"backend": "codex", "resets": "at 14:30", "specialist": "idea_developer", "status": text},
                "2026-10-11 12:00:00",
            )
        ],
        status="paused",
    )
    run = read_run(db, PID)
    [ev] = run.events
    assert ev["event"] == "paused_plan_limit" and ev["status"] == text and ev["specialist"] == "idea_developer"
    assert not [w for w in run.workflow if w.get("accepted") is False]


def test_the_dashboard_headline_is_the_whole_sentence():
    from src.api.app import _plain_error
    from src.core import labels

    text = status_text("claude_code", "at 3pm")
    assert _plain_error(text) == text  # not cut at the semicolon
    assert labels.event("paused_plan_limit") == "Paused: the plan's usage limit was reached"


def test_e2er_status_prints_the_sentence_and_the_command():
    from src.cli_status import _format_status_summary

    text = status_text("codex", "at Oct 11th, 2026 2:30 PM")
    out = _format_status_summary({"id": "abc", "status": "paused", "last_error": text})
    assert f"Paused:     {text}" in out and "e2er resume abc" in out and "Last error" not in out


def test_the_studies_list_carries_the_sentence_for_the_latest_run():
    from src.db.studies import group

    text = status_text("codex")
    row = {
        "id": "1",
        "title": "T",
        "research_question": "Q",
        "status": "paused",
        "pipeline": "empirical",
        "created_at": "2026-10-11 10:00:00",
        "updated_at": "2026-10-11 11:00:00",
        "archived_at": None,
        "last_error": text,
    }
    other = {**row, "id": "2", "status": "paused", "last_error": "BudgetExceededError: spent $1"}
    [study] = group([row]).values()
    assert study.as_dict()["latest_plan_limit"] == text and study.as_dict()["latest_id"] == "1"
    [study] = group([other]).values()
    assert study.as_dict()["latest_plan_limit"] == ""


def test_the_vocabulary_check_reads_the_sentence_as_plain():
    from tests.test_dashboard_vocabulary import problems

    assert not problems(f"<p>{status_text('codex', 'at 14:30')}</p>")
    assert not problems(f"<p>{status_text('claude_code')}</p>")
    assert re.search(r"press Resume", status_text("gemini"))
