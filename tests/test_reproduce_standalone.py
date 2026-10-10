"""Studies reproduce on their own: e2er's read-only queries work in a rerun, the web does not.

The 2026-10-10 Codex run (E2E-01 on 0.15.1) passed `e2er verify` and failed
`e2er reproduce`: its run_estimation.py called `e2er-data query sql` (no run id
in the rerun: exit 2) and read 101 FOMC statements from federalreserve.gov while
it estimated. These tests rebuild that shape in miniature.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core.specialists.contract_check import KIND_RELIABILITY, check_specialist_artifacts
from src.core.specialists.standalone_check import MESSAGE, scan_source

# Like the Codex script: compute in Python, then check the aggregate with e2er's own query tool.
QUERY_SCRIPT = """\
import json, sqlite3, subprocess
con = sqlite3.connect("data.db")
rows = [r[0] for r in con.execute("SELECT return_pp FROM etf_daily_returns ORDER BY session_date")]
mean = sum(rows) / len(rows)
sql = "SELECT AVG(return_pp) AS m, COUNT(*) AS n FROM etf_daily_returns"
check = subprocess.run(["e2er-data", "query", "sql", sql], text=True, capture_output=True, check=True)
q = json.loads(check.stdout)
assert abs(q["rows"][0][0] - mean) < 1e-12, q
json.dump({"main": {"estimate": round(mean, 6), "n": q["rows"][0][1]}}, open("estimation_results.json", "w"))
"""

GET_DATA = """\
import sys
print("data.db: the study's own copy is here, not loaded again")
sys.exit(0)
"""


def _db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE etf_daily_returns (session_date TEXT, return_pp REAL)")
    con.executemany(
        "INSERT INTO etf_daily_returns VALUES (?, ?)", [("2020-01-02", 1.0), ("2020-01-03", 2.0), ("2020-01-06", 4.0)]
    )
    con.commit()
    con.close()


def _study(tmp_path: Path, script: str, published: dict) -> Path:
    """An exported study shaped like the Codex one: data.db at the run folder's root, a reload step first."""
    folder = tmp_path / "study"
    for d in ("code", "results", "data"):
        (folder / d).mkdir(parents=True)
    (folder / "code" / "run_estimation.py").write_text(script, encoding="utf-8")
    (folder / "code" / "get_data.py").write_text(GET_DATA, encoding="utf-8")
    (folder / "code" / "requirements.txt").write_text("# no packages\n", encoding="utf-8")
    _db(folder / "data" / "data.db")
    (folder / "results" / "estimation_results.json").write_text(json.dumps(published), encoding="utf-8")
    sha = hashlib.sha256((folder / "data" / "data.db").read_bytes()).hexdigest()
    recipe = {
        "schema": rp.SCHEMA,
        "requirements": "code/requirements.txt",
        "files": {
            "run_estimation.py": "code/run_estimation.py",
            "data.db": "data/data.db",
            "get_data.py": "code/get_data.py",
        },
        "steps": [
            {"run": ["python", "get_data.py"], "about": "load the inputs the folder does not ship (if any)"},
            {"run": ["python", "run_estimation.py"], "about": "the estimation script"},
        ],
        "inputs": [{"path": "data.db", "sha256": sha, "source": "the study's database", "reload": "get_data.py"}],
        "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
    }
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe), encoding="utf-8")
    return folder


PUBLISHED = {"main": {"estimate": 2.333333, "n": 3}}


# ── e2er's read-only queries work in a rerun ─────────────────────────────────


def test_a_script_that_queries_data_db_with_e2er_data_reproduces(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, QUERY_SCRIPT, PUBLISHED)
    assert reproduce(str(folder)) == 0, capsys.readouterr().out
    text = capsys.readouterr().out
    assert "Reproduced: every compared value is identical" in text
    assert "Inputs, compared with the study's own files (SHA-256):\n  1 of 1 identical" in text


