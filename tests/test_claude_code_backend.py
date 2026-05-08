"""Tests for the Claude Code CLI backend.

This is the v1/v2-style backend that lets users run the pipeline at $0/token
under a Max plan. We mock the subprocess so the tests run offline ($0).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch


def _settings_for_cli(monkeypatch, tmp_path):
    """Force LLM_BACKEND=claude_code and clear settings cache."""
    monkeypatch.setenv("LLM_BACKEND", "claude_code")
    monkeypatch.setenv("CLAUDE_CODE_PATH", "/usr/local/bin/claude")
    monkeypatch.setenv("CLAUDE_CODE_CWD", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_TIMEOUT", "60")
    from src.config import get_settings

    get_settings.cache_clear()


def _mock_proc(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Build a minimal asyncio subprocess mock."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ---------------------------------------------------------------------------
# Registry — config switch picks the right backend
# ---------------------------------------------------------------------------


def test_registry_returns_claude_code_when_configured(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)
    from src.config import get_settings
    from src.modules.llm.claude_code import ClaudeCodeBackend
    from src.modules.llm.registry import get_backend

    backend = get_backend(get_settings())
    assert isinstance(backend, ClaudeCodeBackend)


# ---------------------------------------------------------------------------
# Happy path — CLI returns success → ToolLoopResult(success=True)
# ---------------------------------------------------------------------------


async def test_tool_loop_parses_successful_cli_output(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)

    from src.modules.llm.claude_code import ClaudeCodeBackend

    backend = ClaudeCodeBackend()
    summary = {
        "type": "result",
        "subtype": "success",
        "result": "I have written paper_plan.md.",
        "is_error": False,
        "usage": {"input_tokens": 1234, "output_tokens": 567, "cache_read_input_tokens": 0},
        "messages": [
            {"role": "user", "content": "x"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Write", "input": {"path": "x"}},
                    {"type": "tool_use", "name": "Write", "input": {"path": "y"}},
                ],
            },
        ],
    }
    stdout = (json.dumps({"type": "system"}) + "\n" + json.dumps(summary) + "\n").encode()
    proc = _mock_proc(stdout=stdout)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await backend.tool_loop(
            system="System prompt",
            messages=[{"role": "user", "content": "Do the thing."}],
            tools=[],
            tool_handler=None,
            max_turns=20,
        )

    assert result.success
    assert "paper_plan.md" in result.output
    assert result.usage.input_tokens == 1234
    assert result.usage.output_tokens == 567
    assert result.tool_calls_made == 2
    assert result.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# error_max_turns — CLI exits 0 but flags it didn't finish
# ---------------------------------------------------------------------------


async def test_tool_loop_detects_error_max_turns(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)
    from src.modules.llm.claude_code import ClaudeCodeBackend

    summary = {"subtype": "error_max_turns", "is_error": True, "result": "partial output"}
    stdout = (json.dumps(summary) + "\n").encode()
    proc = _mock_proc(stdout=stdout)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        backend = ClaudeCodeBackend()
        result = await backend.tool_loop(
            system="x",
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            tool_handler=None,
            max_turns=5,
        )

    assert not result.success
    assert "max_turns" in (result.error or "").lower()
    assert result.stop_reason == "max_turns"


# ---------------------------------------------------------------------------
# Subprocess failure — non-zero exit code
# ---------------------------------------------------------------------------


async def test_tool_loop_handles_nonzero_exit(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)
    from src.modules.llm.claude_code import ClaudeCodeBackend

    proc = _mock_proc(returncode=1, stdout=b"", stderr=b"Authentication failed: not logged in")

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        backend = ClaudeCodeBackend()
        result = await backend.tool_loop(
            system="x",
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            tool_handler=None,
            max_turns=5,
        )

    assert not result.success
    assert "Authentication" in (result.error or "")


# ---------------------------------------------------------------------------
# CLI not installed — clean error message
# ---------------------------------------------------------------------------


async def test_tool_loop_handles_cli_not_found(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)
    from src.modules.llm.claude_code import ClaudeCodeBackend

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError())):
        backend = ClaudeCodeBackend()
        result = await backend.tool_loop(
            system="x",
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            tool_handler=None,
            max_turns=5,
        )

    assert not result.success
    assert "not found" in (result.error or "").lower() or "claude" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Timeout — subprocess killed
# ---------------------------------------------------------------------------


async def test_tool_loop_timeout_kills_subprocess(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)
    from src.modules.llm.claude_code import ClaudeCodeBackend

    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=TimeoutError())
    proc.kill = MagicMock()
    proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        backend = ClaudeCodeBackend()
        result = await backend.tool_loop(
            system="x",
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            tool_handler=None,
            max_turns=5,
        )

    assert not result.success
    assert "timed out" in (result.error or "").lower()
    proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Prompt structure — system + user are flattened correctly
# ---------------------------------------------------------------------------


async def test_tool_loop_flattens_messages_into_prompt(monkeypatch, tmp_path):
    _settings_for_cli(monkeypatch, tmp_path)
    from src.modules.llm.claude_code import ClaudeCodeBackend

    summary = {"result": "ok", "usage": {}}
    proc = _mock_proc(stdout=(json.dumps(summary) + "\n").encode())

    captured_input: dict = {}

    async def _capture(input):
        captured_input["data"] = input
        return (json.dumps(summary).encode(), b"")

    proc.communicate = _capture

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        backend = ClaudeCodeBackend()
        await backend.tool_loop(
            system="You are a research specialist.",
            messages=[{"role": "user", "content": "Write paper_plan.md for an NFT paper."}],
            tools=[],
            tool_handler=None,
            max_turns=10,
        )

    sent = captured_input["data"].decode()
    assert "You are a research specialist." in sent
    assert "Write paper_plan.md for an NFT paper." in sent
