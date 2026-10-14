"""The results files are the output of the shipped estimation script (script log + estimation contract).

The demo case (2026-10-14, earthquake study on DeepSeek V4 Pro via OpenRouter):
the specialist wrote ``run_estimation.py`` at 01:18 and ``estimation_results.json``
by hand at 02:01; no run of the script was recorded, and a rerun of the shipped
script gave 289 different values. Nothing checked it before the draft.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.core.script_log import (
    FROM_CODE,
    NOT_FROM_CODE,
    NOT_RECORDED,
    SCRIPT_RUNS,
    output_snapshot,
    read_script_runs,
    record_script_run,
    results_from_code,
)
from src.core.specialists.contract_check import check_results_from_code
from src.core.specialists.post_execution import RERUN_RECORD, _run_recorded, confirm_results_from_code

SCRIPT = """
import json
counts = [3, 5, 8, 13]
out = {"main": {"n": len(counts), "mean": sum(counts) / len(counts), "b_value": 1.02}}
with open("estimation_results.json", "w") as f:
    json.dump(out, f, indent=2)
"""


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "run_estimation.py").write_text(SCRIPT, encoding="utf-8")
    return ws


def _run(ws: Path) -> int | None:
    return _run_recorded(ws, ws / "run_estimation.py", 60, by="test")


def test_the_script_log_records_the_files_a_run_wrote(tmp_path):
    ws = _ws(tmp_path)
    (ws / "untouched.json").write_text("{}", encoding="utf-8")
    assert _run(ws) == 0
    (row,) = read_script_runs(ws)
    assert set(row["outputs"]) == {"estimation_results.json"}  # the file it did not write is not listed
    assert len(row["outputs"]["estimation_results.json"]) == 64


def test_record_without_a_snapshot_keeps_the_old_line_shape(tmp_path):
    ws = _ws(tmp_path)
    record_script_run(ws, "run_estimation.py", "2026-10-14T00:00:00Z", 0, by="test")
    (row,) = read_script_runs(ws)
    assert "outputs" not in row


def test_results_written_by_the_shipped_script_are_from_code(tmp_path):
    ws = _ws(tmp_path)
    _run(ws)
    assert results_from_code(ws, "estimation_results.json")[0] == FROM_CODE
    assert all(c.ok for c in check_results_from_code(ws, "econometrics_specialist"))


def test_a_results_file_edited_after_the_run_is_not_from_code(tmp_path):
    ws = _ws(tmp_path)
    _run(ws)
    data = json.loads((ws / "estimation_results.json").read_text())
    data["main"]["b_value"] = 0.87
    (ws / "estimation_results.json").write_text(json.dumps(data), encoding="utf-8")
    outcome, why, _ = results_from_code(ws, "estimation_results.json")
    assert outcome == NOT_FROM_CODE
    assert "changed after run_estimation.py last wrote it" in why


def test_a_script_changed_after_the_run_is_not_the_shipped_one(tmp_path):
    ws = _ws(tmp_path)
    _run(ws)
    (ws / "run_estimation.py").write_text(SCRIPT.replace("1.02", "1.10"), encoding="utf-8")
    outcome, why, _ = results_from_code(ws, "estimation_results.json")
    assert outcome == NOT_FROM_CODE and "changed after the run" in why


def test_a_failed_run_that_wrote_the_file_does_not_count(tmp_path):
    ws = _ws(tmp_path)
    (ws / "run_estimation.py").write_text(SCRIPT + "\nraise SystemExit(3)\n", encoding="utf-8")
    assert _run(ws) == 3
    outcome, why, _ = results_from_code(ws, "estimation_results.json")
    assert outcome == NOT_FROM_CODE and "failed" in why


def test_runs_from_before_output_records_say_nothing(tmp_path):
    ws = _ws(tmp_path)
    (ws / "estimation_results.json").write_text('{"main": {"n": 4}}', encoding="utf-8")
    line = {"script": "run_estimation.py", "sha256": "x", "started_at": "t", "exit_code": 0, "by": "e2er-run"}
    (ws / SCRIPT_RUNS).write_text(json.dumps(line) + "\n", encoding="utf-8")
    assert results_from_code(ws, "estimation_results.json")[0] == NOT_RECORDED
    assert all(c.ok for c in check_results_from_code(ws, "econometrics_specialist"))


def test_the_demo_case_hand_written_results_fail_the_estimation_contract(tmp_path):
    """No recorded run, results written by hand: the runner runs the shipped script, which writes other values."""
    ws = _ws(tmp_path)
    hand = {"main": {"n": 4, "mean": 7.25, "b_value": 0.87}}  # the specialist's own numbers
    (ws / "estimation_results.json").write_text(json.dumps(hand), encoding="utf-8")
    record = confirm_results_from_code(ws, "econometrics_specialist")
    assert record["estimation_results.json"]["same"] is False
    assert record["estimation_results.json"]["differ"] == 1
    # The file is put back as the specialist left it (the evidence), and the contract fails with plain feedback.
    assert json.loads((ws / "estimation_results.json").read_text()) == hand
    (failed,) = [c for c in check_results_from_code(ws, "econometrics_specialist") if not c.ok]
    assert failed.kind == "reliability"
    assert failed.reason.startswith("estimation_results.json was not written by run_estimation.py as shipped")
    assert "change the script and run it" in failed.reason
    assert "writes 1 of 3 values differently" in failed.reason
    assert (ws / RERUN_RECORD).is_file()


def test_the_rerun_confirms_results_of_a_script_run_outside_the_log(tmp_path):
    """A CLI that ran `python run_estimation.py` itself (no script log): the runner's rerun writes the same."""
    import subprocess

    ws = _ws(tmp_path)
    subprocess.run([sys.executable, "run_estimation.py"], cwd=ws, check=True)
    assert results_from_code(ws, "estimation_results.json")[0] == NOT_RECORDED
    record = confirm_results_from_code(ws, "econometrics_specialist")
    assert record["estimation_results.json"]["same"] is True
    assert results_from_code(ws, "estimation_results.json")[0] == FROM_CODE
    assert all(c.ok for c in check_results_from_code(ws, "econometrics_specialist"))


