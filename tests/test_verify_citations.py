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
    STATUS_UNVERIFIABLE,
    STATUS_VERIFIED_DOI,
    STATUS_VERIFIED_TITLE,
    _normalize_doi,
    _normalize_title,
    _pick_title_match,
    _title_similar,
    load_bib,
    parse_bibitem_entries,
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


# ── parse_bibitem_entries (M4.2) ─────────────────────────────────────────────


def test_parse_bibitem_entries_m4_regression():
    """Exact format from the M4 Welch-Goyal paper that had 9/9 unverifiable."""
    tex = r"""
    \begin{thebibliography}{99}
    \bibitem[Welch and Goyal(2008)]{welch2008}
    Welch, I. and Goyal, A. (2008).
    A comprehensive look at the empirical performance of equity premium prediction.
    \textit{Review of Financial Studies}, 21(4), 1455--1508.
    \end{thebibliography}
    """
    out = parse_bibitem_entries(tex)
    assert "welch2008" in out
    entry = out["welch2008"]
    assert entry["year"] == "2008"
    assert "comprehensive look" in entry["title"].lower()
    assert "Review of Financial Studies" not in entry["title"]  # journal stripped
    assert entry["doi"] == ""


def test_parse_bibitem_entries_with_doi():
    tex = r"""
    \begin{thebibliography}{}
    \bibitem{x2020}
    Author, A. (2020). A great paper title. \textit{Journal}, 1(1), 1--10.
    doi:10.1000/abc.1234
    \end{thebibliography}
    """
    out = parse_bibitem_entries(tex)
    assert out["x2020"]["doi"] == "10.1000/abc.1234"
    assert out["x2020"]["year"] == "2020"


def test_parse_bibitem_entries_doi_url_form():
    tex = r"""\bibitem{y2021} Author (2021). Title. https://doi.org/10.5555/zzzz."""
    out = parse_bibitem_entries(tex)
    assert out["y2021"]["doi"] == "10.5555/zzzz"


def test_parse_bibitem_entries_year_only_in_label():
    """Body uses ``Author, 2008.`` instead of ``(2008).`` — fall back to label year."""
    tex = r"""
    \bibitem[Author(2008)]{a2008}
    Author, A., 2008. The title. Journal, 1(1).
    """
    out = parse_bibitem_entries(tex)
    assert out["a2008"]["year"] == "2008"


def test_parse_bibitem_entries_multiple_entries():
    tex = r"""
    \begin{thebibliography}{}
    \bibitem[Welch and Goyal(2008)]{welch2008}
    Welch, I. and Goyal, A. (2008).
    A comprehensive look at the empirical performance of equity premium prediction.
    \textit{Review of Financial Studies}, 21(4), 1455--1508.

    \bibitem[Clark and West(2007)]{clarkwest2007}
    Clark, T. E. and West, K. D. (2007).
    Approximately normal tests for equal predictive accuracy in nested models.
    \textit{Journal of Econometrics}, 138(1), 291--311.
    \end{thebibliography}
    """
    out = parse_bibitem_entries(tex)
    assert set(out.keys()) == {"welch2008", "clarkwest2007"}
    assert "comprehensive look" in out["welch2008"]["title"].lower()
    assert "approximately normal" in out["clarkwest2007"]["title"].lower()
    assert out["clarkwest2007"]["year"] == "2007"


def test_parse_bibitem_entries_no_bibitems_returns_empty():
    assert parse_bibitem_entries("just prose, no bibitem here") == {}


def test_parse_bibitem_entries_no_journal_marker_falls_back():
    """No \\textit{...} — title falls back to 'first sentence after year'."""
    tex = r"""\bibitem{x} Author (2020). A no-journal-marker title. Conference, 2020."""
    out = parse_bibitem_entries(tex)
    # We don't promise a perfect cut without the journal marker, but the
    # title MUST contain the recognisable subtitle and MUST NOT be empty.
    title = out["x"]["title"].lower()
    assert "no-journal-marker title" in title or "title" in title
    assert out["x"]["title"]  # non-empty


