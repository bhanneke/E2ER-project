"""``e2er zenodo login``, ``logout`` and ``status``: the researcher's own Zenodo token.

    e2er zenodo login [--sandbox] [--no-browser]
    e2er zenodo status [--sandbox]
    e2er zenodo logout [--sandbox]

``login`` opens Zenodo's page for a new personal token, reads the pasted token
without showing it, checks it with a request that changes nothing, and stores
it in the system keychain (service ``zenodo.org`` or ``sandbox.zenodo.org``,
username ``token``), or in ``~/.e2er/credentials.json`` (mode 0600) when there
is no keychain. ``e2er publish --zenodo`` and ``e2er preregister deposit
--zenodo`` read it from there; ``ZENODO_TOKEN`` / ``ZENODO_SANDBOX_TOKEN`` from
the environment still come first (CI). The token is never printed or logged.
"""

from __future__ import annotations

import getpass
import os
import socket
import sys
import webbrowser

from .core import zenodo as zen

#: Zenodo's page for a new personal token. Its form takes no values from the address, so the
#: scopes cannot be ticked in advance (invenio-oauth2server builds the form from POST data only).
NEW_TOKEN_PATH = "/account/settings/applications/tokens/new/"


def new_token_url(sandbox: bool = False) -> str:
    return zen.base_url(sandbox) + NEW_TOKEN_PATH


def _read_token() -> str:
    """The pasted token: a hidden prompt at a terminal, else one line from standard input (a pipe)."""
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass("Paste the token here (it is not shown): ").strip()
    line = sys.stdin.readline() if sys.stdin is not None else ""
    return line.strip()


def login(*, sandbox: bool = False, open_browser: bool = True) -> int:
    site = zen.service(sandbox)
    url = new_token_url(sandbox)
    try:
        host = socket.gethostname().split(".")[0] or "this computer"
    except OSError:
        host = "this computer"
    print(f"1. Sign in to {site} and open {url}")
    print(f"2. Name the token, e.g. 'e2er on {host}'.")
    print("3. Tick the scopes deposit:write and deposit:actions, then Create.")
    print("4. Copy the token Zenodo shows (it is shown only once) and paste it below.")
    if sandbox:
        print("   The sandbox is a separate account with its own tokens: a zenodo.org token does not work there.")
    if open_browser and sys.stdout.isatty():
        webbrowser.open(url)
    sys.stdout.flush()
    try:
        token = _read_token()
    except (EOFError, KeyboardInterrupt):
        print("\nNothing was stored.")
        return 1
    if not token:
        print("error: no token was pasted; nothing was stored.")
        return 1
    if any(c.isspace() for c in token):
        print("error: that is not a token (it contains spaces); nothing was stored.")
        return 1
    check = zen.check_token(token, sandbox)
    if not check.works:
        print(f"error: {check.message}. Nothing was stored.")
        return 1
    print(f"✓ {check.message}.")
    try:
        where = zen.save_token(token, sandbox)
    except zen.ZenodoError as e:
        print(f"error: {e}")
        return 1
    print(f"✓ The {site} token is kept in {where}.")
    print(
        "  Zenodo does not tell which scopes a token has, and testing deposit:write or deposit:actions would "
        "create or publish a record, so they were not tested. If one is missing, Zenodo refuses the first deposit "
        "(403): nothing is published, though an unpublished draft may be left in your Zenodo uploads."
    )
    env = zen.env_var(sandbox)
    if (os.environ.get(env) or "").strip():
        print(f"  Note: {env} is set in this shell and is used before the stored token.")
    return 0


def status(*, sandbox: bool = False) -> int:
    site = zen.service(sandbox)
    token, where = zen.find_token(sandbox)
    stored, stored_where = zen.stored_token(sandbox)
    if not token:
        print(f"No {site} token is stored. Run `e2er zenodo login{' --sandbox' if sandbox else ''}`.")
        return 1
    print(f"A {site} token is in {where}.")
    if stored and stored_where != where:
        print(f"  (A stored token in {stored_where} is not used while {where} has one.)")
    check = zen.check_token(token, sandbox)
    print(("✓ " if check.works else "✗ ") + check.message + ".")
    return 0 if check.works else 1


def logout(*, sandbox: bool = False) -> int:
    site = zen.service(sandbox)
    try:
        removed = zen.forget_token(sandbox)
    except OSError as e:
        print(f"error: could not remove the token: {e}")
        return 1
    if removed:
        print(f"✓ Removed the {site} token from {' and '.join(removed)}.")
        print(
            "  It still works on Zenodo until you delete it there: "
            f"{zen.base_url(sandbox)}/account/settings/applications/"
        )
    else:
        print(f"No {site} token was stored.")
    env = zen.env_var(sandbox)
    if (os.environ.get(env) or "").strip():
        print(f"  Note: {env} is still set in this shell.")
    return 0
