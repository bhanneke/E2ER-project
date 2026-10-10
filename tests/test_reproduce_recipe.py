"""reproduce.json written at export from what the run recorded (plan B1), and `e2er reproduce` on the result.

The environment step of `e2er reproduce` (a new virtual environment with the
pinned packages) is replaced here by the interpreter the tests run on, which
has the packages the studies import; everything else runs as it does for a
reader: the run folder, the steps, the value comparison.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core.export import reproduce_recipe as rr
from src.core.export.structured import export_paper
from src.core.secret_scan import find_local_paths
from tests.replay.backend import FIXTURES

FOMC = json.loads((FIXTURES / "fomc" / "scenario.json").read_text(encoding="utf-8"))


@pytest.fixture
def this_python(monkeypatch):
    """`e2er reproduce` runs the steps with the tests' interpreter instead of a new environment."""

    def make_environment(run_dir, recipe, folder, logs):
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    monkeypatch.setattr(rp, "make_environment", make_environment)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fomc_workspace(tmp_path: Path) -> Path:
    """The FOMC replay run's workspace: every recorded file, written in the run's order."""
    ws = tmp_path / "workspaces" / "2026-09-28-fomc"
    ws.mkdir(parents=True)
    pid = "9a623c39-87df-4f46-9d6f-d9dcabc84e7a"
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": pid, "title": FOMC["title"], "research_question": FOMC["research_question"]}),
        encoding="utf-8",
    )
    stamp = 1_759_000_000
    for sp, rec in FOMC["specialists"].items():
        for rel in rec["files"]:
            src = FIXTURES / "fomc" / "files" / sp / rel
            dest = ws / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix in {".db"}:
                shutil.copyfile(src, dest)
            else:
                text = src.read_text(encoding="utf-8")
                dest.write_text(text.replace("@@WORKSPACE@@", str(ws)).replace("@@PAPER_ID@@", pid), encoding="utf-8")
            # Files keep the order the run wrote them in, whatever the file system's clock resolution.
            stamp += 60
            os.utime(dest, (stamp, stamp))
    return ws


def test_the_fomc_replay_export_gets_a_recipe_and_reproduces(tmp_path: Path, this_python, capsys):
    ws = _fomc_workspace(tmp_path)
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    recipe = json.loads((out / "reproduce.json").read_text(encoding="utf-8"))

    assert recipe["schema"] == rp.SCHEMA and recipe["requirements"] == "code/requirements.txt"
    assert [s["run"] for s in recipe["steps"]] == [
        ["python", "get_data.py"],
        ["python", "run_estimation.py"],
        ["python", "revise_estimation.py"],
        ["python", "compute_h2_final.py"],
        ["python", "compute_h2_v2.py"],
    ]
    assert recipe["files"]["run_estimation.py"] == "code/run_estimation.py"
    assert recipe["files"]["compute_h2_v2.py"] == "code/scratch/compute_h2_v2.py"
    assert recipe["files"]["data.db"] == "data/data.db"
    [db] = recipe["inputs"]
    assert db["path"] == "data.db" and db["sha256"] == _sha(ws / "data.db") and db["reload"] == "get_data.py"
    assert "spy_prices (Yahoo Finance" in db["source"] and "dgs2 (FRED" in db["source"]
    published = "results/estimation_results.json"
    assert recipe["compare"] == [{"published": published, "produced": "estimation_results.json"}]
    assert not find_local_paths(recipe), "the recipe names no path of this machine"
    # The recorded run predates the script log: the order comes from file times, and the recipe says so.
    assert recipe["notes"][0].startswith("Order taken from file times")

    pins = (out / "code" / "requirements.txt").read_text(encoding="utf-8")
    for package in ("numpy==", "pandas==", "scipy==", "statsmodels=="):
        assert package in pins
    get_data = (out / "code" / "get_data.py").read_text(encoding="utf-8")
    assert '"--table",\n            "spy_prices"' in get_data and '"--ticker",\n            "SPY"' in get_data
    # the exported estimation script no longer names the run's workspace
    assert str(ws) not in (out / "code" / "run_estimation.py").read_text(encoding="utf-8")
    assert str(ws) in (ws / "run_estimation.py").read_text(encoding="utf-8"), "the workspace is not changed"
    assert "e2er reproduce ." in (out / "README.md").read_text(encoding="utf-8")

    code = reproduce(str(out))
    report = capsys.readouterr().out
    assert code == 0, report
    assert "1 of 1 identical" in report
    # Every one of the 162 values comes back. The last digits of a float depend on the platform's numerical
    # libraries (CI on Linux: 129 identical and 33 the same at the published precision; macOS: all 162
    # identical), so the test asks what e2er promises: none differs beyond the precision the study published.
    m = re.search(
        r"estimation_results\.json: 162 values: (\d+) identical(?:, (\d+) same at the published precision)?\n", report
    )
    assert m and int(m[1]) + int(m[2] or 0) == 162, report
    assert "Reproduced: every compared value is identical" in report
    assert "spy_prices: the study's own copy is here" not in report  # get_data's own output stays in its log


