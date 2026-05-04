"""LLM module — OpenRouter backend (OpenAI-compatible API)."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from openai import AsyncOpenAI

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, ToolHandler, ToolLoopResult, TokenUsage

logger = get_logger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterBackend(LLMBackend):
    """OpenRouter backend using the OpenAI-compatible API.

    Supports any model available on OpenRouter (Claude, GPT-4, Gemini, etc.).
    Token usage mapped from OpenAI format; no cache fields available.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self._client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=_OPENROUTER_BASE,
            default_headers={
                "HTTP-Referer": "https://github.com/bhanneke/E2ER-project",
                "X-Title": "E2ER Research Pipeline",
            },
        )
        self._model = settings.openrouter_model

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic-format tools to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

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

        oai_tools = self._convert_tools(tools)
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]

        for turn in range(max_turns):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=msgs,  # type: ignore[arg-type]
                    tools=oai_tools if oai_tools else openai_NOT_GIVEN,  # type: ignore[arg-type]
                    max_tokens=8192,
                )
            except Exception as e:
                logger.error("OpenRouter error on turn %d: %s", turn, e)
                return ToolLoopResult(
                    success=False,
                    output="",
                    error=str(e),
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                )

            # Accumulate usage
            if response.usage:
                usage = usage + TokenUsage(
                    input_tokens=response.usage.prompt_tokens or 0,
                    output_tokens=response.usage.completion_tokens or 0,
                )

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            msg = choice.message

            if finish_reason == "stop" or (finish_reason != "tool_calls" and not msg.tool_calls):
                return ToolLoopResult(
                    success=True,
                    output=msg.content or "",
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                    stop_reason="end_turn",
                )

            # Execute tool calls
            msgs.append({"role": "assistant", "content": msg.content, "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (msg.tool_calls or [])
            ]})

            for tc in msg.tool_calls or []:
                tool_calls_made += 1
                import json
                try:
                    tool_input = json.loads(tc.function.arguments)
                except Exception:
                    tool_input = {}
                logger.debug("Tool call: %s(%s)", tc.function.name, list(tool_input.keys()))
                result_text = await tool_handler.handle(tc.function.name, tool_input)
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        return ToolLoopResult(
            success=False,
            output="",
            error=f"Reached max_turns={max_turns}",
            tool_calls_made=tool_calls_made,
            usage=usage,
            duration_seconds=time.monotonic() - start,
            stop_reason="max_turns",
        )
