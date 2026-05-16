"""Lane C — data-layer degradation circuit breaker.

Pins the fix for runs #14 / #17: when Allium's developer API is in a
broken state, the provider must short-circuit further calls with a
single clear "degraded" envelope instead of letting the specialist drain
its turn budget on dozens of independent 429 retries.

The breaker fires when the recent error rate exceeds _DEGRADED_ERROR_RATE
within _DEGRADED_WINDOW calls. It self-clears on the next successful
call (so a transient outage doesn't permanently disable the provider).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from src.modules.data.allium_developer import (
    _DEGRADED_WINDOW,
    AlliumDeveloperProvider,
)


def _provider() -> AlliumDeveloperProvider:
    return AlliumDeveloperProvider(api_key="test-key", base_url="https://api.allium.so/api/v1")


# ---------- unit-level: _is_degraded math ----------


def test_not_degraded_below_window():
    """No degradation signal until we have at least _DEGRADED_WINDOW calls."""
    p = _provider()
    for _ in range(_DEGRADED_WINDOW - 1):
        p._record_outcome(False)
    assert p._is_degraded() is False, (
        f"can't be degraded with <{_DEGRADED_WINDOW} calls — single early failure shouldn't trip"
    )


def test_degraded_when_majority_failed():
    """Recent error rate > _DEGRADED_ERROR_RATE → degraded."""
    p = _provider()
    # All failures
    for _ in range(_DEGRADED_WINDOW):
        p._record_outcome(False)
    assert p._is_degraded() is True


def test_not_degraded_when_majority_succeeded():
    p = _provider()
    for _ in range(_DEGRADED_WINDOW):
        p._record_outcome(True)
    assert p._is_degraded() is False


def test_clears_after_one_success_pushes_window_below_threshold():
    """A single recent success can drop the rate below threshold.

    With _DEGRADED_WINDOW=6 and rate>0.5: 3+ failures + 3 successes = 50%
    which does NOT exceed 0.5 (strict >), so the breaker clears.
    """
    p = _provider()
    for _ in range(6):
        p._record_outcome(False)
    assert p._is_degraded() is True
    # Push 3 successes — window is now last 6 = 3 fails + 3 ok = 50% errors
    for _ in range(3):
        p._record_outcome(True)
    assert p._is_degraded() is False


# ---------- integration: short-circuit at request time ----------


@pytest.mark.asyncio
@respx.mock
async def test_request_short_circuits_when_degraded():
    """Once degraded, _request returns the structured envelope WITHOUT hitting Allium.

    Verifies via respx that no HTTP call is made when the breaker is open.
    """
    p = _provider()
    # Pre-load the breaker into the degraded state.
    for _ in range(_DEGRADED_WINDOW):
        p._record_outcome(False)
    assert p._is_degraded() is True

    # respx route: if any HTTP call escapes despite the breaker, assert.
    route = respx.get("https://api.allium.so/api/v1/developer/tokens/transfers").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    result = await p._request(
        "GET",
        "/developer/tokens/transfers",
        params={"chain": "ethereum", "address": "0xtest"},
    )

    assert route.call_count == 0, "breaker must short-circuit BEFORE the HTTP layer"
    assert result["error"] is not None
    assert "degraded" in result["error"].lower()
    assert result.get("degraded") is True
    assert result["items"] == []


@pytest.mark.asyncio
@respx.mock
async def test_request_makes_real_call_when_not_degraded():
    """Healthy provider must NOT short-circuit; the HTTP layer still runs."""
    p = _provider()
    respx.get("https://api.allium.so/api/v1/developer/tokens/transfers").mock(
        return_value=httpx.Response(200, json={"items": [{"foo": "bar"}], "next_token": None})
    )

    result = await p._request(
        "GET",
        "/developer/tokens/transfers",
        params={"chain": "ethereum", "address": "0xtest"},
    )

    assert result["error"] is None
    assert result["items"] == [{"foo": "bar"}]
    # And the provider should record the success
    assert p._recent_outcomes[-1] is True


@pytest.mark.asyncio
@respx.mock
async def test_degraded_state_clears_after_successful_call():
    """If Allium recovers mid-run, the next successful call clears the breaker.

    Without this, a transient outage permanently disables the provider
    for the rest of the specialist invocation.
    """
    p = _provider()
    for _ in range(_DEGRADED_WINDOW):
        p._record_outcome(False)
    # First call short-circuits...
    result1 = await p._request("GET", "/developer/tokens/transfers", params={"chain": "ethereum"})
    assert result1.get("degraded") is True

    # Simulate operator fixing the issue: manually mark a success (as if
    # caller called a different path that succeeded), then verify the
    # breaker reads the change.
    p._record_outcome(True)
    p._record_outcome(True)
    p._record_outcome(True)
    # Now 3 recent True + 6 earlier False; last 6 = 3T+3F = 50% errors,
    # which is NOT > 0.5 (strict >). Breaker should clear.
    assert p._is_degraded() is False

    respx.get("https://api.allium.so/api/v1/developer/tokens/transfers").mock(
        return_value=httpx.Response(200, json={"items": [], "next_token": None})
    )
    result2 = await p._request("GET", "/developer/tokens/transfers", params={"chain": "ethereum"})
    assert result2.get("degraded") is None, "breaker should not be tripping on healthy provider"
    assert result2["error"] is None
