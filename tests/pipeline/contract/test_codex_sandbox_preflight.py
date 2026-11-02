"""Codex without an extra writable folder, its sandbox checked before the first specialist, no blind retries.

Tester report 2026-11-02 (codex-cli 0.165/0.166, Windows and Ubuntu): every specialist
returned "success" without writing a file, failed its contract three times, and the run
paused after about ten specialists and one to two million tokens. On Windows the cause
was e2er's ``--add-dir <run database folder>`` (openai/codex#30009). Pinned here: no
``--add-dir`` ever; the wrappers' audit rows reach the run database through the call's
journal; a test write before the first specialist stops a run whose sandbox refuses; a
call the sandbox refused pauses the run after one attempt. Every Codex process is faked.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import get_settings
from src.db import client as _db
from src.modules.llm import codex
from src.modules.llm.base import ToolLoopResult, run_preflight
from src.modules.llm.codex import SANDBOX_CHECK_FILE, SANDBOX_CHECK_TEXT, CodexBackend
from src.modules.llm.plan_limit import PlanLimitReachedError, SandboxBlockedError

_USAGE = {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}
_DONE = {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}
_REFUSED_PATCH = {
    "type": "item.completed",
    "item": {"type": "file_change", "status": "failed", "changes": [{"path": "paper_plan.md", "kind": "add"}]},
}


_REAL = (_db.execute, _db.fetch_one, _db.fetch_all)


def _events(*evs: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in evs) + "\n").encode()


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for k in ("CODEX_SANDBOX", "CODEX_ALLOW_FULL_ACCESS", "CODEX_MODEL", "CODEX_PATH", codex.SKIP_SANDBOX_CHECK):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WORKSPACE_ROOT", "workspaces")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db' / 'papers.db'}")
    monkeypatch.setattr(codex, "cli_version", lambda _path: "codex-cli 0.166.0")
    monkeypatch.setattr(codex, "_SANDBOX_PASSED", set())
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _fake_codex(stdout: bytes, *, write: str | None = None, returncode: int = 0):
    """A `codex exec` that answers ``stdout`` and, with ``write``, writes the check file in its -C folder."""
    calls: list[dict] = []

    async def _exec(*args, **kwargs):
        cmd = list(args)
        calls.append({"cmd": cmd, "env": kwargs.get("env") or {}})
        if write is not None:
            (Path(cmd[cmd.index("-C") + 1]) / SANDBOX_CHECK_FILE).write_text(write + "\n", encoding="utf-8")
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = returncode

        async def _comm(input: bytes = b""):
            return (stdout, b"")

        proc.communicate = _comm
        return proc

    return _exec, calls


# ── no extra writable folder ─────────────────────────────────────────────────


@pytest.mark.parametrize("sandbox", ["workspace-write", "read-only"])
@pytest.mark.parametrize("network", ["true", "false"])
def test_the_command_line_never_gives_an_extra_writable_folder(cfg, sandbox, network):
    cfg.setenv("CODEX_SANDBOX", sandbox)
    cfg.setenv("CODEX_NETWORK_ACCESS", network)
    get_settings.cache_clear()
    cmd = CodexBackend().build_cmd(cwd="/w", last_message_file="/f")
    assert "--add-dir" not in cmd and not any("writable_roots" in part for part in cmd)


async def test_a_specialist_call_imports_the_wrappers_journal(cfg, tmp_path):
    """The wrapper writes the call's journal in the workspace; after the call the rows are in the run database."""
    from src.db import client as _client

    cfg.setattr(_client, "_backend", "")
    cfg.setattr(_client, "_sqlite_bootstrapped", False)
    # The real database functions (conftest fakes them for every test).
    cfg.setattr("src.db.client.execute", _REAL[0])
    cfg.setattr("src.db.client.fetch_one", _REAL[1])
    cfg.setattr("src.db.client.fetch_all", _REAL[2])
    pid = str(uuid.uuid4())
    await _client.execute(
        "INSERT INTO papers (id, title, research_question, status) VALUES (%(id)s, 't', 'q', 'designing')", {"id": pid}
    )
    (tmp_path / "workspaces" / pid).mkdir(parents=True)
    rid = str(uuid.uuid4())
    seen: dict = {}

    async def _exec(*args, **kwargs):
        cmd, env = list(args), kwargs["env"]
        journal = Path(env["E2ER_AUDIT_JOURNAL"])
        seen["journal"] = journal
        assert journal.parent == Path(cmd[cmd.index("-C") + 1]), "the journal lies in the workspace"
        line = {"op": "query", "id": rid, "paper_id": pid, "specialist": "data_analyst", "query_sql": "SELECT 1",
                "query_type": "feasibility", "fields_requested": [], "aggregation_level": "local_data_db",
                "estimated_rows": None}  # fmt: skip
        journal.write_text(json.dumps(line) + "\n", encoding="utf-8")
        proc = MagicMock()
        proc.pid, proc.returncode = 4242, 0

        async def _comm(input: bytes = b""):
            return (_events(_DONE, _USAGE), b"")

        proc.communicate = _comm
        return proc

    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=_exec):
        result = await CodexBackend().tool_loop(
            system="s", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None,
            paper_id=pid, specialist="data_analyst",
        )  # fmt: skip
    assert result.success
    assert not seen["journal"].exists(), "the journal is removed after the import"
    with sqlite3.connect(tmp_path / "db" / "papers.db") as c:
        assert c.execute("SELECT id, paper_id FROM data_query_records").fetchall() == [(rid, pid)]


