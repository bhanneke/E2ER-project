"""Contract tests for Lane B — literature-provider HTTP response shapes.

For each provider (OpenAlex, Semantic Scholar, arXiv) we mock the
documented response payload and assert our parser turns it into the
PaperMetadata shape the rest of the pipeline expects. Lane B currently
ships no other tests; these are the floor.

What this catches:
  - Upstream API rename of a top-level field (e.g. `results` → `items`)
  - Type drift (string year → int year)
  - Missing-field handling — empty authors list, null abstract, null DOI
  - Source label not being set on returned PaperMetadata

Payloads are abbreviated versions of real documented response shapes
from each provider's docs (links in each test's docstring).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------- OpenAlex ----------


_OPENALEX_RESPONSE: dict[str, Any] = {
    "meta": {"count": 2, "db_response_time_ms": 12, "page": 1, "per_page": 25},
    "results": [
        {
            "id": "https://openalex.org/W2741809807",
            "doi": "https://doi.org/10.1126/science.aac4716",
            "title": "Estimating the reproducibility of psychological science",
            "publication_year": 2015,
            "cited_by_count": 5012,
            "open_access": {"is_oa": True, "oa_url": "https://example.org/paper.pdf"},
            "primary_location": {"source": {"display_name": "Science"}},
            "authorships": [
                {"author": {"display_name": "Open Science Collaboration"}},
                {"author": {"display_name": "B. A. Nosek"}},
            ],
            "abstract_inverted_index": {"This": [0], "is": [1], "an": [2], "abstract.": [3]},
        },
        {
            # An entry with several optional fields absent — the parser
            # must NOT crash and must fall back to sensible defaults.
            "id": "https://openalex.org/W12345",
            "title": "Minimal paper",
            "publication_year": None,
            "authorships": [],
            "abstract_inverted_index": None,
        },
    ],
}


@pytest.mark.asyncio
async def test_openalex_search_parses_documented_response():
    """Documented response shape from https://docs.openalex.org/."""
    from src.modules.literature.openalex import search_papers

    with patch(
        "src.modules.literature.openalex.fetch_text",
        new=AsyncMock(return_value=json.dumps(_OPENALEX_RESPONSE)),
    ):
        result = await search_papers("test")

    assert result.source == "openalex"
    assert result.total_found == 2
    assert len(result.papers) == 2

    first = result.papers[0]
    assert first.title == "Estimating the reproducibility of psychological science"
    assert first.year == 2015
    assert first.doi == "10.1126/science.aac4716", "DOI must be stripped of https://doi.org/ prefix"
    assert first.citations == 5012
    assert first.pdf_url == "https://example.org/paper.pdf"
    assert first.journal == "Science"
    assert "Open Science Collaboration" in first.authors
    assert first.abstract == "This is an abstract."
    assert first.source == "openalex"

    second = result.papers[1]
    assert second.title == "Minimal paper"
    assert second.year is None
    assert second.authors == []
    assert second.abstract == ""


@pytest.mark.asyncio
async def test_openalex_search_handles_empty_results():
    """An empty results list must return an empty papers list, not crash."""
    from src.modules.literature.openalex import search_papers

    with patch(
        "src.modules.literature.openalex.fetch_text",
        new=AsyncMock(return_value=json.dumps({"meta": {"count": 0}, "results": []})),
    ):
        result = await search_papers("query that matches nothing")

    assert result.papers == []
    assert result.source == "openalex"
    assert result.total_found == 0


@pytest.mark.asyncio
async def test_openalex_search_falls_back_gracefully_on_http_error():
    """Network errors should yield an empty result with source set, not raise."""
    from src.modules.literature.openalex import search_papers

    with patch(
        "src.modules.literature.openalex.fetch_text",
        new=AsyncMock(side_effect=RuntimeError("connection refused")),
    ):
        result = await search_papers("anything")

    assert result.papers == []
    assert result.source == "openalex"


# ---------- Semantic Scholar ----------


_S2_RESPONSE: dict[str, Any] = {
    "total": 1,
    "offset": 0,
    "data": [
        {
            "paperId": "0796f6cd7f0403a854d67d525e9b32af3b277331",
            "externalIds": {"DOI": "10.1145/3447548.3467327", "ArXiv": "2106.01345"},
            "title": "Large-scale evidence on something",
            "abstract": "We provide evidence.",
            "year": 2021,
            "authors": [{"name": "Alice"}, {"name": "Bob"}],
            "venue": "KDD",
            "url": "https://www.semanticscholar.org/paper/0796f6cd",
            "citationCount": 42,
            "openAccessPdf": {"url": "https://example.org/s2.pdf"},
        }
    ],
}


@pytest.mark.asyncio
async def test_semantic_scholar_parses_documented_response():
    """Documented response shape from https://api.semanticscholar.org/graph/v1."""
    from src.modules.literature.semantic_scholar import search_papers

    with patch(
        "src.modules.literature.semantic_scholar.fetch_text",
        new=AsyncMock(return_value=json.dumps(_S2_RESPONSE)),
    ):
        result = await search_papers("anything")

    assert result.source == "semantic_scholar"
    assert result.total_found == 1
    assert len(result.papers) == 1

    p = result.papers[0]
    assert p.title == "Large-scale evidence on something"
    assert p.year == 2021
    assert p.doi == "10.1145/3447548.3467327"
    assert p.citations == 42
    assert p.pdf_url == "https://example.org/s2.pdf"
    assert p.authors == ["Alice", "Bob"]
    assert p.abstract == "We provide evidence."


@pytest.mark.asyncio
async def test_semantic_scholar_handles_empty_response():
    from src.modules.literature.semantic_scholar import search_papers

    with patch(
        "src.modules.literature.semantic_scholar.fetch_text",
        new=AsyncMock(return_value=json.dumps({"total": 0, "data": []})),
    ):
        result = await search_papers("anything")

    assert result.papers == []
    assert result.source == "semantic_scholar"


# ---------- arXiv ----------


_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>Foundations of Distributed Knowledge</title>
    <summary>Abstract text here.</summary>
    <published>2024-01-22T18:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <author><name>John Smith</name></author>
    <arxiv:primary_category term="cs.AI"/>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_arxiv_parses_atom_feed():
    """arXiv returns Atom XML, not JSON. The parser uses ElementTree."""
    from src.modules.literature.arxiv import search_papers

    with patch(
        "src.modules.literature.arxiv.fetch_text",
        new=AsyncMock(return_value=_ARXIV_ATOM),
    ):
        result = await search_papers("anything")

    assert result.source == "arxiv"
    assert len(result.papers) == 1

    p = result.papers[0]
    assert p.title == "Foundations of Distributed Knowledge"
    assert "Jane Doe" in p.authors
    assert "John Smith" in p.authors
    assert p.abstract == "Abstract text here."


@pytest.mark.asyncio
async def test_arxiv_handles_empty_feed():
    empty_feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    from src.modules.literature.arxiv import search_papers

    with patch(
        "src.modules.literature.arxiv.fetch_text",
        new=AsyncMock(return_value=empty_feed),
    ):
        result = await search_papers("query that matches nothing")

    assert result.papers == []
    assert result.source == "arxiv"


@pytest.mark.asyncio
async def test_arxiv_falls_back_on_malformed_xml():
    """Malformed XML should yield empty result, not raise into specialist code."""
    from src.modules.literature.arxiv import search_papers

    with patch(
        "src.modules.literature.arxiv.fetch_text",
        new=AsyncMock(return_value="<<not valid xml>>"),
    ):
        result = await search_papers("anything")

    assert result.papers == []
    assert result.source == "arxiv"
