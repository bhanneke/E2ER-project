"""`keyring` is a dependency, but a computer may have no keychain behind it (headless Linux, CI).

Every test puts a stand-in module at ``sys.modules["keyring"]`` and lets the real ``_keyring`` run with the
test-run guard lifted for that lookup only, so the real keychain of this computer is never reached. The
tokens then go to the credentials file the test names (``E2ER_CREDENTIALS``) with mode 0600.
"""

from __future__ import annotations

import json
import stat
import sys
import types
from pathlib import Path

import pytest

from src.core import platform_client as pc
from src.core import test_guard
from src.core import zenodo as zen

from .platform_help import owner_only

REAL_KEYRING = pc._keyring
URL = "https://e2er.org"


class Backend:
    def __init__(self, priority: float = 1, refuse: bool = False) -> None:
        self.priority = priority
        self.refuse = refuse
        self.store: dict[tuple[str, str], str] = {}

    def _check(self) -> None:
        if self.refuse:
            raise RuntimeError("no keychain in this session")

    def get_password(self, service: str, user: str) -> str | None:
        self._check()
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, token: str) -> None:
        self._check()
        self.store[(service, user)] = token

    def delete_password(self, service: str, user: str) -> None:
        self._check()
        self.store.pop((service, user), None)


def stand_in(backend: object | None = None, broken: bool = False) -> types.ModuleType:
    """A `keyring` module whose calls go to ``backend``; ``broken``: get_keyring() raises."""
    m = types.ModuleType("keyring")

    def get_keyring():
        if broken:
            raise RuntimeError("Unable to load backend")
        return backend

    m.get_keyring = get_keyring  # type: ignore[attr-defined]
    for name in ("get_password", "set_password", "delete_password"):
        setattr(m, name, getattr(backend, name) if backend is not None else None)
    return m


@pytest.fixture
def creds(monkeypatch, tmp_path) -> Path:
    p = tmp_path / "credentials.json"
    monkeypatch.setenv("E2ER_CREDENTIALS", str(p))
    monkeypatch.delenv("E2ER_TOKEN", raising=False)
    monkeypatch.setattr(pc, "_keyring", REAL_KEYRING)
    monkeypatch.setattr(test_guard, "saved_logins_allowed", lambda: True)
    return p


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_the_dependency_is_declared():
    import tomllib

    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(d.startswith("keyring>=") for d in project["project"]["dependencies"])


def test_keyrings_fail_backend_counts_as_no_keychain(monkeypatch, creds):
    """What a headless Linux server or a CI runner selects: keyring.backends.fail, priority 0."""
    from keyring.backends import fail

    monkeypatch.setitem(sys.modules, "keyring", stand_in(fail.Keyring()))
    assert REAL_KEYRING() is None
    assert pc.save_token(URL, "e2er_tok") == str(creds)
    assert owner_only(creds)
    assert pc.load_token(URL) == "e2er_tok"
    assert zen.save_token("zen_tok") == str(creds)
    assert zen.stored_token() == ("zen_tok", str(creds))
    assert json.loads(creds.read_text()) == {URL: "e2er_tok", "zenodo.org": "zen_tok"}
    pc.forget_token(URL)
    assert zen.forget_token() == [str(creds)]
    assert json.loads(creds.read_text()) == {}


def test_a_backend_that_cannot_be_loaded_counts_as_no_keychain(monkeypatch, creds):
    monkeypatch.setitem(sys.modules, "keyring", stand_in(broken=True))
    assert REAL_KEYRING() is None
    assert pc.save_token(URL, "e2er_tok") == str(creds) and owner_only(creds)


def test_keyring_not_importable_counts_as_no_keychain(monkeypatch, creds):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import keyring raises ImportError
    assert REAL_KEYRING() is None
    assert zen.save_token("zen_tok", sandbox=True) == str(creds) and owner_only(creds)
    assert zen.load_token(sandbox=True) == "zen_tok"


def test_a_backend_that_refuses_falls_back_to_the_file(monkeypatch, creds):
    """A backend that looks usable (priority > 0) but raises on every call, e.g. a Secret Service that is locked."""
    backend = Backend(priority=5, refuse=True)
    monkeypatch.setitem(sys.modules, "keyring", stand_in(backend))
    assert REAL_KEYRING() is not None
    assert pc.save_token(URL, "e2er_tok") == str(creds) and owner_only(creds)
    assert pc.load_token(URL) == "e2er_tok"
    assert zen.save_token("zen_tok") == str(creds)
    assert zen.stored_token() == ("zen_tok", str(creds))
    assert zen.forget_token() == [str(creds)]


def test_a_working_backend_is_used_and_the_file_is_not_written(monkeypatch, creds):
    backend = Backend(priority=1)
    monkeypatch.setitem(sys.modules, "keyring", stand_in(backend))
    assert pc.save_token(URL, "e2er_tok") == "the system keychain"
    assert zen.save_token("zen_tok") == "the system keychain"
    assert backend.store == {(pc.KEYRING_SERVICE, URL): "e2er_tok", ("zenodo.org", "token"): "zen_tok"}
    assert not creds.exists()
    assert pc.load_token(URL) == "e2er_tok"
    assert zen.stored_token() == ("zen_tok", "the system keychain")


def test_in_a_test_run_even_a_working_keyring_is_not_used(monkeypatch, creds):
    backend = Backend(priority=1)
    monkeypatch.setitem(sys.modules, "keyring", stand_in(backend))
    monkeypatch.setattr(test_guard, "saved_logins_allowed", lambda: not test_guard.under_test())
    assert test_guard.under_test()
    assert REAL_KEYRING() is None
    pc.save_token(URL, "e2er_tok")
    assert backend.store == {}
