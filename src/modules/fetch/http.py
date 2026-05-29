"""SSRF-safe HTTP client — blocks private IP ranges and enforces timeouts."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

_TIMEOUT = 30.0
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_ALLOWED_SCHEMES = {"http", "https"}


def _is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local  # incl. 169.254.0.0/16 (cloud metadata)
        or addr.is_reserved
        or any(addr in net for net in _PRIVATE_RANGES)
    )


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL has no host")

    # Block private/loopback/link-local targets. For a literal IP, check it
    # directly; for a hostname, resolve and check EVERY resolved address —
    # otherwise a name like `metadata.google.internal` → 169.254.x slips past
    # an IP-only check. (DNS rebinding between this check and the actual
    # connection remains a theoretical gap; pinning the resolved IP would
    # close it fully.)
    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return  # DNS failure — let the real request surface the error
        candidates = []
        for info in infos:
            try:
                candidates.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue

    for addr in candidates:
        if _is_blocked(addr):
            raise ValueError(f"SSRF blocked: {host} resolves to non-public address {addr}")


async def fetch_text(url: str, headers: dict | None = None) -> str:
    """Fetch URL and return text content. Raises on SSRF or HTTP errors."""
    _check_url(url)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        content = resp.content
        if len(content) > _MAX_BYTES:
            content = content[:_MAX_BYTES]
        return content.decode("utf-8", errors="replace")


def fetch_text_sync(url: str, headers: dict | None = None) -> str:
    """Synchronous variant of ``fetch_text``.

    For sync callers — notably the ``ReferenceLibrary`` providers, which are
    consumed by the (sync) specialist prompt builder and so can't await.
    Same SSRF check, timeout, and size cap.
    """
    _check_url(url)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers=headers or {})
        resp.raise_for_status()
        content = resp.content
        if len(content) > _MAX_BYTES:
            content = content[:_MAX_BYTES]
        return content.decode("utf-8", errors="replace")


async def fetch_bytes(url: str, headers: dict | None = None, max_bytes: int | None = None) -> bytes:
    """Fetch URL and return raw bytes (for PDF downloads).

    ``max_bytes`` overrides the default 2 MB cap — PDFs routinely exceed it,
    so the reference-reading path passes a larger limit.
    """
    _check_url(url)
    cap = max_bytes if max_bytes is not None else _MAX_BYTES
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        content = resp.content
        if len(content) > cap:
            raise ValueError(f"Response too large: {len(content)} bytes > {cap}")
        return content


async def post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    """POST JSON payload and return parsed JSON response."""
    _check_url(url)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers or {})
        resp.raise_for_status()
        return resp.json()