BYOD_SCRIPT = """\
import json
import sqlite3

import numpy as np
import pandas as pd

WS = "{ws}"
con = sqlite3.connect(WS + "/data.db")
panel = pd.read_sql("SELECT firm, year, sales FROM panel ORDER BY firm, year", con)
weights = pd.read_csv("data/weights.csv")
merged = panel.merge(weights, on="firm")
beta = float(np.polyfit(merged["year"], merged["sales"] * merged["weight"], 1)[0])
out = {{"main": {{"coefficients": {{"trend": {{"estimate": round(beta, 6), "p_value": 0.01}}}}, "n": len(merged)}}}}
json.dump(out, open(WS + "/estimation_results.json", "w"))
"""


def _byod_workspace(tmp_path: Path) -> Path:
    """A study on the researcher's own files: a staged CSV (a link into their data folder) and data.db."""
    from src.modules.data.load_record import data_folder_load

    ws = tmp_path / "workspaces" / "2026-10-10-sales"
    (ws / "data").mkdir(parents=True)
    own = tmp_path / "my-data"
    own.mkdir()
    (own / "weights.csv").write_text("firm,weight\na,1.0\nb,0.5\n", encoding="utf-8")
    (ws / "data" / "weights.csv").symlink_to(own / "weights.csv")
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-byod", "title": "Sales"}), encoding="utf-8")
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE panel (firm TEXT, year INT, sales REAL)")
    con.executemany(
        "INSERT INTO panel VALUES (?,?,?)",
        [("a", 2020, 1.0), ("a", 2021, 1.4), ("a", 2022, 2.1), ("b", 2020, 3.0), ("b", 2021, 2.6), ("b", 2022, 2.9)],
    )
    con.commit()
    con.close()
    panel_load = data_folder_load("panel.csv", own / "weights.csv", "2026-10-10T08:00:00Z")
    panel_load.update({"series": "panel.csv", "tables": ["panel"], "files": []})
    weights_load = data_folder_load("weights.csv", own / "weights.csv", "2026-10-10T08:00:00Z")
    (ws / "data_sources.json").write_text(json.dumps({"loads": [panel_load, weights_load]}), encoding="utf-8")
    (ws / "run_estimation.py").write_text(BYOD_SCRIPT.format(ws=ws), encoding="utf-8")
    # The runner runs the script in the workspace (post_execution), as in a real run.
    subprocess.run([sys.executable, "run_estimation.py"], cwd=ws, check=True)
    return ws


