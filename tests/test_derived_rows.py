"""Results built from restricted data stay out unless they are aggregates (src/core/derived_rows.py).

Two demos (2026-10-20) showed that only files under data/ were treated as
built from a restricted source: demo 2's results/figure_spec.json carried
9,970 Gaia proper-motion pairs, demo 6's results/*.csv the GISCO units and
weights of 244 regions. Any output a step wrote from restricted data now
counts, unless it is an aggregate (few rows against the source, no source
identifier); left-out results do not break a clone: verify says what it needs
and that `e2er reproduce` builds it, and reproduce builds it by running the
step that wrote it after loading the source again.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.cli_verify import FAIL, SKIP, _check_integrity, _run_checks
from src.core import data_terms
from src.core import derived_data as dd
from src.core import derived_rows as dr
from src.core import reproduce as rp
from src.core.export import package as pkg
from src.core.export.structured import export_paper
from src.core.specialists.post_execution import _run_recorded
from tests.platform_help import fake_program

# ── a Gaia-like study: 120 stars, a figure spec with a point per star ────────

STARS = [(5_000_000_000 + 7919 * i, round(7.0 + (i % 13) * 0.05, 3), 1.0 + (i % 5) * 0.1) for i in range(120)]
RAW_ROWS = "source_id,parallax,ruwe\n" + "".join(f"{s},{p},{r}\n" for s, p, r in STARS)

CLEAN = """\
import csv

RAW = "data/gaia_dr3.csv"
CLEAN = "data/gaia_clean.csv"
rows = [r for r in csv.DictReader(open(RAW)) if float(r["ruwe"]) < 1.35]
with open(CLEAN, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["source_id", "parallax", "ruwe"])
    w.writeheader()
    w.writerows(sorted(rows, key=lambda r: r["source_id"]))
"""

ESTIMATE = """\
import csv
import json

RAW = "data/gaia_dr3.csv"
CLEAN = "data/gaia_clean.csv"
n_raw = sum(1 for _ in csv.DictReader(open(RAW)))
rows = list(csv.DictReader(open(CLEAN)))
par = [float(r["parallax"]) for r in rows]
bins = {}
for p in par:
    bins.setdefault(round(p, 1), []).append(p)