def test_results_traced_to_the_last_run_need_no_rerun(tmp_path):
    ws = _ws(tmp_path)
    _run(ws)
    assert confirm_results_from_code(ws, "econometrics_specialist") == {}
    assert len(read_script_runs(ws)) == 1


def test_robustness_results_written_by_hand_fail_too(tmp_path):
    ws = _ws(tmp_path)
    _run(ws)
    (ws / "robustness_results.json").write_text('{"alt": {"b_value": 0.9}}', encoding="utf-8")
    confirm_results_from_code(ws, "econometrics_specialist")
    failed = [c for c in check_results_from_code(ws, "econometrics_specialist") if not c.ok]
    assert [c.artifact for c in failed] == ["robustness_results.json"]
    assert "does not write it" in failed[0].reason


def test_e2er_run_records_outputs(tmp_path, monkeypatch):
    from src.wrappers import run_main

    ws = _ws(tmp_path)
    monkeypatch.chdir(ws)
    monkeypatch.setenv("E2ER_PYTHON", sys.executable)
    assert run_main(["run_estimation.py"]) == 0
    (row,) = read_script_runs(ws)
    assert row["by"] == "e2er-run" and "estimation_results.json" in row["outputs"]
    assert output_snapshot(ws)["estimation_results.json"][1] > 0


# ── e2er verify: "results from code" from the record export puts in provenance.json ──


def _bundle(tmp_path: Path, ws: Path) -> Path:
    import shutil

    from src.core.export.provenance import results_code_record, write_provenance

    out = tmp_path / "bundle"
    (out / "results").mkdir(parents=True)
    (out / "code").mkdir()
    shutil.copy2(ws / "estimation_results.json", out / "results" / "estimation_results.json")
    shutil.copy2(ws / "run_estimation.py", out / "code" / "run_estimation.py")
    write_provenance(out, {}, exported_at="2026-10-14", results_from_code=results_code_record(ws, out))
    return out


def test_verify_passes_results_written_by_the_shipped_script(tmp_path):
    from src.cli_verify import PASS, _check_results_from_code

    ws = _ws(tmp_path)
    _run(ws)
    check = _check_results_from_code(_bundle(tmp_path, ws))
    assert check is not None and check.status == PASS
    assert "estimation_results.json ← run_estimation.py" in check.detail


def test_verify_fails_the_demo_case(tmp_path):
    """The run recorded its script's output; the results file was edited afterwards (the export ships the edit)."""
    from src.cli_verify import FAIL, _check_results_from_code

    ws = _ws(tmp_path)
    _run(ws)
    (ws / "estimation_results.json").write_text('{"main": {"n": 4, "b_value": 0.87}}', encoding="utf-8")
    check = _check_results_from_code(_bundle(tmp_path, ws))
    assert check is not None and check.status == FAIL
    assert "not the file run_estimation.py wrote" in check.detail


def test_verify_fails_a_results_file_swapped_in_the_folder(tmp_path):
    from src.cli_verify import FAIL, _check_results_from_code

    ws = _ws(tmp_path)
    _run(ws)
    bundle = _bundle(tmp_path, ws)
    (bundle / "results" / "estimation_results.json").write_text('{"main": {"n": 5}}', encoding="utf-8")
    check = _check_results_from_code(bundle)
    assert check is not None and check.status == FAIL


def test_verify_without_a_record_has_no_such_check(tmp_path):
    from src.cli_verify import _check_results_from_code

    ws = _ws(tmp_path)
    (ws / "estimation_results.json").write_text('{"main": {"n": 4}}', encoding="utf-8")  # no script log at all
    assert _check_results_from_code(_bundle(tmp_path, ws)) is None
