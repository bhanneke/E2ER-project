"""OpenRouter tool loop: the conversation stays small, caching is asked for, each attempt is counted.

Demo 8 (2026-10-13): one data-analyst attempt on DeepSeek V4 Pro resent its
whole conversation every turn and sent 785k fresh + 8.6M cached input tokens
($1.44). All calls here are mocked; no model is called.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.modules.llm import history
from src.modules.llm.base import TokenUsage, ToolHandler, ToolLoopResult


def _chars(msgs: list[dict[str, Any]]) -> int:
    return history.history_chars(msgs)


def _resp(
    finish: str,
    *,
    content: str = "",
    calls: list[Any] | None = None,
    prompt: int = 100,
    cached: int = 0,
    written: int = 0,
    cost: float | None = None,
) -> Any:
    msg = SimpleNamespace(content=content, tool_calls=calls)
    details = SimpleNamespace(cached_tokens=cached, cache_write_tokens=written)
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=20, prompt_tokens_details=details, cost=cost)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=msg)], usage=usage, model_extra={})


def _call(i: int, name: str, args: dict[str, Any]) -> Any:
    return SimpleNamespace(id=f"c{i}", type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class _BigReads(ToolHandler):
    """Every read_file returns a 30,000-character data preview; write_file says it wrote."""

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "read_file":
            return "\n".join(f"row {i},{'x' * 50}" for i in range(500))[:30_000]
        return "written"


@pytest.fixture
def backend(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_PROVIDER_SORT", "")
    from src.config import get_settings

    get_settings.cache_clear()
    from src.modules.llm.openrouter import OpenRouterBackend

    def make(model: str = "deepseek/deepseek-v4-pro") -> Any:
        return OpenRouterBackend(model=model)

    yield make
    get_settings.cache_clear()


def _scripted(n_turns: int, sent: list[list[dict[str, Any]]], *, write_every: int = 5):
    """A model that reads a file (and now and then writes one) for ``n_turns`` turns, then stops.

    Reports input tokens as the request's characters / 4, most of them cached.
    """
    state = {"turn": 0}

    async def create(**kwargs: Any) -> Any:
        msgs = kwargs["messages"]
        sent.append(msgs)
        t = state["turn"]
        state["turn"] += 1
        prompt = _chars(msgs) // 4
        if t >= n_turns:
            return _resp("stop", content="done", prompt=prompt, cached=prompt * 9 // 10)
        if t % write_every == write_every - 1:
            call = _call(t, "write_file", {"path": f"out{t}.py", "content": "y" * 20_000})
        else:
            call = _call(t, "read_file", {"path": f"data{t}.csv"})
        return _resp("tool_calls", calls=[call], prompt=prompt, cached=prompt * 9 // 10)

    return create


async def test_history_stays_bounded_over_a_long_attempt(backend, monkeypatch):
    monkeypatch.setenv("OPENROUTER_ATTEMPT_TOKEN_BUDGET", "0")  # this test measures size, not the budget
    from src.config import get_settings

    get_settings.cache_clear()
    b = backend()
    sent: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(b._client.chat.completions, "create", AsyncMock(side_effect=_scripted(60, sent)))
    result = await b.tool_loop("system", [{"role": "user", "content": "analyse"}], [], _BigReads(), max_turns=80)
    assert result.success, result.error
    sizes = [_chars(m) for m in sent]
    # Never more than (keep_full + batch) exchanges in full, each ~30k chars.
    bound = (history.KEEP_FULL_EXCHANGES + history.COMPACT_BATCH) * 31_000 + 61 * 1_200
    assert max(sizes) < bound
    # Without summarising the 60 turns would have reached ~1.5M characters.
    unbounded = sum(30_000 if (t % 5) != 4 else 20_000 for t in range(60))
    assert max(sizes) < unbounded / 3
    assert result.summarised_exchanges > 0
    assert result.turns == 61
    assert result.peak_prompt_tokens == max(s // 4 for s in sizes)


async def test_attempt_sends_a_fraction_of_the_unbounded_tokens(backend, monkeypatch):
    """The same 60-turn task: total input tokens sent, with and without summarising."""
    monkeypatch.setenv("OPENROUTER_ATTEMPT_TOKEN_BUDGET", "0")
    from src.config import get_settings

    get_settings.cache_clear()
    b = backend()
    sent: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(b._client.chat.completions, "create", AsyncMock(side_effect=_scripted(60, sent)))
    result = await b.tool_loop("system", [{"role": "user", "content": "analyse"}], [], _BigReads(), max_turns=80)
    total = result.usage.input_tokens + result.usage.cache_read_tokens
    # Unbounded: turn t resends everything from turns 0..t-1.
    per_turn = [30_000 if (t % 5) != 4 else 20_000 for t in range(60)]
    unbounded_tokens = sum(sum(per_turn[:t]) for t in range(61)) // 4
    assert total < unbounded_tokens / 3


async def test_summarising_happens_in_batches_so_the_cached_prefix_holds(backend, monkeypatch):
    b = backend()
    sent: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(b._client.chat.completions, "create", AsyncMock(side_effect=_scripted(40, sent)))
    await b.tool_loop("system", [{"role": "user", "content": "analyse"}], [], _BigReads(), max_turns=80)
    changed = 0
    for prev, cur in zip(sent, sent[1:], strict=False):
        if cur[: len(prev)] != prev:
            changed += 1
    # The prefix changes only at a summarising step, not on every turn.
    assert 1 <= changed <= 40 // history.COMPACT_BATCH


async def test_summaries_keep_valid_tool_call_json_and_say_what_was_there(backend, monkeypatch):
    b = backend()
    sent: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(b._client.chat.completions, "create", AsyncMock(side_effect=_scripted(30, sent)))
    await b.tool_loop("system", [{"role": "user", "content": "analyse"}], [], _BigReads(), max_turns=80)
    last = sent[-1]
    for m in last:
        assert not any(k.startswith("_") for k in m), "bookkeeping keys must not reach the API"
        for tc in m.get("tool_calls") or []:
            json.loads(tc["function"]["arguments"])  # still valid JSON
    tool_texts = [m["content"] for m in last if m["role"] == "tool"]
    read_texts = [t for t in tool_texts if t != "written"]
    assert any(t.startswith("[earlier result of read_file(path=") for t in tool_texts)
    assert any(
        "characters, not repeated" in tc["function"]["arguments"] for m in last for tc in m.get("tool_calls") or []
    )
    # The last exchanges are in full.
    assert len(read_texts[-1]) > 20_000
    # The task and the system prompt are never summarised.
    assert last[0] == {"role": "system", "content": "system"} and last[1]["content"] == "analyse"


async def test_attempt_stops_plainly_at_its_token_budget(backend, monkeypatch):
    monkeypatch.setenv("OPENROUTER_ATTEMPT_TOKEN_BUDGET", "250000")
    from src.config import get_settings

    get_settings.cache_clear()
    b = backend()
    calls = 0

    async def create(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return _resp("tool_calls", calls=[_call(calls, "read_file", {"path": "a"})], prompt=100_000, cached=90_000)

    monkeypatch.setattr(b._client.chat.completions, "create", create)
    result = await b.tool_loop("s", [{"role": "user", "content": "u"}], [], _BigReads(), max_turns=30)
    assert not result.success
    assert result.stop_reason == "token_budget"
    assert calls == 3  # 300k sent after three calls; the fourth is not made
    assert "past its budget of 250,000" in (result.error or "")
    assert "OPENROUTER_ATTEMPT_TOKEN_BUDGET" in (result.error or "")


def test_long_result_is_cut_with_a_note_and_read_file_can_read_on(tmp_path):
    import asyncio

    from src.modules.llm.tools import FileToolHandler

    lines = [f"line {i}" for i in range(1, 20_001)]
    (tmp_path / "big.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    h = FileToolHandler(tmp_path)
    full = asyncio.run(h.handle("read_file", {"path": "big.txt"}))
    cut = history.cap_tool_result(full, "read_file", {"path": "big.txt"})
    assert len(cut) < len(full)
    note = cut[cut.index("[cut to save space") :]
    nxt = int(note.split("start_line=")[1].split(" ")[0])
    shown = cut[: cut.index("\n\n[cut")].splitlines()
    assert shown[-1] == f"line {nxt - 1}"
    rest = asyncio.run(h.handle("read_file", {"path": "big.txt", "start_line": nxt}))
    assert rest.splitlines()[0] == f"line {nxt}"
    # Short results are untouched.
    assert history.cap_tool_result("short", "read_file", {"path": "x"}) == "short"


# ── caching ──────────────────────────────────────────────────────────────────


async def _one_call(b: Any, monkeypatch: Any) -> dict[str, Any]:
    create = AsyncMock(return_value=_resp("stop", content="x", prompt=10))
    monkeypatch.setattr(b._client.chat.completions, "create", create)
    await b.tool_loop("system prompt", [{"role": "user", "content": "u"}], [], None)
    return create.call_args.kwargs


async def test_anthropic_models_ask_for_caching(backend, monkeypatch):
    kwargs = await _one_call(backend("anthropic/claude-sonnet-4-5"), monkeypatch)
    assert kwargs["extra_body"]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["extra_body"]["session_id"].startswith("e2er-")


async def test_deepseek_v4_caches_automatically_nothing_added(backend, monkeypatch):
    kwargs = await _one_call(backend("deepseek/deepseek-v4-pro"), monkeypatch)
    assert "cache_control" not in kwargs["extra_body"]
    assert kwargs["messages"][0] == {"role": "system", "content": "system prompt"}


async def test_explicit_block_models_get_a_system_breakpoint(backend, monkeypatch):
    kwargs = await _one_call(backend("deepseek/deepseek-v3.2"), monkeypatch)
    system = kwargs["messages"][0]
    assert system["content"] == [{"type": "text", "text": "system prompt", "cache_control": {"type": "ephemeral"}}]


async def test_caching_can_be_switched_off(backend, monkeypatch):
    monkeypatch.setenv("ENABLE_PROMPT_CACHING", "false")
    from src.config import get_settings

    get_settings.cache_clear()
    kwargs = await _one_call(backend("anthropic/claude-sonnet-4-5"), monkeypatch)
    assert "cache_control" not in kwargs["extra_body"]


# ── what an attempt used ─────────────────────────────────────────────────────


def test_cache_writes_are_split_out_of_input(backend):
    b = backend("anthropic/claude-sonnet-4-5")
    part = b._usage_of(_resp("stop", prompt=10_000, cached=6_000, written=3_000, cost=0.01))
    assert (part.input_tokens, part.cache_read_tokens, part.cache_write_tokens) == (1_000, 6_000, 3_000)
    assert part.cost_usd == 0.01


async def test_each_attempt_is_recorded_with_its_tokens_and_cost(monkeypatch):
    from src.core.specialists import base as runner

    seen: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_log_event(paper_id, event_type, *, stage=None, specialist=None, payload=None):
        seen.append((event_type, specialist, payload))

    monkeypatch.setattr("src.db.events.log_event", fake_log_event)
    result = ToolLoopResult(
        success=False,
        output="",
        stop_reason="token_budget",
        tool_calls_made=12,
        turns=13,
        peak_prompt_tokens=180_000,
        summarised_exchanges=8,
        usage=TokenUsage(input_tokens=200_000, output_tokens=9_000, cache_read_tokens=1_800_000, cost_usd=0.31),
    )
    await runner.record_attempt_usage("p1", "data_analyst", "openrouter", "deepseek/deepseek-v4-pro", result, "0.31")
    assert len(seen) == 1
    event, specialist, payload = seen[0]
    assert event == "attempt_usage" and specialist == "data_analyst"
    assert payload["turns"] == 13 and payload["cache_read_tokens"] == 1_800_000
    assert payload["peak_prompt_tokens"] == 180_000 and payload["summarised_exchanges"] == 8
    assert payload["stop_reason"] == "token_budget" and payload["cost_usd"] == "0.31"


def test_deepseek_v4_pro_fallback_price_is_openrouters_listed_one(monkeypatch):
    from decimal import Decimal

    from src.modules.llm import openrouter_models as orm
    from src.modules.tracking.costs import model_rates

    monkeypatch.setattr(orm, "load_models", lambda **_: {})
    inp, out, cache = model_rates("deepseek/deepseek-v4-pro")
    assert (inp, out) == (Decimal("0.95526"), Decimal("1.91052"))
    assert cache == Decimal("0.079605")
