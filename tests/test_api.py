"""API endpoint tests — no live DB or LLM required."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture
def client(tmp_path: Path):
    """TestClient with workspace rooted in a temp directory."""
    with patch("src.config.get_settings") as mock_settings:
        settings = mock_settings.return_value
        settings.workspace_root = str(tmp_path / "workspaces")
        settings.github_enabled = False
        settings.data_module_enabled = False
        settings.allium_api_key = None
        settings.llm_backend = "anthropic"
        settings.default_model = "claude-3-5-sonnet-20241022"
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "e2er-v3"


# ---------------------------------------------------------------------------
# POST /api/papers
# ---------------------------------------------------------------------------


def test_create_paper_returns_paper_id(client, tmp_path):
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/papers",
            json={
                "title": "DeFi Liquidity Provision",
                "research_question": "How does concentrated liquidity affect price discovery?",
                "datasets": ["uniswap_v3_swaps"],
                "mode": "single_pass",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "paper_id" in body
    assert body["title"] == "DeFi Liquidity Provision"
    assert body["status"] == "idea"
    assert "workspace" in body


def test_create_paper_workspace_created(client, tmp_path):
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/papers",
            json={"title": "Test", "research_question": "Test RQ?"},
        )

    assert resp.status_code == 200
    workspace = Path(resp.json()["workspace"])
    assert workspace.exists(), "Workspace directory should be created by the endpoint"
    assert (workspace / "manifest.json").exists(), "manifest.json should be written"


def test_create_paper_manifest_content(client, tmp_path):
    import json

    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/papers",
            json={
                "title": "Bitcoin Volatility",
                "research_question": "Did the ETF approval reduce BTC volatility?",
                "mode": "iterative",
            },
        )

    manifest = json.loads(Path(resp.json()["workspace"]).joinpath("manifest.json").read_text())
    assert manifest["title"] == "Bitcoin Volatility"
    assert manifest["mode"] == "iterative"
    assert manifest["current_stage"] == "idea"


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------


def test_list_papers_empty(client):
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=[]):
        resp = client.get("/api/papers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_papers_returns_rows(client):
    rows = [{"id": "abc", "title": "Paper A", "status": "completed", "created_at": "2026-01-01"}]
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=rows):
        resp = client.get("/api/papers")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["title"] == "Paper A"


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}
# ---------------------------------------------------------------------------


def test_get_paper_not_found(client):
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        resp = client.get("/api/papers/nonexistent-id")
    assert resp.status_code == 404


def test_get_paper_found(client):
    row = {
        "id": "abc-123",
        "title": "Test",
        "status": "completed",
        "research_question": "Test RQ?",
        "workspace": "/tmp/test",
        "mode": "single_pass",
        "github_repo": None,
        "created_at": "2026-01-01",
    }
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row):
        resp = client.get("/api/papers/abc-123")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test"
    assert resp.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}/artifacts
# ---------------------------------------------------------------------------


def test_list_artifacts_workspace_not_found(client):
    with patch("src.config.get_settings") as mock_settings:
        mock_settings.return_value.workspace_root = "/nonexistent/path"
        resp = client.get("/api/papers/missing-paper/artifacts")
    assert resp.status_code == 404


def test_list_artifacts_returns_file_list(client, tmp_path):
    paper_id = "test-paper-id"
    ws = tmp_path / "workspaces" / paper_id
    ws.mkdir(parents=True)
    (ws / "paper_plan.md").write_text("# Plan")
    (ws / "paper_draft.tex").write_text("\\documentclass{article}")
    (ws / ".gitignore").write_text("*.aux")  # hidden files excluded

    with patch("src.config.get_settings") as mock_settings:
        mock_settings.return_value.workspace_root = str(tmp_path / "workspaces")
        resp = client.get(f"/api/papers/{paper_id}/artifacts")

    assert resp.status_code == 200
    body = resp.json()
    assert "files" in body
    files = body["files"]
    assert "paper_plan.md" in files
    assert "paper_draft.tex" in files
    assert ".gitignore" not in files  # hidden files excluded


# ---------------------------------------------------------------------------
# POST /api/queries/{query_id}/approve
# ---------------------------------------------------------------------------


def test_approve_query(client):
    with patch("src.db.client.execute", new_callable=AsyncMock):
        resp = client.post(
            "/api/queries/query-uuid-123/approve",
            json={"approved": True, "note": "Looks good"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["query_id"] == "query-uuid-123"


def test_reject_query(client):
    with patch("src.db.client.execute", new_callable=AsyncMock):
        resp = client.post(
            "/api/queries/query-uuid-456/approve",
            json={"approved": False, "note": "Query too broad"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}/pending-queries
# ---------------------------------------------------------------------------


def test_pending_queries_empty(client):
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=[]):
        resp = client.get("/api/papers/paper-abc/pending-queries")
    assert resp.status_code == 200
    assert resp.json() == []


def test_pending_queries_returns_rows(client):
    rows = [
        {
            "id": "q1",
            "query_sql": "SELECT tx_hash FROM ...",
            "query_type": "production",
            "fields_requested": '["tx_hash"]',
            "aggregation_level": "transaction",
            "estimated_rows": 1000,
            "created_at": "2026-01-01",
            "approval_request_id": "ar1",
            "approval_status": "pending",
        }
    ]
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=rows):
        resp = client.get("/api/papers/paper-abc/pending-queries")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["approval_status"] == "pending"
