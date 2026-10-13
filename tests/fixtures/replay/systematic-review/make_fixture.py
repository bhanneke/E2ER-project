"""Build the systematic-review replay fixture: recorded HTTP answers, the specialists' files, the scenario.

Test-only, and SYNTHETIC: twelve invented records on grit and grades
(tests/meta_fixture.py), not real studies. The OpenAlex answers and the PDFs
are what tests/meta_fixture.py serves, recorded under the addresses e2er's
search and full-text steps request (the default contact address of the polite
pool, research@e2er.app). The draft's numbers come from running e2er's own
steps on these files once, here, so they are what the run will compute.

Writes:

    http/index.json, http/*.json, http/*.pdf   recorded OpenAlex pages and PDFs
    files/protocol_designer/review_protocol.json, review_protocol.md
    files/study_screener/screening.json, screening.md
    files/study_extractor/extraction.json, extraction.md
    files/meta_review_writer/paper_draft.tex
    files/<reviewer>/review_*.md, files/patch_revisor/paper_draft.tex.edits.json
    scenario.json

Run: ``python tests/fixtures/replay/systematic-review/make_fixture.py`` from the repository root.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))

from src.modules.fieldmap.openalex import Budget, Client  # noqa: E402
from src.modules.metaanalysis import fulltext, search  # noqa: E402
from src.modules.metaanalysis import workflow as wf  # noqa: E402
from tests import meta_fixture as mf  # noqa: E402

MAILTO = "research@e2er.app"
REVIEWERS = {
    "methods_reviewer": "review_methods.md",
    "data_reviewer": "review_data.md",
    "plausibility_reviewer": "review_plausibility.md",
    "writing_reviewer": "review_writing.md",
    "technical_reviewer": "review_technical.md",
}


def _write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


def record(ws: Path) -> dict[str, str]:
    """Run the search and the full-text step on the fakes, recording every address and answer."""
    http = HERE / "http"
    shutil.rmtree(http, ignore_errors=True)
    index: dict[str, str] = {}
    fake = mf.FakeOpenAlex()

    def text(url: str, headers: dict[str, str]) -> str:
        body = fake(url, headers)
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".json"
        _write(http / name, body)
        index[url] = name
        return body

    def pdf(url: str) -> bytes:
        data = mf.fake_pdf(url)
        name = url.rsplit("/", 1)[-1]
        _write(http / name, data)
        index[url] = name
        return data

    search.client = lambda w, n: Client(  # type: ignore[assignment]
        cache_dir=Path(w) / search.DIR / "cache", budget=Budget(limit=n), mailto=MAILTO, fetch=text, pause_s=0
    )
    fulltext.fetch_pdf = pdf  # type: ignore[assignment]
    fulltext.resolve_pdf = lambda doi: None  # type: ignore[assignment]
    mf.write_protocol(ws)
    assert wf.search_step(ws).passed
    (ws / "screening.json").write_text(json.dumps(mf.screening()), encoding="utf-8")
    assert wf.screening_step(ws).passed
    assert wf.fulltext_step(ws).passed
    (ws / "extraction.json").write_text(json.dumps(mf.extraction()), encoding="utf-8")
    assert wf.extraction_step(ws).passed, wf.extraction_step(ws)
    v = wf.synthesis_step(ws)
    assert v.passed, v
    _write(http / "index.json", json.dumps(index, indent=2, sort_keys=True))
    return index


def draft(ws: Path) -> str:
    r = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    keys = json.loads((ws / wf.REFERENCES_FILE).read_text(encoding="utf-8"))["studies"]
    p, h, pooled, pi = r["prisma"], r["heterogeneity"], r["pooled"], r["prediction_interval"]
    e = r["small_study_effects"]["egger"]
    tf = r["small_study_effects"]["trim_and_fill"]
    cites = ", ".join(keys[s["id"]] for s in r["studies"])
    return rf"""\title{{Grit and grade point average in university students: a systematic review and meta-analysis of synthetic test data}}
\begin{{abstract}}
This review is a test fixture of e2er: every record and study in it is invented. We searched OpenAlex for studies of
grit and grade point average in university students, screened {p["screened"]} records and included
{p["included_in_review"]} studies. The random-effects pooled correlation is {pooled["estimate_reported_scale"]:.2f}
(95\% CI {pooled["ci_lower_reported_scale"]:.2f} to {pooled["ci_upper_reported_scale"]:.2f}), with
$I^2$ = {h["i2"]:.1f}\%.
\end{{abstract}}

\section{{Introduction}}
Whether grit goes with higher grades is a question for a meta-analysis; the studies here are synthetic and exist only to
test the template \citep{{page2021prisma}}.

\section{{Methods}}
The protocol fixed the question, the eligibility criteria and the searches before any record was read. Two searches
on OpenAlex found {p["identified"]["total"]} records; {p["duplicates_removed"]} duplicate was removed. One screener
decided every record on its title and abstract. Full texts were read where an open-access PDF existed. Correlations were
pooled as Fisher's $z$ in a random-effects model with $\tau^2$ by restricted maximum likelihood
\citep{{viechtbauer2005bias,viechtbauer2010conducting}}; heterogeneity is reported as $I^2$ \citep{{higgins2002quantifying}}
with a prediction interval \citep{{riley2011interpretation}}, and small-study effects with Egger's test
\citep{{egger1997bias}} and trim and fill \citep{{duval2000trim}}.

