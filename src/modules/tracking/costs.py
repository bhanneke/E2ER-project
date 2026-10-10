"""Token cost estimation per model."""

from __future__ import annotations

from decimal import Decimal

from ..llm.base import TokenUsage

# Backends that bill flat-rate at the subscription level, NOT per-token.
# Costing a token-counted invoice against these gives an estimate of
# what the SDK route would have charged — but that number is meaningless
# for users on these backends and was actively harmful in v0.8: the
# default ``--max-cost 5`` cap tripped after a single heavy specialist
# on Claude Code (M4 finding #1). For these backends ``compute_cost``
# returns ``Decimal("0")`` and the budget gate never fires. Gemini (not
# tested) is kept here although since October 2026 it runs on a Gemini API
# key that Google bills: e2er does not count that cost.
_FLAT_RATE_BACKENDS = frozenset({"claude_code", "codex", "gemini"})


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
    # Open models on OpenRouter (cheapest listed provider, 2026-10). The live
    # list (``llm/openrouter_models.py``) is preferred; these cover offline runs.
    "deepseek/deepseek-v4-pro": (Decimal("0.23"), Decimal("0.46")),
    "deepseek/deepseek-v4-flash": (Decimal("0.03"), Decimal("1.28")),
    "deepseek/deepseek-v4.1-flash": (Decimal("0.30"), Decimal("1.20")),
}

_MILLION = Decimal("1_000_000")
_CACHE_READ_MULT = Decimal("0.1")  # cache reads: 10% of input price
_CACHE_WRITE_MULT = Decimal("1.25")  # cache writes: 125% of input price
_DEFAULT_INPUT = Decimal("3")
_DEFAULT_OUTPUT = Decimal("15")


def compute_cost(model: str, usage: TokenUsage, backend: str | None = None) -> Decimal:
    """Estimate USD cost for a token usage record.

    ``backend`` is the LLM backend literal from
    :attr:`Settings.llm_backend` (``"anthropic"`` / ``"openrouter"`` /
    ``"claude_code"`` / ``"codex"`` / ``"gemini"``). For flat-rate
    backends (Claude Code / Codex / Gemini CLI — billed at the
    subscription level, not per-token) this returns ``Decimal("0")``.
    The CLI help and v0.9 plan both promise ``"$0 if on the Claude
    Code / Codex / Gemini CLI backends"``; this is the implementation
    that makes that promise true. M4 finding #1.

    ``backend=None`` preserves the legacy behaviour (always compute
    SDK rates) for the few call sites that don't yet have backend in
    scope — costs.py's pricing table is the authoritative SDK
    reference and remains valid.
    """
    if backend in _FLAT_RATE_BACKENDS:
        return Decimal("0")
    if usage.cost_usd is not None:
        # The provider's own bill for these calls (OpenRouter reports it per
        # response); it already reflects the provider that served the call,
        # cache discounts and reasoning tokens.
        return Decimal(str(usage.cost_usd)).quantize(Decimal("0.000001"))
    return estimate_cost(model, usage)


def model_rates(model: str) -> tuple[Decimal, Decimal, Decimal | None]:
    """USD per million tokens (input, output, cache read or None) for a model.

    For an OpenRouter id (``vendor/model``): OpenRouter's published price
    (when the list was read this run or is cached), then the fixed table, then
    a $3/$15 guess. Never goes to the network.
    """
    model_key = model.lower()
    if "/" in model_key:
        from ..llm.openrouter_models import model_rates as openrouter_rates

        live = openrouter_rates(model) or openrouter_rates(model_key)
        if live is not None:
            return live
    if model_key in _PRICING:
        inp, out = _PRICING[model_key]
        return inp, out, None
    return _DEFAULT_INPUT, _DEFAULT_OUTPUT, None


def estimate_cost(model: str, usage: TokenUsage) -> Decimal:
    """Price the tokens from the model's rates (ignores ``usage.cost_usd``)."""
    input_rate, output_rate, cache_rate = model_rates(model)
    if cache_rate is None:
        cache_rate = input_rate * _CACHE_READ_MULT

    cost = (
        Decimal(usage.input_tokens) * input_rate / _MILLION
        + Decimal(usage.output_tokens) * output_rate / _MILLION
        + Decimal(usage.cache_read_tokens) * cache_rate / _MILLION
        + Decimal(usage.cache_write_tokens) * input_rate * _CACHE_WRITE_MULT / _MILLION
    )
    return cost.quantize(Decimal("0.000001"))
