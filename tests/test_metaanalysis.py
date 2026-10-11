"""The systematic-review template's code: statistics, protocol, search, screening, full texts, extraction, synthesis.

No network: OpenAlex and the PDFs are the fakes of tests/meta_fixture.py
(SYNTHETIC records). The statistics are checked against metafor's published
results for the BCG vaccine trials (dat.bcg; Viechtbauer 2010 and the metafor
reference pages for rma and trimfill) and against an independent OLS fit.
"""

from __future__ import annotations

import json
import math
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from src.core.pipeline import meta_checks
from src.core.pipeline.result_kinds import check_results
from src.core.pipeline.spec import find_spec
from src.modules.metaanalysis import fulltext, search
from src.modules.metaanalysis import stats as st
from src.modules.metaanalysis import workflow as wf
from src.modules.metaanalysis.credit import METHOD_REFERENCES
from src.modules.metaanalysis.protocol import protocol_problems
from tests import meta_fixture as mf

ROOT = Path(__file__).resolve().parents[1]

# dat.bcg: tpos, tneg, cpos, cneg of 13 trials.
BCG = [
    (4, 119, 11, 128), (6, 300, 29, 274), (3, 228, 11, 209), (62, 13536, 248, 12619), (33, 5036, 47, 5761),
    (180, 1361, 372, 1079), (8, 2537, 10, 619), (505, 87886, 499, 87892), (29, 7470, 45, 7232),
    (17, 1699, 65, 1600), (186, 50448, 141, 27197), (5, 2493, 3, 2338), (27, 16886, 29, 17825),
]  # fmt: skip
Y = [math.log((a / (a + b)) / (c / (c + d))) for a, b, c, d in BCG]
V = [1 / a - 1 / (a + b) + 1 / c - 1 / (c + d) for a, b, c, d in BCG]


# ── statistics ──────────────────────────────────────────────────────────────


def test_reml_reproduces_metafor_on_the_bcg_trials():
    r = st.pool(Y, V, method="REML")
    # metafor: estimate -0.7145, se 0.1798, ci [-1.0669, -0.3622], tau^2 0.3132, I^2 92.22%, H^2 12.86, Q 152.2330
    assert round(r["estimate"], 4) == -0.7145 and round(r["se"], 4) == 0.1798
    assert (round(r["ci_lower"], 4), round(r["ci_upper"], 4)) == (-1.0669, -0.3622)
    assert round(r["tau2"], 4) == 0.3132 and round(r["i2"], 2) == 92.22 and round(r["h2"], 2) == 12.86
    assert round(r["q"], 4) == 152.2330 and r["q_df"] == 12
    assert abs(sum(r["weights_percent"]) - 100) < 1e-9
    pi = r["prediction_interval"]
    assert pi["df"] == 11 and pi["lower"] < r["ci_lower"] and pi["upper"] > r["ci_upper"]


def test_dersimonian_laird_reproduces_metafor_on_the_bcg_trials():
    r = st.pool(Y, V, method="DL")
    # metafor (method="DL"): estimate -0.7141, se 0.1787, tau^2 0.3088, I^2 92.12%
    assert round(r["estimate"], 4) == -0.7141 and round(r["se"], 4) == 0.1787
    assert round(r["tau2"], 4) == 0.3088 and round(r["i2"], 2) == 92.12
    # Under DL, I^2 = (Q - df) / Q (Higgins and Thompson 2002).
    assert r["i2"] == pytest.approx(100 * (r["q"] - 12) / r["q"])


def test_trim_and_fill_reproduces_metafor_on_the_bcg_trials():
    tf = st.trim_and_fill(Y, V)
    # metafor trimfill(res): 1 missing study on the right side; -0.6571 [-1.0070, -0.3072]; tau^2 0.3313
    assert tf["k0"] == 1 and tf["side"] == "right"
    assert round(tf["estimate"], 4) == -0.6571 and round(tf["se"], 4) == 0.1785
    assert (round(tf["ci_lower"], 4), round(tf["ci_upper"], 4)) == (-1.0070, -0.3072)
    assert round(tf["tau2"], 4) == 0.3313
    assert len(tf["filled"]) == len(tf["filled_se"]) == 1