with open("parallax_bins.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["bin", "n", "mean"])
    for b in sorted(bins):
        w.writerow([b, len(bins[b]), sum(bins[b]) / len(bins[b])])
with open("brightest.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["source_id", "parallax"])
    for r in sorted(rows, key=lambda r: -float(r["parallax"]))[:3]:
        w.writerow([r["source_id"], r["parallax"]])
out = {"main": {"n_raw": n_raw, "n_clean": len(par), "mean_parallax": sum(par) / len(par), "n_bins": len(bins)}}
with open("estimation_results.json", "w") as f:
    json.dump(out, f, indent=2)
"""

FIGURES = """\
import csv
import json

rows = list(csv.DictReader(open("data/gaia_clean.csv")))
spec = {"figures": [{"filename": "fig_parallax.pdf", "figure_type": "scatter",
                     "x": [float(r["parallax"]) for r in rows], "y": [float(r["ruwe"]) for r in rows]}]}
with open("figure_spec.json", "w") as f:
    json.dump(spec, f)
"""


def _gaia_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "2026-10-20-stars"
    (ws / "data").mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": "p-stars", "title": "Stars"}), encoding="utf-8", newline="\n"
    )
    (ws / "data" / "gaia_dr3.csv").write_text(RAW_ROWS, encoding="utf-8", newline="\n")
    load = {
        "connector": "gaia",
        "dataset": "Gaia Data Release 3",
        "series": "Gaia archive ADQL query",
        "version": "DR3",
        "saved_to": "data/gaia_dr3.csv",
        "rows": len(STARS),
        "request": {"command": "query", "adql": "SELECT source_id, parallax, ruwe FROM gaiadr3.gaia_source"},
        "retrieved_at": "2026-10-13T21:02:56Z",
    }
    (ws / "data_sources.json").write_text(json.dumps({"loads": [load]}), encoding="utf-8", newline="\n")
    for name, text in (("clean_gaia.py", CLEAN), ("run_estimation.py", ESTIMATE), ("make_figures.py", FIGURES)):
        (ws / name).write_text(text, encoding="utf-8", newline="\n")
        assert _run_recorded(ws, ws / name, 60, by="e2er-run") == 0
    return ws


# ── a GISCO-like study: 60 regions, units and weights tables in results/ ─────

REGIONS = [(f"R{i:02d}", f"Region {i}", json.dumps({"type": "Point", "coordinates": [i, i % 7]})) for i in range(60)]
GDP = [(f"R{i:02d}", 100.0 + i) for i in range(60)]

BUILD = """\
import csv, json, sqlite3
con = sqlite3.connect("data.db")
b = {r[0]: r for r in con.execute("SELECT nuts_id, name_latn, geometry FROM nuts2_boundaries")}
g = con.execute("SELECT geo, value FROM gdp ORDER BY geo").fetchall()
with open("units.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "name", "gdp", "x"])
    for geo, v in g:
        w.writerow([geo, b[geo][1], v, json.loads(b[geo][2])["coordinates"][0]])
with open("weights.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["from", "to", "weight"])
    ids = [geo for geo, _ in g]
    for a, c in zip(ids, ids[1:] + ids[:1]):
        w.writerow([a, c, 1.0])
"""

SPATIAL = """\
import csv, json, sqlite3
con = sqlite3.connect("data.db")
n_boundaries = con.execute("SELECT COUNT(*) FROM nuts2_boundaries").fetchone()[0]
units = list(csv.DictReader(open("units.csv")))
weights = list(csv.DictReader(open("weights.csv")))
x = [float(u["gdp"]) for u in units]
groups = {}
for u in units:
    groups.setdefault(int(u["x"]) % 3, []).append(float(u["gdp"]))
with open("by_group.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["group", "n", "mean"])
    for k in sorted(groups):
        w.writerow([k, len(groups[k]), sum(groups[k]) / len(groups[k])])
with open("lags.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "lag"])
    for u in units:
        w.writerow([u["id"], float(u["gdp"]) * 0.5])
out = {"main": {"n": len(x), "mean": sum(x) / len(x), "links": len(weights), "boundaries": n_boundaries},
       "units": {"file": "units.csv", "n_units": len(x)}}
json.dump(out, open("estimation_results.json", "w"), indent=2)
"""

FAKE_TABLE_DATA = """\
import json, os, sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
if "--save-to" in args:  # the Gaia rows, as a file
    name = args[args.index("--save-to") + 1]
    (ws / "data").mkdir(exist_ok=True)
    (ws / "data" / name).write_text(os.environ["FAKE_GAIA"])
    print(json.dumps({"saved_to": "data/" + name}))
    sys.exit(0)
table = args[args.index("--table") + 1]
con = sqlite3.connect(ws / "data.db")
if table == "nuts2_boundaries":
    con.execute('CREATE TABLE nuts2_boundaries (nuts_id TEXT, name_latn TEXT, geometry TEXT)')
    con.executemany('INSERT INTO nuts2_boundaries VALUES (?,?,?)', json.loads(os.environ["FAKE_REGIONS"]))
else:
    con.execute('CREATE TABLE gdp (geo TEXT, value REAL)')
    con.executemany('INSERT INTO gdp VALUES (?,?)', json.loads(os.environ["FAKE_GDP"]))
con.commit()
print(json.dumps({"table": table, "rows": con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}))
"""


def _gisco_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "2026-10-20-regions"
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": "p-regions", "title": "Regions"}), encoding="utf-8", newline="\n"
    )
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE nuts2_boundaries (nuts_id TEXT, name_latn TEXT, geometry TEXT)")
    con.executemany("INSERT INTO nuts2_boundaries VALUES (?,?,?)", REGIONS)
    con.execute("CREATE TABLE gdp (geo TEXT, value REAL)")
    con.executemany("INSERT INTO gdp VALUES (?,?)", GDP)
    con.commit()
    con.close()
    loads = [
        {
            "connector": "gisco",
            "table": "nuts2_boundaries",
            "rows": len(REGIONS),
            "dataset": "GISCO geographical data",
            "series": "NUTS 2 regions",
            "version": "NUTS 2024",
            "request": {"command": "nuts", "level": 2, "year": 2024},
            "retrieved_at": "2026-10-14T17:36:20Z",
        },
        {
            "connector": "eurostat",
            "table": "gdp",
            "rows": len(GDP),
            "dataset": "Eurostat database",
            "series": "nama_10r_2gdp",
            "dataset_code": "nama_10r_2gdp",
            "request": {"command": "data", "dataset": "nama_10r_2gdp"},
            "retrieved_at": "2026-10-14T17:36:16Z",
        },
    ]
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8", newline="\n")
    for name, text in (("build_units.py", BUILD), ("run_estimation.py", SPATIAL)):
        (ws / name).write_text(text, encoding="utf-8", newline="\n")
        assert _run_recorded(ws, ws / name, 60, by="e2er-run") == 0
    return ws


@pytest.fixture
def rerun_here(monkeypatch, tmp_path):
    """`e2er reproduce` with the tests' interpreter and an e2er-data that loads both studies' sources offline."""
    tables = tmp_path / "fake-e2er-data"
    tables = fake_program(tables, FAKE_TABLE_DATA)

    def make_environment(run_dir, recipe, folder, logs):
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    real_step_env = rp.step_env

    def step_env(venv_python, run_dir=None):
        env = real_step_env(venv_python, run_dir)
        env.update(
            {
                "E2ER_DATA": str(tables),
                "FAKE_GAIA": RAW_ROWS,
                "FAKE_REGIONS": json.dumps(REGIONS),
                "FAKE_GDP": json.dumps(GDP),
            }
        )
        return env

    monkeypatch.setattr(rp, "make_environment", make_environment)
    monkeypatch.setattr(rp, "step_env", step_env)
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))


def _export(ws: Path, tmp_path: Path) -> Path:
    return export_paper(ws, tmp_path / "exports", date_str="20261020")


# ── the rule ─────────────────────────────────────────────────────────────────


def test_a_figure_spec_with_a_point_per_star_is_row_level_and_aggregates_go_up(tmp_path):
    folder = _export(_gaia_workspace(tmp_path), tmp_path)
    found = {d.path: d for d in dd.derived(folder)}
    assert {"results/figure_spec.json", "results/brightest.csv", "results/parallax_bins.csv"} <= set(found)
    out = {d.path: d.rows for d in dd.kept_out(folder)}
    assert "an array of" in out["results/figure_spec.json"] and "values" in out["results/figure_spec.json"]
    # Three rows only, but each names a star: the source's identifier.
    assert out["results/brightest.csv"].startswith("an identifier of the source")
    assert out["data/gaia_clean.csv"] == "", "a data file under data/ stays out whatever it holds"
    # The parallax bins (a handful of rows, no star named) and the estimates are aggregates: they go up.
    assert "results/parallax_bins.csv" not in out and "results/estimation_results.json" not in out
    reasons = data_terms.restricted_paths(folder)
    assert "holds them row by row" in reasons["results/figure_spec.json"]
    assert "results/parallax_bins.csv" not in reasons


def test_the_limits_follow_the_source_and_labels_are_no_points(tmp_path):
    shape = dr.Shape(rows={"gaia": 14066, "gisco": 299}, ids={"gaia": {"5000000000"}})
    assert shape.limits(["gaia"]) == (50, 50)
    assert shape.limits(["gisco"]) == (10, 29)
    assert shape.limits(["unknown"]) == (10, 10)
    p = tmp_path / "x.json"
    p.write_text(
        json.dumps({"clusters": [f"R{i}" for i in range(40)], "by_country": {f"C{i}": {"n": i} for i in range(20)}}),
        encoding="utf-8",
        newline="\n",
    )
    assert dr.row_level(p, ["gisco"], shape) is None, "labels and 20 country aggregates are not the source's rows"
    p.write_text(json.dumps({"x": list(range(11))}), encoding="utf-8", newline="\n")
    assert "an array of 11 values" in str(dr.row_level(p, ["gisco"], shape))
    p.write_text(json.dumps({"units": {f"C{i}": {"n": i} for i in range(30)}}), encoding="utf-8", newline="\n")
    assert "30 records" in str(dr.row_level(p, ["gisco"], shape))
    p.write_text(json.dumps({"star": 5000000000}), encoding="utf-8", newline="\n")
    assert "identifier" in str(dr.row_level(p, ["gaia"], shape))
    p = tmp_path / "x.parquet"
    p.write_bytes(b"PAR1")
    assert "whose rows e2er does not count" in str(dr.row_level(p, ["gaia"], shape))


def test_gisco_results_tables_stay_out_and_the_group_means_go_up(tmp_path):
    folder = _export(_gisco_workspace(tmp_path), tmp_path)
    out = {d.path: d.rows for d in dd.kept_out(folder)}
    assert out["results/units.csv"] == "60 rows" and out["results/weights.csv"] == "60 rows"
    assert out["results/lags.csv"] == "60 rows"
    assert "results/by_group.csv" not in out and "results/estimation_results.json" not in out
    # Region names are GISCO's alone; the region codes are in Eurostat's own table too.
    shape = dr.shape(folder, set(data_terms.known()))
    assert "Region 7" in shape.ids["gisco"] and "R07" not in shape.ids["gisco"]


# ── pack, verify a clone, reproduce ──────────────────────────────────────────


def test_the_package_leaves_the_point_array_out_and_the_rerun_builds_it(tmp_path, rerun_here, capsys):
    folder = _export(_gaia_workspace(tmp_path), tmp_path)
    packed = pkg.build(folder)
    left = {i["path"]: i for i in packed.manifest["left_out"]}
    assert set(left) == {"data/gaia_clean.csv", "results/figure_spec.json", "results/brightest.csv"}
    shipped = {c["path"] for c in packed.manifest["contents"]}
    assert {"results/parallax_bins.csv", "results/estimation_results.json"} <= shipped
    assert left["results/figure_spec.json"]["rebuilt_by"]["by"] == "code/scratch/make_figures.py"
    assert left["results/brightest.csv"]["rebuilt_by"]["kind"] == "written"
    [fig] = [r for r in packed.manifest["rebuild"] if r["path"] == "figure_spec.json"]
    assert fig["output"] and fig["after"] == "clean_gaia.py" and fig["sha256"]
    assert "builds it again with code/scratch/make_figures.py" in pkg.rerun_words(left["results/figure_spec.json"])
    capsys.readouterr()
    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    report = capsys.readouterr().out
    assert "python make_figures.py (data preparation: builds figure_spec.json again" in report
    assert "figure_spec.json: identical to the study's file" in report
    assert "brightest.csv: identical to the study's file" in report
    assert "Reproduced: every compared value is identical" in report


def test_a_clone_with_left_out_results_verifies_and_reproduces(tmp_path, rerun_here, capsys):
    folder = _export(_gisco_workspace(tmp_path), tmp_path)
    (folder / "design").mkdir(exist_ok=True)
    packed = pkg.build(folder)
    left = {i["path"]: i for i in packed.manifest["left_out"]}
    assert {"results/units.csv", "results/weights.csv", "results/lags.csv", "data/data.db"} <= set(left)
    assert "results/by_group.csv" not in left
    assert left["results/units.csv"]["rebuilt_by"]["by"] == "code/scratch/build_units.py"
    assert left["results/lags.csv"]["rebuilt_by"] == {"by": "code/run_estimation.py", "source": "", "kind": "written"}
    # The clone: the package opened into a plain folder (as `git clone` gives it), e2er-package.json in it.
    clone = tmp_path / "clone"
    pkg.open_package(packed.path, clone)
    assert not (clone / "results" / "units.csv").exists() and (clone / "results" / "by_group.csv").is_file()
    integrity = _check_integrity(clone)
    assert integrity.status == "PASS", integrity.detail
    assert "results/lags.csv" in integrity.detail or "and 1 more" in integrity.detail
    checks = _run_checks(clone, online=False)
    assert not [c for c in checks if c.status == FAIL], [(c.name, c.detail) for c in checks]
    capsys.readouterr()
    assert reproduce(str(clone), yes=True, sandbox=False) == 0
    report = capsys.readouterr().out
    assert "python build_units.py (data preparation: builds units.csv, weights.csv again" in report
    assert "lags.csv: identical to the study's file" in report
    assert "Reproduced: every compared value is identical" in report


def test_verify_skips_a_check_that_needs_a_left_out_file_and_says_so(tmp_path):
    from src.cli_verify import Check, _mentions, _needs

    left = {
        "results/spatial_units.csv": {"source": "gisco", "rebuilt_by": {"by": "code/scratch/build_data.py"}},
        "results/figure_spec.json": {"source": "gaia", "rebuilt_by": None},
    }
    c = _needs("method checks", left, ["results/spatial_units.csv"])
    assert c.status == SKIP
    assert c.detail == (
        "needs results/spatial_units.csv, left out under GISCO terms; run `e2er reproduce` to rebuild it"
    )
    failed = Check("results contract", FAIL, "'figures' names fig.pdf but there is no readable figure_spec.json")
    c = _mentions(failed, left)
    assert (
        c.status == SKIP
        and c.detail == "needs results/figure_spec.json, left out under Gaia terms; no recorded step rebuilds it"
    )
    other = Check("numbers", FAIL, "3 of 9 table cells differ")
    assert _mentions(other, left) is other


def test_a_planted_declaration_of_a_results_file_does_not_excuse_it(tmp_path):
    """Only a file the folder's own records say holds restricted rows may be missing as "left out"."""
    folder = _export(_gisco_workspace(tmp_path), tmp_path)
    (folder / "results" / "by_group.csv").unlink()  # an aggregate: it goes up, so it may not be missing
    manifest = {"format": pkg.FORMAT, "left_out": [{"path": "results/by_group.csv", "reason": "planted"}]}
    (folder / pkg.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    check = _check_integrity(folder)
    assert check.status == "FAIL" and "missing (results/by_group.csv)" in check.detail


def test_publish_to_github_keeps_row_level_results_out(tmp_path, rerun_here, monkeypatch, capsys):
    from src.core import platform_client as pc
    from tests.test_publish_github import ID, _clone, _fake_platform, _tree, github  # noqa: F401

    root = tmp_path / "github"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    from tests.test_publish_github import FAKE_GH

    gh = bin_dir / "gh"
    gh = fake_program(gh, FAKE_GH)
    import os

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("E2ER_TEST_GITHUB", "fake")  # a fake gh (src/core/test_guard.py)
    monkeypatch.setenv("FAKE_GH_ROOT", str(root))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.file://{root}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: str(gh) if name == "gh" else None)
    monkeypatch.delenv("E2ER_PURPOSE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    monkeypatch.setattr(pc, "request", _fake_platform(root))
    from src.cli_publish import publish

    folder = _export(_gisco_workspace(tmp_path), tmp_path)
    rc = publish(
        str(folder), **ID, no_db=True, github_repo="ada/demos", github_path="regions", out=str(tmp_path / "e"), yes=True
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    tree = _tree(root / "ada" / "demos.git")
    assert "regions/results/by_group.csv" in tree and "regions/results/estimation_results.json" in tree
    for gone in ("units.csv", "weights.csv", "lags.csv"):
        assert f"regions/results/{gone}" not in tree
        assert f"left out: results/{gone}" in out
    clone = _clone(root / "ada" / "demos.git", tmp_path / "clone")
    checks = _run_checks(clone / "regions", online=False)
    assert not [c for c in checks if c.status == FAIL], [(c.name, c.detail) for c in checks]
    capsys.readouterr()
    assert reproduce(str(clone / "regions"), yes=True, sandbox=False) == 0
    assert "Reproduced: every compared value is identical" in capsys.readouterr().out
