"""The event-study-finance template: its file, the event_window check, and template skills.

Three things are pinned here.

* The template is a valid pipeline file (schema and loader agree) and places the
  check between the design and the estimation.
* The `event_window` check passes a sound design and fails each rule on a
  design constructed to break exactly that rule, with the reason spelled out.
* A template's `[skills]` and `[sidecars]` reach the specialists of its runs,
  are recorded in the study's description and dossier, and change nothing for
  runs of other templates.
"""

from __future__ import annotations

import json
import sqlite3
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from src.core.pipeline import components
from src.core.pipeline.event_window import EVENT_DESIGN_FILE, check_event_window
from src.core.pipeline.spec import SCHEMA_PATH, PipelineError, find_spec, load_spec, spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.specialists.contracts import Contribution, WorkOrder
from src.core.strategist.state import GateHaltError, HumanReviewRequestedError

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "pipelines" / "event-study-finance.toml"
PID = "12345678-1234-1234-1234-123456789abc"


# ── the template file ───────────────────────────────────────────────────────


def test_the_template_validates_against_the_published_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    cls(schema).validate(tomllib.loads(TEMPLATE.read_text(encoding="utf-8")))


def test_the_template_loads_and_checks_the_design_before_estimation():
    spec = find_spec("event-study-finance")
    assert spec.name == "event-study-finance" and "overlapping events" in spec.description
    gate = spec.step("event_window_gate")
    assert gate is not None and gate.kind == "gate" and gate.check == "event_window" and gate.on_fail == "halt"
    assert gate.settings == {"min_estimation_days": 120, "min_gap_days": 10, "max_overlap_share": 0.0}
    # Inside the dispatch, after the design specialists and the data; not a step in sequence.
    assert {"identification_strategist", "data_analyst"} <= set(gate.after)
    assert "event_window_gate" not in spec.sequence_for("single_pass")
    assert spec.checks() == ["contracts", "estimation", "event_window"]
    # The fork keeps the researcher steps of empirical-preregistered.
    kinds = {(s.kind, s.name) for s in spec.steps}
    assert {("researcher", "review_design"), ("preregister", "preregister"), ("researcher", "review_draft")} <= kinds
    # The check comes before the pre-registration, so what is frozen passed it.
    names = [s.name for s in spec.steps]
    assert names.index("event_window_gate") < names.index("preregister")
    assert spec.skills["identification_strategist"] == ("econometrics/event-study",)
    assert spec.sidecars["identification_strategist"] == (EVENT_DESIGN_FILE,)


def test_the_template_credits_no_invented_person():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "e2er contributors" in text and "Okafor" not in text


def _spec(steps: list[dict[str, Any]], **top: Any):
    return spec_from_dict({"name": "t", "steps": steps, **top})


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        ({"steps": [{"kind": "strategist", "name": "s", "settings": {"min_gap_days": 5}}]}, "belongs to gate"),
        (
            {"steps": [{"kind": "gate", "name": "g", "check": "event_window", "settings": {"gap": 5}}]},
            "no setting",
        ),
        (
            {"steps": [{"kind": "gate", "name": "g", "check": "estimation", "settings": {"min_gap_days": 5}}]},
            "no setting",
        ),
        (
            {"steps": [{"kind": "gate", "name": "g", "check": "event_window", "settings": {"min_gap_days": -1}}]},
            "non-negative",
        ),
        (
            {"steps": [{"kind": "gate", "name": "g", "check": "event_window", "settings": {"max_overlap_share": 2}}]},
            "share between 0 and 1",
        ),
        (
            {"steps": [{"kind": "gate", "name": "g", "check": "event_window", "after": ["x"], "files": ["a.md"]}]},
            "files",
        ),
        ({"skills": {"identification_strategist": ["econometrics/no-such-skill"]}}, "no skill"),
        ({"skills": {"lena_okafor": ["econometrics/event-study"]}}, "unknown specialist"),
        ({"sidecars": {"identification_strategist": ["../design.json"]}}, "top-level .json"),
        ({"sidecars": {"identification_strategist": ["design.md"]}}, "top-level .json"),
    ],
)
def test_bad_template_additions_fail_at_load(bad, match):
    raw = {"name": "t", "steps": [{"kind": "strategist", "name": "initial"}], **bad}
    with pytest.raises(PipelineError, match=match):
        spec_from_dict(raw)


