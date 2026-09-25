"""What `e2er publish --to` must never send: keys, tokens and local paths.

The platform runs the same patterns on every request it receives
(e2er-site src/lib/api/common.ts). Keys stay where E2ER keeps them — the local
``.env``, the dashboard settings or the provider's own CLI login; nothing in a
publication needs one.
"""

from __future__ import annotations

import getpass
import math
import re
import socket
from collections import Counter
from pathlib import Path
from typing import Any

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")),
    ("OpenRouter key", re.compile(r"sk-or-[A-Za-z0-9_-]{8,}")),
    ("GitHub token", re.compile(r"\bghp_[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("e2er.org token", re.compile(r"\be2er_[A-Za-z0-9]{30,}")),
]
_ENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*[\"']?([^\s\"']{20,})[\"']?\s*$", re.M)
_HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s\"']+|[A-Za-z]:\\Users\\[^\\\s\"']+")


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def find_secrets(value: Any, path: str = "$") -> list[tuple[str, str]]:
    """(json path, kind) for every string in ``value`` that looks like a key or token."""
    if isinstance(value, str):
        hits = [(path, kind) for kind, rx in PATTERNS if rx.search(value)]
        hits += [(path, f"{m.group(1)}= value") for m in _ENV_LINE.finditer(value) if _entropy(m.group(2)) >= 3.5]
        return hits
    if isinstance(value, list):
        return [h for i, v in enumerate(value) for h in find_secrets(v, f"{path}[{i}]")]
    if isinstance(value, dict):
        return [h for k, v in value.items() for h in find_secrets(v, f"{path}.{k}")]
    return []


def find_local_paths(value: Any, path: str = "$") -> list[str]:
    """JSON paths of strings that name a home directory (/Users/…, /home/…, C:\\Users\\…)."""
    if isinstance(value, str):
        return [path] if _HOME_PATH.search(value) else []
    if isinstance(value, list):
        return [h for i, v in enumerate(value) for h in find_local_paths(v, f"{path}[{i}]")]
    if isinstance(value, dict):
        return [h for k, v in value.items() for h in find_local_paths(v, f"{path}.{k}")]
    return []


def sanitize(value: Any, bundle: Path | None = None) -> Any:
    """A copy with the bundle path, home directories and the host name taken out."""
    home = str(Path.home())
    host = socket.gethostname()
    user = getpass.getuser()

    def clean(s: str) -> str:
        if bundle is not None:
            s = s.replace(str(bundle) + "/", "").replace(str(bundle), ".")
        s = s.replace(home, "~")
        s = _HOME_PATH.sub("~", s)
        if len(host) > 3:
            s = s.replace(host, "<host>")
        # The user name only inside paths: as a bare word it may be part of a GitHub login.
        return s.replace(f"/{user}/", "/<user>/")

    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [sanitize(v, bundle) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v, bundle) for k, v in value.items()}
    return value
