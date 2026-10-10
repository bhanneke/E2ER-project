"""The always-on literature acquisition stage.

Why it exists, measured rather than assumed: v1's shipped papers pass v3's own
citation gate (e2er_v1_bitcoin_institutionalization 31/33 verified, 0
missing_in_bib; e2er_v1_nft_seasonality 37/38, 0 missing). v1 got that from a
literature agent that ran as a mandatory pipeline step. v3 replaced it with
LITERATURE_TOOLS, which `tool_loop` ignores on every CLI backend; the `e2er-lit`
bridge made the capability reachable and canary #7 still never called it, then
cited 23 keys against a bibliography that did not exist.

So acquisition does not ask the model. These tests pin that: it runs, it writes,
it runs beside a researcher's own library without touching it (its entries are
marked as found on the web), and it never takes the pipeline down.

No network — the provider chain is patched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.modules.literature.discovery import acquire_literature, bib_entry_count
from src.modules.literature.models import PaperMetadata, SearchResult

SETTINGS = SimpleNamespace(literature_acquire_limit=30)

BIB = """@article{lycsa2020impact,
  title = {Impact of macroeconomic news on the volatility of bitcoin},
  year = {2020},
}
"""


def _paper(title: str, author: str = "Smith", year: int = 2020) -> PaperMetadata:
    return PaperMetadata(title=title, authors=[author], year=year, doi=f"10.1/{title[:6]}")


def _source(name: str, papers: list[PaperMetadata] | None = None, boom: bool = False):
    src = SimpleNamespace(name=name)
    if boom:
        src.search = AsyncMock(side_effect=RuntimeError("provider down"))
    else:
        src.search = AsyncMock(return_value=SearchResult(papers=papers or [], source=name, query="q"))
    return src


def _with_sources(*sources):
    return patch("src.modules.literature.registry.search_sources", return_value=list(sources))


def _no_storage():
    return patch("src.modules.literature.storage.store_paper", new=AsyncMock())


# ── bib_entry_count ──────────────────────────────────────────────────────────


def test_entry_count_absent_file(tmp_path: Path):
    assert bib_entry_count(tmp_path) == 0


def test_entry_count_reads_entries(tmp_path: Path):
    (tmp_path / "literature.bib").write_text(BIB, encoding="utf-8")
    assert bib_entry_count(tmp_path) == 1


# ── the stage ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_writes_a_bibliography_from_the_research_question(tmp_path: Path):
    # Both share the question's words (the web search keeps only hits on its topic: see test_study_inputs).
    hits = [
        _paper("Spot ETF approval and volatility"),
        _paper("Realized volatility after spot ETF launches", "Jones", 2021),
    ]
    with _with_sources(_source("openalex", hits)), _no_storage():
        n = await acquire_literature(tmp_path, "p1", ["does the spot ETF change volatility?"], SETTINGS)

    assert n == 2
    written = (tmp_path / "literature.bib").read_text(encoding="utf-8")
    assert "smith2020spot" in written
    assert "jones2021realized" in written


@pytest.mark.asyncio
async def test_a_hit_off_the_questions_topic_is_left_out(tmp_path: Path):
    hits = [_paper("Spot ETF approval and volatility"), _paper("Teen birth rates and contraception", "Jones", 2021)]
    with _with_sources(_source("openalex", hits)), _no_storage():
        n = await acquire_literature(tmp_path, "p1", ["does the spot ETF change volatility?"], SETTINGS)

    assert n == 1 and "Teen birth" not in (tmp_path / "literature.bib").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_runs_in_addition_to_a_researchers_own_library_marked_as_found_on_the_web(tmp_path: Path):
    """Since 0.15.0 the web search runs in addition to the researcher's papers, never silently:
    the researcher's entries stay as they are, and every web entry says it came from the web."""
    (tmp_path / "literature.bib").write_text(BIB, encoding="utf-8")
    same = _paper("Impact of macroeconomic news on the volatility of bitcoin", "Lyócsa", 2020)
    src = _source("openalex", [_paper("Something else"), same])

    with _with_sources(src), _no_storage():
        n = await acquire_literature(tmp_path, "p1", ["a question"], SETTINGS)

    assert n == 1, "the hit for the researcher's own paper is not a second entry"
    bib = (tmp_path / "literature.bib").read_text(encoding="utf-8")
    assert bib.startswith(BIB.strip()), "the researcher's entries stay first and unchanged"
    assert "smith2020something" in bib and "e2er_source = {web}" in bib


