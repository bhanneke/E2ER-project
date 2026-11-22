"""The sandbox AI-written scripts run in: they cannot read e2er's own folder or the user's secrets.

Up to 0.21.0 a script run by ``e2er-run`` (or by the runner after a specialist, or the
meta-analysis script) got an empty ``HOME``, but nothing stopped it from opening the real one:
``<home>/.e2er/session-<port>.json`` holds the dashboard's session token, with which the script
could call the dashboard's API, ``approval-key`` the key of the researcher's approvals, and
``papers.db`` the run database (review of 2026-11-21, finding 1).

Now such a script runs in the operating system's sandbox, which refuses to read or write:

- e2er's folder (``~/.e2er``), the studies folder's ``.env`` and any other ``.env`` file;
- the user's secrets: ``~/.ssh``, ``~/.aws``, ``~/.gnupg``, ``~/.config/gh``, ``~/.config/gcloud``,
  ``~/.codex``, ``~/.claude``, ``~/.docker``, ``~/.kube``, ``~/.netrc``, ``~/.pgpass``,
  ``~/.git-credentials``, the keychains and the browsers' profiles;
- on macOS also any connection to the dashboard's port on this computer.

macOS: ``sandbox-exec`` with a profile. Linux: bubblewrap (``bwrap``) when it is installed and
may make user namespaces; the folders are then hidden behind empty ones (the network is not
restricted there). Elsewhere, or when the sandbox cannot start, e2er says so and refuses to run
the script, unless the researcher set ``SCRIPT_SANDBOX=off`` (in the settings, or the
environment): the script then runs as before, with the empty ``HOME`` only.

A script started inside another sandbox (Codex's or Gemini's) cannot start a second one on macOS;
there the outer sandbox applies, and e2er says that it does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

#: Values of ``SCRIPT_SANDBOX``.
AUTO = "auto"
OFF = "off"

#: The user's files a script never reads, relative to the home folder.
SECRET_PATHS = (
    ".e2er", ".ssh", ".aws", ".gnupg", ".config/gh", ".config/gcloud", ".config/e2er", ".codex", ".claude",
    ".claude.json", ".docker", ".kube", ".netrc", ".pgpass", ".git-credentials", ".azure", ".npmrc", ".pypirc",
    "Library/Keychains", "Library/Cookies", "Library/Application Support/Google/Chrome",
    "Library/Application Support/Firefox", "Library/Application Support/Microsoft Edge",
    "Library/Application Support/BraveSoftware", "Library/Safari", ".mozilla", ".config/google-chrome",
    ".config/chromium", ".local/share/keyrings", ".password-store",
)  # fmt: skip


class SandboxUnavailable(OSError):  # noqa: N818 - says what it is
    """No sandbox can run the script, and the researcher did not allow running it without one."""


@dataclass
class Plan:
    """How a script runs: the argv prefix of the sandbox (empty: none), and a sentence saying so."""

    prefix: list[str] = field(default_factory=list)
    note: str = ""
    kind: str = "none"


def setting() -> str:
    """``SCRIPT_SANDBOX``: ``auto`` (the default) or ``off``."""
    value = os.environ.get("SCRIPT_SANDBOX") or os.environ.get("E2ER_SCRIPT_SANDBOX")
    if not value:
        try:
            from ..config import get_settings

            value = getattr(get_settings(), "script_sandbox", None)
        except Exception:  # noqa: BLE001 — a settings error must not open the sandbox
            value = None
    value = (value or AUTO).strip().lower()
    return OFF if value in ("off", "none", "0", "false", "no") else AUTO


def _real(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p


def _home() -> Path:
    """The user's real home (``e2er-run`` and the server run with it; the script gets an empty one)."""
    return Path(os.environ.get("HOME") or Path.home())


