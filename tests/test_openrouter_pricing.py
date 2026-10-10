"""OpenRouter: real cost from the response, prices from OpenRouter's list, the setup picker.

Found on the first live run with an open model (DeepSeek V4 Pro, 2026-10-10):
the cost table had no DeepSeek entry, so every call was priced at the $3/$15
guess, 10-40x what OpenRouter billed, and the spending limit would have
stopped a study that had spent a few cents.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.modules.llm import openrouter_models as orm
from src.modules.llm.base import TokenUsage, ToolHandler
from src.modules.tracking.costs import compute_cost, estimate_cost

_PAYLOAD = {
    "data": [
        {
            "id": "deepseek/deepseek-v4-pro",
            "name": "DeepSeek: DeepSeek V4 Pro",
            "pricing": {"prompt": "0.00000022794", "completion": "0.00000045588", "input_cache_read": "0.000000019"},
            "context_length": 1048576,
            "supported_parameters": ["tools", "max_tokens"],
        },
        {
            "id": "anthropic/claude-sonnet-4.5",
            "name": "Anthropic: Claude Sonnet 4.5",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
            "supported_parameters": ["tools"],
        },
        {
            "id": "some/text-only",
            "name": "Some: Text Only",
            "pricing": {"prompt": "0.0000001", "completion": "0.0000001"},
            "supported_parameters": ["max_tokens"],
        },
        {
            "id": "openrouter/auto",
            "name": "Auto Router",
            "pricing": {"prompt": "-1", "completion": "-1"},
            "supported_parameters": ["tools"],
        },
    ]
}


@pytest.fixture
def listed(monkeypatch):
    """OpenRouter's list as if fetched at the start of the run."""
    monkeypatch.setattr(orm, "_fetch", lambda: orm.parse_models(_PAYLOAD))
    orm._reset_for_tests()
    orm.load_models()
    yield
    orm._reset_for_tests()


# ── the list ─────────────────────────────────────────────────────────────────


def test_parse_models_prices_per_million_and_tool_support():
    models = orm.parse_models(_PAYLOAD)
    ds = models["deepseek/deepseek-v4-pro"]
    assert ds.rates() == (Decimal("0.22794"), Decimal("0.45588"), Decimal("0.019"))
    assert ds.tools is True
    assert models["some/text-only"].tools is False
    # A router's "-1" is not a price.
    assert models["openrouter/auto"].rates() is None
    assert ds.price_label() == "$0.23 in / $0.46 out per million tokens"


def test_list_is_cached_and_read_back_without_network(monkeypatch, listed):
    assert orm.cache_file().is_file()
    orm._reset_for_tests()
    monkeypatch.setattr(orm, "_fetch", lambda: pytest.fail("a fresh cache must not be fetched again"))
    assert "deepseek/deepseek-v4-pro" in orm.load_models()


def test_stale_cache_is_used_when_offline(monkeypatch, listed):
    raw = json.loads(orm.cache_file().read_text())
    raw["fetched_at"] = time.time() - 3 * 24 * 3600
    orm.cache_file().write_text(json.dumps(raw))
    orm._reset_for_tests()
    monkeypatch.setattr(orm, "_fetch", lambda: None)
    assert "deepseek/deepseek-v4-pro" in orm.load_models()


def test_no_list_no_cache_is_empty_not_an_error():
    assert orm.load_models() == {}
    assert orm.model_rates("deepseek/deepseek-v4-pro") is None


# ── costs ────────────────────────────────────────────────────────────────────


def test_reported_cost_wins_over_token_pricing():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, cost_usd=0.0123)
    assert compute_cost("deepseek/deepseek-v4-pro", usage, backend="openrouter") == Decimal("0.012300")
    # Flat-rate backends stay at $0 whatever was reported.
    assert compute_cost("x", usage, backend="claude_code") == Decimal("0")


def test_openrouter_model_priced_from_the_list_not_the_guess(listed):
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate_cost("deepseek/deepseek-v4-pro", usage) == Decimal("0.683820")