def test_egger_matches_an_independent_ols_fit():
    import statsmodels.api as sm

    se = np.sqrt(V)
    fit = sm.OLS(np.array(Y) / se, sm.add_constant(1 / se)).fit()
    e = st.egger(Y, V)
    assert e["intercept"] == pytest.approx(fit.params[0]) and e["se"] == pytest.approx(fit.bse[0])
    assert e["p_value"] == pytest.approx(fit.pvalues[0]) and e["df"] == 11
    assert "skipped" in st.egger(Y[:2], V[:2])


def test_a_symmetric_funnel_fills_nothing_and_leave_one_out_drops_each_study():
    y = [0.1, 0.3, 0.2, 0.2, 0.15, 0.25]
    v = [0.01, 0.01, 0.004, 0.02, 0.008, 0.008]
    assert st.trim_and_fill(y, v)["k0"] == 0
    loo = st.leave_one_out(y, v, list("abcdef"))
    assert [x["omitted"] for x in loo] == list("abcdef")
    assert loo[0]["estimate"] == pytest.approx(st.pool(y[1:], v[1:])["estimate"])


def test_one_study_and_no_heterogeneity():
    r = st.pool([0.3], [0.01])
    assert r["tau2"] == 0 and r["i2"] == 0 and r["prediction_interval"] is None
    r = st.pool([0.2, 0.2, 0.2], [0.01, 0.02, 0.03])
    assert r["tau2"] == 0 and r["i2"] == 0 and r["estimate"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("effect", "measure", "y", "v"),
    [
        ({"value": 0.3, "n": 103}, "r", math.atanh(0.3), 0.01),
        ({"value": 2.0, "ci_lower": 1.0, "ci_upper": 4.0}, "OR", math.log(2), (math.log(4) / (2 * 1.959964)) ** 2),
        ({"value": 1.5, "se": 0.2}, "HR", math.log(1.5), 0.04),
        ({"value": 0.4, "ci_lower": 0.2, "ci_upper": 0.6, "ci_level": 0.90}, "MD", 0.4, (0.4 / (2 * 1.644854)) ** 2),
        ({"value": 0.5, "n1": 20, "n2": 30}, "SMD", 0.5, 50 / 600 + 0.25 / 100),
    ],
)
def test_effects_are_put_on_the_analysis_scale(effect: dict[str, Any], measure: str, y: float, v: float):
    yi, vi, _ = st.effect_on_scale(effect, measure)
    assert yi == pytest.approx(y) and vi == pytest.approx(v, rel=1e-5)


def test_hedges_g_from_group_statistics():
    g, v = st.hedges_g(10, 2, 20, 8, 2, 20)
    j = 1 - 3 / (4 * 38 - 1)
    assert g == pytest.approx(j * 1.0) and v == pytest.approx(j**2 * (40 / 400 + 1 / 80))
    yi, _, how = st.effect_on_scale({"mean1": 10, "sd1": 2, "n1": 20, "mean2": 8, "sd2": 2, "n2": 20}, "SMD")
    assert yi == pytest.approx(g) and "Hedges" in how


@pytest.mark.parametrize(
    ("effect", "measure", "match"),
    [
        ({"value": 1.2}, "r", "between -1 and 1"),
        ({"value": 0.2}, "r", "sample size"),
        ({"value": -1, "se": 0.1}, "OR", "positive"),
        ({"value": 0.3}, "MD", "standard error"),
        ({"value": 0.3, "se": 0.1}, "Cohen", "unknown effect measure"),
    ],
)
def test_an_effect_that_cannot_be_used_is_refused(effect, measure, match):
    with pytest.raises(st.EffectError, match=match):
        st.effect_on_scale(effect, measure)


