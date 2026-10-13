"""The web literature search gets usable queries: no cut-off title, no parenthesis arXiv refuses."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

from src.api.app import literature_queries
from src.cli_run import derive_title

RQ = (
    "Did abolishing primary-school fees in sub-Saharan African countries (staggered between the mid-1990s "
    "and the mid-2000s) raise gross primary enrolment? A difference-in-differences with World Bank data."
)


def test_a_cut_title_is_searched_in_full():
    title = derive_title(RQ)
    assert title.endswith("...")
    queries = literature_queries(RQ, title)
    assert queries[0] == RQ
    assert queries[1].endswith("raise gross primary enrolment")
    assert not any(q.endswith("...") for q in queries)


def test_a_short_title_is_kept_and_a_repeat_dropped():
    assert literature_queries("Do ETFs comove?", "Do ETFs comove") == ["Do ETFs comove?", "Do ETFs comove"]
    assert literature_queries("Short question", "Short question") == ["Short question"]
    # A title the researcher typed is not replaced, even with "..." at its end.
    assert literature_queries(RQ, "My own title...") == [RQ, "My own title..."]


def test_arxiv_query_has_no_parentheses(monkeypatch):
    from src.modules.literature import arxiv

    seen: dict[str, str] = {}

    async def fake_fetch(url: str) -> str:
        seen["url"] = url
        return '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    monkeypatch.setattr(arxiv, "fetch_text", fake_fetch)
    asyncio.run(arxiv.search_papers("fees (staggere...", 5))
    q = parse_qs(urlparse(seen["url"]).query)["search_query"][0]
    assert "(" not in q and ")" not in q
    assert q == "all:fees staggere..."
