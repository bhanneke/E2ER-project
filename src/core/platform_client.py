"""Talking to e2er.org (or a staging copy) from the command line.

Sign-in follows the OAuth device flow (RFC 8628) against the platform's
``/api/auth/device/*``; the approved sign-in is exchanged for an ``e2er_``
token (``POST /api/v1/tokens``). The token is kept in the OS keychain (``keyring``), or in
``~/.e2er/credentials.json`` (mode 0600) when the computer has no keychain
backend or it refuses; ``E2ER_TOKEN`` overrides both. AI provider keys are never read
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


def _loopback(host: str) -> bool:
    import ipaddress

    h = host.strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def check_platform_url(url: str) -> str:
    """``url`` when a token may go there: https, or http to this computer only (a local test server)."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    if not host or parts.username or parts.password:
        raise PlatformError(f"{url} is not a platform address")
    if parts.scheme == "https" or (parts.scheme == "http" and _loopback(host)):
        return url
    raise PlatformError(f"refusing {url}: a platform is reached over https (http only for a server on this computer)")


def _same_host(url: str, path: str) -> None:
    """A request path stays on the platform the token belongs to (never an absolute URL elsewhere)."""
    from urllib.parse import urlsplit

    target = urlsplit(path)
    if not target.scheme and not target.netloc:
        if not path.startswith("/"):
            raise PlatformError(f"refusing the request path {path[:80]!r}: not a path on {url}")
        return
    base = urlsplit(url)
    if (target.scheme, target.hostname, target.port) != (base.scheme, base.hostname, base.port):
        raise PlatformError(f"refusing to send the token for {url} to {target.scheme}://{target.hostname}")


# Tests replace this with a client on an httpx.MockTransport.
def client_factory(url: str) -> httpx.Client:
    check_platform_url(url)
    try:
        test_guard.check_target(url)
    except test_guard.RefusedInTestError as e:
        raise PlatformError(str(e)) from e
    return httpx.Client(base_url=url, timeout=30.0, headers={"user-agent": "e2er-cli"}, follow_redirects=False)


def _keyring():
    """The ``keyring`` module when it has a usable backend, else None (then the credentials file is used).

    ``keyring`` is a dependency of e2er, but a computer may have no keychain to back it: a headless
    Linux server or a CI runner without a Secret Service selects keyring's ``fail`` backend (priority
    0), whose every call raises. That counts as no keychain, as does a ``keyring`` that cannot be
    imported or whose backend cannot be loaded (a broken ``PYTHON_KEYRING_BACKEND``).
    """
    if not test_guard.saved_logins_allowed():
        return None  # a test run never touches the researcher's keychain
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - not installed, or a backend that fails at import
        return None
    get_keyring = getattr(keyring, "get_keyring", None)
    if get_keyring is None:
        return keyring
    try:
        backend = get_keyring()
        priority = float(getattr(backend, "priority", 1))
    except Exception:  # noqa: BLE001 - no backend can be loaded
        return None
    if priority <= 0:  # keyring.backends.fail / null: no keychain on this computer
        return None
    return keyring


def _warn(message: str) -> None:
    import sys

    print(f"warning: {message}", file=sys.stderr)


def _read_credentials(p: Path) -> dict[str, Any]:
    """The credentials file's tokens; {} when it is missing, and {} with a warning when it is damaged."""
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _warn(f"{p} cannot be read ({type(e).__name__}); its tokens are ignored. Sign in again to replace it.")
        return {}
    if not isinstance(data, dict):
        _warn(f"{p} is not a JSON object; its tokens are ignored. Sign in again to replace it.")
        return {}
    return data


def _store_credentials(p: Path, data: dict[str, Any]) -> None:
    """Write the file owner-only from the first byte: a 0600 temporary file in the same folder, then os.replace.

    The folder (``~/.e2er``) is made 0700 when e2er makes it. A reader never sees a half-written file.
    """
    import tempfile

    folder = p.parent
    if not folder.exists():
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
    elif folder == Path("~/.e2er").expanduser():
        os.chmod(folder, 0o700)  # e2er's own folder: other users see nothing in it
    fd, tmp = tempfile.mkstemp(prefix=".credentials-", suffix=".tmp", dir=folder)  # mode 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


#: The credentials file's list of keys whose token there is newer than a copy the keychain may still hold:
#: saved while the keychain refused (locked), so the keychain's older copy could not be removed either.
FILE_FIRST = "_newer_than_keychain"


def file_first(key: str) -> bool:
    """True when the credentials file's token for ``key`` is to be read before the keychain's."""
    p = credentials_path()
    if p is None or not p.is_file():
        return False
    listed = _read_credentials(p).get(FILE_FIRST)
    return isinstance(listed, list) and key in listed