def test_a_gate_with_after_is_allowed_and_leaves_the_sequence():
    s = _spec(
        [
            {"kind": "gate", "name": "g", "check": "event_window", "after": ["identification_strategist"]},
            {"kind": "strategist", "name": "initial"},
        ]
    )
    assert s.sequence_for("single_pass") == ["initial"]


# ── the event_window check ──────────────────────────────────────────────────


def _calendar(start: date = date(2014, 1, 1), end: date = date(2019, 12, 31)) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


CAL = _calendar()


def _design(ws: Path, **over: Any) -> Path:
    design: dict[str, Any] = {
        "estimation_window": {"start": -150, "end": -12},
        "event_windows": [{"start": -1, "end": 1}, {"start": 0, "end": 5}],
        "calendar": {"table": "spy", "date_column": "date"},
        "overlap_treatment": "none",
        "events": [
            {"id": "e1", "date": "2016-03-16", "asset": "KBE"},
            {"id": "e2", "date": "2016-12-14", "asset": "KBE"},
            {"id": "e3", "date": "2017-06-14", "asset": "KBE"},
        ],
    }
    design.update(over)
    p = ws / EVENT_DESIGN_FILE
    p.write_text(json.dumps(design), encoding="utf-8")
    return p


def test_a_sound_design_passes(tmp_path: Path):
    _design(tmp_path)
    r = check_event_window(tmp_path, calendar=CAL)
    assert r.passed, r.reasons
    assert r.stats["estimation_days"] == 139 and r.stats["gap_days"] == 10 and r.stats["overlapping"] == 0
    assert r.detail().startswith("passed")


def test_a_missing_design_fails_with_a_reason(tmp_path: Path):
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and "event_design.json is missing" in r.reasons[0]


def test_a_design_that_is_not_json_fails(tmp_path: Path):
    (tmp_path / EVENT_DESIGN_FILE).write_text("{not json", encoding="utf-8")
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and "not valid JSON" in r.reasons[0]


# (a) the estimation window


def test_a_short_estimation_window_fails(tmp_path: Path):
    _design(tmp_path, estimation_window={"start": -100, "end": -12})
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed
    assert any(x.startswith("(a)") and "89 trading days" in x and "120" in x for x in r.reasons)


def test_a_too_small_gap_fails(tmp_path: Path):
    _design(tmp_path, estimation_window={"start": -150, "end": -5})
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and any("3 trading day(s) between" in x for x in r.reasons)


def test_an_estimation_window_reaching_into_the_event_window_fails(tmp_path: Path):
    _design(tmp_path, estimation_window={"start": -150, "end": 0})
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and any("inside or after the event window" in x for x in r.reasons)


def test_the_thresholds_come_from_the_template(tmp_path: Path):
    _design(tmp_path, estimation_window={"start": -100, "end": -5})
    assert not check_event_window(tmp_path, calendar=CAL).passed
    assert check_event_window(tmp_path, calendar=CAL, min_estimation_days=90, min_gap_days=3).passed


def test_malformed_windows_fail(tmp_path: Path):
    _design(tmp_path, estimation_window={"start": -10, "end": -150}, event_windows=[{"start": "a", "end": 1}])
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed
    assert any("estimation_window needs" in x for x in r.reasons) and any("event_windows needs" in x for x in r.reasons)


# (b) overlapping events


def _close_events() -> list[dict[str, str]]:
    return [
        {"id": "a", "date": "2016-03-16", "asset": "KBE"},
        {"id": "b", "date": "2016-03-18", "asset": "KBE"},  # two trading days later: windows overlap
        {"id": "c", "date": "2016-12-14", "asset": "KBE"},
    ]


def test_overlapping_events_of_the_same_asset_fail(tmp_path: Path):
    _design(tmp_path, events=_close_events())
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed
    reason = next(x for x in r.reasons if x.startswith("(b)"))
    assert "2 of 3 events" in reason and "a, b" in reason


