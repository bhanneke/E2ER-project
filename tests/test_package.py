"""The .e2er package: one file that holds a whole study and runs again (`e2er pack`, src/core/export/package.py).

Björn, 2026-10-14: "can we build .e2er packages that export everything and make
runs reproducible, like zip but built in with everything?" A package is
checked file by file before anything reads it, never runs anything when it is
opened, and `e2er reproduce` on it runs the study's code again, also when a
source's terms kept the data out (the recipe loads them again).
"""

# ruff: noqa: F811 — the fixtures imported from test_browser_setup are test parameters here
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from src.cli_package import inspect, pack_folder, unpack
from src.cli_reproduce import reproduce
from src.cli_verify import verify
from src.core import reproduce as rp
from src.core.export import package as pkg
from src.core.export.structured import export_paper
from src.core.specialists.post_execution import _run_recorded

from .test_browser_setup import live_db, session  # noqa: F401 — fixtures

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

#: e2er-data as get_data.py calls it: loads the table it is asked for, offline.
FAKE_E2ER_DATA = """\
import json, os, sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
table = args[args.index("--table") + 1]
ws = Path(os.environ["E2ER_WORKSPACE_ROOT"]) / args[args.index("--paper-id") + 1]
con = sqlite3.connect(ws / "data.db")
if table == "rates_raw":
    con.execute(f'CREATE TABLE "{table}" (location TEXT, spatial_type TEXT, value REAL)')
    con.executemany(f'INSERT INTO "{table}" VALUES (?,?,?)', json.loads(os.environ["FAKE_RATES"]))
else:
    con.execute(f'CREATE TABLE "{table}" (iso3 TEXT, name TEXT)')
    con.executemany(f'INSERT INTO "{table}" VALUES (?,?)', json.loads(os.environ["FAKE_NAMES"]))
con.commit()
print(json.dumps({"table": table, "rows": con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}))
"""

FAKE_LOCK = "numpy==2.5.4 \\\n    --hash=sha256:" + "a" * 64 + "\n"


def _workspace(tmp_path: Path, *, restricted: bool) -> Path:
    """A finished study: rates loaded from a source (the GMD when ``restricted``), cleaned, estimated."""
    ws = tmp_path / "workspaces" / ("2026-10-14-gmd" if restricted else "2026-10-14-wb")
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": "p-pack", "title": "Road deaths"}), encoding="utf-8")
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE rates_raw (location TEXT, spatial_type TEXT, value REAL)")
    con.executemany("INSERT INTO rates_raw VALUES (?,?,?)", RATES)
    con.execute("CREATE TABLE country_names (iso3 TEXT, name TEXT)")
    con.executemany("INSERT INTO country_names VALUES (?,?)", NAMES)
    con.commit()
    con.close()
    if restricted:
        first = {
            "connector": "gmd",
            "table": "rates_raw",
            "variables": ["rGDP"],
            "series": "rGDP",
            "countries": ["AAA", "BBB", "CCC"],
            "version": "2025_01",
            "dataset": "Global Macro Database",
        }
    else:
        first = {
            "connector": "worldbank",
            "table": "rates_raw",
            "dataset": "World Development Indicators",
            "series": "rates_raw",
            "request": {"command": "series", "indicator": "SH.STA.TRAF.P5"},
        }
    loads = [
        {**first, "retrieved_at": "2026-10-13T21:10:05Z"},
        {
            "connector": "naturalearth",
            "table": "country_names",
            "dataset": "Natural Earth",
            "series": "country_names",
            "request": {"command": "countries", "scale": "50m"},
            "retrieved_at": "2026-10-13T21:10:05Z",
        },
    ]
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8")
    for name, text in (("clean_rates.py", CLEAN), ("run_estimation.py", ESTIMATE)):
        (ws / name).write_text(text, encoding="utf-8")
        assert _run_recorded(ws, ws / name, 60, by="e2er-run") == 0
    return ws


@pytest.fixture
def offline_lock(monkeypatch):
    """The lock without the internet: a fixed answer for `uv pip compile`."""
    calls: list[tuple[str, str]] = []

    def lock(requirements: Path, python_minor: str, as_of: str):
        calls.append((python_minor, as_of))
        return FAKE_LOCK, ""

    monkeypatch.setattr(pkg, "uv_lock", lock)
    return calls


