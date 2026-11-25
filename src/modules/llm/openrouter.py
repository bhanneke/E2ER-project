"""LLM module — OpenRouter backend (OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import itertools
import json
import re
import time
from contextvars import ContextVar
from typing import Any

from openai import AsyncOpenAI, AsyncStream

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult
from .history import cap_tool_result, compact_history, for_request

logger = get_logger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_EMPTY_RETRIES = 2
_loop_keys = itertools.count(1)
#: What each running loop has used so far, by loop key (recorded if the run is stopped mid-loop).
_spent: dict[int, TokenUsage] = {}
_EMPTY_BACKOFF_SECONDS = 5.0
#: The usage of the answers one call discarded and asked again (empty, failed mid-stream): OpenRouter
#: bills them. Per task, so the steps that share a backend keep theirs apart (review of 2026-11-24).
_DISCARDED: ContextVar[list[Any] | None] = ContextVar("e2er_openrouter_discarded", default=None)

#: Models whose providers cache only at explicit ``cache_control`` breakpoints
#: (OpenRouter's prompt-caching guide, read 2026-10-14). Anthropic takes one
#: top-level ``cache_control`` ("automatic" mode: the breakpoint moves to the end
#: of the conversation); Alibaba's Qwen models take breakpoints on content
#: blocks. DeepSeek, OpenAI, Grok, Moonshot, Groq and Z.AI models cache
#: automatically, and Gemini 2.5+ implicitly, so nothing is added for them.
_EXPLICIT_BLOCK_CACHE = frozenset(
    {
        "deepseek/deepseek-v3.2",
        "qwen/qwen3-max",
        "qwen/qwen-plus",
        "qwen/qwen3.6-plus",
        "qwen/qwen3-coder-plus",
        "qwen/qwen3-coder-flash",
    }
)


def cache_mode(model: str) -> str:
    """How a call to ``model`` asks for prompt caching: ``top_level``, ``system_block`` or ``automatic``."""
    m = model.lower()
    if m.startswith("anthropic/"):
        return "top_level"
    if m in _EXPLICIT_BLOCK_CACHE:
        return "system_block"
    return "automatic"


def _with_system_breakpoint(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The system message as one text block with a ``cache_control`` breakpoint."""
    if not msgs or msgs[0].get("role") != "system" or not isinstance(msgs[0].get("content"), str):
        return msgs
    block = {"type": "text", "text": msgs[0]["content"], "cache_control": {"type": "ephemeral"}}
    return [{**msgs[0], "content": [block]}, *msgs[1:]]


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
    remap: dict[int, int] = {}
    reasoning: list[Any] = []
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
                details = getattr(delta, "reasoning_details", None)
                if details is None:
                    details = (getattr(delta, "model_extra", None) or {}).get("reasoning_details")
                if isinstance(details, list):
                    reasoning.extend(details)
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = calls.setdefault(_slot_of(tc, calls, remap), {"id": "", "name": "", "args": []})
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
    if seen_choice and finish is None and (text or calls):
        # The stream ended without a finish reason: cut off, not a whole answer (review 2026-11-24).
        raise _StalledError("the stream ended without a finish reason")
    if seen_choice and (text or calls or finish):
        tool_calls = [
            SimpleNamespace(
                id=c["id"] or f"call_{i}",
                type="function",
                function=SimpleNamespace(name=c["name"], arguments="".join(c["args"])),
            )
            for i, c in sorted(calls.items())
        ]
        message = SimpleNamespace(
            content="".join(text) or None,
            tool_calls=tool_calls or None,
            reasoning_details=_merge_reasoning(reasoning) or None,
        )
        choices.append(
            SimpleNamespace(finish_reason=finish or ("tool_calls" if tool_calls else "stop"), message=message)
        )
    return SimpleNamespace(choices=choices, usage=usage, error=error, model_extra={})


