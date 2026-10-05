"""What the three subscription CLI backends (Claude Code, Codex, Gemini) share.

Finding the executable, the PATH the model's shell sees, the prompt layout, the
process-group kill on timeout, and the CLI version stamp. Each of these was
first written for Claude Code and then copied, incompletely, into the other
two backends; keeping one copy here stops the copies drifting apart again.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any

#: `scripts/` holds the e2er-* wrappers in a source checkout. On an installed
#: wheel it does not exist and the entry-point shims in the venv's bin/ apply.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"

#: Setting that names each CLI, and the executable name it defaults to.
CLI_SETTING: dict[str, tuple[str, str]] = {
    "claude_code": ("claude_code_path", "claude"),
    "codex": ("codex_path", "codex"),
    "gemini": ("gemini_path", "gemini"),
}

#: Places a CLI is installed without being put on PATH. The ChatGPT desktop app
#: ships its own `codex` inside the app bundle.
_EXTRA_LOCATIONS: dict[str, tuple[str, ...]] = {
    "codex": (
        "/Applications/ChatGPT.app/Contents/Resources/codex",
        "~/Applications/ChatGPT.app/Contents/Resources/codex",
        "/Applications/Codex.app/Contents/Resources/codex",
    ),
}

#: How much of a backend error to keep: both ends, because a CLI's cause is
#: usually printed last.
MAX_ERROR_CHARS = 4000


def clip(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    """Trim to `limit`, keeping the head AND tail."""
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n… [{len(text) - limit} chars omitted] …\n{text[-tail:]}"


def resolve_cli(backend: str, settings: Any = None) -> str | None:
    """Full path of the CLI for `backend`, or None when it is not installed.

    Order: the configured path (CLAUDE_CODE_PATH / CODEX_PATH / GEMINI_PATH),
    looked up on PATH when it is a bare name; then the known install places
    that are not on PATH (the ChatGPT app's own `codex`).
    """
    if backend not in CLI_SETTING:
        return None
    attr, default = CLI_SETTING[backend]
    configured = (getattr(settings, attr, None) if settings is not None else None) or default
    configured = os.path.expanduser(str(configured))
    if os.sep in configured:
        if os.path.isfile(configured) and os.access(configured, os.X_OK):
            return configured
    else:
        found = shutil.which(configured)
        if found:
            return found
    # Only fall back to the known places when the setting is the default name:
    # a path someone typed and got wrong should be reported, not papered over.
    if configured == default:
        for place in _EXTRA_LOCATIONS.get(backend, ()):
            p = os.path.expanduser(place)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def cli_path_or_setting(backend: str, settings: Any) -> str:
    """The path to run: the resolved CLI, else the setting as written (so the
    error names what was tried)."""
    attr, default = CLI_SETTING[backend]
    return resolve_cli(backend, settings) or (getattr(settings, attr, None) or default)


def subprocess_path(current: str | None) -> str:
    """PATH for the CLI subprocess: the e2er-* wrappers first, then the venv's
    entry-point shims, then the inherited PATH.

    `sysconfig.get_path("scripts")` rather than `Path(sys.executable).parent`:
    on macOS framework venvs the interpreter is a symlink into the framework,
    whose bin/ does not hold the venv's shims.
    """
    parts = [sysconfig.get_path("scripts"), current or ""]
    if SCRIPTS_DIR.exists():
        parts.insert(0, str(SCRIPTS_DIR))
    return os.pathsep.join(p for p in parts if p)


def flatten_prompt(system: str, messages: list[dict[str, Any]]) -> str:
    """System prompt plus messages as one prompt, roles marked in markdown.

    The CLIs take one prompt; a multi-message conversation is not part of
    their contract.
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
    return "\n\n".join(parts).replace("\x00", "")


def kill_process_group(proc: Any) -> None:
    """Kill the CLI and everything it started.

    The CLIs run the model's shell commands as their own children (a Python
    script under `e2er-run`, a data download). `proc.kill()` alone leaves those
    running after a timeout; the subprocess is started in its own session so
    its process group can be killed whole.
    """
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


@lru_cache(maxsize=8)
def cli_version(cli_path: str) -> str | None:
    """`<cli> --version`, first line; None when it cannot be read."""
    try:
        out = subprocess.run([cli_path, "--version"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (out.stdout or out.stderr or "").strip().splitlines()
    return line[0].strip() if line and out.returncode == 0 else None


def workspace_cwd(settings: Any, paper_id: str | None, fallback: str) -> tuple[str, Path | None]:
    """(cwd, absolute workspace root) for a call.

    The workspace root must be absolute before it reaches the subprocess: the
    default `workspaces` is relative, and the subprocess's cwd is already the
    paper's workspace, so a relative root nests `workspaces/<id>` inside itself
    (live test eea5379b, v0.4.4).
    """
    if not paper_id:
        return fallback, None
    root = Path(settings.workspace_root).expanduser().resolve()
    return str(root / paper_id), root


def run_env(
    settings: Any,
    *,
    paper_id: str | None,
    specialist: str | None,
    workspace_root_abs: Path | None,
) -> dict[str, str]:
    """Environment for the CLI subprocess and the e2er-* wrappers it runs.

    The wrappers are separate Python processes. They read their settings from
    the environment and from a `.env` in *their* working directory, which is
    the paper's workspace (or the e2er checkout), never the study folder whose
    `.env` this run was started with. So a FRED key or a study-local database
    named only in the study's `.env` never reached them. Everything in that
    `.env` that the environment does not already set is passed on here, and
    the database is passed as an absolute path.
    """
    import sys

    env = os.environ.copy()
    try:
        from dotenv import dotenv_values

        for key, value in dotenv_values(Path.cwd() / ".env").items():
            if value is not None and key not in env:
                env[key] = value
    except Exception:  # noqa: BLE001 — a missing or unreadable .env is normal
        pass
    db = db_path(settings)
    if db is not None:
        env["DATABASE_URL"] = f"sqlite:///{db}"
    env["PATH"] = subprocess_path(env.get("PATH"))
    # The wrappers run under the same interpreter as the runner (right venv,
    # Python >= 3.11). Without it they fell back to a bare `python` (run #10).
    env["E2ER_PYTHON"] = sys.executable
    if paper_id:
        env["E2ER_PAPER_ID"] = paper_id
    if specialist:
        env["E2ER_SPECIALIST"] = specialist
    if workspace_root_abs is not None:
        env["E2ER_WORKSPACE_ROOT"] = str(workspace_root_abs)
    return env


def db_path(settings: Any) -> Path | None:
    """Absolute path of the run database when it is SQLite, else None."""
    try:
        url = settings.resolved_database_url
    except Exception:  # noqa: BLE001
        return None
    if url and not url.startswith("sqlite"):
        return None
    from ...db.client import _sqlite_path

    try:
        return Path(_sqlite_path(url)).expanduser().resolve()
    except ValueError:
        return None
