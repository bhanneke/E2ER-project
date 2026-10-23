"""The fetch client re-checks every redirect, refuses unresolvable names, caps while reading, pins
the checked address, and keeps API keys on their own host (security review 2026-10-23)."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from src.modules.fetch import http as h

PUBLIC = "93.184.215.14"


@pytest.fixture
def dns(monkeypatch):
    """Names resolve from this table only; anything else fails like a real DNS miss."""
    table = {"good.example": PUBLIC, "other.example": "151.101.1.1", "rebind.example": "127.0.0.1"}

    def fake(host, port, *a, **kw):
        if host not in table:
            raise socket.gaierror(8, "nodename nor servname provided")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]

    monkeypatch.setattr(h, "_getaddrinfo", fake)
    return table


def _mock(monkeypatch, handler, *, sync: bool = False):
    seen: list[httpx.Request] = []

    def record(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    monkeypatch.setattr(h, "_transport", httpx.MockTransport(record))
    return seen


def test_a_name_that_does_not_resolve_is_refused(dns):
    with pytest.raises(ValueError, match="could not resolve"):
        h.check_url("https://nowhere.example/x")


def test_a_url_with_credentials_is_refused(dns):
    with pytest.raises(ValueError, match="user name or password"):
        h.check_url("https://user:pw@good.example/x")


@pytest.mark.parametrize(
    "location", ["http://127.0.0.1:8280/api/papers", "https://rebind.example/x", "file:///etc/passwd"]
)
def test_a_redirect_to_a_private_or_odd_target_is_refused(dns, monkeypatch, location):
    def handler(req):
        return httpx.Response(302, headers={"location": location})

    seen = _mock(monkeypatch, handler)
    with pytest.raises(ValueError):
        asyncio.run(h.fetch_text("https://good.example/start"))
    assert [r.url.host for r in seen] == ["good.example"]  # the private target was never asked


def test_an_api_key_does_not_follow_a_redirect_to_another_host(dns, monkeypatch):
    def handler(req):
        if req.url.host == "good.example" and req.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})  # same origin: keeps the key
        if req.url.host == "good.example":
            return httpx.Response(302, headers={"location": "https://other.example/c"})
        return httpx.Response(200, text="ok")

    seen = _mock(monkeypatch, handler)
    out = h.fetch_text_sync("https://good.example/a", headers={"Zotero-API-Key": "SECRET", "User-Agent": "e2er"})
    assert out == "ok"
    assert [(r.url.host, r.headers.get("zotero-api-key")) for r in seen] == [
        ("good.example", "SECRET"),
        ("good.example", "SECRET"),
        ("other.example", None),
    ]
    assert seen[-1].headers["user-agent"] == "e2er"


def test_too_many_redirects_are_refused(dns, monkeypatch):
    _mock(monkeypatch, lambda req: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(ValueError, match="redirects"):
        asyncio.run(h.fetch_bytes("https://good.example/x"))


def test_the_byte_cap_stops_reading(dns, monkeypatch):
    pulled = []

    def body():
        for i in range(1000):
            pulled.append(i)
            yield b"x" * 1024

    async def abody():
        for i in range(1000):
            pulled.append(i)
            yield b"x" * 1024

    _mock(monkeypatch, lambda req: httpx.Response(200, content=abody()))
    with pytest.raises(ValueError, match="too large"):
        asyncio.run(h.fetch_bytes("https://good.example/big", max_bytes=10 * 1024))
    assert len(pulled) < 50  # stopped near the cap, not after the whole megabyte
    pulled.clear()
    _mock(monkeypatch, lambda req: httpx.Response(200, content=body()))
    text = h.fetch_text_sync("https://good.example/big")  # fetch_text truncates at 2 MB, as before
    assert len(text) == 1000 * 1024 and len(pulled) == 1000


def test_the_connection_goes_to_the_checked_address():
    calls = []

    class Inner:
        def connect_tcp(self, host, port, *a, **kw):
            calls.append((host, port))
            return "stream"

    backend = h._PinnedBackend(Inner(), {"good.example": PUBLIC})
    assert backend.connect_tcp("good.example", 443) == "stream"
    assert calls == [(PUBLIC, 443)]
    with pytest.raises(httpx.ConnectError):
        backend.connect_tcp("unchecked.example", 443)


def test_the_real_transport_is_pinned():
    pins = {"good.example": PUBLIC}
    t = h._pinned_transport(pins, asynchronous=False)
    assert isinstance(t._pool._network_backend, h._PinnedBackend)
    t = h._pinned_transport(pins, asynchronous=True)
    assert isinstance(t._pool._network_backend, h._AsyncPinnedBackend)


def test_a_data_source_key_header_stays_on_its_host(monkeypatch):
    """NOAA's ``token`` header (PoliteClient) is not sent on to a redirect's other host."""
    from src.modules.data.sources import http as kit
    from src.modules.data.sources.base import Polite

    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        if req.url.host == "www.ncei.noaa.gov":
            return httpx.Response(302, headers={"location": "https://attacker.example/steal"})
        return httpx.Response(200, json={"results": []})

    async def run():
        token = kit._TRANSPORT.set(httpx.MockTransport(handler))
        try:
            async with kit.PoliteClient("noaa-test", Polite(min_interval=0, headers=(("X-Api-Key", "K2"),))) as c:
                return await c.get_json("https://www.ncei.noaa.gov/cdo-web/api/v2/data", headers={"token": "K1"})
        finally:
            kit._TRANSPORT.reset(token)

    assert asyncio.run(run()) == {"results": []}
    assert seen[0].headers.get("token") == "K1" and seen[0].headers.get("x-api-key") == "K2"
    assert seen[1].url.host == "attacker.example"
    assert "token" not in seen[1].headers and "x-api-key" not in seen[1].headers
