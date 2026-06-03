"""Tests for token cost computation."""

from decimal import Decimal

from src.modules.llm.base import TokenUsage
from src.modules.tracking.costs import compute_cost


def test_basic_cost_computation():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = compute_cost("claude-sonnet-4-5", usage)
    assert cost == Decimal("18.00")  # $3 input + $15 output per million


def test_cache_read_discounted():
    usage = TokenUsage(input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000)
    cost = compute_cost("claude-sonnet-4-5", usage)
    assert cost == Decimal("0.30")  # 10% of $3/M = $0.30


def test_cache_write_premium():
    usage = TokenUsage(input_tokens=0, output_tokens=0, cache_write_tokens=1_000_000)
    cost = compute_cost("claude-sonnet-4-5", usage)
    assert cost == Decimal("3.75")  # 125% of $3/M = $3.75


def test_token_usage_addition():
    a = TokenUsage(input_tokens=100, output_tokens=200)
    b = TokenUsage(input_tokens=50, output_tokens=75, cache_read_tokens=100)
    c = a + b
    assert c.input_tokens == 150
    assert c.output_tokens == 275
    assert c.cache_read_tokens == 100


def test_total_tokens():
    usage = TokenUsage(input_tokens=100, output_tokens=200, cache_read_tokens=50)
    assert usage.total_tokens == 350


# ── Flat-rate backends return zero (M4 finding #1) ──────────────────────────


def test_claude_code_backend_zeros_cost():
    # The same usage that costs $18.00 on the anthropic SDK backend
    # must cost $0 on the claude_code CLI backend (Max-plan flat-rate).
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    sdk_cost = compute_cost("claude-sonnet-4-5", usage, backend="anthropic")
    cli_cost = compute_cost("claude-sonnet-4-5", usage, backend="claude_code")
    assert sdk_cost == Decimal("18.00")
    assert cli_cost == Decimal("0")


def test_codex_backend_zeros_cost():
    usage = TokenUsage(input_tokens=5_000_000, output_tokens=1_000_000)
    assert compute_cost("anything", usage, backend="codex") == Decimal("0")


def test_gemini_backend_zeros_cost():
    usage = TokenUsage(input_tokens=10_000_000, output_tokens=10_000_000, cache_read_tokens=5_000_000)
    assert compute_cost("google/gemini-pro-1.5", usage, backend="gemini") == Decimal("0")


def test_unknown_backend_falls_back_to_sdk_pricing():
    # Defensive: an unrecognised backend literal should not silently
    # zero costs. We compute SDK rates so a configuration typo
    # surfaces as "too expensive" not "free".
    usage = TokenUsage(input_tokens=1_000_000)
    assert compute_cost("claude-sonnet-4-5", usage, backend="some-other") == Decimal("3.00")


def test_backend_none_preserves_legacy_behaviour():
    # All existing tests call without the backend kwarg; default must
    # match the pre-M4.1 numbers exactly.
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert compute_cost("claude-sonnet-4-5", usage) == Decimal("18.00")