def test_a_declared_overlap_treatment_passes_with_a_note(tmp_path: Path):
    for treatment in ("drop", "cluster", "aggregate"):
        _design(tmp_path, events=_close_events(), overlap_treatment=treatment)
        r = check_event_window(tmp_path, calendar=CAL)
        assert r.passed, r.reasons
        assert any(treatment in n and "2 of 3" in n for n in r.notes)


def test_the_overlap_threshold_comes_from_the_template(tmp_path: Path):
    _design(tmp_path, events=_close_events())
    assert check_event_window(tmp_path, calendar=CAL, max_overlap_share=0.7).passed
    assert not check_event_window(tmp_path, calendar=CAL, max_overlap_share=0.5).passed


def test_events_of_different_assets_on_the_same_day_do_not_overlap(tmp_path: Path):
    events = [
        {"id": "a", "date": "2016-03-16", "asset": "KBE"},
        {"id": "b", "date": "2016-03-16", "asset": "XLF"},
    ]
    _design(tmp_path, events=events)
    assert check_event_window(tmp_path, calendar=CAL).passed


def test_an_event_without_an_asset_overlaps_with_every_asset(tmp_path: Path):
    events = [
        {"id": "a", "date": "2016-03-16", "asset": "KBE"},
        {"id": "market", "date": "2016-03-17"},
    ]
    _design(tmp_path, events=events)
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and any("2 of 2" in x for x in r.reasons)


# (c) the data calendar


def test_an_event_date_that_is_not_a_trading_day_fails(tmp_path: Path):
    events = [{"id": "sat", "date": "2016-03-19", "asset": "KBE"}, {"id": "ok", "date": "2016-12-14", "asset": "KBE"}]
    _design(tmp_path, events=events)
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and any(x.startswith("(c)") and "sat (2016-03-19)" in x for x in r.reasons)


def test_windows_that_run_past_the_data_fail(tmp_path: Path):
    events = [
        {"id": "early", "date": "2014-02-03", "asset": "KBE"},  # fewer than 150 trading days of data before it
        {"id": "late", "date": "2019-12-30", "asset": "KBE"},  # fewer than 5 after it
    ]
    _design(tmp_path, events=events)
    r = check_event_window(tmp_path, calendar=CAL)
    assert not r.passed and any("run past the data" in x and "early, late" in x for x in r.reasons)


def _data_db(ws: Path, dates: list[date]) -> None:
    con = sqlite3.connect(ws / "data.db")
    con.execute('CREATE TABLE spy ("date" TEXT, close REAL)')
    con.executemany("INSERT INTO spy VALUES (?, 1.0)", [(f"{d.isoformat()} 00:00:00",) for d in dates])
    con.commit()
    con.close()


def test_the_calendar_is_read_from_the_papers_data(tmp_path: Path):
    _design(tmp_path)
    _data_db(tmp_path, CAL)
    r = check_event_window(tmp_path)
    assert r.passed, r.reasons
    assert r.stats["calendar"] == "spy.date"


def test_without_data_the_calendar_rule_fails(tmp_path: Path):
    _design(tmp_path)
    r = check_event_window(tmp_path)
    assert not r.passed and any(x.startswith("(c)") and "no data.db" in x for x in r.reasons)


def test_an_unsafe_calendar_name_is_refused(tmp_path: Path):
    _design(tmp_path, calendar={"table": "spy; DROP TABLE spy", "date_column": "date"})
    _data_db(tmp_path, CAL)
    r = check_event_window(tmp_path)
    assert not r.passed and any("not a plain table and column name" in x for x in r.reasons)


# ── the check in a run ──────────────────────────────────────────────────────


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


