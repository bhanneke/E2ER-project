"""The dossier says what the run recorded (2026-10-01 review, findings 18–23 and 26).

The dossier listed the final file's hash as every step's output, pinned every
part to the first commit of a run that spanned several, filled unresolved
pins with today's files, listed the specialists and skills of today's
checkout, leaked local paths, counted the runner's reruns as researcher
actions (and the real rerun twice), dropped the run's outcome, halts and
failures, mixed timestamp formats, dropped fields of the researcher's
actions and matched models to steps by order. Each test pins one of these.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.core import dossier as d
from src.core.dossier import build_dossier, read_run, researcher_step

PID = "9a623c39-87df-4f46-9d6f-d9dcabc84e7a"
C1, C2 = "1" * 40, "2" * 40


def _db(tmp_path: Path, events: list[tuple], contribs: list[tuple] = (), calls: list[tuple] = (), status="completed"):
    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE papers (id TEXT, status TEXT, last_error TEXT, updated_at TEXT, mode TEXT, governance TEXT);"
        "CREATE TABLE pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT);"
        "CREATE TABLE contributions (id TEXT, paper_id TEXT, specialist TEXT, stage TEXT, output_file TEXT,"
        " success INT, error_msg TEXT, usage_tokens INT, cost_usd REAL, duration_sec REAL, created_at TEXT);"
        "CREATE TABLE llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT,"
        " cost_usd REAL, created_at TEXT);"
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?, 'single_pass', 'full')",
        (PID, status, "halted" if status != "completed" else None, "2026-09-29 15:59:32"),
    )
    for i, (etype, stage, sp, payload, at) in enumerate(events):
        con.execute(
            "INSERT INTO pipeline_events VALUES (?,?,?,?,?,?,?)",
            (str(i), PID, etype, stage, sp, json.dumps(payload), at),
        )
    for i, (sp, out, ok, err, at) in enumerate(contribs):
        con.execute(
            "INSERT INTO contributions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(i), PID, sp, None, out, ok, err, 0, 0.0, 1.0, at),
        )
    for i, (sp, backend, model, at) in enumerate(calls):
        con.execute(
            "INSERT INTO llm_usage VALUES (?,?,?,?,?,1,1,0,0,0,?)",
            (str(i), PID, sp, backend, model, at),
        )
    con.commit()
    con.close()
    return db


def _identity(commit: str, version: str = "0.10.0") -> dict[str, Any]:
    return {"git_sha": commit, "git_dirty": False, "package_version": version, "source_root": "/Users/x/e2er"}


# ── 18: what each step wrote ─────────────────────────────────────────────────


def test_each_step_records_the_hash_of_what_it_wrote(tmp_path: Path):
    db = _db(
        tmp_path,
        [
            ("specialist_start", None, "paper_drafter", {"outputs": ["paper_draft.tex"]}, "2026-09-29 13:00:00"),
            (
                "specialist_end",
                None,
                "paper_drafter",
                {"success": True, "outputs": [{"file": "paper_draft.tex", "sha256": "a" * 64, "changed": True}]},
                "2026-09-29 13:04:00",
            ),
            ("specialist_start", None, "paper_drafter", {}, "2026-09-29 13:30:00"),
            (
                "specialist_end",
                None,
                "paper_drafter",
                {"success": True, "outputs": [{"file": "paper_draft.tex", "sha256": "b" * 64, "changed": True}]},
                "2026-09-29 13:41:00",
            ),
        ],
    )
    files = {"paper/paper.tex": {"sha256": "c" * 64, "bytes": 1}}
    first, second = read_run(db, PID, files).workflow
    assert first["output"] == {"file": "paper/paper.tex", "sha256": "a" * 64}
    assert second["output"] == {"file": "paper/paper.tex", "sha256": "b" * 64}


def test_an_older_run_gives_the_export_hash_only_to_the_last_writer_and_says_so(tmp_path: Path):
    ws = f"/Users/hanneke/e2er-studies/x/workspaces/{PID}/"
    db = _db(
        tmp_path,
        [
            ("specialist_start", None, "idea_developer", {}, "2026-09-28 14:57:00"),
            ("specialist_end", None, "idea_developer", {"success": True}, "2026-09-28 14:58:46"),
            ("specialist_start", None, "idea_developer", {}, "2026-09-28 23:05:00"),
            ("specialist_end", None, "idea_developer", {"success": True}, "2026-09-28 23:06:16"),
        ],
        contribs=[
            ("idea_developer", ws + "paper_plan.md", 1, None, "2026-09-28 14:58:46"),
            ("idea_developer", ws + "paper_plan.md", 1, None, "2026-09-28 23:06:16"),
        ],
    )
    files = {"design/paper_plan.md": {"sha256": "e" * 64, "bytes": 1}}
    first, last = read_run(db, PID, files).workflow
    assert first["output"] == {"file": "design/paper_plan.md", "recorded": False, "exported": True, "superseded": True}
    assert last["output"]["sha256_at_export"] == "e" * 64 and last["output"]["recorded"] is False
    assert "sha256" not in first["output"] and "sha256" not in last["output"]


async def test_the_runner_records_the_skills_and_what_each_step_wrote(tmp_path: Path, monkeypatch):
    import hashlib

    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import Contribution, WorkOrder

    logged: list[tuple[str, dict]] = []

    async def log_event(paper_id, event_type, *, stage=None, specialist=None, payload=None):
        logged.append((event_type, payload or {}))

    async def run_specialist(work_order, workspace, **kw):
        (workspace / "paper_plan.md").write_text("the plan v2")
        return Contribution(paper_id=PID, specialist=work_order.specialist, output="", success=True)

    monkeypatch.setattr("src.db.events.log_event", log_event)
    monkeypatch.setattr(dispatcher, "run_specialist", run_specialist)
    (tmp_path / "paper_plan.md").write_text("the plan v1")
    order = WorkOrder(paper_id=PID, specialist="idea_developer", focus="x", context="c")
    await dispatcher.execute_work_order(order, backend=None, workspace=tmp_path, model="m")  # type: ignore[arg-type]
    (start, sp), (end, ep) = logged
    assert start == "specialist_start" and "base/researcher" in sp["skills"]
    assert end == "specialist_end"
    [out] = [o for o in ep["outputs"] if o["file"] == "paper_plan.md"]
    assert out == {"file": "paper_plan.md", "sha256": hashlib.sha256(b"the plan v2").hexdigest(), "changed": True}


# ── 19: segments and pins per commit ─────────────────────────────────────────


def _two_commit_run(tmp_path: Path) -> Path:
    return _db(
        tmp_path,
        [
            ("run_identity", None, None, _identity(C1), "2026-09-28 14:56:39"),
            (
                "template_components",
                None,
                None,
                {
                    "template": "event-study-finance",
                    "skills": {"identification_strategist": ["econometrics/event-study"]},
                },
                "2026-09-28 14:56:39",
            ),
            ("specialist_start", None, "identification_strategist", {}, "2026-09-28 14:57:12"),
            ("specialist_end", None, "identification_strategist", {"success": True}, "2026-09-28 14:59:47"),
            ("run_identity", None, None, _identity(C2, "0.10.1"), "2026-09-29 10:42:52"),
            (
                "template_components",
                None,
                None,
                {"template": "event-study-finance", "skills": {}},
                "2026-09-29 10:42:52",
            ),
            (
                "specialist_start",
                None,
                "econometrics_specialist",
                {"skills": ["base/economist"]},
                "2026-09-29 12:50:00",
            ),
            ("specialist_end", None, "econometrics_specialist", {"success": True}, "2026-09-29 12:59:31"),
        ],
        calls=[
            ("identification_strategist", "claude_code", "claude-haiku-4-5", "2026-09-28 14:58:00"),
            ("econometrics_specialist", "claude_code", "claude-sonnet-4-5", "2026-09-29 12:55:00"),
        ],
    )


@pytest.fixture
def fake_git(monkeypatch):
    """The registry and blobs of two commits; C2 has no econometrics skill file."""
    registry = {
        C1: {"identification_strategist": ["base/researcher"], "econometrics_specialist": ["base/economist"]},
        C2: {"identification_strategist": ["base/researcher"], "econometrics_specialist": ["base/economist"]},
    }
    monkeypatch.setattr(d, "_registry_skills_at", lambda commit: registry.get(commit))

    def blob(commit: str, rel: str) -> str | None:
        if rel == "skills/files/econometrics/event-study.md" and commit == C2:
            return None
        return (commit[0] + rel[:1]) * 20

    monkeypatch.setattr(d, "_blob_at", blob)


def _manifest(run) -> dict[str, Any]:
    return {
        "title": "T",
        "ai": {"backend": "claude_code", "usage": [], "model": None},
        "process": {"template": "event-study-finance", "e2er_version": "0.12.1", "exported": "20261001"},
        "dependencies": {"uses": ["template:event-study-finance"]},
        "data": [],
        "run": {"paper_id": PID},
    }


def test_every_segment_is_recorded_and_each_step_names_its_commit(tmp_path: Path, fake_git):
    run = read_run(_two_commit_run(tmp_path), PID)
    assert [s["commit"] for s in run.segments] == [C1, C2]
    assert [s["version"] for s in run.segments] == ["0.10.0", "0.10.1"]
    assert [(w["specialist"], w["segment"]) for w in run.workflow] == [
        ("identification_strategist", 0),
        ("econometrics_specialist", 1),
    ]
    doc = build_dossier(_manifest(run), run=run)
    assert doc["schema"] == "e2er-dossier/0.6"
    assert doc["e2er"]["commit"] == C2 and doc["e2er"]["version"] == "0.10.1"
    assert doc["e2er"]["exported_with"] == "0.12.1" and len(doc["e2er"]["segments"]) == 2
    comps = {c["id"]: c for c in doc["components"]}
    assert comps["agent:identification_strategist"]["pin"]["commit"] == C1
    assert comps["agent:econometrics_specialist"]["pin"]["commit"] == C2
    assert [p["commit"] for p in comps["template:event-study-finance"]["pins"]] == [C1, C2]


def test_an_unresolvable_blob_is_recorded_as_unresolved_never_replaced_by_todays_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(d, "_blob_at", lambda commit, rel: None)
    monkeypatch.setattr(d, "_registry_skills_at", lambda commit: {})
    run = read_run(_two_commit_run(tmp_path), PID)
    doc = build_dossier(_manifest(run), run=run)
    for c in doc["components"]:
        for p in c.get("pins", [c["pin"]]):
            assert "git_blob" not in p
            assert p.get("note", "").startswith(("unresolved", "built into"))


def test_without_the_database_nothing_is_taken_from_the_publishing_machine(monkeypatch):
    monkeypatch.setattr(d, "_blob_at", lambda commit, rel: "today" * 8)
    doc = build_dossier(_manifest(None))
    assert doc["e2er"]["commit"] is None and doc["workflow"] == []
    assert doc["run"]["workflow_recorded"] is False
    assert all("git_blob" not in c["pin"] for c in doc["components"])


# ── 20: the specialists and skills that ran ──────────────────────────────────


def test_agents_and_skills_are_the_runs_not_todays(tmp_path: Path, fake_git):
    from src.core.research_object import build_manifest

    run = read_run(_two_commit_run(tmp_path), PID)
    assert run.agents == ["identification_strategist", "econometrics_specialist"]
    # C1: registry at C1 + the template's addition recorded at C1; C2: as recorded at dispatch
    assert run.skills == {
        "identification_strategist": ["base/researcher", "econometrics/event-study"],
        "econometrics_specialist": ["base/economist"],
    }
    bundle = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "showcase_export"
    m = build_manifest(
        bundle, owner="bhanneke", project="demo", contributors=[{"github": "b"}], run_record=run, db=None
    )
    assert m["ai"]["agents"] == ["identification_strategist", "econometrics_specialist"]
    assert m["components"]["skills_source"] == "recorded"
    assert "skill:e2er/econometrics/event-study" in m["dependencies"]["uses"]
    assert "agent:paper_drafter" not in m["dependencies"]["uses"]


# ── 21: no local paths ───────────────────────────────────────────────────────


def test_workspace_paths_become_bundle_paths(tmp_path: Path):
    db = _db(
        tmp_path,
        [
            ("specialist_start", None, "data_analyst", {}, "2026-09-29 08:00:00"),
            ("specialist_end", None, "data_analyst", {"success": True}, "2026-09-29 08:04:09"),
        ],
        contribs=[
            (
                "data_analyst",
                f"/Users/hanneke/e2er-studies/s/workspaces/{PID}/data_summary.md",
                1,
                None,
                "2026-09-29 08:04:09",
            )
        ],
    )
    [step] = read_run(db, PID, {"data/data_summary.md": {"sha256": "f" * 64, "bytes": 1}}).workflow
    assert step["output"]["file"] == "data/data_summary.md"
    assert "/Users" not in json.dumps(step) and "hanneke" not in json.dumps(step)


# ── 22: researcher actions, once each ────────────────────────────────────────


def test_only_researcher_action_rows_are_researcher_steps_and_the_rerun_is_listed_once(tmp_path: Path):
    db = _db(
        tmp_path,
        [
            (
                "researcher_action",
                "review_design",
                None,
                {
                    "action": "send_back",
                    "step": "review_design",
                    "at": "2026-09-28T23:04:57Z",
                    "target": "idea_developer",
                    "remark": "Rewrite",
                },
                "2026-09-28 23:04:57",
            ),
            ("researcher_rerun", "idea_developer", None, {"remark": "Rewrite"}, "2026-09-28 23:04:57"),
            ("specialist_start", None, "idea_developer", {}, "2026-09-28 23:05:00"),
            ("specialist_end", None, "idea_developer", {"success": True}, "2026-09-28 23:06:16"),
            (
                "researcher_action",
                "compare",
                None,
                {
                    "action": "rerun",
                    "step": "compare",
                    "target": "compare",
                    "remark": "Again",
                    "reruns": ["compare", "review_report"],
                    "at": "2026-09-30T18:27:19Z",
                },
                "2026-09-30 18:27:19",
            ),
            ("researcher_rerun", "compare", None, {"remark": "Again"}, "2026-09-30 18:27:19"),
        ],
    )
    run = read_run(db, PID)
    researcher = [w for w in run.workflow if w["type"] == "researcher"]
    assert [r["action"] for r in researcher] == ["send_back", "rerun"]
    assert researcher[1]["reruns"] == ["compare", "review_report"]
    [spec] = [w for w in run.workflow if w["type"] == "specialist"]
    assert spec["sent_back"] == {"at": "2026-09-28T23:04:57Z", "remark": "Rewrite"}
    assert [e["event"] for e in run.events] == ["rerun"] and run.events[0]["step"] == "compare"


# ── 23: outcome, halts, pauses, failures, the pre-registration check ─────────


def test_the_outcome_halts_pauses_failures_and_checks_are_recorded(tmp_path: Path):
    db = _db(
        tmp_path,
        [
            (
                "gate_halted",
                "event_window_gate",
                None,
                {"reasons": ["(c) 1 event date is not a trading day"]},
                "2026-09-28 23:24:04",
            ),
            (
                "paper_paused",
                "designing",
                None,
                {"reason": "interrupted", "previous_status": "designing"},
                "2026-09-29 07:24:28",
            ),
            (
                "preregistration_check",
                "estimation_gate",
                None,
                {"passed": False, "deviations": ["H2 changed"], "frozen_at": "2026-09-29T12:49:29Z"},
                "2026-09-29 13:04:41",
            ),
            ("failed", None, None, {"error": "RuntimeError: all specialists failed"}, "2026-09-29 09:45:12"),
            ("cancelled", None, None, {}, "2026-09-29 16:00:00"),
        ],
        status="rejected",
    )
    run = read_run(db, PID)
    halt, prereg = run.workflow
    assert halt == {
        "type": "check",
        "phase": None,
        "check": "event_window_gate",
        "passed": False,
        "enforced": True,
        "halted": True,
        "at": "2026-09-28T23:24:04Z",
        "detail": "(c) 1 event date is not a trading day",
    }
    assert prereg["check"] == "preregistration" and prereg["passed"] is False and prereg["deviations"] == ["H2 changed"]
    assert [e["event"] for e in run.events] == ["paper_paused", "failed", "cancelled"]
    assert run.events[0]["previous_status"] == "designing"
    # Stored `rejected` without an internal quality review: a check stopped the run.
    assert run.outcome == {"status": "stopped", "error": "halted", "at": "2026-09-29T15:59:32Z"}
    doc = build_dossier(_manifest(run), run=run)
    assert doc["run"]["outcome"]["status"] == "stopped" and doc["run"]["events"] == run.events
    assert "internal_review" not in doc["run"]


# ── 26: one time format, every field, models by time ─────────────────────────


def test_times_are_utc_with_z_and_no_field_of_an_action_is_dropped():
    cancel = {
        "action": "cancel",
        "step": "review_draft",
        "at": "2026-09-29T10:00:00+02:00",
        "by": "researcher",
        "via": "dashboard",
        "remark": "cancelled by the researcher",
        "previous_status": "paused",
    }
    step = researcher_step(cancel, "2026-09-29 08:00:00")
    assert step["at"] == "2026-09-29T08:00:00Z"
    assert step["by"] == "researcher" and step["via"] == "dashboard" and step["previous_status"] == "paused"
    assert d._utc("2026-09-28 14:56:39") == "2026-09-28T14:56:39Z"
    assert d._utc("20260929T091500Z") == "2026-09-29T09:15:00Z"


def test_models_are_matched_to_steps_by_time_not_by_order(tmp_path: Path):
    db = _db(
        tmp_path,
        [
            ("specialist_start", None, "data_analyst", {}, "2026-09-29 08:00:00"),
            ("specialist_end", None, "data_analyst", {"success": False}, "2026-09-29 08:04:00"),
            ("specialist_start", None, "data_analyst", {}, "2026-09-29 09:00:00"),
            ("specialist_end", None, "data_analyst", {"success": True}, "2026-09-29 09:04:00"),
        ],
        # The first attempt made no LLM call that was recorded; order-matching gave it the second's model.
        calls=[("data_analyst", "claude_code", "claude-sonnet-4-5", "2026-09-29 09:02:00")],
        contribs=[("data_analyst", "data.db", 1, None, "2026-09-29 09:04:00")],
    )
    first, second = read_run(db, PID).workflow
    assert first["model"] is None and "stopped_by" not in first and first["accepted"] is False
    assert second["model"] == "claude-sonnet-4-5" and second["accepted"] is True


def test_the_preregistration_carries_its_plan_files(tmp_path: Path):
    b = tmp_path / "b"
    (b / "design").mkdir(parents=True)
    (b / "design" / "preregistration.md").write_text("plan")
    (b / "design" / "preregistration.lock.json").write_text(
        json.dumps(
            {
                "file": "preregistration.md",
                "sha256": "a" * 64,
                "frozen_at": "2026-09-29 12:49:29",
                "plan_files": {"event_design.json": "b" * 64},
            }
        )
    )
    doc = build_dossier(_manifest(None), bundle=b)
    assert doc["preregistration"]["plan_files"] == {"event_design.json": "b" * 64}
    assert doc["preregistration"]["frozen_at"] == "2026-09-29T12:49:29Z"