# ── protocol ────────────────────────────────────────────────────────────────


def test_the_fixture_protocol_is_usable():
    assert protocol_problems(mf.PROTOCOL) == []


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda p: p.pop("question"), "question"),
        (lambda p: p["searches"][0].update(query="grit, GPA"), "commas"),
        (lambda p: p.update(effect_measure="d"), "effect_measure"),
        (lambda p: p["eligibility"]["exclude"].append({"id": "E1", "criterion": "again"}), "used twice"),
        (lambda p: p["eligibility"].update(include=[]), "include"),
        (lambda p: p["synthesis"].update(min_studies=1), "min_studies"),
        (lambda p: p["risk_of_bias"].update(domains=[]), "domains"),
        (lambda p: p.update(databases=["scopus"]), "databases"),
    ],
)
def test_a_protocol_with_a_mistake_is_named(change, match):
    p = json.loads(json.dumps(mf.PROTOCOL))
    change(p)
    assert any(match in x for x in protocol_problems(p)), protocol_problems(p)


# ── the steps on a workspace ────────────────────────────────────────────────


@pytest.fixture
def fake(monkeypatch) -> mf.FakeOpenAlex:
    f = mf.FakeOpenAlex()
    monkeypatch.setattr(search, "fetch_text", f)
    monkeypatch.setattr(fulltext, "fetch_pdf", mf.fake_pdf)
    monkeypatch.setattr(fulltext, "resolve_pdf", lambda doi: None)
    return f


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    mf.write_protocol(w)
    return w


def _through(ws: Path, step: str) -> None:
    """Run the steps up to and including ``step`` with the fixture's decisions."""
    assert wf.search_step(ws).passed
    if step == "search":
        return
    (ws / "screening.json").write_text(json.dumps(mf.screening()), encoding="utf-8")
    assert wf.screening_step(ws).passed
    if step == "screening":
        return
    assert wf.fulltext_step(ws).passed
    if step == "fulltext":
        return
    (ws / "extraction.json").write_text(json.dumps(mf.extraction()), encoding="utf-8")
    v = wf.extraction_step(ws)
    assert v.passed, v
    if step == "extraction":
        return
    v = wf.synthesis_step(ws)
    assert v.passed, v


def test_the_search_is_recorded_deduplicated_and_cached(ws: Path, fake: mf.FakeOpenAlex):
    v = wf.search_step(ws)
    assert v.passed and v.stats["records"] == 11 and v.stats["duplicates_removed"] == 1
    log = json.loads((ws / "search_log.json").read_text(encoding="utf-8"))
    assert [s["count_reported"] for s in log["searches"]] == [10, 2]
    assert "publication_year:2010-2024" in log["searches"][0]["query"]
    w103 = next(r for r in json.loads((ws / "records.json").read_text())["records"] if r["id"] == "W103")
    assert w103["found_by"] == ["openalex:main", "openalex:grades"]
    assert "Search counts" in (ws / "search_counts.md").read_text(encoding="utf-8")
    sent = len(fake.calls)
    assert wf.search_step(ws).passed and len(fake.calls) == sent  # the cache: no request the second time


def test_a_search_above_its_limit_is_refused_before_its_pages(ws: Path, fake: mf.FakeOpenAlex):
    v = wf.search_step(ws, max_records=5)
    assert not v.passed and "above the limit of 5" in v.reasons[0]
    assert len(fake.calls) == 1 and not (ws / "records.json").exists()


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: d["decisions"].pop(), "have no decision"),
        (lambda d: d["decisions"].append({"id": "W999", "decision": "include"}), "name no record"),
        (lambda d: d["decisions"][8].pop("reason"), "without a criterion id and a reason"),
        (lambda d: d["decisions"][8].update(criteria=["E9"]), "does not define"),
        (lambda d: d["decisions"][0].update(decision="maybe"), "include, exclude or unsure"),
        (lambda d: d["decisions"].append({"id": "W101", "decision": "exclude"}), "decided twice"),
    ],
)
def test_screening_refusals(ws: Path, fake, change, match):
    _through(ws, "search")
    d = mf.screening()
    change(d)
    (ws / "screening.json").write_text(json.dumps(d), encoding="utf-8")
    v = meta_checks.meta_screening(ws)
    assert not v.passed and any(match in r for r in v.reasons), v.reasons


