"""Lane A — failure-bundle + data-queries observability endpoints.

These pin the contract that /diagnose-run depends on. Both endpoints
must be tolerant of missing data (workspace not created yet, DB tables
absent, paper not found) and return structured responses, not 500s.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.api.app import app


def _client() -> TestClient:
    return TestClient(app)


def _paper_row(paper_id: str) -> dict:
    return {
        "id": paper_id,
        "title": "Test paper",
        "status": "paused",
        "last_error": "Circuit breaker: data_analyst failed 3 times in a row. Last error: Allium degraded",
        "mode": "single_pass",
        "methodology": "empirical",
        "max_cost_usd": 5.0,
        "research_question": "Does X affect Y?",
        "workspace": "/tmp/test-ws",
        "created_at": "2026-05-16T10:00:00Z",
    }


def _event(event_type: str, payload: dict | None = None) -> dict:
    return {
        "event_type": event_type,
        "stage": None,
        "specialist": None,
        "payload": payload or {},
        "created_at": "2026-05-16T10:05:00Z",
    }


def _contrib(specialist: str, success: bool, error_msg: str | None = None) -> dict:
    return {
        "specialist": specialist,
        "output_file": "data_summary.md" if specialist == "data_analyst" else "",
        "success": success,
        "error_msg": error_msg,
        "usage_tokens": 1000,
        "cost_usd": 0.0,
        "duration_sec": 30.0,
        "created_at": "2026-05-16T10:05:00Z",
    }


# ---------- failure-bundle ----------


def test_failure_bundle_404_when_paper_not_found():
    paper_id = str(uuid.uuid4())
    with patch("src.db.client.fetch_one", new=AsyncMock(return_value=None)):
        resp = _client().get(f"/api/papers/{paper_id}/failure-bundle")
    assert resp.status_code == 404


def test_failure_bundle_returns_full_structure(tmp_path):
    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()
    (workspace / "data_summary.md").write_text("# Data Summary\n\nAllium degraded.")
    (workspace / "paper_plan.md").write_text("# Plan")

    events = [
        _event("circuit_breaker_tripped", {"specialist": "data_analyst", "attempts": 3}),
    ]
    contributions = [
        _contrib("data_analyst", False, error_msg="Allium 429 retries exhausted; data layer unrecoverable."),
        _contrib("idea_developer", True),
    ]

    paper = _paper_row(paper_id)
    paper["workspace"] = str(workspace)

    with (
        patch("src.db.client.fetch_one", new=AsyncMock(return_value=paper)),
        patch("src.db.client.fetch_all", new=AsyncMock(side_effect=[events, contributions])),
        # Patch where get_settings is actually called from inside app.py —
        # patching src.config.get_settings doesn't affect the already-imported
        # reference in app.py.
        patch("src.api.app.get_settings") as gs,
    ):
        s = gs.return_value
        s.workspace_root = str(tmp_path)
        resp = _client().get(f"/api/papers/{paper_id}/failure-bundle")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level fields
    assert body["paper_id"] == paper_id
    assert body["status"] == "paused"
    assert "Allium degraded" in body["last_error"]
    assert body["methodology"] == "empirical"

    # Events with full payload
    assert len(body["events"]) == 1
    assert body["events"][0]["event_type"] == "circuit_breaker_tripped"
    assert body["events"][0]["payload"]["attempts"] == 3

    # Specialist drill-down with full untruncated error
    specs = {s["specialist"]: s for s in body["specialists"]}
    assert "data_analyst" in specs
    assert "Allium 429 retries exhausted" in specs["data_analyst"]["error_msg"]
    assert specs["data_analyst"]["success"] is False

    # Workspace artifact listing — data_summary.md present, paper_plan.md
    # present, others (like econometric_spec.md, paper_draft.tex) missing.
    artifacts = {a["specialist"]: a for a in body["artifacts"]}
    assert artifacts["data_analyst"]["exists"] is True
    assert artifacts["data_analyst"]["size_bytes"] > 0
    assert "data_analyst" not in body["missing_canonical_artifacts"]
    # paper_drafter should be in the missing list — its artifact is paper_draft.tex
    # which we didn't create.
    assert "paper_drafter" in body["missing_canonical_artifacts"]

    # data_summary excerpt content
    assert "Allium degraded" in body["data_summary_excerpt"]


def test_failure_bundle_400_on_invalid_uuid():
    """Path validation should reject non-UUIDs (404 per existing convention)."""
    resp = _client().get("/api/papers/not-a-uuid/failure-bundle")
    assert resp.status_code in (400, 404), f"expected 4xx, got {resp.status_code}"


# ---------- data-queries ----------


def test_data_queries_400_on_invalid_uuid():
    resp = _client().get("/api/papers/not-a-uuid/data-queries")
    assert resp.status_code in (400, 404)


def test_data_queries_returns_summary_when_table_missing(tmp_path):
    """If the data_query_records table doesn't exist (data module disabled),
    return an empty result with the error string — not a 500."""
    paper_id = str(uuid.uuid4())

    with patch("src.db.client.fetch_all", new=AsyncMock(side_effect=RuntimeError("no such table"))):
        resp = _client().get(f"/api/papers/{paper_id}/data-queries")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["paper_id"] == paper_id
    assert body["queries"] == []
    assert "no such table" in body.get("error", "")


def test_data_queries_summary_rolls_up_counts():
    paper_id = str(uuid.uuid4())
    fake_rows = [
        {
            "id": "q1",
            "specialist": "data_analyst",
            "query_sql": "SELECT 1",
            "query_type": "feasibility",
            "fields_requested": ["one"],
            "aggregation_level": "transaction",
            "estimated_rows": 100,
            "actual_rows": 3,
            "validation_status": "approved",
            "validation_errors": None,
            "approval_status": "approved",
            "approval_note": None,
            "executed_at": "2026-05-16T10:01:00Z",
            "created_at": "2026-05-16T10:00:00Z",
        },
        {
            "id": "q2",
            "specialist": "data_analyst",
            "query_sql": "SELECT *",
            "query_type": "feasibility",
            "fields_requested": [],
            "aggregation_level": "transaction",
            "estimated_rows": 100,
            "actual_rows": 0,
            "validation_status": "rejected",
            "validation_errors": "no SELECT *",
            "approval_status": "rejected",
            "approval_note": None,
            "executed_at": None,
            "created_at": "2026-05-16T10:02:00Z",
        },
    ]
    with patch("src.db.client.fetch_all", new=AsyncMock(return_value=fake_rows)):
        resp = _client().get(f"/api/papers/{paper_id}/data-queries")

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total"] == 2
    assert body["summary"]["executed"] == 1
    assert body["summary"]["rows_returned"] == 3
    assert body["summary"]["by_validation_status"]["approved"] == 1
    assert body["summary"]["by_validation_status"]["rejected"] == 1