def denied_paths(*, workspace: Path, home: Path | None = None, extra: Iterable[Path] = ()) -> list[Path]:
    """The files and folders the script may not read or write (resolved, and as written)."""
    home = home or _home()
    ws = _real(Path(workspace))
    out: list[Path] = []
    candidates: list[Path] = [home / rel for rel in SECRET_PATHS]
    try:
        from ..home import env_file, state_dir

        candidates += [state_dir(), env_file()]
        if os.environ.get("E2ER_SCRIPT_LOG_DIR"):
            candidates.append(Path(os.environ["E2ER_SCRIPT_LOG_DIR"]))
    except Exception:  # noqa: BLE001
        pass
    db = _sqlite_file()
    if db is not None:
        candidates += [
            db,
            db.with_name(db.name + "-wal"),
            db.with_name(db.name + "-shm"),
            db.with_name(db.name + "-journal"),
        ]
    candidates += list(extra)
    for c in candidates:
        r = _real(c)
        if ws == r:
            continue
        if r not in out:
            out.append(r)
        if c != r and c not in out:
            out.append(c)  # the path as written too (a link the profile would otherwise miss)
    return out


def _sqlite_file() -> Path | None:
    """The run database's file when it is SQLite (``DATABASE_URL=sqlite:///…``)."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from ..config import get_settings

            url = str(getattr(get_settings(), "database_url", "") or "")
        except Exception:  # noqa: BLE001
            url = ""
    if not url.lower().startswith("sqlite:"):
        return None
    rest = url.split(":", 1)[1].lstrip("/")
    if not rest or rest.startswith(":memory:"):
        return None
    return Path("/" + rest) if not (len(rest) > 1 and rest[1] == ":") else Path(rest)


def _sbpl_string(p: Path) -> str:
    return '"' + str(p).replace("\\", "\\\\").replace('"', '\\"') + '"'


def allowed_paths(workspace: Path, python: str | None = None) -> list[Path]:
    """What stays open inside a denied folder: the study's folder, and the Python that runs the script.

    A virtual environment can sit in a denied folder (``~/.claude/…`` for a checkout made by an
    agent); the script still needs its interpreter and packages, read-only.
    """
    out: list[Path] = []
    prefixes = [Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).parent.parent]
    if python:
        prefixes.append(Path(python).parent.parent)
    for p in prefixes:
        for q in (p, _real(p)):
            if q not in out and str(q) not in ("/", ""):
                out.append(q)
    return out


def macos_profile(
    denied: list[Path], port: int | None, *, workspace: Path | None = None, readable: Iterable[Path] = ()
) -> str:
    """The sandbox-exec profile: everything as before, except the denied files and the dashboard's port."""
    rules = ["(version 1)", "(allow default)"]
    paths = " ".join(f"(subpath {_sbpl_string(p)})" for p in denied)
    if paths:
        rules.append(f"(deny file-read* file-write* {paths})")
        open_read = " ".join(f"(subpath {_sbpl_string(p)})" for p in readable)
        if open_read:
            rules.append(f"(allow file-read* {open_read})")
        if workspace is not None:
            ws = {Path(workspace), _real(Path(workspace))}
            rules.append("(allow file-read* file-write* " + " ".join(f"(subpath {_sbpl_string(p)})" for p in ws) + ")")
    rules.append('(deny file-read* file-write* (regex #"/\\.env(\\.[^/]*)?$"))')
    if port:
        rules.append(f'(deny network-outbound (remote ip "localhost:{int(port)}"))')
    return "\n".join(rules)


def bwrap_args(denied: list[Path], *, workspace: Path | None = None, readable: Iterable[Path] = ()) -> list[str]:
    """bubblewrap: the whole file system as it is, the denied folders behind empty ones, files behind /dev/null;
    then the study's folder and the script's Python mounted again where a denied folder hid them."""
    args = ["--dev-bind", "/", "/", "--die-with-parent"]
    hidden: list[Path] = []
    for p in denied:
        if p.is_dir() and not p.is_symlink():
            args += ["--tmpfs", str(p)]
            hidden.append(p)
        elif p.is_file():
            args += ["--ro-bind", "/dev/null", str(p)]
    for p in readable:
        if p.is_dir() and any(p.is_relative_to(h) for h in hidden):
            args += ["--ro-bind", str(p), str(p)]
    if workspace is not None:
        ws = _real(Path(workspace))
        if any(ws.is_relative_to(h) for h in hidden):
            args += ["--bind", str(ws), str(ws)]
    return args


