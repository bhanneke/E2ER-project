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

From 0.14.0 to 0.18.x the token was kept for good in ``~/.e2er/session-secret`` and the cookie
lasted a year. Since 0.19.0 every start of e2er makes a new token and the cookie lasts until
the browser closes: a token that leaked once (a shared screen, a shell history) is worth
nothing after the next start. The old file is removed at start.

Two checks apply to every request, not only to the local endpoints (``guard_request``):
the ``Host`` header must name this computer (127.0.0.1, localhost, [::1], or a host
configured with ``--host``/``HOST``/``E2ER_ALLOWED_HOSTS``), so a page that points its own
domain at 127.0.0.1 (DNS rebinding) reaches nothing; and every ``/api/`` route needs the
session token or the ``API_AUTH_TOKEN`` bearer token.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

ENV_TOKEN = "E2ER_SESSION_TOKEN"
#: The cookie shared by every e2er dashboard on this computer (cookies ignore ports).
SHARED_COOKIE = "e2er_session"
#: Hosts that name every computer's own address; ``HOST``, ``--host`` and ``E2ER_ALLOWED_HOSTS`` add more.
ENV_SERVE_HOST = "E2ER_SERVE_HOST"
ENV_ALLOWED_HOSTS = "E2ER_ALLOWED_HOSTS"
_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]", "*"}
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


def secret_file() -> Path:
    return Path.home() / ".e2er" / "session-secret"


def forget_stable_secret() -> None:
    """Remove ``~/.e2er/session-secret``, the token 0.14.0-0.18.x kept across starts."""
    try:
        secret_file().unlink()
    except OSError:
        pass


def cookie_name(request: Request) -> str:
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return f"e2er_session_{port}"


def _host_name(host_header: str) -> str:
    """``Host: 127.0.0.1:8280`` -> ``127.0.0.1``; ``[::1]:8280`` -> ``[::1]``."""
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8280
        host = host[: host.find("]") + 1] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host


def _host_is_local(host_header: str) -> bool:
    return _host_name(host_header) in _LOCAL_HOSTNAMES


def allowed_hosts() -> set[str]:
    """The host names this server answers to: this computer's, plus the ones configured.

    ``e2er serve --host <name>`` (``E2ER_SERVE_HOST``), ``HOST`` in the settings and the
    comma-separated ``E2ER_ALLOWED_HOSTS`` add a name; a wildcard bind (0.0.0.0) adds none.
    """
    names = set(_LOCAL_HOSTNAMES)
    raw = [os.environ.get(ENV_SERVE_HOST, ""), *os.environ.get(ENV_ALLOWED_HOSTS, "").split(",")]
    try:
        from ..config import get_settings

        s = get_settings()
        for value in (getattr(s, "host", ""), getattr(s, "allowed_hosts", "")):
            if isinstance(value, str):
                raw.extend(value.split(","))
    except Exception:  # noqa: BLE001 — a settings error must not open the server
        pass
    for value in raw:
        h = value.strip().lower()
        if h in _WILDCARD_HOSTS:
            continue
        names.add(h)
        if ":" in h and not h.startswith("["):
            names.add(f"[{h}]")  # an IPv6 address arrives in brackets
    return names


def host_allowed(request: Request) -> bool:
    """Does the ``Host`` header name this server? (No header at all: refused.)"""
    host = request.headers.get("host", "")
    return bool(host) and _host_name(host) in allowed_hosts()


def _bearer_configured() -> bool:
    try:
        from ..config import get_settings

        expected = getattr(get_settings(), "api_auth_token", None)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(expected, str) and bool(expected)


def bearer_ok(request: Request) -> bool | None:
    """True/False for an ``Authorization: Bearer`` header when ``API_AUTH_TOKEN`` is set; None otherwise."""
    try:
        from ..config import get_settings

        expected = getattr(get_settings(), "api_auth_token", None)
    except Exception:  # noqa: BLE001
        expected = None
    auth = request.headers.get("authorization") or ""
    if not (isinstance(expected, str) and expected and auth.startswith("Bearer ")):
        return None
    return secrets.compare_digest(auth[len("Bearer ") :].strip(), expected)


#: ``/api/`` paths that answer without the session (none today; /health is outside /api/).
OPEN_API_PATHS: frozenset[str] = frozenset()


def guard_request(request: Request) -> tuple[int, str] | None:
    """The checks every request passes: a known Host, and the session on ``/api/``. None = pass."""
    if not host_allowed(request):
        return 400, "Invalid Host header: e2er answers at 127.0.0.1 or localhost (or a host set with --host)."
    path = request.url.path
    if path.startswith("/api/") and path not in OPEN_API_PATHS and request.method != "OPTIONS":
        bearer = bearer_ok(request)
        if bearer is False:
            return 401, "Invalid bearer token"
        if not bearer and not has_session(request):
            if _bearer_configured():
                return 401, "Missing bearer token"
            return 403, (
                "This browser tab is not signed in to e2er. Run `e2er` in a terminal: it opens the dashboard "
                "signed in. Scripts use the e2er commands."
            )
    return None


def _client_is_loopback(request: Request) -> bool:
    client = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(client).is_loopback
    except ValueError:
        return False


def has_session(request: Request) -> bool:
    """Does this request carry the session token (cookie or header)?"""
    token = session_token()
    presented = (
        request.headers.get(HEADER),
        request.cookies.get(cookie_name(request)),
        request.cookies.get(SHARED_COOKIE),
    )
    return any(p and secrets.compare_digest(p, token) for p in presented)


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
        return "This browser tab is not signed in to e2er. Run `e2er` in a terminal: it opens the dashboard signed in."
    return ""


def require_local_session(request: Request) -> None:
    """FastAPI dependency for every endpoint that touches this computer."""
    problem = local_problem(request)
    if problem:
        raise HTTPException(status_code=403, detail=problem)


# ── the session file a second `e2er` reads ──────────────────────────────────


def session_file(port: int) -> Path:
    return Path.home() / ".e2er" / f"session-{port}.json"


def set_session_cookies(response: Any, request: Request, token: str) -> None:
    """The cookies that carry the session: one for this port, one shared by every port."""
    for name in (cookie_name(request), SHARED_COOKIE):
        # No max_age: the cookie ends with the browser session (the token ends with this start of e2er).
        response.set_cookie(name, token, httponly=True, samesite="strict", path="/")


def write_session_file(port: int, token: str, *, pid: int | None = None) -> Path:
    """Record the token of the server on ``port``; ``pid`` is the server's process (default: this one)."""
    p = session_file(port)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"token": token, "pid": pid if pid is not None else os.getpid(), "port": port}, fh)
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
