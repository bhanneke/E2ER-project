"""Literature module — OpenAlex search provider (open access, no key required)."""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime

from ...logging_config import get_logger
from ..fetch.http import fetch_text
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)

_BASE = "https://api.openalex.org"
_EMAIL = "research@e2er.app"  # polite pool

# OpenAlex 400s on these two in ``search``; every other punctuation mark a
# research question or title carries — quotes, parens, ampersands, colons,
# commas, hyphens, slashes — is accepted (probed against the live API
# 2026-09-07). Stripping matters because the caller searches with the paper's
# own research question, which normally ends in '?': the whole provider then
# fails and acquisition silently falls through to the next source.
_REJECTED_CHARS = str.maketrans({"?": " ", "*": " "})


#: What a run says when OpenAlex refuses for its daily budget (2026-10-13: the weather-words demo got
#: 429 "Insufficient budget" and its literature search silently found nothing).
BUDGET_SPENT = "OpenAlex's free daily budget for this network is used up"
#: The UTC day on which OpenAlex refused for its budget: later searches that day do not ask again.
_budget_spent_on: str | None = None


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def budget_spent_today() -> bool:
    return _budget_spent_on == _today()


def is_budget_refusal(status: int, body: str) -> bool:
    """OpenAlex's answer when the keyless daily budget is spent: 429 with "Insufficient budget".

    A burst limit is a 429 too, but says nothing of the budget (and its retryAfter is seconds).
    """
    low = (body or "").lower()
    return status == 429 and ("insufficient budget" in low or "dailyremainingusd" in low)


def _headers() -> dict[str, str]:
    try:
        from ...config import get_settings

        key = get_settings().openalex_api_key
    except Exception:  # noqa: BLE001 — no settings: keyless
        key = None
    return {"Authorization": f"Bearer {key}"} if key else {}


def _sanitize(query: str) -> str:
    return " ".join(query.translate(_REJECTED_CHARS).split())


async def search_papers(query: str, limit: int = 20) -> SearchResult:
    """Search OpenAlex for papers matching the query."""
    params = urllib.parse.urlencode(
        {
            "search": _sanitize(query),
            "per-page": min(limit, 50),
            "mailto": _EMAIL,
        }
    )
    url = f"{_BASE}/works?{params}"
    global _budget_spent_on
    if budget_spent_today():
        return SearchResult(papers=[], source="openalex", query=query, notice=BUDGET_SPENT)
    try:
        import json

        import httpx

        try:
            text = await fetch_text(url, headers=_headers())
        except httpx.HTTPStatusError as e:
            if is_budget_refusal(e.response.status_code, e.response.text):
                _budget_spent_on = _today()
                logger.warning("%s (429 Insufficient budget; it resets at midnight UTC)", BUDGET_SPENT)
                return SearchResult(papers=[], source="openalex", query=query, notice=BUDGET_SPENT)
            raise
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
    if budget_spent_today():
        return None
    try:
        import json

        text = await fetch_text(url, headers=_headers())
        data = json.loads(text)
        return _parse(data)
    except Exception as e:
        logger.warning("OpenAlex DOI fetch failed for %s: %s", doi, e)
        return None


def _parse(work: dict) -> PaperMetadata:
    # OpenAlex returns explicit nulls (not just absent keys) for optional
    # fields like `source`, `open_access`, `authorships`. `.get(k, default)`
    # only applies the default when k is ABSENT, so every nested access must
    # guard with `or {}` / `or []` against a present-but-null value.
    authors = []
    for a in work.get("authorships") or []:
        display = (a.get("author") or {}).get("display_name", "")
        if display:
            authors.append(display)

    doi = work.get("doi", "") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]

    oa = work.get("open_access") or {}
    pdf_url = oa.get("oa_url") or ""

    source = (work.get("primary_location") or {}).get("source") or {}

    return PaperMetadata(
        title=work.get("title", "") or "",
        authors=authors,
        year=work.get("publication_year"),
        doi=doi,
        abstract=_clean_abstract(work.get("abstract_inverted_index")),
        journal=source.get("display_name", ""),
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
