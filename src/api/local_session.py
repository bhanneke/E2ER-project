"""The local session: who may use the parts of the dashboard that touch this computer.

The setup page can list folders on this computer, write the settings file (API
keys included) and publish in the researcher's name. Those endpoints are
guarded by four rules together:

1. **A per-session token.** `e2er` makes a random token at start and opens the
   browser at ``/?t=<token>``. The server trades it for an HttpOnly,
   SameSite=Strict cookie (named per port, since cookies ignore ports) and
   redirects to the same page without the token. Guarded endpoints need that
   cookie (or the token in an ``X-E2ER-Token`` header, for scripts).
2. **Loopback only.** The request must come from 127.0.0.1 / ::1, whatever
   address the server was bound to.
3. **A local Host header.** ``Host`` must be ``127.0.0.1``, ``localhost`` or
   ``[::1]``. A page on another site that points its own domain name at
   127.0.0.1 (DNS rebinding) sends its own name here and is refused.
4. **Same origin.** A request that carries ``Origin`` (every cross-site request
   does) must come from this server's own origin; ``Sec-Fetch-Site`` must not
   say ``cross-site``. No CORS header is ever added for these endpoints.

The token lives in the process environment (``E2ER_SESSION_TOKEN``) so the
uvicorn worker sees the one `e2er` printed, and in ``~/.e2er/session-<port>.json``
(mode 600) so a second `e2er` can open the running dashboard with it.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

ENV_TOKEN = "E2ER_SESSION_TOKEN"
HEADER = "x-e2er-token"
QUERY = "t"

_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}

_token: str | None = None


def session_token() -> str:
    """This server's token: from the environment (set by `e2er`), else made once per process."""
    global _token
    env = os.environ.get(ENV_TOKEN)
    if env:
        return env
    if _token is None:
        _token = secrets.token_urlsafe(24)
    return _token


def new_token() -> str:
    return secrets.token_urlsafe(24)


def cookie_name(request: Request) -> str:
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return f"e2er_session_{port}"


def _host_is_local(host_header: str) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8280
        host = host[: host.find("]") + 1] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host in _LOCAL_HOSTNAMES


def _client_is_loopback(request: Request) -> bool:
    client = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(client).is_loopback
    except ValueError:
        return False


def has_session(request: Request) -> bool:
    """Does this request carry the session token (cookie or header)?"""
    presented = request.headers.get(HEADER) or request.cookies.get(cookie_name(request)) or ""
    return bool(presented) and secrets.compare_digest(presented, session_token())


def local_problem(request: Request) -> str:
    """Why a request may not use the local endpoints ("" when it may)."""
    if not _client_is_loopback(request):
        return "This page only works on the computer e2er runs on."
    host = request.headers.get("host", "")
    if not _host_is_local(host):
        return "This page only works at 127.0.0.1 or localhost."
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != f"{request.url.scheme}://{host}":
        return "Requests from other sites are refused."
    if request.headers.get("sec-fetch-site", "") == "cross-site":
        return "Requests from other sites are refused."
    if not has_session(request):
        return "For your safety, this part only works from the link e2er opened. Run `e2er` in the terminal again."
    return ""


def require_local_session(request: Request) -> None:
    """FastAPI dependency for every endpoint that touches this computer."""
    problem = local_problem(request)
    if problem:
        raise HTTPException(status_code=403, detail=problem)


# ── the session file a second `e2er` reads ──────────────────────────────────


def session_file(port: int) -> Path:
    return Path.home() / ".e2er" / f"session-{port}.json"


def write_session_file(port: int, token: str) -> Path:
    p = session_file(port)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"token": token, "pid": os.getpid(), "port": port}, fh)
    os.chmod(p, 0o600)
    return p


def read_session_token(port: int) -> str | None:
    try:
        return str(json.loads(session_file(port).read_text(encoding="utf-8"))["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remove_session_file(port: int) -> None:
    try:
        data = json.loads(session_file(port).read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            session_file(port).unlink()
    except (OSError, ValueError):
        pass
