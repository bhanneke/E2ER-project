"""`e2er zenodo login`, `status`, `logout`: a mocked Zenodo and a fake keychain; the real keychain is never used."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from src import cli_review, cli_zenodo
from src.core import platform_client as pc
from src.core import zenodo as zen

from .platform_help import owner_only

TOKEN = "ZenTok" + "x" * 54  # not a real token
REAL_KEYRING = pc._keyring


class FakeKeyring:
    def __init__(self, refuse: bool = False) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.refuse = refuse

    def get_password(self, service: str, user: str) -> str | None:
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, token: str) -> None:
        if self.refuse:
            raise RuntimeError("no GUI session")
        self.store[(service, user)] = token

    def delete_password(self, service: str, user: str) -> None:
        del self.store[(service, user)]


class FakeZenodo:
    """Answers GET /api/deposit/depositions: 200 for TOKEN, 401 for anything else; refuses every other call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.status_for_good = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.host, request.url.path))
        assert request.method == "GET" and request.url.path == "/api/deposit/depositions", "only a harmless read"
        assert request.url.params.get("size") == "1"
        if request.headers.get("authorization") == f"Bearer {TOKEN}":
            return httpx.Response(self.status_for_good, json=[])
        return httpx.Response(401, json={"message": "The server could not verify that you are authorized"})


@pytest.fixture
def fake(monkeypatch) -> FakeZenodo:
    z = FakeZenodo()
    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(z))
    )
    return z


@pytest.fixture
def keychain(monkeypatch) -> FakeKeyring:
    kr = FakeKeyring()
    monkeypatch.setattr(pc, "_keyring", lambda: kr)
    return kr


@pytest.fixture
def creds(monkeypatch, tmp_path) -> Path:
    p = tmp_path / "credentials.json"
    monkeypatch.setenv("E2ER_CREDENTIALS", str(p))
    return p


@pytest.fixture
def browser(monkeypatch) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr(cli_zenodo.webbrowser, "open", lambda url: opened.append(url))
    return opened