# ── the sandbox check before the first specialist ───────────────────────────


async def test_the_check_passes_when_codex_writes_the_file_and_is_kept_for_the_session(cfg):
    fake, calls = _fake_codex(_events(_DONE, _USAGE), write=SANDBOX_CHECK_TEXT)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        ok, detail = await CodexBackend().check_sandbox()
        assert ok is True and "codex-cli 0.166.0" in detail
        await CodexBackend().preflight()  # passes, from the session's record
    assert len(calls) == 1, "one test call per Codex version and sandbox mode in a session"
    cmd = calls[0]["cmd"]
    folder = Path(cmd[cmd.index("-C") + 1])
    assert not folder.exists(), "the temporary folder is removed"
    assert "--add-dir" not in cmd and cmd[cmd.index("-s") + 1] == "workspace-write"
    assert "E2ER_AUDIT_JOURNAL" not in calls[0]["env"], "no paper, no journal"


@pytest.mark.parametrize(
    "platform, os_name, remedy",
    [("win32", "Windows", "#30009"), ("linux", "Linux", "apparmor_restrict_unprivileged_userns"),
     ("darwin", "macOS", "npm install -g @openai/codex@latest")],
)  # fmt: skip
async def test_the_check_stops_the_run_when_no_file_is_written(cfg, platform, os_name, remedy):
    cfg.setattr(codex, "_platform", lambda: platform)
    fake, calls = _fake_codex(_events(_DONE, _USAGE))
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        with pytest.raises(SandboxBlockedError) as caught:
            await CodexBackend().preflight()
        # A failed check is not remembered: the next run (or Resume) checks again.
        with pytest.raises(SandboxBlockedError):
            await CodexBackend().preflight()
    assert len(calls) == 2
    err = caught.value
    assert isinstance(err, PlanLimitReachedError) and err.event == "paused_sandbox"
    text = str(err)
    assert text.startswith("Stopped before the first step: Codex did not write the test file in a test folder on ")
    assert os_name in text and remedy in text and "every specialist would fail" in text
    assert "WSL" not in text
    assert "Last resort" in text and "CODEX_SANDBOX=danger-full-access" in text


async def test_a_file_with_other_content_fails_too(cfg):
    fake, _calls = _fake_codex(_events(_DONE, _USAGE), write="something else")
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        ok, detail = await CodexBackend().check_sandbox()
    assert ok is False and "other content" in detail


async def test_a_failed_test_call_stops_the_run_with_codex_s_error(cfg):
    stdout = _events({"type": "turn.failed", "error": {"message": "not logged in: run codex login"}})
    fake, _calls = _fake_codex(stdout, returncode=1)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        ok, detail = await CodexBackend().check_sandbox()
    assert ok is False and "test call failed" in detail and "codex login" in detail


@pytest.mark.parametrize(
    "env, why",
    [({"E2ER_SKIP_SANDBOX_PREFLIGHT": "1"}, "E2ER_SKIP_SANDBOX_PREFLIGHT=1"),
     ({"CODEX_SANDBOX": "read-only"}, "CODEX_SANDBOX=read-only"),
     ({"CODEX_SANDBOX": "danger-full-access", "CODEX_ALLOW_FULL_ACCESS": "true"}, "danger-full-access")],
)  # fmt: skip
async def test_nothing_is_checked_when_skipped_or_without_workspace_write(cfg, env, why):
    for k, v in env.items():
        cfg.setenv(k, v)
    get_settings.cache_clear()
    fake, calls = _fake_codex(b"")
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        ok, detail = await CodexBackend().check_sandbox()
        await CodexBackend().preflight()
    assert ok is None and why in detail and calls == []


async def test_run_preflight_leaves_backends_without_a_check_alone():
    await run_preflight(MagicMock())  # a test double: nothing awaited, nothing raised

    class Checked:
        def __init__(self):
            self.ran = False

        async def preflight(self):
            self.ran = True

    b = Checked()
    await run_preflight(b)
    assert b.ran


