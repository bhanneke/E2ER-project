"""The environments e2er gives to programs it did not write: AI CLIs and AI-written scripts.

Allowlists, not denylists. Until 0.18 the AI CLIs got e2er's whole environment minus what
looked like a credential by name, and AI-written scripts (the post-run of an analysis script,
the meta-analysis script, ``e2er-run``) got all of it: ``SSH_AUTH_SOCK`` (the ssh agent), a
``DATABASE_URL`` with its password, ``GH_TOKEN`` under another name, and the user's ``HOME``
with ``~/.ssh`` and the CLIs' logins.

:func:`script_env` is for AI-written scripts: the system's basics, e2er's own run variables,
the run database only as a SQLite path, no key or token, and ``HOME`` (with the ``XDG_*``
folders) pointed at an empty folder. :func:`agent_env` is for the AI CLIs: the same basics, the
user's real ``HOME`` (the CLI signs in from it), e2er's non-secret settings, the data and
literature keys the ``e2er-*`` wrappers need, the CLI's own sign-in, and nothing else.
"""

from __future__ import annotations

import os
import re
import site
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: What every child process gets: where programs are, the language, time zone, temporary
#: folders, certificates, and Windows' system folders.
BASE_VARS = frozenset(
    {
        "PATH", "USER", "LOGNAME", "SHELL", "TERM", "COLORTERM", "NO_COLOR", "TZ", "LANG", "LANGUAGE",
        "TMPDIR", "TEMP", "TMP",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
        "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
        "__CF_USER_TEXT_ENCODING",
        "PYTHONIOENCODING", "PYTHONUTF8", "MPLBACKEND",
        "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    }
)  # fmt: skip
#: The user's folders: real for an AI CLI (it signs in from them), an empty folder for a script.
HOME_VARS = (
    "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
)  # fmt: skip
_PROXY_VARS = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"})
#: e2er's variables that control e2er itself: never passed on.
CONTROL_VARS = frozenset(
    {"E2ER_SESSION_TOKEN", "E2ER_API_TOKEN", "E2ER_API_URL", "E2ER_CREDENTIALS", "E2ER_TOKEN", "API_AUTH_TOKEN"}
)
#: A variable that holds a credential, by its name.
CREDENTIAL_NAME = re.compile(r"(^|_)(TOKEN|KEY|API_KEY|SECRET|PASSWORD|PASSWD|CREDENTIALS?|PAT|AUTH)(_|$)", re.I)


def _proxy_ok(name: str, value: str) -> bool:
    return name.upper() in _PROXY_VARS and "@" not in value


def _sqlite_only(value: str) -> str | None:
    """A DATABASE_URL a child may see: a SQLite path; never a server URL (it may carry a password)."""
    return value if value.strip().lower().startswith("sqlite") else None


def _base(source: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in source.items():
        if k in BASE_VARS or k.startswith("LC_") or _proxy_ok(k, v):
            out[k] = v
    return out


def _e2er_vars(source: Mapping[str, str]) -> dict[str, str]:
    """e2er's own run variables (E2ER_PAPER_ID, E2ER_WORKSPACE, …): never the control ones or a credential."""
    return {
        k: v
        for k, v in source.items()
        if k.startswith("E2ER_") and k not in CONTROL_VARS and not CREDENTIAL_NAME.search(k[len("E2ER_") :])
    }


def empty_home(prefix: str = "e2er-home-") -> Path:
    """A new empty folder that stands in for the user's home (the caller removes it)."""
    return Path(tempfile.mkdtemp(prefix=prefix))


def script_env(
    *,
    home: Path,
    source: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The environment of an AI-written script: no key, no token, no ssh agent, an empty ``home``.

    ``PYTHONUSERBASE`` keeps a ``pip install --user`` of e2er's packages importable from the
    empty home; ``MPLCONFIGDIR`` gives matplotlib a cache outside it.
    """
    src = dict(os.environ if source is None else source)
    env = _base(src)
    env.update(_e2er_vars(src))
    db = _sqlite_only(src.get("DATABASE_URL", ""))
    if db:
        env["DATABASE_URL"] = db
    for var in HOME_VARS:
        env[var] = str(home)
    try:
        env["PYTHONUSERBASE"] = src.get("PYTHONUSERBASE") or site.getuserbase()
    except Exception:  # noqa: BLE001
        pass
    env["MPLCONFIGDIR"] = str(home / ".matplotlib")
    env["PYTHON_COLORS"] = "0"
    env.update(extra or {})
    return env


def agent_env(
    *,
    source: Mapping[str, str],
    keys: Iterable[str] = (),
    settings_names: Iterable[str] = (),
    cli_prefixes: tuple[str, ...] = (),
) -> dict[str, str]:
    """The environment of an AI CLI: the basics, the real home, e2er's run variables and non-secret
    settings, and of the credentials only ``keys`` (the wrappers' data keys, the CLI's sign-in).

    ``settings_names``: e2er's setting names (LOCAL_DATA_DIR, WORKSPACE_ROOT, …), passed on when
    they do not name a credential. ``cli_prefixes``: the CLI's own configuration (``CLAUDE_CODE_``,
    ``CODEX_``), again without credentials.
    """
    keys = set(keys)
    names = {n.upper() for n in settings_names}
    env = _base(source)
    for var in HOME_VARS:
        if var in source:
            env[var] = source[var]
    env.update(_e2er_vars(source))
    for k, v in source.items():
        if k in keys:
            env[k] = v
        elif k in env or k in CONTROL_VARS or CREDENTIAL_NAME.search(k):
            continue
        elif k == "DATABASE_URL":
            db = _sqlite_only(v)
            if db:
                env[k] = db
        elif k in names or (cli_prefixes and k.startswith(cli_prefixes)):
            env[k] = v
    return env


def run_in_own_session(
    argv: list[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str],
    timeout: float,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """``subprocess.run`` for an AI-written script: in its own session, and at the time limit the
    whole process group is stopped (a script's own child processes too), then TimeoutExpired.
    """
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=dict(env),
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        out, err = proc.communicate()
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err) from None
    except BaseException:
        _kill_group(proc)
        proc.wait()
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _kill_group(proc: subprocess.Popen[str]) -> None:
    kill_tree(proc)


def kill_tree(proc: Any) -> None:
    """Stop a process and every process it started.

    POSIX: the process was started in its own session, so its process group is killed whole. Windows has
    no such groups (``os.killpg`` does not exist there): ``taskkill /T /F`` ends the process and its
    children. Either way ``proc.kill()`` is the last resort.
    """
    import signal

    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        elif os.name == "nt":
            try:
                done = subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30, check=False
                )
                if done.returncode == 0:
                    return
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass
