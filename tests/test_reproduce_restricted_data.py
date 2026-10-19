"""A study on data whose terms keep it out of the folder reproduces: get_data.py, then the data preparation.

Demo 7 (WHO road deaths, 2026-10-13): without data.db the rerun failed, because
get_data.py reloads only the tables the sources loaded, while the estimation
reads `who_rs198_2021_clean`, a table the data analyst's cleaning script built.
The recipe now runs that script after get_data.py when data.db was not in the
folder, and loads every table of data.db again (Natural Earth's too).

And the Gaia demo (2026-10-13): a reload with the same rows in another order
(ADQL without ORDER BY) was "differs" by SHA-256. Inputs that are tables are
compared by their rows too.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core.export.structured import export_paper
from src.core.specialists.post_execution import _run_recorded

RATES = [("AAA", "COUNTRY", 12.5), ("BBB", "COUNTRY", 3.25), ("CCC", "COUNTRY", None), ("AFR", "REGION", 19.4)]
NAMES = [("AAA", "Avalon"), ("BBB", "Brigadoon"), ("CCC", "Cockaigne")]

CLEAN = """\
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")
con = sqlite3.connect(DB)
con.execute("DROP TABLE IF EXISTS rates_clean")
con.execute(
    "CREATE TABLE rates_clean AS SELECT r.location AS iso3, n.name, r.value FROM rates_raw r "
    "JOIN country_names n ON n.iso3 = r.location WHERE r.spatial_type = 'COUNTRY' AND r.value IS NOT NULL"
)
con.commit()
con.close()
"""

ESTIMATE = """\
import json
import sqlite3

con = sqlite3.connect("data.db")
rows = con.execute("SELECT iso3, value FROM rates_clean ORDER BY iso3").fetchall()
values = [v for _iso3, v in rows]
out = {"main": {"n": len(values), "mean": sum(values) / len(values), "max": max(values)}}
with open("estimation_results.json", "w") as f:
    json.dump(out, f, indent=2)
"""

#: e2er-data as get_data.py calls it: loads the table it is asked for (rows in another order than the study's).
FAKE_E2ER_DATA = """\
import json, os, sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
connector = args[args.index("--specialist") + 2]
table = args[args.index("--table") + 1]
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
con = sqlite3.connect(ws / "data.db")
if connector == "who_gho":
    con.execute(f'CREATE TABLE "{table}" (location TEXT, spatial_type TEXT, value REAL)')
    con.executemany(f'INSERT INTO "{table}" VALUES (?,?,?)', list(reversed(json.loads(os.environ["FAKE_RATES"]))))
else:
    con.execute(f'CREATE TABLE "{table}" (iso3 TEXT, name TEXT)')
    con.executemany(f'INSERT INTO "{table}" VALUES (?,?)', list(reversed(json.loads(os.environ["FAKE_NAMES"]))))
con.commit()
print(json.dumps({"table": table, "rows": con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}))
"""


def _load(connector: str, table: str, request: dict, dataset: str) -> dict:
    return {
        "connector": connector,
        "table": table,
        "request": request,
        "dataset": dataset,
        "series": table,
        "retrieved_at": "2026-10-13T21:10:05Z",
    }


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "2026-10-13-road-deaths"
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-who", "title": "Road deaths"}), encoding="utf-8")
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE rates_raw (location TEXT, spatial_type TEXT, value REAL)")
    con.executemany("INSERT INTO rates_raw VALUES (?,?,?)", RATES)
    con.execute("CREATE TABLE country_names (iso3 TEXT, name TEXT)")
    con.executemany("INSERT INTO country_names VALUES (?,?)", NAMES)
    con.commit()
    con.close()
    loads = [
        _load(
            "who_gho", "rates_raw", {"command": "data", "indicator": "RS_198", "start": "2021", "end": "2021"}, "GHO"
        ),
        _load("naturalearth", "country_names", {"command": "countries", "scale": "50m"}, "Natural Earth"),
    ]
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8")
    # As the run did: the data analyst's cleaning script, then the estimation (both recorded in the script log).
    for name, text in (("clean_rates.py", CLEAN), ("run_estimation.py", ESTIMATE)):
        (ws / name).write_text(text, encoding="utf-8")
        assert _run_recorded(ws, ws / name, 60, by="e2er-run") == 0
    return ws


@pytest.fixture
def rerun_here(monkeypatch, tmp_path):
    """`e2er reproduce` with the tests' interpreter and an e2er-data that loads the tables offline."""
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)

    def make_environment(run_dir, recipe, folder, logs):
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    real_step_env = rp.step_env

    def step_env(venv_python, run_dir=None):
        env = real_step_env(venv_python, run_dir)
        env.update({"E2ER_DATA": str(fake), "FAKE_RATES": json.dumps(RATES), "FAKE_NAMES": json.dumps(NAMES)})
        return env

    monkeypatch.setattr(rp, "make_environment", make_environment)
    monkeypatch.setattr(rp, "step_env", step_env)


