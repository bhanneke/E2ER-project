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
import sys
import sysconfig
import time
from pathlib import Path
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

logger = get_logger(__name__)


# Default CLI tool allowlist for an empirical research specialist.
# These are Claude Code's *native* tool names. The pipeline's specialists
# describe their artifacts by filename ("write paper_plan.md") rather than
# tool name ("call write_file"), so the CLI naturally maps to its built-in
# Write/Read/Edit.
#
# Note on Bash: we DO NOT grant the unrestricted Bash tool. The only
# permitted shell invocation is `e2er-allium-query`, our Allium gatekeeper
# (see scripts/e2er-allium-query). The pattern syntax
# `Bash(e2er-allium-query:*)` tells Claude Code to allow `bash -c
# "e2er-allium-query <anything>"` but reject any other command. Without
# this restriction, the model could run arbitrary shell (curl, ssh, sudo,
# git push, ...), defeating both the Allium guardrails and the broader
# security model. Specialists that need execution (replication_packager,
# LaTeX compile) get their tools wired through Python at the runner
# level, not via Bash from the model.
_DEFAULT_ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    # Unified data gatekeeper covering Allium + public sources (yfinance,
    # FRED, …). Allium-specific guardrails still fire inside the wrapper
    # for `e2er-data allium ...` invocations.
    "Bash(e2er-data:*)",
    # Back-compat: e2er-allium-query is a thin shim around `e2er-data
    # allium`. Keep it allow-listed through v0.5.0 so existing skill files
    # / external scripts still work during the deprecation window.
    "Bash(e2er-allium-query:*)",
]

# Specialists that write an execution script (see EXECUTION_CONVENTIONS in
# core/specialists/post_execution.py) additionally get `e2er-run`, so they can
# run what they just wrote, read the traceback, and fix it — v1's write→run→fix
# loop, which v3 dropped when it took code execution away from specialists.
#
# `e2er-run` is a gatekeeper like `e2er-data`: one workspace-relative .py file,
# no arguments, no traversal, hard timeout. It is NOT `Bash(python3:*)` — that
# would be arbitrary shell, and unlike v1 we have no container around it.
#
# The orchestrator still re-runs the final script through post_execution, so
# provenance comes from that run, not from whatever the model did while
# iterating.
_SCRIPT_WRITING_SPECIALISTS = frozenset({"econometrics_specialist", "data_analyst"})
_RUN_TOOL = "Bash(e2er-run:*)"


def allowed_tools_for(specialist: str | None) -> list[str]:
    """CLI tool allowlist for a specialist. Script writers get `e2er-run`."""
    tools = list(_DEFAULT_ALLOWED_TOOLS)
    if specialist in _SCRIPT_WRITING_SPECIALISTS:
        tools.append(_RUN_TOOL)
    return tools


