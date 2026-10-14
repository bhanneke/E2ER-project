"""The recipe pins what pandas loads only when a call needs it, and `e2er reproduce` says when a package is missing.

The live Codex study of 2026-10-14 read an Excel file with ``pandas.read_excel``;
its recipe pinned only the packages the script imports, and the rerun failed with
"Missing optional dependency 'openpyxl'".
"""

from __future__ import annotations

import importlib.metadata as md
import json
import shutil
import sys
from pathlib import Path

import pytest

from src import wrappers
from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core.export import reproduce_recipe as rr
from src.core.script_log import read_script_runs, script_command, script_record

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

EXCEL_STUDY = """\
import json
import pandas as pd

sheet = pd.read_excel("data/sheet.xlsx", sheet_name="Statements")
with open("estimation_results.json", "w") as f:
    json.dump({"mean_x": float(sheet["x"].mean()), "n": int(len(sheet))}, f)
"""


@pytest.fixture
def this_python(monkeypatch):
    """`e2er reproduce` runs the steps with the tests' interpreter instead of a new environment."""

    def make_environment(run_dir, recipe, folder, logs):
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    monkeypatch.setattr(rp, "make_environment", make_environment)


def _excel_study(tmp_path: Path, *, run: bool) -> Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    pd.DataFrame({"x": [1.0, 2.0, 4.5]}).to_excel(ws / "data" / "sheet.xlsx", sheet_name="Statements", index=False)
    (ws / "run_estimation.py").write_text(EXCEL_STUDY, encoding="utf-8")
    if run:
        assert wrappers.run_main(["run_estimation.py"]) == 0
    else:
        (ws / "estimation_results.json").write_text(json.dumps({"mean_x": 2.5, "n": 3}), encoding="utf-8")
    return ws


def _export(ws: Path, out: Path) -> Path:
    """The parts of an export the recipe writer reads: the script, the data, the results."""
    (out / "code").mkdir(parents=True)
    (out / "data").mkdir()
    (out / "results").mkdir()
    shutil.copyfile(ws / "run_estimation.py", out / "code" / "run_estimation.py")
    shutil.copyfile(ws / "data" / "sheet.xlsx", out / "data" / "sheet.xlsx")
    shutil.copyfile(ws / "estimation_results.json", out / "results" / "estimation_results.json")
    return out


