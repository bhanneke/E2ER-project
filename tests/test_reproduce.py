"""`e2er reproduce`: the recipe, the value comparison, and a full rerun of a tiny study."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.cli_reproduce import reproduce
from src.core import reproduce as rp

SCRIPT = """\
import json
rows = [float(x) for x in open("data/x.csv").read().split()]
mean = sum(rows) / len(rows)
json.dump({"main": {"estimate": round(mean, 6), "n": len(rows), "label": "ok"}}, open("results.json", "w"))
"""


def _study(tmp_path: Path, published: dict, *, data: str = "1\n2\n4\n", recipe: dict | None = None) -> Path:
    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    (folder / "results").mkdir()
    (folder / "data").mkdir()
    (folder / "code" / "run.py").write_text(SCRIPT, encoding="utf-8")
    (folder / "code" / "requirements.txt").write_text("# no packages\n", encoding="utf-8")
    (folder / "data" / "x.csv").write_text(data, encoding="utf-8")
    (folder / "results" / "results.json").write_text(json.dumps(published), encoding="utf-8")
    base = {
        "schema": rp.SCHEMA,
        "requirements": "code/requirements.txt",
        "files": {"run.py": "code/run.py", "data": "data"},
        "steps": [{"run": ["python", "run.py"], "about": "estimate"}],
        "inputs": [{"path": "data/x.csv", "sha256": hashlib.sha256(b"1\n2\n4\n").hexdigest()}],
        "compare": [{"published": "results/results.json", "produced": "results.json"}],
    }
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe or base), encoding="utf-8")
    return folder


# ── the recipe ───────────────────────────────────────────────────────────────


def test_a_folder_without_a_recipe_says_what_is_missing(tmp_path: Path) -> None:
    with pytest.raises(rp.RecipeError, match="no reproduce.json"):
        rp.load_recipe(tmp_path)


def test_a_recipe_names_every_problem(tmp_path: Path) -> None:
    folder = _study(
        tmp_path,
        {},
        recipe={
            "schema": "x",
            "requirements": "../req.txt",
            "files": {"a.py": "code/missing.py"},
            "steps": [],
            "compare": [{"published": "results/none.json", "produced": "out.json"}],
        },
    )
    with pytest.raises(rp.RecipeError) as e:
        rp.load_recipe(folder)
    text = str(e.value)
    for bit in ('"schema"', '"requirements"', "code/missing.py", '"steps"', "results/none.json"):
        assert bit in text


# ── comparing values ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("published", "produced", "label"),
    [
        (0.5, 0.5, rp.IDENTICAL),
        (0.1234, 0.12341, rp.AT_PRECISION),  # rounds to the published 4 decimals
        (0.5, 0.54, rp.MINOR),  # 0.5 may be exact: no rounding assumed
        (0.123456, 0.1236, rp.MINOR),
        (0.01, -0.01, rp.DIFFERS),  # sign change
        (1.0, 1.5, rp.DIFFERS),  # beyond the minor tolerance
        (540, 540, rp.IDENTICAL),
        ("2026-07-01", "2026-08-01", rp.DIFFERS),
        (None, None, rp.IDENTICAL),
        (True, 1, rp.DIFFERS),
    ],
)
def test_compare_value(published, produced, label) -> None:
    assert rp.compare_value(published, produced)[0] == label


def test_compare_json_counts_missing_and_new_values(tmp_path: Path) -> None:
    pub, new = tmp_path / "p.json", tmp_path / "n.json"
    pub.write_text(json.dumps({"a": 1.0, "b": {"c": [1, 2]}, "gone": 3}), encoding="utf-8")
    new.write_text(json.dumps({"a": 1.0, "b": {"c": [1, 2.5]}, "extra": 4}), encoding="utf-8")
    fc = rp.compare_json(pub, new, "p.json", "n.json")
    assert fc.counts[rp.IDENTICAL] == 2
    assert fc.counts[rp.DIFFERS] == 1
    assert fc.counts[rp.MISSING] == 1 and fc.counts[rp.NEW] == 1
    assert not fc.matches
    assert {d[1] for d in fc.largest()} == {"b/c[1]", "gone", "extra"}


def test_compare_json_says_when_the_rerun_wrote_nothing(tmp_path: Path) -> None:
    pub = tmp_path / "p.json"
    pub.write_text("{}", encoding="utf-8")
    fc = rp.compare_json(pub, tmp_path / "absent.json", "p.json", "absent.json")
    assert fc.problem == "the rerun did not write it"


# ── a full rerun ─────────────────────────────────────────────────────────────


def test_reproduce_a_study_that_reproduces(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    before = sorted(p.relative_to(folder) for p in folder.rglob("*"))
    out_json = tmp_path / "report.json"
    assert reproduce(str(folder), json_out=str(out_json)) == 0
    text = capsys.readouterr().out
    assert "1 of 1 identical" in text
    assert "3 values: 3 identical" in text
    assert text.rstrip().endswith(f"Report written to {out_json}")
    assert "Reproduced: every compared value is identical" in text
    # the study folder is not written to
    assert sorted(p.relative_to(folder) for p in folder.rglob("*")) == before
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["exit_code"] == 0 and doc["inputs"][0]["status"] == "identical"


def test_reproduce_reports_differences_and_exits_1(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, {"main": {"estimate": 2.4, "n": 3, "label": "ok"}})
    assert reproduce(str(folder)) == 1
    text = capsys.readouterr().out
    assert "main/estimate: published 2.4, rerun 2.333333" in text
    assert "Not reproduced exactly: 1 value(s) show small differences." in text
    assert "The run folder is kept:" in text


def test_a_failing_step_exits_2_with_its_output(tmp_path: Path, capsys) -> None:
    folder = _study(tmp_path, {"main": {}})
    (folder / "code" / "run.py").write_text("raise SystemExit('no data here')\n", encoding="utf-8")
    assert reproduce(str(folder)) == 2
    text = capsys.readouterr().out
    assert "FAILED (exit 1)" in text and "no data here" in text
    assert "Could not reproduce: the step `python run.py` failed." in text