def _runner(tmp_path: Path, spec, governance: str = "full"):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id = PID
    r._workspace = tmp_path
    r._mode = "single_pass"
    r._spec = spec
    r._triggers = [s for s in spec.steps if s.kind in ("researcher", "preregister", "gate") and s.after]
    r._state = PipelineState(paper_id=PID, mode="single_pass")
    r._in_initial = True
    r._contributions = []
    r._governance = governance
    r._failure_counts = {}
    r._last_specialist_errors = {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers = [], []
    return r


def _gate_spec(on_fail: str = "halt"):
    return _spec(
        [
            {
                "kind": "gate",
                "name": "event_window_gate",
                "check": "event_window",
                "on_fail": on_fail,
                "after": ["identification_strategist", "data_analyst"],
                "settings": {"min_estimation_days": 120},
            },
            {"kind": "preregister", "name": "preregister", "after": ["identification_strategist", "data_analyst"]},
            {"kind": "strategist", "name": "initial"},
        ]
    )


def _orders() -> list[WorkOrder]:
    return [
        WorkOrder(paper_id=PID, specialist="identification_strategist", focus="x", parallel_group=0),
        WorkOrder(paper_id=PID, specialist="data_analyst", focus="d", parallel_group=1),
        WorkOrder(paper_id=PID, specialist="econometrics_specialist", focus="y", parallel_group=1),
        WorkOrder(paper_id=PID, specialist="paper_drafter", focus="z", parallel_group=2),
    ]


def test_the_estimation_waits_for_the_check(tmp_path: Path):
    r = _runner(tmp_path, _gate_spec())
    groups = {o.specialist: o.parallel_group for o in r._order_for_researcher_steps(_orders())}
    assert groups["data_analyst"] < groups["econometrics_specialist"] < groups["paper_drafter"]


async def test_a_failed_check_halts_before_estimation_and_says_why(tmp_path: Path, events, monkeypatch):
    monkeypatch.setattr("src.core.pipeline.event_window.load_calendar", lambda ws, spec: (CAL, "spy.date"))
    _design(tmp_path, estimation_window={"start": -60, "end": -12})
    r = _runner(tmp_path, _gate_spec())
    remaining = [WorkOrder(paper_id=PID, specialist="econometrics_specialist", focus="y", parallel_group=3)]
    with pytest.raises(GateHaltError) as halt:
        await r._between_groups({"identification_strategist", "data_analyst"}, remaining)
    assert halt.value.stage == "event_window_gate" and "49 trading days" in halt.value.reasons[0]
    st = r._state
    assert st.pending_review_stage == "event_window_gate" and not st.is_complete("event_window_gate")
    assert st.metadata["review"]["kind"] == "gate" and EVENT_DESIGN_FILE in st.metadata["review"]["files"]
    assert [o["specialist"] for o in st.metadata["pending_orders"]] == ["econometrics_specialist"]
    gate_events = [p for k, s, p in events if k == "gate_enforced"]
    assert len(gate_events) == 1 and "(a)" in gate_events[0].pop("detail")
    assert gate_events == [{"gate": "event_window", "passed": False, "enforced": True, "regime": "full"}]

    # Approving does not pass a failed check: it runs again on resume, and a fixed design passes.
    st.approve("event_window_gate")
    with pytest.raises(GateHaltError):
        await r._between_groups(set(), remaining)
    _design(tmp_path)
    with pytest.raises(HumanReviewRequestedError) as stop:
        await r._between_groups(set(), remaining)
    assert stop.value.stage == "preregister" and not isinstance(stop.value, GateHaltError)
    assert st.is_complete("event_window_gate")


async def test_the_check_runs_before_an_estimation_group_even_if_its_specialists_did_not_run(
    tmp_path: Path, events, monkeypatch
):
    monkeypatch.setattr("src.core.pipeline.event_window.load_calendar", lambda ws, spec: (CAL, "spy.date"))
    r = _runner(tmp_path, _gate_spec())  # no event_design.json: the strategist never dispatched its author
    ran: list[str] = []

    async def _never(*a, **k):
        ran.append("dispatched")
        return []

    monkeypatch.setattr("src.core.strategist.runner.execute_with_dependencies", _never)
    orders = [WorkOrder(paper_id=PID, specialist="econometrics_specialist", focus="y", parallel_group=0)]
    with pytest.raises(GateHaltError) as halt:
        await r._execute_orders(orders)
    assert "missing" in halt.value.reasons[0] and ran == []


async def test_shadow_records_and_continues(tmp_path: Path, events, monkeypatch):
    monkeypatch.setattr("src.core.pipeline.event_window.load_calendar", lambda ws, spec: (CAL, "spy.date"))
    r = _runner(tmp_path, _gate_spec(on_fail="shadow"))
    await r._run_open_gates(r._state, [])
    assert r._state.is_complete("event_window_gate")
    assert [(k, p["passed"]) for k, _s, p in events if k.startswith("gate_")] == [("gate_shadow", False)]


async def test_governance_off_shadows_the_check(tmp_path: Path, events, monkeypatch):
    monkeypatch.setattr("src.core.pipeline.event_window.load_calendar", lambda ws, spec: (CAL, "spy.date"))
    r = _runner(tmp_path, _gate_spec(), governance="off")
    await r._run_open_gates(r._state, [])
    assert r._state.is_complete("event_window_gate")


async def test_retry_sends_the_strategist_back_once(tmp_path: Path, events, monkeypatch):
    monkeypatch.setattr("src.core.pipeline.event_window.load_calendar", lambda ws, spec: (CAL, "spy.date"))
    _design(tmp_path, estimation_window={"start": -60, "end": -12})
    r = _runner(tmp_path, _gate_spec(on_fail="retry"))
    sent: list[WorkOrder] = []

    async def _fixes(order, *a, **k):
        sent.append(order)
        _design(tmp_path)
        return Contribution(paper_id=PID, specialist=order.specialist, output="")

    monkeypatch.setattr("src.core.specialists.dispatcher.execute_work_order", _fixes)
    await r._run_open_gates(r._state, [])
    assert r._state.is_complete("event_window_gate")
    assert sent[0].specialist == "identification_strategist" and "49 trading days" in sent[0].focus
    assert [p["passed"] for k, _s, p in events if k == "gate_enforced"] == [False, True]


def test_a_check_verdict_appears_in_the_dossier(tmp_path: Path):
    from src.core.dossier import recorded_workflow

    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT);"
        "CREATE TABLE contributions (id TEXT, paper_id TEXT, specialist TEXT, stage TEXT, output_file TEXT,"
        " success INT, error_msg TEXT, usage_tokens INT, cost_usd REAL, duration_sec REAL, created_at TEXT);"
        "CREATE TABLE llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT,"
        " cost_usd REAL, created_at TEXT);"
    )
    payload = {"gate": "event_window", "passed": False, "enforced": True, "detail": "(b) 2 of 3 events overlap"}
    con.execute(
        "INSERT INTO pipeline_events VALUES ('1', ?, 'phase_start', 'initial', NULL, '{}', '2026-09-28 10:00:00')",
        (PID,),
    )
    con.execute(
        "INSERT INTO pipeline_events VALUES ('2', ?, 'gate_enforced', 'event_window', NULL, ?, '2026-09-28 10:01:00')",
        (PID, json.dumps(payload)),
    )
    con.commit()
    con.close()
    steps = recorded_workflow(db, PID)
    assert steps == [
        {
            "type": "check",
            "phase": "initial",
            "check": "event_window",
            "passed": False,
            "enforced": True,
            "at": "2026-09-28T10:01:00Z",
            "detail": "(b) 2 of 3 events overlap",
        }
    ]


