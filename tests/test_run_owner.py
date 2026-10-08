"""Two e2er servers on one database must not pause each other's runs.

What happened: a study server on port 8280 was running a paper. A second
server, `e2er --port 8300`, started on the same ~/.e2er/papers.db, and its
start-up recovery marked that paper "interrupted — the server stopped while
this paper was running" and paused it. The first server had not stopped.

Now a run records its owner (host, PID, process start time, instance id), and
start-up recovery pauses a paper only when that owner is gone. These tests run
a real second process that claims a paper through the same code a server uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core import run_owner
from src.db import client as _client

_REAL_EXECUTE = _client.execute
_REAL_FETCH_ONE = _client.fetch_one
_REAL_FETCH_ALL = _client.fetch_all

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "papers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setattr("src.db.client.execute", _REAL_EXECUTE)
    monkeypatch.setattr("src.db.client.fetch_one", _REAL_FETCH_ONE)
    monkeypatch.setattr("src.db.client.fetch_all", _REAL_FETCH_ALL)
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False
    yield path
    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


def _run(coro):
    return asyncio.run(coro)


def _paper(status: str = "designing", *, event_age_min: float | None = None) -> str:
    pid = str(uuid.uuid4())

    async def go():
        await _client.execute(
            "INSERT INTO papers (id, title, research_question, status) VALUES (%(id)s, 't', 'q', %(s)s)",
            {"id": pid, "s": status},
        )
        if event_age_min is not None:
            await _client.execute(
                "INSERT INTO pipeline_events (id, paper_id, event_type, created_at) "
                "VALUES (%(e)s, %(id)s, 'specialist_start', datetime('now', %(age)s))",
                {"e": str(uuid.uuid4()), "id": pid, "age": f"-{event_age_min} minutes"},
            )

    _run(go())
    return pid


def _status(db: Path, pid: str) -> str:
    with sqlite3.connect(db) as c:
        return c.execute("SELECT status FROM papers WHERE id = ?", (pid,)).fetchone()[0]


def _owner(db: Path, pid: str) -> dict | None:
    with sqlite3.connect(db) as c:
        raw = c.execute("SELECT run_owner FROM papers WHERE id = ?", (pid,)).fetchone()[0]
    return json.loads(raw) if raw else None


def _other_server(db: Path, paper_id: str) -> subprocess.Popen:
    """A second e2er process that claims ``paper_id`` the way a server does when a run starts."""
    code = (
        "import asyncio, sys, time\n"
        "from src.core import run_owner\n"
        "asyncio.run(run_owner.claim(sys.argv[1], 8280))\n"
        "print('ready', flush=True)\n"
        "time.sleep(120)\n"
    )
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
    proc = subprocess.Popen(
        [sys.executable, "-c", code, paper_id], cwd=REPO, env=env, stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    return proc


def _reconcile() -> None:
    from src.api.app import _reconcile_orphans

    _run(_reconcile_orphans())


# ── the incident ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name != "posix", reason="PID checks are POSIX-only; elsewhere the heartbeat decides")
def test_starting_a_second_server_leaves_the_first_servers_run_alone(db: Path, caplog):
    running = _paper("designing")
    other = _other_server(db, running)
    try:
        owner = _owner(db, running)
        assert owner and owner["pid"] == other.pid and owner["instance"] != run_owner.INSTANCE_ID
        assert owner["port"] == 8280

        with caplog.at_level("INFO"):
            _reconcile()  # this process plays the server that just started

        assert _status(db, running) == "designing"
        assert f"running on another e2er process (PID {other.pid}, port 8280)" in caplog.text
    finally:
        other.kill()
        other.wait()

    # Once that process is gone, the same paper is stranded and is recovered.
    _reconcile()
    assert _status(db, running) == "paused"
    assert _owner(db, running) is None


@pytest.mark.skipif(os.name != "posix", reason="PID checks are POSIX-only")
def test_a_reused_pid_does_not_keep_a_dead_run_alive(db: Path):
    """The owner's PID now belongs to another process (a different start time)."""
    pid = _paper("revision")
    fake = {**run_owner.this_owner(8280), "instance": "an-older-server", "started": "Thu Jan  1 00:00:00 1970"}
    fake["pid"] = os.getppid()  # a live process that is certainly not the owner
    _run(_client.execute("UPDATE papers SET run_owner = %(o)s WHERE id = %(id)s", {"o": json.dumps(fake), "id": pid}))
    _reconcile()
    assert _status(db, pid) == "paused"