def test_screening_writes_a_seeded_sample_for_the_researcher(ws: Path, fake):
    _through(ws, "screening")
    first = (ws / "screening_sample.md").read_text(encoding="utf-8")
    assert "Unsure (1)" in first and "W111" in first and "Sample of exclusions (2)" in first
    assert wf.screening_step(ws).passed
    assert (ws / "screening_sample.md").read_text(encoding="utf-8") == first


def test_full_texts_come_page_by_page_and_a_missing_one_says_why(ws: Path, fake):
    _through(ws, "fulltext")
    log = json.loads((ws / "fulltext_log.json").read_text(encoding="utf-8"))
    assert log["counts"] == {"sought": 9, "retrieved": 8, "not_retrieved": 1}
    assert log["records"]["W101"]["origin"] == "open access" and len(log["records"]["W101"]["sha256"]) == 64
    assert log["records"]["W108"] == {"status": "not available", "reason": "no open-access full text found",
                                     "attempts": []}  # fmt: skip
    pages = fulltext.read_pages(ws / "fulltext" / "W101.txt")
    assert set(pages) == {1, 2} and "412 students" in pages[1]


def test_a_supplied_pdf_is_used_first_and_a_landing_page_is_not_a_pdf(ws: Path, fake, monkeypatch):
    (ws / "data" / "fulltext").mkdir(parents=True)
    (ws / "data" / "fulltext" / "W108.pdf").write_bytes(mf.pdf_bytes("W101"))
    monkeypatch.setattr(fulltext, "fetch_pdf", lambda url: b"<!doctype html><html>paywall</html>")
    _through(ws, "screening")
    assert wf.fulltext_step(ws).passed
    log = json.loads((ws / "fulltext_log.json").read_text(encoding="utf-8"))["records"]
    assert log["W108"]["origin"] == "local"
    assert log["W102"]["status"] == "not available" and "not a PDF" in log["W102"]["attempts"][0]


def _extract_with(ws: Path, change) -> Any:
    _through(ws, "fulltext")
    d = mf.extraction()
    change(d)
    (ws / "extraction.json").write_text(json.dumps(d), encoding="utf-8")
    return meta_checks.meta_extraction(ws)


def _s(d: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in d["studies"] if s["id"] == sid)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        # A quote the full text does not contain.
        (lambda d: _s(d, "W101")["sources"]["effect.n"].update(quote="The final sample comprised 500 people"),
         "number not in quote"),
        (lambda d: _s(d, "W101")["sources"]["effect.n"].update(quote="The sample comprised 412 learners"),
         "quote not found"),
        (lambda d: _s(d, "W102")["sources"].pop("effect.value"), "no source"),
        (lambda d: _s(d, "W102")["sources"]["effect.value"].update(quote=".18"), "quote too short"),
        (lambda d: _s(d, "W108")["sources"]["effect.value"].update(quote="Grit was associated with GPA (r = .35"),
         "traced"),
    ],
)  # fmt: skip
def test_an_extracted_number_that_does_not_trace_stops_the_check(ws: Path, fake, change, match):
    v = _extract_with(ws, change)
    if match == "traced":  # a shorter quote that still prints the number is fine
        assert v.passed, v
        return
    assert not v.passed and match in " ".join(v.reasons), v.reasons
    assert not (ws / "meta_studies.csv").exists()


