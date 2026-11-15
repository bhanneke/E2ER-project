"""`e2er reproduce` on a published study whose package leaves a compared result out.

The real test of 2026-11-12 (e2er 0.20.1, nine studies from e2er.org):

* spot-bitcoin-etf-comovement aborted at once: `"compare": results/figure_spec.json is not in the folder`.
  The package leaves that file out under Yahoo Finance's terms (e2er-package.json ``left_out``), so a compare
  entry for it must be reported as not compared, and the verdict reached from the other results.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core.export import package as pkg
from tests.test_reproduce import _study

YAHOO_LEFT_OUT = {
    "kind": "terms",
    "needed": False,
    "path": "results/figure_spec.json",
    "reason": "built from Yahoo Finance data and holds them row by row",
    "rebuilt_by": {"by": "code/scratch/build_panel.py", "kind": "written", "source": ""},
    "source": "yfinance",
}


def _with_left_out_compare(tmp_path: Path) -> Path:
    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    recipe = json.loads((folder / rp.RECIPE_FILE).read_text(encoding="utf-8"))
    recipe["compare"].append({"published": "results/figure_spec.json", "produced": "figure_spec.json"})
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe), encoding="utf-8", newline="\n")
    return folder


# ── 1. a compared result the package left out ────────────────────────────────


def test_the_words_name_the_source_and_the_script_that_rebuilds_it():
    words = rp.left_out_words(YAHOO_LEFT_OUT)
    assert words == "left out under Yahoo Finance's terms (rebuilt by code/scratch/build_panel.py)"
    assert rp.left_out_words({"source": "nosuch"}) == "left out under nosuch's terms"
    assert rp.left_out_words({}) == "left out under its source's terms"


def test_a_recipe_keeps_a_compare_entry_the_folder_left_out(tmp_path: Path):
    folder = _with_left_out_compare(tmp_path)
    with pytest.raises(rp.RecipeError, match="results/figure_spec.json is not in the folder"):
        rp.load_recipe(folder)
    recipe = rp.load_recipe(folder, left_out={"results/figure_spec.json": "left out under Yahoo Finance's terms"})
    first, second = recipe["compare"]
    assert "left_out" not in first
    assert second["left_out"] == "left out under Yahoo Finance's terms"


def test_a_package_list_explains_the_files_it_left_out(tmp_path: Path):
    folder = tmp_path / "study"
    folder.mkdir()
    (folder / pkg.MANIFEST).write_text(
        json.dumps({"format": pkg.FORMAT, "left_out": [YAHOO_LEFT_OUT]}), encoding="utf-8", newline="\n"
    )
    reasons = pkg.left_out_reasons(folder, trusted=True)
    assert reasons["results/figure_spec.json"].startswith("left out under Yahoo Finance's terms")
    # In a folder (not a package e2er opened) a list is only believed where the study's records support it.
    assert "results/figure_spec.json" not in pkg.left_out_reasons(folder)


def test_the_verdict_comes_from_the_results_that_were_compared():
    good = rp.FileComparison("results/a.json", "a.json")
    good.counts[rp.IDENTICAL] = 4
    left = rp.not_compared(
        {"published": "results/figure_spec.json", "produced": "figure_spec.json", "left_out": "left out under X"}
    )
    sentence, code = rp.verdict([good, left], None, [])
    assert code == 0, sentence
    assert sentence.startswith("Reproduced:")
    assert "results/figure_spec.json not compared: left out under X" in sentence
    doc = left.as_dict()
    assert doc["not_compared"] is True and doc["left_out"] == "left out under X"
    assert doc["problem"] == "not compared: left out under X"
    # Only left-out files: nothing was compared, nothing reproduced.
    sentence, code = rp.verdict([left], None, [])
    assert code == 1 and "no value was compared" in sentence


def test_a_study_whose_package_left_a_compared_file_out_reproduces(tmp_path: Path, monkeypatch, capsys):
    folder = _with_left_out_compare(tmp_path)
    reasons = {"results/figure_spec.json": rp.left_out_words(YAHOO_LEFT_OUT)}
    monkeypatch.setattr(pkg, "left_out_reasons", lambda root, trusted=False: reasons)
    out_json = tmp_path / "report.json"
    assert reproduce(str(folder), json_out=str(out_json), yes=True, sandbox=False) == 0
    text = capsys.readouterr().out
    assert (
        "results/figure_spec.json: not compared: left out under Yahoo Finance's terms "
        "(rebuilt by code/scratch/build_panel.py)"
    ) in text
    assert "Reproduced: every compared value is identical" in text
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    by = {r["published"]: r for r in doc["results"]}
    assert by["results/figure_spec.json"]["not_compared"] is True
    assert by["results/results.json"]["matches"] is True and "not_compared" not in by["results/results.json"]


def test_an_older_recipe_lets_its_get_data_step_load_the_missing_inputs(tmp_path: Path):
    """spot-bitcoin-etf-comovement's reproduce.json (by hand, 2026-10-05) runs get_data.py but marks no input
    with "reload", so the step was kept off the web and the rerun failed."""
    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    recipe = json.loads((folder / rp.RECIPE_FILE).read_text(encoding="utf-8"))
    recipe["steps"].insert(0, {"run": ["python", "get_data.py"], "about": "reload the extracts"})
    recipe["inputs"].append({"path": "data/y.csv", "sha256": "0" * 64})
    assert rp.mark_legacy_reloads(folder, recipe) == ["data/y.csv"], "data/x.csv is in the folder: kept"
    assert rp.is_reload_step(recipe["steps"][0], recipe)
    assert "reload" not in recipe["inputs"][0]
    # A recipe that marks its reloads, or runs no get_data.py, is left as it is.
    marked = {**recipe, "inputs": [{"path": "data/z.csv", "sha256": "0" * 64, "reload": "other.py"}]}
    assert rp.mark_legacy_reloads(folder, marked) == []
    plain = {**recipe, "steps": recipe["steps"][1:], "inputs": [{"path": "data/z.csv", "sha256": "0" * 64}]}
    assert rp.mark_legacy_reloads(folder, plain) == []