def _write_credentials(url: str, token: str, *, newer_than_keychain: bool = False) -> Path:
    p = credentials_path()
    if p is None:
        raise PlatformError(
            f"e2er is running under a test runner ({test_guard.why_test_run()}): it keeps no login in the keychain "
            "or in ~/.e2er/credentials.json. Set E2ER_CREDENTIALS to a file of the test, or E2ER_TOKEN."
        )
    data = _read_credentials(p)
    if p.is_file() and not data and p.stat().st_size > 0:
        # A damaged file is kept beside the new one (owner-only), not overwritten unread.
        kept = p.with_name(p.name + ".damaged")
        os.replace(p, kept)
        os.chmod(kept, 0o600)
        _warn(f"the damaged credentials file was kept as {kept}")
    data[url] = token
    listed = [k for k in data.get(FILE_FIRST) or [] if isinstance(k, str) and k != url]
    if newer_than_keychain:
        listed.append(url)
    if listed:
        data[FILE_FIRST] = listed
    else:
        data.pop(FILE_FIRST, None)
    _store_credentials(p, data)
    return p


def _remove_credential(key: str) -> Path | None:
    """Remove ``key`` from the credentials file; the file when something was removed."""
    p = credentials_path()
    if p is None or not p.is_file():
        return None
    data = _read_credentials(p)
    listed = data.get(FILE_FIRST)
    if isinstance(listed, list) and key in listed:
        listed = [k for k in listed if k != key]
        if listed:
            data[FILE_FIRST] = listed
        else:
            data.pop(FILE_FIRST)
        if data.pop(key, None) is None:
            _store_credentials(p, data)
            return None
    elif data.pop(key, None) is None:
        return None
    _store_credentials(p, data)
    return p


def save_token(url: str, token: str) -> str:
    """Store the token in the system keychain; fall back to the credentials file
    when there is no keyring or the keychain refuses (e.g. no GUI session).

    The other store's copy is removed afterwards, so an old token never stays behind in the file
    once the keychain holds the new one (or the other way round). A token that goes to the file because
    the keychain refused it is marked newer than the keychain's (FILE_FIRST): a locked keychain cannot
    remove its older copy either, and that copy must not win once it is unlocked.
    """
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(KEYRING_SERVICE, url, token)
        except Exception:  # noqa: BLE001 - locked or unavailable keychain
            pass
        else:
            _remove_credential(url)
            return "the system keychain"
    where = str(_write_credentials(url, token, newer_than_keychain=kr is not None))
    if kr is not None:
        try:
            kr.delete_password(KEYRING_SERVICE, url)
        except Exception:  # noqa: BLE001 - nothing stored there, or the keychain is locked
            pass
    return where


def load_token(url: str) -> str | None:
    if os.environ.get("E2ER_TOKEN"):
        return os.environ["E2ER_TOKEN"]
    p = credentials_path()
    if p is not None and file_first(url):  # saved while the keychain refused: newer than its copy
        value = _read_credentials(p).get(url)
        if isinstance(value, str) and value:
            return value
    kr = _keyring()
    if kr is not None:
        try:
            t = kr.get_password(KEYRING_SERVICE, url)
        except Exception:  # noqa: BLE001 - locked or unavailable keychain
            t = None
        if t:
            return t
    p = credentials_path()
    if p is not None:
        value = _read_credentials(p).get(url)
        return value if isinstance(value, str) else None
    return None


def forget_token(url: str) -> list[str]:
    """Remove the saved login for ``url`` from the keychain and the credentials file.

    Returns what could not be removed, for the researcher to see: a keychain that refused (locked, no
    session) may still hold the token. Nothing stored is not a problem.
    """
    left: list[str] = []
    kr = _keyring()
    if kr is not None:
        try:
            if kr.get_password(KEYRING_SERVICE, url):
                kr.delete_password(KEYRING_SERVICE, url)
        except Exception as e:  # noqa: BLE001 - locked or unavailable keychain
            left.append(f"the system keychain (it refused: {type(e).__name__}; it may be locked)")
    _remove_credential(url)
    return left


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
    check_platform_url(url)
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
    if token:
        check_platform_url(url)
        _same_host(url, path)
    headers = {"authorization": f"Bearer {token}"} if token else {}
    # Astro refuses a non-GET request without a JSON content type as a cross-site form post.
    if body is None and method != "GET":
        body = {}
    with client_factory(url) as c:
        r = c.request(method, path, json=body, headers=headers, follow_redirects=False)
    return r.status_code, _json(r)
