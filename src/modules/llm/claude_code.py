"""LLM backend that delegates to the Claude Code CLI subprocess.

This is the v1/v2 architecture — adapted to v3's `LLMBackend` interface so
users on a Claude Max plan can run the pipeline at $0 per token. The CLI
runs its own internal tool loop (Read, Write, Edit, Bash, etc.); we just
hand it a fully-built prompt and read the result.

Trade-offs vs the SDK-based backends:
  + Free under Max plan (no per-token cost)
  + Battle-tested in v1/v2
  - JSON-tool boundary lost: AlliumToolHandler can't intercept calls. Run
    with DATA_MODULE_ENABLED=false (literature-only / BYOD) or expose a
    bash wrapper script that enforces guardrails before hitting Allium.
  - Tool names differ: prompts using "write_file" must work with the CLI's
    "Write" tool. Most specialists describe artifacts by filename rather
    than by tool name, so this is mostly transparent.

Lifted from `E2ER/src/claude_code.py` and adapted to async + the v3
LLMBackend contract. The original is ~660 lines; this is leaner because
v3 doesn't need the per-stage helper logic (the runner does that).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

logger = get_logger(__name__)


# Default CLI tool allowlist for an empirical research specialist.
# These are Claude Code's *native* tool names. The pipeline's specialists
# describe their artifacts by filename ("write paper_plan.md") rather than
# tool name ("call write_file"), so the CLI naturally maps to its built-in
# Write/Read/Edit. Bash is allowed for replication code execution.
_DEFAULT_ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]


class ClaudeCodeBackend(LLMBackend):
    """Claude Code CLI subprocess backend. Free under a Max plan.

    `tool_loop` flattens the system prompt + user messages into a single
    prompt, invokes the CLI, parses its `--output-format json` result, and
    returns a `ToolLoopResult`. The CLI handles its own tool dispatch
    internally, so the `tool_handler` argument is ignored — see module
    docstring for why and the implications for Allium guardrails.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._cli_path = shutil.which(settings.claude_code_path) or settings.claude_code_path
        self._timeout = settings.claude_code_timeout
        self._max_turns_default = settings.claude_code_max_turns
        self._cwd = settings.claude_code_cwd or os.getcwd()

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler | None,
        max_turns: int = 30,
    ) -> ToolLoopResult:
        """Invoke the CLI once with system + last user message as the prompt.

        The CLI runs its own internal tool loop (file ops, bash, etc.) until
        end-turn or max-turns. `tool_handler` and `tools` are ignored — the
        CLI uses its native tool set, allowed via `--allowedTools`.
        """
        start = time.monotonic()

        # Flatten messages to a single prompt. Most v3 callers pass a
        # 1-element list with the user instruction; if there are more, we
        # join them with explicit role markers so the CLI sees them.
        prompt_parts = [system, ""]
        for m in messages:
            role = m.get("role", "user").upper()
            content = m.get("content", "")
            if isinstance(content, list):
                # Anthropic-style content blocks — extract text parts only.
                content = "\n".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            prompt_parts.append(f"# {role}\n{content}")
        prompt = "\n\n".join(prompt_parts)

        # Hint the CLI at allowed tools. Caller-supplied `tools` list is
        # ignored (different naming scheme) — we just allow the standard set.
        allowed_tools = _DEFAULT_ALLOWED_TOOLS

        return await _invoke_cli(
            cli_path=self._cli_path,
            prompt=prompt,
            allowed_tools=allowed_tools,
            timeout=self._timeout,
            cwd=self._cwd,
            max_turns=max_turns or self._max_turns_default,
            start=start,
        )


async def _invoke_cli(
    *,
    cli_path: str,
    prompt: str,
    allowed_tools: list[str],
    timeout: int,
    cwd: str,
    max_turns: int,
    start: float,
) -> ToolLoopResult:
    """Run `claude -p` as a subprocess. Async-native version of v1's wrapper."""
    # Sanitize null bytes — upstream artifacts can embed \x00 which the
    # subprocess pipe cannot transport.
    prompt = prompt.replace("\x00", "")

    cmd = [
        cli_path,
        "-p",
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
    ]
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    logger.info("ClaudeCode: invoking %s (max_turns=%d, prompt=%d chars)", cli_path, max_turns, len(prompt))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except FileNotFoundError:
        return ToolLoopResult(
            success=False,
            output="",
            error=(
                f"Claude Code CLI not found at: {cli_path}. "
                "Set CLAUDE_CODE_PATH or install via `npm i -g @anthropic-ai/claude-code`."
            ),
            duration_seconds=time.monotonic() - start,
        )
    except OSError as e:
        return ToolLoopResult(
            success=False,
            output="",
            error=f"Failed to start Claude Code CLI: {e}",
            duration_seconds=time.monotonic() - start,
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        elapsed = time.monotonic() - start
        return ToolLoopResult(
            success=False,
            output="",
            error=f"Claude Code timed out after {elapsed:.0f}s (limit {timeout}s)",
            duration_seconds=elapsed,
        )

    duration = time.monotonic() - start
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        error_msg = stderr.strip() or f"Exit code {proc.returncode}: {stdout.strip()[:500]}"
        return ToolLoopResult(
            success=False,
            output="",
            error=error_msg,
            duration_seconds=duration,
        )

    raw = _parse_output(stdout)
    output_text = _extract_text(raw, stdout)
    usage = _extract_usage(raw)
    tool_calls_made = _count_tool_calls(raw)

    # error_max_turns: process exits 0 but the agent didn't finish. The
    # CLI returns subtype="error_max_turns" or is_error=True.
    if raw.get("subtype") == "error_max_turns" or raw.get("is_error"):
        return ToolLoopResult(
            success=False,
            output=output_text,
            error=f"Claude Code hit max_turns={max_turns} ({raw.get('subtype', 'is_error')})",
            tool_calls_made=tool_calls_made,
            usage=usage,
            duration_seconds=duration,
            stop_reason="max_turns",
        )

    return ToolLoopResult(
        success=True,
        output=output_text,
        tool_calls_made=tool_calls_made,
        usage=usage,
        duration_seconds=duration,
        stop_reason="end_turn",
    )


def _parse_output(stdout: str) -> dict[str, Any]:
    """Parse CLI JSON output. Falls back to {} on parse failure."""
    if not stdout.strip():
        return {}
    # The CLI emits one JSON object per line in --output-format json mode;
    # the last line is the summary. We want the object that has 'result' or
    # 'subtype' keys (the final assistant turn / completion summary).
    summary: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            summary = obj  # keep updating; the last valid line is the summary
    return summary


def _extract_text(raw: dict[str, Any], stdout: str) -> str:
    """Pull the final assistant message text out of the CLI's JSON output."""
    if not raw:
        return stdout.strip()[:4000]
    # Common shapes: {"result": "..."} or {"messages": [...]}
    if isinstance(raw.get("result"), str):
        return raw["result"]
    msgs = raw.get("messages") or []
    if isinstance(msgs, list) and msgs:
        last = msgs[-1]
        if isinstance(last, dict):
            content = last.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return raw.get("output", "") or stdout.strip()[:4000]


def _extract_usage(raw: dict[str, Any]) -> TokenUsage:
    """Pull token counts from the CLI summary. Zero if missing."""
    usage = raw.get("usage") or {}
    if not isinstance(usage, dict):
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
    )


def _count_tool_calls(raw: dict[str, Any]) -> int:
    """Count tool_use blocks in the CLI's message log if available."""
    msgs = raw.get("messages") or []
    if not isinstance(msgs, list):
        return 0
    count = 0
    for m in msgs:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, list):
            count += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
    return count
