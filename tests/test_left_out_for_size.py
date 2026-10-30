"""Data too large for GitHub stay out when a recorded step gets them back (`e2er publish --github`, `e2er pack`).

The weather-words demo (2026-10-21): its data/data.db is 145 MB, over GitHub's 100 MB limit, and holds
Project Gutenberg texts, which anyone may pass on. Björn: publish the folder without it and let
`e2er reproduce` load the texts again. A data file over the host's limit is left out (``kind: "size"``) when
a step of the study's reproduce.json loads or builds it again; one that nothing gets back is refused. A clone
verifies with the file counted as left out, not missing, and reproduces.

The files here are a few kilobytes; the limit is lowered to just below the database's size.
"""

# ruff: noqa: F811 — the fixtures imported from other test modules are test parameters here
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.cli_publish import publish
from src.cli_reproduce import reproduce
from src.cli_verify import FAIL, _run_checks
from src.core import github_files as gf
from src.core.export import package as pkg
from tests.test_package import _export, rerun_here  # noqa: F401 — fixture
from tests.test_publish_github import ID, _clone, _manifest, _tree, github  # noqa: F401 — fixture


def _put(folder: Path, rel: str, content: bytes) -> None:
    """Write a file of the folder and list it in provenance.json, as export would have."""
    p = folder / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    prov_path = folder / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    prov["files"][rel] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8", newline="\n")


def _open_study(tmp_path: Path, *, reload: bool, prepare: bool = True) -> Path:
    """A study on open data (World Bank, Natural Earth) in data/data.db.

    Export records the steps that get data.db back (e2er after 0.17.1): code/get_data.py loads the open
    sources' tables again, and the study's own step builds rates_clean from them. Without ``reload`` the
    recipe is the one an earlier export wrote (no step loads an open source again); without ``prepare`` the
    step that builds rates_clean is gone.
    """
    folder = _export(tmp_path / "open")
    recipe = json.loads((folder / "reproduce.json").read_text(encoding="utf-8"))
    assert [s["run"][-1] for s in recipe["steps"]] == ["get_data.py", "clean_rates.py", "run_estimation.py"]
    if reload and prepare:
        return folder
    if not reload:
        recipe["steps"] = [s for s in recipe["steps"] if s["run"][-1] == "run_estimation.py"]
        recipe["files"].pop("get_data.py")
        recipe.pop("database")
        for item in recipe["inputs"]:
            item.pop("reload", None)
    else:
        recipe["steps"] = [s for s in recipe["steps"] if "when_missing" not in s]
    _put(folder, "reproduce.json", (json.dumps(recipe, indent=2) + "\n").encode())
    return folder


@pytest.fixture
def small_limit(monkeypatch, tmp_path):
    """GitHub's limit just below the test database (16 kB), above every other file the study could leave out."""
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))

    def set_for(folder: Path) -> int:
        db = (folder / "data" / "data.db").stat().st_size
        limit = db - 1
        others = [
            p
            for p in folder.rglob("*")
            if p.is_file()
            and p.relative_to(folder).as_posix() != "data/data.db"
            and pkg._may_be_left_out(p.relative_to(folder).as_posix())
        ]
        assert all(p.stat().st_size <= limit for p in others)
        monkeypatch.setattr(gf, "GITHUB_FILE_LIMIT", limit)
        monkeypatch.setitem(pkg.HOST_FILE_LIMITS, "GitHub", limit)
        return limit

    return set_for


# ── the rule ─────────────────────────────────────────────────────────────────


def test_a_database_a_recorded_step_loads_again_is_left_out_for_its_size(tmp_path, small_limit):
    folder = _open_study(tmp_path, reload=True)
    limit = small_limit(folder)
    packed = pkg.build(folder, tmp_path / "p.e2er", host="GitHub", max_file_bytes=limit)
    [left] = packed.manifest["left_out"]
    assert left["path"] == "data/data.db" and left["kind"] == "size" and left["host"] == "GitHub"
    assert left["reason"] == "too large for GitHub (16 kB)"
    assert left["bytes"] == (folder / "data" / "data.db").stat().st_size
    assert left["loads"] == ["country_names", "rates_raw"]
    assert left["builds"] == [{"by": "code/scratch/clean_rates.py", "what": ["rates_clean"]}]
    words = pkg.rerun_words(left)
    assert "loads the tables country_names, rates_raw again from the sources with code/get_data.py" in words
    assert "data/data.db" not in {c["path"] for c in packed.manifest["contents"]}
    assert "too large for GitHub" in pkg.summary(packed.manifest)
    # Without a host (`e2er pack`), nothing is left out for its size.
    assert pkg.build(folder, tmp_path / "q.e2er").manifest["left_out"] == []


def test_a_database_no_recorded_step_gets_back_is_refused(tmp_path, small_limit):
    folder = _open_study(tmp_path, reload=False)
    limit = small_limit(folder)
    with pytest.raises(pkg.TooLargeError) as e:
        pkg.build(folder, tmp_path / "p.e2er", host="GitHub", max_file_bytes=limit)
    assert "no recorded step of the study gets these back" in str(e.value)
    assert "data/data.db (16 kB): no step of reproduce.json loads it or builds it again" in str(e.value)
    assert not (tmp_path / "p.e2er").exists()