def test_a_quote_on_another_page_is_accepted_with_a_note(ws: Path, fake):
    v = _extract_with(ws, lambda d: _s(d, "W101")["sources"]["effect.value"].update(page=1))
    assert v.passed and any("found on page 2, not on page 1" in n for n in v.notes), v


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: d["studies"].pop(), "have no decision"),
        (lambda d: _s(d, "W111").update(decision="unsure"), "not unsure"),
        (lambda d: _s(d, "W108").update(source_text="full text"), "fulltext_log.json has none"),
        (lambda d: _s(d, "W111").pop("criteria"), "without a criterion id and a reason"),
        (lambda d: _s(d, "W101")["risk_of_bias"]["domains"].pop("sample"), "not judged for sample"),
        (lambda d: _s(d, "W101")["risk_of_bias"].update(overall="serious"), "not among"),
        (lambda d: _s(d, "W101")["effect"].update(value=1.4), "cannot be used as a r"),
        (lambda d: _s(d, "W101").update(effect=None), "no_effect_reason"),
    ],
)
def test_extraction_structure_refusals(ws: Path, fake, change, match):
    v = _extract_with(ws, change)
    assert not v.passed and match in " ".join(v.reasons), v.reasons


def test_the_synthesis_pools_draws_and_writes_tables_and_references(ws: Path, fake):
    _through(ws, "synthesis")
    r = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    assert check_results("metaanalysis", r, ws) == []
    y = [math.atanh(float(v[2])) for v in mf.STUDIES.values()]
    w = [1 / (n - 3) for *_, n, _ in mf.STUDIES.values()]
    assert r["pooled"]["estimate"] == pytest.approx(st.pool(y, w)["estimate"])
    assert r["prisma"]["included_in_meta_analysis"] == 8 and r["prisma"]["excluded_at_eligibility"] == 1
    for f in ("fig_forest.pdf", "fig_funnel.pdf", "fig_prisma.pdf"):
        assert (ws / f).stat().st_size > 1000
    for t in (wf.TABLE_FLOW, wf.TABLE_STUDIES, wf.TABLE_RESULTS):
        assert "\\begin{tabular}" in (ws / t).read_text(encoding="utf-8")
    bib = (ws / "literature.bib").read_text(encoding="utf-8")
    assert all(f"{{{k}," in bib for k in METHOD_REFERENCES)
    keys = json.loads((ws / wf.REFERENCES_FILE).read_text(encoding="utf-8"))["studies"]
    assert keys["W105"] == "ekstrom2019grit" and len(keys) == 8
    runs = (ws / ".e2er-script-runs.jsonl").read_text(encoding="utf-8")
    assert '"script": "run_estimation.py"' in runs and '"exit_code": 0' in runs


def test_the_script_runs_without_e2er(ws: Path, fake, tmp_path: Path):
    """run_estimation.py imports nothing from e2er: the rerun e2er reproduce makes."""
    import shutil
    import subprocess
    import sys

    _through(ws, "synthesis")
    alone = tmp_path / "alone"
    alone.mkdir()
    for f in ("run_estimation.py", "meta_studies.csv", "review_protocol.json", "prisma_counts.json"):
        shutil.copy2(ws / f, alone / f)
    assert "from src" not in (alone / "run_estimation.py").read_text(encoding="utf-8")
    subprocess.run([sys.executable, "-I", "run_estimation.py"], cwd=alone, check=True, capture_output=True)
    a = json.loads((alone / "estimation_results.json").read_text(encoding="utf-8"))
    b = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    assert a == b