def test_the_recipe_runs_the_data_preparation_after_get_data(tmp_path: Path):
    ws = _workspace(tmp_path)
    out = export_paper(ws, tmp_path / "exports", date_str="20261014")
    recipe = json.loads((out / "reproduce.json").read_text(encoding="utf-8"))
    assert [s["run"] for s in recipe["steps"]] == [
        ["python", "get_data.py"],
        ["python", "clean_rates.py"],
        ["python", "run_estimation.py"],
    ]
    assert recipe["steps"][1]["when_missing"] == ["data.db"]
    assert recipe["files"]["clean_rates.py"].endswith("clean_rates.py")
    assert any("clean_rates.py builds the tables the estimation reads (rates_clean)" in n for n in recipe["notes"])
    get_data = (out / "code" / "get_data.py").read_text(encoding="utf-8")
    # Every table a source loaded comes back, Natural Earth's too; nothing is left that cannot be rebuilt.
    assert '"table": "rates_raw"' in get_data and '"table": "country_names"' in get_data
    assert "OTHER_TABLES = []" in get_data
    [db] = recipe["inputs"]
    assert set(db["tables"]) == {"rates_raw", "country_names", "rates_clean"}


def test_a_study_shipped_without_its_restricted_data_reproduces(tmp_path: Path, rerun_here, capsys):
    ws = _workspace(tmp_path)
    out = export_paper(ws, tmp_path / "exports", date_str="20261014")
    (out / "data" / "data.db").unlink()  # the WHO's terms: the published folder leaves the data out
    code = reproduce(str(out))
    report = capsys.readouterr().out
    assert code == 0, report
    assert "2. python clean_rates.py (data preparation" in report and "done" in report
    # The reloaded rows came back in another order: the same content, not a difference.
    assert "1 with the same rows in a different order (identical content): data.db" in report
    assert "Reproduced: every compared value is identical" in report


def test_with_its_data_the_preparation_does_not_run_again(tmp_path: Path, rerun_here, capsys):
    ws = _workspace(tmp_path)
    out = export_paper(ws, tmp_path / "exports", date_str="20261014")
    code = reproduce(str(out))
    report = capsys.readouterr().out
    assert code == 0, report
    assert (
        "2. python clean_rates.py (data preparation: builds the study's tables from the loaded ones): not run, "
        "the folder has data.db" in report
    )
    assert "1 of 1 identical" in report and "different order" not in report


# ── inputs compared by content ──────────────────────────────────────────────


