"""No publishing from a test run.

Run inside a test runner, e2er never signs in with the researcher's own login
and never publishes anywhere but a local test server:

- **A test run** is one with ``PYTEST_CURRENT_TEST`` set (pytest sets it for
  each test, and a command a test starts inherits it), ``E2ER_TEST=1``, or
  ``CI=true`` together with a test command (pytest, unittest, nose2, tox, nox).
- **No saved login**: the system keychain is never read or written, nor the
  default credentials file (``~/.e2er/credentials.json``). Only ``E2ER_TOKEN``
  and a credentials file the test names itself (``E2ER_CREDENTIALS``) are used.
  The same holds for the Zenodo token: only ``ZENODO_TOKEN`` /
  ``ZENODO_SANDBOX_TOKEN`` from the environment.
- **Local targets only**: a request to e2er.org, a staging copy or Zenodo is
  refused before it is made. Allowed are ``localhost``, ``127.0.0.1`` (and
  the rest of 127.0.0.0/8), ``::1``, and the one address in ``E2ER_TEST_SERVER``
  (e2er's own integration tests run a local copy of the platform there; it may
  never name e2er.org).
- **No GitHub**: ``gh`` and pushes to GitHub are refused, unless
  ``E2ER_TEST_GITHUB=fake`` (e2er's own tests, with a fake ``gh``).

On 2026-10-20 a run of e2er's own test suite on a machine signed in to e2er.org
published test studies there with the machine's token.
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from urllib.parse import urlsplit

#: Names a test server for e2er's own integration tests (a local copy of the platform).
TEST_SERVER_VAR = "E2ER_TEST_SERVER"
#: e2er's own tests of `publish --github` run a fake gh; this lets them through.
TEST_GITHUB_VAR = "E2ER_TEST_GITHUB"
_TEST_COMMANDS = ("pytest", "py.test", "unittest", "nose2", "tox", "nox")
_PRODUCTION = ("e2er.org",)


class RefusedInTestError(RuntimeError):
    """A test run asked e2er to sign in or publish somewhere it must not. Nothing was sent."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _test_command() -> bool:
    """Whether this process is a test runner (or was started by one in-process)."""
    if "pytest" in sys.modules or "_pytest" in sys.modules:
        return True
    # `pytest`, `python -m pytest` (…/pytest/__main__.py), `python -m unittest`, `tox`, …: a word of argv[0].
    words = {
        w.removesuffix(".py").removesuffix(".exe") for w in re.split(r"[\s/\\]+", (sys.argv[:1] or [""])[0].lower())
    }
    return bool(words & set(_TEST_COMMANDS))


def why_test_run() -> str | None:
    """What makes this a test run, in a few words, or None when it is not one."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "PYTEST_CURRENT_TEST is set"
    if _truthy(os.environ.get("E2ER_TEST")):
        return "E2ER_TEST=1"
    if _truthy(os.environ.get("CI")) and _test_command():
        return "CI=true and a test command is running"
    return None


def under_test() -> bool:
    return why_test_run() is not None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _production(host: str) -> bool:
    return any(host == p or host.endswith("." + p) for p in _PRODUCTION)


def test_server() -> str | None:
    """The test server ``E2ER_TEST_SERVER`` names (without a trailing /), or None.

    Raises RefusedInTestError when it names e2er.org or one of its subdomains.
    """
    raw = (os.environ.get(TEST_SERVER_VAR) or "").strip().rstrip("/")
    if not raw:
        return None
    if urlsplit(raw).scheme not in ("http", "https") or not _host(raw):
        raise RefusedInTestError(f"{TEST_SERVER_VAR}={raw!r} is not an http(s) address")
    if _production(_host(raw)):
        raise RefusedInTestError(
            f"{TEST_SERVER_VAR} names {raw}: it is for a local test server, never for e2er.org. Nothing was sent."
        )
    return raw


def target_allowed(url: str) -> bool:
    """Whether a test run may send to ``url``: a loopback address, or the E2ER_TEST_SERVER address."""
    host = _host(url)
    if not host:
        return False
    if _loopback(host):
        return True
    server = test_server()
    if server is None:
        return False
    s = urlsplit(server)
    u = urlsplit(url)
    return (u.scheme, (u.hostname or "").lower(), u.port) == (s.scheme, (s.hostname or "").lower(), s.port)


def check_target(url: str) -> None:
    """Refuse (RefusedInTestError) a request a test run must not make; nothing when this is not a test run."""
    why = why_test_run()
    if why is None or target_allowed(url):
        return
    raise RefusedInTestError(
        f"e2er is running under a test runner ({why}), so it sends nothing to {url}: only to a local test "
        f"server (localhost, 127.0.0.1) or the address in {TEST_SERVER_VAR}. Nothing was sent."
    )


def saved_logins_allowed() -> bool:
    """Whether the keychain and the default credentials file may be read or written: never in a test run."""
    return not under_test()


def check_github() -> None:
    """Refuse gh and pushes to GitHub in a test run, unless e2er's own tests run a fake gh."""
    why = why_test_run()
    if why is None or (os.environ.get(TEST_GITHUB_VAR) or "").strip().lower() == "fake":
        return
    raise RefusedInTestError(
        f"e2er is running under a test runner ({why}), so it does not use gh or push to GitHub. Nothing was pushed."
    )
