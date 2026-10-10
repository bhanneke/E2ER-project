"""LLM module — OpenRouter backend (OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Any

from openai import AsyncOpenAI, AsyncStream

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

logger = get_logger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_EMPTY_RETRIES = 2
_loop_keys = itertools.count(1)
#: What each running loop has used so far, by loop key (recorded if the run is stopped mid-loop).
_spent: dict[int, TokenUsage] = {}
_EMPTY_BACKOFF_SECONDS = 5.0


#: A streamed call that sends nothing for this long has stalled (first chunk: the
#: provider reads the whole prompt first; later chunks: tokens arrive every second).
_FIRST_CHUNK_SECONDS = 240.0
_IDLE_SECONDS = 120.0


class _StalledError(Exception):
    """A streamed call sent nothing for too long."""


async def _collect(stream: Any) -> Any:
    """Assemble a streamed completion into the shape of a non-streamed one."""
    from types import SimpleNamespace

    text: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    finish: str | None = None
    usage: Any = None
    error: Any = None
    seen_choice = False
    it = stream.__aiter__()
    timeout = _FIRST_CHUNK_SECONDS
    while True:
        try:
            chunk = await asyncio.wait_for(it.__anext__(), timeout)
        except StopAsyncIteration:
            break
        except TimeoutError as e:
            raise _StalledError(f"no data for {timeout:.0f} s") from e
        timeout = _IDLE_SECONDS
        if getattr(chunk, "usage", None) is not None:
            usage = chunk.usage
        error = error or getattr(chunk, "error", None) or (getattr(chunk, "model_extra", None) or {}).get("error")
        for choice in getattr(chunk, "choices", None) or []:
            seen_choice = True
            delta = getattr(choice, "delta", None)
            if delta is not None:
                if getattr(delta, "content", None):
                    text.append(delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = calls.setdefault(
                        tc.index if tc.index is not None else len(calls), {"id": "", "name": "", "args": []}
                    )
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["args"].append(fn.arguments)
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason
    choices = []
    if finish == "error":
        # The provider failed mid-answer (OpenRouter sends the error in the stream).
        return SimpleNamespace(choices=[], usage=usage, error=error or "the provider failed mid-answer", model_extra={})
    if seen_choice and (text or calls or finish):
        tool_calls = [
            SimpleNamespace(
                id=c["id"] or f"call_{i}",
                type="function",
                function=SimpleNamespace(name=c["name"], arguments="".join(c["args"])),
            )
            for i, c in sorted(calls.items())
        ]
        message = SimpleNamespace(content="".join(text) or None, tool_calls=tool_calls or None)
        choices.append(
            SimpleNamespace(finish_reason=finish or ("tool_calls" if tool_calls else "stop"), message=message)
        )
    return SimpleNamespace(choices=choices, usage=usage, error=error, model_extra={})


def _int(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str]:
    """A tool call's arguments as a dict, and why they could not be read ("" when fine).

    Open models sometimes send no arguments ("" for a tool without parameters)
    or wrap them in a code fence; both are accepted.
    """
    if isinstance(raw, dict):
        return raw, ""
    text = (raw or "").strip()
    if not text:
        return {}, ""
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        return {}, str(e)
    if not isinstance(value, dict):
        return {}, f"expected an object, got {type(value).__name__}"
    return value, ""


class OpenRouterBackend(LLMBackend):
    """OpenRouter backend using the OpenAI-compatible API.

    Supports any model available on OpenRouter (Claude, GPT-4, Gemini, etc.).
    Token usage mapped from OpenAI format; no cache fields available.
    """

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self._client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=_OPENROUTER_BASE,
            default_headers={
                "HTTP-Referer": "https://github.com/bhanneke/E2ER-project",
                "X-Title": "e2er Research Pipeline",
            },
            max_retries=5,
        )
        self._model = model or settings.openrouter_model
        self._max_tokens = settings.max_tokens_per_call
        self._provider_sort = settings.openrouter_provider_sort
        # Read OpenRouter's price list once (cached for a day under ~/.e2er/cache):
        # it prices any call whose response does not report its own cost.
        from .openrouter_models import load_models

        load_models()

    def _provider_preference(self) -> dict[str, Any]:
        """OpenRouter's ``provider`` field for each call.

        ``price``: the model's providers in order of what a study's calls cost
        there (mostly cached input), with fallback to the others; OpenRouter's
        own ``sort: "price"`` when that list cannot be read.
        """
        sort = getattr(self, "_provider_sort", "")
        if not sort:
            return {}
        if sort == "price":
            from .openrouter_models import provider_order

            order = provider_order(self._model)
            if order:
                return {"order": order, "allow_fallbacks": True}
        return {"sort": sort}

    async def _create(self, create_kwargs: dict[str, Any], turn: int) -> Any:
        """One completion. The SDK retries HTTP errors itself; this also retries
        a call that stalls (see ``_collect``) and the 200 responses OpenRouter
        sends with no choices (an upstream provider failed, or an ``error``
        object in the body)."""
        last = ""
        for attempt in range(_EMPTY_RETRIES + 1):
            try:
                response = await self._complete(create_kwargs)
            except _StalledError as e:
                last = str(e)
                logger.warning("OpenRouter turn %d: %s, attempt %d", turn, last, attempt + 1)
                continue
            if response.choices:
                return response
            err = getattr(response, "error", None) or (getattr(response, "model_extra", None) or {}).get("error")
            last = str(err or "no choices in the response")
            logger.warning("OpenRouter turn %d: empty response (%s), attempt %d", turn, last, attempt + 1)
            if attempt < _EMPTY_RETRIES:
                await asyncio.sleep(_EMPTY_BACKOFF_SECONDS * (attempt + 1))
        raise RuntimeError(f"OpenRouter returned no answer after {_EMPTY_RETRIES + 1} attempts: {last}")

    async def _complete(self, create_kwargs: dict[str, Any]) -> Any:
        """The call, streamed, so a provider that stops sending is noticed.

        Without streaming a stalled call waited for the SDK's 600 s timeout and
        then ran again: three live studies on DeepSeek V4 Pro (2026-10-10) each
        lost 10 to 11 minutes to one such call. A client that answers without a
        stream (a test double) is used as is.
        """
        stream = await self._client.chat.completions.create(
            **create_kwargs, stream=True, stream_options={"include_usage": True}
        )
        if not isinstance(stream, AsyncStream):
            return stream
        try:
            return await _collect(stream)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 — closing a dead stream must not mask the result
                    pass

    def _usage_of(self, response: Any) -> TokenUsage:
        """Tokens and cost of one response.

        OpenAI-style ``prompt_tokens`` include the cached ones; they are split
        out so cache reads are not priced as fresh input. ``usage.cost`` is
        OpenRouter's own charge for the call (the provider that served it, its
        cache discount, reasoning tokens); when it is missing the call is priced
        from OpenRouter's published list or e2er's table.
        """
        u = getattr(response, "usage", None)
        if u is None:
            return TokenUsage()
        prompt = _int(getattr(u, "prompt_tokens", 0))
        completion = _int(getattr(u, "completion_tokens", 0))
        details = getattr(u, "prompt_tokens_details", None)
        cached = min(_int(getattr(details, "cached_tokens", 0)) if details is not None else 0, prompt)
        part = TokenUsage(input_tokens=prompt - cached, output_tokens=completion, cache_read_tokens=cached)
        cost = getattr(u, "cost", None)
        if cost is None:
            cost = (getattr(u, "model_extra", None) or {}).get("cost")
        from ..tracking.costs import estimate_cost

        estimate = float(estimate_cost(self._model, part))
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
            part.cost_usd = float(cost)
        elif isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost == 0 and estimate == 0:
            part.cost_usd = 0.0  # a free model
        else:
            # Missing, or a 0 for a priced model (seen from one provider on
            # 2026-10-10): count the listed price rather than nothing, so the
            # spending limit does not undercount.
            part.cost_usd = estimate
        return part

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
        tool_handler: ToolHandler | None,
        max_turns: int = 30,
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        from ..tracking.usage import loop_finished, record_cancelled_loop

        loop_key = next(_loop_keys)
        try:
            return await self._tool_loop(system, messages, tools, tool_handler, max_turns, paper_id, loop_key)
        except asyncio.CancelledError:
            # A stopped run: the runner never records this loop's usage, but it was billed.
            await record_cancelled_loop(paper_id, specialist, "openrouter", self._model, _spent.pop(loop_key, None))
            raise
        finally:
            _spent.pop(loop_key, None)
            loop_finished(paper_id, loop_key)

    async def _tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler | None,
        max_turns: int,
        paper_id: str | None,
        loop_key: int,
    ) -> ToolLoopResult:
        from ..tracking.usage import loop_over_budget

        start = time.monotonic()
        usage = TokenUsage()
        tool_calls_made = 0

        oai_tools = self._convert_tools(tools)
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]

        for turn in range(max_turns):
            over, spent, cap = await loop_over_budget(paper_id, loop_key, usage.cost_usd or 0.0)
            if over:
                logger.warning(
                    "OpenRouter turn %d: spending limit reached ($%.2f of $%.2f); stopping", turn, spent, cap
                )
                return ToolLoopResult(
                    success=False,
                    output="",
                    error=f"spending limit reached: ${spent:.2f} of ${cap:.2f}",
                    tool_calls_made=tool_calls_made,
                    usage=usage,
                    duration_seconds=time.monotonic() - start,
                    stop_reason="budget",
                )
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
                provider = self._provider_preference()
                if provider:
                    create_kwargs["extra_body"] = {"provider": provider}
                response = await self._create(create_kwargs, turn)
                logger.info(
                    "OpenRouter turn %d: response in %.1fs (finish=%s)",
                    turn,
                    time.monotonic() - t_call,
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

            usage = usage + self._usage_of(response)
            _spent[loop_key] = usage

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            msg = choice.message

            # finish_reason="length" means the model was truncated by max_tokens.
            # Looping is futile — the model will hit the same wall again. Return
            # an error so the runner can fail this specialist and either retry
            # at the orchestration level or surface a clear cap error.
            if finish_reason == "length":
                logger.warning(
                    "OpenRouter turn %d: hit max_tokens=%d (finish=length). Bailing out to avoid infinite loop.",
                    turn,
                    self._max_tokens,
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
            msgs.append(
                {
                    "role": "assistant",
                    # Coerce None → "" : when the model returns only tool calls,
                    # content is None, and some OpenAI-compatible servers reject
                    # an assistant message with content=null + tool_calls.
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in (msg.tool_calls or [])
                    ],
                }
            )

            for tc in msg.tool_calls or []:
                tool_calls_made += 1
                tool_input, bad_args = _parse_arguments(tc.function.arguments)
                logger.debug("Tool call: %s(%s)", tc.function.name, list(tool_input.keys()))
                if tool_handler is None:
                    result_text = "Tool dispatch is disabled for this call."
                elif bad_args:
                    # Do not run the tool on guessed arguments; tell the model so it resends.
                    result_text = (
                        f"Error: the arguments for {tc.function.name} were not valid JSON ({bad_args}). "
                        "Call the tool again with a single JSON object as its arguments."
                    )
                else:
                    result_text = await tool_handler.handle(tc.function.name, tool_input)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    }
                )

        return ToolLoopResult(
            success=False,
            output="",
            error=f"Reached max_turns={max_turns}",
            tool_calls_made=tool_calls_made,
            usage=usage,
            duration_seconds=time.monotonic() - start,
            stop_reason="max_turns",
        )
