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


def test_allows_public_host_behind_nat64():
    """On a NAT64/DNS64 network a public host resolves to 64:ff9b::<ipv4>.

    Python reports the whole prefix as reserved, so the guard refused a real
    public address: `arxiv.org resolves to non-public address
    64:ff9b::9765:c32a`, whose embedded IPv4 is 151.101.195.42. Caught by
    running `e2er doctor` from an installed wheel on such a network.
    """
    # 64:ff9b::9765:c32a == 151.101.195.42
    _check_url("https://[64:ff9b::9765:c32a]/paper.pdf")


def test_still_blocks_a_private_address_behind_nat64():
    """Unwrapping must tighten the guard, not open it.

    64:ff9b::192.168.0.1 names a private host; it has to stay blocked, now on
    the merits of the embedded address rather than by accident of the prefix
    being reserved.
    """
    with pytest.raises(ValueError, match="SSRF"):
        _check_url("https://[64:ff9b::c0a8:1]/admin")


def test_still_blocks_an_ipv4_mapped_loopback():
    with pytest.raises(ValueError, match="SSRF"):
        _check_url("http://[::ffff:127.0.0.1]/admin")
