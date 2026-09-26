"""Literature module — PDF text extraction (M2.5).

Backs the ``read_reference`` tool so specialists can pull the full text of a
reference into the lit review. pypdf is deliberately chosen for a tiny,
permissively-licensed dependency; extraction is adequate for prose and
weaker on tables/complex layout (revisit pymupdf4llm if users need that —
see docs/MODULARIZATION_PLAN.md).
"""

from __future__ import annotations

import io
import re

from ...logging_config import get_logger

logger = get_logger(__name__)


#: A line that is nothing but a page number, in arabic or roman.
_PAGE_NUMBER = re.compile(r"^[\s.\-–—]*[0-9ivxlcdmIVXLCDM]{1,6}[\s.\-–—]*$")

#: Leading/trailing page numbers on a running head, so "4 Chapter 1" and
#: "17 Chapter 1" collapse to the same thing and can be counted together.
#:
#: The \b matters: without it the roman-numeral characters match ordinary
#: letters, so "Chapter 1. Introduction 3" lost its leading "c" and no longer
#: matched "4 Chapter 1. Introduction" — the two forms of the same running head
#: counted separately and neither reached the threshold.
_EDGE_NUMBER = re.compile(
    r"^(?:\d+|[ivxlcdm]+)\b[\s.\-–—]*|[\s.\-–—]*\b(?:\d+|[ivxlcdm]+)$",
    re.IGNORECASE,
)

#: Only the first and last non-empty line of a page are eligible. A wider
#: window covers every line of a short page, so nothing on it is protected and
#: mid-page content starts disappearing — which is what the tests caught.
_EDGE_LINES = 1


def _furniture_key(line: str) -> str:
    return _EDGE_NUMBER.sub("", line.strip().lower()).strip()


#: A running head is short. Anything longer is a sentence, and removing
#: sentences is how this would start deleting evidence.
_MAX_FURNITURE_CHARS = 90


def strip_page_furniture(pages: list[str], *, min_pages: int = 3, min_repeats: int = 3) -> list[str]:
    """Remove running heads, footers and page numbers from extracted pages.

    A sentence that spans a page break comes out of pypdf with the page's
    furniture sitting in the middle of it:

        "...preliminary because of difficulties 4 chapter 1. introduction
         with the solution concept..."

    A verbatim quote of that sentence then cannot be found, and the claim is
    rejected as fabricated. Measured on a 50-paper sample, this was the single
    largest cause of false rejection left after ligatures and hyphenation were
    handled — fourteen of twenty-five rejections were quotes that are in fact in
    the paper.

    Fixing the text rather than loosening the matcher is deliberate. The
    artefact is in the extraction, and a checker that tolerates insertions would
    also tolerate a quote assembled from scattered fragments, which is the thing
    verification exists to catch.

    Conservative by construction: only the first and last few lines of a page
    are eligible, only lines that repeat across at least `min_pages` pages and
    `share` of them are removed, and a document too short to establish a pattern
    is left alone.
    """
    if len(pages) < min_pages:
        return pages

    counts: dict[str, int] = {}
    for page in pages:
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        for line in lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]:
            key = _furniture_key(line)
            if key and len(line) <= _MAX_FURNITURE_CHARS:
                counts[key] = counts.get(key, 0) + 1

    # An absolute repeat count, not a share of the document. A book changes its
    # running head every chapter, so "Chapter 1. Introduction" appears on a
    # dozen pages of two hundred and a share-based threshold never fires — which
    # is exactly the case that sent this looking in the first place.
    furniture = {k for k, n in counts.items() if n >= min_repeats}

    cleaned: list[str] = []
    for page in pages:
        lines = page.splitlines()
        keep: list[str] = []
        # Index the edges so only those positions are eligible for removal.
        non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
        edges = set(non_empty[:_EDGE_LINES] + non_empty[-_EDGE_LINES:])
        for i, line in enumerate(lines):
            if i in edges:
                stripped = line.strip()
                if _PAGE_NUMBER.match(stripped):
                    continue
                if len(stripped) <= _MAX_FURNITURE_CHARS and _furniture_key(stripped) in furniture:
                    continue
            keep.append(line)
        cleaned.append("\n".join(keep))
    return cleaned


def extract_pdf_text(data: bytes, max_chars: int = 20_000) -> str:
    """Extract text from PDF bytes, truncated to ``max_chars``.

    Never raises — returns ``""`` on missing dependency, encrypted/corrupt
    input, or a scanned PDF with no text layer. Stops reading pages once the
    budget is reached so a 400-page book doesn't blow the token budget.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed — cannot extract PDF text")
        return ""

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        logger.warning("PDF parse failed: %s", e)
        return ""

    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            continue
        parts.append(page_text)
        total += len(page_text)
        if total >= max_chars:
            break

    text = "\n\n".join(strip_page_furniture(parts)).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[... truncated]"
    return text
