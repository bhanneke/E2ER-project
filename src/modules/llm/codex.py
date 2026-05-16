"""LLM backend that delegates to the OpenAI ``codex exec`` CLI.

The pattern mirrors `claude_code.py`: shell out to a headless agentic
CLI, hand it a fully-built prompt, parse the subprocess output. The CLI
runs its own tool loop internally; we collect the final answer + usage
metadata.

Status: alpha. Interface is stable but real-run validation is pending —
the Codex CLI's exact stdout/stderr framing differs across versions and
we may need to adjust parsing once we test against a paid ChatGPT
Plus/Pro subscription.

Install Codex CLI: ``npm install -g @openai/codex``. Auth via
``codex login`` (ChatGPT account). No API token is consumed when running
under a Plus/Pro plan — that's the "$0/token" property we want.

Adapted from the patterns in Davidvandijcke/coarse
(src/coarse/headless_clients.py::CodexClient).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

logger = get_logger(__name__)

# `scripts/` (containing e2er-allium-query) is inserted at the front of
# PATH for the subprocess so Codex can invoke the gatekeeper. Same
# rationale as the Claude Code backend.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"


class CodexBackend(LLMBackend):
    """Codex CLI subprocess backend. Free under a ChatGPT Plus/Pro plan.

    The CLI handles its own tool dispatch internally (Read/Write/Edit/Bash),
    so ``tools`` and ``tool_handler`` arguments are ignored — like the
    Claude Code backend. Allium guardrails still apply because the only
    permitted shell invocation is the ``e2er-allium-query`` wrapper.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._cli_path = shutil.which(settings.codex_path) or settings.codex_path
        self._timeout = settings.codex_timeout
        self._model = settings.codex_model
        self._effort = settings.codex_reasoning_effort
        self._cwd = settings.codex_cwd or os.getcwd()

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],  # noqa: ARG002 — CLI manages its own tool set
        tool_handler: ToolHandler | None,  # noqa: ARG002
        max_turns: int = 30,  # noqa: ARG002 — Codex CLI has its own internal cap
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        prompt = _flatten_prompt(system, messages)
        cwd = self._cwd
        if paper_id:
            settings = get_settings()
            cwd = str(Path(settings.workspace_root) / paper_id)

        # Build command. Codex reads the prompt from stdin when '-' is the
        # positional. The reasoning effort flag uses the older config-override
        # syntax that recent Codex versions accept.
        cmd: list[str] = [self._cli_path, "exec"]
        if self._model:
            cmd += ["-m", self._model]
        if self._effort:
            cmd += ["-c", f"model_reasoning_effort={self._effort!r}"]
        cmd.append("-")  # read prompt from stdin

        return await _invoke_codex(
            cmd=cmd,
            cli_path=self._cli_path,
            prompt=prompt,
            timeout=self._timeout,
            cwd=cwd,
            paper_id=paper_id,
            specialist=specialist,
        )


def _flatten_prompt(system: str, messages: list[dict[str, Any]]) -> str:
    """Same flattening as the Claude Code backend.

    Codex CLI accepts a single prompt string; multi-message conversations
    are not part of its CLI contract. We label roles in markdown so the
    model sees the structure.
    """
    parts = [system, ""]
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
        parts.append(f"# {role}\n{content}")
    return "\n\n".join(parts)


async def _invoke_codex(
    *,
    cmd: list[str],
    cli_path: str,
    prompt: str,
    timeout: int,
    cwd: str,
    paper_id: str | None = None,
    specialist: str | None = None,
) -> ToolLoopResult:
    """Run `codex exec` as a subprocess and shape the result."""
    start = time.monotonic()
    prompt = prompt.replace("\x00", "")

    env = os.environ.copy()
    env["PATH"] = f"{_SCRIPTS_DIR}{os.pathsep}{env.get('PATH', '')}"
    env["E2ER_PYTHON"] = sys.executable
    if paper_id:
        env["E2ER_PAPER_ID"] = paper_id
    if specialist:
        env["E2ER_SPECIALIST"] = specialist

    logger.info("Codex: invoking %s (prompt=%d chars)", cli_path, len(prompt))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError:
        return ToolLoopResult(
            success=False,
            output="",
            error=(
                f"Codex CLI not found at: {cli_path}. "
                "Set CODEX_PATH or install via `npm install -g @openai/codex`, "
                "then run `codex login`."
            ),
            duration_seconds=time.monotonic() - start,
        )
    except OSError as e:
        return ToolLoopResult(
            success=False,
            output="",
            error=f"Failed to start Codex CLI: {e}",
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
            error=f"Codex timed out after {elapsed:.0f}s (limit {timeout}s)",
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

    # Codex CLI in exec mode emits the final answer text on stdout. There's
    # no structured-output JSON contract like Claude Code; we treat the
    # whole stdout as the model's final response. Token usage isn't surfaced
    # to stdout in current Codex versions, so we report zero — this is fine
    # for the "$0/token under Plus/Pro plan" use case where the cost
    # tracking is informational only.
    return ToolLoopResult(
        success=True,
        output=stdout.strip(),
        tool_calls_made=0,
        usage=TokenUsage(),
        duration_seconds=duration,
        stop_reason="end_turn",
    )
