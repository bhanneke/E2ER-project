"""`e2er reproduce` when the inputs a step loads again differ from the study's while every result matches.

The real test of 2026-11-12: pleiades-gaia-dr3-members had 917 values identical, 13 the same at the published
precision and 3 of 3 tables identical, yet "Not reproduced exactly: 2 input file(s) differ", because the
reloaded Gaia files differ byte for byte. Reproduced, with a plain note; inputs that differ are still shown.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from tests.test_reproduce import _study

# ── 2. reloaded inputs that differ while every result matches ────────────────


def _reload_study(tmp_path: Path) -> Path:
    """A study whose input get_data.py loads again when the folder lacks it (the source now returns other bytes)."""
    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    (folder / "data" / "x.csv").unlink()
    # The source returns the same values with other bytes (another line ending at the end).
    (folder / "code" / "get_data.py").write_text(
        "import os\nos.makedirs('data', exist_ok=True)\nopen('data/x.csv', 'w').write('1\\n2\\n4\\n\\n')\n",
        encoding="utf-8",
        newline="\n",
    )
    recipe = json.loads((folder / rp.RECIPE_FILE).read_text(encoding="utf-8"))
    recipe["files"] = {"run.py": "code/run.py", "get_data.py": "code/get_data.py", "data/x.csv": "data/x.csv"}
    recipe["steps"].insert(0, {"run": ["python", "get_data.py"], "about": "load the inputs again"})
    recipe["inputs"][0].update({"reload": "get_data.py", "source": "a public source"})
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe), encoding="utf-8", newline="\n")
    return folder


def test_reloaded_inputs_that_differ_do_not_undo_matching_results():
    good = rp.FileComparison("results/a.json", "a.json")
    good.counts[rp.IDENTICAL] = 917
    good.counts[rp.AT_PRECISION] = 13
    tables = {"rendered": 3, "identical": ["a.tex", "b.tex", "c.tex"], "differ": [], "not_shipped": []}
    inputs = [
        {"path": "data/gaia_dr3.csv", "status": "differs", "reloaded": True},
        {"path": "data/gaia_clean.csv", "status": "differs", "reloaded": True},
    ]
    sentence, code = rp.verdict([good], tables, [], inputs)
    assert code == 0, sentence
    assert sentence.startswith("Reproduced: every compared value is identical or the same at the published precision")
    assert "every table renders the same" in sentence
    assert "the reloaded inputs differ byte for byte from the study's (data/gaia_dr3.csv, data/gaia_clean.csv)" in (
        sentence
    )


def test_results_that_differ_are_still_not_reproduced_with_reloaded_inputs():
    bad = rp.FileComparison("results/a.json", "a.json")
    bad.counts[rp.IDENTICAL] = 3
    bad.counts[rp.DIFFERS] = 1
    inputs = [{"path": "data/x.csv", "status": "differs", "reloaded": True}]
    sentence, code = rp.verdict([bad], None, [], inputs)
    assert code == 1
    assert sentence.startswith("Not reproduced exactly: 1 differ")
    assert "1 input file(s) differ from the study's (data/x.csv)" in sentence


def test_an_input_the_folder_shipped_that_differs_is_still_not_reproduced():
    good = rp.FileComparison("results/a.json", "a.json")
    good.counts[rp.IDENTICAL] = 3
    sentence, code = rp.verdict([good], None, [], [{"path": "data/x.csv", "status": "differs"}])
    assert code == 1 and "1 input file(s) differ" in sentence


def test_compare_inputs_marks_what_a_step_loaded_again(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.csv").write_text("1\n", encoding="utf-8", newline="\n")
    items = [{"path": "data/x.csv", "sha256": "0" * 64, "reload": "get_data.py"}]
    [entry] = rp.compare_inputs(tmp_path, items, absent={"data/x.csv"})
    assert entry["status"] == "differs" and entry["reloaded"] is True
    [entry] = rp.compare_inputs(tmp_path, items, absent=set())
    assert "reloaded" not in entry, "the folder shipped it: the study's own file was used"


def test_a_study_whose_reloaded_input_differs_reproduces(tmp_path: Path, capsys):
    folder = _reload_study(tmp_path)
    out_json = tmp_path / "report.json"
    assert reproduce(str(folder), json_out=str(out_json), yes=True, sandbox=False) == 0
    text = capsys.readouterr().out
    assert "1 differ: data/x.csv" in text, "inputs that differ are still shown"
    assert "the reloaded inputs differ byte for byte from the study's (data/x.csv)" in text
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["exit_code"] == 0
    assert doc["inputs"][0]["status"] == "differs" and doc["inputs"][0]["reloaded"] is True
    assert hashlib.sha256((folder / "results" / "results.json").read_bytes()).hexdigest()
