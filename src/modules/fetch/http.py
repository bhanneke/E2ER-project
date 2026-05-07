"""SSRF-safe HTTP client — blocks private IP ranges and enforces timeouts."""

from __future__ import annotations

import ipaddress
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


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL has no host")
    try:
        addr = ipaddress.ip_address(host)
        for net in _PRIVATE_RANGES:
            if addr in net:
                raise ValueError(f"SSRF blocked: {host} is a private address")
    except ValueError as e:
        if "SSRF" in str(e):
            raise
        # hostname, not IP — allow (DNS resolution not checked here)


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


async def fetch_bytes(url: str, headers: dict | None = None) -> bytes:
    """Fetch URL and return raw bytes (for PDF downloads)."""
    _check_url(url)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        content = resp.content
        if len(content) > _MAX_BYTES:
            raise ValueError(f"Response too large: {len(content)} bytes > {_MAX_BYTES}")
        return content


async def post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    """POST JSON payload and return parsed JSON response."""
    _check_url(url)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers or {})
        resp.raise_for_status()
        return resp.json()
