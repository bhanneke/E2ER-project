"""Talking to e2er.org (or a staging copy) from the command line.

Sign-in follows the OAuth device flow (RFC 8628) against the platform's
``/api/auth/device/*``; the approved sign-in is exchanged for an ``e2er_``
token (``POST /api/v1/tokens``). The token is kept in the OS keychain when the
``keyring`` package is installed, otherwise in ``~/.e2er/credentials.json``
(mode 0600); ``E2ER_TOKEN`` overrides both. AI provider keys are never read
or sent here.

In a test run (src/core/test_guard.py) the keychain and the default
credentials file are never read or written, and only a local test server is
reached: e2er's own login never publishes from a test.
"""

from __future__ import annotations

import json
import os
import platform
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from . import test_guard

DEFAULT_URL = "https://e2er.org"
CLIENT_ID = "e2er-cli"
KEYRING_SERVICE = "e2er.org"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class PlatformError(Exception):
    """A request to the platform failed; the message is meant for the user."""


def base_url(url: str | None = None) -> str:
    return (url or os.environ.get("E2ER_URL") or DEFAULT_URL).rstrip("/")


def credentials_path() -> Path | None:
    """The credentials file: ``E2ER_CREDENTIALS``, else ``~/.e2er/credentials.json`` (None in a test run)."""
    explicit = os.environ.get("E2ER_CREDENTIALS")
    if explicit:
        return Path(explicit).expanduser()
    if not test_guard.saved_logins_allowed():
        return None
    return Path("~/.e2er/credentials.json").expanduser()


# Tests replace this with a client on an httpx.MockTransport.
def client_factory(url: str) -> httpx.Client:
    try:
        test_guard.check_target(url)
    except test_guard.RefusedInTestError as e:
        raise PlatformError(str(e)) from e
    return httpx.Client(base_url=url, timeout=30.0, headers={"user-agent": "e2er-cli"})


def _keyring():
    if not test_guard.saved_logins_allowed():
        return None  # a test run never touches the researcher's keychain
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    return keyring


