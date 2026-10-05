"""What the October 2026 live validation of the Codex backend fixed, pinned.

Each test names the fault it pins. The subprocess is mocked; the live runs
that found the faults are recorded in CHANGELOG (Unreleased).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sysconfig
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import get_settings
from src.modules.llm import cli_support, codex, gemini
from src.modules.llm.codex import CodexBackend, is_transient_codex_error, parse_codex_events
from src.modules.llm.gemini import GeminiBackend, parse_gemini_json


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    """Settings from the environment, re-read per test; cwd is a non-git temp dir."""
    monkeypatch.chdir(tmp_path)
    for k in ("CODEX_MODEL", "CODEX_REASONING_EFFORT", "CODEX_SANDBOX", "CODEX_PATH", "GEMINI_MODEL", "DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WORKSPACE_ROOT", "workspaces")  # relative, as by default
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db' / 'papers.db'}")
    get_settings.cache_clear()

    def set_(**kw: str) -> None:
        for k, v in kw.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield set_
    get_settings.cache_clear()


def _fake_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, on_call=None):
    calls: dict = {}

    async def _exec(*args, **kwargs):
        calls["cmd"] = list(args)
        calls["kwargs"] = kwargs
        if on_call:
            on_call(list(args), kwargs)
        proc = MagicMock()
        proc.pid = 4242

        async def _comm(input: bytes = b""):
            calls["stdin"] = input
            return (stdout, stderr)

        proc.communicate = _comm
        proc.returncode = returncode
        return proc

    return _exec, calls


async def _call(backend, **kw):
    return await backend.tool_loop(
        system="sys", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None, max_turns=5, **kw
    )


def _events(*evs: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in evs) + "\n").encode()


_OK_EVENTS = _events(
    {"type": "thread.started", "thread_id": "t"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "1", "type": "command_execution", "command": "ls", "exit_code": 0}},
    {"type": "item.completed", "item": {"id": "2", "type": "file_change", "changes": []}},
    {"type": "item.completed", "item": {"id": "3", "type": "agent_message", "text": "DONE"}},
    {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 50}},
)


# ---------- Codex: the command line (B1, B2, W1, W3, W4, W5, R1) ----------


async def test_codex_command_line_runs_writable_outside_git_with_network(cfg, tmp_path):
    cfg(CODEX_MODEL="gpt-x", CODEX_REASONING_EFFORT="medium")
    fake, calls = _fake_proc(_OK_EVENTS)
    (tmp_path / "workspaces" / "p1").mkdir(parents=True)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend(), paper_id="p1", specialist="data_analyst")
    cmd = calls["cmd"]
    joined = " ".join(cmd)
    assert cmd[1] == "exec" and cmd[-1] == "-"
    # B1: exec defaults to read-only, in which nothing can be written.
    assert cmd[cmd.index("-s") + 1] == "workspace-write"
    # B2: study folders and temp dirs are not git repositories.
    assert "--skip-git-repo-check" in cmd
    # W1: e2er-data / e2er-lit need the network, which the sandbox turns off.
    assert "sandbox_workspace_write.network_access=true" in cmd
    # W3: keys reach the wrappers' shell.
    assert 'shell_environment_policy.inherit="all"' in cmd
    assert "shell_environment_policy.ignore_default_excludes=true" in cmd
    # W4: the run database's folder is writable.
    assert cmd[cmd.index("--add-dir") + 1] == str((tmp_path / "db").resolve())
    # W5: none of the user's own Codex config, rules or session history.
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral"):
        assert flag in cmd
    assert "allow_login_shell=false" in cmd
    assert 'approval_policy="never"' in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-x"
    assert 'model_reasoning_effort="medium"' in cmd
    # R1: events on stdout, final message to a file.
    assert "--json" in cmd and "-o" in cmd
    assert "-C" in cmd and cmd[cmd.index("-C") + 1] == str((tmp_path / "workspaces" / "p1").resolve())
    assert "bypass" not in joined


async def test_codex_read_only_sandbox_gets_no_network_or_extra_dirs(cfg):
    cfg(CODEX_SANDBOX="read-only")
    fake, calls = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend())
    cmd = calls["cmd"]
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert "--add-dir" not in cmd
    assert "sandbox_workspace_write.network_access=true" not in cmd


async def test_codex_database_inside_the_workspace_needs_no_extra_dir(cfg, tmp_path):
    cfg(DATABASE_URL=f"sqlite:///{tmp_path / 'workspaces' / 'p1' / 'papers.db'}")
    fake, calls = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend(), paper_id="p1")
    assert "--add-dir" not in calls["cmd"]


async def test_codex_postgres_database_needs_no_extra_dir(cfg):
    cfg(DATABASE_URL="postgresql://u:p@h:5432/d")
    fake, calls = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend(), paper_id="p1")
    assert "--add-dir" not in calls["cmd"]
    assert calls["kwargs"]["env"].get("DATABASE_URL") == "postgresql://u:p@h:5432/d"


# ---------- the subprocess environment (W2, R7, .env passthrough) ----------


@pytest.mark.parametrize("backend_cls", [CodexBackend, GeminiBackend])
async def test_workspace_root_is_absolute_in_cwd_and_env(cfg, tmp_path, backend_cls):
    """W2: a relative WORKSPACE_ROOT nested workspaces/<id> inside itself (eea5379b)."""
    fake, calls = _fake_proc(_OK_EVENTS if backend_cls is CodexBackend else b'{"response": "ok"}')
    mod = "codex" if backend_cls is CodexBackend else "gemini"
    with (
        patch(f"src.modules.llm.{mod}.asyncio.create_subprocess_exec", new=fake),
        patch("src.modules.llm.gemini._probe_gemini_flags", return_value=(True, True)),
    ):
        await _call(backend_cls(), paper_id="p9", specialist="data_analyst")
    env = calls["kwargs"]["env"]
    root = (tmp_path / "workspaces").resolve()
    assert env["E2ER_WORKSPACE_ROOT"] == str(root)
    assert Path(env["E2ER_WORKSPACE_ROOT"]).is_absolute()
    assert calls["kwargs"]["cwd"] == str(root / "p9")
    assert env["E2ER_PAPER_ID"] == "p9" and env["E2ER_SPECIALIST"] == "data_analyst"
    # R7: the venv's entry-point shims are on PATH, not only the checkout's scripts/.
    assert sysconfig.get_path("scripts") in env["PATH"].split(os.pathsep)
    # The run database, absolute, so the wrappers' audit rows land in it.
    assert env["DATABASE_URL"] == f"sqlite:///{(tmp_path / 'db' / 'papers.db').resolve()}"
    assert calls["kwargs"]["start_new_session"] is True


async def test_study_dotenv_reaches_the_wrappers(cfg, tmp_path, monkeypatch):
    """A key set only in the study's .env reached the e2er process but not the
    wrappers, which read the .env of their own cwd."""
    monkeypatch.delenv("E2ER_TEST_ONLY_IN_DOTENV", raising=False)
    monkeypatch.setenv("E2ER_TEST_ALREADY_SET", "from-env")
    (tmp_path / ".env").write_text("E2ER_TEST_ONLY_IN_DOTENV=yes\nE2ER_TEST_ALREADY_SET=from-file\n")
    fake, calls = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend(), paper_id="p1")
    env = calls["kwargs"]["env"]
    assert env["E2ER_TEST_ONLY_IN_DOTENV"] == "yes"
    assert env["E2ER_TEST_ALREADY_SET"] == "from-env"  # the environment wins, as in Settings


async def test_claude_code_uses_the_same_environment(cfg, tmp_path):
    from src.modules.llm.claude_code import ClaudeCodeBackend

    fake, calls = _fake_proc(b'{"result": "ok", "num_turns": 1}')
    with patch("src.modules.llm.claude_code.asyncio.create_subprocess_exec", new=fake):
        await _call(ClaudeCodeBackend(), paper_id="p1")
    env = calls["kwargs"]["env"]
    assert env["E2ER_WORKSPACE_ROOT"] == str((tmp_path / "workspaces").resolve())
    assert env["DATABASE_URL"].startswith("sqlite:///")


# ---------- parsing and usage (R1, R2) ----------


async def test_codex_reads_the_last_message_file_and_records_usage(cfg):
    def write_last(cmd, _kw):
        Path(cmd[cmd.index("-o") + 1]).write_text("FINAL ANSWER\n")

    fake, _ = _fake_proc(_OK_EVENTS, on_call=write_last)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        r = await _call(CodexBackend())
    assert r.success and r.output == "FINAL ANSWER"
    assert r.tool_calls_made == 2
    assert (r.usage.input_tokens, r.usage.cache_read_tokens, r.usage.output_tokens) == (400, 600, 50)


async def test_codex_falls_back_to_the_last_agent_message(cfg):
    fake, _ = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        r = await _call(CodexBackend())
    assert r.output == "DONE"


async def test_codex_temp_file_is_removed(cfg):
    seen: list[str] = []
    fake, _ = _fake_proc(_OK_EVENTS, on_call=lambda cmd, _kw: seen.append(cmd[cmd.index("-o") + 1]))
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend())
    assert seen and not Path(seen[0]).exists()


def test_parse_codex_events_turn_failed_is_an_error():
    out = parse_codex_events(
        _events(
            {"type": "turn.started"},
            {"type": "error", "message": "stream disconnected before completion"},
            {"type": "turn.failed", "error": {"message": "stream disconnected before completion"}},
        ).decode()
    )
    assert "stream disconnected" in out["error"]


def test_parse_codex_events_reconnect_notice_then_success_is_not_an_error():
    out = parse_codex_events(
        _events(
            {"type": "error", "message": "Reconnecting... 1/5"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 1}},
        ).decode()
    )
    assert out["error"] == "" and out["last_agent_message"] == "ok"


async def test_codex_failure_keeps_usage_and_clips_the_error(cfg):
    big = "x" * 20_000
    fake, _ = _fake_proc(
        _events({"type": "turn.failed", "error": {"message": "bad request " + big}}),
        returncode=1,
    )
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        r = await _call(CodexBackend())
    assert not r.success
    assert r.error and len(r.error) < 4200 and "bad request" in r.error


# ---------- retries and timeouts (R4) ----------


@pytest.mark.parametrize(
    "error, transient",
    [
        ("stream disconnected before completion", True),
        ("exceeded retry limit, last status: 503 Service Unavailable", True),
        ("error sending request for url", True),
        ("Selected model is at capacity. Please try a different model.", True),  # live E2E-01, 2026-10-05
        ("You've hit your usage limit. Try again in 3 hours.", False),
        ("429 Too Many Requests: usage_limit_reached", False),
        ("invalid model gpt-nope", False),
    ],
)
def test_transient_codex_errors(error, transient):
    assert is_transient_codex_error(error) is transient


async def test_codex_retries_a_transient_error_then_succeeds(cfg):
    outputs = [
        (_events({"type": "turn.failed", "error": {"message": "stream disconnected"}}), 1),
        (_OK_EVENTS, 0),
    ]
    n = {"i": 0}

    async def fake(*args, **kwargs):
        out, rc = outputs[n["i"]]
        n["i"] += 1
        proc = MagicMock()
        proc.pid = 1
        proc.communicate = AsyncMock(return_value=(out, b""))
        proc.returncode = rc
        return proc

    with (
        patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake),
        patch("src.modules.llm.codex.asyncio.sleep", new=AsyncMock()),
    ):
        r = await _call(CodexBackend())
    assert r.success and n["i"] == 2


async def test_codex_does_not_retry_a_usage_limit(cfg):
    n = {"i": 0}

    async def fake(*args, **kwargs):
        n["i"] += 1
        proc = MagicMock()
        proc.pid = 1
        proc.communicate = AsyncMock(
            return_value=(_events({"type": "turn.failed", "error": {"message": "usage limit"}}), b"")
        )
        proc.returncode = 1
        return proc

    with (
        patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake),
        patch("src.modules.llm.codex.asyncio.sleep", new=AsyncMock()),
    ):
        r = await _call(CodexBackend())
    assert not r.success and n["i"] == 1


@pytest.mark.parametrize("backend_cls", [CodexBackend, GeminiBackend])
async def test_timeout_kills_the_whole_process_group(cfg, backend_cls):
    cfg(CODEX_TIMEOUT="1", GEMINI_TIMEOUT="1")
    proc = MagicMock()
    proc.pid = 31337

    async def hang(input: bytes = b""):
        await asyncio.sleep(10)

    proc.communicate = hang
    proc.wait = AsyncMock(return_value=-9)
    mod = "codex" if backend_cls is CodexBackend else "gemini"
    with (
        patch(f"src.modules.llm.{mod}.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
        patch("src.modules.llm.gemini._probe_gemini_flags", return_value=(True, True)),
        patch("src.modules.llm.cli_support.os.getpgid", return_value=31337) as getpgid,
        patch("src.modules.llm.cli_support.os.killpg") as killpg,
    ):
        r = await _call(backend_cls())
    assert not r.success and "timed out" in (r.error or "")
    getpgid.assert_called_with(31337)
    killpg.assert_called_once_with(31337, signal.SIGKILL)


# ---------- model label and CLI version (R6) ----------


def _write_models_cache(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "small-one", "priority": 4, "visibility": "list", "description": "Fast."},
                    {"slug": "internal-reviewer", "priority": 1, "visibility": "hide"},
                    {"slug": "big-one", "priority": 2, "visibility": "list", "description": "Frontier."},
                ]
            }
        )
    )


def test_codex_without_a_model_setting_uses_and_records_the_clis_first_listed_model(cfg, tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    _write_models_cache(home)
    monkeypatch.setattr(codex, "_codex_home", lambda: home)
    codex.default_codex_model.cache_clear()
    assert CodexBackend().model == "big-one"
    assert get_settings().default_model_for("codex") == "big-one"
    cmd = CodexBackend().build_cmd(cwd="/w", last_message_file="/f", extra_dirs=[])
    assert cmd[cmd.index("-m") + 1] == "big-one"


def test_codex_label_without_any_model_list_stays_honest(cfg):
    assert get_settings().default_model_for("codex") == "codex-cli-default"
    assert "-m" not in CodexBackend().build_cmd(cwd="/w", last_message_file="/f", extra_dirs=[])


def test_identity_records_model_effort_and_cli_version(cfg):
    cfg(CODEX_MODEL="m1", CODEX_REASONING_EFFORT="low")
    cli_support.cli_version.cache_clear()
    with patch("src.modules.llm.cli_support.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="codex-cli 9.9.9\n", stderr="")
        ident = CodexBackend().identity()
    cli_support.cli_version.cache_clear()
    assert ident["model"] == "m1" and ident["reasoning_effort"] == "low"
    assert ident["cli_version"] == "codex-cli 9.9.9"


@pytest.mark.parametrize("backend", ["anthropic", "openrouter", "claude_code", "codex", "gemini"])
def test_a_per_paper_model_reaches_the_backend(cfg, backend):
    """`e2er run --model` / `run-matrix --models` used to label the run only."""
    from src.modules.llm.registry import get_backend

    cfg(ANTHROPIC_API_KEY="k", OPENROUTER_API_KEY="k")
    b = get_backend(get_settings(), name=backend, model="picked-model")
    assert b._model == "picked-model"  # noqa: SLF001


# ---------- finding the CLI (W6) ----------


def test_resolve_cli_honours_the_configured_path(cfg, tmp_path):
    exe = tmp_path / "bin" / "my-codex"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    cfg(CODEX_PATH=str(exe))
    assert cli_support.resolve_cli("codex", get_settings()) == str(exe)
    assert CodexBackend()._cli_path == str(exe)  # noqa: SLF001


def test_resolve_cli_finds_the_chatgpt_apps_codex(cfg, tmp_path, monkeypatch):
    app = tmp_path / "ChatGPT.app" / "Contents" / "Resources" / "codex"
    app.parent.mkdir(parents=True)
    app.write_text("#!/bin/sh\n")
    app.chmod(0o755)
    monkeypatch.setattr(cli_support, "_EXTRA_LOCATIONS", {"codex": (str(app),)})
    with patch("src.modules.llm.cli_support.shutil.which", return_value=None):
        assert cli_support.resolve_cli("codex", get_settings()) == str(app)


def test_a_wrong_configured_path_is_not_papered_over(cfg, tmp_path, monkeypatch):
    app = tmp_path / "codex"
    app.write_text("#!/bin/sh\n")
    app.chmod(0o755)
    monkeypatch.setattr(cli_support, "_EXTRA_LOCATIONS", {"codex": (str(app),)})
    cfg(CODEX_PATH=str(tmp_path / "nope" / "codex"))
    assert cli_support.resolve_cli("codex", get_settings()) is None


async def test_doctor_uses_the_configured_cli_path(cfg, tmp_path):
    from src.doctor import PASS, backend_check, detect_backends

    exe = tmp_path / "codex-bin"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    cfg(CODEX_PATH=str(exe), LLM_BACKEND="codex")
    with patch("src.modules.llm.cli_support.shutil.which", return_value=None):
        c = await backend_check(get_settings())
        rows = {b.name: b for b in detect_backends(get_settings())}
    assert c.status == PASS and str(exe) in c.detail
    assert rows["codex"].installed


def test_setup_page_lists_the_codex_plans_models(cfg, tmp_path, monkeypatch):
    from src.doctor import detect_backends

    home = tmp_path / "codex-home"
    _write_models_cache(home)
    monkeypatch.setattr(codex, "_codex_home", lambda: home)
    rows = {b.name: b for b in detect_backends(get_settings())}
    values = [v for v, _ in rows["codex"].models]
    assert values == ["", "big-one", "small-one"]


# ---------- prompts name the CLI's own tools (R5) ----------


def test_tool_names_are_translated_for_codex_and_gemini():
    from src.core.specialists.base import _translate_tool_names_for_cli

    text = "Write it with `write_file`, change it with `edit_file`, look with `read_file`."
    assert "write_file" not in _translate_tool_names_for_cli(text, "codex")
    assert "`apply_patch`" in _translate_tool_names_for_cli(text, "codex")
    g = _translate_tool_names_for_cli(text, "gemini")
    assert "`replace`" in g and "`write_file`" in g and "`read_file`" in g
    assert "`Write`" in _translate_tool_names_for_cli(text)  # Claude Code unchanged


async def test_specialist_prompt_is_translated_on_codex(tmp_path):
    from src.core.specialists import base as sb

    seen: dict = {}

    class _B:
        async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
            from src.modules.llm.base import ToolLoopResult

            seen["system"] = system
            seen["user"] = messages[0]["content"]
            return ToolLoopResult(success=False, output="", error="stop here")

    from src.core.specialists.contracts import WorkOrder

    wo = WorkOrder(paper_id="p", specialist="literature_scanner", focus="scan", output_file="literature_review.md")
    with patch.object(sb, "save_usage", new=AsyncMock()), patch("src.db.client.execute", new=AsyncMock()):
        try:
            await sb.run_specialist(work_order=wo, backend=_B(), workspace=tmp_path, model="m", backend_name="codex")
        except Exception:  # noqa: BLE001 — only the prompt matters here
            pass
    assert seen, "the backend was not called"
    assert "write_file" not in seen["system"] + seen["user"]


# ---------- Gemini (not validated live) ----------


def test_gemini_asks_for_json_and_parses_usage_and_tool_calls():
    cmd = GeminiBackend().build_cmd(True, True)
    assert cmd[cmd.index("--output-format") + 1] == "json"
    out = parse_gemini_json(
        json.dumps(
            {
                "response": " answer ",
                "stats": {
                    "models": {
                        "gemini-x": {"tokens": {"prompt": 900, "candidates": 40, "cached": 300, "thoughts": 10}}
                    },
                    "tools": {"totalCalls": 3},
                },
            }
        )
    )
    assert out["json"] and out["response"] == "answer" and out["tool_calls"] == 3
    assert (out["usage"].input_tokens, out["usage"].cache_read_tokens, out["usage"].output_tokens) == (600, 300, 50)


def test_gemini_json_error_is_reported():
    out = parse_gemini_json('{"response": "", "error": {"type": "ApiError", "message": "quota exceeded"}}')
    assert out["error"] == "quota exceeded"


def test_gemini_plain_text_from_an_old_cli_still_works():
    assert parse_gemini_json("just text")["json"] is False


def test_gemini_failed_help_probe_is_not_cached(monkeypatch):
    """The probe used a 5 s timeout and cached the failure: a slow cold start
    pinned the legacy --yolo/text flags for the life of the process."""
    gemini._FLAG_CACHE.clear()
    import subprocess as sp

    with patch("src.modules.llm.gemini.subprocess.run", side_effect=sp.TimeoutExpired("gemini", 30)):
        assert gemini._probe_gemini_flags("/x/gemini") == (True, True)
    assert "/x/gemini" not in gemini._FLAG_CACHE
    with patch("src.modules.llm.gemini.subprocess.run") as run:
        run.return_value = MagicMock(stdout="Usage: gemini [--yolo]", stderr="")
        assert gemini._probe_gemini_flags("/x/gemini") == (False, False)
    assert gemini._FLAG_CACHE["/x/gemini"] == (False, False)
    gemini._FLAG_CACHE.clear()


async def test_gemini_missing_cli_hint_names_a_real_sign_in(cfg):
    b = GeminiBackend()
    b._cli_path = "/nonexistent/gemini"  # noqa: SLF001
    with patch("src.modules.llm.gemini._probe_gemini_flags", return_value=(True, True)):
        r = await _call(b)
    assert "gemini auth" not in (r.error or "")
    assert "run `gemini` once and sign in" in (r.error or "")


# ---------- e2er-data help (found live: a model asking --help got a traceback) ----------


def test_every_e2er_data_help_page_renders():
    import argparse

    from src.modules.data.cli import _build_parser

    def walk(p: argparse.ArgumentParser):
        yield p
        for a in p._actions:  # noqa: SLF001
            if isinstance(a, argparse._SubParsersAction):  # noqa: SLF001
                for sub in a.choices.values():
                    yield from walk(sub)

    for parser in walk(_build_parser()):
        parser.format_help()


@pytest.mark.parametrize(
    "backend, model, expected",
    [
        ("codex", None, None),
        ("codex", "codex-cli-default", None),  # a resumed unpinned run's label
        ("gemini", "gemini-cli-default", None),
        ("claude_code", "claude-sonnet-4-5", None),  # the API id the row carries when CLAUDE_CODE_MODEL is empty
        ("codex", "gpt-picked", "gpt-picked"),
        ("claude_code", "sonnet", "sonnet"),
    ],
)
def test_only_a_real_choice_overrides_the_backends_model(cfg, backend, model, expected):
    from src.api.app import model_override

    cfg(ANTHROPIC_MODEL="claude-sonnet-4-5")
    assert model_override(get_settings(), backend, model) == expected


async def test_e2er_control_credentials_do_not_reach_the_cli(cfg, monkeypatch):
    """No wrapper reads e2er's own control settings; under Codex or Gemini a
    model's shell command could use them."""
    for k in ("E2ER_SESSION_TOKEN", "E2ER_API_TOKEN", "E2ER_API_URL", "E2ER_CREDENTIALS", "API_AUTH_TOKEN"):
        monkeypatch.setenv(k, "x")
    fake, calls = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend(), paper_id="p1")
    env = calls["kwargs"]["env"]
    for k in ("E2ER_SESSION_TOKEN", "E2ER_API_TOKEN", "E2ER_API_URL", "E2ER_CREDENTIALS", "API_AUTH_TOKEN"):
        assert k not in env


def test_e2er_refuses_to_run_inside_an_ai_step(monkeypatch, capsys):
    """Live on Codex, 2026-10-05: a reviewer's shell started a second study on
    the lab's server with `e2er run` while the first was in its review step."""
    import sys as _sys

    from src import __main__ as cli

    monkeypatch.setenv("E2ER_AI_STEP", "writing_reviewer")
    monkeypatch.setattr(_sys, "argv", ["e2er", "run", "Does X affect Y?"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2
    assert "does not run inside a study's step" in capsys.readouterr().err


async def test_every_cli_call_is_marked_as_an_ai_step(cfg):
    fake, calls = _fake_proc(_OK_EVENTS)
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake):
        await _call(CodexBackend())  # a tool-less strategist call: no specialist
    assert calls["kwargs"]["env"]["E2ER_AI_STEP"] == "strategist"
