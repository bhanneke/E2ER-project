"""SSRF-safe HTTP client: public addresses only, checked on every redirect, a byte cap while reading.

Every request (and every redirect it follows, up to :data:`MAX_REDIRECTS`) goes through the same
steps (security review 2026-10-23):

1. The scheme is http or https and the URL names a host.
2. The host is resolved; a name that does not resolve is refused (before, a DNS failure let the
   request through to the client's own lookup, which a rebinding name answers differently).
   Every address it resolves to must be public.
3. The connection goes to the address checked in step 2 (*pinned*): the client's network backend
   connects to that IP for the checked name (TLS still checks the certificate for the name), so a
   second DNS answer cannot point it elsewhere.
4. A redirect is followed by hand: its target is checked from step 1 again, and when it leads to
   another origin (scheme, host or port) only plain headers go with it (:data:`_CROSS_ORIGIN_SAFE`);
   an API key in a custom header (``Zotero-API-Key``, NOAA's ``token``) never reaches the next host.
5. The body is read in chunks and stops at the byte cap, instead of being read whole first.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

_TIMEOUT = 30.0
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
#: Redirects one request follows at most.
MAX_REDIRECTS = 5

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT, also used by some cloud metadata services
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_ALLOWED_SCHEMES = {"http", "https"}
#: Headers that go with a redirect to another origin; every other one (API keys, cookies) stays behind.
_CROSS_ORIGIN_SAFE = frozenset({"user-agent", "accept", "accept-language", "accept-encoding"})


#: Well-known prefix for NAT64 translation (RFC 6052). On a NAT64/DNS64
#: network every public IPv4 host resolves to 64:ff9b::<ipv4>.
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")

Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def _unwrap(addr: Address) -> Address:
    """Resolve an address to the destination it actually names.

    Python reports the whole NAT64 prefix as reserved, so on such a network a
    legitimate public host is refused — the user sees working DNS, a working
    browser, and a tool that will not fetch. Unwrapping also applies the real
    rules to the embedded address, so 64:ff9b::192.168.0.1 is blocked as the
    private address it is rather than as a reserved prefix.
    """
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None:
            return mapped
        if addr in _NAT64_PREFIX:
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr


def _is_blocked(addr: Address) -> bool:
    addr = _unwrap(addr)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local  # incl. 169.254.0.0/16 (cloud metadata)
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or any(addr in net for net in _PRIVATE_RANGES)
    )


@dataclass(frozen=True)
class Target:
    """A checked URL: where it goes and the public address the connection is pinned to."""

    url: str
    scheme: str
    host: str
    port: int
    address: Address

    @property
    def origin(self) -> tuple[str, str, int]:
        return (self.scheme, self.host, self.port)


#: The resolver (replaced in tests): host, port -> getaddrinfo's list.
_getaddrinfo: Callable[..., Any] = socket.getaddrinfo


def check_url(url: str) -> Target:
    """Check ``url`` (scheme, host, every resolved address); the target to connect to, else ValueError."""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no host")
    if parsed.username or parsed.password:
        raise ValueError("URL carries a user name or password; refused")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise ValueError(f"URL has an invalid port: {e}") from None

    try:
        candidates: list[Address] = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = _getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError, OSError) as e:
            # Refused: letting the client resolve the name itself would connect to whatever a second
            # lookup answers, unchecked.
            raise ValueError(f"could not resolve {host}: {e}") from None
        candidates = []
        for info in infos:
            try:
                candidates.append(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]))
            except ValueError:
                continue
        if not candidates:
            raise ValueError(f"could not resolve {host}: no address")

    for addr in candidates:
        if _is_blocked(addr):
            raise ValueError(f"SSRF blocked: {host} resolves to non-public address {addr}")
    return Target(url=url, scheme=scheme, host=host, port=port, address=candidates[0])


def _check_url(url: str) -> None:
    """Kept for callers and tests that only want the check."""
    check_url(url)


def redirect_headers(headers: dict[str, str], same_origin: bool) -> dict[str, str]:
    """The headers that go with a redirect: all of them on the same origin, plain ones elsewhere."""
    if same_origin:
        return dict(headers)
    return {k: v for k, v in headers.items() if k.lower() in _CROSS_ORIGIN_SAFE}


def origin_of(url: str) -> tuple[str, str, int]:
    p = urlsplit(url)
    scheme = (p.scheme or "").lower()
    try:
        port = p.port or (443 if scheme == "https" else 80)
    except ValueError:
        port = -1
    return (scheme, (p.hostname or "").lower(), port)


class _PinnedBackend:
    """A network backend that connects a checked host name only to the address it was checked at."""

    def __init__(self, inner: Any, pins: dict[str, str]) -> None:
        self.inner, self.pins = inner, pins

    def _address(self, host: str) -> str:
        key = host.strip("[]").lower()
        if key not in self.pins:
            raise httpx.ConnectError(f"{host} was not checked; refused")
        return self.pins[key]

    def connect_tcp(self, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        return self.inner.connect_tcp(self._address(host), port, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class _AsyncPinnedBackend(_PinnedBackend):
    async def connect_tcp(self, host: str, port: int, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        return await self.inner.connect_tcp(self._address(host), port, *args, **kwargs)


def _pinned_transport(pins: dict[str, str], *, asynchronous: bool) -> Any:
    """httpx's own transport, its connections pinned to ``pins`` (host -> checked address)."""
    transport: Any = httpx.AsyncHTTPTransport() if asynchronous else httpx.HTTPTransport()
    pool: Any = getattr(transport, "_pool", None)
    inner = getattr(pool, "_network_backend", None)
    if inner is None:  # another httpx/httpcore layout: refuse rather than connect unpinned
        raise RuntimeError("this httpx version cannot pin connections; e2er refuses to fetch unpinned")
    pool._network_backend = (_AsyncPinnedBackend if asynchronous else _PinnedBackend)(inner, pins)
    return transport


