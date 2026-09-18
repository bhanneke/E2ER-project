"""Literature module — provider registry.

Returns the ordered, available providers for each capability. Mirrors
``src/modules/llm/registry.py``. The orderings reproduce the pre-M1
``LiteratureToolHandler`` fallback chains *exactly*:

- search:    OpenAlex → arXiv
- DOI fetch:  OpenAlex → Semantic Scholar

Semantic Scholar is intentionally absent from the search chain — it's
unkeyed and rate-limited, and the pre-M1 handler used it only as the
by-DOI fetch fallback. arXiv has no DOI lookup, so it's absent from the
fetch chain.

``settings`` is accepted (and currently unused for search/fetch) so
keyed/credentialed providers — Zotero (M2), Citavi (M4) — can gate their
own availability here without changing call sites.
"""

from __future__ import annotations

from ...config import Settings
from .oa_resolvers import OAResolver
from .oa_resolvers import oa_pdf_resolvers as _oa_pdf_resolvers
from .providers import (
    ArxivSource,
    LocalBibLibrary,
    LocalZoteroLibrary,
    OpenAlexSource,
    ReferenceLibrary,
    SearchSource,
    SemanticScholarSource,
    ZoteroLibrary,
)


def search_sources(settings: Settings) -> list[SearchSource]:
    """Ordered free-text search fallback chain."""
    return [OpenAlexSource(), ArxivSource()]


def doi_fetch_sources(settings: Settings) -> list[SearchSource]:
    """Ordered by-DOI resolution fallback chain (DOI-capable sources only)."""
    return [OpenAlexSource(), SemanticScholarSource()]


def oa_pdf_resolvers(settings: Settings) -> list[OAResolver]:
    """Ordered OA-PDF resolver chain (v0.9 M3).

    Re-exported from :mod:`oa_resolvers` so all chain builders live
    in one module. See :func:`oa_resolvers.oa_pdf_resolvers` for the
    rationale on default ordering (Unpaywall → OpenAlex → Crossref →
    Semantic Scholar).
    """
    return _oa_pdf_resolvers(settings)


def reference_libraries(settings: Settings) -> list[ReferenceLibrary]:
    """The researcher's own reference corpora, in merge order.

    Local ``.bib`` first, then Zotero. Cross-library ``(title, year)``
    de-duplication is the caller's job (``_load_reference_summary``).
    """
    libraries: list[ReferenceLibrary] = []
    if settings.literature_bibtex_file or settings.local_data_dir:
        libraries.append(
            LocalBibLibrary(
                settings.literature_bibtex_file,
                settings.local_data_dir,
                recursive=settings.local_data_dir_recursive,
            )
        )
    # Local Zotero folder (zotero.sqlite) — cheap sqlite read, safe at prompt
    # time. Only added when a literature dir actually contains a zotero.sqlite;
    # plain PDF folders are NOT parsed here (per-call PDF parsing is too
    # expensive) — they're served via the discovery→SQLite persistence path and
    # the search_papers local routing + staged-PDF listing instead.
    lit_dirs = getattr(settings, "literature_dir", None) or settings.local_data_dir
    if lit_dirs:
        from ..local_corpus import parse_corpus_roots
        from .local_zotero import detect_zotero

        if any(detect_zotero(root) is not None for root in parse_corpus_roots(lit_dirs)):
            libraries.append(LocalZoteroLibrary(lit_dirs))
    # Narrow zotero_api_key to str for the type checker (the zotero_enabled
    # property already implies this, but mypy can't see through a property).
    zotero_key = settings.zotero_api_key
    if zotero_key and (settings.zotero_user_id or settings.zotero_group_id):
        libraries.append(ZoteroLibrary(zotero_key, settings.zotero_user_id, settings.zotero_group_id))
    return libraries
