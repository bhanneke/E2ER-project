"""Build the text replay fixture from a recorded Project Gutenberg load.

Test-only. The data are real: six works of short fiction from Project Gutenberg
(41 The Legend of Sleepy Hollow, 932 The Fall of the House of Usher, 11231
Bartleby, the Scrivener, 43 The Strange Case of Dr. Jekyll and Mr. Hyde, 375 An
Occurrence at Owl Creek Bridge, 1952 The Yellow Wallpaper), recorded once live
through e2er's connector (``inputs/gutenberg_six.json``: the Gutendex catalogue
and the plain texts from the mirror gutenberg.pglaf.org, read 2026-10-11) and
replayed here without the network. From that load and the recorded scripts it
writes:

    files/data_analyst/data.db                  tables gutenberg_texts (the load) and corpus (build_data.py)
    files/data_analyst/data_sources.json        the load's record (terms, citations, SHA-256 of each file)
    files/data_analyst/corpus_manifest.json     by build_data.py
    files/data_analyst/summary_statistics.json  by build_data.py
    files/data_analyst/stopwords.txt            by build_data.py (scikit-learn's English stop words)
    files/econometrics_specialist/estimation_results.json, validation_sample.json   by run_estimation.py
    files/econometrics_specialist/figure_spec.json   the three figures, from the results

Run from the repository root: ``python tests/fixtures/replay/text/make_fixture.py`` (``--record``
loads the books live again and rewrites the cassette). The hand-written files (the plan, the
corpus design, the scripts, the validator's judgements, the draft, the reviews) are not touched;
the script stops when the validation sample no longer matches the judgements.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CASSETTE = HERE / "inputs" / "gutenberg_six.json"
IDS = "41,932,11231,43,375,1952"
FILES = HERE / "files"


def load(tmp: Path, record: bool) -> Path:
    """Run the connector on the recorded responses, as the data analyst would; return the workspace."""
    os.environ["E2ER_WORKSPACE_ROOT"] = str(tmp / "ws")
    os.environ["E2ER_CACHE_DIR"] = str(tmp / "cache")
    ws = tmp / "ws" / "fixture"
    ws.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    from src.modules.data import cli
    from src.modules.data.sources import http

    http.PACING = record
    with http.use_cassette(CASSETTE, record=record), contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(
            ["--paper-id", "fixture", "--specialist", "data_analyst", "gutenberg", "text", "--ids", IDS,
             "--table", "gutenberg_texts"]
        )  # fmt: skip
    if code != 0:
        raise SystemExit(f"the connector failed on the recorded responses (exit {code})")
    return ws


def figures(results: dict) -> dict:
    by_year = [r for r in results["models"]["fear_words"]["outputs"]["by_group"] if r.get("year") is not None]
    series = results["models"]["fear_over_time"]["outputs"]["series"]
    terms = results["models"]["keyness_late"]["outputs"]["terms"]
    prevalence = results["models"]["topics"]["outputs"]["prevalence"]
    lines = [
        {
            "label": "Fear dictionary",
            "x": [r["year"] for r in by_year],
            "y": [r["per_10k"] for r in by_year],
            "source": {
                "results": "models.fear_words.outputs.by_group",
                "fields": {"x": "year", "y": "per_10k"},
                "where": "year IS NOT NULL",
            },
        }
    ]
    for term in ("fear", "terror"):
        rows = [r for r in series if r["term"] == term]
        lines.append(
            {
                "label": f"'{term}'",
                "x": [r["year"] for r in rows],
                "y": [r["per_10k"] for r in rows],
                "source": {
                    "results": "models.fear_over_time.outputs.series",
                    "fields": {"x": "year", "y": "per_10k"},
                    "where": f"term = '{term}'",
                },
            }
        )
    panels = []
    for g in ("early", "late"):
        rows = [r for r in prevalence if r["group"] == g]
        panels.append(
            {
                "figure_type": "bar",
                "title": "1820-1853" if g == "early" else "1886-1892",
                "categories": [r["label"] for r in rows],
                "values": [r["share"] for r in rows],
                "y_label": "Mean topic share",
                "source": {
                    "results": "models.topics.outputs.prevalence",
                    "fields": {"categories": "label", "values": "share"},
                    "where": f"group = '{g}'",
                },
            }
        )
    return {
        "figures": [
            {
                "filename": "fig_fear_by_year.pdf",
                "figure_type": "time_series",
                "label": "fig:fear_by_year",
                "caption_hint": "Fear vocabulary per 10,000 tokens in each work, by year of first publication",
                "series": lines,
                "x_label": "Year of first publication (one work per year)",
                "y_label": "Per 10,000 tokens",
            },
            {
                "filename": "fig_keyness.pdf",
                "figure_type": "bar",
                "label": "fig:keyness",
                "caption_hint": "Key terms of the later works against the earlier ones: log ratio",
                "categories": [t["term"] for t in terms],
                "values": [t["log_ratio"] for t in terms],
                "y_label": "Log ratio (later vs earlier)",
                "source": {
                    "results": "models.keyness_late.outputs.terms",
                    "fields": {"categories": "term", "values": "log_ratio"},
                },
            },
            {
                "filename": "fig_topics.pdf",
                "figure_type": "multi_panel",
                "label": "fig:topics",
                "caption_hint": "Mean topic shares of the 1,000-token segments, by period (NMF, k = 3)",
                "ncols": 2,
                "panels": panels,
            },
        ]
    }


def run(script: Path, cwd: Path) -> None:
    shutil.copy(script, cwd / script.name)
    subprocess.run([sys.executable, script.name], cwd=cwd, check=True, capture_output=True)


def main() -> None:
    record = "--record" in sys.argv
    analyst, econ = FILES / "data_analyst", FILES / "econometrics_specialist"
    with tempfile.TemporaryDirectory() as t:
        ws = load(Path(t), record)
        record_doc = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))
        # The record names the paper the load was made for; the replay fills in the run's own.
        text = json.dumps(record_doc, indent=2, ensure_ascii=False).replace('"fixture"', '"@@PAPER_ID@@"')
        (analyst / "data_sources.json").write_text(text + "\n", encoding="utf-8")
        shutil.copy(FILES / "data_architect" / "corpus_design.json", ws / "corpus_design.json")
        run(analyst / "build_data.py", ws)
        for name in ("data.db", "corpus_manifest.json", "summary_statistics.json", "stopwords.txt"):
            shutil.copy(ws / name, analyst / name)
        run(econ / "run_estimation.py", ws)
        for name in ("estimation_results.json", "validation_sample.json"):
            shutil.copy(ws / name, econ / name)
    results = json.loads((econ / "estimation_results.json").read_text(encoding="utf-8"))
    (econ / "figure_spec.json").write_text(json.dumps(figures(results), indent=2, ensure_ascii=False) + "\n")

    sample = json.loads((econ / "validation_sample.json").read_text(encoding="utf-8"))["fear_words"]["items"]
    judged = json.loads((FILES / "text_validator" / "text_validation.json").read_text(encoding="utf-8"))
    pairs = [(i["doc_id"], i["quote"]) for i in judged["fear_words"]["items"]]
    if pairs != [(i["doc_id"], i["quote"]) for i in sample]:
        raise SystemExit("the validation sample changed: judge the new items in files/text_validator/")


if __name__ == "__main__":
    main()
