"""Lightweight PDF metadata extraction for BYOD literature discovery.

``pypdf`` only — the heavy extractors (marker/docling) are unavailable here, so
we read embedded DocInfo/XMP, scan the first page for a title/DOI, and fall back
to filename heuristics. Never raises: a garbage PDF yields a filename-derived
title so the row is never dropped. Enrichment (CrossRef/OpenAlex) happens later.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .models import PaperMetadata

logger = get_logger(__name__)

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _title_from_filename(path: Path) -> str:
    """Humanize a filename stem into a title-ish string.

    ``smith_2024_concentrated_liquidity.pdf`` → ``Smith 2024 Concentrated Liquidity``.
    """
    stem = path.stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.title() if stem else path.name


def _year_from_text(*texts: str) -> int | None:
    for t in texts:
        m = _YEAR_RE.search(t or "")
        if m:
            y = int(m.group(0))
            if 1900 <= y <= 2100:
                return y
    return None


def extract_pdf_metadata(path: Path) -> PaperMetadata:
    """Best-effort metadata for a single PDF. Never raises."""
    path = Path(path)
    title = ""
    authors: list[str] = []
    doi = ""
    first_page = ""

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        info: Any = reader.metadata or {}
        title = (getattr(info, "title", None) or info.get("/Title") or "") if info else ""
        author_raw = (getattr(info, "author", None) or info.get("/Author") or "") if info else ""
        if author_raw:
            authors = [a.strip() for a in re.split(r"[;,]| and ", str(author_raw)) if a.strip()]
        if reader.pages:
            try:
                first_page = reader.pages[0].extract_text() or ""
            except Exception:  # noqa: BLE001
                first_page = ""
    except Exception as e:  # noqa: BLE001 — never raise on a bad/encrypted PDF
        logger.debug("pypdf metadata read failed for %s: %s", path.name, e)

    title = (str(title) or "").strip()
    # A DocInfo title is often junk ("Microsoft Word - …") — prefer the first
    # substantial line of page 1 when DocInfo is empty or obviously a filename.
    if not title or title.lower().endswith((".pdf", ".docx", ".doc")) or title.lower().startswith("microsoft word"):
        for line in (first_page or "").splitlines():
            cand = line.strip()
            if len(cand) >= 12 and not cand.lower().startswith(("doi", "http", "www", "abstract")):
                title = cand
                break
    if not title:
        title = _title_from_filename(path)

    m = _DOI_RE.search(first_page)
    if m:
        doi = m.group(0).rstrip(".")

    year = _year_from_text(first_page[:2000], path.stem)

    return PaperMetadata(
        title=title[:500],
        authors=authors[:20],
        year=year,
        doi=doi,
        source="byod_pdf",
        pdf_path="",  # set when staged into the workspace
        raw={"filename": path.name},
    )
