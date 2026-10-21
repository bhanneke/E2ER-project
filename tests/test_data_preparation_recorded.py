"""Export records a study's whole data preparation, so a folder without data.db can be run again.

The weather-words demo (2026-10-21): its 145 MB data.db is too large for GitHub, and `e2er publish --github`
refused to leave it out because nothing in reproduce.json got it back. Three gaps: export wrote no step that
loads an open source again (Project Gutenberg); the tables the estimation reads (corpus, …) were written by
build_data.py with ``t.to_sql(name, con)``, a name the code computes, which table detection missed, so no step
built them again; and build_data.py read data/sample_ids_v2.csv, made by a seeded draw script, which the folder
did not ship.

Now the script log records the tables each run writes (the database before and after the run), export maps
every table of data.db to its writer (reproduce.json ``database``), records the scripts that built the tables
as steps in run order, lists the open sources' loads in get_data.py, and ships the small files those steps read
together with the scripts that made them.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core import script_log as sl
from src.core.export import package as pkg
from src.core.export import reproduce_recipe as rr
from src.core.export.structured import export_paper
from src.core.specialists.post_execution import _run_recorded

TEXTS = {"texts_c1": [(1, "Rain fell. Fog rose."), (2, "Wind and storm.")], "texts_c2": [(3, "Snow, sun, cloud.")]}

DRAW = """\
import csv
import random

random.seed(20261014)
ids = [1, 2, 3]
random.shuffle(ids)
with open("data/sample_ids.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "draw_rank"])
    for rank, i in enumerate(ids, 1):
        w.writerow([i, rank])
"""

# Writes its tables with a name the code computes (as build_data.py of the weather-words study does).
BUILD = """\
import csv
import sqlite3

import pandas as pd

con = sqlite3.connect("data.db")
frames = [pd.read_sql(f"select id, text from texts_{c}", con) for c in ["c1", "c2"]]
texts = pd.concat(frames, ignore_index=True)
ranks = {int(r["id"]): int(r["draw_rank"]) for r in csv.DictReader(open("data/sample_ids.csv"))}
texts["draw_rank"] = texts["id"].map(ranks)
texts["n_words"] = texts["text"].str.split().str.len()
counts = texts.groupby(texts["id"] > 2).n_words.sum().reset_index(name="words")
for name, t in [("corpus", texts), ("corpus_counts", counts)]:
    t.to_sql(name, con, if_exists="replace", index=False)
con.commit()
"""

ESTIMATE = """\
import json
import sqlite3

con = sqlite3.connect("data.db")
rows = con.execute("SELECT id, n_words, draw_rank FROM corpus ORDER BY draw_rank").fetchall()
total = con.execute("SELECT SUM(words) FROM corpus_counts").fetchone()[0]
out = {"main": {"n_docs": len(rows), "words": total, "first_drawn": rows[0][0]}}
with open("estimation_results.json", "w") as f:
    json.dump(out, f, indent=2)
"""

#: e2er-data as get_data.py calls it: loads the Gutenberg texts it is asked for, offline.
FAKE_E2ER_DATA = """\
import json, os, sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
table = args[args.index("--table") + 1]
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\\n")
con = sqlite3.connect(ws / "data.db")
con.execute(f'CREATE TABLE "{table}" (id INTEGER, text TEXT)')
con.executemany(f'INSERT INTO "{table}" VALUES (?,?)', json.loads(os.environ["FAKE_TEXTS"])[table])
con.commit()
print(json.dumps({"table": table}))
"""


def _load(connector: str, table: str, request: dict, when: str) -> dict:
    return {
        "connector": connector,
        "table": table,
        "dataset": "Project Gutenberg ebooks",
        "series": table,
        "request": request,
        "retrieved_at": when,
    }


def _workspace(tmp_path: Path) -> Path:
    """A finished text study: Gutenberg texts and a catalogue loaded, a seeded draw, the corpus built, estimated."""
    ws = tmp_path / "workspaces" / "2026-10-14-weather"
    (ws / "data").mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-weather", "title": "Weather words"}), "utf-8")
    con = sqlite3.connect(ws / "data.db")
    for table, rows in TEXTS.items():
        con.execute(f"CREATE TABLE {table} (id INTEGER, text TEXT)")
        con.executemany(f"INSERT INTO {table} VALUES (?,?)", rows)
    con.execute("CREATE TABLE books (id INTEGER, title TEXT)")  # the catalogue: loaded, read by no step
    con.executemany("INSERT INTO books VALUES (?,?)", [(1, "A"), (2, "B"), (3, "C")])
    con.commit()
    con.close()
    loads = [
        _load("gutenberg", "books", {"command": "books", "topic": "fiction", "limit": 3}, "2026-10-14T18:05:48Z"),
        _load("gutenberg", "texts_c1", {"command": "text", "ids": ["1", "2"]}, "2026-10-14T18:47:53Z"),
        _load("gutenberg", "texts_c2", {"command": "text", "ids": ["3"]}, "2026-10-14T18:48:22Z"),
    ]
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8")
    for name, text in (("draw_sample.py", DRAW), ("build_data.py", BUILD), ("run_estimation.py", ESTIMATE)):
        (ws / name).write_text(text, encoding="utf-8")
        assert _run_recorded(ws, ws / name, 120, by="e2er-run") == 0
    return ws


@pytest.fixture
def rerun_offline(monkeypatch, tmp_path):
    """`e2er reproduce` with the tests' interpreter and an e2er-data that loads the texts offline."""
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)
    calls = tmp_path / "e2er-data-calls.jsonl"

    def make_environment(run_dir, recipe, folder, logs):
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    real_step_env = rp.step_env

    def step_env(venv_python, run_dir=None):
        env = real_step_env(venv_python, run_dir)
        env.update({"E2ER_DATA": str(fake), "FAKE_TEXTS": json.dumps(TEXTS), "FAKE_CALLS": str(calls)})
        return env

    monkeypatch.setattr(rp, "make_environment", make_environment)
    monkeypatch.setattr(rp, "step_env", step_env)
    return calls