def test_deepseek_has_a_table_price_offline():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    # Not the $3/$15 guess ($18).
    assert estimate_cost("deepseek/deepseek-v4-pro", usage) < Decimal("1")


def test_token_usage_sums_reported_cost():
    a = TokenUsage(input_tokens=1, cost_usd=0.5)
    assert (a + TokenUsage(output_tokens=2, cost_usd=0.25)).cost_usd == 0.75
    assert (TokenUsage() + TokenUsage()).cost_usd is None


# ── the backend ──────────────────────────────────────────────────────────────


class _Recorder(ToolHandler):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def handle(self, tool_name, tool_input):
        self.calls.append((tool_name, tool_input))
        return "ok"


def _resp(finish, *, content="", tool_calls=None, usage=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=msg)], usage=usage)


def _usage(prompt, completion, *, cached=0, cost=None):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        cost=cost,
    )


def _tc(tid, name, args):
    return SimpleNamespace(id=tid, function=SimpleNamespace(name=name, arguments=args))


@pytest.fixture
def backend(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    from src.config import get_settings

    get_settings.cache_clear()
    from src.modules.llm.openrouter import OpenRouterBackend

    b = OpenRouterBackend(model="deepseek/deepseek-v4-pro")
    yield b
    get_settings.cache_clear()


async def test_usage_records_openrouter_cost_and_cached_tokens(backend, monkeypatch):
    create = AsyncMock(
        side_effect=[
            _resp(
                "tool_calls", tool_calls=[_tc("a", "write_file", "{}")], usage=_usage(1000, 50, cached=800, cost=0.001)
            ),
            _resp("stop", content="done", usage=_usage(1200, 10, cost=0.002)),
        ]
    )
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    r = await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], _Recorder())
    assert r.success
    assert r.usage.input_tokens == 200 + 1200
    assert r.usage.cache_read_tokens == 800
    assert r.usage.cost_usd == pytest.approx(0.003)
    assert compute_cost("deepseek/deepseek-v4-pro", r.usage, backend="openrouter") == Decimal("0.003000")


async def test_usage_without_reported_cost_is_priced_per_response(backend, monkeypatch):
    create = AsyncMock(return_value=_resp("stop", content="x", usage=_usage(1_000_000, 0)))
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    r = await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], None)
    assert r.usage.cost_usd is not None and r.usage.cost_usd < 1.0  # not the $3 guess


async def test_empty_response_is_retried(backend, monkeypatch):
    monkeypatch.setattr("src.modules.llm.openrouter._EMPTY_BACKOFF_SECONDS", 0)
    empty = SimpleNamespace(choices=[], usage=None, error={"message": "upstream failed"})
    create = AsyncMock(side_effect=[empty, _resp("stop", content="ok", usage=_usage(1, 1, cost=0.0))])
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    r = await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], None)
    assert r.success and r.output == "ok"
    assert create.call_count == 2


async def test_empty_responses_give_up_with_a_clear_error(backend, monkeypatch):
    monkeypatch.setattr("src.modules.llm.openrouter._EMPTY_BACKOFF_SECONDS", 0)
    empty = SimpleNamespace(choices=None, usage=None, error={"message": "upstream failed"})
    create = AsyncMock(return_value=empty)
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    r = await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], None)
    assert not r.success
    assert "upstream failed" in (r.error or "")


async def test_invalid_tool_arguments_go_back_to_the_model(backend, monkeypatch):
    handler = _Recorder()
    create = AsyncMock(
        side_effect=[
            _resp(
                "tool_calls",
                tool_calls=[
                    _tc("a", "write_file", '{"path": "x.md", "content": "unterminated'),
                    _tc("b", "list_directory", ""),
                ],
                usage=_usage(1, 1, cost=0.0),
            ),
            _resp("stop", content="done", usage=_usage(1, 1, cost=0.0)),
        ]
    )
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    r = await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], handler)
    assert r.success
    # The broken call was not run on guessed arguments; the empty one ran with {}.
    assert handler.calls == [("list_directory", {})]
    tool_msgs = [m for m in create.call_args_list[1].kwargs["messages"] if m.get("role") == "tool"]
    assert "not valid JSON" in tool_msgs[0]["content"]


