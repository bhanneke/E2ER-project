"""Lane A — closes #5: graceful shutdown transitions in-flight papers to PAUSED.

Pre-v0.4: when uvicorn received SIGTERM, runner tasks died without their
DB row being touched. Papers stuck at `designing` / `revision` / etc.
became zombies — they appeared active in the dashboard but no actual
runner existed.

Fix: a FastAPI ``@app.on_event("shutdown")`` hook cancels each running
task and transitions the paper to PAUSED (unless state.json says it
genuinely completed, in which case we leave it alone).

These tests exercise the hook directly. The full SIGTERM path is
infrastructure-coupled; we trust uvicorn to invoke the shutdown event.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

import pytest

from src.api import app as app_module


async def _never_finishes():
    await asyncio.sleep(60)


@pytest.mark.asyncio
async def test_shutdown_cancels_running_tasks_and_marks_paused(tmp_path, monkeypatch):
    """A running paper → shutdown hook → task cancelled + status='paused' in DB."""
    paper_id = str(uuid.uuid4())

    # Make a fake workspace WITHOUT a complete state.json so the hook
    # treats this as in-flight (not genuinely completed).
    ws = tmp_path / paper_id
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": paper_id, "mode": "iterative"}))

    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "workspace_root": str(tmp_path),
                "llm_backend": "mock",
                "default_model": "mock",
                "data_module_enabled": False,
                "literature_kb_enabled": False,
                "github_enabled": False,
                "default_max_cost_usd": 5.0,
            },
        )(),
    )

    # Inject a long-running task into _RUNNING that mimics a real runner.
    task = asyncio.create_task(_never_finishes())
    app_module._RUNNING[paper_id] = task

    executed_sql: list[tuple[str, dict]] = []

    async def _capture_execute(sql, params=None):
        executed_sql.append((sql, params or {}))

    try:
        with patch("src.db.client.execute", new=_capture_execute):
            await app_module._graceful_shutdown_runners()
    finally:
        app_module._RUNNING.pop(paper_id, None)

    # The task should have been cancelled.
    assert task.cancelled() or task.done(), "shutdown hook must cancel running tasks"

    # An UPDATE must have been issued setting status='paused' for this paper.
    paused_updates = [(sql, p) for sql, p in executed_sql if "status = 'paused'" in sql and p.get("id") == paper_id]
    assert paused_updates, (
        f"shutdown hook must UPDATE papers SET status='paused' for in-flight paper, "
        f"got SQL: {[s for s, _ in executed_sql]}"
    )


@pytest.mark.asyncio
async def test_shutdown_skips_genuinely_completed_papers(tmp_path, monkeypatch):
    """If state.json shows last_status='completed', shutdown must NOT downgrade
    to paused — the runner just hadn't gotten to write the DB yet (the #6
    case, before fix). Belt-and-suspenders: shutdown should still leave
    these alone in case any survive.
    """
    paper_id = str(uuid.uuid4())

    ws = tmp_path / paper_id
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": paper_id, "mode": "iterative"}))
    # PipelineState with every stage complete + last_status=completed
    from src.core.pipeline.state import PipelineState

    state = PipelineState(paper_id=paper_id, mode="iterative")
    for stage in ("initial", "iterative", "self_attack", "polish", "review", "revision", "replication"):
        state.mark_complete(stage)
    state.last_status = "completed"
    state.save(ws)

    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "workspace_root": str(tmp_path),
                "llm_backend": "mock",
                "default_model": "mock",
                "data_module_enabled": False,
                "literature_kb_enabled": False,
                "github_enabled": False,
                "default_max_cost_usd": 5.0,
            },
        )(),
    )

    task = asyncio.create_task(_never_finishes())
    app_module._RUNNING[paper_id] = task

    executed_sql: list[tuple[str, dict]] = []

    async def _capture_execute(sql, params=None):
        executed_sql.append((sql, params or {}))

    try:
        with patch("src.db.client.execute", new=_capture_execute):
            await app_module._graceful_shutdown_runners()
    finally:
        app_module._RUNNING.pop(paper_id, None)

    # No 'paused' update should have been issued for this paper —
    # state.json says it's completed.
    paused_for_this_paper = [
        (sql, p) for sql, p in executed_sql if "status = 'paused'" in sql and p.get("id") == paper_id
    ]
    assert not paused_for_this_paper, (
        f"shutdown should not downgrade genuinely-completed papers to paused. SQL: {executed_sql}"
    )


@pytest.mark.asyncio
async def test_shutdown_is_noop_when_no_running_papers():
    """No tasks in _RUNNING → no DB calls, no errors."""
    app_module._RUNNING.clear()
    executed_sql: list[tuple[str, dict]] = []

    async def _capture_execute(sql, params=None):
        executed_sql.append((sql, params or {}))

    with patch("src.db.client.execute", new=_capture_execute):
        await app_module._graceful_shutdown_runners()

    assert executed_sql == []