def test_too_few_studies_give_a_narrative_synthesis(ws: Path, fake):
    p = json.loads(json.dumps(mf.PROTOCOL))
    p["synthesis"]["min_studies"] = 10
    (ws / "review_protocol.json").write_text(json.dumps(p), encoding="utf-8")
    _through(ws, "synthesis")
    r = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    assert r["narrative_only"] and r["pooled"] is None and "at least 10" in r["narrative_reason"]
    assert r["figures"] == ["fig_prisma.pdf"] and not (ws / wf.TABLE_RESULTS).exists()
    assert check_results("metaanalysis", r, ws) == []
    # A draft that reports a pooled estimate anyway is refused.
    (ws / "paper_draft.tex").write_text("\\input{tables/meta_results.tex}", encoding="utf-8")
    assert any("cannot include a pooled-results table" in x for x in wf.draft_problems(ws))


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda r: r["pooled"].update(estimate=r["pooled"]["estimate"] + 0.01), "do not follow from the studies"),
        (lambda r: r["prisma"].update(screened=99), "identified - duplicates removed"),
        (lambda r: r["pooled"].update(p_value=0.5), "does not follow from z"),
        (lambda r: r.update(narrative_only=True), "pooled"),
        (lambda r: r["heterogeneity"].update(i2=120), "i2 between 0 and 100"),
        (lambda r: r.pop("prediction_interval"), "prediction_interval"),
        (lambda r: r["studies"][0].update(se=1.0), "square root of vi"),
        (lambda r: r["small_study_effects"]["egger"].update(p_value=0.9), "egger"),
        (lambda r: r.update(k=7), "number of studies listed"),
    ],
)
def test_the_results_contract_refuses_inconsistent_results(ws: Path, fake, change, match):
    _through(ws, "synthesis")
    r = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    change(r)
    assert any(match in x for x in check_results("metaanalysis", r, ws)), check_results("metaanalysis", r, ws)


def test_a_protocol_changed_after_the_freeze_stops_the_synthesis(ws: Path, fake):
    from src.core.pipeline.preregistration import assemble, freeze

    _through(ws, "extraction")
    assemble(ws, ("review_protocol.json",))
    freeze(ws)
    p = json.loads((ws / "review_protocol.json").read_text(encoding="utf-8"))
    p["synthesis"]["tau2_method"] = "DL"
    (ws / "review_protocol.json").write_text(json.dumps(p), encoding="utf-8")
    v = meta_checks.meta_synthesis(ws)
    assert not v.passed and "changed after it was frozen" in v.reasons[0]


def test_the_number_check_traces_the_tables_and_the_draft_contract(ws: Path, fake):
    from src.core.pipeline.verify_numbers import verify

    _through(ws, "synthesis")
    keys = json.loads((ws / wf.REFERENCES_FILE).read_text(encoding="utf-8"))["studies"]
    draft = "\n".join(
        [
            "\\input{tables/meta_flow.tex}",
            "\\input{tables/meta_studies.tex}",
            "\\input{tables/meta_results.tex}",
            "\\includegraphics{fig_prisma.pdf}\\includegraphics{fig_forest.pdf}\\includegraphics{fig_funnel}",
            "\\citep{" + ",".join(list(keys.values())[:-1]) + "}",
        ]
    )
    (ws / "paper_draft.tex").write_text(draft, encoding="utf-8")
    rep = verify(ws / "paper_draft.tex", ws)
    assert rep.passed and rep.total_values_in_tables >= 60 and rep.mismatched == 0
    problems = wf.draft_problems(ws)
    assert problems == [f"the draft must cite every included study; not cited: {list(keys.values())[-1]}"]
    (ws / "paper_draft.tex").write_text("\\input{tables/meta_studies.tex}", encoding="utf-8")
    joined = " ".join(wf.draft_problems(ws))
    assert "tables/meta_flow.tex" in joined and "fig_forest.pdf" in joined


def test_the_exported_study_is_checked_against_its_quotes(ws: Path, fake):
    _through(ws, "synthesis")
    assert wf.export_check(ws).passed
    csv_path = ws / "meta_studies.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(",412.0,", ",413.0,"), encoding="utf-8")
    v = wf.export_check(ws)
    assert not v.passed and "W101: meta_studies.csv has n = 413" in " ".join(v.reasons)