async def test_verify_uses_bibitem_bodies_end_to_end(tmp_path: Path):
    """End-to-end: a \\bibitem-only paper with a parseable title goes from
    'unverifiable' (pre-M4.2) to 'verified_title' (post-M4.2)."""
    from unittest.mock import AsyncMock, patch

    draft = tmp_path / "paper_draft.tex"
    draft.write_text(
        r"""
        Per \cite{welch2008}, the historical mean is hard to beat.
        \begin{thebibliography}{}
        \bibitem[Welch and Goyal(2008)]{welch2008}
        Welch, I. and Goyal, A. (2008).
        A comprehensive look at the empirical performance of equity premium prediction.
        \textit{Review of Financial Studies}, 21(4), 1455--1508.
        \end{thebibliography}
        """,
        encoding="utf-8",
    )
    # No DOI in body → DOI chain fails; OpenAlex title-search returns
    # the canonical paper.
    canonical = PaperMetadata(
        title="A Comprehensive Look at the Empirical Performance of Equity Premium Prediction",
        year=2008,
        doi="10.1093/rfs/hhm014",
    )
    title_hit = type("R", (), {"papers": [canonical]})()
    empty = type("R", (), {"papers": []})()
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=AsyncMock(return_value=title_hit)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=AsyncMock(return_value=empty)),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=AsyncMock(return_value=empty)),
    ):
        report = await verify(draft)  # No references.bib → bibitem path.
    assert report.total_cites == 1
    assert report.verified == 1
    assert report.checks[0].status == STATUS_VERIFIED_TITLE
    assert report.checks[0].verifier == "openalex"


async def test_verify_bibitem_entry_with_empty_body_is_unverifiable(tmp_path: Path):
    """If parse_bibitem_entries can't extract a title for an entry,
    we still report ``unverifiable`` (not ``missing_in_bib``) so the
    distinction between 'LaTeX would also fail' and 'bib content too
    sparse to verify' is preserved."""
    draft = tmp_path / "paper_draft.tex"
    draft.write_text(
        r"""
        See \cite{minimal}.
        \begin{thebibliography}{}
        \bibitem{minimal}
        \end{thebibliography}
        """,
        encoding="utf-8",
    )
    report = await verify(draft)
    assert report.total_cites == 1
    assert report.missing_in_bib == 0
    assert report.unverifiable == 1
    assert report.checks[0].status == STATUS_UNVERIFIABLE


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


async def test_citing_with_no_bibliography_fails_rather_than_skips(tmp_path: Path):
    """A draft that cites with no bibliography is a finding, not a skip.

    This used to skip with passed=True. The 2026-09-01 repeats cell shows what
    that costs: paper 7274dddc cited 14 distinct keys and ee229dca 19, both
    with no .bib and no \\bibitem, and the gate and the experiment's
    fabrication count reported both clean.

    The keys themselves are largely real papers recalled from memory, so this
    asserts "unverifiable and uncompilable", not "fabricated".
    """
    draft = tmp_path / "draft.tex"
    draft.write_text(r"See \cite{foo} and \citep{bar, baz}.", encoding="utf-8")

    report = await verify(draft)

    assert report.skipped_reason is None, "no bibliography is a finding, not a skip"
    assert report.passed is False
    assert report.total_cites == 3
    assert report.missing_in_bib == 3
    assert report.bibliography_source is None
    assert {c.cite_key for c in report.missing_checks} == {"foo", "bar", "baz"}


async def test_bibliography_source_records_the_bib_actually_used(tmp_path: Path):
    draft = tmp_path / "draft.tex"
    draft.write_text(r"\cite{x2020}", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text("@article{x2020, title={T}, year={2020}}", encoding="utf-8")

    none_ = AsyncMock(return_value=None)
    empty = AsyncMock(return_value=_search_with())
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=none_),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=none_),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=none_),
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=empty),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=empty),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=empty),
    ):
        report = await verify(draft)

    assert report.bibliography_source == str(bib)
    assert report.missing_in_bib == 0


