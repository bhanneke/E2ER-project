"""Run-state fixes from the correctness review of 2026-10-23.

* A rerun from a step after the revision (abstract, replication, abstract_writer) left the study
  "in progress" for good: apply_rerun set the state to in_progress and the revision, which decided
  the outcome, did not run again.
* Send-backs and reruns waiting in the state were taken out before their work ran: a check that
  halted, a contract stop or a full disk on the way lost them.
* A send-back ran before the loop entered any step, so the time limit of its step did not apply.
* Two resumes sent together both passed the "is a task running?" check and started two runners.
* "completed" was set although the final export had failed, and "finishing" was shown during the
  whole abstract and replication steps.
* A circuit-breaker pause ran the finalize (compile, audit export, push, export) twice.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from src.core.pipeline import components
from src.core.pipeline.researcher import apply_rerun
from src.core.pipeline.spec import spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.strategist.runner import GateHaltError, PipelineRunner
from src.core.strategist.state import CircuitBreakerError, PaperStatus

PID = "5b0f1f3e-9a51-4d6c-9a43-0c2b8f1e7d21"
REMARK = "Write the abstract again from the revised paper."


def _runner(tmp_path: Path, st: PipelineState, spec) -> PipelineRunner:
    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id, r._workspace, r._mode, r._spec = PID, tmp_path, "single_pass", spec
    r._triggers, r._state, r._in_initial, r._contributions = [], st, False, []
    r._governance, r._failure_counts, r._last_specialist_errors = "full", {}, {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers, r._review_stages = [], [], set()
    r._max_cost_usd, r._pivot_count, r._iteration, r._deep_revision_count = 5.0, 0, 0, 0
    r._steps_done, r._export_error = False, None
    r._in_memory_spent = lambda: 0.0
    return r


@pytest.fixture
def db(monkeypatch):
    """The papers row as the runner writes it, (status, last_error) per update, and the events."""
    rows: list[tuple[str, str | None]] = []
    events: list[str] = []

    async def execute(sql, params=None):
        if "UPDATE papers SET status" in sql:
            rows.append((params["s"], params.get("e")))

    async def log(paper_id, kind, *, stage=None, payload=None, **kw):
        events.append(kind)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr("src.db.client.execute", execute)
    monkeypatch.setattr("src.db.events.log_event", log)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget", noop)
    return rows, events


def _load_as(monkeypatch, st: PipelineState) -> None:
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.load", classmethod(lambda cls, *a: st))


def _paper_spec():
    return spec_from_dict(
        {
            "name": "draft-revise-abstract",
            "steps": [
                {"kind": "specialists", "name": "draft", "run": ["paper_drafter"]},
                {"kind": "specialists", "name": "revision", "run": ["revisor"]},
                {"kind": "specialists", "name": "abstract", "run": ["abstract_writer"]},
                {"kind": "specialists", "name": "package", "run": ["replication_packager"]},
            ],
        }
    )


async def _noop(*a, **k):
    return None


# ── 1: a rerun after the revision ends ───────────────────────────────────────


@pytest.mark.parametrize("step", ["abstract", "package", "abstract_writer"])
@pytest.mark.parametrize("recorded", [True, False])  # a state from before revision_status was recorded
async def test_a_rerun_after_the_revision_completes_again(tmp_path: Path, monkeypatch, db, step, recorded):
    rows, _events = db
    spec = _paper_spec()
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["draft", "revision", "abstract", "package"]
    st.last_status = "completed"
    if recorded:
        st.metadata["revision_status"] = "completed"
    apply_rerun(tmp_path, st, spec, step, REMARK)
    assert st.last_status == "in_progress"
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st, spec)
    ran: list[str] = []

    async def abstract():
        ran.append("abstract")

    async def specialists(s):
        ran.append(s.name)

    r._run_abstract_phase = abstract
    r._run_specialists_step = specialists
    r._run_revision_phase = AsyncMock(side_effect=AssertionError("the revision does not run again"))
    r._best_effort_finalize = _noop
    out = await r.run()
    assert "revision" not in ran and ran[-1] == "package"
    assert out["status"] == "completed"
    assert rows[-1] == ("completed", None)  # not left "in_progress"
    assert st.last_status == "completed"


# ── 9 and 23: send-backs survive an error, and run with their step's time limit ──


def _send_back_spec():
    return spec_from_dict(
        {
            "name": "fetch-compare-review",
            "steps": [
                {"kind": "gate", "name": "fetch", "check": "sandbox", "resumable": False},
                {"kind": "specialists", "name": "compare", "run": ["reproduction_comparer"], "timeout_minutes": 90},
                {"kind": "researcher", "name": "review_report", "files": ["reproduction_report.md"]},
            ],
        }
    )


def _stopped_with_send_backs() -> PipelineState:
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["fetch", "compare"]
    st.pending_review_stage = "review_report"
    st.metadata = {
        "review": {"kind": "researcher", "files": ["reproduction_report.md"]},
        "rerun": [
            {"target": "reproduction_comparer", "remark": "Count again."},
            {"target": "reproduction_comparer", "remark": "And name the versions."},
        ],
        "sent_back": {"stage": "review_report", "specialists": ["reproduction_comparer"]},
    }
    return st


@pytest.mark.parametrize(
    "where, error",
    [
        ("check", GateHaltError("fetch", ["the package is gone"])),
        ("specialist", OSError(28, "No space left on device")),
        ("specialist", RuntimeError("contract")),
    ],
)
async def test_the_send_backs_are_kept_when_something_stops_them(tmp_path: Path, db, where, error):
    spec = _send_back_spec()
    st = _stopped_with_send_backs()
    queued = [dict(r) for r in st.metadata["rerun"]]
    r = _runner(tmp_path, st, spec)

    async def check(step, state):
        if where == "check":
            raise error

    async def execute(orders):
        raise error

    r._run_check_step = check
    r._execute_orders = execute
    r._researcher_edited_files = AsyncMock(return_value=set())
    with pytest.raises(type(error)):
        await r._settle_researcher_decisions(st)
    saved = PipelineState.load(tmp_path, PID, "single_pass")
    assert saved.metadata["rerun"] == queued  # nothing ran: both wait for the resume
    assert saved.metadata["sent_back"] == {"stage": "review_report", "specialists": ["reproduction_comparer"]}


async def test_a_send_back_that_ran_is_not_queued_again(tmp_path: Path, db):
    spec = _send_back_spec()
    st = _stopped_with_send_backs()
    r = _runner(tmp_path, st, spec)
    calls: list[str] = []

    async def execute(orders):
        calls.append(orders[0].focus)
        if len(calls) == 2:
            raise RuntimeError("the second one failed")
        return []

    r._run_check_step = _noop
    r._execute_orders = execute
    r._researcher_edited_files = AsyncMock(return_value=set())
    with pytest.raises(RuntimeError):
        await r._settle_researcher_decisions(st)
    saved = PipelineState.load(tmp_path, PID, "single_pass")
    assert saved.metadata["rerun"] == [{"target": "reproduction_comparer", "remark": "And name the versions."}]


async def test_a_send_back_runs_with_the_time_limit_of_its_step(tmp_path: Path, db):
    spec = _send_back_spec()
    st = _stopped_with_send_backs()
    st.metadata["rerun"] = st.metadata["rerun"][:1]
    r = _runner(tmp_path, st, spec)
    limits: list[object] = []

    async def execute(orders):
        limits.append(components.timeout_for("reproduction_comparer", spec))
        return []

    r._run_check_step = _noop
    r._execute_orders = execute
    r._researcher_edited_files = AsyncMock(return_value=set())
    r._recheck_after_send_back = _noop
    with pytest.raises(Exception):  # noqa: B017 - stops again at the researcher step
        await r._settle_researcher_decisions(st)
    assert limits == [(90 * 60, False)]  # before: None, the backend's own limit
    assert components._STEP.get() is None


# ── 17: completed only with the export, finishing only at the end ────────────


async def test_a_failed_final_export_pauses_with_the_reason_instead_of_completed(tmp_path: Path, monkeypatch, db):
    rows, events = db
    spec = spec_from_dict(
        {"name": "one", "steps": [{"kind": "specialists", "name": "work", "run": ["text_validator"]}]}
    )
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.last_status = "completed"  # what a finished template's state says
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st, spec)
    r._run_specialists_step = _noop
    r._run_compile_phase = r._export_audit_log_only = r._run_github_push_phase = _noop

    async def export():
        raise OSError(28, "No space left on device")

    r._run_export_phase = export
    out = await r.run()
    assert out["status"] == "paused" and out["reason"] == "export_failed"
    assert "completed" not in [s for s, _ in rows]
    status, error = rows[-1]
    assert status == "paused" and "final export failed" in (error or "") and "No space left" in error
    assert "export_failed" in events


async def test_finishing_is_shown_only_after_the_last_step(tmp_path: Path, monkeypatch, db):
    rows, _events = db
    spec = _paper_spec()
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["draft"]
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st, spec)
    seen: dict[str, str] = {}

    async def revision(status):
        await r._update_status(PaperStatus.COMPLETED)  # as _run_revision_phase does on an accept
        return PaperStatus.COMPLETED

    async def abstract():
        seen["abstract"] = rows[-1][0]

    async def specialists(s):
        seen[s.name] = rows[-1][0]

    async def finalize():
        seen["export"] = rows[-1][0]

    r._run_revision_phase = revision
    r._run_abstract_phase = abstract
    r._run_specialists_step = specialists
    r._best_effort_finalize = finalize
    out = await r.run()
    assert seen == {"abstract": "in_progress", "package": "in_progress", "export": "finishing"}
    assert out["status"] == "completed" and rows[-1] == ("completed", None)


# ── 20: one finalize for a circuit-breaker pause ─────────────────────────────


async def test_a_circuit_breaker_pause_finalizes_once(tmp_path: Path, monkeypatch, db):
    rows, _events = db
    spec = spec_from_dict({"name": "one", "steps": [{"kind": "specialists", "name": "work", "run": ["data_analyst"]}]})
    st = PipelineState(paper_id=PID, mode="single_pass")
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st, spec)
    finalized: list[str] = []

    async def step(s):
        raise CircuitBreakerError("data_analyst", 3, "the data source is down")

    async def finalize():
        finalized.append(rows[-1][0])

    r._run_specialists_step = step
    r._best_effort_finalize = finalize
    out = await r.run()
    assert out["reason"] == "circuit_breaker"
    assert finalized == ["paused"]  # once (it ran twice), after the pause is recorded


# ── 10: one runner per paper ─────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch, tmp_path: Path):
    """The app with a slow database read (so two requests interleave) and a run that waits."""
    from src.api import app as appmod

    started: list[str] = []
    release = asyncio.Event()

    async def run_pipeline(paper_id, *a, **k):
        started.append(paper_id)
        await release.wait()

    async def fetch_one(sql, params=None):
        await asyncio.sleep(0.01)  # the await between the check and the start
        return {"id": params["id"], "status": "paused", "workspace": str(tmp_path), "mode": "single_pass"}

    monkeypatch.setattr(appmod, "_run_pipeline", run_pipeline)
    monkeypatch.setattr("src.db.client.fetch_one", fetch_one)
    monkeypatch.setattr("src.db.client.execute", AsyncMock(return_value=None))
    monkeypatch.setattr(appmod, "_running_elsewhere", AsyncMock(return_value=None))
    monkeypatch.setattr("src.core.run_owner.claim", AsyncMock(return_value=None))
    monkeypatch.setattr("src.core.run_owner.release", AsyncMock(return_value=None))
    monkeypatch.setattr("src.core.run_owner.heartbeat_loop", AsyncMock(return_value=None))
    yield appmod, started, release
    release.set()


async def _post_together(appmod, posts: list[tuple[str, dict]]) -> list[httpx.Response]:
    from tests.conftest import TEST_SESSION_TOKEN

    transport = httpx.ASGITransport(app=appmod.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1", headers={"x-e2er-token": TEST_SESSION_TOKEN}
    ) as client:
        return list(await asyncio.gather(*(client.post(p, json=body) for p, body in posts)))


async def test_two_resumes_sent_together_start_one_runner(api):
    appmod, started, release = api
    pid = str(uuid.uuid4())
    try:
        responses = await _post_together(appmod, [(f"/api/papers/{pid}/resume", {})] * 2)
        await asyncio.sleep(0)
        assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
        assert started == [pid]
    finally:
        release.set()
        task = appmod._RUNNING.get(pid)
        if task is not None:
            await task
        appmod._RUNNING.pop(pid, None)


async def test_a_rerun_and_a_resume_sent_together_start_one_runner(api, monkeypatch):
    appmod, started, release = api
    pid = str(uuid.uuid4())

    async def rerun(req, paper_id):
        await asyncio.sleep(0.02)
        return {"resumed": await appmod.resume_paper(paper_id)}

    monkeypatch.setattr(appmod, "_rerun_paper", rerun)
    try:
        responses = await _post_together(
            appmod,
            [(f"/api/papers/{pid}/rerun", {"step": "compare", "remark": "again"}), (f"/api/papers/{pid}/resume", {})],
        )
        assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
        await asyncio.sleep(0)
        assert started == [pid]
    finally:
        release.set()
        task = appmod._RUNNING.get(pid)
        if task is not None:
            await task
        appmod._RUNNING.pop(pid, None)


async def test_a_finished_runs_callback_leaves_a_newer_run_registered(monkeypatch):
    from src.api import app as appmod

    monkeypatch.setattr("src.core.run_owner.claim", AsyncMock(return_value=None))
    released = AsyncMock(return_value=None)
    monkeypatch.setattr("src.core.run_owner.release", released)
    monkeypatch.setattr("src.core.run_owner.heartbeat_loop", AsyncMock(return_value=None))
    pid = str(uuid.uuid4())
    gate = asyncio.Event()

    async def old_run():
        await gate.wait()

    async def new_run():
        await asyncio.sleep(3600)

    old = asyncio.create_task(old_run())
    await appmod._track_run(pid, old)
    new = asyncio.create_task(new_run())
    appmod._RUNNING[pid] = new  # a later run of the paper, registered while the old one ends
    try:
        gate.set()
        await old
        await asyncio.sleep(0)
        assert appmod._RUNNING.get(pid) is new
        released.assert_not_awaited()
    finally:
        new.cancel()
        appmod._RUNNING.pop(pid, None)