def test_steps_get_the_run_folder_and_no_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-the-study")
    run_dir = tmp_path / "e2er-reproduce-x"
    run_dir.mkdir()
    env = rp.step_env(tmp_path / "venv" / "bin" / "python", run_dir)
    assert env["E2ER_WORKSPACE"] == str(run_dir) and env["E2ER_PAPER_ID"] == run_dir.name
    assert env[rp.REPRODUCE_ENV] == "1"
    assert "OPENAI_API_KEY" not in env


def test_e2er_data_refuses_a_loader_in_a_rerun_step(tmp_path: Path, capsys) -> None:
    script = (
        "import subprocess, sys\n"
        "r = subprocess.run(['e2er-data', 'yfinance', 'history', '--ticker', 'SPY'], capture_output=True, text=True)\n"
        "sys.stderr.write(r.stderr)\n"
        "sys.exit(r.returncode)\n"
    )
    folder = _study(tmp_path, script, PUBLISHED)
    assert reproduce(str(folder)) == 2
    text = capsys.readouterr().out
    assert "FAILED (exit 5)" in text
    assert "called `e2er-data yfinance history`, which loads data from the web" in text
    assert "Could not reproduce: the step `python run_estimation.py` called `e2er-data yfinance history`" in text


# ── no web outside the data step ─────────────────────────────────────────────

WEB_SCRIPT = """\
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    s.connect(("192.0.2.1", 80))  # TEST-NET-1: never answers
except OSError as e:
    if "may not use the network" in str(e):
        raise
finally:
    s.close()
json.dump({"main": {"estimate": 2.333333, "n": 3}}, open("estimation_results.json", "w"))
"""


def test_an_estimation_step_that_reaches_the_web_is_stopped(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, WEB_SCRIPT, PUBLISHED)
    assert reproduce(str(folder)) == 2
    text = capsys.readouterr().out
    assert "this step may not use the network (it tried to reach 192.0.2.1)" in text
    assert (
        "Could not reproduce: the step `python run_estimation.py` tried to reach the web (192.0.2.1), which a rerun "
        "allows only in the step that loads the inputs again." in text
    )
    # the inputs are compared also when a step failed
    assert "Inputs, compared with the study's own files (SHA-256):\n  1 of 1 identical" in text


def test_allow_network_lets_it_through_and_says_so(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, WEB_SCRIPT, PUBLISHED)
    assert reproduce(str(folder), allow_network=True) == 0
    text = capsys.readouterr().out
    assert "It read from the web (allowed with --allow-network): 192.0.2.1." in text
    assert "the study's code read from the web while it ran (192.0.2.1)" in text


def test_the_reload_step_may_use_the_web(tmp_path: Path) -> None:
    recipe = {"steps": [], "inputs": [{"path": "data.db", "sha256": "x", "reload": "get_data.py"}]}
    assert rp.is_reload_step({"run": ["python", "get_data.py"]}, recipe)
    assert not rp.is_reload_step({"run": "python run_estimation.py"}, recipe)


def test_inputs_are_listed_when_the_environment_cannot_be_made(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, QUERY_SCRIPT, PUBLISHED)
    (folder / "code" / "requirements.txt").write_text("this is === not a requirement\n", encoding="utf-8")
    assert reproduce(str(folder)) == 2
    text = capsys.readouterr().out
    assert "error: could not install" in text
    assert "Inputs, compared with the study's own files (SHA-256):\n  1 of 1 identical" in text


def test_a_recipe_without_inputs_says_so(tmp_path: Path) -> None:
    from src.cli_reproduce import render

    recipe = {"requirements": "r.txt", "steps": [{"run": "python x.py"}], "compare": []}
    text = render(Path("s"), recipe, None, [], [], [], None, "v")
    assert (
        "Inputs, compared with the study's own files (SHA-256):\n  the study's reproduce.json lists no inputs" in text
    )


