"""The researcher's approval of a production query, sealed so that a model cannot forge it.

The approval lived only in the run database (``data_approval_requests.status``), and the
model's shell could write that database: it holds the file (SQLite) or, under Postgres, had the
password. Since 0.19.0 the dashboard seals each decision with an HMAC (SHA-256) over the query's
id, the decision and the query's SQL, keyed with a secret in ``~/.e2er/approval-key`` (mode 600),
and keeps the seal in ``~/.e2er/approvals/<query id>.json``. ``check_approval`` counts an
"approved" row only with a seal that matches; a row without one stays pending.

What this does and does not hold: Claude Code's specialists cannot read or write ``~/.e2er``
(``--disallowedTools``), and no backend gets the key in its environment. Codex's sandbox does
not stop reading files, so under Codex a shell command can still read the key; the seal then
only stops a model that writes the database without it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def is_query_id(value: object) -> bool:
    """A query id (e2er makes UUIDs): letters, digits and ``-`` only, so it can name a seal file."""
    return isinstance(value, str) and bool(_ID.match(value))


def _dir() -> Path:
    return Path.home() / ".e2er"


def key_file() -> Path:
    return _dir() / "approval-key"


def seals_dir() -> Path:
    return _dir() / "approvals"


def _key(create: bool) -> bytes | None:
    p = key_file()
    try:
        text = p.read_text(encoding="utf-8").strip()
        if len(text) >= 64:
            return bytes.fromhex(text[:64])
    except (OSError, ValueError):
        pass
    if not create:
        return None
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = secrets.token_bytes(32)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(raw.hex() + "\n")
    os.replace(tmp, p)
    return raw


def _mac(key: bytes, query_id: str, status: str, sql: str) -> str:
    msg = f"{query_id}\n{status}\n{hashlib.sha256(sql.encode('utf-8')).hexdigest()}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def seal(query_id: str, status: str, sql: str) -> None:
    """Record the researcher's decision (called by the dashboard, never by a wrapper)."""
    if not _ID.match(query_id):
        raise ValueError(f"not a query id: {query_id!r}")
    key = _key(create=True)
    assert key is not None
    d = seals_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = d / f"{query_id}.json"
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"status": status, "mac": _mac(key, query_id, status, sql)}, fh)
    os.replace(tmp, path)


def is_sealed(query_id: str, status: str, sql: str) -> bool:
    """Did the dashboard record this decision for this query and this SQL?"""
    if not _ID.match(str(query_id)):
        return False
    key = _key(create=False)
    if key is None:
        return False
    try:
        doc = json.loads((seals_dir() / f"{query_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict) or doc.get("status") != status:
        return False
    return hmac.compare_digest(str(doc.get("mac") or ""), _mac(key, query_id, status, sql))
