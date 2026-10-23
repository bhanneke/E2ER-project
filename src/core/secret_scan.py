"""What must never leave this computer: keys, tokens and local paths.

``scan_text``/``scan_files`` are the one check run before files go out: ``e2er pack``, the
Zenodo deposit, the GitHub push, and the scratch logs an export copies (redacted with
``redact_text``). ``find_secrets`` checks a request body for `e2er publish --to`.

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
    ("OpenAI key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-(?!ant-|or-|proj-)[A-Za-z0-9]{32,}")),
    ("GitHub token", re.compile(r"\bghp_[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"\bgh[osur]_[A-Za-z0-9]{30,}")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("e2er.org token", re.compile(r"\be2er_[A-Za-z0-9]{30,}")),
    ("bearer token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    # Keys without a prefix of their own, where they appear in a request: FRED's 32 hex digits in
    # ``api_key=``, a Zenodo token in ``access_token=`` (both end up in logged URLs).
    ("FRED key", re.compile(r"(?i)[?&;\s\"']api_key=[0-9a-f]{32}\b")),
    ("Zenodo token", re.compile(r"(?i)[?&;\s\"']access_token=[A-Za-z0-9]{40,}\b")),
]
#: A key-like name given a value: ``ZENODO_TOKEN=…``, ``zenodo_token: …``, ``"FRED_API_KEY": "…"``,
#: ``api_key = '…'``. The value counts when it is long, mixes letters and digits and is not plain
#: text (entropy), so ``token_file = path_to_the_file`` or ``API_KEY = os.environ[...]`` do not.
_KEY_NAME = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9])
    ["']?([A-Za-z0-9_.-]*(?:api[_-]?key|token(?![a-z])|secret(?![a-z])|passw(?:or)?d|auth(?:orization)?(?![a-z])
        |credential|access[_-]?key)[A-Za-z0-9_]*)["']?
    \s*[:=]\s*
    ["']?([A-Za-z0-9_+=-]{16,})["']?
    """
)


def _keylike_value(value: str) -> bool:
    return (
        any(c.isdigit() for c in value)
        and any(c.isalpha() for c in value)
        and _entropy(value) >= 2.5
        and not re.fullmatch(r"[a-z]+(?:_[a-z]+)+", value)
        and not re.fullmatch(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+){2,}", value)  # a model or package name
    )


_ENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*[\"']?([^\s\"']{20,})[\"']?\s*$", re.M)
_HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s\"']+|[A-Za-z]:\\Users\\[^\\\s\"']+")
#: A path on this machine: a home directory, an absolute path under a system root
#: (/private, /var, /tmp, /Volumes, …), a Windows drive path or a network share.
#: A URL's path ("https://e2er.org/d/…", "https://unstats.un.org/home/nso_sites/") is not one:
#: it follows a host name.
_LOCAL_PATH = re.compile(
    r"(?<![\w.-])(?:/Users|/home)/[^/\s\"']+"
    r"|(?<![\w:/.~\\-])/(?:root|private|var|tmp|opt|mnt|Volumes|media|srv|etc|usr|nix|run|workspaces?)/[^\s\"']*"
    r"|(?<![\w])[A-Za-z]:[\\/][^\s\"']+"
    r"|\\\\[A-Za-z0-9._-]+\\[^\s\"']+"
)


#: The same places as `_LOCAL_PATH`, each matched to the end of the path (a home
#: directory included), so the whole path can be taken out of a string.
_LOCAL_PATH_WHOLE = re.compile(
    r"(?<![\w.-])(?:/Users|/home)/[^/\s\"']+[^\s\"']*"
    r"|(?<![\w:/.~\\-])/(?:root|private|var|tmp|opt|mnt|Volumes|media|srv|etc|usr|nix|run|workspaces?)/[^\s\"']*"
    r"|(?<![\w])[A-Za-z]:[\\/][^\s\"']+"
    r"|\\\\[A-Za-z0-9._-]+\\[^\s\"']+"
)


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def scan_text(text: str) -> list[str]:
    """The kinds of key or token ``text`` holds: a provider's own format, or a key-like name with a key-like value."""
    kinds = [kind for kind, rx in PATTERNS if rx.search(text)]
    for m in _KEY_NAME.finditer(text):
        if _keylike_value(m.group(2)):
            kinds.append(f"{m.group(1)} value")
    return list(dict.fromkeys(kinds))