# `scripts/` (containing the wrappers) is inserted at the front of PATH
# for the subprocess so the model can invoke them by bare name.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"


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
        self._model = settings.claude_code_model

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler | None,
        max_turns: int = 30,
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        """Invoke the CLI once with system + last user message as the prompt.

        The CLI runs its own internal tool loop (file ops, bash, etc.) until
        end-turn or max-turns. `tool_handler` and `tools` are ignored — the
        CLI uses its native tool set, allowed via `--allowedTools`.

        ``paper_id`` and ``specialist`` are propagated to the subprocess as
        ``E2ER_PAPER_ID`` and ``E2ER_SPECIALIST`` env vars. The
        ``e2er-allium-query`` wrapper picks them up automatically — the
        specialist doesn't have to remember its own paper_id.
        """
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
        # ignored (different naming scheme) — we just allow the standard set,
        # plus `e2er-run` for the specialists that write execution scripts.
        allowed_tools = allowed_tools_for(specialist)

        # Per-specialist working directory: the CLI's `Write` tool resolves
        # relative paths against cwd. If we run the CLI from the project
        # root, files like "paper_plan.md" land in the repo root instead of
        # the paper's workspace — discovered May 2026 NFT-paper run #4. Use
        # the paper's workspace as cwd when paper_id is supplied; fall back
        # to the configured backend cwd for tool-less invocations
        # (strategist decisions don't write files anyway).
        # Resolve workspace_root to an ABSOLUTE path. The default
        # `workspace_root="workspaces"` (relative) plus the subprocess having
        # cwd inside a workspace combine to nest `workspaces/<id>` inside
        # itself when `e2er-data --save-to` resolves its target path. See
        # live test eea5379b (v0.4.4) — analyze.py wrote
        # `workspaces/<id>/data/...` from cwd already at `workspaces/<id>/`,
        # so the CSV landed at `workspaces/<id>/workspaces/<id>/data/...`.
        cwd = self._cwd
        workspace_root_abs: Path | None = None
        if paper_id:
            settings = get_settings()
            workspace_root_abs = Path(settings.workspace_root).resolve()
            cwd = str(workspace_root_abs / paper_id)

        # Retry transient Anthropic API errors. The CLI surfaces these in
        # its JSON output as is_error=true + api_error_status set (e.g.
        # 429, 500, 502, 503, 504, 529). They're not bugs in our code or
        # the prompt — they're Anthropic infrastructure hiccups, and they
        # bubble all the way up to the cascade detector unless retried
        # here. Two retries with 5s + 15s backoff is enough for the
        # vast majority of transients without burning much wall time.
        retry_delays = [5.0, 15.0]
        last_result: ToolLoopResult | None = None
        for attempt in range(len(retry_delays) + 1):
            result = await _invoke_cli(
                cli_path=self._cli_path,
                prompt=prompt,
                allowed_tools=allowed_tools,
                timeout=self._timeout,
                cwd=cwd,
                max_turns=max_turns or self._max_turns_default,
                start=time.monotonic(),
                paper_id=paper_id,
                specialist=specialist,
                workspace_root_abs=workspace_root_abs,
                model=self._model,
            )
            last_result = result
            if result.success or not _is_transient_api_error(result.error or ""):
                return result
            if attempt >= len(retry_delays):
                break
            delay = retry_delays[attempt]
            logger.warning(
                "Claude Code transient API error (attempt %d/%d, sleeping %.0fs): %s",
                attempt + 1,
                len(retry_delays) + 1,
                delay,
                (result.error or "")[:200],
            )
            await asyncio.sleep(delay)
        return last_result if last_result is not None else result


def _is_transient_api_error(error: str) -> bool:
    """Detect transient Anthropic API errors worth retrying.

    The CLI's failure JSON includes ``api_error_status`` set to the HTTP
    code Anthropic returned (e.g. 429, 500, 502, 503, 504, 529) plus
    ``is_error: true``. These are infrastructure issues, not prompt bugs
    — retrying with a short backoff resolves >90% of them. We also
    accept the literal string ``overloaded_error`` Anthropic sometimes
    returns at the SDK layer.

    Hard failures (auth, malformed request, max_turns) are NOT matched
    here — those should propagate so the human sees them.
    """
    if not error:
        return False
    e = error.lower()
    # CLI exit-code-1 path leaves a JSON blob in the error message with
    # api_error_status set; the actual status code is what matters.
    transient_codes = ("429", "500", "502", "503", "504", "529")
    for code in transient_codes:
        if f'api_error_status":{code}' in e or f'api_error_status": {code}' in e:
            return True
    return "overloaded_error" in e or "overloaded" in e and "anthropic" in e