# ── the script log ───────────────────────────────────────────────────────────


def test_the_script_log_records_the_tables_a_run_writes_also_under_a_computed_name(tmp_path):
    ws = _workspace(tmp_path)
    runs = {r["script"]: r for r in sl.read_script_runs(ws)}
    assert runs["build_data.py"]["tables"] == {"written": ["corpus", "corpus_counts"], "dropped": []}
    assert "tables" not in runs["draw_sample.py"], "a run that leaves the database alone records no tables"
    assert "tables" not in runs["run_estimation.py"]

    (ws / "drop.py").write_text(
        "import sqlite3\ncon = sqlite3.connect('data.db')\nname = 'books'\ncon.execute('DROP TABLE ' + name)\n"
        "con.commit()\n",
        encoding="utf-8",
    )
    assert _run_recorded(ws, ws / "drop.py", 60, by="e2er-run") == 0
    assert sl.read_script_runs(ws)[-1]["tables"] == {"written": [], "dropped": ["books"]}


def test_the_database_is_read_again_only_when_it_changed(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    reads: list[Path] = []
    real = sl.table_digests
    monkeypatch.setattr(sl, "table_digests", lambda db: reads.append(db) or real(db))
    before = sl.output_snapshot(ws)
    assert reads == [], "e2er's record of the tables is current: the database is not read"
    assert set(before.db or {}) == {"books", "corpus", "corpus_counts", "texts_c1", "texts_c2"}
    sl.record_script_run(ws, "draw_sample.py", "2026-10-14T19:00:00Z", 0, by="e2er-run", before=before)
    assert reads == [] and "tables" not in sl.read_script_runs(ws)[-1]
    # An older caller's snapshot (a plain dict) records no tables, rather than every table as written.
    sl.record_script_run(ws, "draw_sample.py", "2026-10-14T19:00:01Z", 0, by="e2er-run", before={})
    assert "tables" not in sl.read_script_runs(ws)[-1]


# ── who wrote each table ─────────────────────────────────────────────────────


def test_every_table_is_traced_to_its_load_or_its_script_and_the_code_answers_for_older_runs(tmp_path):
    ws = _workspace(tmp_path)
    loads = rr._loads(ws)
    writers = rr.table_writers(ws, loads, {"run_estimation.py"})
    assert {t: (w["how"], w.get("by"), w["evidence"]) for t, w in writers.items() if w["how"] != "loaded"} == {
        "corpus": ("built", "build_data.py", "script log"),
        "corpus_counts": ("built", "build_data.py", "script log"),
    }
    assert {t for t, w in writers.items() if w["how"] == "loaded"} == {"books", "texts_c1", "texts_c2"}
    chain = rr.chain_of(ws).scripts
    # texts_c1 and texts_c2 are read through f"texts_{c}"; the catalogue (books) by no step.
    assert set(rr.needed_tables(ws, chain, writers)) == {"corpus", "corpus_counts", "texts_c1", "texts_c2"}

    # A run from before e2er recorded tables: the code says it (to_sql with a computed name and the name in a
    # string of the script).
    log = ws / sl.SCRIPT_RUNS
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    log.write_text("".join(json.dumps({k: v for k, v in r.items() if k != "tables"}) + "\n" for r in rows), "utf-8")
    writers = rr.table_writers(ws, loads, {"run_estimation.py"})
    assert writers["corpus"] == {"how": "built", "by": "build_data.py", "evidence": "the scripts' code"}
    assert rr.preparation_scripts(ws, chain, loads) == ([ws / "build_data.py"], ["corpus", "corpus_counts"])


@pytest.mark.parametrize(
    ("source", "table", "writes"),
    [
        ('for name, t in [("corpus", df)]:\n    t.to_sql(name, con)\n', "corpus", True),
        ('for name, t in [("corpus", df)]:\n    t.to_sql(name, con)\n', "hits", False),
        ('df.to_sql(f"texts_{c}", con)\n', "texts_c3", True),
        ('df.to_sql(name="corpus", con=con)\n', "corpus", True),
        ('df.to_sql("corpus", con)\n', "corpus_counts", False),
        ('con.execute("CREATE TABLE IF NOT EXISTS corpus AS SELECT 1")\n', "corpus", True),
        ('print("corpus")\n', "corpus", False),
    ],
)
def test_table_detection_from_the_code(source, table, writes):
    assert rr._writes_table(source, table) is writes


def test_an_f_string_names_the_tables_it_can_make_and_no_others():
    code = 'pd.read_sql(f"select id from gutenberg_texts_{c}", con)\nx = f"{a}{b}"\n'
    assert rr._reads_table(code, "gutenberg_texts_c1")
    assert rr._reads_table(code, "gutenberg_texts_c3_refill")
    assert not rr._reads_table(code, "corpus"), "a bare {a}{b} names no table"


# ── export → reproduce.json ──────────────────────────────────────────────────


def test_export_records_the_data_preparation_and_a_folder_without_data_db_reproduces(tmp_path, rerun_offline, capsys):
    ws = _workspace(tmp_path)
    folder = export_paper(ws, tmp_path / "exports", date_str="20261021")
    recipe = json.loads((folder / "reproduce.json").read_text(encoding="utf-8"))
    assert [(s["run"][-1], s.get("when_missing")) for s in recipe["steps"]] == [
        ("get_data.py", None),
        ("build_data.py", ["data.db"]),
        ("run_estimation.py", None),
    ]
    assert recipe["files"]["build_data.py"] == "code/scratch/build_data.py"
    # The small file the preparation reads ships with the folder, with the seeded script that made it.
    assert recipe["files"]["data/sample_ids.csv"] == "data/sample_ids.csv"
    assert (folder / "data" / "sample_ids.csv").is_file()
    [sample] = [i for i in recipe["inputs"] if i["path"] == "data/sample_ids.csv"]
    assert sample["made_by"]["script"] == "draw_sample.py" and sample["made_by"]["seeded"] is True
    assert sample["made_by"]["file"] == "code/scratch/draw_sample.py"
    assert any(
        "data/sample_ids.csv was made during the run by draw_sample.py, a seeded draw" in n for n in recipe["notes"]
    )
    # Every table of data.db: where it came from and how a rerun gets it back.
    tables = recipe["database"]["tables"]
    assert {t: (e["how"], e["back"], e["read"]) for t, e in tables.items()} == {
        "books": ("loaded", None, False),
        "texts_c1": ("loaded", "get_data.py", True),
        "texts_c2": ("loaded", "get_data.py", True),
        "corpus": ("built", "build_data.py", True),
        "corpus_counts": ("built", "build_data.py", True),
    }
    [db] = [i for i in recipe["inputs"] if i["path"] == "data.db"]
    assert db["reload"] == "get_data.py" and db["not_read"] == ["books"]
    get_data = (folder / "code" / "get_data.py").read_text(encoding="utf-8")
    assert '"texts_c1"' in get_data and '"texts_c2"' in get_data
    assert '"table": "books"' not in get_data, "the catalogue no step reads is not loaded again"
    assert any("open sources" in n and "needs the internet" in n for n in recipe["notes"])

    # A folder too large for its host leaves data.db out: loads, builds and the tables nobody reads.
    files = pkg.study_files(folder)
    [left] = pkg.left_out_data(folder, files, recipe, no_data=False, host="GitHub", max_file_bytes=1000)
    assert left["kind"] == "size" and left["loads"] == ["texts_c1", "texts_c2"]
    assert left["builds"] == [{"by": "code/scratch/build_data.py", "what": ["corpus", "corpus_counts"]}]
    assert left["not_read"] == ["books"] and "not_built" not in left
    assert "does not need the tables books (no step reads them)" in pkg.rerun_words(left)

    # The rerun without data.db: get_data.py loads the texts, build_data.py builds the corpus, the results match.
    clone = tmp_path / "clone"
    shutil.copytree(folder, clone)
    (clone / "data" / "data.db").unlink()
    capsys.readouterr()
    assert reproduce(str(clone)) == 0
    report = capsys.readouterr().out
    assert "python build_data.py (data preparation" in report
    assert "Reproduced: every compared value is identical" in report
    calls = [json.loads(line) for line in rerun_offline.read_text(encoding="utf-8").splitlines()]
    assert sorted(c[c.index("--table") + 1] for c in calls) == ["texts_c1", "texts_c2"]

    # With data.db in the folder nothing is loaded and the preparation does not run.
    rerun_offline.unlink()
    assert reproduce(str(folder)) == 0
    report = capsys.readouterr().out
    assert "not run" in report and "Reproduced: every compared value is identical" in report
    assert not rerun_offline.exists() or not rerun_offline.read_text(encoding="utf-8").strip()


def test_a_rebuilt_database_is_compared_on_the_tables_the_steps_read(tmp_path):
    db = tmp_path / "data.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE corpus (id INTEGER)")
    con.execute("INSERT INTO corpus VALUES (1)")
    con.commit()
    con.close()
    have = rp.content_fingerprint(db)["tables"]["corpus"]
    item = {"tables": {"corpus": have, "books": {"rows": 3, "content_sha256": "0" * 64}}}
    assert rp._same_content(item, db)[0] == rp.DIFFERS, "books is missing from the rebuilt database"
    assert rp._same_content({**item, "not_read": ["books"]}, db)[0] == rp.SAME_ROWS


