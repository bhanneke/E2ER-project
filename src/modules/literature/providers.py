"""Literature module — provider interfaces and concrete adapters.

M1 of `docs/MODULARIZATION_PLAN.md`: formalize the de-facto interface the
source modules already share so the tool handler and the reference-summary
builder iterate a registry instead of hardcoding provider names. Pure
refactor — the adapters delegate to the existing module functions; no
behaviour change.

Two capability sub-types (per the plan's locked decision — capability
sub-types, not one fat interface):

- ``SearchSource`` — web discovery: ``search`` plus an optional by-DOI
  ``fetch``. arXiv has no DOI lookup, so it simply doesn't override
  ``fetch`` (the base returns ``None`` — a real "not found here" result,
  not an unimplemented stub; the registry never routes a fetch to it).
- ``ReferenceLibrary`` — the researcher's own corpus: ``entries``. Today
  only local ``.bib`` (``LITERATURE_BIBTEX_FILE`` + ``LOCAL_DATA_DIR``);
  Zotero (M2) and Citavi (M4) plug in here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ...logging_config import get_logger
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)


# ── Capability interfaces ─────────────────────────────────────────────────


class SearchSource(ABC):
    """A web literature source: free-text search, optional DOI resolution."""

    name: str

    @abstractmethod
    async def search(self, query: str, limit: int) -> SearchResult:
        """Free-text search. Must not raise — degrade to an empty result."""
        ...

    async def fetch(self, doi: str) -> PaperMetadata | None:
        """Resolve a single paper by DOI.

        Default: this source does not resolve DOIs (e.g. arXiv). Sources
        that can — OpenAlex, Semantic Scholar — override it. Returning
        ``None`` means "not found here", and the registry only lists
        DOI-capable sources in its fetch chain, so the default is never
        actually invoked in the fetch path.
        """
        return None


class ReferenceLibrary(ABC):
    """The researcher's own reference corpus (their library, not the web)."""

    name: str

    @abstractmethod
    def entries(self) -> list[PaperMetadata]:
        """Every reference in the library.

        Sync, because it's consumed by the (sync) specialist prompt
        builder. Must not raise — degrade to ``[]``.
        """
        ...


# ── Search sources (adapters over the existing module functions) ──────────


class OpenAlexSource(SearchSource):
    name = "openalex"

    async def search(self, query: str, limit: int) -> SearchResult:
        from . import openalex

        return await openalex.search_papers(query, limit=limit)

    async def fetch(self, doi: str) -> PaperMetadata | None:
        from . import openalex

        return await openalex.fetch_by_doi(doi)


class ArxivSource(SearchSource):
    name = "arxiv"

    async def search(self, query: str, limit: int) -> SearchResult:
        from . import arxiv

        return await arxiv.search_papers(query, limit=limit)

    # No ``fetch`` override — arXiv has no DOI lookup; inherits the
    # ``None`` default and is kept out of the registry's fetch chain.


class SemanticScholarSource(SearchSource):
    name = "semantic_scholar"

    async def search(self, query: str, limit: int) -> SearchResult:
        from . import semantic_scholar

        return await semantic_scholar.search_papers(query, limit=limit)

    async def fetch(self, doi: str) -> PaperMetadata | None:
        from . import semantic_scholar

        return await semantic_scholar.fetch_by_doi(doi)


# ── Reference libraries ───────────────────────────────────────────────────


class LocalBibLibrary(ReferenceLibrary):
    """Local ``.bib`` files: ``LITERATURE_BIBTEX_FILE`` plus any ``*.bib``
    inside ``LOCAL_DATA_DIR``.

    Holds the collect-and-parse logic that used to live inline in
    ``_load_reference_summary``. Files named in both config knobs are
    de-duplicated by resolved path so the same file isn't parsed twice.
    Cross-library ``(title, year)`` de-duplication stays in the caller,
    which merges across all libraries.
    """

    name = "local_bibtex"

    def __init__(self, bibtex_file: str | None, local_data_dir: str | None, recursive: bool = False) -> None:
        self._bibtex_file = bibtex_file
        self._local_data_dir = local_data_dir
        self._recursive = recursive

    def _bib_paths(self) -> list[Path]:
        from ..local_corpus import BIB_EXTENSIONS, iter_corpus_files, parse_corpus_roots

        paths: list[Path] = []
        if self._bibtex_file:
            primary = Path(self._bibtex_file).expanduser()
            if primary.is_file():
                paths.append(primary)
        seen = {p.resolve() for p in paths}
        for _root, candidate in iter_corpus_files(
            parse_corpus_roots(self._local_data_dir), BIB_EXTENSIONS, self._recursive
        ):
            resolved = candidate.resolve()
            if resolved in seen:
                continue  # same file named in LITERATURE_BIBTEX_FILE
            paths.append(candidate)
            seen.add(resolved)
        return paths

    def entries(self) -> list[PaperMetadata]:
        from .bibtex import parse_bibtex_file

        papers: list[PaperMetadata] = []
        for bib_path in self._bib_paths():
            try:
                papers.extend(parse_bibtex_file(bib_path))
            except Exception as e:
                logger.warning("LocalBibLibrary: failed to parse %s: %s", bib_path, e)
        return papers


class LocalZoteroLibrary(ReferenceLibrary):
    """The researcher's Zotero library read from a LOCAL folder (``zotero.sqlite``
    + ``storage/`` PDFs) — no Web API key needed. Distinct from ``ZoteroLibrary``
    (Web API). Reads are cheap (one sqlite pass) so this is safe at prompt time.
    Never raises — degrades to ``[]``.
    """

    name = "zotero_local"

    def __init__(self, literature_dir: str | None) -> None:
        self._literature_dir = literature_dir

    def entries(self) -> list[PaperMetadata]:
        from ..local_corpus import parse_corpus_roots
        from .local_zotero import detect_zotero, read_zotero_sqlite

        papers: list[PaperMetadata] = []
        for root in parse_corpus_roots(self._literature_dir):
            if detect_zotero(root) is not None:
                try:
                    papers.extend(read_zotero_sqlite(root))
                except Exception as e:  # noqa: BLE001
                    logger.warning("LocalZoteroLibrary failed for %s: %s", root, e)
        return papers


class ZoteroLibrary(ReferenceLibrary):
    """The researcher's Zotero library, via the Zotero Web API.

    Set the API key plus exactly one of ``user_id`` / ``group_id``. Maps
    items to ``PaperMetadata`` and captures the primary PDF attachment href
    (for the planned on-demand ``read_reference`` tool). Never raises —
    degrades to ``[]`` so a Zotero outage can't break paper creation.
    """

    name = "zotero"

    def __init__(self, api_key: str, user_id: str | None = None, group_id: str | None = None) -> None:
        self._api_key = api_key
        self._user_id = user_id
        self._group_id = group_id

    def entries(self) -> list[PaperMetadata]:
        from .zotero import fetch_library

        try:
            return fetch_library(self._api_key, user_id=self._user_id, group_id=self._group_id)
        except Exception as e:
            logger.warning("ZoteroLibrary.entries failed: %s", e)
            return []