def test_a_dead_owner_is_recovered(db: Path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    pid = _paper("in_progress")
    dead = {**run_owner.this_owner(8280), "instance": "gone", "pid": proc.pid, "started": None}
    _run(_client.execute("UPDATE papers SET run_owner = %(o)s WHERE id = %(id)s", {"o": json.dumps(dead), "id": pid}))
    _reconcile()
    assert _status(db, pid) == "paused"


# ── rows from an older e2er, with no owner recorded ──────────────────────────


def test_a_legacy_row_with_recent_activity_is_left_alone(db: Path, caplog):
    recent = _paper("designing", event_age_min=1)
    with caplog.at_level("INFO"):
        _reconcile()
    assert _status(db, recent) == "designing"
    assert "may be running it" in caplog.text


def test_a_legacy_row_that_went_quiet_is_paused_as_before(db: Path):
    quiet = _paper("designing", event_age_min=30)
    never = _paper("review")
    _reconcile()
    assert _status(db, quiet) == "paused"
    assert _status(db, never) == "paused"


def test_finished_and_paused_papers_are_never_touched(db: Path):
    done = _paper("completed")
    paused = _paper("paused")
    _reconcile()
    assert _status(db, done) == "completed" and _status(db, paused) == "paused"


# ── owner state rules ────────────────────────────────────────────────────────


def test_owner_state_rules():
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    fresh, stale = now - timedelta(minutes=1), now - timedelta(hours=1)
    me = run_owner.this_owner()
    assert run_owner.owner_state(me, None) == "mine"
    assert run_owner.owner_state(None, fresh) == "unknown"
    far = {"instance": "x", "host": "another-machine", "pid": 1}
    assert run_owner.owner_state(far, fresh, now) == "alive"
    assert run_owner.owner_state(far, stale, now) == "gone"
    if os.name == "posix":
        parent = {"instance": "x", "host": me["host"], "pid": os.getppid(), "started": None}
        assert run_owner.owner_state(parent, None) == "alive"


def test_heartbeat_and_release(db: Path):
    pid = _paper("designing")
    _run(run_owner.claim(pid))
    assert _owner(db, pid)["instance"] == run_owner.INSTANCE_ID
    with sqlite3.connect(db) as c:
        c.execute("UPDATE papers SET heartbeat_at = '2000-01-01 00:00:00' WHERE id = ?", (pid,))
    _run(run_owner.beat([pid]))
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT heartbeat_at FROM papers WHERE id = ?", (pid,)).fetchone()[0] > "2026"
    # Release only forgets this process as the owner, never another's claim.
    other = {**run_owner.this_owner(), "instance": "someone-else"}
    other_pid = _paper("designing")
    _run(
        _client.execute(
            "UPDATE papers SET run_owner = %(o)s WHERE id = %(id)s", {"o": json.dumps(other), "id": other_pid}
        )
    )
    _run(run_owner.release(pid))
    _run(run_owner.release(other_pid))
    assert _owner(db, pid) is None
    assert _owner(db, other_pid)["instance"] == "someone-else"


def test_heartbeat_loop_beats_only_live_tasks(monkeypatch):
    beaten: list[list[str]] = []

    async def _beat(ids):
        beaten.append(ids)

    monkeypatch.setattr(run_owner, "beat", _beat)

    class _Task:
        def __init__(self, done):
            self._d = done

        def done(self):
            return self._d

    async def go():
        loop = asyncio.create_task(run_owner.heartbeat_loop({"a": _Task(False), "b": _Task(True)}, interval=0.01))
        await asyncio.sleep(0.05)
        loop.cancel()

    _run(go())
    assert beaten and all(ids == ["a"] for ids in beaten)


# ── the dashboard ────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name != "posix", reason="PID checks are POSIX-only")
def test_dashboard_shows_running_elsewhere_and_refuses_resume_and_cancel(db: Path):
    from src.api.app import app

    running = _paper("designing")
    other = _other_server(db, running)
    try:
        c = TestClient(app)
        live = c.get(f"/htmx/papers/{running}/live").text
        assert "This run is working in another e2er window" in live
        assert f"PID {other.pid}, port 8280" in live
        assert "/resume" not in live and "/cancel" not in live
        assert "http://127.0.0.1:8280/papers/" in live

        r = c.post(f"/api/papers/{running}/resume")
        assert r.status_code == 409 and "the dashboard on port 8280" in r.json()["detail"]
        r = c.post(f"/api/papers/{running}/cancel")
        assert r.status_code == 409 and "Follow or stop it there" in r.json()["detail"]
    finally:
        other.kill()
        other.wait()
    time.sleep(0.05)
    live = TestClient(app).get(f"/htmx/papers/{running}/live").text
    assert "This run is working in another e2er window" not in live