# ── template skills and sidecars ────────────────────────────────────────────


def test_template_skills_merge_after_the_registry_and_only_for_its_runs():
    from src.core.specialists.registry import SPECIALIST_SKILLS
    from src.skills.loader import load_skills_for_specialist

    spec = load_spec(TEMPLATE)
    own = SPECIALIST_SKILLS["identification_strategist"]
    assert "econometrics/event-study" not in own
    merged = components.skills_for("identification_strategist", spec)
    assert merged == [*own, "econometrics/event-study"]
    # Already the econometrics specialist's own: listed once.
    assert components.skills_for("econometrics_specialist", spec).count("econometrics/event-study") == 1

    assert "event_design.json" not in load_skills_for_specialist("identification_strategist")
    token = components.activate(spec)
    try:
        assert "event_design.json" in load_skills_for_specialist("identification_strategist")
    finally:
        components.deactivate(token)
    assert components.active() is None


def test_template_sidecars_reach_the_work_order(tmp_path: Path):
    from src.core.specialists.dispatcher import _inject_context

    spec = load_spec(TEMPLATE)
    order = WorkOrder(paper_id=PID, specialist="identification_strategist", focus="x", context="c")
    assert _inject_context(order, tmp_path).sidecar_artifacts == ["identification_spec.json"]
    token = components.activate(spec)
    try:
        assert _inject_context(order, tmp_path).sidecar_artifacts == ["identification_spec.json", EVENT_DESIGN_FILE]
    finally:
        components.deactivate(token)


