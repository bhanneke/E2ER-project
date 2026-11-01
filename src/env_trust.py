"""Settings in a folder's ``.env`` that decide what runs, and how freely, are used only once you said yes.

e2er reads the ``.env`` of the folder it was started in when that folder has one (a project of
its own), else the studies folder's. A downloaded study folder or repository can carry a
``.env``: with ``CLAUDE_CODE_PATH=./tool`` it chose the program e2er starts for every AI call,
with ``CODEX_SANDBOX=danger-full-access`` or ``GEMINI_YOLO=true`` it switched the CLI's sandbox
off. Since 0.19.0 these settings (:data:`RISKY`) are taken from a ``.env`` only when it is the
studies folder you chose in the setup (or ``E2ER_PROJECT_DIR`` names it), or when you said yes
to exactly these lines (``e2er`` asks at a terminal and remembers the answer in
``~/.e2er/trusted-env.json``). Otherwise they keep their defaults and e2er says why.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

#: Settings that name a program e2er starts, the folder it runs in, or how sandboxed it is.
RISKY = (
    "CLAUDE_CODE_PATH", "CODEX_PATH", "GEMINI_PATH",
    "CLAUDE_CODE_CWD", "CODEX_CWD", "GEMINI_CWD",
    "CODEX_SANDBOX", "CODEX_ALLOW_FULL_ACCESS", "CODEX_NETWORK_ACCESS", "GEMINI_YOLO",
)  # fmt: skip

_warned: set[str] = set()


def trust_file() -> Path:
    return Path.home() / ".e2er" / "trusted-env.json"


def risky_lines(env_file: Path) -> dict[str, str]:
    """The risky settings ``env_file`` sets (and the environment does not already set)."""
    try:
        from dotenv import dotenv_values

        values = dotenv_values(env_file)
    except Exception:  # noqa: BLE001 — a missing or unreadable .env sets nothing
        return {}
    return {k: str(v) for k, v in values.items() if k in RISKY and v is not None and k not in os.environ}


def _fingerprint(env_file: Path, lines: dict[str, str]) -> str:
    text = json.dumps({"file": str(env_file.resolve()), "lines": sorted(lines.items())})
    return hashlib.sha256(text.encode()).hexdigest()


def _trusted() -> set[str]:
    try:
        data = json.loads(trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def remember(env_file: Path, lines: dict[str, str]) -> None:
    keep = _trusted() | {_fingerprint(env_file, lines)}
    p = trust_file()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sorted(keep), fh)
    os.replace(tmp, p)


def configured(env_file: Path) -> bool:
    """Is ``env_file`` the studies folder's (chosen in the setup) or the one E2ER_PROJECT_DIR names?"""
    from .home import ENV_PROJECT, remembered_studies_folder

    folder = env_file.parent
    for chosen in (os.environ.get(ENV_PROJECT, "").strip(), remembered_studies_folder()):
        if chosen:
            try:
                if Path(chosen).expanduser().resolve() == folder.resolve():
                    return True
            except OSError:
                continue
    return False


def untrusted(env_file: Path) -> dict[str, str]:
    """The risky lines of ``env_file`` that may not be used (empty when the file is configured or trusted)."""
    lines = risky_lines(env_file)
    if not lines or configured(env_file) or _fingerprint(env_file, lines) in _trusted():
        return {}
    return lines


def warn(env_file: Path, lines: dict[str, str]) -> None:
    key = str(env_file)
    if key in _warned:
        return
    _warned.add(key)
    shown = ", ".join(f"{k}={v}" for k, v in sorted(lines.items()))
    print(
        f"e2er: {env_file} sets {shown}; not used. A folder's .env may choose the programs e2er starts or "
        "turn a sandbox off only after you said yes: run `e2er` at a terminal in this folder to be asked, "
        "or put these settings in your studies folder's .env.",
        file=sys.stderr,
    )


def ask(env_file: Path) -> bool:
    """At a terminal: ask whether to use this folder's risky settings; remembered when yes."""
    lines = untrusted(env_file)
    if not lines:
        return True
    try:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        interactive = False
    if not interactive:
        return False
    print(f"{env_file} sets what e2er starts or how sandboxed it is:")
    for k, v in sorted(lines.items()):
        print(f"  {k}={v}")
    try:
        yes = input("Use these settings from this folder? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        yes = False
    if yes:
        remember(env_file, lines)
        from .config import get_settings

        get_settings.cache_clear()
    return yes