@pytest.fixture
def rerun_here(monkeypatch, tmp_path):
    """`e2er reproduce` with the tests' interpreter and an e2er-data that loads the tables offline."""
    fake = tmp_path / "e2er-data"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_E2ER_DATA, encoding="utf-8")
    fake.chmod(0o755)
    seen: list[dict] = []

    def make_environment(run_dir, recipe, folder, logs):
        seen.append(dict(recipe))
        return Path(sys.executable), {"python": sys.version.split()[0], "packages": {}, "installer": "tests"}

    real_step_env = rp.step_env

    def step_env(venv_python, run_dir=None):
        env = real_step_env(venv_python, run_dir)
        env.update({"E2ER_DATA": str(fake), "FAKE_RATES": json.dumps(RATES), "FAKE_NAMES": json.dumps(NAMES)})
        return env

    monkeypatch.setattr(rp, "make_environment", make_environment)
    monkeypatch.setattr(rp, "step_env", step_env)
    return seen


def _export(tmp_path: Path, *, restricted: bool = False) -> Path:
    return export_paper(_workspace(tmp_path, restricted=restricted), tmp_path / "exports", date_str="20261014")


# ── pack → verify → reproduce ───────────────────────────────────────────────


def test_a_package_verifies_and_reproduces_like_its_folder(tmp_path, offline_lock, rerun_here, capsys):
    folder = _export(tmp_path)
    packed = pkg.build(folder)
    assert packed.path == folder.parent / f"{folder.name}.e2er"
    m = packed.manifest
    assert m["format"] == "e2er-package/1" and m["fingerprint"].startswith("sha256:")
    assert m["left_out"] == []
    assert m["recipe"]["present"] and [s["run"][-1] for s in m["recipe"]["steps"]][-1] == "run_estimation.py"
    assert m["environment"]["lock"] == pkg.LOCK and m["environment"]["hashes"] is True
    assert offline_lock == [(m["environment"]["python"], "2026-10-15")], "resolved as of the export's day"
    paths = {c["path"] for c in m["contents"]}
    assert {"data/data.db", "reproduce.json", "provenance.json", pkg.LOCK} <= paths
    with zipfile.ZipFile(packed.path) as zf:
        names = zf.namelist()
        assert names[0] == pkg.MANIFEST and names[1:] == sorted(names[1:])
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in zf.infolist())

    capsys.readouterr()
    folder_code = verify(str(folder), json_output=True)
    folder_checks = json.loads(capsys.readouterr().out)["checks"]
    package_code = verify(str(packed.path), json_output=True)
    package_checks = json.loads(capsys.readouterr().out)["checks"]
    assert package_code == folder_code
    assert package_checks[0]["name"] == "package" and package_checks[0]["status"] == "PASS"
    assert [(c["name"], c["status"]) for c in package_checks[1:]] == [(c["name"], c["status"]) for c in folder_checks]

    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    report = capsys.readouterr().out
    assert "match e2er-package.json" in report
    assert "Reproduced: every compared value is identical" in report
    assert rerun_here[-1]["requirements"] == pkg.LOCK, "the rerun installs from the package's lock"
    assert "wheelhouse" not in rerun_here[-1]


def test_a_study_with_restricted_data_packs_without_it_and_reproduces_by_rebuilding(
    tmp_path, offline_lock, rerun_here, capsys
):
    folder = _export(tmp_path, restricted=True)
    packed = pkg.build(folder)
    [left] = packed.manifest["left_out"]
    assert left["path"] == "data/data.db"
    assert "Global Macro Database" in left["reason"]
    assert left["rebuilt_by"]["by"] == "code/get_data.py"
    with zipfile.ZipFile(packed.path) as zf:
        assert "data/data.db" not in zf.namelist()
        assert "code/get_data.py" in zf.namelist()

    capsys.readouterr()
    assert inspect(str(packed.path)) == 0
    shown = capsys.readouterr().out
    assert "left out: data/data.db" in shown
    assert "loads the tables " in shown and " again from the sources with code/get_data.py" in shown

    verify(str(packed.path))
    out = capsys.readouterr().out
    assert "[PASS] integrity" in out and "1 data file(s) left out of the package (data/data.db)" in out

    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    report = capsys.readouterr().out
    assert "python get_data.py" in report and "2. python clean_rates.py (data preparation" in report
    assert "not run" not in report.split("Steps:")[1].split("Inputs")[0], "the preparation ran: data.db was rebuilt"
    assert "Reproduced: every compared value is identical" in report


