"""Data only from the data analyst, and nothing estimated before a pre-registration is frozen.

The 2026-09-28 event study (paper 9e1c7f09) is the case: after the design
review, the data analyst wrote run_estimation.py, the runner discovered it as
the analyst's script and ran it, and CARs for all 31 events sat in data.db
(`event_study_results`) with two CAR figures, before the event-window check
and before the pre-registration. No raw price table was stored, so the check
could not even find its calendar.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.core.pipeline import preregistration as prereg
from src.core.pipeline.spec import spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.specialists.contract_check import check_declared_tables, check_specialist_artifacts
from src.core.specialists.contracts import Contribution
from src.core.strategist.state import GateHaltError, HumanReviewRequestedError

PID = "12345678-1234-1234-1234-123456789abc"


def _db(ws: Path, tables: dict[str, int]) -> None:
    con = sqlite3.connect(ws / "data.db")
    for name, n in tables.items():
        con.execute(f'CREATE TABLE "{name}" (date TEXT, close REAL)')
        con.executemany(f'INSERT INTO "{name}" VALUES (?, 1.0)', [(f"2020-01-{i % 28 + 1:02d}",) for i in range(n)])
    con.commit()
    con.close()


def _dictionary(ws: Path, names: list[str]) -> None:
    (ws / "data_dictionary.json").write_text(
        json.dumps({"tables": [{"name": n, "source": "yfinance"} for n in names], "fields": []})
    )


def _summary(ws: Path, text: str) -> None:
    (ws / "data_summary.md").write_text("# Data summary\n\n" + text + "\n" + "Sample description. " * 10)


# ── 1. the data analyst loads the declared tables and counts them truthfully ──


def test_declared_tables_loaded_and_counted_pass(tmp_path: Path):
    _dictionary(tmp_path, ["spy_prices", "kbe_prices"])
    _db(tmp_path, {"spy_prices": 3018, "kbe_prices": 3018})
    _summary(tmp_path, "spy_prices: 3,018 rows. kbe_prices: 3018 rows.")
    checks = check_declared_tables(tmp_path)
    assert [c.ok for c in checks] == [True, True]


def test_a_missing_or_empty_declared_table_fails_and_names_what_is_there(tmp_path: Path):
    _dictionary(tmp_path, ["spy_prices", "kbe_prices", "dgs2"])
    _db(tmp_path, {"spy_prices": 10, "dgs2": 0, "event_study_results": 31})
    _summary(tmp_path, "spy_prices: 10 rows")
    [check] = check_declared_tables(tmp_path)
    assert not check.ok and check.artifact == "data.db"
    assert "missing from data.db: kbe_prices" in check.reason and "empty in data.db: dgs2" in check.reason
    assert "event_study_results (31 rows)" in check.reason


def test_speculative_row_counts_fail(tmp_path: Path):
    _dictionary(tmp_path, ["spy_prices"])
    _db(tmp_path, {"spy_prices": 3018})
    _summary(tmp_path, "spy_prices: expected ~2,520 rows")
    checks = check_declared_tables(tmp_path)
    assert checks[0].ok and not checks[1].ok
    assert "spy_prices (actual 3018 rows)" in checks[1].reason


def test_the_data_analyst_contract_includes_the_tables(tmp_path: Path):
    _dictionary(tmp_path, ["spy_prices"])
    _summary(tmp_path, "spy_prices: 5 rows")
    (tmp_path / "summary_statistics.json").write_text('{"n": 1}')
    failed = [c for c in check_specialist_artifacts(tmp_path, "data_analyst") if not c.ok]
    assert [c.artifact for c in failed] == ["data.db"]


def test_without_declared_tables_nothing_changes(tmp_path: Path):
    (tmp_path / "data_dictionary.json").write_text('{"fields": []}')
    assert check_declared_tables(tmp_path) == []


def test_the_data_cli_writes_the_table_into_data_db(tmp_path: Path, monkeypatch):
    import argparse

    from src.modules.data import cli

    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / PID).mkdir()
    result = {"items": [{"date": "2020-01-02", "close": 1.0}, {"date": "2020-01-03", "close": 2.0}]}
    cli._maybe_save_table(result, argparse.Namespace(table="SPY Prices", paper_id=PID))
    assert result["saved_table"] == "spy_prices" and result["saved_table_rows"] == 2
    con = sqlite3.connect(tmp_path / PID / "data.db")
    assert con.execute("SELECT COUNT(*) FROM spy_prices").fetchone()[0] == 2
    con.close()


def test_the_runner_never_runs_the_estimation_script_for_the_data_analyst(tmp_path: Path):
    from src.core.specialists.post_execution import EXECUTION_CONVENTIONS, _discover_script

    (tmp_path / "run_estimation.py").write_text("# writes summary_statistics.json and CARs\n")
    script, _ = _discover_script(tmp_path, EXECUTION_CONVENTIONS["data_analyst"])
    assert script is None
    (tmp_path / "build_panel.py").write_text("# writes summary_statistics.json\n")
    script, _ = _discover_script(tmp_path, EXECUTION_CONVENTIONS["data_analyst"])
    assert script is not None and script.name == "build_panel.py"


def test_the_data_skill_is_loaded_and_says_never_estimate():
    from src.core.specialists.registry import SPECIALIST_SKILLS
    from src.skills.loader import load_skills_for_specialist

    for sp in ("data_architect", "data_analyst", "identification_strategist"):
        assert "data/data-tables" in SPECIALIST_SKILLS[sp]
    assert "It never estimates" in load_skills_for_specialist("data_analyst")


# ── 2. nothing estimated before the freeze ──────────────────────────────────


def _old_study(ws: Path) -> None:
    """What the 9e1c7f09 workspace held when the pre-registration came up."""
    (ws / "run_estimation.py").write_text("import statsmodels.api as sm\n# market model, CARs\n")
    (ws / "fig_car_by_direction.pdf").write_bytes(b"%PDF-1.4")
    (ws / "fig_sample_by_year.pdf").write_bytes(b"%PDF-1.4")  # descriptive: not a result
    (ws / "build_panel.py").write_text("import pandas as pd\n# clean prices\n")
    _db(ws, {"event_study_results": 31, "fomc_announcement_dates": 31, "spy_prices": 3018})


def test_estimation_outputs_are_found(tmp_path: Path):
    _old_study(tmp_path)
    (tmp_path / "estimation_results.json").write_text('{"main": {}}')
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "main.tex").write_text("x")
    assert prereg.estimation_outputs(tmp_path) == [
        "data.db:event_study_results",
        "estimation_results.json",
        "fig_car_by_direction.pdf",
        "run_estimation.py",
        "tables/main.tex",
    ]


def test_a_clean_workspace_has_none(tmp_path: Path):
    _db(tmp_path, {"spy_prices": 3, "fomc_announcement_dates": 31})
    (tmp_path / "build_panel.py").write_text("import pandas as pd\n")
    assert prereg.estimation_outputs(tmp_path) == []


def test_set_aside_moves_and_records_never_deletes(tmp_path: Path):
    _old_study(tmp_path)
    found = prereg.estimation_outputs(tmp_path)
    manifest = prereg.set_aside(tmp_path, found)
    assert prereg.estimation_outputs(tmp_path) == []
    folder = tmp_path / prereg.SET_ASIDE_DIR / manifest["set_aside_at"]
    assert (folder / "run_estimation.py").is_file() and (folder / "fig_car_by_direction.pdf").is_file()
    con = sqlite3.connect(folder / "tables.db")
    assert con.execute("SELECT COUNT(*) FROM event_study_results").fetchone()[0] == 31
    con.close()
    items = {i.get("file") or i.get("table"): i for i in manifest["items"]}
    assert items["event_study_results"]["rows"] == 31 and len(items["run_estimation.py"]["sha256"]) == 64
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    # Data stay.
    con = sqlite3.connect(tmp_path / "data.db")
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master")} == {"fomc_announcement_dates", "spy_prices"}
    con.close()


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


def _runner(tmp_path: Path, governance: str = "full"):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id = PID
    r._workspace = tmp_path
    r._mode = "single_pass"
    r._spec = spec_from_dict(
        {
            "name": "t",
            "steps": [
                {"kind": "preregister", "name": "preregister", "after": ["data_analyst"]},
                {"kind": "strategist", "name": "initial"},
            ],
        }
    )
    r._triggers = [s for s in r._spec.steps if s.after]
    r._state = PipelineState(paper_id=PID, mode="single_pass")
    r._in_initial = True
    r._contributions = []
    r._governance = governance
    r._failure_counts = {}
    r._last_specialist_errors = {}
    return r


async def test_the_preregistration_halts_on_estimates_and_lists_them(tmp_path: Path, events):
    _old_study(tmp_path)
    (tmp_path / "paper_plan.md").write_text("H1\n")
    r = _runner(tmp_path)
    with pytest.raises(GateHaltError) as halt:
        await r._between_groups({"data_analyst"}, [])
    st = r._state
    assert halt.value.stage == "preregister" and "run_estimation.py" in halt.value.reasons[0]
    assert "data.db:event_study_results" in halt.value.reasons[0]
    assert not (tmp_path / prereg.PREREG_FILE).exists()  # nothing assembled over results
    assert st.metadata["review"]["kind"] == "gate" and st.metadata["preregistration_blocked"]
    assert [(k, p["gate"], p["passed"]) for k, _s, p in events if k == "gate_enforced"] == [
        ("gate_enforced", "preregistration", False)
    ]

    # Approving (what resume does) does not freeze: the check runs again and halts.
    st.approve("preregister")
    with pytest.raises(GateHaltError):
        await r._settle_researcher_decisions(st)
    assert not (tmp_path / prereg.LOCK_FILE).exists() and not st.is_approved("preregister")

    # Sending the analyst back moves the outputs aside, records it, and stops again.
    ran: list[str] = []

    async def _exec(orders):
        ran.extend(o.specialist for o in orders)
        return [Contribution(paper_id=PID, specialist=o.specialist, output="") for o in orders]

    r._execute_orders = _exec
    st.metadata["rerun"] = [{"target": "data_analyst", "remark": "Data only."}]
    st.metadata["sent_back"] = True
    with pytest.raises(HumanReviewRequestedError):
        await r._settle_researcher_decisions(st)
    assert ran == ["data_analyst"] and prereg.estimation_outputs(tmp_path) == []
    aside = [p for k, _s, p in events if k == "estimation_set_aside"]
    assert aside and {i.get("file") or i.get("table") for i in aside[0]["items"]} >= {
        "run_estimation.py",
        "event_study_results",
    }

    # Now clean: approving shows the pre-registration itself first, then freezes.
    st.approve("preregister")
    with pytest.raises(HumanReviewRequestedError) as stop:
        await r._settle_researcher_decisions(st)
    assert not isinstance(stop.value, GateHaltError) and (tmp_path / prereg.PREREG_FILE).is_file()
    assert not (tmp_path / prereg.LOCK_FILE).exists()
    st.approve("preregister")
    await r._settle_researcher_decisions(st)
    assert (tmp_path / prereg.LOCK_FILE).is_file() and st.is_complete("preregister")


async def test_a_clean_workspace_reaches_the_preregistration(tmp_path: Path, events):
    (tmp_path / "paper_plan.md").write_text("H1\n")
    _db(tmp_path, {"spy_prices": 3})
    r = _runner(tmp_path)
    with pytest.raises(HumanReviewRequestedError) as stop:
        await r._between_groups({"data_analyst"}, [])
    assert not isinstance(stop.value, GateHaltError) and (tmp_path / prereg.PREREG_FILE).is_file()


async def test_estimates_after_the_freeze_are_fine(tmp_path: Path, events):
    (tmp_path / "paper_plan.md").write_text("H1\n")
    r = _runner(tmp_path)
    with pytest.raises(HumanReviewRequestedError):
        await r._between_groups({"data_analyst"}, [])
    r._state.approve("preregister")
    await r._settle_researcher_decisions(r._state)
    _old_study(tmp_path)
    await r._settle_researcher_decisions(r._state)  # frozen: no halt


def test_the_dossier_lists_what_was_set_aside(tmp_path: Path):
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
    payload = {"reason": "estimation output found", "items": [{"table": "event_study_results", "rows": 31}]}
    con.execute(
        "INSERT INTO pipeline_events VALUES ('1', ?, 'estimation_set_aside', 'preregister', NULL, ?, 't')",
        (PID, json.dumps(payload)),
    )
    con.commit()
    con.close()
    [step] = recorded_workflow(db, PID)
    assert step["type"] == "set_aside" and step["items"] == payload["items"]


# ── 3. the calendar is a table the analyst wrote ────────────────────────────


def test_the_calendar_must_be_a_declared_loaded_table_and_the_failure_names_the_tables(tmp_path: Path):
    from src.core.pipeline.event_window import check_event_window

    _dictionary(tmp_path, ["spy_prices", "kbe_prices"])
    _db(tmp_path, {"kbe_prices": 5, "fomc_announcement_dates": 31})
    design = {
        "estimation_window": {"start": -250, "end": -12},
        "event_windows": [{"start": -1, "end": 1}],
        "calendar": {"table": "spy_prices", "date_column": "date"},
        "events": [{"id": "e", "date": "2020-01-02", "asset": "KBE"}],
    }
    (tmp_path / "event_design.json").write_text(json.dumps(design))
    r = check_event_window(tmp_path)
    reason = next(x for x in r.reasons if "no such table: spy_prices" in x)
    assert "Tables in data.db: fomc_announcement_dates (31 rows), kbe_prices (5 rows)" in reason

    design["calendar"]["table"] = "fomc_announcement_dates"
    (tmp_path / "event_design.json").write_text(json.dumps(design))
    r = check_event_window(tmp_path)
    assert any("is not one of the tables data_dictionary.json declares" in x for x in r.reasons)
