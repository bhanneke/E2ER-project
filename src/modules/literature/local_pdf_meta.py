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

#: The stamp arXiv prints down the margin of every preprint it hosts, e.g.
#: "arXiv:2302.04068v2 [q-fin.TR]". The version suffix is dropped: v1 and v2 of
#: a preprint are the same paper.
_ARXIV_RE = re.compile(r"arXiv[:\s]\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
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


#: Lines on page 1 that are never part of a title.
_NOT_TITLE = ("doi", "http", "www", "abstract", "arxiv", "keywords", "jel ", "working paper", "preprint")


def _title_from_first_page(first_page: str) -> str:
    """The title, including the part that wrapped onto the next line.

    Taking only the first substantial line gives "HOW DECENTRALIZED IS THE
    GOVERNANCE OF" and stops there — titles wrap, and a truncated title is worse
    than a missing one: it deduplicates against nothing, so the same paper
    arriving later from the web is stored a second time.

    Continuation lines are joined while they still look like part of a heading:
    no terminal full stop above, no author/affiliation markers, and not yet into
    the abstract.
    """
    lines = [ln.strip() for ln in first_page.splitlines()]
    parts: list[str] = []

    for line in lines:
        low = line.lower()
        if not parts:
            if len(line) >= 12 and not low.startswith(_NOT_TITLE):
                parts.append(line)
            continue

        # Already started. Keep going only while this still reads as a heading.
        if not line:
            break
        if low.startswith(_NOT_TITLE):
            break
        if parts[-1].rstrip().endswith((".", "?", "!")) and not parts[-1].rstrip().endswith(("et al.", "Inc.")):
            break
        if "@" in line or re.search(r"\b(university|department|school|institute)\b", low):
            break
        if len(" ".join(parts)) > 250:
            break
        parts.append(line)

    return " ".join(parts).strip()


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
        title = _title_from_first_page(first_page or "")
    if not title:
        title = _title_from_filename(path)

    m = _DOI_RE.search(first_page)
    if m:
        doi = m.group(0).rstrip(".")

    # An arXiv stamp is a DOI in disguise. arXiv mints 10.48550/arXiv.<id> for
    # every submission, and that is exactly the DOI OpenAlex reports — so
    # reading the stamp off the page turns a preprint with "no DOI" into one
    # that matches its own web record exactly, instead of relying on titles.
    if not doi:
        a = _ARXIV_RE.search(first_page)
        if a:
            doi = f"10.48550/arXiv.{a.group(1)}"

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
