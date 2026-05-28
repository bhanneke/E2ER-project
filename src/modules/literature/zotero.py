"""Literature module — Zotero Web API reference-library provider (M2).

Reads the researcher's own Zotero library via the Web API's native JSON
(``docs.MODULARIZATION_PLAN.md`` locked decision #1: Web API, JSON-direct).
Maps each top-level bibliographic item to ``PaperMetadata`` and captures the
primary PDF attachment href from ``links.attachment`` — that href is what
the planned on-demand ``read_reference`` tool (M2.5) will download.

Synchronous on purpose: ``ReferenceLibrary.entries`` is consumed by the
sync specialist prompt builder, so this uses ``fetch_text_sync``.
"""

from __future__ import annotations

import json

from ...logging_config import get_logger
from ..fetch.http import fetch_text_sync
from .models import PaperMetadata

logger = get_logger(__name__)

_BASE = "https://api.zotero.org"
_PAGE = 100  # Zotero's max page size
_MAX_ITEMS = 2000  # safety cap on total items pulled into a prompt

# Item types that are never standalone references in a bibliography.
_SKIP_TYPES = frozenset({"attachment", "note", "annotation"})
# Creator roles that count as "authors" for display.
_AUTHOR_ROLES = frozenset({"author", "editor"})


def fetch_library(
    api_key: str,
    *,
    user_id: str | None = None,
    group_id: str | None = None,
) -> list[PaperMetadata]:
    """Fetch all top-level bibliographic items from a Zotero library.

    Uses the ``/items/top`` endpoint so child attachments/notes aren't
    returned as separate entries. Pages until a short page is seen or the
    safety cap is hit. Never raises — degrades to whatever was collected
    before an error (``[]`` if the first page failed).
    """
    if user_id:
        base = f"{_BASE}/users/{user_id}/items/top"
    elif group_id:
        base = f"{_BASE}/groups/{group_id}/items/top"
    else:
        return []

    headers = {"Zotero-API-Key": api_key, "Zotero-API-Version": "3"}
    papers: list[PaperMetadata] = []
    start = 0
    while start < _MAX_ITEMS:
        url = f"{base}?format=json&limit={_PAGE}&start={start}"
        try:
            text = fetch_text_sync(url, headers=headers)
            items = json.loads(text)
        except Exception as e:
            logger.warning("Zotero fetch/parse failed at start=%d: %s", start, e)
            break
        if not items:
            break
        for item in items:
            paper = _to_metadata(item)
            if paper is not None:
                papers.append(paper)
        if len(items) < _PAGE:
            break
        start += _PAGE
    return papers


def _to_metadata(item: dict) -> PaperMetadata | None:
    data = item.get("data", {}) or {}
    if data.get("itemType", "") in _SKIP_TYPES:
        return None
    title = (data.get("title") or "").strip()
    if not title:
        return None

    journal = data.get("publicationTitle") or data.get("bookTitle") or data.get("proceedingsTitle") or ""
    links = item.get("links") or {}
    attachment = links.get("attachment") or {}
    pdf_url = attachment.get("href", "") if attachment.get("attachmentType") == "application/pdf" else ""
    url = data.get("url") or (links.get("alternate") or {}).get("href", "") or ""

    return PaperMetadata(
        title=title,
        authors=_authors(data.get("creators", [])),
        year=_year(data.get("date", "")),
        doi=data.get("DOI", "") or "",
        abstract=data.get("abstractNote", "") or "",
        journal=journal,
        url=url,
        pdf_url=pdf_url,
        source="zotero",
        raw=item,
    )


def _authors(creators: list[dict]) -> list[str]:
    """Extract author/editor display names from Zotero creators.

    Zotero creators are either two-field (``firstName``/``lastName``) or
    single-field (``name``, e.g. institutional authors). Falls back to all
    creators if none carry an author/editor role.
    """
    primary = [c for c in creators if c.get("creatorType") in _AUTHOR_ROLES]
    chosen = primary or creators
    names: list[str] = []
    for c in chosen:
        if c.get("name"):
            names.append(c["name"].strip())
            continue
        full = f"{(c.get('firstName') or '').strip()} {(c.get('lastName') or '').strip()}".strip()
        if full:
            names.append(full)
    return names


def _year(date: str) -> int | None:
    """Pull a 4-digit year out of a free-form Zotero date string."""
    import re

    m = re.search(r"\b(\d{4})\b", date or "")
    return int(m.group(1)) if m else None
