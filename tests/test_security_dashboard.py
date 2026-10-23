"""The dashboard answers only to this computer and only with the session (security review 2026-10-23).

The reviewer's DNS-rebinding repro: a page at attacker.example, resolved to 127.0.0.1, read
``/api/papers/…`` with its own Host header and no session. And ``//evil.example/x?t=…`` redirected
to another site.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import local_session as ls
from src.api.app import app
from src.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
PID = "5b0c7f4e-2a61-4d8e-9f3b-6c1d2e4a8b70"  # fixed: parametrized ids must match across xdist workers


def _client(**kw) -> TestClient:
    kw.setdefault("base_url", "http://127.0.0.1:8280")
    return TestClient(app, client=("127.0.0.1", 50000), **kw)


@pytest.mark.parametrize("host", ["attacker.example:8280", "attacker.example", "192.168.1.20:8280", ""])
@pytest.mark.parametrize("path", ["/", "/health", "/api/papers", f"/api/papers/{PID}/artifacts/.env", "/setup"])
def test_a_host_that_is_not_this_computer_is_refused_everywhere(host, path):
    r = _client().get(path, headers={"host": host}, follow_redirects=False)
    assert r.status_code == 400, (host, path, r.status_code)


@pytest.mark.parametrize("host", ["127.0.0.1:8280", "localhost:8280", "[::1]:8280"])
def test_this_computers_hosts_pass(host):
    assert _client().get("/health", headers={"host": host}).status_code == 200


def test_a_configured_host_passes(monkeypatch):
    monkeypatch.setenv(ls.ENV_ALLOWED_HOSTS, "e2er.lab.internal, 10.0.0.5")
    assert _client().get("/health", headers={"host": "e2er.lab.internal:8280"}).status_code == 200
    assert _client().get("/health", headers={"host": "10.0.0.5"}).status_code == 200
    monkeypatch.setenv(ls.ENV_SERVE_HOST, "0.0.0.0")  # a wildcard bind names no host
    assert "0.0.0.0" not in ls.allowed_hosts()


@pytest.mark.parametrize(
    "path",
    [
        "/api/papers",
        f"/api/papers/{PID}",
        f"/api/papers/{PID}/artifacts",
        f"/api/papers/{PID}/events",
        f"/api/papers/{PID}/usage",
        f"/api/papers/{PID}/failure-bundle",
        f"/api/papers/{PID}/audit-bundle",
        f"/api/papers/{PID}/data-queries",
        f"/api/papers/{PID}/pending-queries",
        "/api/usage",
    ],
)
def test_every_api_route_needs_the_session(path):
    anonymous = _client(headers={"x-e2er-token": ""})
    r = anonymous.get(path)
    assert r.status_code == 403 and "not signed in" in r.json()["detail"], (path, r.status_code)
    wrong = _client(headers={"x-e2er-token": "guessed"})
    assert wrong.get(path).status_code == 403


def test_the_api_takes_the_bearer_token_when_one_is_set(monkeypatch):
    monkeypatch.setenv("API_AUTH_TOKEN", "operator-token")
    get_settings.cache_clear()
    try:
        assert _client(headers={"x-e2er-token": ""}).get("/api/papers").status_code == 401
        bad = _client(headers={"x-e2er-token": "", "Authorization": "Bearer nope"})
        assert bad.get("/api/papers").status_code == 401
        ok = _client(headers={"x-e2er-token": "", "Authorization": "Bearer operator-token"})
        assert ok.get("/api/papers").status_code == 200
    finally:
        get_settings.cache_clear()


def test_the_launch_link_never_redirects_to_another_site():
    """The reviewer's repro: ``//evil.example/x?t=…`` answered with ``Location: //evil.example/x``."""
    r = _client().get("//evil.example/x?t=whatever", follow_redirects=False)
    loc = r.headers.get("location", "")
    assert r.status_code == 303 and loc.startswith("/") and not loc.startswith("//"), loc
    r = _client().get("/\\evil.example/x?t=whatever", follow_redirects=False)
    assert not r.headers.get("location", "").startswith(("//", "/\\"))


def test_the_cookie_lasts_only_the_browser_session(monkeypatch):
    monkeypatch.setenv(ls.ENV_TOKEN, "launch-token-for-this-test")
    r = _client().get("/?t=launch-token-for-this-test", follow_redirects=False)
    cookies = r.headers.get_list("set-cookie")
    assert cookies and all("max-age" not in c.lower() and "expires" not in c.lower() for c in cookies)


def test_links_from_answers_are_http_only():
    from src.api.app import _http_url

    assert _http_url("https://e2er.org/s/x") == "https://e2er.org/s/x"
    for bad in ["javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "vbscript:x", "", None]:
        assert _http_url(bad) == ""
    html = (ROOT / "src/api/templates/finish.html").read_text(encoding="utf-8")
    assert "a.href = p.study_url" not in html and "esc(d.study_url)" not in html
    assert html.count("httpUrl(") >= 6 and html.count("| http_url") >= 3


def test_serving_beyond_this_computer_needs_a_bearer_token(monkeypatch, capsys):
    from src import __main__ as m

    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        assert m._serve(host="0.0.0.0", port=18299, reload=False, no_browser=True) == 2
        assert "API_AUTH_TOKEN" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()
    assert m._loopback_host("127.0.0.1") and m._loopback_host("::1") and m._loopback_host("localhost")
    assert not m._loopback_host("0.0.0.0") and not m._loopback_host("192.168.1.2")


def test_the_default_host_is_this_computer(monkeypatch):
    from src.config import Settings

    monkeypatch.delenv("HOST", raising=False)
    assert Settings(_env_file=None).host == "127.0.0.1"


def test_the_docker_image_needs_a_bearer_token():
    entry = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert 'if [ -z "${API_AUTH_TOKEN:-}" ]' in entry and "exit 1" in entry
    compose = (ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8280:8280"' in compose