def test_no_data_leaves_every_data_file_out_and_says_what_cannot_be_rebuilt(tmp_path, offline_lock):
    folder = _export(tmp_path)
    packed = pkg.build(folder, tmp_path / "out.e2er", no_data=True)
    [left] = packed.manifest["left_out"]
    # The open sources' tables are loaded again and the study's own step builds rates_clean (e2er after 0.17.1).
    assert left["kind"] == "no_data" and left["rebuilt_by"]["by"] == "code/get_data.py"
    assert left["loads"] == ["country_names", "rates_raw"]
    assert left["builds"] == [{"by": "code/scratch/clean_rates.py", "what": ["rates_clean"]}]
    assert not any("cannot rebuild it" in n for n in packed.notes)
    # A recipe without those steps (an export before 0.17.1): nothing gets it back, and the package says so.
    recipe = json.loads((folder / "reproduce.json").read_text(encoding="utf-8"))
    recipe["steps"] = [s for s in recipe["steps"] if s["run"][-1] == "run_estimation.py"]
    recipe.pop("database")
    for item in recipe["inputs"]:
        item.pop("reload", None)
    (folder / "reproduce.json").write_text(json.dumps(recipe), encoding="utf-8")
    packed = pkg.build(folder, tmp_path / "old.e2er", no_data=True)
    [left] = packed.manifest["left_out"]
    assert {k: v for k, v in left.items() if k != "content"} == {
        "path": "data/data.db",
        "reason": "packed with --no-data",
        "kind": "no_data",
        "rebuilt_by": None,
        "needed": True,
    }
    assert left["content"]["tables"], "the package records the rows it left out, for the rerun's comparison"
    assert any("cannot rebuild it" in n for n in packed.notes)
    assert "data/data_sources.json" in {c["path"] for c in packed.manifest["contents"]}, "the records stay"