# ── get_data.py: a source that does not answer in time ───────────────────────

#: Fails the first call for each table (Gutendex's first answer to a query it has not seen takes a minute).
FLAKY_E2ER_DATA = """\
import json, os, sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
table = args[args.index("--table") + 1]
seen = Path(os.environ["FAKE_SEEN"]) / table
if not seen.exists():
    seen.write_text("1")
    print(json.dumps({"error": "Gutendex did not answer within 45 s. No text was loaded; try again later."}))
    sys.exit(1)
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
con = sqlite3.connect(ws / "data.db")
con.execute(f'CREATE TABLE "{table}" (id INTEGER, text TEXT)')
rows = json.loads(os.environ["FAKE_TEXTS"])[table]
con.executemany(f'INSERT INTO "{table}" VALUES (?,?)', rows)
con.commit()
print(json.dumps({"table": table}))
"""


def test_get_data_asks_a_slow_source_again_and_says_when_a_load_has_too_few_rows(tmp_path, monkeypatch, capsys):
    import importlib.util

    ws = _workspace(tmp_path)
    loads = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))["loads"]
    for e in loads:
        e["table_rows"] = len(TEXTS.get(e["table"], [])) or 3
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8")
    folder = export_paper(ws, tmp_path / "exports", date_str="20261021")
    run = tmp_path / "runs" / "p-weather"
    run.mkdir(parents=True)
    script = folder / "code" / "get_data.py"
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FLAKY_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)
    (tmp_path / "seen").mkdir()
    monkeypatch.setenv("E2ER_DATA", str(fake))
    monkeypatch.setenv("FAKE_SEEN", str(tmp_path / "seen"))
    monkeypatch.setenv("FAKE_TEXTS", json.dumps(TEXTS))
    monkeypatch.chdir(run)
    spec = importlib.util.spec_from_file_location("get_data_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PAUSE_SECONDS = 0
    assert [r["rows"] for r in module.RELOADS] == [2, 1], "the rows each load wrote in the run"
    assert module.main() == 0
    err = capsys.readouterr().err
    assert err.count("trying again in 0 s") == 2, "each table's first call failed and was asked again"
    con = sqlite3.connect(run / "data.db")
    assert con.execute("SELECT COUNT(*) FROM texts_c1").fetchone() == (2,)
    con.close()

    # A load that comes back with fewer rows than the run's is not taken for the study's input.
    (run / "data.db").unlink()
    module.RELOADS[0]["rows"] = 5
    assert module.main() == 1
    err = capsys.readouterr().err
    assert "Could not load:" in err and "loaded 2 of the 5 rows the run loaded" in err
