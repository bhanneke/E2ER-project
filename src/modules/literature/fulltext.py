"""Get a paper's full text, from wherever it happens to be.

The ``read_reference`` tool already does this, but it does it inside a tool
handler bound to a paper's workspace and capped at 20k characters — a preview
for a model that wants to check one thing. Extraction needs the whole paper, and
needs it outside any workspace, so the waterfall lives here and the tool keeps
its own cap.

Nothing here raises. Every failure is a ``FullText`` with an ``error`` on it,
because acquiring literature fails constantly and in boring ways — a paywall, a
dead link, a scanned image — and none of those should stop a corpus refresh
partway through a hundred papers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .models import PaperMetadata

logger = get_logger(__name__)

#: Enough for a long empirical paper with appendices. The extractor chunks past
#: its own limit, so this bounds memory and download time rather than quality.
MAX_TEXT_CHARS = 150_000

#: PDFs routinely exceed the HTTP client's 2 MB default.
MAX_PDF_BYTES = 25 * 1024 * 1024


@dataclass
class FullText:
    """Text, where it came from, or why there is none."""

    text: str = ""
    origin: str = ""  # local | pdf_url | oa:<resolver>
    url: str = ""
    path: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text.strip()) and not self.error

    @property
    def chars(self) -> int:
        return len(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "chars": self.chars,
            "origin": self.origin,
            "url": self.url,
            "path": self.path,
            "error": self.error,
        }


def read_pdf_file(path: str | Path, *, max_chars: int = MAX_TEXT_CHARS) -> FullText:
    """Extract text from a PDF already on disk."""
    from .pdf import extract_pdf_text

    p = Path(path).expanduser()
    if not p.is_file():
        return FullText(error=f"no file at {p}", path=str(p))
    try:
        data = p.read_bytes()
    except OSError as e:
        return FullText(error=f"could not read {p.name}: {e}", path=str(p))

    if not looks_like_pdf(data):
        return FullText(error=f"not a PDF ({describe_payload(data)})", path=str(p))

    text = extract_pdf_text(data, max_chars=max_chars)
    if not text.strip():
        return FullText(error="no extractable text (scanned image?)", path=str(p), origin="local")
    return FullText(text=text, origin="local", path=str(p))


async def resolve_oa_pdf(doi: str) -> tuple[str, str] | None:
    """Walk the OA-resolver chain for a DOI. Returns (url, resolver name).

    Resolvers are contractually forbidden from raising, but a chain that dies on
    one misbehaving provider would take the whole refresh with it, so this is
    belt and braces.
    """
    if not doi:
        return None

    from ...config import get_settings
    from .registry import oa_pdf_resolvers

    for resolver in oa_pdf_resolvers(get_settings()):
        try:
            url = await resolver.resolve(doi)
        except Exception as e:  # a provider outage is not a failed extraction
            logger.debug("OA resolver %s failed for %s: %s", resolver.name, doi, e)
            continue
        if url:
            return url, resolver.name
    return None


async def download_pdf_text(pdf_url: str, *, max_chars: int = MAX_TEXT_CHARS) -> FullText:
    """Download a PDF and extract its text."""
    from ...config import get_settings
    from ..fetch.http import fetch_bytes
    from .pdf import extract_pdf_text

    url, headers = _download_target(pdf_url, get_settings())
    try:
        data = await fetch_bytes(url, headers=headers, max_bytes=MAX_PDF_BYTES)
    except Exception as e:
        return FullText(error=f"could not download: {e}", url=pdf_url)

    if not looks_like_pdf(data):
        return FullText(error=f"not a PDF ({describe_payload(data)})", url=pdf_url)

    text = extract_pdf_text(data, max_chars=max_chars)
    if not text.strip():
        return FullText(error="downloaded but no extractable text (likely scanned)", url=pdf_url)
    return FullText(text=text, origin="pdf_url", url=pdf_url)


def looks_like_pdf(data: bytes) -> bool:
    """Is this actually a PDF?

    OA resolvers hand back landing pages, paywall interstitials and login
    redirects with content-type text/html and a URL ending in .pdf. Parsing one
    as a PDF fails, and the failure used to be reported as "no extractable text
    (likely scanned)" — an explanation that is confidently wrong and sends
    whoever reads it looking for an OCR problem that does not exist.
    """
    return data[:1024].lstrip()[:5] == b"%PDF-"


def describe_payload(data: bytes) -> str:
    """Name what arrived instead, so the error says something true."""
    head = data[:1024].lstrip().lower()
    if not data:
        return "empty response"
    if head.startswith((b"<!doc", b"<html")):
        return "got an HTML page — probably a landing page or paywall"
    if head.startswith(b"{") or head.startswith(b"["):
        return "got JSON — probably an API error"
    return f"unrecognised content, {len(data)} bytes"


def _download_target(pdf_url: str, settings: Any) -> tuple[str, dict[str, str]]:
    """Zotero attachment hrefs need the API key and the non-viewer endpoint."""
    from urllib.parse import urlparse

    host = urlparse(pdf_url).hostname or ""
    if host == "api.zotero.org" and getattr(settings, "zotero_api_key", None):
        url = pdf_url[: -len("/view")] if pdf_url.endswith("/view") else pdf_url
        return url, {"Zotero-API-Key": settings.zotero_api_key}
    return pdf_url, {}


async def fetch_full_text(meta: PaperMetadata, *, max_chars: int = MAX_TEXT_CHARS) -> FullText:
    """Local file, then a known PDF URL, then the OA chain.

    Local first because it is free, instant, and the copy the researcher
    actually has. The OA chain is last because it is the one that makes network
    calls to four providers.
    """
    if meta.pdf_path:
        result = read_pdf_file(meta.pdf_path, max_chars=max_chars)
        if result.ok:
            return result
        logger.debug("local PDF unusable for %s: %s", meta.title[:50], result.error)

    if meta.pdf_url:
        result = await download_pdf_text(meta.pdf_url, max_chars=max_chars)
        if result.ok:
            return result
        logger.debug("pdf_url unusable for %s: %s", meta.title[:50], result.error)

    doi = (meta.doi or "").strip()
    if doi:
        resolved = await resolve_oa_pdf(doi)
        if resolved is not None:
            url, resolver = resolved
            result = await download_pdf_text(url, max_chars=max_chars)
            if result.ok:
                result.origin = f"oa:{resolver}"
                return result
            return FullText(error=result.error or "OA PDF unreadable", url=url, origin=f"oa:{resolver}")

    return FullText(error="no open-access full text found", url=meta.pdf_url or "")