def test_restricted_data_the_code_does_not_read_is_left_out_without_a_warning(tmp_path):
    """The Gaia demo: data.db holds the Gaia load, the estimation reads a CSV; a rerun does not need data.db."""
    folder = tmp_path / "study"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "data.db").write_bytes(b"db")
    loads = [{"connector": "gaia", "table": "gaia_dr3", "version": "DR3"}]
    (folder / "data" / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8")
    files = {"data/data.db": folder / "data" / "data.db"}
    [item] = pkg.left_out_data(folder, files, {"files": {}, "inputs": []}, no_data=False)
    assert item["path"] == "data/data.db" and "Gaia" in item["reason"]
    assert item["needed"] is False and item["rebuilt_by"] is None
    assert pkg.rerun_words(item) == "the study's code does not read it, so a rerun does not need it"


def test_unpack_then_verify_the_folder(tmp_path, offline_lock, capsys):
    folder = _export(tmp_path)
    packed = pkg.build(folder)
    dest = tmp_path / "unpacked"
    assert unpack(str(packed.path), str(dest)) == 0
    assert (dest / pkg.MANIFEST).is_file() and (dest / pkg.LOCK).is_file()
    for p in dest.rglob("*"):
        if p.is_file():
            assert not (p.stat().st_mode & stat.S_IXUSR), f"{p} came out executable"
    capsys.readouterr()
    assert verify(str(dest), json_output=True) == verify(str(folder), json_output=True)
    assert unpack(str(packed.path), str(dest)) == 1, "never into a folder that is not empty"
    assert "not empty" in capsys.readouterr().out


# ── determinism ─────────────────────────────────────────────────────────────


def test_the_same_export_packs_to_the_same_bytes(tmp_path, offline_lock):
    folder = _export(tmp_path)
    a = pkg.build(folder, tmp_path / "a.e2er")
    # The same folder elsewhere, with other file times and another listing order on disk.
    other = tmp_path / "elsewhere" / folder.name
    shutil.copytree(folder, other)
    for p in other.rglob("*"):
        os.utime(p, (1_000_000_000, 1_000_000_000))
    b = pkg.build(other, tmp_path / "b.e2er")
    assert a.manifest["fingerprint"] == b.manifest["fingerprint"]
    assert a.path.read_bytes() == b.path.read_bytes()
    with zipfile.ZipFile(a.path) as zf:
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    # A changed file changes the fingerprint.
    (other / "README.md").write_text("changed\n", encoding="utf-8")
    assert pkg.build(other, tmp_path / "c.e2er").manifest["fingerprint"] != a.manifest["fingerprint"]


# ── tampering ───────────────────────────────────────────────────────────────


def _rewrite(
    src: Path,
    dst: Path,
    *,
    replace: dict[str, bytes] | None = None,
    drop: str = "",
    add: dict[str, bytes] | None = None,
) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename == drop:
                continue
            data = (replace or {}).get(info.filename, zin.read(info.filename))
            zout.writestr(info.filename, data)
        for name, data in (add or {}).items():
            zout.writestr(name, data)
    return dst


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"replace": {"results/estimation_results.json": None}}, "results/estimation_results.json does not match"),
        ({"replace": {"README.md": b"# Other study\n"}}, "README.md does not match"),
        ({"drop": "code/run_estimation.py"}, "code/run_estimation.py is missing from the package"),
        ({"add": {"code/extra.py": b"print(1)\n"}}, "code/extra.py is in the package but not in e2er-package.json"),
    ],
)
def test_a_tampered_package_is_refused_naming_the_file(tmp_path, offline_lock, capsys, change, words):
    folder = _export(tmp_path)
    packed = pkg.build(folder)
    if "replace" in change and None in change["replace"].values():
        name = next(iter(change["replace"]))
        with zipfile.ZipFile(packed.path) as zf:
            data = bytearray(zf.read(name))
        data[data.index(b"1")] = ord("9")  # same size, other bytes
        change = {"replace": {name: bytes(data)}}
    bad = _rewrite(packed.path, tmp_path / "bad.e2er", **change)
    capsys.readouterr()
    assert verify(str(bad)) == 1
    err = capsys.readouterr().err
    assert "the package is not intact" in err and words in err
    assert reproduce(str(bad), yes=True, sandbox=False) == 2
    assert words in capsys.readouterr().out
    assert unpack(str(bad), str(tmp_path / "u")) == 1
    assert not (tmp_path / "u").exists(), "a refused package leaves nothing behind"


def test_an_edited_manifest_is_refused(tmp_path, offline_lock):
    folder = _export(tmp_path)
    packed = pkg.build(folder)
    with zipfile.ZipFile(packed.path) as zf:
        manifest = json.loads(zf.read(pkg.MANIFEST))
    manifest["contents"][0]["sha256"] = "0" * 64
    bad = _rewrite(packed.path, tmp_path / "bad.e2er", replace={pkg.MANIFEST: json.dumps(manifest).encode()})
    with pytest.raises(pkg.PackageError, match="fingerprint .* does not match its own list"):
        pkg.open_package(bad, tmp_path / "u")


# ── unsafe archives ─────────────────────────────────────────────────────────


