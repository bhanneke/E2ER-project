"""The script log counts only the lines e2er wrote (review of 2026-11-21, finding 4).

One line the model wrote into ``.e2er-script-runs.jsonl`` without ``outputs`` made every results
file "predate output records", and the results-from-code contract accepted numbers typed by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.core import script_log
from src.core.script_log import (
    FROM_CODE,
    NOT_FROM_CODE,
    NOT_RECORDED,
    PREDATES,
    SCRIPT_RUNS,
    adopt,
    output_snapshot,
    read_script_runs,
    record_script_run,
    results_from_code,
)
from src.core.specialists.contract_check import check_results_from_code


def _forge(ws: Path, row: dict) -> None:
    with open(ws / SCRIPT_RUNS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _study(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "estimation_results.json").write_text('{"beta": 0.42}', encoding="utf-8")  # typed by hand
    (ws / "run_estimation.py").write_text("print('hi')\n", encoding="utf-8")
    return ws


def test_forged_line_without_outputs_no_longer_passes(tmp_path):
    ws = _study(tmp_path)
    adopt(ws)  # the runner adopts the workspace before any model step
    _forge(ws, {"script": "run_estimation.py", "sha256": "x", "started_at": "2020-01-01T00:00:00Z", "exit_code": 0})
    assert read_script_runs(ws) == []
    outcome, why, _ = results_from_code(ws, "estimation_results.json")
    assert (outcome, why) != (NOT_RECORDED, PREDATES)
    # The runner's rerun of the script (signed) does not write the file: the contract fails.
    record_script_run(ws, "run_estimation.py", "2026-11-21T00:00:00Z", 0, by="runner", before=output_snapshot(ws))
    checks = check_results_from_code(ws, "econometrics_specialist")
    assert checks and not any(c.ok for c in checks)


def test_forged_line_with_a_made_up_mac_is_ignored(tmp_path):
    ws = _study(tmp_path)
    adopt(ws)
    _forge(ws, {"script": "run_estimation.py", "exit_code": 0, "outputs": {}, "mac": "0" * 64})
    assert read_script_runs(ws) == []


def test_lines_e2er_writes_are_signed_and_count(tmp_path):
    ws = _study(tmp_path)
    adopt(ws)
    before = output_snapshot(ws)
    (ws / "estimation_results.json").write_text('{"beta": 0.5}', encoding="utf-8")
    record_script_run(ws, "run_estimation.py", "2026-11-21T00:00:00Z", 0, by="e2er-run", before=before)
    raw = json.loads((ws / SCRIPT_RUNS).read_text(encoding="utf-8").splitlines()[-1])
    assert len(raw["mac"]) == 64
    runs = read_script_runs(ws)
    assert len(runs) == 1 and runs[0]["signed"] is True
    assert results_from_code(ws, "estimation_results.json")[0] == FROM_CODE
    # An edited signed line no longer counts.
    raw["exit_code"] = 0
    raw["outputs"]["estimation_results.json"] = "f" * 64
    (ws / SCRIPT_RUNS).write_text(json.dumps(raw) + "\n", encoding="utf-8")
    assert read_script_runs(ws) == []


def test_older_lines_count_when_adopted(tmp_path):
    """A study resumed after an update: its unsigned lines from before still count, later ones do not."""
    ws = _study(tmp_path)
    _forge(ws, {"script": "run_estimation.py", "sha256": "x", "started_at": "2025-01-01T00:00:00Z", "exit_code": 0})
    adopt(ws)
    assert len(read_script_runs(ws)) == 1
    assert results_from_code(ws, "estimation_results.json")[:2] == (NOT_RECORDED, PREDATES)
    _forge(ws, {"script": "run_estimation.py", "exit_code": 0})
    assert len(read_script_runs(ws)) == 1


def test_predates_needs_the_script(tmp_path):
    """An older line naming a script the study does not have is no reason to accept a results file."""
    ws = _study(tmp_path)
    (ws / "run_estimation.py").unlink()
    _forge(ws, {"script": "gone.py", "sha256": "x", "started_at": "2025-01-01T00:00:00Z", "exit_code": 0})
    outcome, _, _ = results_from_code(ws, "estimation_results.json")
    assert outcome == NOT_FROM_CODE


def test_never_adopted_log_reads_as_before(tmp_path):
    """A study this e2er never ran (exported or checked now): its unsigned lines all count, as before."""
    ws = _study(tmp_path)
    _forge(ws, {"script": "run_estimation.py", "exit_code": 0})
    assert len(read_script_runs(ws)) == 1


def test_adoption_record_is_outside_the_workspace(tmp_path):
    ws = _study(tmp_path)
    adopt(ws)
    assert not any(p.name.startswith(".e2er-script") and p.suffix == ".json" for p in ws.iterdir())
    assert script_log.key_file().is_file()
    if sys.platform != "win32":  # Windows has no Unix permission bits; the key sits in the user's own folder
        assert (script_log.key_file().stat().st_mode & 0o077) == 0