def paste(monkeypatch, text: str) -> None:
    """The token arrives on a pipe (not a terminal), as `pbpaste | e2er zenodo login` would send it."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(text + "\n"))


def test_the_conftest_keeps_the_keychain_and_zenodo_away():
    assert pc._keyring() is None  # conftest's stand-in
    assert REAL_KEYRING() is None  # and the guard itself: no keychain in a test run
    assert zen.load_token() is None and zen.load_token(True) is None
    with pytest.raises(AssertionError, match="reached a real platform"):
        zen.client_factory("https://zenodo.org").get("/api/deposit/depositions")


def test_login_checks_and_stores_in_the_keychain(monkeypatch, capsys, fake, keychain, creds, browser):
    paste(monkeypatch, TOKEN)
    assert cli_zenodo.login() == 0
    out = capsys.readouterr().out
    assert TOKEN not in out
    assert "https://zenodo.org/account/settings/applications/tokens/new/" in out
    assert "deposit:write and deposit:actions" in out and "the system keychain" in out
    assert keychain.store == {("zenodo.org", "token"): TOKEN}
    assert fake.calls == [("GET", "zenodo.org", "/api/deposit/depositions")]
    assert not creds.exists()
    assert browser == []  # standard output is not a terminal here
    assert zen.load_token() == TOKEN  # what publish --zenodo reads


def test_login_reads_the_token_with_a_hidden_prompt_at_a_terminal(monkeypatch, capsys, fake, keychain, browser):
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Tty(""))
    monkeypatch.setattr(sys, "stdout", Tty())
    asked: list[str] = []
    monkeypatch.setattr(cli_zenodo.getpass, "getpass", lambda prompt: asked.append(prompt) or f"  {TOKEN}  ")
    assert cli_zenodo.login(sandbox=True) == 0
    out = sys.stdout.getvalue()
    monkeypatch.undo()
    assert asked and "not shown" in asked[0]
    assert TOKEN not in out
    assert browser == ["https://sandbox.zenodo.org/account/settings/applications/tokens/new/"]
    assert keychain.store == {("sandbox.zenodo.org", "token"): TOKEN}


def test_a_token_zenodo_refuses_is_not_stored(monkeypatch, capsys, fake, keychain, creds, browser):
    paste(monkeypatch, "wrong-token")
    assert cli_zenodo.login() == 1
    out = capsys.readouterr().out
    assert "401" in out and "Nothing was stored" in out and "wrong-token" not in out
    assert keychain.store == {} and not creds.exists()
    fake.status_for_good = 403
    paste(monkeypatch, TOKEN)
    assert cli_zenodo.login() == 1
    out = capsys.readouterr().out
    assert "403" in out and "deposit:write and deposit:actions" in out and TOKEN not in out
    assert keychain.store == {}


def test_nothing_pasted_stores_nothing_and_asks_zenodo_nothing(monkeypatch, capsys, fake, keychain, browser):
    paste(monkeypatch, "")
    assert cli_zenodo.login() == 1
    assert "no token was pasted" in capsys.readouterr().out
    assert fake.calls == [] and keychain.store == {}


def test_without_a_keychain_the_credentials_file_mode_600(monkeypatch, capsys, fake, creds, browser):
    monkeypatch.setattr(pc, "_keyring", lambda: None)
    creds.write_text(json.dumps({"https://e2er.org": "e2er_keep"}))
    paste(monkeypatch, TOKEN)
    assert cli_zenodo.login() == 0
    assert str(creds) in capsys.readouterr().out
    assert json.loads(creds.read_text()) == {"https://e2er.org": "e2er_keep", "zenodo.org": TOKEN}
    assert owner_only(creds)
    assert zen.load_token() == TOKEN and zen.load_token(sandbox=True) is None
    # A keychain that refuses (no GUI session) falls back the same way.
    monkeypatch.setattr(pc, "_keyring", lambda: FakeKeyring(refuse=True))
    assert zen.save_token(TOKEN, sandbox=True) == str(creds)
    assert json.loads(creds.read_text())["sandbox.zenodo.org"] == TOKEN


def test_status_says_whether_a_token_is_stored_and_works(monkeypatch, capsys, fake, keychain):
    assert cli_zenodo.status() == 1
    assert "No zenodo.org token is stored" in capsys.readouterr().out
    keychain.store[("zenodo.org", "token")] = TOKEN
    assert cli_zenodo.status() == 0
    out = capsys.readouterr().out
    assert "the system keychain" in out and "accepted the token" in out and TOKEN not in out
    keychain.store[("zenodo.org", "token")] = "expired"
    assert cli_zenodo.status() == 1
    assert "401" in capsys.readouterr().out
    # The environment comes first (CI) and status says so.
    monkeypatch.setenv("ZENODO_TOKEN", TOKEN)
    assert cli_zenodo.status() == 0
    out = capsys.readouterr().out
    assert "ZENODO_TOKEN" in out and "is not used" in out and TOKEN not in out


def test_logout_removes_it_from_keychain_and_file(monkeypatch, capsys, keychain, creds):
    keychain.store[("zenodo.org", "token")] = TOKEN
    keychain.store[("sandbox.zenodo.org", "token")] = "sandbox-one"
    creds.write_text(json.dumps({"zenodo.org": TOKEN, "https://e2er.org": "e2er_keep"}))
    assert cli_zenodo.logout() == 0
    out = capsys.readouterr().out
    assert "the system keychain" in out and str(creds) in out and TOKEN not in out
    assert keychain.store == {("sandbox.zenodo.org", "token"): "sandbox-one"}
    assert json.loads(creds.read_text()) == {"https://e2er.org": "e2er_keep"}
    assert owner_only(creds)
    assert cli_zenodo.logout() == 0
    assert "No zenodo.org token was stored" in capsys.readouterr().out


def test_the_cli_dispatches_zenodo(monkeypatch):
    from src import __main__ as main_mod

    seen: list[Any] = []
    monkeypatch.setattr(cli_zenodo, "status", lambda **k: seen.append(("status", k)) or 0)
    monkeypatch.setattr(cli_zenodo, "login", lambda **k: seen.append(("login", k)) or 0)
    for argv in (["e2er", "zenodo", "status", "--sandbox"], ["e2er", "zenodo", "login", "--no-browser"]):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as e:
            main_mod.main()
        assert e.value.code == 0
    assert seen == [("status", {"sandbox": True}), ("login", {"sandbox": False, "open_browser": False})]


def test_preregister_deposit_uses_the_stored_token(monkeypatch, tmp_path, keychain, capsys):
    from src.core.pipeline import preregistration as pr

    (tmp_path / pr.LOCK_FILE).write_text(json.dumps({"file": "preregistration.md", "sha256": "a" * 64}))
    assert cli_review.deposit(str(tmp_path), zenodo=True, sandbox=True) == 1
    assert "e2er zenodo login --sandbox" in capsys.readouterr().err
    calls: list[Any] = []
    monkeypatch.setattr(
        pr, "deposit_zenodo", lambda folder, token, *, base_url: calls.append((token, base_url)) or {"doi": "d"}
    )
    keychain.store[("zenodo.org", "token")] = TOKEN
    assert cli_review.deposit(str(tmp_path), zenodo=True) == 0
    assert calls == [(TOKEN, "https://zenodo.org")]
    assert TOKEN not in capsys.readouterr().out