def _write_credentials(url: str, token: str) -> Path:
    p = credentials_path()
    if p is None:
        raise PlatformError(
            f"e2er is running under a test runner ({test_guard.why_test_run()}): it keeps no login in the keychain "
            "or in ~/.e2er/credentials.json. Set E2ER_CREDENTIALS to a file of the test, or E2ER_TOKEN."
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data[url] = token
    # Created owner-only from the start, so the token is never readable by others.
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    p.chmod(0o600)
    return p


def save_token(url: str, token: str) -> str:
    """Store the token in the system keychain; fall back to the credentials file
    when there is no keyring or the keychain refuses (e.g. no GUI session)."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(KEYRING_SERVICE, url, token)
            return "the system keychain"
        except Exception:  # noqa: BLE001 - locked or unavailable keychain
            pass
    return str(_write_credentials(url, token))


def load_token(url: str) -> str | None:
    if os.environ.get("E2ER_TOKEN"):
        return os.environ["E2ER_TOKEN"]
    kr = _keyring()
    if kr is not None:
        try:
            t = kr.get_password(KEYRING_SERVICE, url)
        except Exception:  # noqa: BLE001 - locked or unavailable keychain
            t = None
        if t:
            return t
    p = credentials_path()
    if p is not None and p.is_file():
        return json.loads(p.read_text(encoding="utf-8")).get(url)
    return None


def forget_token(url: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(KEYRING_SERVICE, url)
        except Exception:  # noqa: BLE001 - nothing stored there
            pass
    p = credentials_path()
    if p is not None and p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.pop(url, None) is not None:
            p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _json(r: httpx.Response) -> dict[str, Any]:
    """The answer as a dict; a body that is not a JSON object is kept (shortened) under ``_body``."""
    try:
        data = r.json()
    except ValueError:
        return {"_body": r.text[:500]}
    return data if isinstance(data, dict) else {"_body": r.text[:500]}


def error_text(status: int, body: Any) -> str:
    """What the server said went wrong: its ``error`` (or ``message``), else the HTTP status and the body's start.

    An answer without an error text (a proxy's page, a database over its daily
    limit, an empty body) is shown as ``HTTP <status>: <first 200 characters>``
    rather than as an empty line.
    """
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raw = body["_body"] if "_body" in body else json.dumps(body, ensure_ascii=False) if body else ""
    else:
        raw = "" if body is None else str(body)
    excerpt = " ".join(str(raw).split())
    excerpt = (excerpt[:200] + "…") if len(excerpt) > 200 else excerpt
    return f"HTTP {status}: {excerpt or '(empty body)'}"


def _raise(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        raise PlatformError(f"{what}: {error_text(r.status_code, _json(r))}")


#: ``study:<owner>/<slug>``: a token that can only publish new versions of that study.
_STUDY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._-]{0,99}$")


def parse_study_scope(spec: str, *, scope: bool = True) -> str:
    """``owner/slug`` from ``study:owner/slug`` (``--scope``) or ``owner/slug`` (``--study``); ValueError says why."""
    raw = spec.strip()
    if scope and not raw.startswith("study:"):
        raise ValueError(f"--scope {spec!r}: the one scope is study:<owner>/<slug>, e.g. study:ada/fx-carry")
    study = raw.removeprefix("study:").strip().strip("/").lower()
    if not _STUDY.match(study):
        flag = "--scope" if scope else "--study"
        raise ValueError(f"{flag} {spec!r}: give the study as <owner>/<slug>, e.g. ada/fx-carry")
    return study


def study_token_body(study: str, name: str | None = None) -> dict[str, Any]:
    """The request for a study token (POST /api/v1/tokens): it may publish new versions of ``study`` only."""
    return {"name": (name or f"e2er token for {study}")[:120], "study": study}


def login(
    url: str,
    *,
    announce: Callable[[str, str], None],
    sleep: Callable[[float], None] | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    """Run the device flow; ``announce(verification_url, user_code)`` tells the user where to approve.

    With ``study`` the token made from the approved sign-in can only publish new versions of that study.
    """
    with client_factory(url) as c:
        r = c.post("/api/auth/device/code", json={"client_id": CLIENT_ID})
        _raise(r, "Could not start the sign-in")
        d = r.json()
        verify = d.get("verification_uri_complete") or d.get("verification_uri") or "/device"
        if verify.startswith("/"):
            verify = url + verify
        announce(verify, d["user_code"])
        interval = float(d.get("interval") or 5)
        deadline = time.monotonic() + float(d.get("expires_in") or 1800)
        wait = sleep or time.sleep
        while True:
            wait(interval)
            p = c.post(
                "/api/auth/device/token",
                json={"grant_type": GRANT, "device_code": d["device_code"], "client_id": CLIENT_ID},
            )
            if p.status_code == 200:
                access = p.json()["access_token"]
                break
            err = _json(p).get("error")
            if err == "authorization_pending":
                if time.monotonic() > deadline:
                    raise PlatformError("The sign-in code expired. Run `e2er login` again.")
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err == "access_denied":
                raise PlatformError("The sign-in was denied in the browser.")
            if err == "expired_token":
                raise PlatformError("The sign-in code expired. Run `e2er login` again.")
            _raise(p, "The sign-in failed")
        name = f"e2er command line on {platform.system() or 'a computer'}"
        body = study_token_body(study) if study else {"name": name}
        t = c.post("/api/v1/tokens", json=body, headers={"authorization": f"Bearer {access}"})
        _raise(t, "Could not create the command-line token")
        made = t.json()
        if study and made.get("study") != study:
            # A platform without study tokens made a token with every right: end it at once.
            c.delete("/api/v1/tokens/current", headers={"authorization": f"Bearer {made.get('token', '')}"})
            raise PlatformError(f"{url} does not make tokens limited to one study yet; no token was kept")
        return made


def create_study_token(url: str, token: str, study: str, name: str | None = None) -> dict[str, Any]:
    """With the personal token, a token that can only publish new versions of ``study`` (POST /api/v1/tokens)."""
    code, made = request(url, "POST", "/api/v1/tokens", token=token, body=study_token_body(study, name))
    if code not in (200, 201):
        raise PlatformError(f"Could not create the token for {study}: {error_text(code, made)}")
    if made.get("study") != study:
        if made.get("token"):
            request(url, "DELETE", "/api/v1/tokens/current", token=str(made["token"]))
        raise PlatformError(f"{url} does not make tokens limited to one study yet; no token was kept")
    return made


def request(
    url: str, method: str, path: str, *, token: str | None = None, body: Any = None
) -> tuple[int, dict[str, Any]]:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    # Astro refuses a non-GET request without a JSON content type as a cross-site form post.
    if body is None and method != "GET":
        body = {}
    with client_factory(url) as c:
        r = c.request(method, path, json=body, headers=headers)
    return r.status_code, _json(r)
