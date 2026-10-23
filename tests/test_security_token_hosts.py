"""Tokens go only to their own host (security review 2026-10-23, repro_zenodo_links.py).

Zenodo's answer names the next URL (``links.latest_draft``, ``links.bucket``, a file's
``links.self``): an answer pointing to http://evil.example received the Bearer token.
"""

from __future__ import annotations

import httpx
import pytest

from src.core import platform_client as pc
from src.core import zenodo as zen


def _zenodo(handler, base="https://zenodo.org"):
    return zen.Zenodo(
        "SECRET-TOKEN-123", base=base, client=httpx.Client(base_url=base, transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize(
    "link",
    [
        "http://evil.example/steal",
        "https://evil.example/steal",
        "http://zenodo.org/x",
        "https://zenodo.org.evil.example/x",
    ],
)
def test_a_zenodo_link_to_another_host_gets_no_token(link):
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers.get("authorization")))
        if req.url.path.endswith("/actions/newversion"):
            return httpx.Response(201, json={"id": 1, "links": {"latest_draft": link}})
        return httpx.Response(
            200, json={"id": 2, "links": {"bucket": link}, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.2"}}}
        )

    z = _zenodo(handler)
    with pytest.raises(zen.ZenodoError, match="token"):
        z.new_version(1)
    with pytest.raises(zen.ZenodoError, match="token"):
        z.upload(zen.Deposit(id=2, bucket=link, doi=None), "a.csv", b"x")
    assert all(host == "zenodo.org" for host, _ in seen), seen


def test_zenodo_links_on_its_own_host_work():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(201, json={})

    z = _zenodo(handler, base="https://sandbox.zenodo.org")
    z.upload(zen.Deposit(id=1, bucket="https://sandbox.zenodo.org/api/files/b", doi=None), "a.csv", b"x")
    z.upload(zen.Deposit(id=1, bucket="/api/files/b", doi=None), "b.csv", b"x")
    assert seen == ["https://sandbox.zenodo.org/api/files/b/a.csv", "https://sandbox.zenodo.org/api/files/b/b.csv"]


@pytest.mark.parametrize("base", ["http://zenodo.org", "https://evil.example", "https://zenodo.org.evil.example"])
def test_the_zenodo_client_refuses_another_base(base):
    with pytest.raises(zen.ZenodoError, match="refusing"):
        zen.Zenodo("t", base=base, client=httpx.Client())


@pytest.mark.parametrize(
    "url", ["http://e2er.org", "http://192.168.1.5:4321", "ftp://e2er.org", "https://u:p@e2er.org"]
)
def test_the_platform_client_refuses_plain_http_off_this_computer(url):
    with pytest.raises(pc.PlatformError):
        pc.check_platform_url(url)
    with pytest.raises(pc.PlatformError):
        pc.request(url, "GET", "/api/v1/me", token="tok")


@pytest.mark.parametrize(
    "url", ["https://e2er.org", "http://127.0.0.1:4321", "http://localhost:4321", "http://[::1]:4321"]
)
def test_https_and_a_local_server_are_allowed(url):
    assert pc.check_platform_url(url) == url


def test_a_platform_token_never_goes_to_an_absolute_url_elsewhere(monkeypatch):
    seen = []

    def factory(url):
        return httpx.Client(
            base_url=url, transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={}))
        )

    monkeypatch.setattr(pc, "client_factory", factory)
    with pytest.raises(pc.PlatformError, match="refusing"):
        pc.request("https://e2er.org", "GET", "https://evil.example/api", token="tok")
    with pytest.raises(pc.PlatformError, match="refusing"):
        pc.request("https://e2er.org", "GET", "//evil.example/api", token="tok")
    assert seen == []
    assert pc.request("https://e2er.org", "GET", "/api/v1/me", token="tok")[0] == 200
    assert seen[0].url.host == "e2er.org"
