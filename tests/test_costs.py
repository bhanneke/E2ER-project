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
