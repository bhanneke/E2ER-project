"""The keychain and the credentials file: the newer token wins, and a logout says what it could not remove.

Found in the review of 2026-10-23 (zenodo.py, platform_client.py): the keychain was always read first. A new
token saved while the keychain was locked went to the credentials file, the older token stayed in the
keychain (it could not be removed either), and once the keychain was unlocked again the stale token won.
`e2er logout` and `e2er zenodo logout` with a locked keychain said "Signed out" or "No token was stored"
although the token was still in the keychain.
"""

from __future__ import annotations

import sys

import pytest

from src import cli_platform, cli_zenodo
from src.core import platform_client as pc
from src.core import zenodo as zen
from tests.test_keyring_backend import REAL_KEYRING, Backend, stand_in

URL = "https://e2er.org"


@pytest.fixture
def backend(monkeypatch, tmp_path) -> Backend:
    """A keychain stand-in (never this computer's) and a credentials file of the test."""
    from src.core import test_guard

    monkeypatch.setenv("E2ER_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.delenv("E2ER_TOKEN", raising=False)
    monkeypatch.setattr(pc, "_keyring", REAL_KEYRING)
    monkeypatch.setattr(test_guard, "saved_logins_allowed", lambda: True)
    b = Backend(priority=1)
    monkeypatch.setitem(sys.modules, "keyring", stand_in(b))
    return b


def test_a_token_saved_while_the_keychain_is_locked_wins_once_it_is_unlocked(backend: Backend):
    assert pc.save_token(URL, "old") == "the system keychain"
    backend.refuse = True  # locked: the new token goes to the file; the old one cannot be removed
    assert pc.save_token(URL, "new") != "the system keychain"
    backend.refuse = False
    assert backend.store[(pc.KEYRING_SERVICE, URL)] == "old", "the stand-in kept the stale copy"
    assert pc.load_token(URL) == "new"
    # Saved in the keychain again: the file's copy and its precedence go.
    assert pc.save_token(URL, "newest") == "the system keychain"
    assert pc.load_token(URL) == "newest"
    assert URL not in pc._read_credentials(pc.credentials_path())
    assert not pc._read_credentials(pc.credentials_path()).get(pc.FILE_FIRST)


def test_the_same_for_the_zenodo_token(backend: Backend):
    assert zen.save_token("old") == "the system keychain"
    backend.refuse = True
    zen.save_token("new")
    backend.refuse = False
    assert zen.stored_token()[0] == "new"
    assert zen.load_token() == "new"
    assert zen.save_token("newest") == "the system keychain"
    assert zen.stored_token() == ("newest", "the system keychain")


def test_a_saved_token_removes_the_other_copy(backend: Backend, monkeypatch):
    """The security fix of 2026-10-23: one store holds the token, the other copy goes (verified here)."""
    backend.refuse = True
    pc.save_token(URL, "file-copy")
    backend.refuse = False
    assert pc.save_token(URL, "keychain-copy") == "the system keychain"
    assert URL not in pc._read_credentials(pc.credentials_path())
    # And the other way round: the keychain refuses the new token but lets the old one be removed.
    monkeypatch.setattr(backend, "set_password", lambda *a: (_ for _ in ()).throw(RuntimeError("refused")))
    monkeypatch.setitem(sys.modules, "keyring", stand_in(backend))
    assert pc.save_token(URL, "file-again") != "the system keychain"
    assert (pc.KEYRING_SERVICE, URL) not in backend.store
    assert pc.load_token(URL) == "file-again"


def test_platform_logout_with_a_locked_keychain_says_the_token_may_still_be_there(backend: Backend, capsys):
    pc.save_token(URL, "tok")
    backend.refuse = True
    assert cli_platform.logout(URL) == 1
    out = capsys.readouterr().out
    assert "Signed out" not in out
    assert "could not be removed from the system keychain" in out and "locked" in out


def test_zenodo_logout_with_a_locked_keychain_does_not_say_nothing_was_stored(backend: Backend, capsys):
    zen.save_token("tok")
    backend.refuse = True
    assert cli_zenodo.logout() == 1
    out = capsys.readouterr().out
    assert "No zenodo.org token was stored" not in out
    assert "could not be removed from the system keychain" in out


def test_logout_with_a_working_keychain_still_signs_out(backend: Backend, monkeypatch, capsys):
    pc.save_token(URL, "tok")
    monkeypatch.setattr(pc, "request", lambda *a, **k: (200, {}))
    assert cli_platform.logout(URL) == 0
    assert "✓ Signed out of https://e2er.org." in capsys.readouterr().out
    assert pc.load_token(URL) is None
    zen.save_token("tok")
    assert cli_zenodo.logout() == 0
    assert zen.stored_token() == (None, None)
