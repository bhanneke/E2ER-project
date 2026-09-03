"""LLM module — backend registry."""

from __future__ import annotations

from ...config import Settings
from .base import LLMBackend

BACKENDS = ("anthropic", "openrouter", "claude_code", "codex", "gemini")


def get_backend(settings: Settings, name: str | None = None) -> LLMBackend:
    """Return an LLM backend instance.

    ``name`` overrides ``settings.llm_backend`` for this call only — used by
    per-paper backend selection (multi-model runs, the governance
    experiment) so two papers can run on different backends against one
    server without re-reading the process-global config. Backend-specific
    settings (CLI paths, timeouts, model pins) still come from ``settings``.
    """
    backend = name or settings.llm_backend
    if backend == "anthropic":
        from .anthropic import AnthropicBackend

        return AnthropicBackend()
    elif backend == "openrouter":
        from .openrouter import OpenRouterBackend

        return OpenRouterBackend()
    elif backend == "claude_code":
        from .claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend()
    elif backend == "codex":
        from .codex import CodexBackend

        return CodexBackend()
    elif backend == "gemini":
        from .gemini import GeminiBackend

        return GeminiBackend()
    raise ValueError(f"Unknown LLM backend: {backend!r}")
