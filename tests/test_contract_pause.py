"""After the last failed attempt, output that fails its contract stops the run for the researcher.

Live run 2026-10-03: data_analyst's output failed its contract three times and
the run ended `failed` ("All specialists failed in parallel batch: ..."). Now
the run stops at a researcher step (kind `contract`) with each attempt's
violations; the researcher approves the output as it is, edits, instructs or
sends the specialist back. Crashes still fail the run.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.researcher import CONTRACT_STEP, apply_action, pending_review
from src.core.pipeline.state import PipelineState
from src.core.specialists.contracts import WorkOrder
from src.core.specialists.dispatcher import ContractFailureError, execute_parallel, order_by_dependencies
from src.modules.llm.base import ToolLoopResult
from src.modules.tracking.usage import TokenUsage
from tests.conftest import MockLLMBackend

TEMPLATE = """
name = "contracttest"
description = "Two specialists in parallel."
methodologies = ["empirical"]

[[steps]]
kind = "specialists"
name = "work"
run = ["idea_developer", "data_analyst"]
parallel = true
"""


class _Backend(MockLLMBackend):
    """data_analyst claims success without writing anything while `bad` is set (a contract violation)."""

    def __init__(self, bad: bool = True) -> None:
        super().__init__()
        self.bad = bad
        self.prompts: dict[str, list[str]] = {}

    async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
        sp = self._detect_specialist(system)
        self.prompts.setdefault(sp, []).append(str(messages[0]["content"]))
        if sp == "data_analyst" and self.bad:
            self.specialist_calls.append(sp)
            return ToolLoopResult(
                success=True, output="done", usage=TokenUsage(input_tokens=1, output_tokens=1), tool_calls_made=0
            )
        return await super().tool_loop(system, messages, tools, tool_handler, max_turns, **kw)


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


@pytest.fixture
def study(tmp_path: Path, monkeypatch) -> tuple[str, Path]:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "contracttest.toml").write_text(TEMPLATE)
    pid = str(uuid.uuid4())
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": pid, "research_question": "Q?"}))
    return pid, ws


async def _run(pid: str, ws: Path, backend: MockLLMBackend) -> dict[str, Any]:
    from src.core.strategist.runner import PipelineRunner

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=pid,
            workspace=ws,
            backend=backend,
            model="m",
            mode="single_pass",
            backend_name="mock",
            pipeline="contracttest",
            max_cost_usd=100.0,
        )
        return await runner.run()


# ── the dispatcher ──────────────────────────────────────────────────────────


async def test_a_batch_with_one_failing_specialist_keeps_the_others_output(tmp_path: Path, events):
    pid = str(uuid.uuid4())
    backend = _Backend()
    orders = [
        WorkOrder(paper_id=pid, specialist="idea_developer", focus="plan"),
        WorkOrder(paper_id=pid, specialist="data_analyst", focus="data"),
    ]
    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
        pytest.raises(ContractFailureError) as exc,
    ):
        await execute_parallel(orders, backend, tmp_path, "m", [], [], "mock")
    cf = exc.value
    assert [f["specialist"] for f in cf.failures] == ["data_analyst"]
    attempts = cf.failures[0]["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2, 3]
    assert all(any("data_summary.md" in v for v in a["violations"]) for a in attempts)
    assert "data_summary.md" in cf.failures[0]["files"]
    # idea_developer succeeded and keeps its output.
    assert [c.specialist for c in cf.contributions if c.success] == ["idea_developer"]
    assert (tmp_path / "paper_plan.md").is_file()
    assert backend.specialist_calls.count("idea_developer") == 1


async def test_a_crash_still_fails_the_batch(tmp_path: Path, events):
    pid = str(uuid.uuid4())
    backend = MockLLMBackend(fail_specialists={"data_analyst"})
    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
        pytest.raises(RuntimeError, match="All specialists failed") as exc,
    ):
        await execute_parallel(
            [WorkOrder(paper_id=pid, specialist="data_analyst", focus="d")], backend, tmp_path, "m", [], [], "mock"
        )
    assert not isinstance(exc.value, ContractFailureError)


def test_a_specialist_never_runs_beside_the_one_whose_output_it_reads():
    """The live log: econometrics_specialist in data_analyst's group, estimating on no data."""
    pid = "p"
    planned = [
        WorkOrder(paper_id=pid, specialist="idea_developer", focus="", parallel_group=0),
        WorkOrder(paper_id=pid, specialist="identification_strategist", focus="", parallel_group=0),
        WorkOrder(paper_id=pid, specialist="data_architect", focus="", parallel_group=1),
        WorkOrder(paper_id=pid, specialist="data_analyst", focus="", parallel_group=2),
        WorkOrder(paper_id=pid, specialist="econometrics_specialist", focus="", parallel_group=2),
        WorkOrder(paper_id=pid, specialist="paper_drafter", focus="", parallel_group=3),
        WorkOrder(paper_id=pid, specialist="abstract_writer", focus="", parallel_group=3),
    ]
    ordered, moves = order_by_dependencies(planned)
    g = {o.specialist: o.parallel_group for o in ordered}
    assert g["data_architect"] < g["data_analyst"] < g["econometrics_specialist"] < g["paper_drafter"]
    # Everything planned later stays later: the abstract does not move up beside the estimation.
    assert g["abstract_writer"] == g["paper_drafter"]
    assert g["idea_developer"] == g["identification_strategist"] == 0
    assert moves == ["econometrics_specialist waits for data_analyst (planned in the same or a later group)"]
    # A consumer planned before its producer moves behind it.
    early = [
        WorkOrder(paper_id=pid, specialist="econometrics_specialist", focus="", parallel_group=0),
        WorkOrder(paper_id=pid, specialist="data_analyst", focus="", parallel_group=1),
    ]
    g2 = {o.specialist: o.parallel_group for o in order_by_dependencies(early)[0]}
    assert g2["data_analyst"] < g2["econometrics_specialist"]
    # A dependency outside the dispatch is no constraint.
    alone = [WorkOrder(paper_id=pid, specialist="econometrics_specialist", focus="", parallel_group=0)]
    assert order_by_dependencies(alone) == (alone, [])


