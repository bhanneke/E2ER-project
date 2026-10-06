"""LLM backend that delegates to the OpenAI ``codex exec`` CLI.

Same pattern as `claude_code.py`: hand a headless agentic CLI the whole
prompt, let it run its own tool loop, read back the final answer and usage.
Runs on a ChatGPT plan (`codex login`), so no API tokens are billed.

Validated live on codex-cli 0.155 (October 2026). What each flag is for:

* ``--skip-git-repo-check``: study folders and temp dirs are not git
  repositories, and without it Codex refuses to start in them.
* ``-s workspace-write`` (CODEX_SANDBOX): ``exec`` defaults to read-only, in
  which a specialist cannot write a single file.
* ``sandbox_workspace_write.network_access=true``: the sandbox has no network
  by default; ``e2er-data`` and ``e2er-lit`` need it.
* ``--add-dir <run database folder>``: writes outside the workspace are
  blocked, and the wrappers write their audit rows to the run database.
* ``shell_environment_policy``: pass the whole environment to shell commands,
  so FRED/Allium keys reach the wrappers (some Codex versions drop variables
  whose names contain KEY/TOKEN/SECRET).
* ``allow_login_shell=false``: a login shell reads the user's profile, which
  can put another ``e2er-data`` ahead of this checkout's on PATH.
* ``--ignore-user-config --ignore-rules --ephemeral``: run with e2er's
  settings only, not the user's own ``~/.codex/config.toml`` (model, effort,
  plugins, MCP servers, notify hooks) or command rules, and leave no session
  history behind. Sign-in still comes from ``$CODEX_HOME/auth.json``.
* ``--json`` and ``-o``: events on stdout (usage, command runs, errors), the
  final message in a file.

What this backend does NOT have: a command allowlist. Claude Code is started
with ``--allowedTools`` so its shell can run only the e2er-* wrappers. Codex
has no per-run equivalent: its command rules (execpolicy) are read only from
``$CODEX_HOME/rules`` or a trusted project, and a rule can forbid a command but
not forbid everything except a list. So under Codex the model can run any
shell command; the sandbox confines its writes to the paper's workspace (plus
the run database folder), but network access is on. See docs/BACKENDS.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger
from .base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult
from .cli_support import (
    cli_name,
    cli_path_or_setting,
    cli_version,
    clip,
    db_path,
    flatten_prompt,
    kill_process_group,
    run_env,
    workspace_cwd,
)

logger = get_logger(__name__)

#: Item types in `--json` events that are a tool use (one per command, file
#: edit, MCP call or web search).
_TOOL_ITEM_TYPES = frozenset({"command_execution", "file_change", "mcp_tool_call", "web_search"})

#: Error text worth one more try: the service or the connection, not the
#: prompt and not the plan's usage limit.
_TRANSIENT_MARKERS = (
    "stream disconnected",
    "error sending request",
    "connection reset",
    "connection closed",
    "timed out waiting",
    "429 too many requests",
    "500 internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
    "server_error",
    "overloaded",
    "at capacity",
    "please try again",
)
_NOT_TRANSIENT_MARKERS = ("usage limit", "usage_limit", "quota", "not logged in", "unauthorized", "401")


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def codex_models(home: Path | None = None) -> list[dict[str, Any]]:
    """The models this Codex install lists, best first, from its own cache.

    Codex keeps the model list it fetched for the signed-in plan in
    ``$CODEX_HOME/models_cache.json``. Read-only; [] when absent or unreadable.
    Hidden entries (internal reviewers, reserves) are left out.
    """
    path = (home or _codex_home()) / "models_cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    out = [m for m in models if isinstance(m, dict) and m.get("slug") and m.get("visibility", "list") == "list"]
    return sorted(out, key=lambda m: m.get("priority", 1_000))


@lru_cache(maxsize=4)
def default_codex_model(home: str | None = None) -> str:
    """The model `codex exec` picks without a user config: the first listed one."""
    models = codex_models(Path(home) if home else None)
    return str(models[0]["slug"]) if models else ""


def effective_codex_model(settings: Any) -> str:
    """CODEX_MODEL, else the CLI's own default as read from its model list."""
    return settings.codex_model or default_codex_model(str(_codex_home()))


