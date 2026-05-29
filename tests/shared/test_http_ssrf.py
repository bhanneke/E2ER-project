"""SSRF guard: block private/loopback/link-local targets, incl. via hostname.

Before the fix only literal private IPs were blocked; a hostname like
`localhost` (or `metadata.google.internal` → 169.254.x) slipped past. Now
hostnames are resolved and every resolved address is checked.
"""

from __future__ import annotations

import pytest

from src.modules.fetch.http import _check_url


def test_blocks_literal_loopback():
    with pytest.raises(ValueError, match="SSRF"):
        _check_url("http://127.0.0.1/x")


def test_blocks_literal_private():
    with pytest.raises(ValueError, match="SSRF"):
        _check_url("http://10.0.0.5/admin")


def test_blocks_hostname_resolving_to_loopback():
    # `localhost` always resolves to 127.0.0.1 / ::1 — the regression case
    # (an IP-only check let this through).
    with pytest.raises(ValueError, match="SSRF"):
        _check_url("http://localhost:8280/api")


def test_allows_public_literal_ip():
    # Public literal IP, no DNS needed — must not raise.
    _check_url("https://8.8.8.8/")


def test_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        _check_url("file:///etc/passwd")
