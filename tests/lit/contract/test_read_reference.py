"""Lane B — full-text read_reference tool + PDF extraction (M2.5).

Mock-only (no network, no real PDFs). Pins:
  - extract_pdf_text: page join, char cap, graceful empties,
  - read_reference: pdf_url and doi paths, Zotero auth + /view normalization,
    open-access (no auth), error envelopes, and the per-specialist read budget.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.modules.literature.models import PaperMetadata
from src.modules.literature.pdf import extract_pdf_text
from src.modules.literature.tools import LiteratureToolHandler

_FETCH = "src.modules.fetch.http.fetch_bytes"
_EXTRACT = "src.modules.literature.pdf.extract_pdf_text"
_SETTINGS = "src.config.get_settings"


def _settings(zotero_api_key=None):
    return SimpleNamespace(zotero_api_key=zotero_api_key)


# ---------------------------------------------------------------------------
# extract_pdf_text (real pypdf, faked PdfReader)
# ---------------------------------------------------------------------------


def _page(text: str):
    p = MagicMock()
    p.extract_text.return_value = text
    return p


def test_extract_joins_pages_and_caps():
    reader = MagicMock()
    reader.pages = [_page("A" * 15000), _page("B" * 15000)]
    with patch("pypdf.PdfReader", return_value=reader):
        out = extract_pdf_text(b"%PDF-fake", max_chars=20000)
    assert len(out) <= 20000 + len("\n\n[... truncated]")
    assert out.endswith("[... truncated]")


def test_extract_empty_when_no_text_layer():
    reader = MagicMock()
    reader.pages = [_page(""), _page("")]
    with patch("pypdf.PdfReader", return_value=reader):
        assert extract_pdf_text(b"%PDF-fake") == ""


def test_extract_returns_empty_on_parse_error():
    with patch("pypdf.PdfReader", side_effect=Exception("corrupt")):
        assert extract_pdf_text(b"not a pdf") == ""


# ---------------------------------------------------------------------------
# read_reference — happy paths
# ---------------------------------------------------------------------------


async def _read(handler, inp, *, zotero_api_key=None, extract="FULLTEXT", fetch=b"%PDF"):
    with (
        patch(_SETTINGS, return_value=_settings(zotero_api_key)),
        patch(_FETCH, new=AsyncMock(return_value=fetch)) as fb,
        patch(_EXTRACT, return_value=extract) as ex,
    ):
        result = await handler.handle("read_reference", inp)
    return result, fb, ex


async def test_reads_pdf_url():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    result, fb, _ = await _read(handler, {"pdf_url": "https://oa.org/p.pdf"})
    out = json.loads(result)
    assert out["text"] == "FULLTEXT"
    assert out["pdf_url"] == "https://oa.org/p.pdf"
    # open-access → no auth header
    assert fb.await_args.kwargs["headers"] == {}


async def test_zotero_url_gets_auth_and_file_normalization():
    handler = LiteratureToolHandler(Path("/tmp"))
    url = "https://api.zotero.org/users/1/items/ABCD/file/view"
    _result, fb, _ = await _read(handler, {"pdf_url": url}, zotero_api_key="SECRET")
    called_url = fb.await_args.args[0]
    assert called_url == "https://api.zotero.org/users/1/items/ABCD/file"  # /view stripped
    assert fb.await_args.kwargs["headers"]["Zotero-API-Key"] == "SECRET"


async def test_doi_resolves_open_access_pdf():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    paper = PaperMetadata(title="X", pdf_url="https://oa.org/resolved.pdf", source="openalex")
    handler._resolve_doi = AsyncMock(return_value=("openalex", paper))
    result, fb, _ = await _read(handler, {"doi": "10.1/x"})
    assert json.loads(result)["pdf_url"] == "https://oa.org/resolved.pdf"
    assert fb.await_args.args[0] == "https://oa.org/resolved.pdf"


# ---------------------------------------------------------------------------
# read_reference — error envelopes
# ---------------------------------------------------------------------------


async def test_no_pdf_url_or_doi_errors():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    result, _, _ = await _read(handler, {})
    assert "no readable PDF" in json.loads(result)["error"]


async def test_doi_without_oa_pdf_errors():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    paper = PaperMetadata(title="X", pdf_url="", source="openalex")
    handler._resolve_doi = AsyncMock(return_value=("openalex", paper))
    result, _, _ = await _read(handler, {"doi": "10.1/x"})
    assert "no readable PDF" in json.loads(result)["error"]


async def test_download_failure_errors():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    with (
        patch(_SETTINGS, return_value=_settings()),
        patch(_FETCH, new=AsyncMock(side_effect=RuntimeError("404"))),
    ):
        result = await handler.handle("read_reference", {"pdf_url": "https://oa.org/p.pdf"})
    assert "could not download" in json.loads(result)["error"]


async def test_scanned_pdf_no_text_errors():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    result, _, _ = await _read(handler, {"pdf_url": "https://oa.org/scan.pdf"}, extract="")
    assert "no extractable text" in json.loads(result)["error"]


# ---------------------------------------------------------------------------
# Budget + registration
# ---------------------------------------------------------------------------


async def test_read_budget_enforced():
    import json

    handler = LiteratureToolHandler(Path("/tmp"))
    cap = LiteratureToolHandler._MAX_READS
    with (
        patch(_SETTINGS, return_value=_settings()),
        patch(_FETCH, new=AsyncMock(return_value=b"%PDF")),
        patch(_EXTRACT, return_value="text"),
    ):
        for _ in range(cap):
            r = await handler.handle("read_reference", {"pdf_url": "https://oa.org/p.pdf"})
            assert "budget exhausted" not in r
        over = await handler.handle("read_reference", {"pdf_url": "https://oa.org/p.pdf"})
    assert "budget exhausted" in json.loads(over)["error"]


def test_can_handle_read_reference():
    assert LiteratureToolHandler(Path("/tmp")).can_handle("read_reference") is True
