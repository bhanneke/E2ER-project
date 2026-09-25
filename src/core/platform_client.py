"""Talking to e2er.org (or a staging copy) from the command line.

Sign-in follows the OAuth device flow (RFC 8628) against the platform's
``/api/auth/device/*``; the approved sign-in is exchanged for an ``e2er_``
token (``POST /api/v1/tokens``). The token is kept in the OS keychain when the
``keyring`` package is installed, otherwise in ``~/.e2er/credentials.json``
(mode 0600); ``E2ER_TOKEN`` overrides both. AI provider keys are never read
or sent here.
"""

from __future__ import annotations

import json
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

DEFAULT_URL = "https://e2er.org"
CLIENT_ID = "e2er-cli"
KEYRING_SERVICE = "e2er.org"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class PlatformError(Exception):
    """A request to the platform failed; the message is meant for the user."""


def base_url(url: str | None = None) -> str:
    return (url or os.environ.get("E2ER_URL") or DEFAULT_URL).rstrip("/")


def credentials_path() -> Path:
    return Path(os.environ.get("E2ER_CREDENTIALS", "~/.e2er/credentials.json")).expanduser()


# Tests replace this with a client on an httpx.MockTransport.
def client_factory(url: str) -> httpx.Client:
    return httpx.Client(base_url=url, timeout=30.0, headers={"user-agent": "e2er-cli"})


def _keyring():
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    return keyring


def save_token(url: str, token: str) -> str:
    kr = _keyring()
    if kr is not None:
        kr.set_password(KEYRING_SERVICE, url, token)
        return "the system keychain"
    p = credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data[url] = token
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    p.chmod(0o600)
    return str(p)


def load_token(url: str) -> str | None:
    if os.environ.get("E2ER_TOKEN"):
        return os.environ["E2ER_TOKEN"]
    kr = _keyring()
    if kr is not None:
        t = kr.get_password(KEYRING_SERVICE, url)
        if t:
            return t
    p = credentials_path()
    if p.is_file():
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
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.pop(url, None) is not None:
            p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _json(r: httpx.Response) -> dict[str, Any]:
    try:
        return r.json()
    except ValueError:
        return {"error": r.text[:200]}


def _raise(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        body = _json(r)
        raise PlatformError(f"{what}: {body.get('error') or body.get('message') or r.status_code}")


def login(
    url: str,
    *,
    announce: Callable[[str, str], None],
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run the device flow; ``announce(verification_url, user_code)`` tells the user where to approve."""
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
        t = c.post("/api/v1/tokens", json={"name": name}, headers={"authorization": f"Bearer {access}"})
        _raise(t, "Could not create the command-line token")
        return t.json()


def request(
    url: str, method: str, path: str, *, token: str | None = None, body: Any = None
) -> tuple[int, dict[str, Any]]:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    with client_factory(url) as c:
        r = c.request(method, path, json=body, headers=headers)
    return r.status_code, _json(r)
