"""LLM module — backend registry."""

from __future__ import annotations

from ...config import Settings
from .base import LLMBackend


def get_backend(settings: Settings) -> LLMBackend:
    """Return the configured LLM backend instance."""
    if settings.llm_backend == "anthropic":
        from .anthropic import AnthropicBackend

        return AnthropicBackend()
    elif settings.llm_backend == "openrouter":
        from .openrouter import OpenRouterBackend

        return OpenRouterBackend()
    raise ValueError(f"Unknown LLM backend: {settings.llm_backend!r}")
