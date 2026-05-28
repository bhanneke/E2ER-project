"""Literature module — PDF text extraction (M2.5).

Backs the ``read_reference`` tool so specialists can pull the full text of a
reference into the lit review. pypdf is deliberately chosen for a tiny,
permissively-licensed dependency; extraction is adequate for prose and
weaker on tables/complex layout (revisit pymupdf4llm if users need that —
see docs/MODULARIZATION_PLAN.md).
"""

from __future__ import annotations

import io

from ...logging_config import get_logger

logger = get_logger(__name__)


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

    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[... truncated]"
    return text
