"""M2: citation-integrity gate — parse, verify, report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.verify_citations import (
    STATUS_MISSING_IN_BIB,
    STATUS_VERIFIED_DOI,
    STATUS_VERIFIED_TITLE,
    _normalize_doi,
    _normalize_title,
    _pick_title_match,
    _title_similar,
    load_bib,
    parse_bibitem_keys,
    parse_cite_keys,
    render_human,
    verify,
    verify_and_save,
)
from src.modules.literature.models import PaperMetadata

# ── Parsing ──────────────────────────────────────────────────────────────────


def test_parse_cite_keys_basic_variants():
    tex = r"""
    See \cite{smith2020} and \citep{jones2019,doe2018}.
    Per \citet{lee2021} and \citeauthor{kim2017}, also \citeyear{kim2017}.
    \autocite{biber2022} \textcite{biber2022} \parencite{martin2015}.
    """
    keys = parse_cite_keys(tex)
    # Dedup preserves first appearance; kim2017 appears twice → once.
    assert keys == [
        "smith2020",
        "jones2019",
        "doe2018",
        "lee2021",
        "kim2017",
        "biber2022",
        "martin2015",
    ]


def test_parse_cite_keys_with_prenote_postnote():
    tex = r"As shown by \citep[see][p.~12]{smith2020} and \citet[][Ch.~3]{jones2019}."
    assert parse_cite_keys(tex) == ["smith2020", "jones2019"]


def test_parse_cite_keys_starred_variant():
    # \cite*{key} — natbib starred form ("expand author list")
    tex = r"\cite*{abc1990}"
    assert parse_cite_keys(tex) == ["abc1990"]


def test_parse_cite_keys_ignores_commented_lines():
    tex = "Real cite: \\cite{real2020}\n% Fake: \\cite{ghost1999}\n"
    assert parse_cite_keys(tex) == ["real2020"]


def test_parse_cite_keys_respects_escaped_percent():
    # \% is a literal percent — comment doesn't start there.
    tex = r"Inflation rose 5\% then \cite{infl2020} was published."
    assert parse_cite_keys(tex) == ["infl2020"]


def test_parse_bibitem_keys():
    tex = r"""
    \begin{thebibliography}{}
    \bibitem{smith2020} Smith, J. (2020). A title.
    \bibitem[Jones et al.]{jones2019} Jones et al. (2019).
    \end{thebibliography}
    """
    assert parse_bibitem_keys(tex) == ["smith2020", "jones2019"]


def test_load_bib(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """
@article{smith2020,
  title={The Title},
  author={Smith, J.},
  year={2020},
  doi={10.1000/xyz}
}
@book{jones2019,
  title={Another Title},
  author={Jones, A.},
  year={2019}
}
""",
        encoding="utf-8",
    )
    out = load_bib(bib)
    assert set(out.keys()) == {"smith2020", "jones2019"}
    assert out["smith2020"]["doi"] == "10.1000/xyz"
    assert out["smith2020"]["year"] == "2020"


def test_load_bib_missing_file_returns_empty(tmp_path: Path):
    assert load_bib(tmp_path / "nope.bib") == {}


# ── Title / DOI helpers ──────────────────────────────────────────────────────


def test_normalize_doi_strips_url_prefixes():
    assert _normalize_doi("https://doi.org/10.1000/X") == "10.1000/x"
    assert _normalize_doi("doi:10.1000/X") == "10.1000/x"
    assert _normalize_doi("10.1000/X") == "10.1000/x"
    assert _normalize_doi("") == ""


def test_normalize_title_strips_braces_and_punct():
    assert _normalize_title("{The Title}: A Subtitle!") == "the title a subtitle"


def test_normalize_title_strips_accents():
    assert _normalize_title("Économétrie") == "econometrie"


def test_title_similar_exact_match():
    assert _title_similar("Foo Bar", "foo bar") == 1.0


def test_title_similar_unrelated_low():
    assert _title_similar("Foo Bar", "Completely Different") < 0.5


def test_pick_title_match_above_cutoff():
    bib_title = "Concentrated Liquidity in Automated Market Makers"
    candidates = [
        PaperMetadata(title="Concentrated Liquidity in Automated Market Makers", year=2023),
        PaperMetadata(title="Something totally unrelated about volatility", year=2023),
    ]
    match = _pick_title_match(candidates, bib_title, 2023)
    assert match is not None and match.title.startswith("Concentrated")


def test_pick_title_match_year_drift_rejects_far_when_fuzzy():
    # Fuzzy match (not exact) — year gate stays at ±1.
    candidates = [PaperMetadata(title="The Same Title with slight drift", year=1995)]
    assert _pick_title_match(candidates, "The Exact Same Title", 2023) is None


def test_pick_title_match_exact_accepts_any_year():
    # Exact title (sim>=0.99) — reprints / proceedings drift get through.
    # Live-test bug: OpenAlex's top hit for "Attention Is All You Need" was
    # a 2025 reprint; bib said 2017. With strict ±1 gate we'd reject the
    # canonical paper. Exact title overrides the year gate.
    candidates = [PaperMetadata(title="Attention Is All You Need", year=2025)]
    match = _pick_title_match(candidates, "Attention Is All You Need", 2017)
    assert match is not None and match.year == 2025


def test_pick_title_match_no_year_in_one_side_ok():
    # If either side lacks a year, year-gate is skipped.
    candidates = [PaperMetadata(title="The Exact Same Title", year=None)]
    assert _pick_title_match(candidates, "The Exact Same Title", 2023) is not None


# ── verify() end-to-end ──────────────────────────────────────────────────────


def _stub_paper(doi: str = "", title: str = "X") -> PaperMetadata:
    return PaperMetadata(title=title, doi=doi, year=2020)


def _empty_search():
    """A SearchResult-shaped object with no papers — for mocking search misses."""
    return type("R", (), {"papers": []})()


def _search_with(*papers: PaperMetadata):
    return type("R", (), {"papers": list(papers)})()


@pytest.fixture
def draft_and_bib(tmp_path: Path):
    """A draft with two cites + a bib with two matching entries + one orphan."""
    draft = tmp_path / "paper_draft.tex"
    draft.write_text(
        r"""
        Per \cite{good2020} and \citep{good2021}, but also \cite{hallucinated2024}.
        """,
        encoding="utf-8",
    )
    bib = tmp_path / "references.bib"
    bib.write_text(
        """