async def test_bibitem_only_draft_records_its_source(tmp_path: Path):
    """A hand-rolled thebibliography still counts as a bibliography."""
    draft = tmp_path / "draft.tex"
    draft.write_text(
        r"\cite{k1}"
        "\n\\begin{thebibliography}{9}\n"
        r"\bibitem{k1} A. Author. A Real Title. Journal, 2020."
        "\n\\end{thebibliography}\n",
        encoding="utf-8",
    )
    none_ = AsyncMock(return_value=None)
    empty = AsyncMock(return_value=_search_with())
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=none_),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=none_),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=none_),
        patch("src.core.pipeline.verify_citations.openalex.search_papers", new=empty),
        patch("src.core.pipeline.verify_citations.semantic_scholar.search_papers", new=empty),
        patch("src.core.pipeline.verify_citations.crossref.search_papers", new=empty),
    ):
        report = await verify(draft)

    assert report.skipped_reason is None
    assert report.missing_in_bib == 0
    assert report.bibliography_source == "\\bibitem entries in draft"


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


# ── Default bib fallback chain (the "gate silently skipped itself" fix) ─────
# The standard pipeline writes literature.bib (ingest) and refs.bib
# (assembled for compile) — never references.bib. The gate's default must
# find them, otherwise it exits skipped/passed=True on every paper.


async def test_verify_default_falls_back_to_literature_bib(tmp_path: Path):
    draft = tmp_path / "paper_draft.tex"
    draft.write_text(r"See \cite{ghost2024}.", encoding="utf-8")
    (tmp_path / "literature.bib").write_text("@article{real2020, title={Real}, year={2020}}", encoding="utf-8")
    report = await verify(draft)
    assert not report.skipped_reason, "gate skipped despite literature.bib being present"
    assert report.missing_in_bib == 1  # proves literature.bib was actually loaded
    assert report.passed is False


async def test_verify_default_prefers_refs_bib_over_literature_bib(tmp_path: Path):
    draft = tmp_path / "paper_draft.tex"
    draft.write_text(r"See \cite{merged2020}.", encoding="utf-8")
    # merged2020 exists ONLY in refs.bib — if literature.bib won, it would
    # report missing_in_bib.
    (tmp_path / "refs.bib").write_text(
        "@article{merged2020, title={Merged}, year={2020}, doi={10.1/m}}", encoding="utf-8"
    )
    (tmp_path / "literature.bib").write_text("@article{other2019, title={Other}, year={2019}}", encoding="utf-8")
    stub = _stub_paper(doi="10.1/m", title="Merged")
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=AsyncMock(return_value=stub)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
    ):
        report = await verify(draft)
    assert report.missing_in_bib == 0
    assert report.verified == 1
    assert report.passed is True


async def test_gate_composition_with_assembled_refs_bib(tmp_path: Path):
    """The runner assembles refs.bib from the ingested library and passes it
    to the gate explicitly — a hallucinated cite must now fail, not skip."""
    from src.core.renderer.templates import assemble_refs_bib

    draft = tmp_path / "paper_draft.tex"
    draft.write_text(r"Real \cite{real2020} and fake \cite{ghost2024}.", encoding="utf-8")
    (tmp_path / "literature.bib").write_text(
        "@article{real2020, title={Real}, year={2020}, doi={10.1/r}}", encoding="utf-8"
    )
    refs_bib = assemble_refs_bib(tmp_path)
    assert refs_bib is not None and refs_bib.name == "refs.bib"

    stub = _stub_paper(doi="10.1/r", title="Real")
    with (
        patch("src.core.pipeline.verify_citations.openalex.fetch_by_doi", new=AsyncMock(return_value=stub)),
        patch("src.core.pipeline.verify_citations.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=None)),
        patch("src.core.pipeline.verify_citations.crossref.fetch_by_doi", new=AsyncMock(return_value=None)),
    ):
        report = await verify(draft, bib_path=refs_bib)
    assert report.total_cites == 2
    assert report.verified == 1
    assert report.missing_in_bib == 1
    assert report.passed is False
