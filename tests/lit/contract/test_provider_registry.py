"""Lane B — provider interface + registry (M1 of docs/MODULARIZATION_PLAN.md).

The registry formalizes the de-facto interface the source modules already
shared. These tests pin:
  - the capability sub-types (SearchSource / ReferenceLibrary),
  - the registry's fallback ordering (which reproduces the pre-M1 handler
    chains exactly — search: OpenAlex→arXiv, fetch: OpenAlex→S2),
  - the adapters delegate to the underlying module functions,
  - LocalBibLibrary's collect/parse/path-dedup behaviour.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.modules.literature.providers import (
    ArxivSource,
    LocalBibLibrary,
    OpenAlexSource,
    ReferenceLibrary,
    SearchSource,
    SemanticScholarSource,
)
from src.modules.literature.registry import (
    doi_fetch_sources,
    reference_libraries,
    search_sources,
)


def _settings(**kwargs):
    base = {
        "literature_bibtex_file": None,
        "local_data_dir": None,
        "zotero_enabled": False,
        "zotero_api_key": None,
        "zotero_user_id": None,
        "zotero_group_id": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _bib(title: str, year: int = 2024) -> str:
    key = title.lower().replace(" ", "_")
    return f"@article{{{key}, title={{{title}}}, author={{Doe, J.}}, year={{{year}}}, journal={{Test J.}}}}\n"


# ---------------------------------------------------------------------------
# Registry ordering — must reproduce the pre-M1 fallback chains
# ---------------------------------------------------------------------------


def test_search_chain_is_openalex_then_arxiv():
    sources = search_sources(_settings())
    assert [s.name for s in sources] == ["openalex", "arxiv"]
    assert all(isinstance(s, SearchSource) for s in sources)


def test_fetch_chain_is_openalex_then_semantic_scholar():
    """S2 is the by-DOI fallback; arXiv (no DOI lookup) is absent here."""
    sources = doi_fetch_sources(_settings())
    assert [s.name for s in sources] == ["openalex", "semantic_scholar"]


def test_semantic_scholar_kept_out_of_search_chain():
    """Deliberate: S2 is unkeyed/rate-limited, so the search chain skips it."""
    assert "semantic_scholar" not in [s.name for s in search_sources(_settings())]


# ---------------------------------------------------------------------------
# Reference libraries
# ---------------------------------------------------------------------------


def test_no_libraries_when_unconfigured():
    assert reference_libraries(_settings()) == []


def test_library_present_when_bibtex_file_set():
    libs = reference_libraries(_settings(literature_bibtex_file="/some/refs.bib"))
    assert [lib.name for lib in libs] == ["local_bibtex"]
    assert all(isinstance(lib, ReferenceLibrary) for lib in libs)


def test_library_present_when_local_data_dir_set():
    libs = reference_libraries(_settings(local_data_dir="/some/corpus"))
    assert [lib.name for lib in libs] == ["local_bibtex"]


# ---------------------------------------------------------------------------
# Adapters delegate to the underlying module functions
# ---------------------------------------------------------------------------


async def test_openalex_adapter_delegates_search():
    sentinel = object()
    with patch("src.modules.literature.openalex.search_papers", new=AsyncMock(return_value=sentinel)) as m:
        result = await OpenAlexSource().search("q", 5)
    assert result is sentinel
    m.assert_awaited_once_with("q", limit=5)


async def test_semantic_scholar_adapter_delegates_fetch():
    sentinel = object()
    with patch("src.modules.literature.semantic_scholar.fetch_by_doi", new=AsyncMock(return_value=sentinel)) as m:
        result = await SemanticScholarSource().fetch("10.1/x")
    assert result is sentinel
    m.assert_awaited_once_with("10.1/x")


async def test_arxiv_fetch_returns_none_no_doi_lookup():
    """arXiv inherits the SearchSource default — it cannot resolve DOIs.
    A None here is a real 'not found', not an unimplemented stub."""
    assert await ArxivSource().fetch("10.1/anything") is None


# ---------------------------------------------------------------------------
# LocalBibLibrary — collect / parse / path-dedup
# ---------------------------------------------------------------------------


def test_local_bib_library_reads_both_sources(tmp_path: Path):
    curated = tmp_path / "curated.bib"
    curated.write_text(_bib("Alpha"))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "zotero.bib").write_text(_bib("Beta"))
    (corpus / "ignore.csv").write_text("a,b\n1,2\n")  # non-.bib ignored

    lib = LocalBibLibrary(str(curated), str(corpus))
    titles = {p.title for p in lib.entries()}
    assert titles == {"Alpha", "Beta"}


def test_local_bib_library_path_dedups_same_file(tmp_path: Path):
    """File named in LITERATURE_BIBTEX_FILE *and* present in LOCAL_DATA_DIR
    is parsed once, not twice. (title,year) dedup is the caller's job;
    this layer only de-dups by resolved path.)"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shared = corpus / "shared.bib"
    shared.write_text(_bib("Alpha") + _bib("Beta"))

    lib = LocalBibLibrary(str(shared), str(corpus))
    entries = lib.entries()
    assert len(entries) == 2, "same file via both knobs must be parsed once"


def test_local_bib_library_never_raises_on_bad_file(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "good.bib").write_text(_bib("Survivor"))
    (corpus / "broken.bib").write_text("this is not bibtex at all")

    titles = {p.title for p in LocalBibLibrary(None, str(corpus)).entries()}
    assert "Survivor" in titles


def test_local_bib_library_empty_when_nothing_configured():
    assert LocalBibLibrary(None, None).entries() == []
