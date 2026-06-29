"""Literature persistence + search on the SQLite backend.

Verifies store_paper inserts/upserts (no duplicate by (paper_id, doi)) and that
search_literature returns the local library via LIKE search — the offline path
that replaces pgvector when there's no Postgres.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from src.db import client as _client
from src.modules.literature.models import PaperMetadata

# Capture the REAL db helpers at import time, before conftest's autouse
# `_block_real_db_pool` fixture replaces them with no-op AsyncMocks. The
# sqlite_db fixture restores these so the tests hit a real tmp SQLite DB.
_REAL_EXECUTE = _client.execute
_REAL_FETCH_ONE = _client.fetch_one
_REAL_FETCH_ALL = _client.fetch_all


@pytest.fixture
def sqlite_db(tmp_path: Path, monkeypatch):
    """Point the metadata client at a fresh tmp SQLite DB and reset its cached
    backend/bootstrap state so each test is isolated. Restores the real DB
    helpers over conftest's autouse mocks."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'papers.db'}")
    monkeypatch.setattr("src.db.client.execute", _REAL_EXECUTE)
    monkeypatch.setattr("src.db.client.fetch_one", _REAL_FETCH_ONE)
    monkeypatch.setattr("src.db.client.fetch_all", _REAL_FETCH_ALL)
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False
    yield
    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


async def _make_paper_row(paper_id: str) -> None:
    from src.db.client import execute

    await execute(
        "INSERT INTO papers (id, title, status) VALUES (%(i)s, %(t)s, 'idea')",
        {"i": paper_id, "t": "host paper"},
    )


def _paper(title="Concentrated Liquidity and Price Discovery", doi="10.1/abc") -> PaperMetadata:
    return PaperMetadata(
        title=title,
        authors=["Alice Smith"],
        year=2024,
        doi=doi,
        abstract="We study automated market makers and price discovery.",
        journal="Journal of Finance",
        source="zotero_local",
        pdf_path="literature/smith2024.pdf",
    )


async def test_store_and_upsert_no_duplicate(sqlite_db):
    from src.db.client import fetch_all
    from src.modules.literature.storage import store_paper

    pid = str(uuid.uuid4())
    await _make_paper_row(pid)

    id1 = await store_paper(_paper(), pid)
    id2 = await store_paper(_paper(), pid)  # same (paper_id, doi) → update, not insert
    assert id1 == id2

    rows = await fetch_all("SELECT id FROM literature_items WHERE paper_id = %(p)s", {"p": pid})
    assert len(rows) == 1


async def test_doiless_items_both_stored(sqlite_db):
    from src.db.client import fetch_all
    from src.modules.literature.storage import store_paper

    pid = str(uuid.uuid4())
    await _make_paper_row(pid)
    await store_paper(_paper(title="Paper One", doi=""), pid)
    await store_paper(_paper(title="Paper Two", doi=""), pid)
    rows = await fetch_all("SELECT title FROM literature_items WHERE paper_id = %(p)s", {"p": pid})
    assert {r["title"] for r in rows} == {"Paper One", "Paper Two"}


async def test_search_finds_local_paper(sqlite_db):
    from src.modules.literature.storage import search_literature, store_paper

    pid = str(uuid.uuid4())
    await _make_paper_row(pid)
    await store_paper(_paper(), pid)

    hits = await search_literature("liquidity price discovery", paper_project_id=pid)
    assert hits
    assert hits[0]["title"] == "Concentrated Liquidity and Price Discovery"
    assert hits[0]["pdf_path"] == "literature/smith2024.pdf"


async def test_search_scoped_to_paper(sqlite_db):
    from src.modules.literature.storage import search_literature, store_paper

    pid_a, pid_b = str(uuid.uuid4()), str(uuid.uuid4())
    await _make_paper_row(pid_a)
    await _make_paper_row(pid_b)
    await store_paper(_paper(title="Liquidity in AMMs", doi="10.1/a"), pid_a)

    assert await search_literature("liquidity", paper_project_id=pid_a)
    assert await search_literature("liquidity", paper_project_id=pid_b) == []