def _slot_of(tc: Any, calls: dict[int, dict[str, Any]], remap: dict[int, int] | None = None) -> int:
    """Which tool call a streamed fragment belongs to.

    OpenAI-style providers number the calls (``index``). Some send fragments without an index: those
    continue the call being streamed, unless they carry a new call id. Some number every call 0: a
    fragment with a new call id opens a new call there too (``remap``: index -> the call it now feeds).
    """
    new_id = getattr(tc, "id", None)
    if getattr(tc, "index", None) is not None:
        remap = {} if remap is None else remap
        idx = int(tc.index)
        slot = remap.get(idx)
        if slot is None or (new_id and calls.get(slot, {}).get("id") and calls[slot]["id"] != new_id):
            slot = max(calls, default=-1) + 1
            remap[idx] = slot
        return slot
    if not calls:
        return 0
    last = max(calls)
    if new_id and calls[last]["id"] and calls[last]["id"] != new_id:
        return last + 1
    return last


def _merge_reasoning(parts: list[Any]) -> list[Any]:
    """Streamed reasoning fragments as whole blocks, one per (index, type): their text and summary joined,
    the other fields (signature, data, id, format) as last sent. A provider streams one thinking block as
    many fragments, and only the whole block, with its signature, is valid to send back."""
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    out: list[Any] = []
    for part in parts:
        if not isinstance(part, dict):
            out.append(part)
            continue
        key = (part.get("index", 0), part.get("type"))
        block = merged.get(key)
        if block is None:
            block = merged[key] = dict(part)
            out.append(block)
            continue
        for k, v in part.items():
            if k in ("text", "summary") and isinstance(v, str):
                block[k] = (block.get(k) or "") + v
            elif v is not None:
                block[k] = v
    return out


def _reasoning_of(msg: Any) -> Any:
    """The reasoning blocks of an answer (OpenRouter's ``reasoning_details``), to send back unchanged."""
    details = getattr(msg, "reasoning_details", None)
    if details is None:
        details = (getattr(msg, "model_extra", None) or {}).get("reasoning_details")
    return details if isinstance(details, list) and details else None


#: How an answer the model's providers never sent is reported (``_create``).
STALLED_PREFIX = "OpenRouter returned no answer after"
#: The smallest output limit worth asking for when the credit left covers no more (a step writes files).
_MIN_OUTPUT_TOKENS = 2048


def _affordable(error: str) -> int | None:
    """The output tokens OpenRouter's 402 says the credit left can pay for ("can only afford N"), or None."""
    m = re.search(r"can only afford (\d+)", error)
    return int(m.group(1)) - 64 if m else None


#: The context a model needs for a study's steps (the system prompt, skills and the step's files).
MIN_CONTEXT_TOKENS = 64_000