@article{good2020, title={Good Paper One}, year={2020}, doi={10.1/g1}}
@article{good2021, title={Good Paper Two}, year={2021}, doi={10.1/g2}}
@article{never_cited, title={Orphan}, year={2019}, doi={10.1/orph}}
""",
        encoding="utf-8",
    )
    return draft, bib


async def test_verify_happy_path(draft_and_bib, tmp_path: Path):
    draft, bib = draft_and_bib
    g1 = _stub_paper(doi="10.1/g1", title="Good Paper One")
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=AsyncMock(return_value=g1)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=AsyncMock()),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=AsyncMock()),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=AsyncMock()),
    ):
        report = await verify(draft, bib_path=bib)
    # Two of three keys verify by DOI (the same stub responds for both DOIs);
    # the third (hallucinated2024) isn't in the bib → missing_in_bib.
    assert report.total_cites == 3
    assert report.verified == 2
    assert report.missing_in_bib == 1
    assert report.bibbed_uncited == ["never_cited"]
    assert report.passed is False  # missing_in_bib always fails


async def test_verify_missing_in_bib_only_fails(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"See \cite{ghost}.", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text("@article{real, title={Real}, year={2020}}", encoding="utf-8")
    report = await verify(draft, bib_path=bib)
    assert report.missing_in_bib == 1
    assert report.passed is False


async def test_verify_unverifiable_warn_by_default(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"See \cite{obscure}.", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{obscure, title={An obscure working paper nobody indexes}, year={2024}}",
        encoding="utf-8",
    )
    empty = _empty_search()
    with (
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=AsyncMock(return_value=empty)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=AsyncMock(return_value=empty)),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=AsyncMock(return_value=empty)),
    ):
        report = await verify(draft, bib_path=bib)
    assert report.unverifiable == 1
    # Default policy: unverifiable is warn-only.
    assert report.passed is True


async def test_verify_unverifiable_strict_fails(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"See \cite{obscure}.", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{obscure, title={An obscure working paper nobody indexes}, year={2024}}",
        encoding="utf-8",
    )
    empty = _empty_search()
    with (
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=AsyncMock(return_value=empty)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=AsyncMock(return_value=empty)),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=AsyncMock(return_value=empty)),
    ):
        report = await verify(draft, bib_path=bib, strict=True)
    assert report.unverifiable == 1
    assert report.passed is False
    assert report.strict is True


async def test_verify_skipped_when_no_cites(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text("Just text, no citations.", encoding="utf-8")
    report = await verify(draft)
    assert report.skipped_reason and "no \\cite" in report.skipped_reason
    assert report.passed is True  # skipped == pass per the verify_numbers convention


async def test_verify_skipped_when_no_bib(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"See \cite{foo}.", encoding="utf-8")
    # No references.bib + no \bibitem → skipped.
    report = await verify(draft)
    assert report.skipped_reason and "no bibliography" in report.skipped_reason


async def test_verify_falls_through_doi_chain_to_title_search(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"\cite{x2020}", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{x2020, title={The Exact Title}, year={2020}, doi={10.1/x}}",
        encoding="utf-8",
    )
    # All three DOI lookups fail; OpenAlex title search finds it.
    title_hit = _search_with(PaperMetadata(title="The Exact Title", year=2020, doi="10.1/x"))
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=AsyncMock(return_value=title_hit)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=AsyncMock()),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=AsyncMock()),
    ):
        report = await verify(draft, bib_path=bib)
    assert report.verified == 1
    assert report.checks[0].status == STATUS_VERIFIED_TITLE
    assert report.checks[0].verifier == "openalex"


# ── verify_and_save persists the report ──────────────────────────────────────


async def test_verify_and_save_writes_json(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"\cite{good}", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text("@article{good, title={Good}, year={2020}, doi={10.1/g}}", encoding="utf-8")
    good = _stub_paper(doi="10.1/g", title="Good")
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=AsyncMock(return_value=good)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
    ):
        report = await verify_and_save(draft, tmp_path, bib_path=bib)
    out = tmp_path / "citation_integrity.json"
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["verified"] == 1
    assert data["checks"][0]["status"] == STATUS_VERIFIED_DOI
    assert report.passed is True


# ── render_human ─────────────────────────────────────────────────────────────


def test_render_human_pass():
    from src.core.pipeline.verify_citations import CitationIntegrityReport

    r = CitationIntegrityReport(passed=True, total_cites=2, verified=2)
    out = render_human(r)
    assert "✅ Passed" in out


def test_render_human_missing_in_bib_fails():
    from src.core.pipeline.verify_citations import CitationCheck, CitationIntegrityReport

    r = CitationIntegrityReport(
        passed=False,
        total_cites=1,
        missing_in_bib=1,
        checks=[CitationCheck(cite_key="ghost", status=STATUS_MISSING_IN_BIB)],
    )
    out = render_human(r)
    assert "❌ Failed" in out and "ghost" in out


def test_render_human_skipped():
    from src.core.pipeline.verify_citations import CitationIntegrityReport

    r = CitationIntegrityReport(skipped_reason="no \\cite commands")
    out = render_human(r)
    assert "Skipped" in out


# ── CLI integration ──────────────────────────────────────────────────────────


def test_cli_verify_citations_help_lists_subcommand():
    r = subprocess.run(
        [sys.executable, "-m", "src", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert r.returncode == 0
    assert "verify-citations" in r.stdout
