"""Data built from a source with terms inherit its terms (src/core/derived_data.py).

The Gaia demo (2026-10-14): data/gaia_clean.csv, the cleaned Gaia rows, was packed
and would be published as a file "the study's code reads", although Gaia's terms
keep the rows themselves out. A file a script writes from restricted data is now
restricted too (transitively): `e2er pack` leaves it out with the reason, the
recipe builds it again on reproduce, and `e2er publish` treats it like the
source's own data. And an e2er-package.json planted in a plain folder no longer
turns a missing data file into "left out".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.cli_verify import _check_integrity, verify
from src.core import data_terms
from src.core import derived_data as dd
from src.core import reproduce as rp
from src.core.export import package as pkg
from src.core.export.structured import export_paper
from src.core.specialists.post_execution import _run_recorded

RAW_ROWS = "source_id,parallax,ruwe\n1,7.3,1.0\n2,7.4,2.0\n3,7.2,1.1\n4,0.5,1.0\n"

CLEAN = """\
import csv

RAW = "data/gaia_dr3.csv"
CLEAN = "data/gaia_clean.csv"
rows = [r for r in csv.DictReader(open(RAW)) if float(r["ruwe"]) < 1.4]
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
clean = [float(r["parallax"]) for r in csv.DictReader(open(CLEAN))]
members = [p for p in clean if p > 5]
out = {"main": {"n_raw": n_raw, "n_clean": len(clean), "n_members": len(members),
                "mean_parallax": sum(members) / len(members)}}
with open("estimation_results.json", "w") as f:
    json.dump(out, f, indent=2)