async def _key_info(api_key: str) -> dict[str, Any] | str | None:
    """OpenRouter's answer about the key: its data, ``"rejected"`` (401), or None (offline, no answer)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{_OPENROUTER_BASE}/key", headers={"Authorization": f"Bearer {api_key}"})
    except Exception as e:  # noqa: BLE001 — offline: the calls will tell
        logger.info("OpenRouter key check not possible (%s)", type(e).__name__)
        return None
    if resp.status_code == 401:
        return "rejected"
    if resp.status_code != 200:
        return None
    try:
        data = resp.json().get("data")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


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
    Token usage mapped from OpenAI format, with cache reads and writes split
    out. The conversation is kept small (``llm/history.py``) and each attempt
    stops at ``openrouter_attempt_token_budget`` input tokens.
    """

    #: Billed per call: the study's spending limit applies to every call (strategist/engine.py).
    bills_per_call = True

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

    async def _raise_if_stalled(self, result: Any, paper_id: str | None, specialist: str | None) -> None:
        """Pause the run when the model's providers stopped answering, even the fast ones: a new attempt from the
        start would cost the step's whole conversation again and meet the same providers (live test 2026-11-25:
        three attempts of about 530,000 tokens each, then the study failed)."""
        error = str(getattr(result, "error", "") or "")
        if getattr(result, "success", True) or not error.startswith(STALLED_PREFIX):
            return
        from ..tracking.usage import record_cancelled_loop
        from .plan_limit import CallTimedOutError

        await record_cancelled_loop(paper_id, specialist, "openrouter", self._model, getattr(result, "usage", None))
        status = (
            f"Paused: OpenRouter's providers of {self._model} stopped answering ({error.split(': ', 1)[-1]}), "
            "the fastest ones too. Nothing is lost: press Resume to try this step again, now or later, or choose "
            "another model (OPENROUTER_MODEL)."
        )
        raise CallTimedOutError("openrouter", error, status, specialist=specialist)

    async def preflight(self) -> None:
        """Before a run's first step: stop when the key, the model or its limits cannot run a study.

        Checks the key with OpenRouter (``/api/v1/key``: accepted, its own spending limit not used up; the
        account's credit shows at the first call, which pauses the run when it is empty), and in OpenRouter's model
        list that the model exists, can call tools, and has room for a study's prompts; lowers the output
        limit per call to what the model allows. Offline or when OpenRouter does not answer, the run goes
        on and the calls report what is wrong. Raises :class:`BackendSetupError` (the run pauses).
        """
        from .openrouter_models import find_model
        from .plan_limit import SETUP_TAIL, BackendSetupError

        def stop(status: str, message: str = "") -> BackendSetupError:
            logger.error("OpenRouter check before the run: %s", status)
            return BackendSetupError("openrouter", message or status, f"Stopped before the first step: {status}")

        key = await _key_info(self._client.api_key)
        if key == "rejected":
            raise stop(
                "OpenRouter does not accept the key (401). Check OPENROUTER_API_KEY in the settings. " + SETUP_TAIL
            )
        if isinstance(key, dict):
            remaining = key.get("limit_remaining")
            if isinstance(remaining, (int, float)) and remaining <= 0:
                from .plan_limit import detect_billing

                limit = detect_billing("openrouter", "key limit exceeded (OpenRouter /key: limit_remaining 0)")
                if limit is not None:
                    raise limit
        model = await asyncio.to_thread(find_model, self._model, network=True)
        if model is None:
            logger.warning(
                "OpenRouter check: %s is not in OpenRouter's model list (offline?); the calls will tell", self._model
            )
            return
        if not model.tools:
            raise stop(
                f"{self._model} cannot call tools on OpenRouter, and every step of a study needs them. Choose a "
                "model that can (the setup page lists them) and set OPENROUTER_MODEL. " + SETUP_TAIL
            )
        if model.context_length and model.context_length < MIN_CONTEXT_TOKENS:
            raise stop(
                f"{self._model} reads at most {model.context_length:,} tokens at once, and a study's steps need "
                f"{MIN_CONTEXT_TOKENS:,}. Choose a model with a longer context and set OPENROUTER_MODEL. " + SETUP_TAIL
            )
        cap = model.max_completion_tokens or 0
        if model.context_length:
            cap = min(cap or model.context_length, model.context_length // 2)
        if cap and self._max_tokens > cap:
            logger.info(
                "OpenRouter: %s writes at most %d tokens per call; using that instead of %d",
                self._model,
                cap,
                self._max_tokens,
            )
            self._max_tokens = cap
        logger.info(
            "OpenRouter check passed: %s (tools, %s tokens of context, %d output tokens per call)",
            self._model,
            f"{model.context_length:,}",
            self._max_tokens,
        )

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
                # A stall is no error to OpenRouter, so it does not fall back by itself: ask the model's fast
                # providers from now on, for the rest of the run (live test 2026-11-25: the cheapest DeepSeek
                # provider sent nothing for 120 s, three times on the same call).
                if self._provider_sort != "throughput":
                    logger.warning("OpenRouter: %s stalled; asking its fastest providers from now on", self._model)
                    self._provider_sort = "throughput"
                extra = dict(create_kwargs.get("extra_body") or {})
                extra["provider"] = self._provider_preference()
                create_kwargs = {**create_kwargs, "extra_body": extra}
                continue
            if response.choices:
                return response
            wasted = _DISCARDED.get()
            if wasted is not None and getattr(response, "usage", None) is not None:
                wasted.append(response)
            err = getattr(response, "error", None) or (getattr(response, "model_extra", None) or {}).get("error")
            last = str(err or "no choices in the response")
            logger.warning("OpenRouter turn %d: empty response (%s), attempt %d", turn, last, attempt + 1)
            if attempt < _EMPTY_RETRIES:
                await asyncio.sleep(_EMPTY_BACKOFF_SECONDS * (attempt + 1))
        raise RuntimeError(f"{STALLED_PREFIX} {_EMPTY_RETRIES + 1} attempts: {last}")

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
        # Tokens written to the cache (Anthropic, Qwen, GPT-5.6+): part of prompt_tokens, priced higher.
        written = min(_int(getattr(details, "cache_write_tokens", 0)) if details is not None else 0, prompt - cached)
        part = TokenUsage(
            input_tokens=prompt - cached - written,
            output_tokens=completion,
            cache_read_tokens=cached,
            cache_write_tokens=written,
        )
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
        from .plan_limit import raise_if_billing

        loop_key = next(_loop_keys)
        try:
            result = await self._tool_loop(system, messages, tools, tool_handler, max_turns, paper_id, loop_key)
            # No credits, or the key's spending limit: the run pauses (like a plan's limit) instead of failing.
            await raise_if_billing("openrouter", self._model, result, paper_id, specialist)
            await self._raise_if_stalled(result, paper_id, specialist)
            return result
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
        turns = 0
        peak_prompt = 0
        summarised = 0
        settings = get_settings()
        token_budget = max(0, int(getattr(settings, "openrouter_attempt_token_budget", 0) or 0))
        caching = bool(getattr(settings, "enable_prompt_caching", True))
        mode = cache_mode(self._model) if caching else "automatic"
        # One session per attempt: OpenRouter keeps the attempt's calls on the
        # provider that holds its cache (unless a provider order is set).
        session_id = f"e2er-{paper_id or 'call'}-{loop_key}-{int(time.time())}"[:256]

        def _result(success: bool, output: str, error: str | None, stop_reason: str) -> ToolLoopResult:
            return ToolLoopResult(
                success=success,
                output=output,
                error=error,
                tool_calls_made=tool_calls_made,
                usage=usage,
                duration_seconds=time.monotonic() - start,
                stop_reason=stop_reason,
                turns=turns,
                peak_prompt_tokens=peak_prompt,
                summarised_exchanges=summarised,
            )

        oai_tools = self._convert_tools(tools)
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]
        # The step's time limit, as the CLI backends have it (template, step, else SPECIALIST_TIMEOUT).
        from .cli_support import effective_timeout

        time_limit = effective_timeout(int(getattr(settings, "specialist_timeout", 3600) or 3600))
        max_tokens = self._max_tokens
        lowered = False

        for turn in range(max_turns):
            over, spent, cap = await loop_over_budget(paper_id, loop_key, usage.cost_usd or 0.0)
            if over:
                logger.warning(
                    "OpenRouter turn %d: spending limit reached ($%.2f of $%.2f); stopping", turn, spent, cap
                )
                return _result(False, "", f"spending limit reached: ${spent:.2f} of ${cap:.2f}", "budget")
            if time_limit and time.monotonic() - start > time_limit:
                logger.warning(
                    "OpenRouter turn %d: the step's time limit (%d s) is used up; stopping", turn, time_limit
                )
                return _result(
                    False, "", f"the step ran into its time limit {time_limit}s after {turns} calls", "timeout"
                )
            sent = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
            if token_budget and sent >= token_budget:
                logger.warning(
                    "OpenRouter turn %d: attempt token budget used (%d of %d); stopping", turn, sent, token_budget
                )
                return _result(
                    False,
                    "",
                    (
                        f"this attempt sent {sent:,} input tokens over {turns} calls, past its budget of "
                        f"{token_budget:,}; it was stopped so it does not cost more. Work in smaller steps "
                        "(write intermediate results to files), or raise OPENROUTER_ATTEMPT_TOKEN_BUDGET."
                    ),
                    "token_budget",
                )
            msgs, n_summarised = compact_history(msgs)
            if n_summarised:
                summarised += n_summarised
                logger.info("OpenRouter turn %d: summarised %d older tool exchanges", turn, n_summarised)
            t_call = time.monotonic()
            logger.info("OpenRouter turn %d: calling %s (msgs=%d)", turn, self._model, len(msgs))
            try:
                # OpenAI SDK requires omitting `tools` entirely when there are
                # none — passing an empty list, None, or NOT_GIVEN can error
                # depending on SDK version. Build kwargs conditionally.
                request_msgs = for_request(msgs)
                if mode == "system_block":
                    request_msgs = _with_system_breakpoint(request_msgs)
                create_kwargs: dict[str, Any] = {
                    "model": self._model,
                    "messages": request_msgs,
                    "max_tokens": max_tokens,
                }
                if oai_tools:
                    create_kwargs["tools"] = oai_tools
                extra: dict[str, Any] = {"session_id": session_id}
                provider = self._provider_preference()
                if provider:
                    extra["provider"] = provider
                if mode == "top_level":
                    extra["cache_control"] = {"type": "ephemeral"}
                create_kwargs["extra_body"] = extra
                turns += 1
                discarded: list[Any] = []
                discard_token = _DISCARDED.set(discarded)
                try:
                    response = await self._create(create_kwargs, turn)
                finally:
                    _DISCARDED.reset(discard_token)
                    for lost in discarded:
                        usage = usage + self._usage_of(lost)
                    _spent[loop_key] = usage
                logger.info(
                    "OpenRouter turn %d: response in %.1fs (finish=%s)",
                    turn,
                    time.monotonic() - t_call,
                    response.choices[0].finish_reason if response.choices else "?",
                )
            except Exception as e:
                afford = _affordable(str(e))
                if afford and not lowered and _MIN_OUTPUT_TOKENS <= afford < max_tokens:
                    # "This request requires more credits, or fewer max_tokens ... can only afford N": the
                    # credit left covers a shorter answer. Ask for that once, instead of pausing the run.
                    logger.warning("OpenRouter turn %d: credit covers %d output tokens; asking for that", turn, afford)
                    max_tokens, lowered = afford, True
                    continue
                logger.error("OpenRouter error on turn %d: %s", turn, e)
                return _result(False, "", str(e), "end_turn")

            part = self._usage_of(response)
            usage = usage + part
            _spent[loop_key] = usage
            peak_prompt = max(peak_prompt, part.input_tokens + part.cache_read_tokens + part.cache_write_tokens)
            logger.info(
                "OpenRouter turn %d: %d fresh + %d cached + %d cache-write input, %d output tokens",
                turn,
                part.input_tokens,
                part.cache_read_tokens,
                part.cache_write_tokens,
                part.output_tokens,
            )

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            msg = choice.message

            # finish_reason="length" means the model was truncated by max_tokens.
            # Looping is futile — the model will hit the same wall again. Return
            # an error so the runner can fail this specialist and either retry
            # at the orchestration level or surface a clear cap error.
            if finish_reason == "length" and lowered:
                # The output limit came down to what the credit pays for, and the answer needs more: a
                # refusal for money after all, so the run pauses at the billing limit (review 2026-11-24).
                return _result(
                    False,
                    msg.content or "",
                    f"OpenRouter: the credit left can only afford {max_tokens} output tokens per call, "
                    "too few for this step; error code: 402",
                    "end_turn",
                )
            if finish_reason == "length":
                logger.warning(
                    "OpenRouter turn %d: hit max_tokens=%d (finish=length). Bailing out to avoid infinite loop.",
                    turn,
                    max_tokens,
                )
                return _result(
                    False,
                    msg.content or "",
                    (
                        f"max_tokens={max_tokens} too low — model output truncated. "
                        "Increase max_tokens_per_call in settings."
                    ),
                    "length",
                )

            # The calls decide, not the finish reason: some providers report "stop" with tool calls.
            if not msg.tool_calls:
                return _result(True, msg.content or "", None, "end_turn")

            # Execute tool calls
            assistant: dict[str, Any] = {
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
            details = _reasoning_of(msg)
            if details:
                # Reasoning models (Gemini 3, o-series, Claude with thinking) need their reasoning back
                # with the tool results, or the next turn loses it or is refused.
                assistant["reasoning_details"] = details
            msgs.append(assistant)

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
                    result_text = cap_tool_result(result_text, tc.function.name, tool_input)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    }
                )

        return _result(False, "", f"Reached max_turns={max_turns}", "max_turns")
