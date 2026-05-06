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
            max_retries=5,
        )
        self._model = settings.openrouter_model
        self._max_tokens = settings.max_tokens_per_call

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
            t_call = time.monotonic()
            logger.info("OpenRouter turn %d: calling %s (msgs=%d)", turn, self._model, len(msgs))
            try:
                # OpenAI SDK requires omitting `tools` entirely when there are
                # none — passing an empty list, None, or NOT_GIVEN can error
                # depending on SDK version. Build kwargs conditionally.
                create_kwargs: dict[str, Any] = {
                    "model": self._model,
                    "messages": msgs,
                    "max_tokens": self._max_tokens,
                }
                if oai_tools:
                    create_kwargs["tools"] = oai_tools
                response = await self._client.chat.completions.create(**create_kwargs)
                logger.info(
                    "OpenRouter turn %d: response in %.1fs (finish=%s)",
                    turn, time.monotonic() - t_call,
                    response.choices[0].finish_reason if response.choices else "?",
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

            # finish_reason="length" means the model was truncated by max_tokens.
            # Looping is futile — the model will hit the same wall again. Return
            # an error so the runner can fail this specialist and either retry
            # at the orchestration level or surface a clear cap error.
            if finish_reason == "length":
                logger.warning(
                    "OpenRouter turn %d: hit max_tokens=%d (finish=length). "
                    "Bailing out to avoid infinite loop.",
                    turn, self._max_tokens,
                )
                return ToolLoopResult(
                    success=False,
                    output=msg.content or "",
                    error=(
                        f"max_tokens={self._max_tokens} too low — model output truncated. "
                        "Increase max_tokens_per_call in settings."
                    ),
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                    stop_reason="length",
                )

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
