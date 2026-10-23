"""get_data.py: a half-loaded table is loaded again, and the last load into a table is the one reloaded.

Review of 2026-10-23: a table counted as present when it had any rows, so a rerun after "loaded 400 of
1200 rows" said "the study's own copy is here" and exited 0; with two loads into one table (e2er-data
replaces the table: the study used the last), the first was reloaded and the second skipped as present.
Also the small path fixes found beside them (`_saved`, `_rewrite_workspace_paths`).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from src.core.export import reproduce_recipe as rr

#: e2er-data as get_data.py calls it: writes FAKE_ROWS rows (an env var) into the table it is asked for.
FAKE_E2ER_DATA = """\
import json, os, sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
table = args[args.index("--table") + 1]
series = args[args.index("--series") + 1]
with open(ws / "calls.txt", "a") as f:
    f.write(series + "\\n")
con = sqlite3.connect(ws / "data.db")
con.execute(f'DROP TABLE IF EXISTS "{table}"')
con.execute(f'CREATE TABLE "{table}" (v INTEGER)')
con.executemany(f'INSERT INTO "{table}" VALUES (?)', [(i,) for i in range(int(os.environ["FAKE_ROWS"]))])
con.commit()
print(json.dumps({"table": table}))
"""


def _get_data(run: Path, reloads: list[dict]) -> None:
    (run / "get_data.py").write_text(
        rr.GET_DATA.format(date="20261023", terms="", reloads=json.dumps(reloads), other_tables="[]"),
        encoding="utf-8",
    )


def _run(run: Path, fake: Path, rows: int) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "E2ER_DATA": str(fake), "FAKE_ROWS": str(rows)}
    return subprocess.run([sys.executable, "get_data.py"], cwd=run, env=env, capture_output=True, text=True)


def _fake(tmp_path: Path) -> Path:
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)
    return fake


def _rows_in(run: Path, table: str) -> int:
    con = sqlite3.connect(run / "data.db")
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        con.close()


def test_a_table_a_load_stopped_early_is_loaded_again(tmp_path: Path):
    run = tmp_path / "run"
    run.mkdir()
    fake = _fake(tmp_path)
    _get_data(
        run, [{"table": "gdp", "args": ["fred", "--series", "GDP", "--table", "gdp"], "what": "FRED GDP", "rows": 12}]
    )
    first = _run(run, fake, 4)  # the source stopped early
    assert first.returncode == 1 and "loaded 4 of the 12 rows" in first.stderr
    again = _run(run, fake, 12)
    assert "own copy is here" not in again.stdout, again.stdout
    assert again.returncode == 0 and _rows_in(run, "gdp") == 12
    # A whole table is kept.
    third = _run(run, fake, 12)
    assert "gdp: the study's own copy is here" in third.stdout
    assert (run / "calls.txt").read_text().splitlines() == ["GDP", "GDP"]


def test_only_the_last_load_into_a_table_is_reloaded():
    loads = [
        {
            "connector": "fred",
            "dataset": "FRED",
            "series": "GDP",
            "table": "macro",
            "table_rows": 10,
            "request": {"command": "series", "series": "GDP"},
        },
        {
            "connector": "fred",
            "dataset": "FRED",
            "series": "GDPC1",
            "table": "macro",
            "table_rows": 10,
            "request": {"command": "series", "series": "GDPC1"},
        },
    ]
    reloads, _ = rr._reloads(Path("."), loads, ["data.db"], {"macro"})
    tables = [r for r in reloads if r.get("table") == "macro"]
    assert len(tables) == 1 and "GDPC1" in tables[0]["what"], reloads


def test_saved_strips_the_prefix_not_the_characters():
    assert rr._saved({"saved_to": "./data/x.csv"}) == "data/x.csv"
    assert rr._saved({"saved_to": ".hidden.csv"}) == "data/.hidden.csv"
    assert rr._saved({"saved_to": "x.csv"}) == "data/x.csv"


def test_only_the_workspace_path_itself_is_rewritten(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    script = tmp_path / "s.py"
    script.write_text(f'A = "{ws}/data/x.csv"\nB = "{ws}_other/y.csv"\nC = "{ws}"\n', encoding="utf-8")
    assert rr._rewrite_workspace_paths(script, ws)
    text = script.read_text()
    assert 'A = "data/x.csv"' in text and f'B = "{ws}_other/y.csv"' in text and 'C = "."' in text