def _package(path: Path, files: dict[str, bytes], *, link: str = "") -> Path:
    """A package whose manifest lists ``files`` honestly (so only the safety checks can refuse it)."""
    import hashlib

    contents = [{"path": n, "sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)} for n, d in files.items()]
    manifest = {"format": pkg.FORMAT, "contents": contents, "fingerprint": pkg.fingerprint(contents)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pkg.MANIFEST, json.dumps(manifest))
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if name == link:
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, data)
    return path


@pytest.mark.parametrize(
    ("files", "link", "words"),
    [
        ({"/etc/passwd": b"x"}, "", "is an absolute path"),
        ({"../escape.txt": b"x"}, "", "leaves the folder"),
        ({"code/../../escape.txt": b"x"}, "", "leaves the folder"),
        ({"C:/Windows/x": b"x"}, "", "is an absolute path"),
        ({"code\\x.py": b"x"}, "", "backslash"),
        ({"code/link": b"/etc/passwd"}, "code/link", "symbolic link"),
        ({"README.md": b"a", "readme.md": b"b"}, "", "twice"),
    ],
)
def test_unsafe_archives_are_refused_before_anything_is_written(tmp_path, files, link, words):
    bad = _package(tmp_path / "bad.e2er", files, link=link)
    dest = tmp_path / "out"
    with pytest.raises(pkg.PackageError, match=words):
        pkg.open_package(bad, dest)
    assert not dest.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_a_zip_bomb_and_an_oversized_package_are_refused(tmp_path, monkeypatch):
    bomb = _package(tmp_path / "bomb.e2er", {"data/zeros.bin": b"\0" * (4 << 20)})
    monkeypatch.setattr(pkg, "MAX_RATIO", 50)
    with pytest.raises(pkg.PackageError, match="times its packed size"):
        pkg.open_package(bomb, tmp_path / "a")
    monkeypatch.setattr(pkg, "MAX_RATIO", 10**9)
    with pytest.raises(pkg.PackageError, match="unpacks to more than"):
        pkg.open_package(bomb, tmp_path / "b", max_total=1 << 20)
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_a_file_that_is_not_a_package_is_said_so(tmp_path, capsys):
    plain = tmp_path / "x.e2er"
    plain.write_bytes(b"not a zip")
    assert verify(str(plain)) == 1
    assert "not a readable .e2er package" in capsys.readouterr().err
    other = tmp_path / "y.e2er"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("README.md", "hi")
    with pytest.raises(pkg.PackageError, match="no e2er-package.json"):
        pkg.read_manifest(other)


def test_a_folder_with_a_symbolic_link_is_not_packed(tmp_path, offline_lock):
    folder = _export(tmp_path)
    (folder / "code" / "link.py").symlink_to(folder / "code" / "run_estimation.py")
    with pytest.raises(pkg.PackageError, match="symbolic links"):
        pkg.build(folder)


# ── offline wheels ──────────────────────────────────────────────────────────


def _fake_wheels(names: list[str]):
    got: list[tuple[Path, str, Path]] = []

    def download(requirements: Path, python_minor: str, dest: Path):
        got.append((requirements, python_minor, dest))
        dest.mkdir(parents=True, exist_ok=True)
        for n in names:
            (dest / n).write_bytes(b"wheel " + n.encode())
        return sorted(dest.glob("*.whl")), ""

    return download, got


def test_offline_packs_the_wheels_for_this_computer_and_the_rerun_installs_from_them(
    tmp_path, offline_lock, rerun_here, capsys
):
    folder = _export(tmp_path)
    download, got = _fake_wheels(["numpy-2.5.4-cp312-cp312-macosx_14_0_arm64.whl"])
    packed = pkg.build(folder, offline=True, downloader=download)
    [(requirements, python_minor, _dest)] = got
    assert requirements.name == "requirements.lock.txt", "the wheels of the locked set"
    key = pkg.platform_key(python_minor)
    wheels = packed.manifest["wheels"]
    assert wheels["platform"] == key and wheels["files"] == 1 and wheels["folder"] == f"{pkg.WHEELS}/{key}"
    assert f"{pkg.WHEELS}/{key}/numpy-2.5.4-cp312-cp312-macosx_14_0_arm64.whl" in {
        c["path"] for c in packed.manifest["contents"]
    }
    capsys.readouterr()
    assert verify(str(packed.path)) in (0, 1)
    assert "unlisted" not in capsys.readouterr().out, "the package's own files are not the study's"

    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    assert rerun_here[-1]["wheelhouse"] == f"{pkg.WHEELS}/{key}"


def test_wheels_for_another_computer_are_not_used(tmp_path, offline_lock, rerun_here, capsys, monkeypatch):
    folder = _export(tmp_path)
    download, _ = _fake_wheels(["x-1-py3-none-any.whl"])
    packed = pkg.build(folder, offline=True, downloader=download)
    monkeypatch.setattr(pkg, "platform_key", lambda python_minor: "win32-x86_64-py" + python_minor)
    capsys.readouterr()
    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    assert "the packages are downloaded" in capsys.readouterr().out
    assert "wheelhouse" not in rerun_here[-1]


def test_the_environment_installs_offline_from_the_wheels(tmp_path, monkeypatch):
    """make_environment adds --no-index --find-links <wheels> when the package's wheels fit this computer."""
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd, env, timeout, log):
        calls.append(argv)
        return (0, "") if len(calls) == 1 else (1, "stopped by the test")

    monkeypatch.setattr(rp, "_run", fake_run)
    folder = tmp_path / "study"
    (folder / "e2er-package" / "wheels" / "k").mkdir(parents=True)
    (folder / "req.txt").write_text("x==1\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recipe = {"requirements": "req.txt", "wheelhouse": "e2er-package/wheels/k"}
    with pytest.raises(rp.RecipeError):
        rp.make_environment(run_dir, recipe, folder, tmp_path)
    install = calls[1]
    i = install.index("--find-links")
    assert "--no-index" in install and install[i + 1] == str((folder / "e2er-package" / "wheels" / "k").resolve())


def test_a_wheelhouse_named_in_reproduce_json_is_ignored(tmp_path, rerun_here, capsys):
    """Only e2er sets where the wheels are: a recipe cannot point the installer at a folder of its own."""
    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    (folder / "results").mkdir()
    (folder / "code" / "run.py").write_text('import json; json.dump({"a": 1}, open("r.json", "w"))\n', encoding="utf-8")
    (folder / "code" / "requirements.txt").write_text("\n", encoding="utf-8")
    (folder / "results" / "r.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "reproduce.json").write_text(
        json.dumps(
            {
                "schema": rp.SCHEMA,
                "requirements": "code/requirements.txt",
                "files": {"run.py": "code/run.py"},
                "steps": [{"run": ["python", "run.py"]}],
                "compare": [{"published": "results/r.json", "produced": "r.json"}],
                "wheelhouse": "../../somewhere",
            }
        ),
        encoding="utf-8",
    )
    assert reproduce(str(folder), yes=True, sandbox=False) == 0
    assert "wheelhouse" not in rerun_here[-1]


def test_without_the_internet_the_package_keeps_the_recipes_pins(tmp_path, monkeypatch):
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "the packages could not be resolved (offline)"))
    folder = _export(tmp_path)
    packed = pkg.build(folder)
    env = packed.manifest["environment"]
    assert env["lock"] is None and env["hashes"] is False
    assert "code/requirements.txt (the study's own pins, without hashes)" in env["note"]
    assert pkg.LOCK not in {c["path"] for c in packed.manifest["contents"]}