#: Read in chunks this large; consecutive chunks overlap so a key across a boundary is still seen.
_CHUNK = 1 << 20
_OVERLAP = 512


def scan_file(path: Path) -> list[str]:
    """``scan_text`` over a whole file of any size, read in chunks; bytes that are not UTF-8 become U+FFFD."""
    kinds: list[str] = []
    tail = ""
    with open(path, "rb") as fh:
        while True:
            raw = fh.read(_CHUNK)
            if not raw:
                break
            text = tail + raw.decode("utf-8", errors="replace")
            kinds += scan_text(text)
            tail = text[-_OVERLAP:]
    return list(dict.fromkeys(kinds))


def scan_bytes(data: bytes) -> list[str]:
    return scan_text(data.decode("utf-8", errors="replace"))


def scan_files(root: Path, files: Any) -> list[str]:
    """``path: looks like a <kind>`` for every file under ``root`` (relative names) that holds a key or token.

    The one check before files leave this computer: ``e2er pack``, the Zenodo deposit, the GitHub
    push, and the scratch logs an export copies.
    """
    hits: list[str] = []
    for rel in files:
        p = Path(root) / str(rel)
        if not p.is_file() or p.is_symlink():
            continue
        try:
            kinds = scan_file(p)
        except OSError:
            continue
        hits += [f"{rel}: looks like a {kind}" for kind in kinds]
    return hits


def redact_text(text: str) -> tuple[str, list[str]]:
    """``text`` with every key or token replaced by ``[removed: <kind>]``; (new text, kinds found)."""
    kinds: list[str] = []

    def cut(kind: str) -> Any:
        def repl(m: re.Match[str]) -> str:
            kinds.append(kind)
            return f"[removed: {kind}]"

        return repl

    for kind, rx in PATTERNS:
        text = rx.sub(cut(kind), text)

    def name_value(m: re.Match[str]) -> str:
        if not _keylike_value(m.group(2)):
            return m.group(0)
        kinds.append(f"{m.group(1)} value")
        return m.group(0).replace(m.group(2), "[removed]")

    text = _KEY_NAME.sub(name_value, text)
    return text, list(dict.fromkeys(kinds))


def find_secrets(value: Any, path: str = "$") -> list[tuple[str, str]]:
    """(json path, kind) for every string in ``value`` that looks like a key or token."""
    if isinstance(value, str):
        hits = [(path, kind) for kind in scan_text(value)]
        hits += [(path, f"{m.group(1)}= value") for m in _ENV_LINE.finditer(value) if _entropy(m.group(2)) >= 3.5]
        return list(dict.fromkeys(hits))
    if isinstance(value, list):
        return [h for i, v in enumerate(value) for h in find_secrets(v, f"{path}[{i}]")]
    if isinstance(value, dict):
        return [h for k, v in value.items() for h in find_secrets(v, f"{path}.{k}")]
    return []


def find_local_paths(value: Any, path: str = "$") -> list[str]:
    """JSON paths of strings that name a path on this machine: a home directory (/Users/…,
    /home/…, C:\\Users\\…) or any other absolute local path (/private/var/…, /tmp/…, D:\\…, \\\\host\\share)."""
    if isinstance(value, str):
        return [path] if _LOCAL_PATH.search(value) else []
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


def strip_local_paths(value: Any) -> Any:
    """A copy in which every path on this machine (what `find_local_paths` finds) is cut
    to its last part: ``/Users/ann/.local/bin/claude`` becomes ``…/claude``.

    Strings without such a path come back unchanged, so a record that had none reads
    exactly as before.
    """

    def cut(m: re.Match[str]) -> str:
        whole = m.group(0).rstrip("/\\")
        if _HOME_PATH.fullmatch(whole):  # a home directory itself: its last part is the user name
            return "~"
        tail = re.split(r"[\\/]", whole)[-1]
        return f"…/{tail}" if tail else "…"

    if isinstance(value, str):
        if not _LOCAL_PATH.search(value):
            return value
        out = _LOCAL_PATH_WHOLE.sub(cut, value)
        # Whatever the whole-path pattern missed still goes.
        return _LOCAL_PATH.sub("…", out) if _LOCAL_PATH.search(out) else out
    if isinstance(value, list):
        return [strip_local_paths(v) for v in value]
    if isinstance(value, dict):
        return {k: strip_local_paths(v) for k, v in value.items()}
    return value
