"""`e2er rerun`: send a finished study back to one of its steps.

The replication demonstration (08af321d) completed with a written report that
contradicted its JSON; only its report step had to be redone. A send-back needs
a pending researcher step, and resume refuses a completed study, so e2er had no
way to do that. ``apply_rerun`` withdraws the approvals from the step on,
records the researcher's remark, and the runner reruns the steps and stops at
the next researcher step.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.researcher import INSTRUCTIONS_FILE, ResearcherActionError, apply_rerun
from src.core.pipeline.spec import find_spec, spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.strategist.state import PaperStatus

PID = "08af321d-1a9c-47fe-93ac-b1629bbd9afc"
REMARK = "Write the report again from the comparison, with the counts and versions of reproduction_report.json."


def _completed_replication() -> PipelineState:
    """The state file of the finished replication demonstration."""
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = [
        "fetch",
        "plan",
        "review_plan",
        "sandbox_run",
        "compare",
        "reproduction_gate",
        "review_report",
    ]
    st.approved_stages = ["review_plan", "reproduction_gate", "review_report"]
    st.last_status = "completed"
    st.metadata = {"review": {"kind": "researcher", "files": ["reproduction_report.md"]}}
    return st


def test_a_rerun_withdraws_the_approvals_from_the_step_on_and_records_the_remark(tmp_path: Path):
    st = _completed_replication()
    (tmp_path / INSTRUCTIONS_FILE).write_text("(at step review_plan) Use the package date.\n")
    payload = apply_rerun(tmp_path, st, find_spec("replication"), "compare", REMARK)
    assert payload["action"] == "rerun" and payload["step"] == "compare" and payload["remark"] == REMARK
    assert payload["reruns"] == ["compare", "reproduction_gate", "review_report"]
    assert st.approved_stages == ["review_plan"]  # the plan the researcher approved stands
    assert st.metadata["rerun"] == [{"target": "compare", "remark": REMARK}]
    assert st.last_status == "in_progress" and "review" not in st.metadata
    text = (tmp_path / INSTRUCTIONS_FILE).read_text()
    assert text.startswith("(at step review_plan)") and "(for compare, rerun of the study, " in text
    assert text.rstrip().endswith(REMARK)


@pytest.mark.parametrize(
    ("step", "why"),
    [
        ("nope", "is not a step of the template replication"),
        ("review_report", "is a researcher step"),
        ("", "needs the step"),
    ],
)
def test_a_rerun_is_refused_for_a_step_it_cannot_start_from(tmp_path: Path, step: str, why: str):
    with pytest.raises(ResearcherActionError, match=why):
        apply_rerun(tmp_path, _completed_replication(), find_spec("replication"), step, REMARK)


def test_a_rerun_needs_a_remark(tmp_path: Path):
    with pytest.raises(ResearcherActionError, match="a remark"):
        apply_rerun(tmp_path, _completed_replication(), find_spec("replication"), "compare", "  ")


def _failed_at_compare() -> PipelineState:
    """The replication run failed in its compare step: plan approved, compare not done."""
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["fetch", "plan", "review_plan", "sandbox_run"]
    st.approved_stages = ["review_plan"]
    st.last_status = "failed"
    return st


def test_a_failed_study_reruns_from_the_step_that_failed(tmp_path: Path):
    st = _failed_at_compare()
    payload = apply_rerun(tmp_path, st, find_spec("replication"), "compare", REMARK)
    assert payload["reruns"] == ["compare", "reproduction_gate", "review_report"]
    assert "replaces" not in payload
    assert st.metadata["rerun"] == [{"target": "compare", "remark": REMARK}] and st.last_status == "in_progress"
    assert st.approved_stages == ["review_plan"]


def test_a_rerun_from_a_step_after_the_failure_runs_from_the_first_unfinished_step(tmp_path: Path):
    st = _failed_at_compare()
    payload = apply_rerun(tmp_path, st, find_spec("replication"), "reproduction_gate", REMARK)
    assert payload["step"] == "reproduction_gate"
    assert payload["reruns"] == ["compare", "reproduction_gate", "review_report"]


def test_an_earlier_step_of_a_failed_study_runs_again_with_everything_after_it(tmp_path: Path):
    st = _failed_at_compare()
    payload = apply_rerun(tmp_path, st, find_spec("replication"), "plan", REMARK)
    assert payload["reruns"][:3] == ["plan", "review_plan", "sandbox_run"]
    assert st.approved_stages == []  # the plan review comes again


def test_at_a_researcher_step_the_rerun_takes_the_place_of_the_stop(tmp_path: Path):
    st = _completed_replication()
    st.completed_stages.remove("review_report")
    st.approved_stages.remove("review_report")
    st.pending_review_stage = "review_report"
    payload = apply_rerun(tmp_path, st, find_spec("replication"), "compare", REMARK)
    assert payload["replaces"] == "review_report"
    assert st.pending_review_stage is None and "review" not in st.metadata


def test_a_rerun_at_a_contract_stop_runs_every_specialist_of_the_step_again(tmp_path: Path):
    st = _failed_at_compare()
    st.last_status = "paused"
    st.pending_review_stage = "output_contract"
    st.metadata = {
        "review": {"kind": "contract", "files": ["reproduction_report.md"]},
        "contract_pause": {"phase": "compare", "failed": [{"specialist": "reproduction_comparer"}]},
        "step_done": {"compare": ["helper"]},
    }
    payload = apply_rerun(tmp_path, st, find_spec("replication"), "compare", REMARK)
    assert payload["replaces"] == "output_contract"
    assert st.pending_review_stage is None
    assert "contract_pause" not in st.metadata and "review" not in st.metadata
    assert "compare" not in st.metadata["step_done"]


# ── the runner reruns the steps and stops at the researcher step ──────────────


def _spec():
    return spec_from_dict(
        {
            "name": "compare-then-review",
            "steps": [
                {"kind": "specialists", "name": "plan", "run": ["replication_planner"]},
                {"kind": "specialists", "name": "compare", "run": ["reproduction_comparer"]},
                {"kind": "researcher", "name": "review_report", "files": ["reproduction_report.md"]},
            ],
        }
    )


@pytest.mark.parametrize("before", ["completed", "failed"])
async def test_the_runner_reruns_from_the_step_and_stops_at_the_researcher_step(tmp_path: Path, monkeypatch, before):
    from src.core.strategist.runner import PipelineRunner

    st = PipelineState(paper_id=PID, mode="single_pass")
    if before == "completed":
        st.completed_stages = ["plan", "compare", "review_report"]
        st.approved_stages = ["review_report"]
    else:  # failed in compare: the step never finished
        st.completed_stages = ["plan"]
    st.last_status = before
    spec = _spec()
    apply_rerun(tmp_path, st, spec, "compare", REMARK)

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id, r._workspace, r._mode, r._spec = PID, tmp_path, "single_pass", spec
    r._triggers, r._state, r._in_initial, r._contributions = [], st, False, []
    r._governance, r._failure_counts, r._last_specialist_errors = "full", {}, {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers, r._review_stages = [], [], set()
    r._max_cost_usd, r._pivot_count, r._iteration, r._deep_revision_count = 5.0, 0, 0, 0
    r._in_memory_spent = lambda: 0.0
    statuses: list[PaperStatus] = []
    events: list[tuple[str, str | None, dict]] = []
    ran: list[str] = []

    async def _status(status, error=None):
        statuses.append(status)

    async def _log(paper_id, kind, *, stage=None, payload=None, **kw):
        events.append((kind, stage, payload or {}))

    async def _step(step):
        ran.append(step.name)

    async def _noop(*a, **k):
        return None

    r._update_status = _status
    r._best_effort_finalize = _noop
    r._run_specialists_step = _step
    monkeypatch.setattr("src.db.events.log_event", _log)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget", _noop)
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.load", classmethod(lambda cls, *a: st))

    out = await r.run()
    assert ran == ["compare"]  # plan is not redone
    assert out["status"] == "paused" and out["stage"] == "review_report"
    assert ("researcher_rerun", "compare", {"remark": REMARK}) in events
    assert PaperStatus.COMPLETED not in statuses
    assert st.pending_review_stage == "review_report" and not st.is_approved("review_report")


# ── the endpoint and the command ──────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from src.api.app import app

    with patch("src.config.get_settings") as s:
        s.return_value.workspace_root = str(tmp_path / "workspaces")
        yield TestClient(app)


def test_the_rerun_endpoint_records_the_action_and_resumes(client, tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _completed_replication().save(ws)
    row = {"id": PID, "workspace": str(ws), "mode": "single_pass", "pipeline": "replication", "status": "completed"}
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row),
        patch("src.db.client.execute", new_callable=AsyncMock) as executed,
        patch("src.db.events.log_event", new_callable=AsyncMock) as logged,
        patch("src.api.app._running_elsewhere", new_callable=AsyncMock, return_value=None),
        patch("src.api.app.resume_paper", new_callable=AsyncMock, return_value={"status": "resuming"}) as resumed,
    ):
        r = client.post(f"/api/papers/{PID}/rerun", json={"step": "compare", "remark": REMARK})
        assert r.status_code == 200, r.text
        assert r.json()["recorded"]["remark"] == REMARK and resumed.called
        bad = client.post(f"/api/papers/{PID}/rerun", json={"step": "review_report", "remark": REMARK})
        assert bad.status_code == 400 and "researcher step" in bad.json()["detail"]
    kind, payload = logged.call_args_list[0].args[1], logged.call_args_list[0].kwargs["payload"]
    assert kind == "researcher_action" and payload["action"] == "rerun" and payload["step"] == "compare"
    assert any("status = 'paused'" in c.args[0] for c in executed.call_args_list)
    saved = PipelineState.load(ws, PID, "single_pass")
    assert saved.metadata["rerun"][0]["target"] == "compare" and saved.approved_stages == ["review_plan"]


def test_the_rerun_endpoint_takes_a_failed_study(client, tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _failed_at_compare().save(ws)
    row = {"id": PID, "workspace": str(ws), "mode": "single_pass", "pipeline": "replication", "status": "failed"}
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.events.log_event", new_callable=AsyncMock) as logged,
        patch("src.api.app._running_elsewhere", new_callable=AsyncMock, return_value=None),
        patch("src.api.app.resume_paper", new_callable=AsyncMock, return_value={"status": "resuming"}) as resumed,
    ):
        r = client.post(f"/api/papers/{PID}/rerun", json={"step": "compare", "remark": REMARK})
    assert r.status_code == 200, r.text
    assert resumed.called and logged.call_args_list[0].kwargs["payload"]["action"] == "rerun"


def test_the_dossier_lists_the_rerun_as_the_researchers_step():
    from src.core.dossier import researcher_step

    step = researcher_step(
        {"action": "rerun", "step": "compare", "target": "compare", "remark": REMARK, "at": "2026-09-30T18:00:00Z"},
        "2026-09-30T18:00:00Z",
    )
    assert step == {
        "type": "researcher",
        "action": "rerun",
        "phase": None,
        "step": "compare",
        "at": "2026-09-30T18:00:00Z",
        "target": "compare",
        "remark": REMARK,
    }


def test_e2er_rerun_posts_the_step_and_remark(monkeypatch, capsys):
    from src import cli_review

    sent = {}

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"recorded": {"step": "compare", "reruns": ["compare", "reproduction_gate", "review_report"]}}

    class _Http:
        def post(self, url, json):
            sent.update(url=url, body=json)
            return _Resp()

    monkeypatch.setattr(cli_review, "_client", lambda: _Http())
    assert cli_review.rerun(PID, step="compare", remark=REMARK) == 0
    assert sent == {"url": f"/api/papers/{PID}/rerun", "body": {"step": "compare", "remark": REMARK}}
    assert "rerun from compare: compare, reproduction_gate, review_report" in capsys.readouterr().out


def test_an_approved_deviation_fits_the_dossier_format():
    """e2er.org refused a dossier whose researcher step listed the approved deviations as objects."""
    from src.core.dossier import researcher_step

    rec = {
        "file": "identification_spec.json",
        "sha256_frozen": "a" * 64,
        "sha256_approved": "b" * 64,
        "deviation": "identification_spec.json changed since the freeze",
        "approved_at": "2026-10-04T10:00:00Z",
    }
    step = researcher_step(
        {"action": "approve", "step": "estimation_gate", "decision": "deviation_approved", "deviations": [rec]},
        "2026-10-04T10:00:00Z",
    )
    assert step["deviations"] == ["identification_spec.json changed since the freeze"]
    assert step["approved_deviations"] == [rec]


def test_a_step_that_runs_at_every_start_is_not_where_a_rerun_picks_up(tmp_path: Path):
    """The estimation check (resumable = false) is never marked done; a failed review is where the run stopped."""
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["initial"]
    st.last_status = "failed"
    payload = apply_rerun(tmp_path, st, find_spec("empirical"), "review", REMARK)
    assert payload["reruns"] == ["review", "revision", "replication"]
