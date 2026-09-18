"""M3: OA-PDF resolver chain — Unpaywall + Crossref + cache."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.modules.literature import unpaywall
from src.modules.literature.crossref import _pick_pdf_link
from src.modules.literature.oa_resolvers import (
    CrossrefOA,
    OpenAlexOA,
    SemanticScholarOA,
    UnpaywallOA,
    oa_pdf_resolvers,
)
from src.modules.literature.tools import LiteratureToolHandler

# ── unpaywall.find_oa ────────────────────────────────────────────────────────


def test_best_pdf_url_prefers_url_for_pdf():
    data = {
        "best_oa_location": {"url_for_pdf": "https://x/pdf", "url": "https://x/landing"},
    }
    assert unpaywall._best_pdf_url(data) == "https://x/pdf"


def test_best_pdf_url_falls_back_to_url():
    data = {"best_oa_location": {"url_for_pdf": None, "url": "https://x/landing"}}
    assert unpaywall._best_pdf_url(data) == "https://x/landing"


def test_best_pdf_url_walks_oa_locations_when_best_is_null():
    data = {
        "best_oa_location": None,
        "oa_locations": [
            {"url_for_pdf": None, "url": None},
            {"url_for_pdf": "https://repo/file.pdf", "url": "https://repo/"},
        ],
    }
    assert unpaywall._best_pdf_url(data) == "https://repo/file.pdf"


def test_best_pdf_url_empty_when_no_oa():
    assert unpaywall._best_pdf_url({"best_oa_location": None, "oa_locations": []}) == ""


async def test_find_oa_returns_paper_with_pdf_url():
    payload = (
        '{"doi":"10.1/x","title":"T","year":2020,'
        '"best_oa_location":{"url_for_pdf":"https://x/p.pdf"},'
        '"z_authors":[{"given":"A","family":"Author"}]}'
    )
    with patch("src.modules.literature.unpaywall.fetch_text", new=AsyncMock(return_value=payload)):
        p = await unpaywall.find_oa("10.1/x", "me@example.com")
    assert p is not None
    assert p.pdf_url == "https://x/p.pdf"
    assert p.year == 2020
    assert p.authors == ["A Author"]


async def test_find_oa_returns_none_when_no_oa_location():
    payload = '{"doi":"10.1/x","title":"T","best_oa_location":null,"oa_locations":[]}'
    with patch("src.modules.literature.unpaywall.fetch_text", new=AsyncMock(return_value=payload)):
        p = await unpaywall.find_oa("10.1/x", "me@example.com")
    assert p is None


async def test_find_oa_handles_errors_gracefully():
    with patch("src.modules.literature.unpaywall.fetch_text", new=AsyncMock(side_effect=RuntimeError("network"))):
        p = await unpaywall.find_oa("10.1/x", "me@example.com")
    assert p is None


async def test_find_oa_requires_doi_and_email():
    assert await unpaywall.find_oa("", "me@x") is None
    assert await unpaywall.find_oa("10.1/x", "") is None


# ── crossref._pick_pdf_link ──────────────────────────────────────────────────


def test_pick_pdf_link_finds_pdf_content_type():
    message = {
        "link": [
            {"URL": "https://x/text.xml", "content-type": "application/xml"},
            {"URL": "https://x/paper.pdf", "content-type": "application/pdf"},
        ]
    }
    assert _pick_pdf_link(message) == "https://x/paper.pdf"


def test_pick_pdf_link_case_insensitive_content_type():
    message = {"link": [{"URL": "https://x/p.pdf", "content-type": "Application/PDF"}]}
    assert _pick_pdf_link(message) == "https://x/p.pdf"


def test_pick_pdf_link_returns_empty_when_no_pdf():
    message = {"link": [{"URL": "https://x/text.xml", "content-type": "application/xml"}]}
    assert _pick_pdf_link(message) == ""


def test_pick_pdf_link_handles_missing_link_field():
    assert _pick_pdf_link({}) == ""


# ── OA resolver adapters ────────────────────────────────────────────────────


async def test_unpaywall_oa_returns_url_on_success():
    with patch(
        "src.modules.literature.oa_resolvers.unpaywall.find_oa_pdf",
        new=AsyncMock(return_value="https://x/p.pdf"),
    ):
        assert await UnpaywallOA(email="me@x").resolve("10.1/x") == "https://x/p.pdf"


async def test_unpaywall_oa_returns_none_on_miss():
    with patch(
        "src.modules.literature.oa_resolvers.unpaywall.find_oa_pdf",
        new=AsyncMock(return_value=None),
    ):
        assert await UnpaywallOA(email="me@x").resolve("10.1/x") is None


async def test_unpaywall_oa_swallows_exceptions():
    with patch(
        "src.modules.literature.oa_resolvers.unpaywall.find_oa_pdf",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        assert await UnpaywallOA(email="me@x").resolve("10.1/x") is None


async def test_openalex_oa_returns_pdf_url_when_paper_has_one():
    from src.modules.literature.models import PaperMetadata

    paper = PaperMetadata(title="T", doi="10.1/x", pdf_url="https://oa.example/p.pdf")
    with patch(
        "src.modules.literature.oa_resolvers.openalex.fetch_by_doi",
        new=AsyncMock(return_value=paper),
    ):
        assert await OpenAlexOA().resolve("10.1/x") == "https://oa.example/p.pdf"


async def test_openalex_oa_returns_none_when_paper_has_no_pdf():
    from src.modules.literature.models import PaperMetadata

    paper = PaperMetadata(title="T", doi="10.1/x", pdf_url="")
    with patch(
        "src.modules.literature.oa_resolvers.openalex.fetch_by_doi",
        new=AsyncMock(return_value=paper),
    ):
        assert await OpenAlexOA().resolve("10.1/x") is None


async def test_crossref_oa_calls_find_oa_pdf():
    with patch(
        "src.modules.literature.oa_resolvers.crossref.find_oa_pdf",
        new=AsyncMock(return_value="https://publisher/p.pdf"),
    ):
        assert await CrossrefOA().resolve("10.1/x") == "https://publisher/p.pdf"


async def test_semantic_scholar_oa_returns_pdf_url():
    from src.modules.literature.models import PaperMetadata

    paper = PaperMetadata(title="T", doi="10.1/x", pdf_url="https://s2/p.pdf")
    with patch(
        "src.modules.literature.oa_resolvers.semantic_scholar.fetch_by_doi",
        new=AsyncMock(return_value=paper),
    ):
        assert await SemanticScholarOA().resolve("10.1/x") == "https://s2/p.pdf"


# ── registry chain ──────────────────────────────────────────────────────────


def test_oa_pdf_resolvers_default_order():
    settings = SimpleNamespace(unpaywall_email="me@example.com")
    chain = oa_pdf_resolvers(settings)  # type: ignore[arg-type]
    names = [r.name for r in chain]
    assert names == ["unpaywall", "openalex", "crossref", "semantic_scholar"]


# ── Cache in LiteratureToolHandler ──────────────────────────────────────────


async def test_resolve_oa_pdf_caches_hit(tmp_path: Path):
    handler = LiteratureToolHandler(tmp_path)
    call_count = {"n": 0}

    async def fake_resolve(self, doi):
        call_count["n"] += 1
        return "https://x/p.pdf"

    with patch.object(UnpaywallOA, "resolve", new=fake_resolve):
        url1 = await handler._resolve_oa_pdf("10.1/x")
        url2 = await handler._resolve_oa_pdf("10.1/x")
    assert url1 == url2 == "https://x/p.pdf"
    assert call_count["n"] == 1  # second call hit the cache


async def test_resolve_oa_pdf_caches_miss(tmp_path: Path):
    """A known-miss must also cache — otherwise retries keep hammering."""
    handler = LiteratureToolHandler(tmp_path)
    counts = {"unpay": 0, "oa": 0, "cross": 0, "s2": 0}

    async def fake_u(self, doi):
        counts["unpay"] += 1
        return None

    async def fake_oa(self, doi):
        counts["oa"] += 1
        return None

    async def fake_cr(self, doi):
        counts["cross"] += 1
        return None

    async def fake_s2(self, doi):
        counts["s2"] += 1
        return None

    with (
        patch.object(UnpaywallOA, "resolve", new=fake_u),
        patch.object(OpenAlexOA, "resolve", new=fake_oa),
        patch.object(CrossrefOA, "resolve", new=fake_cr),
        patch.object(SemanticScholarOA, "resolve", new=fake_s2),
    ):
        assert await handler._resolve_oa_pdf("10.1/y") is None
        assert await handler._resolve_oa_pdf("10.1/y") is None
    # All four resolvers ran ONCE; the cached None served the second call.
    assert counts == {"unpay": 1, "oa": 1, "cross": 1, "s2": 1}


async def test_resolve_oa_pdf_short_circuits_after_first_hit(tmp_path: Path):
    """First non-None resolver wins; downstream resolvers must not run."""
    handler = LiteratureToolHandler(tmp_path)
    later_called = {"oa": 0, "cr": 0, "s2": 0}

    async def fake_u(self, doi):
        return "https://x/p.pdf"

    async def fake_oa(self, doi):
        later_called["oa"] += 1
        return "should-not-be-called"

    async def fake_cr(self, doi):
        later_called["cr"] += 1
        return None

    async def fake_s2(self, doi):
        later_called["s2"] += 1
        return None

    with (
        patch.object(UnpaywallOA, "resolve", new=fake_u),
        patch.object(OpenAlexOA, "resolve", new=fake_oa),
        patch.object(CrossrefOA, "resolve", new=fake_cr),
        patch.object(SemanticScholarOA, "resolve", new=fake_s2),
    ):
        url = await handler._resolve_oa_pdf("10.1/z")
    assert url == "https://x/p.pdf"
    assert later_called == {"oa": 0, "cr": 0, "s2": 0}


# ── _read_reference falls through to OA resolver ────────────────────────────


async def test_read_reference_falls_through_metadata_chain_to_oa_resolver(tmp_path: Path):
    """Metadata chain returns a paper with no pdf_url → OA resolver chain
    runs and the PDF download proceeds with whatever it surfaces."""
    import json as _json

    from src.modules.literature.models import PaperMetadata

    handler = LiteratureToolHandler(tmp_path)
    metadata_paper = PaperMetadata(title="T", doi="10.1/z", pdf_url="")  # no PDF
    pdf_bytes = b"%PDF-1.4\n... fake content ..."

    async def fake_resolve_doi(doi):
        return ("openalex", metadata_paper)

    async def fake_oa_resolve(_self, doi):
        return "https://oa.fallback/p.pdf"

    # Patch at the original import sites (pdf.extract_pdf_text +
    # fetch.http.fetch_bytes) — tools.py imports them lazily inside
    # _read_reference so we must reach them through their owning modules.
    with (
        patch.object(handler, "_resolve_doi", new=fake_resolve_doi),
        patch.object(UnpaywallOA, "resolve", new=fake_oa_resolve),
        patch("src.modules.literature.pdf.extract_pdf_text", return_value="full text body"),
        patch("src.modules.fetch.http.fetch_bytes", new=AsyncMock(return_value=pdf_bytes)),
    ):
        raw = await handler._read_reference({"doi": "10.1/z"})
    out = _json.loads(raw)
    assert out.get("pdf_url") == "https://oa.fallback/p.pdf"
    assert out.get("chars") == len("full text body")