def test_a_study_on_the_researchers_own_data_reproduces(tmp_path: Path, this_python, capsys):
    ws = _byod_workspace(tmp_path)
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    recipe = json.loads((out / "reproduce.json").read_text(encoding="utf-8"))

    assert [s["run"] for s in recipe["steps"]] == [["python", "run_estimation.py"]]  # nothing to reload
    assert not any("file times" in n for n in recipe["notes"])  # one script: no order to take from anywhere
    assert not (out / "code" / "get_data.py").exists()
    inputs = {i["path"]: i for i in recipe["inputs"]}
    assert set(inputs) == {"data.db", "data/weights.csv"}
    assert "panel (the researcher's data file panel.csv)" in inputs["data.db"]["source"]
    assert inputs["data/weights.csv"]["source"] == "the researcher's data file weights.csv"
    # the researcher's file, staged as a link, is copied into the folder for the rerun
    assert (out / "data" / "weights.csv").read_text(encoding="utf-8") == "firm,weight\na,1.0\nb,0.5\n"
    assert recipe["files"]["data/weights.csv"] == "data/weights.csv"
    script = (out / "code" / "run_estimation.py").read_text(encoding="utf-8")
    assert str(ws) not in script and 'WS = "."' in script
    assert any("full path" in n for n in recipe["notes"])
    assert not find_local_paths(recipe)

    code = reproduce(str(out))
    report = capsys.readouterr().out
    assert code == 0, report
    assert "2 of 2 identical" in report and "Reproduced:" in report


def test_a_study_without_an_estimation_script_says_why_there_is_no_recipe(tmp_path: Path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-x", "title": "A field map"}), encoding="utf-8")
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"estimate": 1.0}}), encoding="utf-8")
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")

    assert not (out / "reproduce.json").exists()
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "the study has no estimation script: no script of the run writes estimation_results.json" in readme
    assert reproduce(str(out)) == 2
    said = capsys.readouterr().out
    assert "This study has no estimation script: none of its code writes estimation_results.json" in said