def test_a_database_whose_built_tables_no_step_builds_again_is_refused(tmp_path, small_limit):
    """get_data.py loads the sources' tables, but nothing builds rates_clean, which the estimation reads."""
    folder = _open_study(tmp_path, reload=True, prepare=False)
    limit = small_limit(folder)
    with pytest.raises(pkg.TooLargeError) as e:
        pkg.build(folder, tmp_path / "p.e2er", host="GitHub", max_file_bytes=limit)
    assert "loads or builds only some of its tables again; no step builds rates_clean" in str(e.value)


def test_the_published_result_is_never_left_out_for_its_size(tmp_path, small_limit, monkeypatch):
    folder = _open_study(tmp_path, reload=True)
    small_limit(folder)
    files = pkg.study_files(folder)
    recipe, _ = pkg._recipe(folder)
    with pytest.raises(pkg.TooLargeError) as e:
        pkg.left_out_data(folder, files, recipe, no_data=False, host="GitHub", max_file_bytes=10)
    assert "results/estimation_results.json (1 kB): it is the published result a rerun is compared with" in str(e.value)


def test_a_declaration_counts_in_a_folder_only_when_provenance_records_the_file_too_large(tmp_path):
    """A clone's e2er-package.json is only a file: "too large" holds when provenance.json says so, at the
    host's real limit (not the declaration's own numbers)."""
    folder = _open_study(tmp_path, reload=True)
    item = {"path": "data/data.db", "kind": "size", "host": "GitHub", "bytes": 10**9, "reason": "too large"}
    assert not pkg.too_large_for_host(folder, item), "provenance.json records 16 kB"
    prov_path = folder / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    prov["files"]["data/data.db"]["bytes"] = 145_076_224
    prov_path.write_text(json.dumps(prov), encoding="utf-8", newline="\n")
    assert pkg.too_large_for_host(folder, item)
    assert not pkg.too_large_for_host(folder, {**item, "host": "Somewhere"})
    assert not pkg.too_large_for_host(folder, {**item, "kind": "terms"})


# ── publish --github → clone → verify → reproduce ────────────────────────────


def test_a_study_too_large_for_github_goes_up_without_it_and_a_clone_verifies_and_reproduces(
    tmp_path, small_limit, github, rerun_here, capsys, monkeypatch
):
    folder = _open_study(tmp_path, reload=True)
    small_limit(folder)
    rc = publish(
        str(folder),
        **ID,
        no_db=True,
        github_repo="ada/demos",
        github_path="roads",
        demonstration=True,
        out=str(tmp_path / "e"),
        yes=True,
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    bare = github / "ada" / "demos.git"
    tree = _tree(bare)
    assert "roads/data/data.db" not in tree and "roads/code/get_data.py" in tree
    assert "left out: data/data.db (too large for GitHub (16 kB)); `e2er reproduce` loads the tables" in out
    m = _manifest(folder)
    assert m["repository"]["left_out"] == [
        {"path": "data/data.db", "reason": "too large for GitHub (16 kB)", "kind": "size"}
    ]
    clone = _clone(bare, tmp_path / "clone") / "roads"
    readme = (clone / "README.md").read_text(encoding="utf-8")
    assert "- `data/data.db`: too large for GitHub (16 kB); `e2er reproduce` loads the tables" in readme

    checks = _run_checks(clone, online=False)
    assert not [c for c in checks if c.status == FAIL], [(c.name, c.detail) for c in checks]
    integrity = next(c for c in checks if c.name == "integrity")
    assert "left out" in integrity.detail and "data/data.db" in integrity.detail

    assert reproduce(str(clone), yes=True, sandbox=False) == 0
    report = capsys.readouterr().out
    assert "python get_data.py" in report and "clean_rates.py (data preparation" in report
    assert "Reproduced: every compared value is identical" in report

    # At GitHub's real limit the 16 kB database is not "too large": the clone's declaration does not hold.
    monkeypatch.setitem(pkg.HOST_FILE_LIMITS, "GitHub", 100 * 1024 * 1024)
    integrity = next(c for c in _run_checks(clone, online=False) if c.name == "integrity")
    assert integrity.status == FAIL and "data/data.db" in integrity.detail


def test_a_study_whose_large_data_nothing_rebuilds_is_refused_and_nothing_is_pushed(
    tmp_path, small_limit, github, capsys
):
    folder = _open_study(tmp_path, reload=False)
    small_limit(folder)
    for dry in (True, False):
        rc = publish(
            str(folder),
            **ID,
            no_db=True,
            github_repo="ada/demos",
            github_path="roads",
            dry_run=dry,
            out=str(tmp_path / "e"),
            yes=True,
        )
        captured = capsys.readouterr()
        said = captured.out + captured.err
        assert rc != 0
        assert "GitHub does not take files larger than" in said and "data/data.db (16 kB)" in said
        assert "Nothing was published or pushed." in said
    assert not (github / "ada").exists(), "no repository was made and nothing was pushed"
    assert not (folder / "e2er.json").exists()