def _pins(out: Path) -> dict[str, str]:
    """{name: the whole line} of code/requirements.txt."""
    lines = (out / "code" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {ln.split("==")[0].split()[0]: ln for ln in lines if ln and not ln.startswith("#")}


def test_a_read_excel_study_gets_openpyxl_pinned_and_reproduces(tmp_path: Path, monkeypatch, this_python, capsys):
    monkeypatch.chdir(tmp_path)
    ws = _excel_study(tmp_path, run=False)  # no script log: the pin comes from the call in the script
    monkeypatch.chdir(ws)
    out = _export(ws, tmp_path / "export")
    outcome = rr.write_recipe(ws, out, date_str="20261014")
    assert outcome.recipe, outcome.reason

    pins = _pins(out)
    assert pins["openpyxl"].startswith(f"openpyxl=={md.version('openpyxl')}")
    assert "pandas needs it to read Excel files" in pins["openpyxl"]
    assert pins["pandas"] == f"pandas=={md.version('pandas')}"

    code = reproduce(str(out))
    report = capsys.readouterr().out
    assert code == 0, report


def test_the_script_log_records_what_the_script_loaded_and_the_recipe_pins_it(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    monkeypatch.setenv("E2ER_PYTHON", sys.executable)
    ws = _excel_study(tmp_path, run=True)

    [run] = read_script_runs(ws)
    assert run["python"] == sys.version.split()[0]
    loaded = run["packages"]
    # openpyxl is never imported by the script; pandas loaded it to read the sheet. numpy came with pandas.
    assert loaded["openpyxl"] == md.version("openpyxl")
    assert loaded["pandas"] == md.version("pandas") and "numpy" in loaded
    assert not set(loaded) & {"json", "os", "sys"}, "no standard-library module"

    out = _export(ws, tmp_path / "export")
    rr.write_recipe(ws, out, date_str="20261014")
    pins = _pins(out)
    assert pins["numpy"] == f"numpy=={loaded['numpy']}", "a package the script loaded but never imported is pinned"
    text = (out / "code" / "requirements.txt").read_text(encoding="utf-8")
    assert "every package the scripts loaded when the run ran them" in text


def test_recorded_versions_win_and_a_changed_script_does_not_use_them(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    script = ws / "run_estimation.py"
    script.write_text("import json\n", encoding="utf-8")
    import hashlib

    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    rows = [
        {"script": "run_estimation.py", "sha256": sha, "exit_code": 1, "packages": {"numpy": "0.0.1"}},
        {"script": "run_estimation.py", "sha256": sha, "exit_code": 0, "packages": {"numpy": "1.2.3"}},
        {"script": "run_estimation.py", "sha256": "other", "exit_code": 0, "packages": {"numpy": "9.9.9"}},
    ]
    (ws / ".e2er-script-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert rr.recorded_packages(ws, [script]) == {"numpy": "1.2.3"}
    req = rr.requirements_for([script], set(), ws)
    assert req.lines == ["numpy==1.2.3"] and req.recorded == 1


def test_the_bootstrap_runs_a_script_as_python_would(tmp_path: Path):
    import subprocess

    (tmp_path / "helper.py").write_text("VALUE = 7\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "import sys, helper\n"
        "print(__name__, sys.argv[0].endswith('main.py'), __file__.endswith('main.py'), helper.VALUE)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    argv, extra, packages_file = script_command(sys.executable, tmp_path / "main.py")
    proc = subprocess.run(
        argv, cwd=tmp_path / "..", env={"PATH": "/usr/bin:/bin", **extra}, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 3, proc.stderr
    assert proc.stdout.strip() == "__main__ True True 7", "a sibling module imports, as with `python main.py`"
    assert script_record(packages_file) == {"python": sys.version.split()[0], "packages": {}}
    assert not packages_file.exists()


@pytest.mark.parametrize(
    ("call", "wanted"),
    [
        ("pd.read_excel('a.xlsx')", {"openpyxl"}),
        ("df.to_excel('a.xlsx')", {"openpyxl"}),
        ("pd.read_excel('old.xls')", {"openpyxl", "xlrd"}),
        ("pd.ExcelWriter('a.xlsx', engine='xlsxwriter')", {"openpyxl", "XlsxWriter"}),
        ("pd.read_parquet('a.parquet')", {"pyarrow"}),
        ("pd.read_feather('a.feather')", {"pyarrow"}),
        ("pd.read_xml('a.xml')", {"lxml"}),
        ("pd.read_html('a.html')", {"lxml", "beautifulsoup4", "html5lib"}),
        ("df.to_markdown()", {"tabulate"}),
        ("df.to_latex()", {"jinja2"}),
        ("pd.read_spss('a.sav')", {"pyreadstat"}),
        ("pd.read_stata('a.dta')", set()),
        ("pd.read_sql('select 1', 'postgresql://h/db')", {"SQLAlchemy"}),
        ("pd.read_sql('select 1', sqlite3.connect('data.db'))", set()),
        ("df.plot(); import matplotlib; matplotlib.use('Agg')", set()),
    ],
)
def test_optional_backends_from_pandas_calls(call: str, wanted: set[str]):
    assert set(rr.optional_backends(f"import pandas as pd\nimport sqlite3\ndf = pd.DataFrame()\n{call}\n")) == wanted


def test_no_pandas_no_backends():
    assert rr.optional_backends("import polars as pl\npl.read_excel('a.xlsx')\n") == {}


def test_a_backend_not_installed_is_listed_unpinned_with_a_note(tmp_path: Path, monkeypatch):
    real = md.version

    def version(name: str) -> str:
        if name == "tabulate":
            raise md.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(md, "version", version)
    script = tmp_path / "run_estimation.py"
    script.write_text("import pandas as pd\nprint(pd.DataFrame().to_markdown())\n", encoding="utf-8")
    req = rr.requirements_for([script], set(), tmp_path)
    [line] = [ln for ln in req.lines if ln.startswith("tabulate")]
    assert line.startswith("tabulate  # pandas needs it to write Markdown tables")
    assert "latest compatible release" in line and req.unpinned == ["tabulate"]


EVIDENCE = """\
Traceback (most recent call last):
  File "/tmp/run/.venv/lib/python3.12/site-packages/pandas/compat/_optional.py", line 135, in import_optional_dependency
    module = importlib.import_module(name)
  File "/opt/homebrew/lib/python3.12/importlib/__init__.py", line 90, in import_module
ModuleNotFoundError: No module named 'openpyxl'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/tmp/run/run_estimation.py", line 77, in <module>
    sheet=pd.read_excel(io.BytesIO(workbook),sheet_name='Statements')
  File "/tmp/run/.venv/lib/python3.12/site-packages/pandas/io/excel/_base.py", line 495, in read_excel
  File "/tmp/run/.venv/lib/python3.12/site-packages/pandas/compat/_optional.py", line 138, in import_optional_dependency
    raise ImportError(msg)
ImportError: Missing optional dependency 'openpyxl'.  Use pip or conda to install openpyxl.
"""


def test_the_missing_package_in_plain_words():
    assert rp.missing_dependency(EVIDENCE) == (
        "The recipe does not pin openpyxl, which pandas needs to read and write Excel files (.xlsx)."
    )
    plain = (
        "Traceback (most recent call last):\n"
        '  File "/r/x.py", line 1\n'
        "ModuleNotFoundError: No module named 'sklearn'\n"
    )
    assert rp.missing_dependency(plain) == ("The recipe does not pin scikit-learn, which the study's code imports.")
    assert rp.missing_dependency("ValueError: boom\n") == ""


def test_reproduce_says_which_package_the_recipe_left_out(tmp_path: Path, this_python, capsys):
    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    (folder / "results").mkdir()
    (folder / "code" / "requirements.txt").write_text("pandas\n", encoding="utf-8")
    (folder / "code" / "run_estimation.py").write_text(
        "from pandas.compat._optional import import_optional_dependency\n"
        "import_optional_dependency('e2er_no_such_backend')\n",
        encoding="utf-8",
    )
    (folder / "results" / "estimation_results.json").write_text('{"a": 1}', encoding="utf-8")
    recipe = {
        "schema": rp.SCHEMA,
        "requirements": "code/requirements.txt",
        "files": {"run_estimation.py": "code/run_estimation.py"},
        "steps": [{"run": ["python", "run_estimation.py"]}],
        "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
    }
    (folder / "reproduce.json").write_text(json.dumps(recipe), encoding="utf-8")

    assert reproduce(str(folder)) == 2
    report = capsys.readouterr().out
    sentence = "The recipe does not pin e2er_no_such_backend, which pandas needs."
    assert sentence in report
    assert f"Could not reproduce: the step `python run_estimation.py` failed. {sentence}" in report
    assert "full output: step-1.log, removed with the run folder (--keep keeps it)" in report


def test_the_recipe_names_the_python_the_run_recorded_not_the_exporting_one(tmp_path: Path, monkeypatch):
    """Exported under another interpreter (e2er's 3.14 for a run on 3.12), the recipe keeps the run's 3.12."""
    import hashlib

    ws = _excel_study(tmp_path, run=False)
    sha = hashlib.sha256((ws / "run_estimation.py").read_bytes()).hexdigest()
    rows = [
        {"script": "run_estimation.py", "sha256": sha, "exit_code": 0, "python": "3.11.9", "packages": {}},
        {"script": "run_estimation.py", "sha256": sha, "exit_code": 0, "python": "3.12.12", "packages": {}},
        {"script": "run_estimation.py", "sha256": sha, "exit_code": 1, "python": "3.13.1", "packages": {}},
    ]
    (ws / ".e2er-script-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = _export(ws, tmp_path / "export")
    recipe = rr.write_recipe(ws, out, date_str="20261014").recipe
    assert recipe["python"] == "3.12"
    assert not any("recorded no Python version" in n for n in recipe["notes"])
    assert "(Python 3.12.12)" in (out / "code" / "requirements.txt").read_text(encoding="utf-8")


def test_an_older_run_without_a_record_falls_back_to_the_export_python_with_a_note(tmp_path: Path):
    ws = _excel_study(tmp_path, run=False)
    out = _export(ws, tmp_path / "export")
    recipe = rr.write_recipe(ws, out, date_str="20261014").recipe
    here = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert recipe["python"] == here
    [note] = [n for n in recipe["notes"] if "recorded no Python version" in n]
    assert sys.version.split()[0] in note
    assert "at export; the run recorded none" in (out / "code" / "requirements.txt").read_text(encoding="utf-8")