def test_template_skills_are_recorded_in_the_description_and_dossier(tmp_path: Path):
    import shutil

    from src.core.dossier import build_dossier
    from src.core.research_object import build_manifest

    showcase = ROOT / "examples" / "showcase"
    bundle = tmp_path / "bundle"
    shutil.copytree(showcase, bundle)
    paper_id = json.loads((showcase / "provenance.json").read_text())["run"]["paper_id"]
    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE papers (id TEXT, mode TEXT, methodology TEXT, governance TEXT);"
        "CREATE TABLE llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT,"
        " cost_usd REAL, created_at TEXT);"
    )
    con.execute("INSERT INTO papers VALUES (?, 'single_pass', 'empirical', 'full')", (paper_id,))
    con.execute(
        "INSERT INTO llm_usage VALUES ('1', ?, 'identification_strategist', 'claude_code', 'm', 1, 1, 0, 0, 0, 't')",
        (paper_id,),
    )
    con.commit()
    con.close()
    m = build_manifest(
        bundle,
        owner="bhanneke",
        project="demo",
        contributors=[{"github": "bhanneke"}],
        db=db,
        template="event-study-finance",
        template_file=TEMPLATE,
    )
    assert "econometrics/event-study" in m["components"]["skills"]["identification_strategist"]
    assert "skill:e2er/econometrics/event-study" in m["dependencies"]["uses"]
    doc = build_dossier(m)
    ids = {c["id"]: c for c in doc["components"]}
    assert ids["skill:e2er/econometrics/event-study"]["pin"]["path"] == "skills/files/econometrics/event-study.md"
    assert ids["template:event-study-finance"]["pin"]["path"] == "pipelines/event-study-finance.toml"
    # Another template does not add the skill.
    other = build_manifest(
        bundle, owner="bhanneke", project="demo", contributors=[{"github": "bhanneke"}], db=db, template="empirical"
    )
    assert "econometrics/event-study" not in other["components"]["skills"]["identification_strategist"]


def test_the_preregistration_includes_the_event_design(tmp_path: Path):
    from src.core.pipeline import preregistration as prereg

    (tmp_path / "paper_plan.md").write_text("H1: bank stocks fall on hikes.\n")
    _design(tmp_path)
    text = prereg.assemble(tmp_path).read_text()
    assert "Events and windows (machine-readable)" in text
    assert EVENT_DESIGN_FILE in prereg.freeze(tmp_path)["plan_files"]


# (d) the researcher's own event table


def _source_db(ws: Path, dates: list[str], calendar: list[date] = CAL, table: str = "fomc_announcement_dates") -> None:
    con = sqlite3.connect(ws / "data.db")
    con.execute('CREATE TABLE spy ("date" TEXT, close REAL)')
    con.executemany("INSERT INTO spy VALUES (?, 1.0)", [(d.isoformat(),) for d in calendar])
    con.execute(f'CREATE TABLE "{table}" (announcement_date TEXT, source_url TEXT)')
    con.executemany(f'INSERT INTO "{table}" VALUES (?, ?)', [(d, "https://www.federalreserve.gov/") for d in dates])
    con.commit()
    con.close()


SOURCE = {"table": "fomc_announcement_dates", "date_column": "announcement_date"}
TABLE_DATES = ["2016-03-16", "2016-12-14", "2017-06-14"]


