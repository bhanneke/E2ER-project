"""Stress tests for `LLMBackend.tool_loop` — the v3-introduced layer.

v3 made an architectural choice that v1/v2 didn't have: instead of delegating
to the Claude Code CLI subprocess, it owns the tool-use loop directly via the
Anthropic / OpenRouter SDKs (so AlliumToolHandler can intercept every tool
call for guardrail validation).

That choice introduced a class of bugs the unit-test suite didn't cover:
the layer was never pressure-tested with realistic specialist output sizes.
The May 2026 NFT-marketplace run lost ~$8 to one such bug (`max_tokens_per_call`
default was 16384 — too small for `data_architect` writing
`data_dictionary.json` as a single tool argument). MockLLMBackend returns
short canned outputs, so unit tests never saw the problem.

This file tests the tool_loop layer with the failure modes that matter:
- A specialist's tool argument can be tens of KB (large JSON / LaTeX).
- A tool result can be hundreds of KB (Allium query response).
- Many turns of tool calls accumulate message history.
- When `finish_reason="length"` fires, the error must point at the setting
  to fix.
- The default `max_tokens_per_call` must accommodate the largest single
  tool argument any specialist writes.

If any of these regress, this file goes red and the bug is caught offline
instead of via $8 of failed live runs.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.llm.base import ToolHandler

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _RecordingToolHandler(ToolHandler):
    """Records tool name + input on each handle() call. Returns canned text."""

    def __init__(self, return_text: str = "ok") -> None:
        self.calls: list[tuple[str, dict]] = []
        self._return_text = return_text

    def can_handle(self, tool_name: str) -> bool:
        return True

    async def handle(self, tool_name: str, tool_input: dict) -> str:
        self.calls.append((tool_name, dict(tool_input)))
        return self._return_text


def _openai_response(
    *,
    finish_reason: str,
    content: str = "",
    tool_calls: list | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
):
    """Build an OpenAI-compatible mock response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return response


def _openai_tool_call(tool_id: str, name: str, arguments_json: str):
    tc = MagicMock()
    tc.id = tool_id
    tc.function = MagicMock(name=name, arguments=arguments_json)
    tc.function.name = name  # MagicMock(name=...) sets the mock's *name*, not the attribute
    return tc


# ---------------------------------------------------------------------------
# T1: 30KB JSON tool argument flows through cleanly (the NFT-paper repro)
# ---------------------------------------------------------------------------


async def test_tool_loop_passes_through_30kb_tool_argument(monkeypatch):
    """data_architect writing data_dictionary.json emits a single tool call
    whose `content` argument is tens of KB of JSON. The tool_loop must
    forward that to the handler intact, not truncate it or trip on it."""
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("MAX_TOKENS_PER_CALL", "32768")

    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.llm.openrouter import OpenRouterBackend

    # Build a realistic 30KB JSON payload — what data_architect actually writes.
    big_dict = {
        "datasets": [{"name": f"ds_{i}", "fields": [f"f{j}" for j in range(80)]} for i in range(40)],
        "time_filter": {"start": "2024-01-01", "end": "2025-12-31"},
        "notes": "x" * 2000,
    }
    big_arg_json = json.dumps({"path": "data_dictionary.json", "content": json.dumps(big_dict)})
    assert len(big_arg_json) > 30_000, "test setup: argument should be >30KB"

    handler = _RecordingToolHandler(return_text='{"status": "written"}')

    # 2-turn mock: turn 1 returns the giant tool call, turn 2 returns end_turn.
    backend = OpenRouterBackend()
    create_mock = AsyncMock(
        side_effect=[
            _openai_response(
                finish_reason="tool_calls",
                tool_calls=[_openai_tool_call("tc1", "write_file", big_arg_json)],
            ),
            _openai_response(finish_reason="stop", content="Done."),
        ]
    )
    monkeypatch.setattr(backend._client.chat.completions, "create", create_mock)

    result = await backend.tool_loop(
        system="You write a data dictionary.",
        messages=[{"role": "user", "content": "Write data_dictionary.json"}],
        tools=[{"name": "write_file", "description": "x", "input_schema": {"type": "object"}}],
        tool_handler=handler,
        max_turns=10,
    )

    assert result.success, f"tool_loop should succeed; got error={result.error}"
    assert len(handler.calls) == 1, "handler must receive the giant tool call exactly once"
    assert handler.calls[0][0] == "write_file"
    received_content = handler.calls[0][1].get("content", "")
    assert len(received_content) > 25_000, (
        f"handler received only {len(received_content)} chars — tool argument was truncated en route"
    )


# ---------------------------------------------------------------------------
# T2: large tool result threads back into messages without crashing
# ---------------------------------------------------------------------------


