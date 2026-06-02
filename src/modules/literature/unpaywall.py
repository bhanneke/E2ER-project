"""Literature module — Unpaywall open-access PDF resolver (keyless,
email-required polite pool).

Unpaywall has the best OA-PDF coverage of any free service — it
aggregates Crossref, repositories (arXiv, RePEc, SSRN), publisher
landing pages, and crawls. The live-test on M1 showed Zotero often
holds metadata-only entries (PDF not uploaded to Zotero cloud), so
``read_reference`` has to fall through to OA-by-DOI. The bigger that
OA reach, the more papers a real run can read.

API: ``GET https://api.unpaywall.org/v2/{doi}?email={email}`` — no
key, but Unpaywall requires the email in every call so they can
throttle politely and contact you about misuse.

Response shape we care about:
- ``best_oa_location.url_for_pdf`` (preferred) — direct PDF URL.
- ``best_oa_location.url`` — landing page or PDF; sometimes the only
  available URL.
- ``oa_locations[]`` — full list; we fall through them when
  ``best_oa_location`` is null but other locations exist.
- ``title`` / ``year`` / ``z_authors`` — enough to populate
  ``PaperMetadata`` so the rest of the pipeline doesn't refetch.
"""

from __future__ import annotations

import json
import urllib.parse

from ...logging_config import get_logger
from ..fetch.http import fetch_text
from .models import PaperMetadata

logger = get_logger(__name__)

_BASE = "https://api.unpaywall.org/v2"


def _best_pdf_url(data: dict) -> str:
    """Pick the best OA PDF URL from an Unpaywall response.

    Preference: ``best_oa_location.url_for_pdf`` > ``best_oa_location.url`` >
    first ``oa_locations[].url_for_pdf`` > first ``oa_locations[].url``.
    Returns ``""`` if no OA URL is available (typical for paywalled
    work without a green-OA copy anywhere).
    """
    best = data.get("best_oa_location") or {}
    url = best.get("url_for_pdf") or best.get("url")
    if url:
        return url
    for loc in data.get("oa_locations") or []:
        url = loc.get("url_for_pdf") or loc.get("url")
        if url:
            return url
    return ""


async def find_oa(doi: str, email: str) -> PaperMetadata | None:
    """Look up an OA copy by DOI. Returns a ``PaperMetadata`` with
    ``pdf_url`` set on success, ``None`` if Unpaywall has no record
    for the DOI or no OA URL is available.
    """
    if not doi or not email:
        return None
    url = f"{_BASE}/{urllib.parse.quote(doi, safe='/')}?email={urllib.parse.quote(email)}"
    try:
        text = await fetch_text(url)
        data = json.loads(text)
    except Exception as e:
        logger.warning("Unpaywall fetch failed for %s: %s", doi, e)
        return None

    pdf_url = _best_pdf_url(data)
    if not pdf_url:
        # Unpaywall responded but no OA location — this is a real
        # "no OA copy exists" signal, distinct from a fetch error.
        logger.debug("Unpaywall: no OA URL for %s", doi)
        return None

    authors: list[str] = []
    for a in data.get("z_authors") or []:
        given = a.get("given", "")
        family = a.get("family", "")
        if family:
            authors.append(f"{given} {family}".strip())
        elif a.get("name"):
            authors.append(a["name"])

    return PaperMetadata(
        title=data.get("title", "") or "",
        authors=authors,
        year=data.get("year"),
        doi=data.get("doi", "") or doi,
        journal=data.get("journal_name", "") or "",
        url=data.get("doi_url", "") or "",
        pdf_url=pdf_url,
        source="unpaywall",
        raw=data,
    )


async def find_oa_pdf(doi: str, email: str) -> str | None:
    """Lightweight OA-URL-only entry point used by :class:`OAResolver`.
    Returns the best OA PDF URL or ``None``."""
    paper = await find_oa(doi, email)
    return paper.pdf_url if paper else None
