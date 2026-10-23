"""Every way a script writes a file counts for the data terms (src/core/derived_data.py, script_log.py).

Review of 2026-10-23 (confirmed by a test): a script read data/gmd.csv (the Global Macro Database, whose
terms keep its rows out of a published study), then wrote ``g.to_file("results/regions.gpkg")`` and
``shutil.copy("data/gmd.csv", "results/gmd_copy.csv")``; ``derived()`` found neither, and the script log
recorded only .json/.csv/.tsv files up to 64 MB, so `e2er pack` and `publish --github` would ship both.
Also missed: polars ``write_parquet``/``write_json``, ``pyarrow.parquet.write_table``, ``to_netcdf``,
``joblib.dump``, DuckDB ``COPY … TO``, f-string paths, and parquet and CSV files over 64 MB.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from src.core import derived_data as dd
from src.core import script_log as sl
from src.core.export import package as pkg
from src.core.export.structured import export_paper

#: 60 country-years: more rows than an aggregate of a source with unrecorded rows may have (derived_rows.py).
GMD_ROWS = "ISO3,year,rGDP,infl\n" + "".join(
    f"{c},{y},{1000 + i * 7.5:.1f},{0.1 * (i % 9):.1f}\n"
    for i, (c, y) in enumerate((c, y) for c in ("DEU", "FRA", "ITA", "ESP", "NLD", "BEL") for y in range(2011, 2021))
)

GMD_SCRIPT = """\
import shutil

import geopandas as gpd
import pandas as pd