# ── the command line ────────────────────────────────────────────────────────


def test_pack_and_inspect_print_a_plain_summary(tmp_path, offline_lock, capsys):
    folder = _export(tmp_path)
    assert pack_folder(folder, str(tmp_path / "s.e2er"), offline=False, no_data=False) == 0
    out = capsys.readouterr().out
    assert "Packed →" in out and "fingerprint sha256:" in out
    assert inspect(str(tmp_path / "s.e2er")) == 0
    out = capsys.readouterr().out
    for bit in (
        "Title:",
        "Authors:",
        "e2er version: packed with",
        "Data:",
        "included: data/data.db",
        "Size:",
        "Fingerprint: sha256:",
    ):
        assert bit in out
    assert pack_folder(tmp_path / "nothing", None, offline=False, no_data=False) == 1
    assert "is not a folder" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "words"),
    [
        (["pack", "--help"], ["--offline", "--no-data", "-o", "one .e2er file"]),
        (["unpack", "--help"], ["Nothing is run", "no link"]),
        (["inspect", "--help"], ["fingerprint"]),
        (["verify", "--help"], [".e2er package"]),
        (["reproduce", "--help"], [".e2er package"]),
        (["export", "--help"], ["--package"]),
    ],
)
def test_help_texts(argv, words):
    out = subprocess.run(
        [sys.executable, "-m", "src", *argv], capture_output=True, text=True, timeout=120, check=True
    ).stdout
    flat = " ".join(out.split())
    for w in words:
        assert w in flat, (w, out)


def test_the_package_manifest_is_valid_json_in_the_zip(tmp_path, offline_lock):
    folder = _export(tmp_path)
    packed = pkg.build(folder)
    with zipfile.ZipFile(packed.path) as zf:
        manifest = json.load(io.BytesIO(zf.read(pkg.MANIFEST)))
    for key in (
        "format",
        "e2er_version",
        "study",
        "created",
        "contents",
        "fingerprint",
        "left_out",
        "recipe",
        "environment",
        "wheels",
    ):
        assert key in manifest
    assert manifest["created"] == "20261014", "the export's date: the same export packs to the same bytes"
    assert all(set(c) == {"path", "sha256", "bytes", "part"} for c in manifest["contents"])