def _events(*dates: str) -> list[dict[str, str]]:
    return [{"id": f"e{i}", "date": d, "asset": "KBE"} for i, d in enumerate(dates)]


def test_d_design_matching_the_researchers_table_passes(tmp_path: Path):
    _source_db(tmp_path, TABLE_DATES)
    _design(tmp_path, events_source=SOURCE, events=_events(*TABLE_DATES))
    r = check_event_window(tmp_path)
    assert r.passed, r.reasons
    assert r.stats["events_source"] == "fomc_announcement_dates.announcement_date"


def test_d_a_missing_event_fails(tmp_path: Path):
    _source_db(tmp_path, TABLE_DATES)
    _design(tmp_path, events_source=SOURCE, events=_events("2016-03-16", "2016-12-14"))
    r = check_event_window(tmp_path)
    assert not r.passed
    assert any("1 event(s) of the researcher's table are missing" in x and "2017-06-14" in x for x in r.reasons)


def test_d_an_extra_event_fails(tmp_path: Path):
    _source_db(tmp_path, TABLE_DATES)
    _design(tmp_path, events_source=SOURCE, events=_events(*TABLE_DATES, "2018-06-13"))
    r = check_event_window(tmp_path)
    assert not r.passed
    assert any("not in the researcher's table" in x and "2018-06-13" in x for x in r.reasons)


def test_d_a_shifted_event_fails(tmp_path: Path):
    _source_db(tmp_path, TABLE_DATES)
    # FRED's effective date, one day after the announcement.
    _design(tmp_path, events_source=SOURCE, events=_events("2016-03-17", "2016-12-14", "2017-06-14"))
    r = check_event_window(tmp_path)
    assert not r.passed
    reason = next(x for x in r.reasons if "different day" in x)
    assert "2016-03-16 in the table, 2016-03-17 in the design" in reason
    assert not any("missing" in x or "not in the researcher's table" in x for x in r.reasons)


def test_d_a_weekend_announcement_maps_to_the_next_trading_day(tmp_path: Path):
    # 2020-03-15 was a Sunday; the market's day 0 is Monday 2020-03-16.
    cal = _calendar(date(2019, 1, 1), date(2020, 12, 31))
    _source_db(tmp_path, ["2020-03-15", "2020-09-16"], calendar=cal)
    _design(tmp_path, events_source=SOURCE, events=_events("2020-03-16", "2020-09-16"))
    r = check_event_window(tmp_path)
    assert r.passed, r.reasons
    assert any("2020-03-15 → 2020-03-16" in n for n in r.notes)
    # Keeping the Sunday itself is caught by (c): not a trading day.
    _design(tmp_path, events_source=SOURCE, events=_events("2020-03-15", "2020-09-16"))
    assert not check_event_window(tmp_path).passed


def test_d_a_missing_source_table_fails(tmp_path: Path):
    _source_db(tmp_path, TABLE_DATES, table="other_name")
    _design(tmp_path, events_source=SOURCE, events=_events(*TABLE_DATES))
    r = check_event_window(tmp_path)
    assert not r.passed and any(x.startswith("(d)") and "cannot be read" in x for x in r.reasons)


def test_d_an_undeclared_event_table_only_warns(tmp_path: Path):
    _source_db(tmp_path, TABLE_DATES)
    _design(tmp_path, events=_events("2016-03-16", "2018-06-13"))  # no events_source
    r = check_event_window(tmp_path)
    assert r.passed, r.reasons
    assert any(n.startswith("(d) warning") and "fomc_announcement_dates (announcement_date)" in n for n in r.notes)


def test_the_design_schema_accepts_the_documented_example(tmp_path: Path):
    schema = json.loads((ROOT / "docs" / "schemas" / "event_design.schema.json").read_text())
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    design = json.loads(_design(tmp_path, events_source=SOURCE).read_text())
    cls(schema).validate(design)
    with pytest.raises(jsonschema.ValidationError):
        cls(schema).validate({**design, "events_source": {"table": "x; drop", "date_column": "d"}})