"""

#: e2er-data as get_data.py calls it: saves the Gaia rows again (offline).
FAKE_E2ER_DATA = """\
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
name = args[args.index("--save-to") + 1]
(ws / "data").mkdir(exist_ok=True)
(ws / "data" / name).write_text(os.environ["FAKE_GAIA"])
print(json.dumps({"saved_to": "data/" + name}))
"""


def _gaia_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "2026-10-14-pleiades"
    (ws / "data").mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-gaia", "title": "Pleiades"}), encoding="utf-8")
    (ws / "data" / "gaia_dr3.csv").write_text(RAW_ROWS, encoding="utf-8")
    load = {
        "connector": "gaia",
        "dataset": "Gaia Data Release 3",
        "series": "Gaia archive ADQL query",
        "version": "DR3",
        "saved_to": "data/gaia_dr3.csv",
        "request": {"command": "query", "adql": "SELECT source_id, parallax, ruwe FROM gaiadr3.gaia_source"},
        "retrieved_at": "2026-10-13T21:02:56Z",
    }
    (ws / "data_sources.json").write_text(json.dumps({"loads": [load]}), encoding="utf-8")
    for name, text in (("clean_gaia.py", CLEAN), ("run_estimation.py", ESTIMATE)):
        (ws / name).write_text(text, encoding="utf-8")
        assert _run_recorded(ws, ws / name, 60, by="e2er-run") == 0
    return ws


@pytest.fixture
def rerun_here(monkeypatch, tmp_path):
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)

    def make_environment(run_dir, recipe, folder, logs):
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    real_step_env = rp.step_env

    def step_env(venv_python, run_dir=None):
        env = real_step_env(venv_python, run_dir)
        env.update({"E2ER_DATA": str(fake), "FAKE_GAIA": RAW_ROWS})
        return env

    monkeypatch.setattr(rp, "make_environment", make_environment)
    monkeypatch.setattr(rp, "step_env", step_env)
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))


def test_a_file_built_from_restricted_data_is_restricted_too(tmp_path):
    folder = export_paper(_gaia_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    [d] = dd.kept_out(folder)
    assert d.path == "data/gaia_clean.csv" and d.connectors == ["gaia"]
    # The estimates are built from the Gaia rows too, but are an aggregate of them (derived_rows.py).
    assert {x.path for x in dd.derived(folder)} == {"data/gaia_clean.csv", "results/estimation_results.json"}
    assert d.writers == ["code/scratch/clean_gaia.py"]
    [use] = data_terms.uses(folder)
    assert use.files == ["data/gaia_clean.csv"]
    assert not (folder / "data" / "gaia_dr3.csv").exists(), "export never ships the raw Gaia rows"
    assert use.reason("data/gaia_clean.csv").startswith("built from ") and "Gaia" in use.reason("data/gaia_clean.csv")
    assert "whose terms do not allow passing it on" in use.reason("data/gaia_clean.csv")
    # The recipe written at export builds it again when the folder lacks it.
    recipe = json.loads((folder / "reproduce.json").read_text(encoding="utf-8"))
    [item] = [i for i in recipe["inputs"] if i["path"] == "data/gaia_clean.csv"]
    assert item["rebuild"] == "clean_gaia.py"
    assert [s["run"][-1] for s in recipe["steps"]] == ["get_data.py", "clean_gaia.py", "run_estimation.py"]
    assert recipe["steps"][1]["when_missing"] == ["data/gaia_clean.csv"]
    assert dd.cannot_rebuild(folder) == []


def test_the_package_leaves_derived_data_out_and_the_rerun_builds_it_again(tmp_path, rerun_here, capsys):
    folder = export_paper(_gaia_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    packed = pkg.build(folder)
    left = {i["path"]: i for i in packed.manifest["left_out"]}
    assert set(left) == {"data/gaia_clean.csv"}
    assert left["data/gaia_clean.csv"]["reason"].startswith("built from ")
    assert left["data/gaia_clean.csv"]["rebuilt_by"]["by"] == "code/scratch/clean_gaia.py"
    capsys.readouterr()
    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    report = capsys.readouterr().out
    assert "2. python clean_gaia.py (data preparation: builds data/gaia_clean.csv again" in report
    assert "2 of 2 identical" in report
    assert "Reproduced: every compared value is identical" in report


def test_an_older_export_gets_the_rebuild_step_from_the_package(tmp_path, rerun_here, capsys):
    """An export from before 0.16.2 has no "rebuild" in its recipe: the package's manifest supplies it."""
    folder = export_paper(_gaia_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    path = folder / "reproduce.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    recipe["steps"] = [s for s in recipe["steps"] if not s.get("when_missing")]
    for i in recipe["inputs"]:
        i.pop("rebuild", None)
    path.write_text(json.dumps(recipe), encoding="utf-8")
    packed = pkg.build(folder)
    assert packed.manifest["rebuild"] == [
        {"path": "data/gaia_clean.csv", "script": "clean_gaia.py", "from": "code/scratch/clean_gaia.py"}
    ]
    capsys.readouterr()
    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    assert "Reproduced: every compared value is identical" in capsys.readouterr().out


def test_derived_data_is_found_transitively_and_unrelated_files_are_not(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "code").mkdir()
    loads = [{"connector": "yfinance", "saved_to": "data/prices.csv"}]
    (tmp_path / "data" / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8")
    for name in ("prices.csv", "returns.csv", "panel.parquet", "weather.csv"):
        (tmp_path / "data" / name).write_text("x\n", encoding="utf-8")
    (tmp_path / "code" / "a.py").write_text(
        'import os\nimport pandas as pd\nIN = os.path.join("data", "prices.csv")\n'
        'pd.read_csv(IN).pct_change().to_csv("data/returns.csv")\n',
        encoding="utf-8",
    )
    (tmp_path / "code" / "b.py").write_text(
        'import pandas as pd\nfrom pathlib import Path\nOUT = Path("data") / "panel.parquet"\n'
        'pd.read_csv("data/returns.csv").to_parquet(OUT)\n',
        encoding="utf-8",
    )
    (tmp_path / "code" / "c.py").write_text(
        'import pandas as pd\npd.read_csv("data/raw_weather.csv").to_csv("data/weather.csv")\n', encoding="utf-8"
    )
    found = {d.path: d for d in dd.derived(tmp_path)}
    assert set(found) == {"data/returns.csv", "data/panel.parquet"}
    assert found["data/panel.parquet"].writers == ["code/b.py"]
    assert data_terms.restricted_paths(tmp_path).keys() == {"data/prices.csv", "data/returns.csv", "data/panel.parquet"}


def test_publish_treats_derived_data_like_the_sources_and_says_when_it_cannot_be_built_again(tmp_path, capsys):
    from src.cli_publish import publish
    from tests.test_publish_access import BASE

    folder = export_paper(_gaia_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    assert prov["run"]["derived_data"] == [
        {
            "path": "data/gaia_clean.csv",
            "named": "data/gaia_clean.csv",
            "connectors": ["gaia"],
            "writers": ["code/scratch/clean_gaia.py"],
            "holds_rows": True,
        },
        {
            "path": "results/estimation_results.json",
            "named": "estimation_results.json",
            "connectors": ["gaia"],
            "writers": ["code/run_estimation.py"],
            "holds_rows": False,
        },
    ]
    capsys.readouterr()
    assert publish(str(folder), **BASE, data="public", no_db=True, out=str(tmp_path / "e1"), yes=True) == 1
    out = capsys.readouterr().out
    assert "--accept-data-terms gaia" in out, "public derived data need the same confirmation as the source's"

    # Without the script that builds it, the record of the run still says what it holds, and publish says
    # plainly that a reader without the file cannot run the code again.
    (folder / "code" / "scratch" / "clean_gaia.py").unlink()
    path = folder / "reproduce.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    recipe["steps"] = [st for st in recipe["steps"] if not st.get("when_missing")]
    for i in recipe["inputs"]:
        i.pop("rebuild", None)
    recipe["files"].pop("clean_gaia.py", None)
    path.write_text(json.dumps(recipe), encoding="utf-8")
    from src.core.export.provenance import write_provenance

    write_provenance(
        folder,
        {"paper_id": "p-gaia", "title": "Pleiades"},
        exported_at="20261014",
        derived_data=prov["run"]["derived_data"],
    )
    assert [d.path for d in dd.cannot_rebuild(folder)] == ["data/gaia_clean.csv"]
    assert "data/gaia_clean.csv" in data_terms.uses(folder)[0].files
    capsys.readouterr()
    publish(str(folder), **BASE, data="private", no_db=True, out=str(tmp_path / "e2"), yes=True)
    out = capsys.readouterr().out
    assert "data/gaia_clean.csv is built from ESA Gaia Data Release 3 (Gaia) data" in out
    assert "warning: data/gaia_clean.csv is built from data whose terms keep it out" in out
    assert "cannot run the study's code again" in out


# ── a planted e2er-package.json ─────────────────────────────────────────────


def _plant(folder: Path, left: list[str]) -> None:
    manifest = {
        "format": pkg.FORMAT,
        "left_out": [{"path": p, "reason": "packed with --no-data", "rebuilt_by": None} for p in left],
    }
    (folder / pkg.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def test_a_planted_manifest_does_not_excuse_a_missing_data_file(tmp_path):
    from .test_package import _export

    folder = _export(tmp_path)  # World Bank data: no terms keep it out
    (folder / "data" / "data.db").unlink()
    _plant(folder, ["data/data.db"])
    check = _check_integrity(folder)
    assert check.status == "FAIL" and "1 missing (data/data.db)" in check.detail


def test_a_declaration_the_folders_own_records_support_is_accepted(tmp_path):
    folder = export_paper(_gaia_workspace(tmp_path), tmp_path / "exports", date_str="20261014")
    (folder / "data" / "gaia_clean.csv").unlink()
    _plant(folder, ["data/gaia_clean.csv"])
    check = _check_integrity(folder)
    assert check.status == "PASS", check.detail
    assert "1 data file(s) left out of the package (data/gaia_clean.csv)" in check.detail


def test_a_no_data_package_verifies_but_its_unpacked_folder_does_not(tmp_path, capsys, monkeypatch):
    from .test_package import _export

    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    folder = _export(tmp_path)
    packed = pkg.build(folder, tmp_path / "nd.e2er", no_data=True)
    capsys.readouterr()
    verify(str(packed.path))
    assert "[PASS] integrity" in capsys.readouterr().out, "the package's checked manifest counts"
    dest = tmp_path / "unpacked"
    pkg.open_package(packed.path, dest)
    assert _check_integrity(dest).status == "FAIL", "in a folder, --no-data is not a record of the study's"