#: Transport for the clients made here (None: the network). Tests put an httpx.MockTransport here.
_transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None


def _pin(pins: dict[str, str], target: Target) -> None:
    pins[target.host.strip("[]")] = str(target.address)


def _next_hop(resp: httpx.Response, current: Target, headers: dict[str, str]) -> tuple[Target, dict[str, str]]:
    location = resp.headers.get("location")
    if not location:
        raise ValueError(f"HTTP {resp.status_code} without a Location header")
    nxt = check_url(urljoin(current.url, location))
    return nxt, redirect_headers(headers, nxt.origin == current.origin)


async def _fetch_async(
    url: str, headers: dict | None, cap: int, *, truncate: bool, method: str = "GET", json: Any = None
) -> tuple[httpx.Response, bytes]:
    target = check_url(url)
    hdrs = dict(headers or {})
    pins: dict[str, str] = {}
    transport = _transport if isinstance(_transport, httpx.AsyncBaseTransport) else None
    transport = transport or _pinned_transport(pins, asynchronous=True)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, transport=transport) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _pin(pins, target)
            request = client.build_request(method, target.url, headers=hdrs, json=json)
            async with _AStream(client, request) as resp:
                if resp.is_redirect and method == "GET":
                    target, hdrs = _next_hop(resp, target, hdrs)
                    continue
                if resp.is_error and _small(resp, cap):
                    await resp.aread()  # the caller's error handling reads the refusal's body
                resp.raise_for_status()
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > cap:
                        if truncate:
                            return resp, bytes(body[:cap])
                        raise ValueError(f"Response too large: more than {cap} bytes")
                return resp, bytes(body)
    raise ValueError(f"more than {MAX_REDIRECTS} redirects")


def _small(resp: httpx.Response, cap: int) -> bool:
    """An error answer small enough to read whole (it says so in Content-Length, within the cap)."""
    try:
        return int(resp.headers.get("content-length", "")) <= min(cap, 1 << 20)
    except ValueError:
        return False


class _AStream:
    """``async with`` around ``client.send(request, stream=True)``."""

    def __init__(self, client: httpx.AsyncClient, request: httpx.Request) -> None:
        self.client, self.request = client, request
        self.resp: httpx.Response | None = None

    async def __aenter__(self) -> httpx.Response:
        self.resp = await self.client.send(self.request, stream=True)
        return self.resp

    async def __aexit__(self, *exc: object) -> None:
        if self.resp is not None:
            await self.resp.aclose()


def _fetch_sync(url: str, headers: dict | None, cap: int, *, truncate: bool) -> tuple[httpx.Response, bytes]:
    target = check_url(url)
    hdrs = dict(headers or {})
    pins: dict[str, str] = {}
    transport = _transport if isinstance(_transport, httpx.BaseTransport) else None
    transport = transport or _pinned_transport(pins, asynchronous=False)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False, transport=transport) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _pin(pins, target)
            resp = client.send(client.build_request("GET", target.url, headers=hdrs), stream=True)
            try:
                if resp.is_redirect:
                    target, hdrs = _next_hop(resp, target, hdrs)
                    continue
                if resp.is_error and _small(resp, cap):
                    resp.read()
                resp.raise_for_status()
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > cap:
                        if truncate:
                            return resp, bytes(body[:cap])
                        raise ValueError(f"Response too large: more than {cap} bytes")
                return resp, bytes(body)
            finally:
                resp.close()
    raise ValueError(f"more than {MAX_REDIRECTS} redirects")


async def fetch_text(url: str, headers: dict | None = None) -> str:
    """Fetch URL and return text content (at most 2 MB). Raises on SSRF or HTTP errors."""
    _, content = await _fetch_async(url, headers, _MAX_BYTES, truncate=True)
    return content.decode("utf-8", errors="replace")


def fetch_text_sync(url: str, headers: dict | None = None) -> str:
    """Synchronous variant of ``fetch_text``.

    For sync callers — notably the ``ReferenceLibrary`` providers, which are
    consumed by the (sync) specialist prompt builder and so can't await.
    Same checks, timeout, and size cap.
    """
    _, content = _fetch_sync(url, headers, _MAX_BYTES, truncate=True)
    return content.decode("utf-8", errors="replace")


async def fetch_bytes(url: str, headers: dict | None = None, max_bytes: int | None = None) -> bytes:
    """Fetch URL and return raw bytes (for PDF downloads).

    ``max_bytes`` overrides the default 2 MB cap — PDFs routinely exceed it,
    so the reference-reading path passes a larger limit. A larger response is refused
    once the cap is passed, without reading the rest.
    """
    cap = max_bytes if max_bytes is not None else _MAX_BYTES
    _, content = await _fetch_async(url, headers, cap, truncate=False)
    return content


async def post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    """POST JSON payload and return parsed JSON response (no redirects followed)."""
    import json as _json

    resp, content = await _fetch_async(url, headers, _MAX_BYTES, truncate=False, method="POST", json=payload)
    if resp.is_redirect:
        raise ValueError(f"HTTP {resp.status_code}: a POST is not redirected")
    return _json.loads(content.decode("utf-8"))