# ── the run ─────────────────────────────────────────────────────────────────


async def test_three_failed_attempts_pause_the_run_with_the_reasons(study, events):
    pid, ws = study
    result = await _run(pid, ws, _Backend())
    assert result["status"] == "paused" and result["reason"] == "contract"
    st = PipelineState.load(ws, pid, "single_pass")
    p = pending_review(ws, st)
    assert p is not None and p.stage == CONTRACT_STEP and p.kind == "contract"
    assert "data_summary.md" in p.files
    reasons = st.metadata["review"]["reasons"]
    assert len(reasons) == 3 and reasons[0].startswith("data_analyst, attempt 1 of 3: data_summary.md")
    halted = [e for e in events if e[0] == "contract_halted"]
    assert halted and halted[0][2]["specialists"][0]["specialist"] == "data_analyst"
    assert halted[0][2]["succeeded"] == ["idea_developer"]
    assert (ws / "paper_plan.md").is_file()


async def test_send_back_with_a_remark_gives_new_attempts_and_continues(study, events):
    pid, ws = study
    backend = _Backend()
    await _run(pid, ws, backend)
    st = PipelineState.load(ws, pid, "single_pass")
    apply_action(ws, st, {"action": "send_back", "step": "data_analyst", "remark": "Write data_summary.md."})
    st.save(ws)
    backend.bad = False
    result = await _run(pid, ws, backend)
    assert result["status"] == "completed", result
    assert "Write data_summary.md." in backend.prompts["data_analyst"][-1]
    assert backend.specialist_calls.count("idea_developer") == 1  # kept, not run again
    assert (ws / "data_summary.md").is_file()
    st = PipelineState.load(ws, pid, "single_pass")
    assert st.pending_review_stage is None and "contract_pause" not in st.metadata


async def test_a_send_back_that_fails_again_stops_again(study, events):
    pid, ws = study
    backend = _Backend()
    await _run(pid, ws, backend)
    st = PipelineState.load(ws, pid, "single_pass")
    apply_action(ws, st, {"action": "send_back", "step": "data_analyst", "remark": "Try again."})
    st.save(ws)
    result = await _run(pid, ws, backend)
    assert result["status"] == "paused" and result["reason"] == "contract"
    assert backend.specialist_calls.count("data_analyst") == 6