def test_a_study_without_estimation_results_says_so(tmp_path: Path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-y", "title": "A field map"}), encoding="utf-8")
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    assert not (out / "reproduce.json").exists()
    assert "the study has no estimation results" in (out / "README.md").read_text(encoding="utf-8")
    assert reproduce(str(out)) == 2
    assert "This study has no estimation results" in capsys.readouterr().out


YAHOO_SCRIPT = """\
import json
import pandas as pd
px = pd.read_csv("data/px_SPY.csv")
json.dump({"main": {"mean": float(px["close"].mean())}}, open("estimation_results.json", "w"))
"""

FAKE_E2ER_DATA = """\
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["FAKE_LOG"])
log.write_text(log.read_text() + " ".join(args) + "\\n" if log.exists() else " ".join(args) + "\\n")
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
target = ws / "data" / args[args.index("--save-to") + 1]
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("date,close\\n2026-01-02,1.0\\n2026-01-03,3.0\\n")
print(json.dumps({"saved_to": str(target), "saved_rows": 2}))
"""


def test_a_yahoo_file_is_not_shipped_and_get_data_loads_it_with_the_recorded_request(tmp_path: Path):
    from src.modules.data.load_record import yfinance_load

    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-y", "title": "SPY"}), encoding="utf-8")
    (ws / "data" / "px_SPY.csv").write_text("date,close\n2026-01-02,1.0\n2026-01-03,3.0\n", encoding="utf-8")
    load = {
        **yfinance_load("SPY", "2026-10-10T08:00:00Z"),
        "saved_to": "data/px_SPY.csv",
        "request": {
            "command": "history",
            "ticker": "SPY",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "interval": "1d",
            "adjusted": True,
        },
    }
    (ws / "data_sources.json").write_text(json.dumps({"loads": [load]}), encoding="utf-8")
    (ws / "run_estimation.py").write_text(YAHOO_SCRIPT, encoding="utf-8")
    subprocess.run([sys.executable, "run_estimation.py"], cwd=ws, check=True)
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    recipe = json.loads((out / "reproduce.json").read_text(encoding="utf-8"))

    [item] = recipe["inputs"]
    assert item["path"] == "data/px_SPY.csv" and item["reload"] == "get_data.py"
    assert "data/px_SPY.csv" not in recipe["files"] and not (out / "data" / "px_SPY.csv").exists()
    assert any(n.startswith("Yahoo Finance's terms allow personal use only") for n in recipe["notes"])
    rp.load_recipe(out)  # a reloaded input may be missing from the folder

    # get_data.py repeats the recorded request when the file is missing, and keeps the study's copy otherwise
    run = tmp_path / "run" / "folder"
    run.mkdir(parents=True)
    shutil.copy(out / "code" / "get_data.py", run / "get_data.py")
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "E2ER_DATA": str(fake), "FAKE_LOG": str(tmp_path / "calls.txt")}
    first = subprocess.run([sys.executable, "get_data.py"], cwd=run, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    calls = (tmp_path / "calls.txt").read_text()
    assert (
        "yfinance history --ticker SPY --interval 1d --start 2026-01-01 --end 2026-01-31 --save-to px_SPY.csv" in calls
    )
    assert (run / "data" / "px_SPY.csv").is_file()
    again = subprocess.run([sys.executable, "get_data.py"], cwd=run, env=env, capture_output=True, text=True)
    assert "the study's own copy is here" in again.stdout
    assert (tmp_path / "calls.txt").read_text() == calls


def test_the_chain_follows_the_order_the_run_changed_the_scripts(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    writes = 'open("estimation_results.json", "w").write("{}")\n'
    for i, name in enumerate(["early_try.py", "run_estimation.py", "zz_fix.py", "aa_patch.py", "notes.py"]):
        (ws / name).write_text(writes if name != "notes.py" else "print(1)\n", encoding="utf-8")
        os.utime(ws / name, (1000 + i, 1000 + i))
    (ws / "estimation_results.json").write_text('{"x": 1}', encoding="utf-8")
    os.utime(ws / "estimation_results.json", (1010, 1010))
    assert [p.name for p in rr.estimation_chain(ws)] == ["run_estimation.py", "zz_fix.py", "aa_patch.py"]


def test_the_yfinance_command_records_its_request(tmp_path: Path, monkeypatch):
    import argparse
    import asyncio

    from src.modules.data import cli

    async def history(self, **kw):
        return {"items": [{"date": "2026-01-02", "close": 1.0}], "source": "yfinance"}

    monkeypatch.setattr("src.modules.data.yfinance_provider.YFinanceProvider.history", history)
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "p-1").mkdir()
    args = argparse.Namespace(
        ticker="SPY",
        start="2026-01-01",
        end="2026-01-31",
        interval="1d",
        raw=False,
        save_to=None,
        table=None,
        paper_id="p-1",
        specialist="data_analyst",
    )
    asyncio.run(cli._run_yf_history(args))
    [load] = json.loads((tmp_path / "p-1" / "data_sources.json").read_text(encoding="utf-8"))["loads"]
    assert load["request"] == {
        "command": "history",
        "ticker": "SPY",
        "start": "2026-01-01",
        "end": "2026-01-31",
        "interval": "1d",
        "adjusted": True,
    }


# ── the order comes from what the run ran, not from file times ──────────────

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "e2er-run"
ORDERED_SCRIPTS = {
    # writes the first results
    "run_estimation.py": 'import json\njson.dump({"main": {"b": 1.0}}, open("estimation_results.json", "w"))\n',
    # a later revision replaces them
    "zz_revise.py": 'import json\njson.dump({"main": {"b": 2.0}}, open("estimation_results.json", "w"))\n',
    # a patch on top of the revision: only right after zz_revise.py
    "aa_patch.py": (
        "import json\nr = json.load(open('estimation_results.json'))\nr['main']['b'] *= 10\n"
        "json.dump(r, open('estimation_results.json', 'w'))\n"
    ),
}


def _ordered_workspace(tmp_path: Path) -> Path:
    """Three scripts run with e2er-run in the order estimation, revision, patch; then the file times are shuffled."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-o", "title": "Order"}), encoding="utf-8")
    for name, code in ORDERED_SCRIPTS.items():
        (ws / name).write_text(code, encoding="utf-8")
    env = {**os.environ, "E2ER_PYTHON": sys.executable}
    for name in ORDERED_SCRIPTS:
        r = subprocess.run(["bash", str(WRAPPER), name], cwd=ws, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert json.loads((ws / "estimation_results.json").read_text())["main"]["b"] == 20.0
    # A copy or checkout resets the times: here the patch looks oldest and the revision newest.
    for name, t in (("aa_patch.py", 1000), ("run_estimation.py", 2000), ("zz_revise.py", 3000)):
        os.utime(ws / name, (t, t))
    os.utime(ws / "estimation_results.json", (3500, 3500))
    return ws


def test_e2er_run_records_every_run_in_the_workspace(tmp_path: Path):
    from src.core.specialists.post_execution import read_script_runs

    ws = _ordered_workspace(tmp_path)
    runs = read_script_runs(ws)
    assert [r["script"] for r in runs] == list(ORDERED_SCRIPTS)
    assert all(r["exit_code"] == 0 and r["by"] == "e2er-run" and len(r["sha256"]) == 64 for r in runs)
    (ws / "bad.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    r = subprocess.run(["bash", str(WRAPPER), "bad.py"], cwd=ws, env={**os.environ, "E2ER_PYTHON": sys.executable})
    assert r.returncode == 3 and read_script_runs(ws)[-1]["exit_code"] == 3  # the exit code is passed on


def test_the_runner_records_the_script_it_runs(tmp_path: Path):
    from src.core.specialists.post_execution import maybe_execute_specialist_script, read_script_runs

    (tmp_path / "run_estimation.py").write_text(ORDERED_SCRIPTS["run_estimation.py"], encoding="utf-8")
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran and attempt.returncode == 0
    [run] = read_script_runs(tmp_path)
    assert run["script"] == "run_estimation.py" and run["by"] == "runner" and run["exit_code"] == 0


def test_the_recipe_follows_the_recorded_order_when_file_times_disagree(tmp_path: Path, this_python, capsys):
    ws = _ordered_workspace(tmp_path)
    assert [p.name for p in rr.chain_of(ws).scripts] == ["run_estimation.py", "zz_revise.py", "aa_patch.py"]
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    recipe = json.loads((out / "reproduce.json").read_text(encoding="utf-8"))
    assert [s["run"][-1] for s in recipe["steps"]] == ["run_estimation.py", "zz_revise.py", "aa_patch.py"]
    assert "in the order the run ran them (its script log)" in recipe["about"]
    assert not any("file times" in n for n in recipe["notes"])
    assert reproduce(str(out)) == 0, capsys.readouterr().out


def test_without_a_script_log_the_recipe_says_the_order_comes_from_file_times(tmp_path: Path):
    ws = _ordered_workspace(tmp_path)
    (ws / ".e2er-script-runs.jsonl").unlink()
    ordered = rr.chain_of(ws)
    assert ordered.order == rr.ORDER_FILE_TIMES
    assert [p.name for p in ordered.scripts] == ["run_estimation.py", "zz_revise.py"]  # what file times can tell
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    recipe = json.loads((out / "reproduce.json").read_text(encoding="utf-8"))
    assert recipe["notes"][0].startswith("Order taken from file times")
    assert "file times; the run recorded no script runs" in recipe["about"]


def test_a_script_changed_after_its_last_run_is_named(tmp_path: Path):
    ws = _ordered_workspace(tmp_path)
    (ws / "aa_patch.py").write_text(ORDERED_SCRIPTS["aa_patch.py"] + "# edited\n", encoding="utf-8")
    assert any("aa_patch.py changed after the run last ran it" in n for n in rr.chain_of(ws).notes)