def test_the_figures_render_from_their_entries(tmp_path: Path):
    from src.core.renderer.figures import render_figures

    spec = {
        "figures": [
            {"filename": "fig_prisma.pdf", "figure_type": "prisma", "counts": {"identified": {"total": 3}}},
            {"filename": "fig_forest.pdf", "figure_type": "forest", "log_x": True, "null_value": 1,
             "studies": [{"label": "A", "estimate": 1.2, "lower": 0.9, "upper": 1.6, "weight": 50}],
             "pooled": {"estimate": 1.2, "lower": 0.9, "upper": 1.6}},
            {"filename": "fig_funnel.pdf", "figure_type": "funnel", "points": [{"estimate": 0.2, "se": 0.1}],
             "pooled": 0.2},
            {"filename": "fig_bad.pdf", "figure_type": "forest", "studies": []},
        ]
    }  # fmt: skip
    (tmp_path / "figure_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    rep = render_figures(tmp_path)
    assert set(rep.rendered) == {"fig_prisma.pdf", "fig_forest.pdf", "fig_funnel.pdf"}
    assert any(s.startswith("fig_bad.pdf") for s in rep.skipped)


# ── the template ────────────────────────────────────────────────────────────


def test_the_template_loads_in_the_order_of_a_systematic_review():
    spec = find_spec("systematic-review", project=ROOT)
    assert [s.name for s in spec.steps] == [
        "design_protocol", "search", "review_protocol", "preregister", "screen", "screening_check",
        "review_screening", "fulltext", "extract", "extraction_check", "review_extraction", "synthesis",
        "write_draft", "review_draft", "polish", "review", "revision",
    ]  # fmt: skip
    assert spec.optional_steps() == ["preregister", "review_extraction"]
    assert spec.results == "metaanalysis" and not spec.causal and spec.base_skill == "base/researcher"
    assert set(spec.panel()) == {
        "methods_reviewer", "data_reviewer", "plausibility_reviewer", "writing_reviewer", "technical_reviewer",
    }  # fmt: skip
    gates = {s.name: s for s in spec.steps if s.kind == "gate"}
    assert all(not g.resumable for g in gates.values())  # every check runs again on resume


def test_the_method_sources_are_credited_with_the_dois_the_references_carry():
    raw = tomllib.loads((ROOT / "pipelines" / "systematic-review.toml").read_text(encoding="utf-8"))
    credit = raw["credit"]
    assert credit[0]["relation"] == "based_on" and credit[0]["url"] == "https://doi.org/10.1136/bmj.n71"
    for c in credit:
        assert c["url"] == f"https://doi.org/{METHOD_REFERENCES[c['cite_key']]['doi']}", c["cite_key"]
    doc = json.loads((ROOT / "credits.json").read_text(encoding="utf-8"))
    assert doc["parts"]["template:systematic-review"] == credit


def test_the_specialists_and_checks_are_registered():
    from src.core.governance import GATES, RELIABILITY_CHECKS
    from src.core.labels import SPECIALISTS, STEPS, TEMPLATES
    from src.core.specialists.registry import SPECIALIST_DEFAULT_FOCUS, SPECIALIST_SIDECAR_ARTIFACTS
    from src.core.strategist.runner import _sequence_check

    for name in ("protocol_designer", "study_screener", "study_extractor", "meta_review_writer"):
        assert name in SPECIALISTS and name in SPECIALIST_DEFAULT_FOCUS
    assert SPECIALIST_SIDECAR_ARTIFACTS["study_extractor"] == ["extraction.json"]
    assert TEMPLATES["systematic-review"] == "Systematic review and meta-analysis"
    spec = find_spec("systematic-review", project=ROOT)
    assert all(s.name in STEPS for s in spec.steps)
    for check in meta_checks.CHECKS:
        assert _sequence_check(check) is meta_checks.CHECKS[check]
        assert check in GATES or check in RELIABILITY_CHECKS
