"""First-run cost guardrail.

Until a paper at (model, methodology, mode) has reached status='completed',
the cost cap is limited to $1 unless the request explicitly acknowledges.

This is the proactive defense against "spend $8 chasing a bug on the first
live run with this combination" — the failure mode that motivated this
guardrail in the first place. Tests don't predict next-time spend; this
guardrail caps it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from src.api.app import app

    return TestClient(app)


def _payload(**overrides):
    base = {
        "title": "T",
        "research_question": "RQ?",
        "mode": "iterative",
        "methodology": "empirical",
        "max_cost_usd": 25.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Behaviour 1: unproven tuple + cap > $1 + no ack → 400
# ---------------------------------------------------------------------------


def test_unproven_tuple_rejects_high_cap_without_ack(tmp_path, monkeypatch):
    """First-of-anything must not be allowed to spend $25."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    from src.config import get_settings

    get_settings.cache_clear()

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = _client().post("/api/papers", json=_payload(max_cost_usd=25.0))

    assert resp.status_code == 400, f"expected 400 on unproven+high-cap, got {resp.status_code}: {resp.text}"
    body = resp.text.lower()
    assert "first paper" in body or "unproven" in body
    assert "acknowledge" in body, "rejection must tell the user how to override"


# ---------------------------------------------------------------------------
# Behaviour 2: unproven tuple + cap <= $1 → allowed, cap honored
# ---------------------------------------------------------------------------


def test_unproven_tuple_accepts_low_cap(tmp_path, monkeypatch):
    """Cheap first runs are the easy path — no acknowledgement required."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    from src.config import get_settings

    get_settings.cache_clear()

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = _client().post("/api/papers", json=_payload(max_cost_usd=0.50))

    assert resp.status_code == 200, f"expected 200 on unproven+low-cap, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Behaviour 3: unproven tuple + ack=true → allowed at the higher cap
# ---------------------------------------------------------------------------


def test_unproven_tuple_with_ack_allows_high_cap(tmp_path, monkeypatch):
    """Explicit acknowledgement is the override path: request goes through
    AND the effective cap is the requested value, not the unproven floor.

    Regression for May 2026 NFT-paper run #4: ack-with-cap=$5 ran the
    pipeline but the runner was still given cap=$1, so the run died on
    BudgetExceededError at $1.33."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    from src.config import get_settings

    get_settings.cache_clear()

    captured: dict = {}

    async def capture_execute(sql, params=None):
        # Capture the INSERT INTO papers row to verify the persisted cap.
        if params and "cap" in params:
            captured["cap"] = params["cap"]

    with (
        patch("src.db.client.execute", side_effect=capture_execute),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = _client().post(
            "/api/papers",
            json=_payload(max_cost_usd=25.0, acknowledge_unproven_tuple=True),
        )

    assert resp.status_code == 200, f"ack should override: {resp.text}"
    assert captured.get("cap") == 25.0, (
        f"ack=true must raise the effective cap to the requested value, not just "
        f"bypass the rejection. Got persisted cap = {captured.get('cap')}, expected 25.0."
    )


# ---------------------------------------------------------------------------
# Behaviour 4: proven tuple → high cap allowed without ack
# ---------------------------------------------------------------------------


def test_proven_tuple_allows_high_cap_without_ack(tmp_path, monkeypatch):
    """Once a paper at the same tuple has completed, full caps are allowed."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    from src.config import get_settings

    get_settings.cache_clear()

    # fetch_one returns a row → proven tuple
    proven_row = {"?column?": 1}

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=proven_row),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = _client().post("/api/papers", json=_payload(max_cost_usd=25.0))

    assert resp.status_code == 200, f"proven tuple should allow the high cap without ack: {resp.text}"


# ---------------------------------------------------------------------------
# Behaviour 5: DB unavailable → fail safe (treat as unproven)
# ---------------------------------------------------------------------------


def test_db_unavailable_treats_tuple_as_unproven(tmp_path, monkeypatch):
    """If the DB-side proof check fails, default to unproven (cap forced)
    rather than fail open. The user can still override with ack=true."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    from src.config import get_settings

    get_settings.cache_clear()

    async def _boom(*a, **kw):
        raise RuntimeError("db is on fire")

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", side_effect=_boom),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = _client().post("/api/papers", json=_payload(max_cost_usd=25.0))

    assert resp.status_code == 400, (
        f"when DB is down we cannot prove the tuple — must reject high caps without ack; got {resp.status_code}"
    )
