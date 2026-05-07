"""LLM module — abstract backend interface and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass
class ToolLoopResult:
    success: bool
    output: str
    error: str | None = None
    tool_calls_made: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    duration_seconds: float = 0.0
    stop_reason: str = "end_turn"


class ToolHandler(ABC):
    """Intercepts and executes tool calls from the LLM."""

    @abstractmethod
    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool call and return result as string."""
        ...

    def can_handle(self, tool_name: str) -> bool:
        return True


class CompositeToolHandler(ToolHandler):
    """Delegates to the first handler that can handle the tool."""

    def __init__(self, handlers: list[ToolHandler]) -> None:
        self._handlers = handlers

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        for handler in self._handlers:
            if handler.can_handle(tool_name):
                return await handler.handle(tool_name, tool_input)
        return f"Error: no handler registered for tool '{tool_name}'"


class LLMBackend(ABC):
    """Abstract LLM execution backend."""

    @abstractmethod
    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler,
        max_turns: int = 30,
    ) -> ToolLoopResult:
        """Run a multi-turn tool-use conversation until end_turn or max_turns."""
        ...


def extract_json(text: str) -> dict[str, Any] | None:
    """Extract the last JSON object from text output."""
    import json
    import re

    # Try full parse first
    try:
        return json.loads(text.strip())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError):
        pass

    # Find last {...} block
    matches = list(re.finditer(r"\{", text))
    for m in reversed(matches):
        start = m.start()
        depth = 0
        for i, ch in enumerate(text[start:]):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : start + i + 1]
                    try:
                        return json.loads(candidate)  # type: ignore[no-any-return]
                    except (json.JSONDecodeError, ValueError):
                        break
    return None
