"""Lane A — POST /api/papers/{id}/resume endpoint.

Pins the resume contract: papers in PAUSED or FAILED state can be
re-kicked, and the runner's state-load skips phases that already produced
their canonical artifacts. This is the recovery path after the circuit
breaker trips.

These tests exercise the route surface (status codes, response shape,
DB transitions) — the actual resume-from-checkpoint logic is covered by
tests/test_pipeline.py::test_resume_skips_completed_phases.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _silence_db(monkeypatch, tmp_path: Path):
    """Patch DB + pipeline spawn so route tests run hermetically."""
    monkeypatch.setattr("src.api.app._run_pipeline", AsyncMock(return_value=None))


def _mock_paper_row(status: str, workspace: Path) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "status": status,
        "workspace": str(workspace),
        "mode": "single_pass",
        "max_cost_usd": 5.0,
    }


def test_resume_404_when_paper_not_found(tmp_path):
    paper_id = str(uuid.uuid4())
    with (
        patch("src.db.client.fetch_one", new=AsyncMock(return_value=None)),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")
    assert resp.status_code == 404, resp.text


def test_resume_409_when_already_running(tmp_path):
    """A paper with an in-flight task cannot be resumed — must cancel first."""
    import asyncio

    from src.api import app as app_mod

    paper_id = str(uuid.uuid4())
    # Insert a still-running task into the registry.

    async def _never_finishes():
        await asyncio.sleep(60)

    loop = asyncio.new_event_loop()
    task = loop.create_task(_never_finishes())
    try:
        app_mod._RUNNING[paper_id] = task
        with (
            patch("src.db.client.fetch_one", new=AsyncMock(return_value=_mock_paper_row("paused", tmp_path))),
            patch("src.db.client.execute", new=AsyncMock(return_value=None)),
        ):
            resp = _client().post(f"/api/papers/{paper_id}/resume")
        assert resp.status_code == 409, resp.text
        assert "already running" in resp.json().get("detail", "")
    finally:
        task.cancel()
        app_mod._RUNNING.pop(paper_id, None)
        loop.close()


def test_resume_409_when_already_completed(tmp_path):
    """Terminal state — nothing to resume."""
    paper_id = str(uuid.uuid4())
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("completed", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", "")
    assert "completed" in detail
    assert "terminal" in detail.lower()


def test_resume_409_when_cancelled(tmp_path):
    paper_id = str(uuid.uuid4())
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("cancelled", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")
    assert resp.status_code == 409


def test_resume_accepts_zombie_revision_status(tmp_path):
    """#7: status=revision but no live runner task → resumable (zombie path).

    Pre-v0.4 this was 409 + manual UPDATE workaround. v0.4 softens the gate
    so the natural workflow (restart server, /resume mid-flight paper) works.
    """
    paper_id = str(uuid.uuid4())
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("revision", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "resuming"
    assert body["from_status"] == "revision"


def test_resume_accepts_zombie_designing_status(tmp_path):
    """#7: status=designing but no live runner task → resumable."""
    paper_id = str(uuid.uuid4())
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("designing", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")
    assert resp.status_code == 200


def test_resume_from_paused_status(tmp_path):
    """Happy path: a PAUSED paper transitions to in_progress and a task is spawned."""
    paper_id = str(uuid.uuid4())
    execute_mock = AsyncMock(return_value=None)
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("paused", tmp_path)),
        ),
        patch("src.db.client.execute", new=execute_mock),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "resuming"
    assert body["from_status"] == "paused"

    # Status update was issued
    assert execute_mock.await_count >= 1
    call_args = execute_mock.await_args_list[0]
    # First positional arg is the SQL string
    assert "UPDATE papers SET status = 'in_progress'" in call_args.args[0]


def test_resume_from_failed_status(tmp_path):
    """FAILED papers are also resumable — operator typically fixes the bug
    and resumes rather than restarting from idea."""
    paper_id = str(uuid.uuid4())
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("failed", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp = _client().post(f"/api/papers/{paper_id}/resume")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "resuming"
    assert body["from_status"] == "failed"
