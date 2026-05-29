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
from .providers import (
    ArxivSource,
    LocalBibLibrary,
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
    # Narrow zotero_api_key to str for the type checker (the zotero_enabled
    # property already implies this, but mypy can't see through a property).
    zotero_key = settings.zotero_api_key
    if zotero_key and (settings.zotero_user_id or settings.zotero_group_id):
        libraries.append(ZoteroLibrary(zotero_key, settings.zotero_user_id, settings.zotero_group_id))
    return libraries