def test_fenced_arguments_are_accepted():
    from src.modules.llm.openrouter import _parse_arguments

    assert _parse_arguments('```json\n{"a": 1}\n```') == ({"a": 1}, "")
    assert _parse_arguments("[1]")[1]


# ── the setup page ───────────────────────────────────────────────────────────


def test_setup_offers_tool_models_with_price(listed):
    from src.doctor import openrouter_models

    models = openrouter_models()
    ids = [m for m, _ in models]
    assert "some/text-only" not in ids  # cannot call tools
    assert ids[0] == "anthropic/claude-sonnet-4.5"  # suggestions first
    label = dict(models)["deepseek/deepseek-v4-pro"]
    assert "$0.23 in / $0.46 out per million tokens" in label


def test_setup_keeps_the_model_in_use():
    from src.doctor import openrouter_models

    ids = [m for m, _ in openrouter_models("vendor/retired-model")]
    assert ids[0] == "vendor/retired-model"
    assert "anthropic/claude-sonnet-4-5" in ids  # offline: the fixed suggestions


def test_setup_saves_an_open_model(listed, tmp_path):
    from src.api.setup import SaveSetup, build_env

    body, _ = build_env(
        SaveSetup(backend="openrouter", model="deepseek/deepseek-v4-pro", api_key="sk-or-x"), {}, tmp_path
    )
    assert "OPENROUTER_MODEL=deepseek/deepseek-v4-pro" in body


def test_settings_spelling_of_a_listed_model_is_found(listed):
    """e2er's default is anthropic/claude-sonnet-4-5; OpenRouter lists anthropic/claude-sonnet-4.5."""
    from src.doctor import openrouter_models

    assert orm.model_rates("anthropic/claude-sonnet-4-5") == (Decimal("3"), Decimal("15"), None)
    first = openrouter_models("anthropic/claude-sonnet-4-5")[0]
    assert first[0] == "anthropic/claude-sonnet-4-5"
    assert "Claude Sonnet 4.5" in first[1] and "not in OpenRouter" not in first[1]


def test_batch_variants_are_not_offered(monkeypatch):
    payload = {"data": [{"id": "x/m:batch", "name": "M (batch)", "pricing": {}, "supported_parameters": ["tools"]}]}
    monkeypatch.setattr(orm, "_fetch", lambda: orm.parse_models(payload))
    assert orm.tool_models() == []


async def test_calls_ask_for_the_cheapest_provider(backend, monkeypatch):
    create = AsyncMock(return_value=_resp("stop", content="x", usage=_usage(1, 1, cost=0.0001)))
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], None)
    assert create.call_args.kwargs["extra_body"] == {"provider": {"sort": "price"}}


async def test_provider_sort_can_be_left_to_openrouter(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_PROVIDER_SORT", "")
    from src.config import get_settings

    get_settings.cache_clear()
    from src.modules.llm.openrouter import OpenRouterBackend

    b = OpenRouterBackend(model="deepseek/deepseek-v4-pro")
    create = AsyncMock(return_value=_resp("stop", content="x", usage=_usage(1, 1, cost=0.0001)))
    monkeypatch.setattr(b._client.chat.completions, "create", create)
    await b.tool_loop("s", [{"role": "user", "content": "u"}], [], None)
    assert "extra_body" not in create.call_args.kwargs
    get_settings.cache_clear()


async def test_zero_cost_for_a_priced_model_counts_the_listed_price(backend, monkeypatch):
    create = AsyncMock(return_value=_resp("stop", content="x", usage=_usage(1_000_000, 0, cost=0)))
    monkeypatch.setattr(backend._client.chat.completions, "create", create)
    r = await backend.tool_loop("s", [{"role": "user", "content": "u"}], [], None)
    assert r.usage.cost_usd and r.usage.cost_usd > 0.1