def _csv(path: Path, rows: list[str]) -> Path:
    path.write_text("ra,dec,parallax\n" + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def test_a_csv_with_the_same_rows_in_another_order_has_the_same_content(tmp_path: Path):
    rows = ["56.75,24.12,7.3", "56.80,24.00,7.4", "57.01,23.90,7.2"]
    a = _csv(tmp_path / "a.csv", rows)
    b = _csv(tmp_path / "b.csv", list(reversed(rows)))
    c = _csv(tmp_path / "c.csv", [*rows[:2], "57.01,23.90,7.9"])
    fa, fb, fc = (rp.content_fingerprint(p) for p in (a, b, c))
    assert fa == fb and fa["rows"] == 3
    assert fa != fc
    run = tmp_path / "run"
    (run / "data").mkdir(parents=True)
    item = {"path": "data/gaia_dr3.csv", "sha256": rp.sha256_file(a), **fa}
    (run / "data" / "gaia_dr3.csv").write_bytes(b.read_bytes())
    [same] = rp.compare_inputs(run, [item])
    assert same["status"] == rp.SAME_ROWS
    (run / "data" / "gaia_dr3.csv").write_bytes(c.read_bytes())
    [other] = rp.compare_inputs(run, [item])
    assert other["status"] == "differs"
    # A recipe from before content fingerprints compares by SHA-256 alone.
    (run / "data" / "gaia_dr3.csv").write_bytes(b.read_bytes())
    [old] = rp.compare_inputs(run, [{"path": "data/gaia_dr3.csv", "sha256": rp.sha256_file(a)}])
    assert old["status"] == "differs"


def test_a_database_names_the_tables_that_differ(tmp_path: Path):
    def db(path: Path, values: list[tuple]) -> Path:
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE t (k TEXT, v REAL)")
        con.execute("CREATE TABLE u (k TEXT)")
        con.executemany("INSERT INTO t VALUES (?,?)", values)
        con.execute("INSERT INTO u VALUES ('x')")
        con.commit()
        con.close()
        return path

    study = db(tmp_path / "study.db", [("a", 1.0), ("b", 2.0)])
    run = tmp_path / "run"
    run.mkdir()
    item = {"path": "data.db", "sha256": rp.sha256_file(study), **rp.content_fingerprint(study)}
    db(run / "data.db", [("b", 2.0), ("a", 1.0)])
    assert rp.compare_inputs(run, [item])[0]["status"] == rp.SAME_ROWS
    os.remove(run / "data.db")
    db(run / "data.db", [("a", 1.0), ("b", 2.5)])
    [found] = rp.compare_inputs(run, [item])
    assert found["status"] == "differs" and found["tables_differ"] == ["t"]


def test_the_verdict_counts_the_same_rows_as_the_studys_input():
    inputs = [{"path": "data/gaia_dr3.csv", "status": rp.SAME_ROWS}]
    fc = rp.FileComparison("results/estimation_results.json", "estimation_results.json")
    fc.counts[rp.IDENTICAL] = 3
    text, code = rp.verdict([fc], None, [], inputs)
    assert code == 0 and text.startswith("Reproduced")


# ── numbers equal to 12 significant digits (the Gaia demo's rebuilt gaia_clean.csv, 2026-10-15) ──────────────


def test_a_rebuilt_csv_whose_numbers_differ_in_the_last_digits_has_the_same_numbers(tmp_path: Path):
    """pandas wrote -0.0005179820886653808 in the run and -0.0005179820886653 in the rerun, from the same rows."""
    rows = ["70198148077311360,55.48074268072565,-0.0005179820886653808", "63324452353258240,56.878,7.25"]
    study = _csv(tmp_path / "study.csv", rows)
    item = {"path": "data/gaia_clean.csv", "sha256": rp.sha256_file(study), **rp.content_fingerprint(study)}
    assert set(item) >= {"rows", "content_sha256", "numeric_sha256"}
    run = tmp_path / "run"
    (run / "data").mkdir(parents=True)
    _csv(run / "data" / "gaia_clean.csv", [rows[1], "70198148077311360,55.48074268072565,-0.0005179820886653"])
    [close] = rp.compare_inputs(run, [item])
    assert close["status"] == rp.SAME_NUMBERS
    # A change a reader could see is a difference: the 7th significant digit.
    _csv(run / "data" / "gaia_clean.csv", [rows[1], "70198148077311360,55.48074268072565,-0.0005179830886653"])
    assert rp.compare_inputs(run, [item])[0]["status"] == "differs"
    # Integers (a Gaia source_id) are never rounded: one digit off is a different row.
    _csv(run / "data" / "gaia_clean.csv", [rows[1], "70198148077311361,55.48074268072565,-0.0005179820886653808"])
    assert rp.compare_inputs(run, [item])[0]["status"] == "differs"
    # A recipe without the numbers fingerprint compares rows exactly.
    old = {k: v for k, v in item.items() if k != "numeric_sha256"}
    _csv(run / "data" / "gaia_clean.csv", [rows[1], "70198148077311360,55.48074268072565,-0.0005179820886653"])
    assert rp.compare_inputs(run, [old])[0]["status"] == "differs"


def test_the_verdict_counts_numbers_equal_to_12_digits_and_says_so():
    inputs = [{"path": "data/gaia_clean.csv", "status": rp.SAME_NUMBERS}]
    fc = rp.FileComparison("results/estimation_results.json", "estimation_results.json")
    fc.counts[rp.IDENTICAL] = 3
    text, code = rp.verdict([fc], None, [], inputs)
    assert code == 0 and text.startswith("Reproduced")
    assert "data/gaia_clean.csv has the study's rows with every decimal number equal to 12 significant digits" in text


def test_an_older_recipe_takes_the_numbers_fingerprint_only_from_a_record_of_the_same_file():
    recipe = {
        "files": {"data.db": "data/data.db"},
        "inputs": [
            {"path": "data/gaia_clean.csv", "sha256": "a" * 64, "content_sha256": "c1"},
            {"path": "data.db", "sha256": "b" * 64, "tables": {"t": {"rows": 1, "content_sha256": "t1"}}},
            {"path": "data/other.csv", "sha256": "d" * 64, "content_sha256": "o1"},
        ],
    }
    recorded = {
        "data/gaia_clean.csv": {"rows": 2, "content_sha256": "c1", "numeric_sha256": "n1"},
        "data/data.db": {"tables": {"t": {"rows": 1, "content_sha256": "t1", "numeric_sha256": "tn"}}},
        "data/other.csv": {"rows": 2, "content_sha256": "NOT THE RECIPE'S", "numeric_sha256": "planted"},
    }
    assert rp.add_numeric_fingerprints(recipe, recorded) == ["data/gaia_clean.csv", "data.db"]
    gaia, db, other = recipe["inputs"]
    assert gaia["numeric_sha256"] == "n1" and db["tables"]["t"]["numeric_sha256"] == "tn"
    assert "numeric_sha256" not in other


def test_the_package_names_what_a_rerun_loads_and_what_the_studys_steps_build(tmp_path: Path, monkeypatch):
    from src.core.export import package as pkg

    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    out = export_paper(_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    packed = pkg.build(out, tmp_path / "who.e2er")
    [item] = packed.manifest["left_out"]
    assert item["path"] == "data/data.db"
    assert item["loads"] == ["country_names", "rates_raw"]
    assert [b["what"] for b in item["builds"]] == [["rates_clean"]]
    words = pkg.rerun_words(item)
    assert words.startswith("`e2er reproduce` loads the tables country_names, rates_raw again from the sources with ")
    assert "code/get_data.py; builds the tables rates_clean again with code/" in words and "clean_rates.py" in words
    assert "made by the study" not in words
    assert set(item["content"]["tables"]) == {"rates_raw", "country_names", "rates_clean"}
    # In an unpacked folder the record counts only for files the folder's own records restrict.
    folder = pkg.open_package(packed.path, tmp_path / "clone").root
    assert set(pkg.left_out_content(folder)) == {"data/data.db"}
    doc = json.loads((folder / pkg.MANIFEST).read_text(encoding="utf-8"))
    doc["left_out"].append({"path": "data/own.csv", "reason": "planted", "content": {"content_sha256": "x"}})
    (folder / pkg.MANIFEST).write_text(json.dumps(doc), encoding="utf-8")
    assert set(pkg.left_out_content(folder)) == {"data/data.db"}
    assert "data/own.csv" in pkg.left_out_content(folder, trusted=True)


def test_an_unpacked_package_without_its_restricted_data_reproduces(tmp_path: Path, rerun_here, monkeypatch, capsys):
    """The folder a GitHub repository holds (e2er publish --github) is an unpacked package: it reproduces too."""
    from src.core.export import package as pkg

    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    out = export_paper(_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    folder = pkg.open_package(pkg.build(out, tmp_path / "who.e2er").path, tmp_path / "clone").root
    assert not (folder / "data" / "data.db").exists()
    code = reproduce(str(folder))
    report = capsys.readouterr().out
    assert code == 0, report
    assert "2. python clean_rates.py (data preparation" in report
    assert "Reproduced: every compared value is identical" in report