@pytest.mark.asyncio
async def test_use_only_my_papers_sends_no_request(tmp_path: Path):
    (tmp_path / "literature.bib").write_text(BIB, encoding="utf-8")
    src = _source("openalex", [_paper("Something else")])

    with _with_sources(src), _no_storage():
        n = await acquire_literature(tmp_path, "p1", ["a question"], SETTINGS, web_search=False)

    assert n == 0
    src.search.assert_not_awaited()
    assert (tmp_path / "literature.bib").read_text(encoding="utf-8") == BIB


@pytest.mark.asyncio
async def test_a_web_hit_never_replaces_a_researchers_entry_with_the_same_key(tmp_path: Path):
    mine = PaperMetadata(
        title="Spot trading", authors=["Ann Smith"], year=2020, source="bibtex", cite_key="smith2020spot"
    )
    (tmp_path / "literature.bib").write_text(mine.to_bibtex() + "\n", encoding="utf-8")
    other = _paper("Spot markets elsewhere", "Bob Smith", 2020)  # derives the same key, smith2020spot
    assert other.bibtex_key == "smith2020spot"

    with _with_sources(_source("openalex", [other])), _no_storage():
        await acquire_literature(tmp_path, "p1", ["a question"], SETTINGS)

    bib = (tmp_path / "literature.bib").read_text(encoding="utf-8")
    assert "Spot trading" in bib and "Spot markets elsewhere" not in bib


@pytest.mark.asyncio
async def test_falls_through_to_the_next_source(tmp_path: Path):
    dead = _source("openalex", boom=True)
    alive = _source("arxiv", [_paper("A paper")])

    with _with_sources(dead, alive), _no_storage():
        n = await acquire_literature(tmp_path, "p1", ["q"], SETTINGS)

    assert n == 1
    alive.search.assert_awaited()


@pytest.mark.asyncio
async def test_first_source_with_hits_wins(tmp_path: Path):
    """Same chain semantics as the SDK handler — not a merge across providers."""
    first = _source("openalex", [_paper("From OpenAlex")])
    second = _source("arxiv", [_paper("From arXiv", "Other")])

    with _with_sources(first, second), _no_storage():
        await acquire_literature(tmp_path, "p1", ["q"], SETTINGS)

    second.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedupes_across_the_two_queries(tmp_path: Path):
    """The research question and the title overlap heavily; one paper found by
    both must produce one entry."""
    same = _paper("Spot ETF volatility")
    with _with_sources(_source("openalex", [same])), _no_storage():
        n = await acquire_literature(
            tmp_path, "p1", ["Does the spot ETF change volatility?", "Spot ETF volatility"], SETTINGS
        )

    assert n == 1


@pytest.mark.asyncio
async def test_no_query_is_a_no_op(tmp_path: Path):
    with _with_sources(_source("openalex", [_paper("x")])), _no_storage():
        assert await acquire_literature(tmp_path, "p1", ["", "   "], SETTINGS) == 0
    assert not (tmp_path / "literature.bib").exists()


@pytest.mark.asyncio
async def test_finding_nothing_leaves_no_bibliography(tmp_path: Path):
    with _with_sources(_source("openalex", [])), _no_storage():
        assert await acquire_literature(tmp_path, "p1", ["q"], SETTINGS) == 0
    assert not (tmp_path / "literature.bib").exists()


@pytest.mark.asyncio
async def test_every_source_failing_does_not_raise(tmp_path: Path):
    """A dead network must cost the bibliography, never the run."""
    with _with_sources(_source("openalex", boom=True), _source("arxiv", boom=True)), _no_storage():
        assert await acquire_literature(tmp_path, "p1", ["q"], SETTINGS) == 0


@pytest.mark.asyncio
async def test_a_storage_failure_still_leaves_the_bibliography(tmp_path: Path):
    """The .bib is what makes the draft compile; SQLite persistence is a bonus."""
    with (
        _with_sources(_source("openalex", [_paper("A paper")])),
        patch("src.modules.literature.storage.store_paper", new=AsyncMock(side_effect=RuntimeError("db gone"))),
    ):
        n = await acquire_literature(tmp_path, "p1", ["q"], SETTINGS)

    assert n == 1
    assert "smith2020a" in (tmp_path / "literature.bib").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_untitled_hits_are_dropped(tmp_path: Path):
    """A title-less record cannot be cited and would collide on the fallback key."""
    with _with_sources(_source("openalex", [_paper("Real one"), PaperMetadata(title="")])), _no_storage():
        assert await acquire_literature(tmp_path, "p1", ["q"], SETTINGS) == 1
