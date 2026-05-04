"""LLM module — Anthropic API backend with prompt caching and tool-use loop."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import anthropic

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, ToolHandler, ToolLoopResult, TokenUsage

logger = get_logger(__name__)

_CACHE_THRESHOLD_CHARS = 4000  # only cache if system prompt is substantial


class AnthropicBackend(LLMBackend):
    """Anthropic API backend.

    Runs a multi-turn tool-use loop. Accumulates TokenUsage across all turns.
    Applies prompt caching to the system prompt when enabled.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model
        self._caching = settings.enable_prompt_caching

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler,
        max_turns: int = 30,
    ) -> ToolLoopResult:
        start = time.monotonic()
        usage = TokenUsage()
        tool_calls_made = 0
        msgs = list(messages)

        # Build system with optional cache_control
        system_content: list[dict[str, Any]] | str
        if self._caching and len(system) >= _CACHE_THRESHOLD_CHARS:
            system_content = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_content = system

        # Cache first user message if it's large repeated context
        if self._caching and msgs and isinstance(msgs[0].get("content"), str):
            first_content = msgs[0]["content"]
            if len(first_content) >= _CACHE_THRESHOLD_CHARS:
                msgs[0] = {
                    **msgs[0],
                    "content": [
                        {
                            "type": "text",
                            "text": first_content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }

        for turn in range(max_turns):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=8192,
                    system=system_content,  # type: ignore[arg-type]
                    messages=msgs,
                    tools=tools,  # type: ignore[arg-type]
                )
            except anthropic.APIError as e:
                logger.error("Anthropic API error on turn %d: %s", turn, e)
                return ToolLoopResult(
                    success=False,
                    output="",
                    error=str(e),
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                )

            # Accumulate usage
            u = response.usage
            usage = usage + TokenUsage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            )

            # Extract text output
            text_output = " ".join(
                b.text for b in response.content if hasattr(b, "text")
            )

            if response.stop_reason == "end_turn":
                return ToolLoopResult(
                    success=True,
                    output=text_output,
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                    stop_reason="end_turn",
                )

            if response.stop_reason != "tool_use":
                return ToolLoopResult(
                    success=False,
                    output=text_output,
                    error=f"Unexpected stop_reason: {response.stop_reason}",
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                    stop_reason=response.stop_reason or "unknown",
                )

            # Execute tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_calls_made += 1
                logger.debug("Tool call: %s(%s)", block.name, list(block.input.keys()))
                result_text = await tool_handler.handle(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            # Append assistant turn + tool results
            msgs.append({"role": "assistant", "content": response.content})
            msgs.append({"role": "user", "content": tool_results})

        return ToolLoopResult(
            success=False,
            output="",
            error=f"Reached max_turns={max_turns} without end_turn",
            tool_calls_made=tool_calls_made,
            usage=usage,
            duration_seconds=time.monotonic() - start,
            stop_reason="max_turns",
        )