# ── the estimation contract reads the scripts ────────────────────────────────


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("from urllib.request import Request, urlopen\n", "imports urllib.request"),
        ("import requests\n", "imports requests"),
        ("import yfinance as yf\n", "imports yfinance"),
        ("import pandas_datareader.data as web\n", "imports pandas_datareader"),
        ("import pandas as pd\nx = pd.read_csv('https://example.org/a.csv')\n", "reads https://example.org/a.csv"),
        ("import subprocess\nsubprocess.run(['curl', '-s', 'https://x.org'])\n", "runs `curl`"),
        ("import os\nos.system('wget https://x.org/f.csv')\n", "runs `wget`"),
        ("import subprocess\nsubprocess.run(['e2er-data', 'yfinance', 'history'])\n", "runs `e2er-data yfinance"),
        ("import subprocess, os\nsubprocess.run([os.environ['E2ER_DATA'], 'fred', 'series'])\n", "e2er-data fred"),
        ("import subprocess\nsubprocess.run('e2er-run other.py', shell=True)\n", "runs `e2er-run other.py`"),
    ],
)
def test_the_scan_names_web_access_and_e2er_loaders(source: str, found: str) -> None:
    problems = scan_source(source, "run_estimation.py")
    assert problems and found in problems[0], problems
    assert problems[0].startswith("run_estimation.py:")


@pytest.mark.parametrize(
    "source",
    [
        "import sqlite3, pandas as pd\ncon = sqlite3.connect('data.db')\ndf = pd.read_sql('SELECT 1', con)\n",
        "from urllib.parse import urljoin\nimport json\n",
        "import subprocess\nsubprocess.run(['e2er-data', 'query', 'sql', 'SELECT 1'], check=True)\n",
        "import subprocess\nsubprocess.run(['e2er-data', '--paper-id', 'x', 'query', 'tables'])\n",
        "import pandas as pd\ndf = pd.read_csv('data/x.csv')\n",
    ],
)
def test_the_scan_lets_local_reads_and_queries_pass(source: str) -> None:
    assert scan_source(source) == []


def _estimation_workspace(tmp_path: Path, script: str) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "run_estimation.py").write_text(script, encoding="utf-8")
    results = {
        "main": {"coefficients": {"x": {"estimate": 1.0, "se": 0.5, "t_stat": 2.0, "p_value": 0.0455, "df": None}}}
    }
    (ws / "estimation_results.json").write_text(json.dumps(results), encoding="utf-8")
    return ws


def test_an_estimation_script_that_fetches_the_web_fails_the_contract(tmp_path: Path) -> None:
    script = (
        "import json\nfrom urllib.request import urlopen\n"
        "page = urlopen('https://www.federalreserve.gov/x.htm').read()\n"
        "json.dump({}, open('estimation_results.json', 'w'))\n"
    )
    ws = _estimation_workspace(tmp_path, script)
    checks = check_specialist_artifacts(ws, "econometrics_specialist")
    failed = [c for c in checks if not c.ok and MESSAGE[:60] in c.reason]
    assert len(failed) == 1, checks
    assert failed[0].kind == KIND_RELIABILITY
    assert failed[0].reason.startswith(
        "The estimation script must read its data from data.db or files in data/; load web data in the data step"
    )
    assert "run_estimation.py:2: imports urllib.request" in failed[0].reason


def test_a_local_helper_that_fetches_the_web_is_found(tmp_path: Path) -> None:
    ws = _estimation_workspace(
        tmp_path, "import json\nimport helpers\njson.dump({}, open('estimation_results.json','w'))\n"
    )
    (ws / "helpers.py").write_text("import requests\n", encoding="utf-8")
    checks = check_specialist_artifacts(ws, "econometrics_specialist")
    assert any("helpers.py:1: imports requests" in c.reason for c in checks if not c.ok)


def test_an_estimation_script_with_a_read_only_query_passes_that_check(tmp_path: Path) -> None:
    ws = _estimation_workspace(tmp_path, QUERY_SCRIPT)
    checks = check_specialist_artifacts(ws, "econometrics_specialist")
    assert not any(MESSAGE[:60] in c.reason for c in checks)