async def test_tool_loop_handles_100kb_tool_result(monkeypatch):
    """Allium / read_file can return hundreds of KB. The tool_loop must
    pack that back into the message history and not corrupt the next turn."""
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.llm.openrouter import OpenRouterBackend

    huge_result = "row," * 25_000  # 100,000 chars
    handler = _RecordingToolHandler(return_text=huge_result)

    backend = OpenRouterBackend()
    create_mock = AsyncMock(
        side_effect=[
            _openai_response(
                finish_reason="tool_calls",
                tool_calls=[_openai_tool_call("tc1", "query_allium", '{"sql": "SELECT 1"}')],
            ),
            _openai_response(finish_reason="stop", content="Analysis complete."),
        ]
    )
    monkeypatch.setattr(backend._client.chat.completions, "create", create_mock)

    result = await backend.tool_loop(
        system="You analyse data.",
        messages=[{"role": "user", "content": "Run analysis"}],
        tools=[{"name": "query_allium", "description": "x", "input_schema": {"type": "object"}}],
        tool_handler=handler,
        max_turns=10,
    )

    assert result.success, f"tool_loop should succeed even with huge tool result; got {result.error}"
    # The 2nd `create` call should have received messages including the tool_result with the huge content.
    assert create_mock.call_count == 2
    second_call_msgs = create_mock.call_args_list[1].kwargs["messages"]
    tool_msg = next(m for m in second_call_msgs if m.get("role") == "tool")
    # Verbatim equality, not just length — tool result must be passed back
    # to the model unchanged. Any truncation here silently breaks specialists.
    assert tool_msg["content"] == huge_result, (
        f"tool result corrupted in transit: sent {len(huge_result)} chars, received {len(tool_msg['content'])} chars"
    )


# ---------------------------------------------------------------------------
# T3: finish_reason="length" surfaces an actionable error
# ---------------------------------------------------------------------------


async def test_finish_length_error_references_setting(monkeypatch):
    """When the model output gets truncated, the error message must name
    the setting to bump (`max_tokens_per_call`). Otherwise developers chase
    the wrong fix (max_turns, prompt size, etc.) — exactly what happened
    on the May 2026 NFT-paper run."""
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.llm.openrouter import OpenRouterBackend

    backend = OpenRouterBackend()
    create_mock = AsyncMock(
        return_value=_openai_response(
            finish_reason="length",
            content="partial output...",
        )
    )
    monkeypatch.setattr(backend._client.chat.completions, "create", create_mock)

    result = await backend.tool_loop(
        system="x",
        messages=[{"role": "user", "content": "x"}],
        tools=[],
        tool_handler=None,
        max_turns=5,
    )

    assert not result.success
    assert "max_tokens" in (result.error or "").lower(), (
        f"finish=length error must reference max_tokens setting; got: {result.error}"
    )
    assert create_mock.call_count == 1, "must NOT loop on finish=length — looping is futile (same wall every retry)"


# ---------------------------------------------------------------------------
# T4: config default floor — set high enough for biggest specialist writes
# ---------------------------------------------------------------------------


def test_max_tokens_per_call_default_at_least_32k():
    """Specialists that write large structured artifacts in a single tool call
    (data_architect → data_dictionary.json, paper_drafter → paper_draft.tex,
    latex_formatter → formatted draft) regularly emit >16K output tokens.
    Lowering this re-introduces the May 2026 failure mode."""
    from src.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings()
    assert s.max_tokens_per_call >= 32768, (
        f"max_tokens_per_call={s.max_tokens_per_call} too low. "
        f"Both Sonnet 4.6 and Haiku 4.5 support 64K out; 32K is a safe floor "
        f"for the largest single tool argument any specialist emits."
    )


# ---------------------------------------------------------------------------
# T5: many-turn message accumulation does not silently lose history
# ---------------------------------------------------------------------------


async def test_tool_loop_25_turns_accumulates_history_correctly(monkeypatch):
    """Specialists routinely run 25-40 tool calls. Each turn appends an
    assistant message + a tool result to `msgs`. Verify the accumulation
    is correct (not dropping turns) and total token usage is summed."""
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.llm.openrouter import OpenRouterBackend

    handler = _RecordingToolHandler(return_text="ok")
    backend = OpenRouterBackend()

    # 24 tool-call turns + 1 final end_turn
    side_effects = [
        _openai_response(
            finish_reason="tool_calls",
            tool_calls=[_openai_tool_call(f"tc{i}", "write_file", '{"path": "f.md", "content": "x"}')],
            prompt_tokens=100,
            completion_tokens=50,
        )
        for i in range(24)
    ] + [_openai_response(finish_reason="stop", content="done.", prompt_tokens=200, completion_tokens=10)]
    create_mock = AsyncMock(side_effect=side_effects)
    monkeypatch.setattr(backend._client.chat.completions, "create", create_mock)

    result = await backend.tool_loop(
        system="x",
        messages=[{"role": "user", "content": "x"}],
        tools=[{"name": "write_file", "description": "x", "input_schema": {"type": "object"}}],
        tool_handler=handler,
        max_turns=30,
    )

    assert result.success
    assert result.tool_calls_made == 24, f"expected 24 tool calls (one per turn), got {result.tool_calls_made}"
    assert len(handler.calls) == 24, "handler should have been invoked once per tool call"
    # Token usage must SUM across turns, not just take the last value.
    expected_input = 100 * 24 + 200
    expected_output = 50 * 24 + 10
    assert result.usage.input_tokens == expected_input, (
        f"input tokens not accumulated: got {result.usage.input_tokens}, expected {expected_input}"
    )
    assert result.usage.output_tokens == expected_output, (
        f"output tokens not accumulated: got {result.usage.output_tokens}, expected {expected_output}"
    )