async def test_the_runner_stops_before_the_first_specialist(tmp_path, monkeypatch):
    from src.core.strategist.runner import PipelineRunner

    events: list[str] = []

    async def _log_event(paper_id, kind, *, stage=None, specialist=None, payload=None, **kw):
        events.append(kind)

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    paper_id = str(uuid.uuid4())
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": paper_id, "title": "T", "research_question": "Q?", "mode": "single_pass"}),
        encoding="utf-8",
        newline="\n",
    )
    reason = "Stopped before the first step: Codex did not write the test file in a test folder on Linux."

    class Blocked(MagicMock):
        async def preflight(self):
            raise SandboxBlockedError("codex", reason, reason)

    statuses: list[tuple[str, str | None]] = []

    async def _execute(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            statuses.append((params["s"], params.get("e")))

    initial = AsyncMock()
    with (
        patch("src.db.client.execute", side_effect=_execute),
        patch("src.core.strategist.runner.PipelineRunner._run_initial_phase", initial),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=ws, backend=Blocked(), model="m", mode="single_pass", backend_name="codex"
        )
        result = await runner.run()
    initial.assert_not_called()
    assert result["status"] == "paused" and result["reason"] == "sandbox"
    assert statuses[-1] == ("paused", reason)
    assert "paused_sandbox" in events and "specialist_start" not in events


# ── no retries against a sandbox that refused ──────────────────────────────


async def test_a_refused_call_sets_sandbox_blocked(cfg):
    fake, _calls = _fake_codex(_events(_REFUSED_PATCH, _USAGE))
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        result = await CodexBackend().tool_loop(
            system="s", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None
        )
    assert result.success and result.sandbox_blocked
    assert "file change refused (paper_plan.md)" in result.diagnostic


async def test_a_call_without_refusals_is_not_blocked(cfg):
    fake, _calls = _fake_codex(_events(_DONE, _USAGE))
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        result = await CodexBackend().tool_loop(
            system="s", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None
        )
    assert result.success and not result.sandbox_blocked


class _Refused:
    """A backend whose sandbox refused every write: success, no file, sandbox_blocked."""

    def __init__(self, blocked: bool = True):
        self.calls = 0
        self.blocked = blocked

    async def tool_loop(self, **kw):
        self.calls += 1
        return ToolLoopResult(
            success=True,
            output="done",
            tool_calls_made=1,
            diagnostic="Codex's sandbox refused a write or command (file change refused (paper_plan.md)).",
            sandbox_blocked=self.blocked,
        )


@pytest.fixture
def quiet_db(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, specialist=None, payload=None, **kw):
        log.append((kind, specialist, payload or {}))

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    monkeypatch.setattr("src.db.client.execute", _noop)
    monkeypatch.setattr("src.core.specialists.base.save_usage", _noop)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget_by_paper_id", AsyncMock())
    return log


async def test_the_dispatcher_stops_after_one_attempt_and_pauses_with_the_reason(tmp_workspace, paper_id, quiet_db):
    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import WorkOrder

    backend = _Refused()
    order = WorkOrder(paper_id=paper_id, specialist="idea_developer", focus="Plan.", context_tier=1)
    with pytest.raises(SandboxBlockedError) as caught:
        await dispatcher.run_with_attempts(order, backend, tmp_workspace, "m", backend_name="codex")
    assert backend.calls == 1, "no second and third attempt against the same sandbox"
    err = caught.value
    assert err.event == "paused_sandbox" and err.specialist == "idea_developer"
    assert "file change refused (paper_plan.md)" in err.status and "Press Resume" in err.status
    failed = [p for kind, _sp, p in quiet_db if kind == "specialist_failed"]
    assert len(failed) == 1 and failed[0]["sandbox_blocked"] is True


async def test_without_a_refusal_the_contract_violation_is_retried_as_before(tmp_workspace, paper_id, quiet_db):
    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import WorkOrder

    backend = _Refused(blocked=False)
    order = WorkOrder(paper_id=paper_id, specialist="idea_developer", focus="Plan.", context_tier=1)
    contribution = await dispatcher.run_with_attempts(order, backend, tmp_workspace, "m", backend_name="codex")
    assert contribution.success is False and backend.calls == dispatcher.MAX_SPECIALIST_ATTEMPTS


# ── e2er doctor ──────────────────────────────────────────────────────────────


async def test_doctor_reports_the_sandbox_check(cfg):
    from src import doctor

    cfg.setattr(doctor, "resolve_backend_cli", lambda backend, settings=None: "/bin/codex")
    cfg.setattr(doctor, "cli_signed_in", lambda backend, home=None: (True, "signed in"))
    settings = MagicMock(llm_backend="codex")
    fake, _calls = _fake_codex(_events(_DONE, _USAGE))
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        failed = await doctor.codex_sandbox_check(settings)
    assert failed.name == "workspace.codex_sandbox" and failed.status == doctor.FAIL
    fake, _calls = _fake_codex(_events(_DONE, _USAGE), write=SANDBOX_CHECK_TEXT)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        passed = await doctor.codex_sandbox_check(settings)
    assert passed.status == doctor.PASS
    assert await doctor.codex_sandbox_check(MagicMock(llm_backend="claude_code")) is None
