"""Literature module — Crossref metadata provider (keyless, polite pool).

Crossref is the DOI registrar of record; OpenAlex and Semantic Scholar
both *consume* Crossref. We query it directly as a third verifier in
the citation-integrity gate (`src/core/pipeline/verify_citations.py`)
so that DOIs which haven't propagated to OpenAlex/S2 yet — new
preprints, freshly assigned DOIs — still verify.

Endpoints we use:
- ``GET /works/{doi}`` — exact DOI lookup.
- ``GET /works?query.title=...&rows=...`` — title search.

Polite pool: Crossref asks for a `mailto=` (in URL or User-Agent)
so they can throttle politely without 429s. We pass it in the
User-Agent per their docs.
"""

from __future__ import annotations

import json
import urllib.parse

from ...logging_config import get_logger
from ..fetch.http import fetch_text
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)

_BASE = "https://api.crossref.org"
_EMAIL = "research@e2er.app"  # polite pool — same value the OpenAlex provider uses
_HEADERS = {"User-Agent": f"E2ER/0.9 (mailto:{_EMAIL})"}


async def search_papers(query: str, limit: int = 20) -> SearchResult:
    """Search Crossref for papers matching the (title) query."""
    params = urllib.parse.urlencode({"query.title": query, "rows": min(limit, 50)})
    url = f"{_BASE}/works?{params}"
    try:
        text = await fetch_text(url, headers=_HEADERS)
        data = json.loads(text)
        items = (data.get("message") or {}).get("items", [])
        papers = [_parse(it) for it in items]
        return SearchResult(
            papers=papers,
            source="crossref",
            query=query,
            total_found=(data.get("message") or {}).get("total-results", len(papers)),
        )
    except Exception as e:
        logger.warning("Crossref search failed: %s", e)
        return SearchResult(papers=[], source="crossref", query=query)


async def fetch_by_doi(doi: str) -> PaperMetadata | None:
    """Fetch paper metadata by DOI from Crossref."""
    url = f"{_BASE}/works/{urllib.parse.quote(doi, safe='/')}"
    try:
        text = await fetch_text(url, headers=_HEADERS)
        data = json.loads(text)
        msg = data.get("message")
        if not msg:
            return None
        return _parse(msg)
    except Exception as e:
        logger.warning("Crossref DOI fetch failed for %s: %s", doi, e)
        return None


def _pick_pdf_link(message: dict) -> str:
    """Return the best PDF URL from a Crossref work's ``link`` array.

    Crossref records carry publisher-deposited full-text links in
    ``link[]``. Each entry has ``URL``, ``content-type``, and
    ``intended-application`` (``text-mining`` / ``similarity-checking``
    / ``unspecified``). We want PDFs intended for human readers, but
    publishers are inconsistent about ``intended-application``, so the
    practical filter is ``content-type == 'application/pdf'``.
    """
    for entry in message.get("link") or []:
        if (entry.get("content-type") or "").lower() == "application/pdf":
            url = entry.get("URL", "")
            if url:
                return url
    return ""


async def find_oa_pdf(doi: str) -> str | None:
    """Lookup an OA PDF URL by DOI via the Crossref ``link`` array.

    Used by the OA-PDF resolver chain (``oa_pdf_resolvers`` in the
    registry) as a fallback when Unpaywall and OpenAlex have no copy.
    Crossref's coverage is publisher-deposited links — narrower than
    Unpaywall, but it catches cases where the publisher's own DOI
    record points at a PDF that Unpaywall hasn't indexed.
    """
    url = f"{_BASE}/works/{urllib.parse.quote(doi, safe='/')}"
    try:
        text = await fetch_text(url, headers=_HEADERS)
        data = json.loads(text)
    except Exception as e:
        logger.warning("Crossref OA-PDF fetch failed for %s: %s", doi, e)
        return None
    msg = data.get("message") or {}
    pdf = _pick_pdf_link(msg)
    return pdf or None


def _parse(item: dict) -> PaperMetadata:
    # Crossref returns title and container-title as arrays of strings.
    title_arr = item.get("title") or []
    title = title_arr[0] if title_arr else ""
    container_arr = item.get("container-title") or []
    journal = container_arr[0] if container_arr else ""

    authors: list[str] = []
    for a in item.get("author") or []:
        given = a.get("given", "")
        family = a.get("family", "")
        if family:
            authors.append(f"{given} {family}".strip())
        elif a.get("name"):
            authors.append(a["name"])

    # Year lives in one of issued / published-print / published-online /
    # created, as a `date-parts: [[YYYY, MM, DD]]` triple. Fall through.
    year: int | None = None
    for date_key in ("issued", "published-print", "published-online", "created"):
        parts = (item.get(date_key) or {}).get("date-parts") or []
        if parts and parts[0]:
            try:
                year = int(parts[0][0])
                break
            except (TypeError, ValueError):
                continue

    return PaperMetadata(
        title=title,
        authors=authors,
        year=year,
        doi=item.get("DOI", "") or "",
        abstract=item.get("abstract", "") or "",
        journal=journal,
        url=item.get("URL", "") or "",
        source="crossref",
        citations=item.get("is-referenced-by-count", 0),
        raw=item,
    )
