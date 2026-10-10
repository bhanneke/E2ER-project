"""The number check with rendered tables and no traced cell: a stop, never a pass.

Live run 2026-10-10 (E2E-01, Claude Haiku 4.5 via Claude Code, e2er 0.15.1):
the renderer wrote tables/descriptive_stats.tex and tables/main.tex from the
results files, and the draft ``\\input``-ed neither. The number check, which reads
the draft, found no table and compared 0 table cells; it checked 87 prose
numbers, reported ``passed: true``, and the run went on to the reviewers and
the export. ``e2er verify`` then failed the export (integrity: no table_cell
edges; numbers: 0 cells traced).

tests/fixtures/haiku_untraced_tables holds that run's draft, table spec, render
report, results files and rendered tables, unchanged (plus decomposition.tex, a
stale table from the first spec). With the tables included, every cell traces:
the tracing was never the problem.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from src.core.pipeline.researcher import NUMBERS_STEP, pending_review
from src.core.pipeline.verify_numbers import included_tables, rendered_tables, verify
from src.core.specialists.contract_check import check_draft_includes_declared_tables, check_specialist_artifacts
from tests.test_number_check import TEMPLATE, _act, _Backend, _Run, _state

FIXTURE = Path(__file__).parent / "fixtures" / "haiku_untraced_tables"
TABLES = ["descriptive_stats.tex", "main.tex"]
INPUTS = "\\input{tables/descriptive_stats.tex}\n\\input{tables/main.tex}\n"


def _copy(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest)
    return dest


def _include_tables(ws: Path) -> None:
    draft = ws / "paper_draft.tex"
    text = draft.read_text(encoding="utf-8")
    assert "\\end{document}" in text
    draft.write_text(text.replace("\\end{document}", INPUTS + "\\end{document}"), encoding="utf-8")


# ── the check on the run's own files ───────────────────────────────────────


def test_the_runs_draft_includes_none_of_its_rendered_tables(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    report = verify(ws / "paper_draft.tex", ws)

    # What the run recorded: no table value, rich prose coverage, `passed`.
    assert report.total_values_in_tables == 0
    assert report.prose_total > 0
    assert report.passed and not report.critical_mismatches
    # And what it must now say: the rendered tables went unchecked.
    assert report.rendered_tables == TABLES  # the stale decomposition.tex is not one of them
    assert report.rendered_tables_not_in_draft == TABLES
    assert report.tables_untraced
    reason = report.untraced_reason
    assert "includes none of its 2 rendered results table(s) (descriptive_stats.tex, main.tex)" in reason
    assert "\\input{tables/descriptive_stats.tex}, \\input{tables/main.tex}" in reason
    saved = report.to_dict()
    assert saved["tables_untraced"] is True and saved["untraced_reason"] == reason


@pytest.mark.parametrize(("rounding", "cells"), [(False, 19), (True, 25)])
def test_with_the_tables_included_every_cell_traces(tmp_path: Path, rounding: bool, cells: int):
    ws = _copy(tmp_path / "ws")
    _include_tables(ws)
    report = verify(ws / "paper_draft.tex", ws, rounding=rounding)

    # The run's gate rule skips zero cells, verify's rule (rounding) counts them.
    assert report.total_values_in_tables == cells
    assert report.matched == cells and not report.mismatches and report.unverifiable == 0
    assert not report.tables_untraced and report.untraced_reason == ""
    assert report.rendered_tables_not_in_draft == []


def test_rendered_tables_come_from_the_render_report_and_inputs_ignore_comments(tmp_path: Path):
    assert rendered_tables(tmp_path) == []
    (tmp_path / "table_render_report.json").write_text("not json")
    assert rendered_tables(tmp_path) == []
    (tmp_path / "table_render_report.json").write_text(json.dumps({"rendered": ["main.tex", "a.tex", 3]}))
    assert rendered_tables(tmp_path) == ["a.tex", "main.tex"]

    tex = "% \\input{tables/a.tex}\n\\input{tables/main}\n50\\% \\input{tables/b.tex} % \\input{tables/c.tex}\n"
    assert included_tables(tex) == {"main.tex", "b.tex"}


def test_tables_in_the_paper_with_no_number_in_them_are_untraced_too(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "tables").mkdir(parents=True)
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"coef": 0.5}}))
    (ws / "table_render_report.json").write_text(json.dumps({"rendered": ["main.tex"]}))
    (ws / "tables" / "main.tex").write_text("\\begin{tabular}{lc}\nx & y \\\\\nCoef & --- \\\\\n\\end{tabular}\n")
    (ws / "paper_draft.tex").write_text("We find 0.5.\n\\input{tables/main.tex}\n")
    report = verify(ws / "paper_draft.tex", ws)
    assert report.tables_untraced
    assert "hold no number the check can read" in report.untraced_reason


def test_no_rendered_tables_means_nothing_to_flag(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    (ws / "table_render_report.json").write_text(json.dumps({"rendered": []}))
    report = verify(ws / "paper_draft.tex", ws)
    assert not report.tables_untraced and report.untraced_reason == ""


# ── the drafter's contract: what it declares, it includes ─────────────────


def test_the_drafter_contract_catches_declared_tables_the_draft_leaves_out(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    check = check_draft_includes_declared_tables(ws)
    assert not check.ok and check.kind == "verification"
    assert "table_spec.json declares 2 table(s) and the draft includes none of them" in check.reason
    assert "\\input{tables/descriptive_stats.tex}, \\input{tables/main.tex}" in check.reason
    # It is part of the drafter's contract (and no one else's).
    assert check in check_specialist_artifacts(ws, "paper_drafter")
    assert check not in check_specialist_artifacts(ws, "revisor")

    _include_tables(ws)
    assert check_draft_includes_declared_tables(ws).ok


def test_the_drafter_contract_names_the_one_table_left_out(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    draft = ws / "paper_draft.tex"
    draft.write_text(draft.read_text().replace("\\end{document}", "\\input{tables/main}\n\\end{document}"))
    check = check_draft_includes_declared_tables(ws)
    assert not check.ok
    assert "includes 1 of them: add \\input{tables/descriptive_stats.tex}" in check.reason


def test_the_drafter_contract_does_not_apply_without_a_table_spec(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    (ws / "table_spec.json").unlink()
    assert check_draft_includes_declared_tables(ws).ok
    (ws / "table_spec.json").write_text("{broken")
    assert check_draft_includes_declared_tables(ws).ok
    (ws / "table_spec.json").write_text(json.dumps({"tables": []}))
    assert check_draft_includes_declared_tables(ws).ok


# ── the run: stops for the researcher under full, records under contracts/off ──


@pytest.fixture
def events(monkeypatch) -> list[tuple[str, str | None, dict]]:
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    async def _fetch_events(paper_id, *a, **kw):
        return []

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    monkeypatch.setattr("src.db.events.fetch_events", _fetch_events)
    return log


@pytest.fixture
def study(tmp_path: Path, monkeypatch) -> tuple[str, Path]:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "numgate.toml").write_text(TEMPLATE)
    pid = str(uuid.uuid4())
    ws = _copy(tmp_path / "ws")
    (ws / "manifest.json").write_text(json.dumps({"paper_id": pid, "research_question": "Q?"}))
    return pid, ws


async def test_the_run_stops_at_the_number_check_when_no_table_cell_was_traced(study, events):
    pid, ws = study
    backend = _Backend()
    run = _Run()
    out = await run(pid, ws, backend)

    assert out["status"] == "paused" and out["reason"] == "number_check" and out["stage"] == NUMBERS_STEP
    [reason] = out["reasons"]
    assert reason.startswith("the paper includes none of its 2 rendered results table(s)")
    status, error = run.last
    assert status == "paused"
    assert error.startswith("Stopped at the number check: no number in the paper's tables was compared")
    assert "\\input{tables/main.tex}" in error and f"e2er review {pid}" in error
    # Nothing to patch (no mismatched cell), and the reviewers did not run.
    assert "patch_revisor" not in backend.specialist_calls
    assert not [s for s in backend.specialist_calls if s.endswith("_reviewer")]
    state = _state(ws, pid)
    pending = pending_review(ws, state)
    assert pending is not None and (pending.stage, pending.kind) == (NUMBERS_STEP, "numbers")
    assert "paper_draft.tex" in pending.files and "table_spec.json" in pending.files
    check = state.metadata["number_check"]
    assert check["mismatches"] == [] and check["untraced"]["not_in_draft"] == TABLES
    gate = [p for k, s, p in events if k == "gate_enforced" and s == "numbers"]
    assert gate and gate[-1]["passed"] is False and "none of its 2 rendered" in gate[-1]["detail"]
    saved = json.loads((ws / "number_verification.json").read_text())
    assert saved["tables_untraced"] is True


async def test_a_plain_resume_stops_again(study, events):
    pid, ws = study
    run = _Run()
    await run(pid, ws, _Backend())
    out = await run(pid, ws, _Backend())
    assert out.get("reason") == "number_check"


async def test_an_edit_that_includes_the_tables_lets_the_run_finish(study, events):
    pid, ws = study
    run = _Run()
    await run(pid, ws, _Backend())
    text = (ws / "paper_draft.tex").read_text().replace("\\end{document}", INPUTS + "\\end{document}")
    _act(ws, pid, {"action": "edit", "file": "paper_draft.tex", "content": text})
    out = await run(pid, ws, _Backend())
    assert out["status"] == "completed", out
    assert not (ws / "number_check.json").exists()
    saved = json.loads((ws / "number_verification.json").read_text())
    assert saved["tables_untraced"] is False and saved["matched"] == saved["total_values_in_tables"] == 19


async def test_approving_continues_without_the_table_check_and_records_it(study, events):
    pid, ws = study
    backend = _Backend()
    run = _Run()
    await run(pid, ws, backend)

    payload = _act(ws, pid, {"action": "approve"})
    assert payload["decision"] == "numbers_accepted" and payload["mismatches"] == []
    assert payload["untraced"]["rendered_tables"] == TABLES

    out = await run(pid, ws, backend)
    assert out["status"] == "completed", out
    assert len([s for s in backend.specialist_calls if s.endswith("_reviewer")]) == 6
    note = json.loads((ws / "number_check.json").read_text())
    assert note["decision"] == "accepted_by_researcher"
    assert note["untraced"]["not_in_draft"] == TABLES
    assert "compared no table cell with the results" in note["note"]


@pytest.mark.parametrize("regime", ["contracts", "off"])
async def test_under_contracts_or_off_it_is_recorded_and_the_run_continues(study, events, regime):
    from src.core.run_outcome import run_notes

    pid, ws = study
    backend = _Backend()
    run = _Run()
    out = await run(pid, ws, backend, governance=regime)
    assert out["status"] == "completed", out
    note = json.loads((ws / "number_check.json").read_text())
    assert note["decision"] == "recorded_and_continued" and note["governance"] == regime
    assert note["untraced"]["rendered_tables"] == TABLES
    [text] = run_notes(ws)
    assert "compared no table cell" in text and f"governance '{regime}'" in text
    gate = [p for k, s, p in events if k == "gate_shadow" and s == "numbers"]
    assert gate and gate[-1]["passed"] is False


# ── the researcher's view ──────────────────────────────────────────────────


def test_e2er_review_prints_the_untraced_reason():
    from src.cli_review import format_pending

    text = format_pending(
        {
            "pending": {
                "stage": NUMBERS_STEP,
                "kind": "numbers",
                "mismatches": [],
                "untraced": "the paper includes none",
            },
            "files": [],
        }
    )
    assert "Researcher step: number_check (the number check: no table cell was checked)" in text
    assert "compared no table cell with the results files: the paper includes none" in text
    assert "Approve to continue without the table check" in text


def test_e2er_verify_names_why_no_cell_was_traced(tmp_path: Path):
    from src.cli_verify import _check_numbers

    ws = _copy(tmp_path / "ws")
    bundle = tmp_path / "bundle"
    (bundle / "paper").mkdir(parents=True)
    (bundle / "results").mkdir()
    shutil.copy(ws / "paper_draft.tex", bundle / "paper" / "paper.tex")
    shutil.copy(ws / "table_render_report.json", bundle / "results" / "table_render_report.json")
    check = _check_numbers(bundle, ws)
    assert check.status == "FAIL"
    assert check.detail.startswith("0 table cell(s) traced although the paper ships rendered tables: the paper ")
    assert "includes none of its 2 rendered results table(s)" in check.detail
