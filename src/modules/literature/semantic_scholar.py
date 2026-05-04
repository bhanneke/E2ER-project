"""Literature module — Semantic Scholar search provider."""
from __future__ import annotations

import urllib.parse

from ...logging_config import get_logger
from ..fetch.http import fetch_text
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)

_BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "title,authors,year,abstract,externalIds,openAccessPdf,citationCount,venue,url"


async def search_papers(query: str, limit: int = 20) -> SearchResult:
    """Search Semantic Scholar."""
    params = urllib.parse.urlencode({"query": query, "limit": min(limit, 100), "fields": _FIELDS})
    url = f"{_BASE}/paper/search?{params}"
    try:
        import json
        text = await fetch_text(url)
        data = json.loads(text)
        papers = [_parse(p) for p in data.get("data", [])]
        return SearchResult(
            papers=papers,
            source="semantic_scholar",
            query=query,
            total_found=data.get("total", len(papers)),
        )
    except Exception as e:
        logger.warning("Semantic Scholar search failed: %s", e)
        return SearchResult(papers=[], source="semantic_scholar", query=query)


async def fetch_by_doi(doi: str) -> PaperMetadata | None:
    """Fetch paper metadata by DOI from Semantic Scholar."""
    url = f"{_BASE}/paper/DOI:{doi}?fields={_FIELDS}"
    try:
        import json
        text = await fetch_text(url)
        data = json.loads(text)
        return _parse(data)
    except Exception as e:
        logger.warning("S2 DOI fetch failed for %s: %s", doi, e)
        return None


def _parse(paper: dict) -> PaperMetadata:
    authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
    doi = (paper.get("externalIds") or {}).get("DOI", "")
    pdf_url = (paper.get("openAccessPdf") or {}).get("url", "")
    return PaperMetadata(
        title=paper.get("title", "") or "",
        authors=authors,
        year=paper.get("year"),
        doi=doi,
        abstract=paper.get("abstract", "") or "",
        journal=paper.get("venue", "") or "",
        url=paper.get("url", "") or "",
        pdf_url=pdf_url,
        source="semantic_scholar",
        citations=paper.get("citationCount", 0),
        raw=paper,
    )
