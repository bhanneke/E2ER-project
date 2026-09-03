"""Per-paper LLM backend / model override (WS-P3.0).

Two papers must be able to run on different backends against one server —
the enabler for multi-model runs and the governance experiment. Covers the
registry override, the request-model fields, and the SQLite `backend`
column (fresh bootstrap + idempotent add to an existing DB).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.db import client as _client

# Capture real DB helpers before conftest's autouse mock replaces them.
_REAL_EXECUTE = _client.execute
_REAL_FETCH_ONE = _client.fetch_one


# ── registry: get_backend(name=...) ─────────────────────────────────────────


def test_get_backend_name_overrides_settings():
    """`name` is used for dispatch even when it disagrees with settings."""
    from src.modules.llm.registry import get_backend

    s = SimpleNamespace(llm_backend="anthropic")
    # A bogus override name must surface in the error — proof it was used.
    with pytest.raises(ValueError, match="totally-bogus"):
        get_backend(s, name="totally-bogus")


def test_get_backend_falls_back_to_settings_when_name_none():
    from src.modules.llm.registry import get_backend

    s = SimpleNamespace(llm_backend="also-bogus")
    with pytest.raises(ValueError, match="also-bogus"):
        get_backend(s, name=None)


def test_backends_constant_matches_config_literal():
    from src.config import Settings
    from src.modules.llm.registry import BACKENDS

    for b in BACKENDS:
        Settings(llm_backend=b)  # raises if BACKENDS drifts from the Literal


# ── model default follows the EFFECTIVE backend ─────────────────────────────


def test_default_model_for_resolves_per_backend():
    """The bug this pins: a paper overriding the backend used to inherit the
    model configured for the process-global backend — so `--backend openrouter`
    on an anthropic server sent a bare `claude-sonnet-4-5` (OpenRouter needs
    the `anthropic/` prefix) and every specialist call failed."""
    from src.config import Settings

    s = Settings(
        llm_backend="anthropic",
        anthropic_model="claude-sonnet-4-5",
        openrouter_model="anthropic/claude-sonnet-4-5",
    )
    assert s.default_model == "claude-sonnet-4-5"
    assert s.default_model_for("openrouter") == "anthropic/claude-sonnet-4-5"
    assert s.default_model_for("anthropic") == "claude-sonnet-4-5"
    # CLI backends: bookkeeping labels, never another family's model id.
    assert s.default_model_for("codex") == "codex-cli-default"
    assert s.default_model_for("gemini") == "gemini-cli-default"


def test_default_model_is_the_global_backends_case():
    """`default_model` must stay exactly `default_model_for(LLM_BACKEND)` —
    one resolution rule, so the two can't drift apart again."""
    from src.config import Settings
    from src.modules.llm.registry import BACKENDS

    for b in BACKENDS:
        s = Settings(llm_backend=b)
        assert s.default_model == s.default_model_for(b)


def test_configured_cli_model_wins_over_placeholder():
    from src.config import Settings

    s = Settings(llm_backend="anthropic", codex_model="gpt-5", gemini_model="gemini-3-pro")
    assert s.default_model_for("codex") == "gpt-5"
    assert s.default_model_for("gemini") == "gemini-3-pro"


# ── request model: backend / model fields ───────────────────────────────────


def test_create_paper_request_backend_model_default_none():
    from src.api.app import CreatePaperRequest

    req = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q"})
    assert req.backend is None and req.model is None


def test_create_paper_request_accepts_backend_model():
    from src.api.app import CreatePaperRequest

    req = CreatePaperRequest.model_validate(
        {"title": "T", "research_question": "Q", "backend": "codex", "model": "gpt-5"}
    )
    assert req.backend == "codex" and req.model == "gpt-5"


# ── SQLite: idempotent column add + fresh-bootstrap column presence ──────────


async def test_ensure_sqlite_columns_adds_missing_idempotently(tmp_path: Path):
    import aiosqlite

    from src.db.client import _ensure_sqlite_columns

    db = tmp_path / "t.db"
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, model TEXT)")
        await _ensure_sqlite_columns(conn, "papers", {"model": "TEXT", "backend": "TEXT"})
        # Second call is a no-op (idempotent).
        await _ensure_sqlite_columns(conn, "papers", {"model": "TEXT", "backend": "TEXT"})
        cur = await conn.execute("PRAGMA table_info(papers)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "backend" in cols and "model" in cols


@pytest.fixture
def sqlite_db(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'papers.db'}")
    monkeypatch.setattr("src.db.client.execute", _REAL_EXECUTE)
    monkeypatch.setattr("src.db.client.fetch_one", _REAL_FETCH_ONE)
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False
    yield
    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


async def test_fresh_bootstrap_has_backend_column_and_round_trips(sqlite_db):
    from src.db.client import execute, fetch_one

    await execute(
        "INSERT INTO papers (id, title, status, backend, model) VALUES (%(i)s, %(t)s, 'idea', %(b)s, %(m)s)",
        {"i": "p1", "t": "T", "b": "claude_code", "m": "sonnet"},
    )
    row = await fetch_one("SELECT backend, model FROM papers WHERE id = %(i)s", {"i": "p1"})
    assert row["backend"] == "claude_code"
    assert row["model"] == "sonnet"
