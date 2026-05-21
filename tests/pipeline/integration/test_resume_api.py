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


# ---------------------------------------------------------------------------
# v0.5: optional max_cost_usd body parameter
# ---------------------------------------------------------------------------


def test_resume_with_raised_cap_persists_new_value(tmp_path):
    """v0.5: POST /resume with {max_cost_usd: 15} must persist the new cap
    on the papers row and pass it to the runner. Pre-v0.5 the endpoint
    silently ignored the body and the row's old cap was used — the exact
    UX gap that surfaced during the 2026-05-20 live validation."""
    from src.api import app as app_mod

    paper_id = str(uuid.uuid4())
    execute_mock = AsyncMock(return_value=None)
    run_pipeline_mock = AsyncMock(return_value=None)

    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("paused", tmp_path)),
        ),
        patch("src.db.client.execute", new=execute_mock),
        patch.object(app_mod, "_run_pipeline", run_pipeline_mock),
    ):
        resp = _client().post(
            f"/api/papers/{paper_id}/resume",
            json={"max_cost_usd": 15.0},
        )

    assert resp.status_code == 200, resp.text

    # 1. The UPDATE persists the new cap on the row, atomically with
    #    the status reset. Without this, the runner reads the old cap
    #    from the DB on next budget check.
    update_call = execute_mock.await_args_list[0]
    sql, params = update_call.args
    assert "max_cost_usd" in sql, "UPDATE must set max_cost_usd on the row, not just the status"
    assert params["cap"] == 15.0, f"new cap not persisted; saw {params}"

    # 2. The runner is invoked with the new cap (not the row's old 5.0).
    assert run_pipeline_mock.await_count == 1
    runner_kwargs = run_pipeline_mock.await_args
    # _run_pipeline signature: (paper_id, workspace, mode, cap, methodology)
    cap_arg = runner_kwargs.args[3]
    assert cap_arg == 15.0, f"runner received old cap {cap_arg}, expected 15.0"


def test_resume_without_body_uses_row_cap(tmp_path):
    """Backwards compat: POST /resume with no body (or empty body) preserves
    the pre-v0.5 behaviour of using the cap already on the row."""
    from src.api import app as app_mod

    paper_id = str(uuid.uuid4())
    run_pipeline_mock = AsyncMock(return_value=None)

    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("paused", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
        patch.object(app_mod, "_run_pipeline", run_pipeline_mock),
    ):
        # Two ways callers omit the cap raise: no body at all, or empty {}.
        resp_no_body = _client().post(f"/api/papers/{paper_id}/resume")
        resp_empty = _client().post(f"/api/papers/{paper_id}/resume", json={})

    assert resp_no_body.status_code == 200
    assert resp_empty.status_code == 200
    # Runner was called with the row's existing cap (5.0 from
    # _mock_paper_row) both times.
    for call in run_pipeline_mock.await_args_list:
        cap_arg = call.args[3]
        assert cap_arg == 5.0, f"runner received unexpected cap {cap_arg}; row's value is 5.0"


def test_resume_rejects_non_positive_cap(tmp_path):
    """Zero or negative caps would re-pause immediately — reject at the
    API layer rather than letting the operator footgun themselves."""
    paper_id = str(uuid.uuid4())
    with (
        patch(
            "src.db.client.fetch_one",
            new=AsyncMock(return_value=_mock_paper_row("paused", tmp_path)),
        ),
        patch("src.db.client.execute", new=AsyncMock(return_value=None)),
    ):
        resp_zero = _client().post(f"/api/papers/{paper_id}/resume", json={"max_cost_usd": 0.0})
        resp_negative = _client().post(f"/api/papers/{paper_id}/resume", json={"max_cost_usd": -1.0})

    assert resp_zero.status_code == 400, resp_zero.text
    assert resp_negative.status_code == 400, resp_negative.text
    assert "positive" in resp_zero.json()["detail"].lower()
