"""Literature module — arXiv search provider."""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET

from ...logging_config import get_logger
from ..fetch.http import fetch_text
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)

_BASE = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


async def search_papers(query: str, limit: int = 20) -> SearchResult:
    """Search arXiv using the Atom feed API."""
    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(limit, 50),
            "sortBy": "relevance",
        }
    )
    url = f"{_BASE}?{params}"
    try:
        xml_text = await fetch_text(url)
        root = ET.fromstring(xml_text)
        papers = [_parse(entry) for entry in root.findall("atom:entry", _NS)]
        return SearchResult(papers=papers, source="arxiv", query=query, total_found=len(papers))
    except Exception as e:
        logger.warning("arXiv search failed: %s", e)
        return SearchResult(papers=[], source="arxiv", query=query)


def _parse(entry: ET.Element) -> PaperMetadata:
    def text(tag: str) -> str:
        el = entry.find(tag, _NS)
        return (el.text or "").strip() if el is not None else ""

    authors = [
        (a.find("atom:name", _NS).text or "").strip()
        for a in entry.findall("atom:author", _NS)
        if a.find("atom:name", _NS) is not None
    ]

    arxiv_id = text("atom:id").split("/abs/")[-1]
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    published = text("atom:published")
    year = int(published[:4]) if published and len(published) >= 4 else None

    doi = ""
    doi_el = entry.find("arxiv:doi", _NS)
    if doi_el is not None and doi_el.text:
        doi = doi_el.text.strip()

    return PaperMetadata(
        title=text("atom:title").replace("\n", " "),
        authors=authors,
        year=year,
        doi=doi,
        abstract=text("atom:summary").replace("\n", " "),
        journal="arXiv",
        url=text("atom:id"),
        pdf_url=pdf_url,
        source="arxiv",
        raw={"arxiv_id": arxiv_id},
    )