async def test_approve_as_is_continues_and_the_dossier_marks_it(study, events, tmp_path: Path):
    pid, ws = study
    backend = _Backend()
    await _run(pid, ws, backend)
    st = PipelineState.load(ws, pid, "single_pass")
    payload = apply_action(ws, st, {"action": "approve"})
    st.save(ws)
    assert payload["decision"] == "accepted_as_is"
    acc = payload["accepted"][0]
    assert acc["specialist"] == "data_analyst" and acc["contract_failed"] is True and acc["violations"]
    result = await _run(pid, ws, backend)
    assert result["status"] == "completed", result
    assert backend.specialist_calls.count("data_analyst") == 3  # not run again
    st = PipelineState.load(ws, pid, "single_pass")
    assert st.metadata["contract_accepted"][0]["specialist"] == "data_analyst"

    # The dossier: the stop is a check step with each attempt; the output is marked.
    from src.core.dossier import recorded_workflow

    halted = next(e for e in events if e[0] == "contract_halted")
    rows = [
        ("phase_start", "work", None, {}),
        ("specialist_start", None, "data_analyst", {}),
        ("specialist_end", None, "data_analyst", {"success": False}),
        ("contract_halted", "work", None, halted[2]),
        ("researcher_action", CONTRACT_STEP, None, payload),
    ]
    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE pipeline_events (paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT)"
    )
    for i, (et, stage, sp, data) in enumerate(rows):
        con.execute(
            "INSERT INTO pipeline_events VALUES (?,?,?,?,?,?)",
            (pid, et, stage, sp, json.dumps(data), f"2026-10-03 10:{i:02d}:00"),
        )
    con.commit()
    con.close()
    steps = recorded_workflow(db, pid)
    spec_step, check, researcher = steps
    assert spec_step["approved_by_researcher"]["contract_failed"] is True
    assert check["check"] == "output_contract" and check["halted"] is True
    assert len(check["specialists"][0]["attempts"]) == 3
    assert researcher["decision"] == "accepted_as_is"
    # The kept outputs go under `kept`: `accepted` is a yes/no in the dossier format,
    # and e2er.org refused a dossier with a list there (E2E-16, 2026-10-04).
    assert "accepted" not in researcher and researcher["kept"][0]["specialist"] == "data_analyst"


async def test_a_plain_resume_does_not_approve_the_output(study, events):
    """`e2er resume` gives new attempts; keeping failed output is only ever the researcher's explicit decision."""
    pid, ws = study
    backend = _Backend()
    await _run(pid, ws, backend)
    backend.bad = False
    result = await _run(pid, ws, backend)  # no action: what resume_paper leaves for a contract stop
    assert result["status"] == "completed"
    st = PipelineState.load(ws, pid, "single_pass")
    assert "contract_accepted" not in st.metadata
    assert backend.specialist_calls.count("data_analyst") == 4


# ── what the researcher sees: API, dashboard page, CLI ─────────────────────


async def test_the_review_api_page_and_cli_show_each_attempt(study, events):
    from fastapi.testclient import TestClient

    from src.api.app import app
    from src.cli_review import format_pending

    pid, ws = study
    await _run(pid, ws, _Backend())
    row = {"id": pid, "workspace": str(ws), "mode": "single_pass", "pipeline": "contracttest", "status": "paused"}
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row),
        patch("src.db.events.fetch_events", new_callable=AsyncMock, return_value=[]),
    ):
        client = TestClient(app)
        got = client.get(f"/api/papers/{pid}/review").json()
        page = client.get(f"/papers/{pid}/review").text
    pending = got["pending"]
    assert pending["kind"] == "contract" and pending["stage"] == CONTRACT_STEP
    assert len(pending["failures"][0]["attempts"]) == 3
    assert "data_analyst" in got["sendable"]
    assert "Keep the output as it is and continue" in page and "data_analyst: 3 attempts" in page
    text = format_pending(got)
    assert "data_analyst: the output failed its check in all 3 attempts" in text
    assert "    attempt 3: data_summary.md" in text


def test_a_plain_resume_leaves_a_contract_stop_unapproved(tmp_path: Path):
    """resume_paper approves an ordinary researcher step on resume, never a contract stop."""
    import inspect

    from src.api import app as app_module

    src = inspect.getsource(app_module.resume_paper)
    assert 'get("kind") == "contract"' in src and "not contract_stop" in src