g = gpd.GeoDataFrame(pd.read_csv("data/gmd.csv"))
g.to_file("regions.gpkg")
shutil.copy("data/gmd.csv", "gmd_copy.csv")
"""


def _gmd_load() -> dict:
    return {
        "connector": "gmd",
        "dataset": "Global Macro Database",
        "series": "GMD",
        "version": "2025_06",
        "saved_to": "data/gmd.csv",
        "retrieved_at": "2026-10-23T10:00:00Z",
    }


def _gmd_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "2026-10-23-gmd"
    (ws / "data").mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-gmd", "title": "Inflation in Europe"}))
    (ws / "data" / "gmd.csv").write_text(GMD_ROWS)
    (ws / "data_sources.json").write_text(json.dumps({"loads": [_gmd_load()]}))
    (ws / "regions.py").write_text(GMD_SCRIPT)
    later = time.time() + 2
    for name, data in (("regions.gpkg", b"GPKG\x00" + GMD_ROWS.encode()), ("gmd_copy.csv", GMD_ROWS.encode())):
        (ws / name).write_bytes(data)
        os.utime(ws / name, (later, later))
    return ws


def test_the_reviewers_gmd_case_is_left_out_of_the_package(tmp_path: Path):
    folder = export_paper(_gmd_workspace(tmp_path), tmp_path / "exports", date_str="20261023")
    found = {d.path: d for d in dd.derived(folder)}
    assert "misc/regions.gpkg" in found and "results/gmd_copy.csv" in found, sorted(found)
    assert found["results/gmd_copy.csv"].connectors == ["gmd"]
    kept = {d.path for d in dd.kept_out(folder)}
    assert {"misc/regions.gpkg", "results/gmd_copy.csv"} <= kept
    # Export recorded them too (provenance.json run.derived_data), and pack leaves them out.
    recorded = {e["path"] for e in json.loads((folder / "provenance.json").read_text())["run"]["derived_data"]}
    assert {"misc/regions.gpkg", "results/gmd_copy.csv"} <= recorded
    packed = pkg.build(folder)
    left = {i["path"] for i in packed.manifest["left_out"]}
    assert {"misc/regions.gpkg", "results/gmd_copy.csv"} <= left


def _writes(source: str) -> dd.Script:
    return dd.analyse("code/x.py", source)


def test_every_write_call_is_seen():
    s = _writes(
        "import polars as pl, pyarrow.parquet as pq, pyarrow.feather as feather, joblib, shutil, duckdb\n"
        'OUT = "results"\n'
        "YEAR = '2020'\n"
        'df = pl.read_csv("data/gmd.csv")\n'
        'df.write_parquet("data/a.parquet")\n'
        'df.write_json("results/b.json")\n'
        'pq.write_table(df.to_arrow(), "data/c.parquet")\n'
        'pq.write_table(df.to_arrow(), where="data/c2.parquet")\n'
        'feather.write_feather(df, "data/d.feather")\n'
        'ds.to_netcdf("data/e.nc")\n'
        'joblib.dump(model, "results/f.joblib")\n'
        'shutil.copy2("data/gmd.csv", "data/g.csv")\n'
        'shutil.copyfile("data/gmd.csv", "data/h.csv")\n'
        'shutil.move("tmp.csv", "data/i.csv")\n'
        'df.to_pandas().to_csv(f"{OUT}/j_{YEAR}.csv")\n'
        "duckdb.sql(\"COPY (SELECT * FROM 'data/gmd.csv') TO 'data/k.parquet' (FORMAT parquet)\")\n"
        'g.to_file("results/l.gpkg")\n'
    )
    assert {
        "data/a.parquet",
        "results/b.json",
        "data/c.parquet",
        "data/c2.parquet",
        "data/d.feather",
        "data/e.nc",
        "results/f.joblib",
        "data/g.csv",
        "data/h.csv",
        "data/i.csv",
        "results/j_2020.csv",
        "data/k.parquet",
        "results/l.gpkg",
    } <= s.writes
    assert "data/gmd.csv" in s.reads  # the copies read their source
    assert s.unresolved_writes == []


def test_a_handle_or_a_copy_of_a_frame_is_no_unresolved_write():
    s = _writes(
        "import json, pandas as pd\n"
        'df = pd.read_csv("data/gmd.csv")\n'
        "df2 = df.copy()\n"
        'with open("results/x.json", "w") as fh:\n'
        "    json.dump({}, fh)\n"
        "text = df.to_csv()\n"
    )
    assert s.writes == {"results/x.json"} and s.unresolved_writes == []


def test_unresolved_writes_are_named():
    s = _writes(
        "import pandas as pd, duckdb\n"
        "for y in range(3):\n"
        '    pd.read_csv("data/gmd.csv").to_parquet(f"data/gmd_{y}.parquet")\n'
        "out = make_path()\n"
        "open(out, 'w').write('x')\n"
        "duckdb.sql(f\"COPY t TO '{out}'\")\n"
    )
    assert len(s.unresolved_writes) == 3, s.unresolved_writes


def test_a_script_reading_restricted_data_with_an_unresolved_write_taints_every_new_output(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "code").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "data" / "data_sources.json").write_text(json.dumps({"loads": [_gmd_load()]}))
    old = tmp_path / "results" / "older.csv"
    old.write_text("a\n1\n")
    past = time.time() - 3600
    os.utime(old, (past, past))
    script = tmp_path / "code" / "split.py"
    script.write_text(
        "import pandas as pd\n"
        'df = pd.read_csv("data/gmd.csv")\n'
        "for c, part in df.groupby('ISO3'):\n"
        '    part.to_parquet(f"data/gmd_{c}.parquet")\n'
    )
    os.utime(script, (past + 60, past + 60))
    for name in ("data/gmd_DEU.parquet", "results/summary.csv"):
        (tmp_path / name).write_text("x\n")
    found = {d.path: d for d in dd.derived(tmp_path)}
    assert {"data/gmd_DEU.parquet", "results/summary.csv"} <= set(found)
    assert "results/older.csv" not in found, "a file older than the script is not its output"
    assert "data/data_sources.json" not in found
    assert found["data/gmd_DEU.parquet"].writers == ["code/split.py"]
    # A script that reads no restricted data taints nothing.
    script.write_text("import pandas as pd\nfor c in 'ab':\n    pd.DataFrame().to_parquet(f'data/{c}.parquet')\n")
    os.utime(script, (past + 60, past + 60))
    assert dd.derived(tmp_path) == []


def test_the_script_log_records_every_data_file_and_the_path_of_one_too_large_to_hash(tmp_path: Path, monkeypatch):
    (tmp_path / "s.py").write_text("print(1)\n")
    before = sl.output_snapshot(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "regions.gpkg").write_bytes(b"GPKG")
    (tmp_path / "panel.parquet").write_bytes(b"PAR1" * 100)
    monkeypatch.setattr(sl, "_MAX_OUTPUT_BYTES", 100)
    sl.record_script_run(tmp_path, "s.py", "2026-10-23T10:00:00Z", 0, by="tests", before=before)
    [run] = sl.read_script_runs(tmp_path)
    assert set(run["outputs"]) == {"results/regions.gpkg"}
    assert run["outputs_unhashed"] == ["panel.parquet"]
    # derived() counts both as written by the script.
    (tmp_path / "data").mkdir()
    (tmp_path / "data_sources.json").write_text(json.dumps({"loads": [_gmd_load()]}))
    (tmp_path / "s.py").write_text('import pandas as pd\nX = pd.read_csv("data/gmd.csv")\n')
    found = {d.path for d in dd.derived(tmp_path)}
    assert {"results/regions.gpkg", "panel.parquet"} <= found
