"""`e2er reproduce` report: two oddities of the EU regional GDP demo (demo 6, 2026-10-20).

* A note from the export said results/spatial_units_all244.csv had no step to build it again, although the
  package's ``rebuild`` list runs code/scratch/build_data.py for it: the note now follows that list.
* figure_spec.json "differed": run_estimation.py only updates the copy it finds (the figure step wrote the
  study's copy, code/scratch/fill_fig.py changed it), so the rerun's copy is labelled not compared.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.cli_reproduce import render
from src.core import reproduce as rp
from src.core.derived_data import not_produced_by_step

STUCK = (
    "{} {} built from data whose terms keep them out of a published study, and no recorded step builds them "
    "again from data the rerun can load: a folder without them cannot be run again."
)


def _recipe(notes: list[str]) -> dict:
    return {
        "schema": rp.SCHEMA,
        "requirements": "code/requirements.txt",
        "files": {
            "run_estimation.py": "code/run_estimation.py",
            "units_all.csv": "results/units_all.csv",
            "weights.csv": "results/weights.csv",
        },
        "steps": [{"run": ["python", "run_estimation.py"]}],
        "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
        "inputs": [
            {"path": "units_all.csv", "sha256": "a" * 64},
            {"path": "weights.csv", "sha256": "b" * 64},
        ],
        "notes": notes,
    }


def _folder(tmp_path: Path, recipe: dict) -> Path:
    b = tmp_path / "study"
    (b / "code" / "scratch").mkdir(parents=True)
    (b / "results").mkdir()
    (b / "code" / "requirements.txt").write_text("pandas==2.3.3\n", encoding="utf-8", newline="\n")
    (b / "code" / "run_estimation.py").write_text("print(1)\n", encoding="utf-8", newline="\n")
    (b / "code" / "scratch" / "build_data.py").write_text(
        "import pandas as pd\npd.DataFrame().to_csv('units_all.csv')\n", encoding="utf-8", newline="\n"
    )
    (b / "results" / "estimation_results.json").write_text("{}", encoding="utf-8", newline="\n")
    (b / "results" / "weights.csv").write_text("x\n", encoding="utf-8", newline="\n")
    (b / "results" / "units_all.csv").write_text("id\n", encoding="utf-8", newline="\n")
    (b / "reproduce.json").write_text(json.dumps(recipe), encoding="utf-8", newline="\n")
    return b


def test_the_note_drops_a_file_the_packages_rebuild_list_builds_again(tmp_path: Path):
    stuck = STUCK.format("results/units_all.csv, results/weights.csv", "are")
    b = _folder(tmp_path, _recipe(["Keep this note.", stuck]))
    rebuild = [{"path": "units_all.csv", "script": "build_data.py", "from": "code/scratch/build_data.py"}]
    recipe = rp.load_recipe(b, rebuild=rebuild)
    assert recipe["notes"] == ["Keep this note.", STUCK.format("results/weights.csv", "is")]
    # Every file covered: the note goes.
    rebuild.append({"path": "weights.csv", "script": "build_data.py", "from": "code/scratch/build_data.py"})
    assert rp.load_recipe(b, rebuild=rebuild)["notes"] == ["Keep this note."]
    # Without a rebuild list the export's note stays as it was.
    assert rp.load_recipe(b)["notes"] == ["Keep this note.", stuck]


SPEC_UPDATER = """\
import json
try:
    fs = json.load(open("figure_spec.json"))
except Exception:
    fs = {"figures": []}
fs["figures"].append({"filename": "fig_map.pdf"})
json.dump(fs, open("figure_spec.json", "w"), indent=1)
open("moran.csv", "w").write("z,wz\\n")
"""


def _spec_folder(tmp_path: Path) -> tuple[Path, dict]:
    recipe = _recipe([])
    recipe["files"].update({"figure_spec.json": "results/figure_spec.json", "moran.csv": "results/moran.csv"})
    b = _folder(tmp_path, recipe)
    (b / "code" / "run_estimation.py").write_text(SPEC_UPDATER, encoding="utf-8", newline="\n")
    (b / "code" / "scratch" / "fill_fig.py").write_text(
        "import json\nf = json.load(open('figure_spec.json'))\njson.dump(f, open('figure_spec.json', 'w'))\n",
        encoding="utf-8",
        newline="\n",
    )
    # export's copy of the estimation script, which writes the same files: not a script of the run of its own.
    (b / "replication").mkdir()
    (b / "replication" / "estimation.py").write_text("# copy\n" + SPEC_UPDATER, encoding="utf-8", newline="\n")
    rebuild = [
        {
            "path": p,
            "script": "run_estimation.py",
            "from": "code/run_estimation.py",
            "output": True,
            "written": True,
            "folder": f"results/{p}",
            "sha256": "c" * 64,
        }
        for p in ("figure_spec.json", "moran.csv")
    ]
    return b, rp.load_recipe(b, rebuild=rebuild)


def test_an_output_the_step_only_updates_is_not_compared(tmp_path: Path):
    b, recipe = _spec_folder(tmp_path)
    found = not_produced_by_step(b, recipe)
    assert set(found) == {"figure_spec.json"}, "moran.csv is written by the step itself: compared as before"
    why = found["figure_spec.json"]
    assert why.startswith("not compared: the study's copy comes from the figure step")
    assert "changed by code/scratch/fill_fig.py" in why and "run_estimation.py only updates the copy it finds" in why


def test_the_report_labels_it_and_the_verdict_is_unchanged(tmp_path: Path):
    b, recipe = _spec_folder(tmp_path)
    for item in recipe["inputs"]:
        why = not_produced_by_step(b, recipe).get(item["path"])
        if why:
            item["not_compared"] = why
    run = tmp_path / "run"
    run.mkdir()
    (run / "figure_spec.json").write_text('{"figures": []}', encoding="utf-8", newline="\n")
    (run / "moran.csv").write_text("z,wz\n", encoding="utf-8", newline="\n")
    inputs = rp.compare_inputs(run, [i for i in recipe["inputs"] if i.get("output")])
    by = {i["path"]: i for i in inputs}
    assert by["figure_spec.json"]["status"] == rp.NOT_COMPARED and "figure step" in by["figure_spec.json"]["why"]
    assert by["moran.csv"]["status"] == "differs"
    text = render(b, recipe, None, [], inputs, [], None, "verdict")
    assert "  figure_spec.json: not compared: the study's copy comes from the figure step" in text
    assert "figure_spec.json: differs" not in text
    (run / "est.json").write_text('{"b": 1.5}', encoding="utf-8", newline="\n")
    same = rp.compare_json(run / "est.json", run / "est.json", "results/est.json", "est.json")
    assert rp.verdict([same], None, [], inputs)[1] == 0, "left-out outputs never decide the verdict"
