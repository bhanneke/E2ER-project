"""A spent OpenAlex budget is said plainly, not read as "no literature" (2026-10-13 demo).

Keyless OpenAlex requests share one daily budget per network. The weather-words
demo got 429 "Insufficient budget" all night and its literature search found
nothing, with nothing in the run saying why. No network: requests are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.modules.literature import openalex
from src.modules.literature.discovery import acquire_literature
from src.modules.literature.models import PaperMetadata, SearchResult

BUDGET_BODY = {
    "error": "Insufficient budget. This request has no API key, so it uses the free daily budget shared by your IP.",
    "retryAfter": 50213,
    "dailyRemainingUsd": 0,
}
SETTINGS = SimpleNamespace(literature_acquire_limit=30)


@pytest.fixture(autouse=True)
def _fresh_budget(monkeypatch):
    monkeypatch.setattr(openalex, "_budget_spent_on", None)
    monkeypatch.setattr(openalex, "_headers", lambda: {})


def test_the_budget_refusal_is_told_apart_from_a_burst_limit():
    assert openalex.is_budget_refusal(429, json.dumps(BUDGET_BODY))
    assert not openalex.is_budget_refusal(429, '{"error": "Too many requests", "retryAfter": 1}')
    assert not openalex.is_budget_refusal(500, json.dumps(BUDGET_BODY))


@respx.mock
async def test_a_spent_budget_returns_a_notice_and_stops_asking():
    route = respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(429, json=BUDGET_BODY)
    )
    first = await openalex.search_papers("weather words in novels")
    assert first.papers == [] and first.notice == openalex.BUDGET_SPENT
    second = await openalex.search_papers("another query")
    assert second.notice == openalex.BUDGET_SPENT
    assert route.call_count == 1  # the rest of the day does not ask again
    assert await openalex.fetch_by_doi("10.1/x") is None and route.call_count == 1


@respx.mock
async def test_a_burst_limit_is_not_a_spent_budget():
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(429, json={"error": "Too many requests", "retryAfter": 1})
    )
    result = await openalex.search_papers("q")
    assert result.papers == [] and result.notice == ""
    assert not openalex.budget_spent_today()


def _source(name: str, result: SearchResult):
    return SimpleNamespace(name=name, search=AsyncMock(return_value=result))


async def _acquire(tmp_path: Path, *sources) -> tuple[int, list[tuple]]:
    events: list[tuple] = []

    async def log_event(paper_id, event_type, *, stage=None, specialist=None, payload=None):
        events.append((event_type, payload))

    with (
        patch("src.modules.literature.registry.search_sources", return_value=list(sources)),
        patch("src.modules.literature.storage.store_paper", new=AsyncMock()),
        patch("src.db.events.log_event", new=log_event),
    ):
        n = await acquire_literature(tmp_path, "p1", ["weather words in english novels"], SETTINGS)
    return n, events


async def test_the_run_says_the_search_found_nothing_today(tmp_path: Path):
    spent = SearchResult(papers=[], source="openalex", query="q", notice=openalex.BUDGET_SPENT)
    n, events = await _acquire(tmp_path, _source("openalex", spent), _source("arxiv", SearchResult([], "arxiv", "q")))
    assert n == 0
    expected = "OpenAlex's free daily budget for this network is used up; the literature search found nothing today"
    record = json.loads((tmp_path / "literature" / "web_search.json").read_text())
    assert record["notices"][0].startswith(expected)
    assert events == [("literature_search_notice", {"notice": record["notices"][0]})]


async def test_other_sources_still_count_and_the_notice_says_so(tmp_path: Path):
    spent = SearchResult(papers=[], source="openalex", query="q", notice=openalex.BUDGET_SPENT)
    hit = PaperMetadata(title="Weather words in English novels", authors=["Smith"], year=2020, doi="10.1/w")
    n, events = await _acquire(
        tmp_path, _source("openalex", spent), _source("arxiv", SearchResult([hit], "arxiv", "q"))
    )
    assert n == 1
    record = json.loads((tmp_path / "literature" / "web_search.json").read_text())
    assert "used the other sources only today" in record["notices"][0]


async def test_no_notice_when_openalex_answers(tmp_path: Path):
    hit = PaperMetadata(title="Weather words in English novels", authors=["Smith"], year=2020, doi="10.1/w")
    _n, events = await _acquire(tmp_path, _source("openalex", SearchResult([hit], "openalex", "q")))
    assert events == []
    assert "notices" not in json.loads((tmp_path / "literature" / "web_search.json").read_text())


async def test_the_literature_tool_passes_the_notice_to_the_specialist(monkeypatch, tmp_path: Path):
    from src.modules.literature import tools

    spent = SearchResult(papers=[], source="openalex", query="q", notice=openalex.BUDGET_SPENT)
    monkeypatch.setattr("src.modules.literature.registry.search_sources", lambda s: [_source("openalex", spent)])
    monkeypatch.setattr("src.config.get_settings", lambda: SimpleNamespace(literature_local_enabled=False))
    handler = tools.LiteratureToolHandler(tmp_path)
    out = json.loads(await handler._search({"query": "weather words", "limit": 5}))
    assert out["count"] == 0 and "found nothing today" in out["notice"]