def _dashboard_port() -> int | None:
    try:
        from ..config import get_settings

        port = getattr(get_settings(), "port", None)
        return int(port) if port else None
    except Exception:  # noqa: BLE001
        return None


def outer_sandbox() -> str | None:
    """The sandbox this process already runs in, when a CLI says so in the environment."""
    if os.environ.get("CODEX_SANDBOX"):
        return f"Codex's sandbox ({os.environ['CODEX_SANDBOX']})"
    if os.environ.get("SANDBOX"):  # Gemini CLI: "sandbox-exec" or the container's name
        return f"Gemini's sandbox ({os.environ['SANDBOX']})"
    return None


_probed: dict[str, bool] = {}


def _works(argv: list[str]) -> bool:
    key = "\0".join(argv)
    if key not in _probed:
        try:
            done = subprocess.run([*argv, "/bin/sh", "-c", "exit 0"], capture_output=True, timeout=20, check=False)
            _probed[key] = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _probed[key] = False
    return _probed[key]


def plan(workspace: Path, *, python: str | None = None, extra_denied: Iterable[Path] = ()) -> Plan:
    """How to run an AI-written script in ``workspace``; raises :class:`SandboxUnavailable` when none can."""
    if setting() == OFF:
        return Plan(note="no sandbox (SCRIPT_SANDBOX=off): the script can read your files", kind="off")
    denied = denied_paths(workspace=workspace, extra=extra_denied)
    # Never a folder that holds a denied one (a Python in ~/bin would open the whole home).
    readable = [r for r in allowed_paths(workspace, python) if not any(d.is_relative_to(r) for d in denied)]
    why = ""
    if sys.platform == "darwin":
        exe = shutil.which("sandbox-exec") or (
            "/usr/bin/sandbox-exec" if Path("/usr/bin/sandbox-exec").exists() else None
        )
        if exe:
            profile = macos_profile(denied, _dashboard_port(), workspace=workspace, readable=readable)
            prefix = [exe, "-p", profile]
            if _works([exe, "-p", "(version 1)(allow default)"]):
                return Plan(prefix=prefix, note="macOS sandbox (sandbox-exec)", kind="sandbox-exec")
            why = "macOS's sandbox-exec could not start a sandbox here"
        else:
            why = "macOS's sandbox-exec is missing"
    elif sys.platform.startswith("linux"):
        exe = shutil.which("bwrap")
        if exe:
            if _works([exe, "--dev-bind", "/", "/"]):
                args = bwrap_args(denied, workspace=workspace, readable=readable)
                return Plan(prefix=[exe, *args, "--"], note="bubblewrap sandbox", kind="bwrap")
            why = "bubblewrap is installed but may not make a sandbox here (user namespaces are off)"
        else:
            why = "bubblewrap (bwrap) is not installed"
    else:
        why = f"e2er has no sandbox for scripts on {sys.platform}"
    outer = outer_sandbox()
    if outer:
        return Plan(note=f"inside {outer}; {why}", kind="outer")
    raise SandboxUnavailable(
        f"{why}, so e2er cannot keep the AI-written script from reading your files (your e2er session, "
        "your keys, ~/.ssh). It did not run the script. Install the sandbox (Linux: `sudo apt install "
        "bubblewrap`), or set SCRIPT_SANDBOX=off in your settings to run such scripts without one."
    )


def wrap(argv: list[str], workspace: Path, *, extra_denied: Iterable[Path] = ()) -> tuple[list[str], Plan]:
    """``argv`` inside the sandbox :func:`plan` chose."""
    p = plan(workspace, python=argv[0] if argv else None, extra_denied=extra_denied)
    return [*p.prefix, *argv], p
