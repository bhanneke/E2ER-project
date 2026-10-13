"""Checks that pass before the draft (`before`), the template's method sources in the bibliography,
and the claims a seed-independent topic model may not make.

From the text-analysis live run of 2026-10-11: the plan left out the text
validator and the validation check sent it out only after the draft existed;
the template's method sources were credited but not citable; and the draft
claimed topics stable across seeds of an NMF model started from nndsvda.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.spec import PipelineError, find_spec, spec_from_dict

# ── before: the spec ─────────────────────────────────────────────────────────


def _pipeline(*steps: dict) -> dict:
    return {"name": "t", "steps": [{"kind": "strategist", "name": "initial"}, *steps]}


def test_a_gate_inside_the_dispatch_can_hold_the_drafter_back():
    spec = spec_from_dict(
        _pipeline(
            {
                "kind": "gate",
                "name": "g",
                "check": "text_validation",
                "after": ["econometrics_specialist", "text_validator"],
                "before": ["paper_drafter"],
            }
        )
    )
    assert spec.step("g").before == ("paper_drafter",)


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"kind": "researcher", "name": "r", "after": ["data_architect"], "before": ["paper_drafter"]}, "gate steps"),
        (
            {
                "kind": "gate",
                "name": "g",
                "check": "text_results",
                "after": ["econometrics_specialist"],
                "before": ["x"],
            },
            "unknown specialist",
        ),
        (
            {
                "kind": "gate",
                "name": "g",
                "check": "text_results",
                "after": ["econometrics_specialist"],
                "before": ["econometrics_specialist"],
            },
            "both",
        ),
        # A check of its own cannot hold back a specialist the strategist dispatches.
        ({"kind": "gate", "name": "g", "check": "figure_data", "before": ["paper_drafter"]}, "needs `after`"),
    ],
)
def test_before_is_refused_where_it_cannot_hold(step: dict, message: str):
    with pytest.raises(PipelineError, match=message):
        spec_from_dict(_pipeline(step))


def test_a_check_of_its_own_must_come_before_the_step_that_runs_the_writer():
    gate = {"kind": "gate", "name": "g", "check": "meta_synthesis", "before": ["meta_review_writer"]}
    write = {"kind": "specialists", "name": "w", "run": ["meta_review_writer"]}
    assert spec_from_dict({"name": "t", "steps": [gate, write]}).step("g").before == ("meta_review_writer",)
    with pytest.raises(PipelineError, match="must come before the step that runs meta_review_writer"):
        spec_from_dict({"name": "t", "steps": [write, gate]})


def test_the_figure_and_forecast_checks_may_also_sit_inside_the_dispatch():
    for check in ("figure_data", "forecast_evaluation"):
        step = {"kind": "gate", "name": "g", "check": check, "after": ["econometrics_specialist"]}
        assert spec_from_dict(_pipeline(step)).step("g").after == ("econometrics_specialist",)
    with pytest.raises(PipelineError, match="takes no `after`"):
        spec_from_dict(_pipeline({"kind": "gate", "name": "g", "check": "numbers", "after": ["paper_drafter"]}))


@pytest.mark.parametrize(
    ("template", "steps", "writer"),
    [
        ("text-analysis", ["text_results_gate", "text_validation_gate"], "paper_drafter"),
        ("policy-evaluation", ["did_results_gate"], "paper_drafter"),
        ("spatial-analysis", ["spatial_results_gate"], "paper_drafter"),
        ("descriptive-study", ["data_quality_gate", "figures_before_draft"], "paper_drafter"),
        ("time-series-forecasting", ["forecasts_before_draft"], "paper_drafter"),
        ("systematic-review", ["extraction_check", "synthesis"], "meta_review_writer"),
    ],
)
def test_the_shipped_templates_check_before_the_draft(template: str, steps: list[str], writer: str):
    spec = find_spec(template)
    for name in steps:
        assert spec.step(name).before == (writer,), (template, name)


def test_the_strategist_is_told_the_drafter_waits_for_the_check():
    from src.core.pipeline.components import activate, deactivate
    from src.core.strategist.context import template_context

    token = activate(find_spec("text-analysis"))
    try:
        text = template_context()
    finally:
        deactivate(token)
    line = next(x for x in text.splitlines() if "(text_validation)" in x)
    assert "Dispatch text_validator after econometrics_specialist and before paper_drafter" in line
    assert "paper_drafter is not dispatched until this check has passed" in line


# ── the template's method sources ────────────────────────────────────────────


def test_each_cited_credit_becomes_a_bibtex_entry_with_a_stable_key():
    from src.core.method_sources import bibtex, method_credits

    credits = method_credits(find_spec("text-analysis"))
    assert len(credits) == 9
    entries = dict(bibtex(c, "text-analysis") for c in credits)
    assert set(entries) == {
        "dunning1993accurate",
        "rayson2000comparing",
        "hardie2014log",
        "church1990word",
        "blei2003latent",
        "lee1999learning",
        "greene2014many",
        "grimmer2013text",
        "gentzkow2019text",
    }
    nmf = entries["lee1999learning"]
    assert nmf.startswith("@article{lee1999learning,")
    assert "author = {Daniel D. Lee and H. Sebastian Seung}" in nmf
    assert "journal = {Nature}" in nmf and "volume = {401}" in nmf and "pages = {788--791}" in nmf
    assert "doi = {10.1038/44565}" in nmf and "e2er_source = {template}" in nmf
    assert "e2er_template = {text-analysis}" in nmf
    assert entries["hardie2014log"].startswith("@misc{")  # a web page
    assert "url = {https://aclanthology.org/J93-1003/}" in entries["dunning1993accurate"]


def test_a_credit_with_its_own_key_keeps_it_and_the_modules_fuller_entry():
    from src.core.method_sources import bibtex, method_credits

    entries = dict(bibtex(c, "systematic-review") for c in method_credits(find_spec("systematic-review")))
    assert "dersimonian1986meta" in entries and "page2021prisma" not in entries  # PRISMA is based_on
    entry = entries["dersimonian1986meta"]
    assert "pages = {177--188}" in entry and "e2er_source = {template}" in entry


def test_the_sources_are_added_once_and_an_existing_key_is_kept(tmp_path: Path):
    from src.core.method_sources import add_method_sources

    spec = find_spec("text-analysis")
    (tmp_path / "literature.bib").write_text(
        "@article{blei2003latent,\n  title = {Mine},\n  e2er_source = {researcher},\n}\n", encoding="utf-8"
    )
    added = add_method_sources(tmp_path, spec)
    assert len(added) == 8 and "blei2003latent" not in added
    text = (tmp_path / "literature.bib").read_text(encoding="utf-8")
    assert "title = {Mine}" in text and text.count("@") == 9
    assert add_method_sources(tmp_path, spec) == []
    assert (tmp_path / "literature.bib").read_text(encoding="utf-8") == text
    from src.core.pipeline.verify_citations import load_bib

    bib = load_bib(tmp_path / "literature.bib")
    assert len(bib) == 9 and bib["lee1999learning"]["e2er_source"] == "template"


def test_a_template_without_cited_sources_adds_nothing(tmp_path: Path):
    from src.core.method_sources import add_method_sources

    assert add_method_sources(tmp_path, find_spec("empirical")) == []
    assert not (tmp_path / "literature.bib").exists()


def test_the_writers_see_the_method_sources_marked_and_told_to_cite_only_what_they_used(tmp_path, monkeypatch):
    from src.core.method_sources import add_method_sources
    from src.core.specialists import base

    add_method_sources(tmp_path, find_spec("text-analysis"))
    monkeypatch.setattr("src.home.find_workspace", lambda _pid, _root: tmp_path)
    listing = base._workspace_bib_for_prompt("paper_drafter", "p")
    assert "\\cite{lee1999learning}" in listing and "[method source]" in listing
    assert "Cite only the methods the study used" in listing


def test_the_dossier_and_the_finish_page_name_them_method_sources(tmp_path: Path):
    from src.core import labels
    from src.core.dossier import _references
    from src.core.method_sources import add_method_sources

    paper = tmp_path / "bundle" / "paper"
    paper.mkdir(parents=True)
    add_method_sources(tmp_path, find_spec("text-analysis"))
    (paper / "refs.bib").write_text((tmp_path / "literature.bib").read_text(encoding="utf-8"), encoding="utf-8")
    (paper / "paper.tex").write_text("G2 \\citep{dunning1993accurate}.", encoding="utf-8")
    refs = _references(tmp_path / "bundle")
    assert refs == [
        {
            "key": "dunning1993accurate",
            "title": "Accurate Methods for the Statistics of Surprise and Coincidence",
            "source": "template",
            "year": "1993",
        }
    ]
    assert labels.reference_source("template") == "method source"


async def test_the_citation_check_verifies_a_method_source_like_any_reference(tmp_path: Path):
    from src.core.method_sources import add_method_sources
    from src.core.pipeline.verify_citations import verify
    from src.modules.literature.models import PaperMetadata

    add_method_sources(tmp_path, find_spec("text-analysis"))
    draft = tmp_path / "paper_draft.tex"
    draft.write_text("NMF \\citep{lee1999learning}.", encoding="utf-8")
    found = PaperMetadata(
        title="Learning the parts of objects by non-negative matrix factorization", doi="10.1038/44565"
    )
    fetch = AsyncMock(return_value=found)
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=fetch),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=AsyncMock()),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=AsyncMock()),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=AsyncMock()),
    ):
        report = await verify(draft, bib_path=tmp_path / "literature.bib")
    assert report.verified == 1 and report.missing_in_bib == 0 and report.passed
    assert fetch.await_args.args[0] == "10.1038/44565"
    # Not cited, not required: the other eight are only listed as uncited.
    assert len(report.bibbed_uncited) == 8


# ── NMF from nndsvd: no stability across seeds ───────────────────────────────


def _text_check(ws: Path, models: list[str]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "text_check.json").write_text(
        json.dumps({"passed": True, "notes": [], "seed_independent_models": models}), encoding="utf-8"
    )


CLAIMS = [
    "The topics are stable across seeds (mean best-match Jaccard 1.0).",
    "An NMF model gives the same top terms with every seed for 3, 4 and 5 topics (stability 1.0).",
    "The topic model is robust to the choice of seed.",
]
HONEST = [
    "The NMF model starts from nndsvda, so every seed gives the same fit; its stability is not tested.",
    "The fit does not depend on the seed, so the runs say nothing about the stability of the topics.",
    "We fix the seed at 42 for the dictionary sample.",
]


@pytest.mark.parametrize("sentence", CLAIMS)
def test_a_stability_claim_of_a_seed_independent_model_is_refused(tmp_path: Path, sentence: str):
    from src.core.writing_check import refused_claims

    _text_check(tmp_path, ["topics"])
    hits = refused_claims(tmp_path, f"\\section{{Results}}\n{sentence}\n")
    assert [h.phrase for h in hits] == ["stability across seeds"], sentence
    assert "nndsvd" in hits[0].fix and "topics" in hits[0].fix


@pytest.mark.parametrize("sentence", HONEST)
def test_saying_the_fit_ignores_the_seed_passes(tmp_path: Path, sentence: str):
    from src.core.writing_check import refused_claims

    _text_check(tmp_path, ["topics"])
    assert refused_claims(tmp_path, sentence) == []


def test_with_a_random_start_or_no_text_check_the_claim_is_the_researchers(tmp_path: Path):
    from src.core.writing_check import refused_claims

    assert refused_claims(tmp_path, CLAIMS[0]) == []
    _text_check(tmp_path, [])
    assert refused_claims(tmp_path, CLAIMS[0]) == []


def test_the_draft_writers_contract_sends_the_claim_back(tmp_path: Path):
    from src.core.specialists.contract_check import check_draft_phrases, check_patch_phrases

    _text_check(tmp_path, ["topics"])
    (tmp_path / "paper_draft.tex").write_text(CLAIMS[0], encoding="utf-8")
    result = check_draft_phrases(tmp_path, "paper_draft.tex")
    assert not result.ok and "stability across seeds" in result.reason
    (tmp_path / "paper_draft.tex.edits.json").write_text(
        json.dumps({"edits": [{"edit_type": "replace_text", "find": "x", "replace": CLAIMS[2]}]}), encoding="utf-8"
    )
    assert not check_patch_phrases(tmp_path).ok
    (tmp_path / "paper_draft.tex").write_text(HONEST[0], encoding="utf-8")
    assert check_draft_phrases(tmp_path, "paper_draft.tex").ok


@pytest.mark.parametrize(("init", "independent"), [("", True), ("nndsvd", True), ("nndsvda", True), ("random", False)])
def test_which_nmf_starts_ignore_the_seed(init: str, independent: bool):
    from src.core.pipeline.text_checks import seed_independent_init

    assert seed_independent_init(init) is independent
    assert seed_independent_init("nndsvdar") is False


def test_method_sources_alone_do_not_make_a_draft_without_citations_fail(tmp_path: Path):
    """Nothing forces a paper to cite them: a study whose bibliography holds only the template's
    method sources is a study without literature to the 'cites no work' contract."""
    from src.core.method_sources import add_method_sources
    from src.core.pipeline.verify_citations import study_references

    add_method_sources(tmp_path, find_spec("text-analysis"))
    assert study_references(tmp_path) == 0
    with (tmp_path / "literature.bib").open("a", encoding="utf-8") as f:
        f.write("\n@article{web2021found,\n  title = {Found},\n  e2er_source = {web},\n}\n")
    assert study_references(tmp_path) == 1