\section{{Results}}
Table~\ref{{tab:flow}} gives the flow of records and Figure~\ref{{fig:prisma}} the diagram.
\begin{{table}}[h]\centering\caption{{Flow of records}}\label{{tab:flow}}
\input{{tables/meta_flow.tex}}
\end{{table}}
\begin{{figure}}[h]\centering\includegraphics[width=0.8\textwidth]{{fig_prisma.pdf}}\caption{{PRISMA 2020 flow diagram}}\label{{fig:prisma}}\end{{figure}}
The {r["k"]} included studies \citep{{{cites}}} are listed in Table~\ref{{tab:studies}}.
\begin{{table}}[h]\centering\caption{{Included studies}}\label{{tab:studies}}
\input{{tables/meta_studies.tex}}
\end{{table}}
The pooled correlation is {pooled["estimate_reported_scale"]:.2f} with a prediction interval from
{pi["lower_reported_scale"]:.2f} to {pi["upper_reported_scale"]:.2f}: a new study could find almost no association.
$\tau^2$ is {h["tau2"]:.3f}. Egger's intercept is {e["intercept"]:.2f} ($p$ = {e["p_value"]:.3f}) on {r["k"]} studies,
a test with little power; trim and fill adds {tf["k0"]} studies.
\begin{{table}}[h]\centering\caption{{Meta-analysis}}\label{{tab:meta}}
\input{{tables/meta_results.tex}}
\end{{table}}
\begin{{figure}}[h]\centering\includegraphics[width=0.8\textwidth]{{fig_forest.pdf}}\caption{{Forest plot}}\end{{figure}}
\begin{{figure}}[h]\centering\includegraphics[width=0.7\textwidth]{{fig_funnel.pdf}}\caption{{Funnel plot}}\end{{figure}}

\section{{Limitations}}
One open index was searched, one screener decided every record, extraction was done by a model and checked against the
text by e2er, and the studies are synthetic.
"""


def review(title: str, score: int, points: list[str]) -> str:
    lines = [f"# {title}", "", "## Summary", "", "A synthetic test review of grit and grade point average: the flow, "
             "the included studies, the pooled correlation with its heterogeneity and the small-study checks are "
             "reported, and every number is in the results.", "", "## Points to address", ""]
    lines += [f"{i}. {p}" for i, p in enumerate(points, start=1)]
    lines += ["", "## DIMENSION SCORES", f"- Overall: {score}/10", "", f"OVERALL SCORE: {score}/10",
              "RECOMMENDATION: Minor Revision", ""]
    return "\n".join(lines)


def main() -> None:
    files = HERE / "files"
    shutil.rmtree(files, ignore_errors=True)
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        record(ws)
        _write(files / "protocol_designer" / "review_protocol.json", json.dumps(mf.PROTOCOL, indent=2))
        _write(
            files / "protocol_designer" / "review_protocol.md",
            "# Review protocol (synthetic test data)\n\nQuestion: how strongly is grit associated with GPA in "
            "university students. Criteria I1-I3 and E1-E2 as in review_protocol.json: primary quantitative studies "
            "of university students that report the correlation of grit with GPA and the sample size. Two OpenAlex "
            "searches; effect measure r, pooled as Fisher's z by REML; risk of bias with an adapted JBI checklist.\n",
        )
        _write(files / "study_screener" / "screening.json", json.dumps(mf.screening(), indent=2))
        _write(
            files / "study_screener" / "screening.md",
            "# Screening\n\n11 records: 8 included, 2 excluded (E1: a meta-analysis; I1: school pupils), 1 unsure "
            "(no abstract). The unsure record goes to the full text.\n",
        )
        _write(files / "study_extractor" / "extraction.json", json.dumps(mf.extraction(), indent=2))
        _write(
            files / "study_extractor" / "extraction.md",
            "# Extraction\n\nEight studies included with a correlation and its sample size, seven read from the full "
            "text and one (W108) from its abstract; W111 excluded on its full text (I3: no correlation with GPA).\n",
        )
        _write(files / "meta_review_writer" / "paper_draft.tex", draft(ws))
    for name, fname in REVIEWERS.items():
        title = "Review of the " + name.removesuffix("_reviewer").replace("_", " ")
        _write(files / name / fname, review(title, 8, ["Say how the searches were sized.", "Discuss the funnel."]))
    _write(files / "patch_revisor" / "paper_draft.tex.edits.json", "[]\n")

    usage = {"input_tokens": 20, "output_tokens": 1000, "cache_read_tokens": 0, "cache_write_tokens": 0}

    def entry(specialist: str) -> dict:
        names = sorted(str(p.relative_to(files / specialist)) for p in (files / specialist).rglob("*") if p.is_file())
        return {"files": names, "output": f"Wrote {', '.join(names)}.", "usage": usage}

    specialists = ["protocol_designer", "study_screener", "study_extractor", "meta_review_writer", *REVIEWERS]
    scenario = {
        "name": "systematic-review",
        "source": (
            "Hand-made test fixture of the systematic-review template, not a recorded run: a review of SYNTHETIC "
            "records on grit and grades (tests/meta_fixture.py). make_fixture.py records the OpenAlex pages and "
            "PDFs the search and full-text steps request and writes the specialists' files; the draft's numbers "
            "come from e2er's own steps run once on these files."
        ),
        "template": "systematic-review",
        "research_question": mf.PROTOCOL["question"],
        "title": "Grit and grade point average: a synthetic systematic review",
        "model": "claude-haiku-4-5-20251001",
        "initial_groups": [],
        "specialists": {s: entry(s) for s in [*specialists, "patch_revisor"]},
    }
    _write(HERE / "scenario.json", json.dumps(scenario, indent=2) + "\n")


if __name__ == "__main__":
    main()
