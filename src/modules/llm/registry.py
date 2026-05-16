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
    elif settings.llm_backend == "claude_code":
        from .claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend()
    elif settings.llm_backend == "codex":
        from .codex import CodexBackend

        return CodexBackend()
    elif settings.llm_backend == "gemini":
        from .gemini import GeminiBackend

        return GeminiBackend()
    raise ValueError(f"Unknown LLM backend: {settings.llm_backend!r}")
