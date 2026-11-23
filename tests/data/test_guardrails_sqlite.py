"""Feasibility-first on the default SQLite run database (review 2026-11-22, finding 5).

The guardrail matched the feasibility query's SQL with ``ILIKE``, which SQLite does not know:
every production query crashed with ``near "ILIKE": syntax error`` on the default database.
A real SQLite database; no network.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from src.db import client as _client
from src.modules.data import audit_journal
from src.modules.data.guardrails import QueryValidator

_REAL = (_client.execute, _client.fetch_one, _client.fetch_all)


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "papers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.delenv(audit_journal.ENV, raising=False)
    monkeypatch.setattr("src.db.client.execute", _REAL[0])
    monkeypatch.setattr("src.db.client.fetch_one", _REAL[1])
    monkeypatch.setattr("src.db.client.fetch_all", _REAL[2])
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False
    yield path
    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


def _setup(feasibility_sql: str | None) -> str:
    pid = str(uuid.uuid4())

    async def go() -> None:
        await _client.execute(
            "INSERT INTO papers (id, title, research_question, status) VALUES (%(id)s, 't', 'q', 'designing')",
            {"id": pid},
        )
        if feasibility_sql:
            await _client.execute(
                "INSERT INTO data_query_records (id, paper_id, specialist, query_sql, query_type, validation_status) "
                "VALUES (%(id)s, %(pid)s, 's', %(sql)s, 'feasibility', 'approved')",
                {"id": str(uuid.uuid4()), "pid": pid, "sql": feasibility_sql},
            )

    asyncio.run(go())
    return pid


def test_production_query_passes_feasibility_first_on_sqlite(db):
    pid = _setup("SELECT a FROM Chain.Trades WHERE ts > '2024-01-01' LIMIT 10")
    result = asyncio.run(QueryValidator.validate_feasibility_first("production", pid, "chain.trades"))
    assert result.valid, result.rejection_reason


def test_production_query_without_feasibility_is_refused_on_sqlite(db):
    pid = _setup(None)
    result = asyncio.run(QueryValidator.validate_feasibility_first("production", pid, "chain.trades"))
    assert not result.valid
    assert "No approved feasibility query" in (result.rejection_reason or "")


def test_the_sqlite_translator_rewrites_ilike():
    assert _client._translate_to_sqlite("a ILIKE %(p)s AND b not ilike 'x'") == "a LIKE :p AND b not LIKE 'x'"
    assert _client._translate_to_sqlite("SELECT 'ILIKEWISE'") == "SELECT 'ILIKEWISE'"