# ── the dashboard ───────────────────────────────────────────────────────────


def test_the_finish_page_offers_the_package_for_download(live_db, session, offline_lock):
    import asyncio
    import uuid

    from fastapi.testclient import TestClient

    from src.api.app import app
    from src.db.client import execute

    from .test_browser_setup import BASE, TOKEN

    pid = str(uuid.uuid4())
    ws = _workspace(live_db, restricted=False)
    manifest = json.loads((ws / "manifest.json").read_text(encoding="utf-8"))
    (ws / "manifest.json").write_text(json.dumps({**manifest, "paper_id": pid}), encoding="utf-8")
    bundle = export_paper(ws, live_db / "exports", date_str="20261014")
    asyncio.run(
        execute(
            "INSERT INTO papers (id, title, research_question, status, workspace, mode, methodology, pipeline) "
            "VALUES (%(id)s, 'Road deaths', 'Q?', 'completed', %(ws)s, 'single_pass', 'empirical', 'empirical')",
            {"id": pid, "ws": str(ws)},
        )
    )
    c = TestClient(app, base_url=BASE, client=("127.0.0.1", 5))
    page = c.get(f"/papers/{pid}/finish").text
    assert "Download package (.e2er)" in page
    assert c.post(f"/api/papers/{pid}/package").status_code == 403, "needs the session"
    c.cookies.set("e2er_session_8290", TOKEN)
    assert c.get(f"/api/papers/{pid}/package").status_code == 404, "not written yet"
    d = c.post(f"/api/papers/{pid}/package").json()
    assert d["name"] == f"{bundle.name}.e2er" and d["fingerprint"].startswith("sha256:")
    r = c.get(d["download"])
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert f'filename="{bundle.name}.e2er"' in r.headers["content-disposition"]


# ── no temporary folders left behind ────────────────────────────────────────


def _leftovers(tmp: Path) -> list[str]:
    return sorted(p.name for p in tmp.iterdir() if p.name.startswith(("e2er-reproduce-", "e2er-package-")))


@pytest.mark.parametrize("tamper", [False, True])
def test_reproduce_removes_its_temporary_folders_also_after_a_failure(
    tmp_path, offline_lock, rerun_here, capsys, tamper
):
    """Each kept run folder held a whole environment (up to ~140 MB); failing runs piled up until the disk was full."""
    import tempfile

    folder = _export(tmp_path)
    packed = pkg.build(folder)
    if tamper:  # the rerun differs from the published results (recorded as a change): a failure
        from src.core.export.provenance import amend

        res = folder / "results" / "estimation_results.json"
        doc = json.loads(res.read_text(encoding="utf-8"))
        doc["main"]["mean"] += 1
        res.write_text(json.dumps(doc), encoding="utf-8")
        amend(folder, "results/estimation_results.json", "edited", at="x")
    tmp = Path(tempfile.gettempdir())
    assert reproduce(str(packed.path), yes=True, sandbox=False) == 0
    assert reproduce(str(folder), yes=True, sandbox=False) == (1 if tamper else 0)
    out = capsys.readouterr().out
    assert _leftovers(tmp) == [], out
    assert "is kept" not in out and "--keep keeps it" in out
    bad = _rewrite(packed.path, tmp_path / "bad.e2er", replace={"README.md": b"# other\n"})
    assert reproduce(str(bad), yes=True, sandbox=False) == 2
    assert _leftovers(tmp) == []


def test_keep_keeps_both_folders_and_says_where(tmp_path, offline_lock, rerun_here, capsys):
    import tempfile

    folder = _export(tmp_path)
    packed = pkg.build(folder)
    assert reproduce(str(packed.path), keep=True, yes=True, sandbox=False) == 0
    out = capsys.readouterr().out
    left = _leftovers(Path(tempfile.gettempdir()))
    assert len(left) == 2 and "The run folder is kept:" in out and "The unpacked package is kept:" in out
    for name in left:
        shutil.rmtree(Path(tempfile.gettempdir()) / name)
