"""`e2er run` starts the server with the session token it sends; `e2er serve` binds PORT from .env.

Found in the 0.16.0 demo runs (2026-10-13): `e2er run` started uvicorn without a
token, the server made its own, and every POST came back 403 ("This browser tab
is not signed in"). `e2er serve` bound 8280 while `e2er run` talked to PORT.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.api import local_session as ls


@pytest.fixture
def home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("E2ER_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("E2ER_API_TOKEN", raising=False)
    monkeypatch.delenv("E2ER_API_URL", raising=False)
    from src.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_e2er_run_starts_the_server_with_the_token_it_sends(monkeypatch, home):
    from src import cli_run

    monkeypatch.setenv("PORT", "8394")
    started: dict = {}

    class Proc:
        pid = 4242

    def fake_popen(cmd, **kw):
        started["cmd"] = cmd
        started["env"] = kw.get("env") or {}
        return Proc()

    monkeypatch.setattr(cli_run.subprocess, "Popen", fake_popen)
    answers = iter([False, True])
    monkeypatch.setattr(cli_run, "_api_reachable", lambda timeout=1.5: next(answers, True))

    ok, msg = cli_run._ensure_api_up(deadline_seconds=3)
    assert ok, msg
    assert "8394" in started["cmd"]
    token = started["env"][ls.ENV_TOKEN]
    assert token
    assert ls.read_session_token(8394) == token
    assert cli_run.api_headers()[ls.HEADER] == token
    import json

    assert json.loads(ls.session_file(8394).read_text())["pid"] == 4242


def test_a_running_server_keeps_its_session_file(monkeypatch, home):
    from src import cli_run

    monkeypatch.setenv("PORT", "8396")
    ls.write_session_file(8396, "the-running-one")
    monkeypatch.setattr(cli_run, "_api_reachable", lambda timeout=1.5: True)
    monkeypatch.setattr(cli_run.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start a server"))
    assert cli_run._ensure_api_up(deadline_seconds=1) == (True, None)
    assert ls.read_session_token(8396) == "the-running-one"


@pytest.mark.parametrize("argv", [["e2er", "serve", "--no-browser"], ["e2er", "--no-browser"]])
def test_serve_binds_the_port_from_settings(monkeypatch, home, argv):
    from src import __main__ as cli

    monkeypatch.setenv("PORT", "8395")
    seen = {}

    def fake_serve(host, port, reload, no_browser):
        seen["port"] = port
        return 0

    monkeypatch.setattr(cli, "_serve", fake_serve)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        cli.main()
    assert seen["port"] == 8395


def test_an_explicit_port_wins_over_settings(monkeypatch, home):
    from src import __main__ as cli

    monkeypatch.setenv("PORT", "8395")
    seen = {}
    monkeypatch.setattr(cli, "_serve", lambda host, port, reload, no_browser: seen.setdefault("port", port) and 0)
    monkeypatch.setattr(sys, "argv", ["e2er", "serve", "--no-browser", "--port", "8397"])
    with pytest.raises(SystemExit):
        cli.main()
    assert seen["port"] == 8397
