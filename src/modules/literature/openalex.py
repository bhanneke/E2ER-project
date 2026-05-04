"""Literature module — OpenAlex search provider (open access, no key required)."""
from __future__ import annotations

import urllib.parse

from ...logging_config import get_logger
from ..fetch.http import fetch_text
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)

_BASE = "https://api.openalex.org"
_EMAIL = "research@e2er.app"  # polite pool


async def search_papers(query: str, limit: int = 20) -> SearchResult:
    """Search OpenAlex for papers matching the query."""
    params = urllib.parse.urlencode({
        "search": query,
        "per-page": min(limit, 50),
        "mailto": _EMAIL,
    })
    url = f"{_BASE}/works?{params}"
    try:
        import json
        text = await fetch_text(url)
        data = json.loads(text)
        papers = [_parse(w) for w in data.get("results", [])]
        return SearchResult(
            papers=papers,
            source="openalex",
            query=query,
            total_found=data.get("meta", {}).get("count", len(papers)),
        )
    except Exception as e:
        logger.warning("OpenAlex search failed: %s", e)
        return SearchResult(papers=[], source="openalex", query=query)


async def fetch_by_doi(doi: str) -> PaperMetadata | None:
    """Fetch paper metadata by DOI from OpenAlex."""
    encoded = urllib.parse.quote(doi, safe="")
    url = f"{_BASE}/works/https://doi.org/{encoded}?mailto={_EMAIL}"
    try:
        import json
        text = await fetch_text(url)
        data = json.loads(text)
        return _parse(data)
    except Exception as e:
        logger.warning("OpenAlex DOI fetch failed for %s: %s", doi, e)
        return None


def _parse(work: dict) -> PaperMetadata:
    authors = []
    for a in work.get("authorships", []):
        display = a.get("author", {}).get("display_name", "")
        if display:
            authors.append(display)

    doi = work.get("doi", "") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    pdf_url = ""
    oa = work.get("open_access", {})
    if oa.get("oa_url"):
        pdf_url = oa["oa_url"]

    return PaperMetadata(
        title=work.get("title", "") or "",
        authors=authors,
        year=work.get("publication_year"),
        doi=doi,
        abstract=_clean_abstract(work.get("abstract_inverted_index")),
        journal=(work.get("primary_location") or {}).get("source", {}).get("display_name", ""),
        url=work.get("id", ""),
        pdf_url=pdf_url,
        source="openalex",
        citations=work.get("cited_by_count", 0),
        raw=work,
    )


def _clean_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, pos_list in inverted.items():
        for pos in pos_list:
            positions.append((pos, word))
    positions.sort()
    return " ".join(w for _, w in positions)