async def _invoke_cli(
    *,
    cli_path: str,
    prompt: str,
    allowed_tools: list[str],
    timeout: int,
    cwd: str,
    max_turns: int,
    start: float,
    paper_id: str | None = None,
    specialist: str | None = None,
    workspace_root_abs: Path | None = None,
    model: str = "",
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
    # Pin the subprocess model when configured — without --model the CLI
    # uses the user's interactive /model default, which can silently burn
    # the priciest tier's usage credits (see claude_code_model in config).
    if model:
        cmd.extend(["--model", model])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    logger.info("ClaudeCode: invoking %s (max_turns=%d, prompt=%d chars)", cli_path, max_turns, len(prompt))

    # Make `e2er-data` resolvable from the subprocess by name. Two sources,
    # prepended in priority order:
    #   1. The dev-checkout `scripts/` directory (bash wrappers — used when
    #      running from a source checkout).
    #   2. The venv `bin/` dir where pip installs the `e2er-data` entry-point
    #      shim from pyproject.toml [project.scripts] (pip-install users).
    #
    # For (2), use `sysconfig.get_path("scripts")` rather than
    # `Path(sys.executable).parent`. On macOS framework venvs the venv's
    # bin/python is a symlink to the underlying Python.framework binary,
    # so `.resolve().parent` lands in the framework's bin/ — where the
    # entry-point shim does NOT live. `sysconfig.get_path("scripts")`
    # returns the venv's own bin/ correctly on all platforms (verified
    # on macOS 26 framework venv where .resolve() jumps to
    # /opt/homebrew/Cellar/python@3.12/.../Python.framework/.../bin/).
    env = os.environ.copy()
    _bin_dir = sysconfig.get_path("scripts")
    # Only include the dev-checkout `scripts/` dir if it actually exists.
    # On pip-installed wheels `_SCRIPTS_DIR` resolves to a non-existent
    # `site-packages/scripts/` because scripts/ is excluded from packaging.
    # The entry-point shim in `_bin_dir` covers pip users.
    _path_parts = [_bin_dir, env.get("PATH", "")]
    if _SCRIPTS_DIR.exists():
        _path_parts.insert(0, str(_SCRIPTS_DIR))
    env["PATH"] = os.pathsep.join(p for p in _path_parts if p)
    # Tell the wrapper which Python to use — same interpreter that's running
    # the runner, so the subprocess inherits the correct venv (project deps)
    # and the correct Python version (>=3.11, needed for PEP 604 union types
    # used throughout the codebase). Discovered run #10: without this the
    # wrapper called bare `python` from the CLI subprocess's PATH, which
    # either resolved to nothing (then `exec: python: not found`) or to a
    # system Python 3.9 that crashed on first import (`str | None`).
    env["E2ER_PYTHON"] = sys.executable
    # Wire deterministic context — the wrapper reads these and injects them
    # into the python CLI call, so the specialist doesn't have to remember
    # its own paper_id.
    if paper_id:
        env["E2ER_PAPER_ID"] = paper_id
    if specialist:
        env["E2ER_SPECIALIST"] = specialist
    # Absolute workspace root so e2er-data's `_resolve_workspace` resolves to
    # the same path regardless of subprocess cwd. Without this the relative
    # default `"workspaces"` resolves against the subprocess cwd, which is
    # ALREADY the paper's workspace dir → we get `workspaces/<id>/workspaces/<id>/data/`.
    # See live test eea5379b (v0.4.4) for the failure mode.
    if workspace_root_abs is not None:
        env["E2ER_WORKSPACE_ROOT"] = str(workspace_root_abs)

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
    """Approximate tool-call count from the CLI summary.

    Claude Code 2.x doesn't include a `messages` array in
    `--output-format json`; only top-level metadata. The closest signal is
    `num_turns`: a tool-less completion = 1 turn, each tool use adds at
    least one more turn. So `num_turns - 1` is a lower bound on tool calls.
    Approximate is fine — this metric is informational, the cascade-
    detection logic uses file existence, not tool count.
    """
    n = raw.get("num_turns", 0)
    if isinstance(n, int) and n > 0:
        return max(0, n - 1)
    return 0
