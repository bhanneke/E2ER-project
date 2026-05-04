"""Token cost estimation per model."""
from __future__ import annotations

from decimal import Decimal

from ..llm.base import TokenUsage

# Cost per million tokens (input, output) in USD
_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # Anthropic
    "claude-opus-4-7": (Decimal("15"), Decimal("75")),
    "claude-opus-4-5": (Decimal("15"), Decimal("75")),
    "claude-sonnet-4-5": (Decimal("3"), Decimal("15")),
    "claude-haiku-4-5": (Decimal("0.8"), Decimal("4")),
    "claude-sonnet-4-6": (Decimal("3"), Decimal("15")),
    # OpenRouter aliases
    "anthropic/claude-opus-4-7": (Decimal("15"), Decimal("75")),
    "anthropic/claude-sonnet-4-5": (Decimal("3"), Decimal("15")),
    "anthropic/claude-haiku-4-5": (Decimal("0.8"), Decimal("4")),
    "openai/gpt-4o": (Decimal("5"), Decimal("15")),
    "openai/gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "google/gemini-pro-1.5": (Decimal("1.25"), Decimal("5")),
}

_MILLION = Decimal("1_000_000")
_CACHE_READ_MULT = Decimal("0.1")    # cache reads: 10% of input price
_CACHE_WRITE_MULT = Decimal("1.25")  # cache writes: 125% of input price
_DEFAULT_INPUT = Decimal("3")
_DEFAULT_OUTPUT = Decimal("15")


def compute_cost(model: str, usage: TokenUsage) -> Decimal:
    """Estimate USD cost for a token usage record."""
    model_key = model.lower()
    input_rate, output_rate = _PRICING.get(model_key, (_DEFAULT_INPUT, _DEFAULT_OUTPUT))

    cost = (
        Decimal(usage.input_tokens) * input_rate / _MILLION
        + Decimal(usage.output_tokens) * output_rate / _MILLION
        + Decimal(usage.cache_read_tokens) * input_rate * _CACHE_READ_MULT / _MILLION
        + Decimal(usage.cache_write_tokens) * input_rate * _CACHE_WRITE_MULT / _MILLION
    )
    return cost.quantize(Decimal("0.000001"))
