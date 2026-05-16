"""LLM backend that delegates to the Google ``gemini`` CLI.

Pattern mirrors `claude_code.py` and `codex.py`. The Gemini CLI runs its
own tool loop; we shell out, hand it the prompt, parse the result.

Status: alpha. Live validation pending. The CLI exposes ``--approval-mode``
(newer) vs the legacy ``--yolo`` toggle (older); we probe at startup
once and cache. Same for ``--output-format``.

Install Gemini CLI: ``npm install -g @google/gemini-cli``. Auth with
``gemini auth`` (Google AI Pro/Ultra subscription). Free under that
plan — the "$0/token" property we want.

Adapted from the patterns in Davidvandijcke/coarse
(src/coarse/headless_clients.py::GeminiClient).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

logger = get_logger(__name__)

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"

# Cache the CLI-flag probe results at module scope — every Gemini backend
# instance in the same process shares them.
_FLAG_PROBE_DONE: bool = False
_APPROVAL_MODE_FLAG_SUPPORTED: bool = False
_OUTPUT_FORMAT_FLAG_SUPPORTED: bool = False


def _probe_gemini_flags(cli_path: str) -> None:
    """Probe `gemini --help` once and cache which version-gated flags are present.

    Older Gemini CLIs reject ``--approval-mode`` and ``--output-format``;
    we fall back to the legacy ``--yolo`` toggle and the default text
    output respectively.
    """
    global _FLAG_PROBE_DONE, _APPROVAL_MODE_FLAG_SUPPORTED, _OUTPUT_FORMAT_FLAG_SUPPORTED
    if _FLAG_PROBE_DONE:
        return
    try:
        help_out = subprocess.run(
            [cli_path, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:  # CLI missing, slow, or hung — fall through to fallbacks
        help_out = ""
    _APPROVAL_MODE_FLAG_SUPPORTED = "--approval-mode" in help_out
    _OUTPUT_FORMAT_FLAG_SUPPORTED = "--output-format" in help_out
    _FLAG_PROBE_DONE = True
    if not _APPROVAL_MODE_FLAG_SUPPORTED:
        logger.warning(
            "Gemini CLI doesn't expose --approval-mode (older version). "
            "Falling back to legacy --yolo. Upgrade via `npm install -g @google/gemini-cli@latest`."
        )


class GeminiBackend(LLMBackend):
    """Gemini CLI subprocess backend. Free under a Google AI Pro/Ultra plan."""

    def __init__(self) -> None:
        settings = get_settings()
        self._cli_path = shutil.which(settings.gemini_path) or settings.gemini_path
        self._timeout = settings.gemini_timeout
        self._model = settings.gemini_model
        self._cwd = settings.gemini_cwd or os.getcwd()
        # Probe flags once at construction time.
        _probe_gemini_flags(self._cli_path)

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],  # noqa: ARG002 — CLI manages its own tool set
        tool_handler: ToolHandler | None,  # noqa: ARG002
        max_turns: int = 30,  # noqa: ARG002 — Gemini CLI has its own internal cap
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        prompt = _flatten_prompt(system, messages)
        cwd = self._cwd
        if paper_id:
            settings = get_settings()
            cwd = str(Path(settings.workspace_root) / paper_id)

        cmd: list[str] = [self._cli_path]
        if _APPROVAL_MODE_FLAG_SUPPORTED:
            cmd += ["--approval-mode", "yolo"]
        else:
            cmd.append("--yolo")
        if _OUTPUT_FORMAT_FLAG_SUPPORTED:
            cmd += ["--output-format", "text"]
        if self._model:
            cmd += ["--model", self._model]
        # Gemini CLI reads prompt from stdin by default — no '-' positional.

        return await _invoke_gemini(
            cmd=cmd,
            cli_path=self._cli_path,
            prompt=prompt,
            timeout=self._timeout,
            cwd=cwd,
            paper_id=paper_id,
            specialist=specialist,
        )


def _flatten_prompt(system: str, messages: list[dict[str, Any]]) -> str:
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


async def _invoke_gemini(
    *,
    cmd: list[str],
    cli_path: str,
    prompt: str,
    timeout: int,
    cwd: str,
    paper_id: str | None = None,
    specialist: str | None = None,
) -> ToolLoopResult:
    """Run the Gemini CLI as a subprocess and shape the result."""
    start = time.monotonic()
    prompt = prompt.replace("\x00", "")

    env = os.environ.copy()
    env["PATH"] = f"{_SCRIPTS_DIR}{os.pathsep}{env.get('PATH', '')}"
    env["E2ER_PYTHON"] = sys.executable
    if paper_id:
        env["E2ER_PAPER_ID"] = paper_id
    if specialist:
        env["E2ER_SPECIALIST"] = specialist

    logger.info("Gemini: invoking %s (prompt=%d chars)", cli_path, len(prompt))

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
                f"Gemini CLI not found at: {cli_path}. "
                "Set GEMINI_PATH or install via `npm install -g @google/gemini-cli`, "
                "then run `gemini auth`."
            ),
            duration_seconds=time.monotonic() - start,
        )
    except OSError as e:
        return ToolLoopResult(
            success=False,
            output="",
            error=f"Failed to start Gemini CLI: {e}",
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
            error=f"Gemini timed out after {elapsed:.0f}s (limit {timeout}s)",
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

    return ToolLoopResult(
        success=True,
        output=stdout.strip(),
        tool_calls_made=0,
        usage=TokenUsage(),
        duration_seconds=duration,
        stop_reason="end_turn",
    )
