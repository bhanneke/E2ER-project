"""LLM backend that delegates to the Google ``gemini`` CLI.

Same pattern as `claude_code.py` and `codex.py`: hand the CLI the whole prompt
on stdin, let it run its own tool loop, read back the answer and usage.

Status: NOT validated live. The Gemini CLI was not installed on the machine
the Codex backend was validated on (2026-10); the command line and the JSON
shape below follow the CLI's documented headless mode and are covered by
mocked tests only.

Install: ``npm install -g @google/gemini-cli``, then run ``gemini`` once and
sign in with a Google account (or set GEMINI_API_KEY).

Like Codex, the Gemini CLI has no per-run command allowlist: with
``--approval-mode yolo`` its shell tool can run any command. See
docs/BACKENDS.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult
from .cli_support import (
    cli_name,
    cli_path_or_setting,
    cli_version,
    clip,
    flatten_prompt,
    kill_process_group,
    run_env,
    workspace_cwd,
)

logger = get_logger(__name__)

#: Flags found in `gemini --help`, per CLI path. Only a probe that actually
#: read the help text is kept; a slow or failed probe is retried next time
#: instead of pinning the legacy flags for the life of the process.
_FLAG_CACHE: dict[str, tuple[bool, bool]] = {}

#: Node CLIs can take well over 5 s to print their help on a cold start.
_PROBE_TIMEOUT = 30


def _probe_gemini_flags(cli_path: str) -> tuple[bool, bool]:
    """(supports --approval-mode, supports --output-format) for this CLI.

    When the help text cannot be read, assume a current CLI (both flags):
    the legacy ``--yolo``/text fallback is for old versions that print their
    help fine.
    """
    if cli_path in _FLAG_CACHE:
        return _FLAG_CACHE[cli_path]
    try:
        out = subprocess.run([cli_path, "--help"], capture_output=True, text=True, timeout=_PROBE_TIMEOUT)
        help_out = (out.stdout or "") + (out.stderr or "")
    except (OSError, subprocess.SubprocessError):
        help_out = ""
    if not help_out.strip():
        return True, True
    flags = ("--approval-mode" in help_out, "--output-format" in help_out)
    _FLAG_CACHE[cli_path] = flags
    if not flags[0]:
        logger.warning(
            "This Gemini CLI has no --approval-mode (older version); using --yolo. "
            "Update with `npm install -g @google/gemini-cli@latest`."
        )
    return flags


class GeminiBackend(LLMBackend):
    """Gemini CLI subprocess backend. Runs on a Google AI plan or a Gemini API key."""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._cli_path = cli_path_or_setting("gemini", settings)
        self._timeout = settings.gemini_timeout
        self._model = model or settings.gemini_model
        self._cwd = settings.gemini_cwd or os.getcwd()

    @property
    def model(self) -> str:
        return self._model

    def identity(self) -> dict[str, Any]:
        return {
            "backend": "gemini",
            "model": self._model or None,
            "cli": cli_name(self._cli_path),
            "cli_version": cli_version(self._cli_path),
        }

    def build_cmd(self, approval_mode: bool, output_format: bool) -> list[str]:
        cmd: list[str] = [self._cli_path]
        cmd += ["--approval-mode", "yolo"] if approval_mode else ["--yolo"]
        if output_format:
            cmd += ["--output-format", "json"]
        if self._model:
            cmd += ["--model", self._model]
        # The prompt goes on stdin; no positional.
        return cmd

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],  # noqa: ARG002 — the CLI has its own tool set
        tool_handler: ToolHandler | None,  # noqa: ARG002
        max_turns: int = 30,  # noqa: ARG002 — the CLI has its own cap
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        settings = get_settings()
        prompt = flatten_prompt(system, messages)
        cwd, root = workspace_cwd(settings, paper_id, self._cwd)
        env = run_env(settings, paper_id=paper_id, specialist=specialist, workspace_root_abs=root)
        # The probe is a blocking subprocess; keep it off the event loop.
        approval_mode, output_format = await asyncio.to_thread(_probe_gemini_flags, self._cli_path)
        cmd = self.build_cmd(approval_mode, output_format)
        start = time.monotonic()
        logger.info("Gemini: invoking %s (prompt=%d chars)", self._cli_path, len(prompt))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError:
            return ToolLoopResult(
                success=False,
                output="",
                error=(
                    f"Gemini CLI not found at: {self._cli_path}. Install it with "
                    "`npm install -g @google/gemini-cli`, then run `gemini` once and sign in; "
                    "set GEMINI_PATH if it is not on PATH."
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
                timeout=self._timeout,
            )
        except TimeoutError:
            kill_process_group(proc)
            await proc.wait()
            elapsed = time.monotonic() - start
            return ToolLoopResult(
                success=False,
                output="",
                error=f"Gemini timed out after {elapsed:.0f}s (limit {self._timeout}s)",
                duration_seconds=elapsed,
                stop_reason="timeout",
            )

        duration = time.monotonic() - start
        stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
        parsed = parse_gemini_json(stdout)
        output = parsed["response"] if parsed["json"] else stdout.strip()

        if proc.returncode != 0 or parsed["error"]:
            error = parsed["error"] or stderr.strip() or f"Exit code {proc.returncode}: {stdout.strip()}"
            return ToolLoopResult(
                success=False,
                output=output,
                error=clip(f"Gemini failed (exit {proc.returncode}): {error}"),
                tool_calls_made=parsed["tool_calls"],
                usage=parsed["usage"],
                duration_seconds=duration,
                stop_reason="error",
            )

        return ToolLoopResult(
            success=True,
            output=output,
            tool_calls_made=parsed["tool_calls"],
            usage=parsed["usage"],
            duration_seconds=duration,
            stop_reason="end_turn",
        )


def parse_gemini_json(stdout: str) -> dict[str, Any]:
    """Read `gemini --output-format json`: response, per-model token stats, tool calls, error.

    Shape (documented headless mode): ``{"response": str, "stats": {"models":
    {name: {"tokens": {"prompt", "candidates", "cached", ...}}}, "tools":
    {"totalCalls": n}}, "error": {"message": ...}}``. Anything else — plain
    text from an older CLI — comes back with ``json=False``.
    """
    empty: dict[str, Any] = {"json": False, "response": "", "usage": TokenUsage(), "tool_calls": 0, "error": ""}
    text = stdout.strip()
    if not text.startswith("{"):
        # Some versions print a notice line before the JSON object.
        brace = text.find("\n{")
        if brace < 0:
            return empty
        text = text[brace + 1 :]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    usage = TokenUsage()
    stats = data.get("stats") or {}
    models = stats.get("models") if isinstance(stats, dict) else None
    if isinstance(models, dict):
        for m in models.values():
            tokens = (m or {}).get("tokens") or {}
            cached = int(tokens.get("cached", 0) or 0)
            prompt = int(tokens.get("prompt", 0) or 0)
            usage = usage + TokenUsage(
                input_tokens=max(0, prompt - cached),
                output_tokens=int(tokens.get("candidates", 0) or 0) + int(tokens.get("thoughts", 0) or 0),
                cache_read_tokens=cached,
            )
    tools = stats.get("tools") if isinstance(stats, dict) else None
    tool_calls = int((tools or {}).get("totalCalls", 0) or 0) if isinstance(tools, dict) else 0
    err = data.get("error")
    error = ""
    if err:
        error = str(err.get("message") or err) if isinstance(err, dict) else str(err)
    return {
        "json": True,
        "response": str(data.get("response") or "").strip(),
        "usage": usage,
        "tool_calls": tool_calls,
        "error": error,
    }
