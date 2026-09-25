"""The researcher step and pre-registration (docs/researcher-step.md)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.core.pipeline import preregistration as prereg
from src.core.pipeline.researcher import (
    INSTRUCTIONS_FILE,
    ResearcherActionError,
    apply_action,
    instructions_block,
    pending_review,
)
from src.core.pipeline.spec import PipelineError, spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.specialists.contracts import Contribution, WorkOrder
from src.core.strategist.state import HumanReviewRequestedError

PID = "12345678-1234-1234-1234-123456789abc"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ── the template format ─────────────────────────────────────────────────────


def _spec(steps: list[dict[str, Any]]):
    return spec_from_dict({"name": "t", "steps": steps})


def test_researcher_and_preregister_steps_parse():
    s = _spec(
        [
            {
                "kind": "researcher",
                "name": "review_design",
                "after": ["identification_strategist"],
                "files": ["paper_plan.md"],
            },
            {"kind": "preregister", "name": "preregister", "after": ["identification_strategist"]},
            {"kind": "strategist", "name": "initial"},
            {"kind": "researcher", "name": "review_draft", "files": ["paper_draft.tex"]},
        ]
    )
    assert s.step("review_design").files == ("paper_plan.md",)
    # `after` steps happen inside the strategist's dispatch, not in the sequence.
    assert s.sequence_for("single_pass") == ["initial", "review_draft"]


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "researcher", "name": "r", "run": ["x"]},
        {"kind": "researcher", "name": "r", "files": ["../secret"]},
        {"kind": "strategist", "name": "s", "files": ["a.md"]},
    ],
)
def test_bad_researcher_steps_are_refused(bad):
    with pytest.raises(PipelineError):
        _spec([bad])


def test_the_preregistered_template_loads():
    from src.core.pipeline.spec import find_spec

    s = find_spec("empirical-preregistered")
    kinds = [(x.kind, x.name) for x in s.steps]
    assert ("researcher", "review_design") in kinds and ("preregister", "preregister") in kinds
    assert s.sequence_for("single_pass")[:3] == ["initial", "estimation_gate", "review_draft"]


# ── researcher actions ──────────────────────────────────────────────────────


def _paused(tmp_path: Path, stage: str = "review_design", files=("paper_plan.md",)) -> PipelineState:
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.pending_review_stage = stage
    st.metadata["review"] = {"kind": "researcher", "files": list(files)}
    (tmp_path / "paper_plan.md").write_text("plan v1\n")
    return st


def test_edit_is_saved_with_fingerprints_before_and_after(tmp_path: Path):
    st = _paused(tmp_path)
    ev = apply_action(tmp_path, st, {"action": "edit", "file": "paper_plan.md", "content": "plan v2\n"})
    assert (tmp_path / "paper_plan.md").read_text() == "plan v2\n"
    assert ev["sha256_before"] == _sha(b"plan v1\n") and ev["sha256_after"] == _sha(b"plan v2\n")
    with pytest.raises(ResearcherActionError):
        apply_action(tmp_path, st, {"action": "edit", "file": "other.md", "content": "x"})  # not a step file
    with pytest.raises(ResearcherActionError):
        apply_action(tmp_path, st, {"action": "edit", "file": "paper_plan.md", "content": "plan v2\n"})  # unchanged


def test_instruction_is_kept_for_every_following_specialist(tmp_path: Path):
    st = _paused(tmp_path)
    assert instructions_block(tmp_path) == ""
    ev = apply_action(tmp_path, st, {"action": "instruction", "text": "Use monthly data."})
    assert ev["text"] == "Use monthly data."
    block = instructions_block(tmp_path)
    assert block.startswith("## Instructions from the researcher") and "Use monthly data." in block


def test_approve_and_send_back(tmp_path: Path):
    st = _paused(tmp_path)
    ev = apply_action(
        tmp_path,
        st,
        {"action": "send_back", "step": "identification_strategist", "remark": "Add an IV."},
        sendable=["identification_strategist"],
    )
    assert ev["target"] == "identification_strategist"
    assert st.metadata["rerun"] == [{"target": "identification_strategist", "remark": "Add an IV."}]
    assert st.metadata["sent_back"] is True and st.pending_review_stage == "review_design"
    with pytest.raises(ResearcherActionError):
        apply_action(
            tmp_path, st, {"action": "send_back", "step": "nope", "remark": "x"}, sendable=["identification_strategist"]
        )
    apply_action(tmp_path, st, {"action": "approve"})
    assert st.is_approved("review_design") and st.pending_review_stage is None and "sent_back" not in st.metadata
    with pytest.raises(ResearcherActionError):
        apply_action(tmp_path, st, {"action": "approve"})  # nothing pending any more


def test_review_at_pause_offers_the_workspace_text_files(tmp_path: Path):
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.pending_review_stage = "initial"
    (tmp_path / "paper_draft.tex").write_text("x")
    (tmp_path / ".hidden.md").write_text("x")
    p = pending_review(tmp_path, st)
    assert p is not None and p.kind == "review_at" and p.files == ("paper_draft.tex",)


# ── the runner ──────────────────────────────────────────────────────────────


def _runner(tmp_path: Path, steps: list[dict[str, Any]]):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id = PID
    r._workspace = tmp_path
    r._mode = "single_pass"
    r._spec = _spec(steps)
    r._triggers = [s for s in r._spec.steps if s.kind in ("researcher", "preregister") and s.after]
    r._state = PipelineState(paper_id=PID, mode="single_pass")
    r._in_initial = False
    r._contributions = []
    return r


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


async def test_the_run_stops_at_a_researcher_step(tmp_path: Path, events):
    from src.core.strategist.runner import PaperStatus

    r = _runner(tmp_path, [{"kind": "researcher", "name": "review_draft", "files": ["paper_draft.tex"]}])
    step, state = r._spec.steps[0], r._state
    with pytest.raises(HumanReviewRequestedError):
        await r._run_spec_step(step, None, state, 0, PaperStatus.IN_PROGRESS)
    assert state.pending_review_stage == "review_draft" and state.metadata["review"]["files"] == ["paper_draft.tex"]
    state.approve("review_draft")
    await r._run_spec_step(step, None, state, 0, PaperStatus.IN_PROGRESS)
    assert state.is_complete("review_draft")


async def test_a_step_inside_the_dispatch_stops_after_its_specialists(tmp_path: Path, events):
    r = _runner(tmp_path, [{"kind": "researcher", "name": "review_design", "after": ["identification_strategist"]}])
    r._in_initial = True
    orders = [
        WorkOrder(paper_id=PID, specialist="identification_strategist", focus="x", parallel_group=0),
        WorkOrder(paper_id=PID, specialist="econometrics_specialist", focus="y", parallel_group=0),
        WorkOrder(paper_id=PID, specialist="paper_drafter", focus="z", parallel_group=1),
    ]
    shifted = r._order_for_researcher_steps(orders)
    groups = {o.specialist: o.parallel_group for o in shifted}
    # Nothing else — estimation above all — runs in the same group as the design.
    assert groups["identification_strategist"] < groups["econometrics_specialist"] < groups["paper_drafter"]
    with pytest.raises(HumanReviewRequestedError):
        await r._between_groups({"identification_strategist"}, shifted[1:])
    assert [o["specialist"] for o in r._state.metadata["pending_orders"]] == [
        "econometrics_specialist",
        "paper_drafter",
    ]


async def test_resume_continues_with_the_saved_orders_and_stops_at_the_preregistration(
    tmp_path: Path, events, monkeypatch
):
    steps = [
        {"kind": "researcher", "name": "review_design", "after": ["identification_strategist"]},
        {"kind": "preregister", "name": "preregister", "after": ["identification_strategist"]},
    ]
    r = _runner(tmp_path, steps)
    (tmp_path / "paper_plan.md").write_text("# Plan\nH1: ETFs change co-movement.\n")
    (tmp_path / "identification_spec.json").write_text('{"design": "did"}')
    st = r._state
    st.metadata["done_specialists"] = ["identification_strategist"]
    st.metadata["pending_orders"] = [
        WorkOrder(paper_id=PID, specialist="econometrics_specialist", focus="y").model_dump()
    ]
    st.approve("review_design")
    ran: list[str] = []

    async def _exec(orders):
        ran.extend(o.specialist for o in orders)
        return []

    monkeypatch.setattr(r, "_execute_orders", _exec)
    r._in_initial = True
    with pytest.raises(HumanReviewRequestedError) as hr:
        await r._initial_phase_body()
    assert hr.value.stage == "preregister" and ran == []  # nothing ran before the pre-registration
    assert (tmp_path / "preregistration.md").is_file() and "H1: ETFs" in (tmp_path / "preregistration.md").read_text()
    st.approve("preregister")
    await r._settle_researcher_decisions(st)  # the resumed run freezes it
    lock = json.loads((tmp_path / prereg.LOCK_FILE).read_text())
    assert lock["sha256"] == _sha((tmp_path / "preregistration.md").read_bytes())
    assert any(k == "preregistration" for k, _s, _p in events)
    await r._initial_phase_body()
    assert ran == ["econometrics_specialist"]


async def test_send_back_reruns_the_specialist_and_stops_again(tmp_path: Path, events, monkeypatch):
    r = _runner(tmp_path, [{"kind": "researcher", "name": "review_design", "after": ["identification_strategist"]}])
    st = r._state
    st.pending_review_stage = "review_design"
    st.metadata.update(rerun=[{"target": "identification_strategist", "remark": "Add an IV."}], sent_back=True)
    ran: list[WorkOrder] = []

    async def _exec(orders):
        ran.extend(orders)
        return [Contribution(paper_id=PID, specialist=o.specialist, output="") for o in orders]

    monkeypatch.setattr(r, "_execute_orders", _exec)
    with pytest.raises(HumanReviewRequestedError) as hr:
        await r._settle_researcher_decisions(st)
    assert hr.value.stage == "review_design"
    assert ran[0].specialist == "identification_strategist" and "Add an IV." in ran[0].focus
    assert (
        "rerun" not in st.metadata
        and ("researcher_rerun", "identification_strategist", {"remark": "Add an IV."}) in events
    )


async def test_the_strategist_receives_the_instructions(tmp_path: Path):
    from src.core.strategist.engine import StrategistEngine
    from src.modules.llm.base import ToolLoopResult

    (tmp_path / INSTRUCTIONS_FILE).write_text("(at step review_design) Use monthly data.\n")
    seen: list[str] = []

    class _Backend:
        async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
            seen.append(messages[0]["content"])
            return ToolLoopResult(success=True, output='{"action": "wait", "rationale": "x", "work_orders": []}')

    eng = StrategistEngine(_Backend(), tmp_path, PID, "single_pass", model="m")
    await eng.decide("designing")
    assert "Instructions from the researcher" in seen[0] and "Use monthly data." in seen[0]


# ── pre-registration ────────────────────────────────────────────────────────


def _design(ws: Path) -> None:
    (ws / "paper_plan.md").write_text("# Plan\nQuestion and hypotheses.\n")
    (ws / "identification_strategy.md").write_text("DiD around the approval.\n")
    (ws / "identification_spec.json").write_text('{"design": "did", "treatment": "etf"}')
    (ws / "econometric_spec.md").write_text("Fisher-z, coin and month fixed effects.\n")


def test_preregistration_is_assembled_frozen_and_compared(tmp_path: Path):
    _design(tmp_path)
    prereg.assemble(tmp_path)
    text = (tmp_path / prereg.PREREG_FILE).read_text()
    assert "## Research question and hypotheses" in text and '"design": "did"' in text
    lock = prereg.freeze(tmp_path)
    assert set(lock["plan_files"]) == {"identification_spec.json", "econometric_spec.md"}
    assert prereg.deviations(tmp_path, lock) == []
    (tmp_path / "identification_spec.json").write_text('{"design": "rdd"}')
    assert prereg.deviations(tmp_path, lock) == ["identification_spec.json changed after the pre-registration"]


def _bundle_with_prereg(tmp_path: Path) -> Path:
    b = tmp_path / "bundle"
    (b / "design").mkdir(parents=True)
    _design(b / "design")
    prereg.assemble(b / "design")
    prereg.freeze(b / "design")
    return b


def test_verify_reports_the_preregistration(tmp_path: Path):
    from src.cli_verify import _check_preregistration

    b = _bundle_with_prereg(tmp_path)
    c = _check_preregistration(b)
    assert c is not None and c.status == "PASS" and "follows the pre-registered plan" in c.detail
    (b / "design" / "econometric_spec.md").write_text("Something else.\n")
    c = _check_preregistration(b)
    assert c.status == "FAIL" and "econometric_spec.md changed" in c.detail
    assert _check_preregistration(tmp_path) is None  # no pre-registration: no extra check


def test_export_includes_the_preregistration_and_instructions(tmp_path: Path):
    from src.core.export.structured import EXPORT_MAP

    design = [p for p, _ in EXPORT_MAP["design"]]
    for f in ("preregistration.md", "preregistration.lock.json", INSTRUCTIONS_FILE):
        assert f in design


def test_zenodo_deposit_uses_the_researchers_token(tmp_path: Path):
    _design(tmp_path)
    prereg.assemble(tmp_path)
    prereg.freeze(tmp_path)
    calls: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        assert req.headers["authorization"] == "Bearer tok"
        if req.method == "POST" and req.url.path == "/api/deposit/depositions":
            return httpx.Response(201, json={"id": 7, "links": {"bucket": "https://sandbox.zenodo.org/api/files/b1"}})
        if req.url.path.endswith("/actions/publish"):
            return httpx.Response(
                202, json={"doi": "10.5072/zenodo.7", "links": {"record_html": "https://sandbox.zenodo.org/records/7"}}
            )
        return httpx.Response(200, json={})

    client = httpx.Client(base_url=prereg.ZENODO_SANDBOX_URL, transport=httpx.MockTransport(handler))
    dep = prereg.deposit_zenodo(tmp_path, "tok", base_url=prereg.ZENODO_SANDBOX_URL, client=client)
    assert dep["doi"] == "10.5072/zenodo.7"
    assert ("PUT", "/api/files/b1/preregistration.md") in calls
    assert json.loads((tmp_path / prereg.LOCK_FILE).read_text())["deposit"]["doi"] == "10.5072/zenodo.7"


# ── the dossier ─────────────────────────────────────────────────────────────


def _events_db(tmp_path: Path, rows: list[tuple[str, str | None, str | None, dict]]) -> Path:
    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT);"
        "CREATE TABLE contributions (id TEXT, paper_id TEXT, specialist TEXT, stage TEXT, output_file TEXT,"
        " success INT, error_msg TEXT, usage_tokens INT, cost_usd REAL, duration_sec REAL, created_at TEXT);"
        "CREATE TABLE llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT, cost_usd REAL,"
        " created_at TEXT);"
    )
    for i, (etype, stage, sp, payload) in enumerate(rows):
        con.execute(
            "INSERT INTO pipeline_events VALUES (?,?,?,?,?,?,?)",
            (str(i), PID, etype, stage, sp, json.dumps(payload), f"2026-09-25 10:{i:02d}:00"),
        )
    con.commit()
    con.close()
    return db


def test_the_dossier_lists_the_researchers_steps_in_order(tmp_path: Path):
    from src.core.dossier import recorded_workflow

    db = _events_db(
        tmp_path,
        [
            ("phase_start", "initial", None, {}),
            (
                "researcher_action",
                "review_design",
                None,
                {
                    "action": "edit",
                    "step": "review_design",
                    "file": "paper_plan.md",
                    "sha256_before": "a",
                    "sha256_after": "b",
                },
            ),
            (
                "researcher_action",
                "review_design",
                None,
                {"action": "instruction", "step": "review_design", "text": "Use monthly data."},
            ),
            ("researcher_action", "review_design", None, {"action": "approve", "step": "review_design"}),
            ("preregistration", "preregister", None, {"sha256": "c" * 64}),
        ],
    )
    steps = recorded_workflow(db, PID, None)
    assert [(s["type"], s["action"]) for s in steps] == [
        ("researcher", "edit"),
        ("researcher", "instruction"),
        ("researcher", "approve"),
        ("researcher", "preregistration_frozen"),
    ]
    assert (
        steps[0]["sha256_after"] == "b" and steps[1]["text"] == "Use monthly data." and steps[0]["phase"] == "initial"
    )


def test_dossier_format_rises_only_with_researcher_steps(tmp_path: Path, monkeypatch):
    from src.core import dossier as d

    manifest = {
        "title": "T",
        "ai": {"backend": None, "usage": []},
        "process": {},
        "dependencies": {"uses": []},
        "data": [],
    }
    monkeypatch.setattr(d, "_e2er_commit", lambda: None)
    assert d.build_dossier(manifest)["schema"] == "e2er-dossier/0.3"  # unchanged documents keep their address
    b = _bundle_with_prereg(tmp_path)
    doc = d.build_dossier(manifest, bundle=b)
    assert doc["schema"] == "e2er-dossier/0.4"
    assert doc["preregistration"]["file"] == "design/preregistration.md" and doc["preregistration"]["frozen_at"]


# ── the review endpoints ────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from src.api.app import app

    with patch("src.config.get_settings") as s:
        s.return_value.workspace_root = str(tmp_path / "workspaces")
        yield TestClient(app)


def test_review_endpoints_apply_actions_and_resume(client, tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    st = _paused(ws)
    st.save(ws)
    row = {"id": PID, "workspace": str(ws), "mode": "single_pass", "pipeline": "empirical", "status": "paused"}
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row),
        patch("src.db.events.fetch_events", new_callable=AsyncMock, return_value=[]),
        patch("src.db.events.log_event", new_callable=AsyncMock) as logged,
        patch("src.api.app.resume_paper", new_callable=AsyncMock, return_value={"status": "in_progress"}) as resumed,
    ):
        got = client.get(f"/api/papers/{PID}/review").json()
        assert (
            got["pending"] == {"stage": "review_design", "kind": "researcher"}
            and got["files"][0]["content"] == "plan v1\n"
        )
        r = client.post(f"/api/papers/{PID}/review", json={"action": "instruction", "text": "Use monthly data."})
        assert r.status_code == 200 and not resumed.called
        r = client.post(f"/api/papers/{PID}/review", json={"action": "edit", "file": "nope.md", "content": "x"})
        assert r.status_code == 400
        r = client.post(f"/api/papers/{PID}/review", json={"action": "approve"})
        assert r.status_code == 200 and resumed.called
    kinds = [c.args[1] for c in logged.call_args_list]
    assert kinds == ["researcher_action", "researcher_action"]
    assert PipelineState.load(ws, PID, "single_pass").is_approved("review_design")