class CodexBackend(LLMBackend):
    """Codex CLI subprocess backend. Runs on a ChatGPT plan."""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._cli_path = cli_path_or_setting("codex", settings)
        self._timeout = settings.codex_timeout
        # Always pass -m: with --ignore-user-config an empty model would be the
        # CLI's built-in pick, and the run would be labelled with a name that
        # says nothing ("codex-cli-default").
        self._model = model or effective_codex_model(settings)
        self._effort = settings.codex_reasoning_effort
        self._sandbox = settings.codex_sandbox or "workspace-write"
        self._cwd = settings.codex_cwd or os.getcwd()

    @property
    def model(self) -> str:
        return self._model

    def identity(self) -> dict[str, Any]:
        """What ran: model, reasoning effort and CLI version, for the run record."""
        return {
            "backend": "codex",
            "model": self._model or None,
            "reasoning_effort": self._effort or None,
            "cli": cli_name(self._cli_path),
            "cli_version": cli_version(self._cli_path),
            "sandbox": self._sandbox,
        }

    def build_cmd(self, *, cwd: str, last_message_file: str, extra_dirs: list[str]) -> list[str]:
        cmd: list[str] = [
            self._cli_path,
            "exec",
            "--json",
            "-o",
            last_message_file,
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "-s",
            self._sandbox,
            "-C",
            cwd,
            "-c",
            'approval_policy="never"',
            "-c",
            "allow_login_shell=false",
            "-c",
            'shell_environment_policy.inherit="all"',
            "-c",
            "shell_environment_policy.ignore_default_excludes=true",
        ]
        if self._sandbox == "workspace-write":
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
            for d in extra_dirs:
                cmd += ["--add-dir", d]
        if self._model:
            cmd += ["-m", self._model]
        if self._effort:
            cmd += ["-c", f'model_reasoning_effort="{self._effort}"']
        cmd.append("-")  # prompt on stdin
        return cmd

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],  # noqa: ARG002 — the CLI has its own tool set
        tool_handler: ToolHandler | None,  # noqa: ARG002
        max_turns: int = 30,  # noqa: ARG002 — Codex has no turn cap; the timeout bounds a call
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        settings = get_settings()
        prompt = flatten_prompt(system, messages)
        cwd, root = workspace_cwd(settings, paper_id, self._cwd)
        env = run_env(settings, paper_id=paper_id, specialist=specialist, workspace_root_abs=root)
        extra_dirs: list[str] = []
        db = db_path(settings)
        if db is not None and not _inside(db.parent, Path(cwd)):
            db.parent.mkdir(parents=True, exist_ok=True)
            extra_dirs.append(str(db.parent))

        retry_delays = [5.0, 20.0]
        result: ToolLoopResult | None = None
        for attempt in range(len(retry_delays) + 1):
            result = await self._invoke_once(prompt, cwd, env, extra_dirs)
            if result.success or not is_transient_codex_error(result.error or ""):
                return result
            if attempt >= len(retry_delays):
                break
            logger.warning(
                "Codex transient error (attempt %d/%d, retrying in %.0fs): %s",
                attempt + 1,
                len(retry_delays) + 1,
                retry_delays[attempt],
                (result.error or "")[:200],
            )
            await asyncio.sleep(retry_delays[attempt])
        assert result is not None
        return result

    async def _invoke_once(self, prompt: str, cwd: str, env: dict[str, str], extra_dirs: list[str]) -> ToolLoopResult:
        start = time.monotonic()
        fd, last_file = tempfile.mkstemp(prefix="e2er-codex-", suffix=".txt")
        os.close(fd)
        try:
            cmd = self.build_cmd(cwd=cwd, last_message_file=last_file, extra_dirs=extra_dirs)
            logger.info("Codex: invoking %s (model=%s, prompt=%d chars)", self._cli_path, self._model, len(prompt))
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
                        f"Codex CLI not found at: {self._cli_path}. Install it with "
                        "`npm install -g @openai/codex` (or install the ChatGPT desktop app, which includes it) "
                        "and run `codex login`; set CODEX_PATH if it is not on PATH."
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
                    timeout=self._timeout,
                )
            except TimeoutError:
                kill_process_group(proc)
                await proc.wait()
                elapsed = time.monotonic() - start
                return ToolLoopResult(
                    success=False,
                    output="",
                    error=f"Codex timed out after {elapsed:.0f}s (limit {self._timeout}s)",
                    duration_seconds=elapsed,
                    stop_reason="timeout",
                )

            duration = time.monotonic() - start
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
            try:
                last_message = Path(last_file).read_text(encoding="utf-8").strip()
            except OSError:
                last_message = ""
        finally:
            try:
                os.unlink(last_file)
            except OSError:
                pass

        parsed = parse_codex_events(stdout)
        output = last_message or parsed["last_agent_message"] or ("" if parsed["events"] else stdout.strip())

        if proc.returncode != 0 or parsed["error"]:
            error = parsed["error"] or stderr.strip() or f"Exit code {proc.returncode}: {stdout.strip()}"
            return ToolLoopResult(
                success=False,
                output=output,
                error=clip(f"Codex failed (exit {proc.returncode}): {error}"),
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


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def parse_codex_events(stdout: str) -> dict[str, Any]:
    """Read `codex exec --json` output: usage, tool uses, last message, error.

    Usage: `turn.completed` carries ``input_tokens`` (cached ones included),
    ``cached_input_tokens`` and ``output_tokens``. Cached input is recorded as
    cache reads and taken out of input, so totals are not double-counted.
    """
    usage = TokenUsage()
    tool_calls = 0
    last_agent_message = ""
    error = ""
    events = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict) or "type" not in ev:
            continue
        events += 1
        etype = ev.get("type")
        if etype == "turn.completed":
            u = ev.get("usage") or {}
            cached = int(u.get("cached_input_tokens", 0) or 0)
            total_in = int(u.get("input_tokens", 0) or 0)
            usage = usage + TokenUsage(
                input_tokens=max(0, total_in - cached),
                output_tokens=int(u.get("output_tokens", 0) or 0),
                cache_read_tokens=cached,
                cache_write_tokens=int(u.get("cache_write_input_tokens", 0) or 0),
            )
        elif etype == "item.completed":
            item = ev.get("item") or {}
            itype = item.get("type")
            if itype in _TOOL_ITEM_TYPES:
                tool_calls += 1
            elif itype == "agent_message" and item.get("text"):
                last_agent_message = str(item["text"])
        elif etype == "turn.failed":
            err = ev.get("error") or {}
            error = str(err.get("message") if isinstance(err, dict) else err) or "turn failed"
        elif etype == "error":
            # Codex also emits `error` events for reconnect attempts that then
            # succeed; keep the text, a later turn.completed clears it.
            error = str(ev.get("message") or "error")
    if usage.total_tokens and error and "turn.failed" not in stdout:
        # A completed turn after reconnect notices is a success.
        error = ""
    return {
        "usage": usage,
        "tool_calls": tool_calls,
        "last_agent_message": last_agent_message.strip(),
        "error": error,
        "events": events,
    }


def is_transient_codex_error(error: str) -> bool:
    """Service or connection trouble worth retrying; never a usage limit."""
    e = error.lower()
    if any(m in e for m in _NOT_TRANSIENT_MARKERS):
        return False
    return any(m in e for m in _TRANSIENT_MARKERS)
