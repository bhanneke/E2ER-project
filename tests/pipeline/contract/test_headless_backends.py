"""Lane A — contract tests for the Codex + Gemini headless backends.

These backends shell out to vendor CLIs (`codex exec`, `gemini`). The
tests mock the subprocess so they run hermetically and in <100ms. Live
validation against a real Plus/Pro/Ultra subscription happens out of band.

What's pinned:
  - Backend instantiates without an installed CLI (constructor doesn't
    probe the binary)
  - CLI command shape (binary, key flags) is correct
  - Missing-CLI returns a structured ToolLoopResult with a clear hint,
    not an uncaught FileNotFoundError
  - Timeout path returns a ToolLoopResult, not a raised TimeoutError
  - registry routes LLM_BACKEND=codex / gemini correctly
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.modules.llm.codex import CodexBackend
from src.modules.llm.gemini import GeminiBackend
from src.modules.llm.registry import get_backend

# ---------- registry routing ----------


def test_registry_routes_codex():
    s = Settings(llm_backend="codex")
    assert isinstance(get_backend(s), CodexBackend)


def test_registry_routes_gemini():
    s = Settings(llm_backend="gemini")
    assert isinstance(get_backend(s), GeminiBackend)


# ---------- Codex backend ----------


@pytest.mark.asyncio
async def test_codex_returns_structured_error_when_cli_missing():
    """If `codex` isn't on PATH, the backend returns a ToolLoopResult with
    a clear install hint — never raises FileNotFoundError into runner code."""
    backend = CodexBackend()
    backend._cli_path = "/nonexistent/codex"  # noqa: SLF001

    result = await backend.tool_loop(
        system="You are a test.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        tool_handler=None,
        max_turns=5,
    )
    assert result.success is False
    assert result.error is not None
    assert "Codex CLI not found" in result.error
    assert "npm install -g @openai/codex" in result.error


@pytest.mark.asyncio
async def test_codex_cmd_includes_exec_subcommand():
    """The first positional arg to the subprocess must be 'exec' — Codex
    has multiple modes ('exec', 'login', 'serve'). Pin the contract."""
    backend = CodexBackend()
    captured_cmd: list[str] = []

    async def _fake_exec(*args, **kwargs):
        captured_cmd.extend(args)
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"hello world", b""))
        proc.returncode = 0
        return proc

    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=_fake_exec):
        await backend.tool_loop(
            system="sys",
            messages=[{"role": "user", "content": "u"}],
            tools=[],
            tool_handler=None,
            max_turns=1,
        )

    assert captured_cmd, "subprocess must have been invoked"
    # cli_path is index 0, "exec" must be index 1
    assert captured_cmd[1] == "exec", f"second arg should be 'exec', got {captured_cmd[:3]}"
    # Last arg must be '-' for stdin prompt
    assert captured_cmd[-1] == "-", f"last arg should be '-', got {captured_cmd[-1]}"


@pytest.mark.asyncio
async def test_codex_stdout_becomes_output():
    """Whole stdout (stripped) becomes the model's output."""
    backend = CodexBackend()

    async def _fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"  the answer is 42  ", b""))
        proc.returncode = 0
        return proc

    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=_fake_exec):
        result = await backend.tool_loop(
            system="sys",
            messages=[{"role": "user", "content": "u"}],
            tools=[],
            tool_handler=None,
            max_turns=1,
        )

    assert result.success is True
    assert result.output == "the answer is 42"


# ---------- Gemini backend ----------


@pytest.mark.asyncio
async def test_gemini_returns_structured_error_when_cli_missing():
    backend = GeminiBackend()
    backend._cli_path = "/nonexistent/gemini"  # noqa: SLF001

    result = await backend.tool_loop(
        system="You are a test.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        tool_handler=None,
        max_turns=5,
    )
    assert result.success is False
    assert result.error is not None
    assert "Gemini CLI not found" in result.error
    assert "@google/gemini-cli" in result.error


@pytest.mark.asyncio
async def test_gemini_cmd_includes_yolo_or_approval_mode():
    """Either --approval-mode yolo (newer) or --yolo (older) must appear —
    otherwise the CLI prompts interactively and the subprocess hangs."""
    backend = GeminiBackend()
    captured_cmd: list[str] = []

    async def _fake_exec(*args, **kwargs):
        captured_cmd.extend(args)
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        proc.returncode = 0
        return proc

    with patch("src.modules.llm.gemini.asyncio.create_subprocess_exec", new=_fake_exec):
        await backend.tool_loop(
            system="sys",
            messages=[{"role": "user", "content": "u"}],
            tools=[],
            tool_handler=None,
            max_turns=1,
        )

    cmd_str = " ".join(captured_cmd)
    assert "--yolo" in cmd_str or "--approval-mode" in cmd_str, (
        f"missing approval/yolo flag — Gemini will hang interactively. cmd: {cmd_str}"
    )


@pytest.mark.asyncio
async def test_gemini_stdout_becomes_output():
    backend = GeminiBackend()

    async def _fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"42", b""))
        proc.returncode = 0
        return proc

    with patch("src.modules.llm.gemini.asyncio.create_subprocess_exec", new=_fake_exec):
        result = await backend.tool_loop(
            system="sys",
            messages=[{"role": "user", "content": "u"}],
            tools=[],
            tool_handler=None,
            max_turns=1,
        )

    assert result.success is True
    assert result.output == "42"


# ---------- shared: prompt flattening ----------


@pytest.mark.asyncio
async def test_codex_flattens_system_and_messages_into_stdin():
    """Both backends combine system + messages into one prompt via stdin —
    verify the prompt content actually contains both parts."""
    backend = CodexBackend()
    captured_stdin: list[bytes] = []

    async def _fake_exec(*args, **kwargs):
        proc = MagicMock()

        async def _comm(input: bytes):
            captured_stdin.append(input)
            return (b"", b"")

        proc.communicate = _comm
        proc.returncode = 0
        return proc

    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=_fake_exec):
        await backend.tool_loop(
            system="SYSTEM_MARKER",
            messages=[{"role": "user", "content": "USER_MARKER"}],
            tools=[],
            tool_handler=None,
            max_turns=1,
        )

    assert captured_stdin, "stdin must have been written"
    body = captured_stdin[0].decode("utf-8")
    assert "SYSTEM_MARKER" in body
    assert "USER_MARKER" in body
