"""Allium Developer-tier REST endpoints (wallet/, prices/, tokens/).

The SQL Explorer API (see allium.py) requires a higher Allium subscription
tier. Plans that don't include Explorer still get the *Developer API* —
a set of REST endpoints serving wallet histories, token transfers, and
price feeds across ~17 EVM chains.

This module is the read-only client for those endpoints. It's the only
way E2ER specialists access Allium when the key doesn't have Explorer.

## Endpoint coverage (what this key tier provides)

  GET  /developer/tokens/transfers     ERC-20 Transfer events for a token
  POST /developer/wallet/transactions  Full tx history for an address (list body)
  POST /developer/wallet/balances/history  Daily balance snapshots for an address
  POST /developer/prices/history       OHLC price for a fungible token over time

NFT collections (ERC-721/1155) return empty from the price endpoints —
this tier doesn't carry floor-price feeds. Studies that need NFT prices
must add a second data source (Reservoir, OpenSea, etc.).

## Rate-limit discipline

Allium throttles aggressively. Every method:
  1. Retries 429s with exponential backoff (2.0s → 15.0s cap, 60s budget)
  2. Spaces requests via a module-level asyncio.Semaphore so concurrent
     specialists can't burst the per-second cap.
  3. Returns an error envelope ``{"error": str, "items": []}`` on
     non-retryable failures — never raises into specialist code.

## Response shape

All methods return ``{"items": [...], "error": str | None}`` for uniformity.
Pagination tokens (Allium uses ``next_token``) are surfaced as ``next_token``
in the dict so callers can fetch additional pages explicitly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

_TIMEOUT = 60.0
_MAX_429_WAIT = 60.0
_BACKOFF_START = 2.0
_BACKOFF_CAP = 15.0
_MIN_REQUEST_SPACING_SEC = 0.5

# Circuit-breaker thresholds for the data layer. When the recent error rate
# crosses _DEGRADED_ERROR_RATE within the last _DEGRADED_WINDOW calls, the
# provider returns a structured "data layer degraded" envelope on every
# subsequent call until at least one call succeeds. This stops a specialist
# from burning its turn budget retrying the same broken endpoint dozens of
# times (run #14 / #17 failure mode).
_DEGRADED_WINDOW = 6
_DEGRADED_ERROR_RATE = 0.5

# Module-level lock + last-call timestamp to pace requests across concurrent
# specialists. Without this, 6 parallel data_analyst invocations can burst
# 30+ requests in one second and exhaust the per-second quota immediately.
_pace_lock = asyncio.Lock()
_last_call_ts: float = 0.0


async def _pace_request() -> None:
    """Sleep just enough that requests are at least _MIN_REQUEST_SPACING_SEC apart.

    Module-level state; safe to call from any async context. Prevents
    bursty concurrent calls from blowing the per-second quota even before
    the 429 retry kicks in.
    """
    import time

    global _last_call_ts
    async with _pace_lock:
        now = time.monotonic()
        wait = (_last_call_ts + _MIN_REQUEST_SPACING_SEC) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


class AlliumDeveloperProvider:
    """Read-only client for Allium's Developer REST endpoints."""

    def __init__(self, api_key: str, base_url: str = "https://api.allium.so/api/v1") -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        # Sliding window of recent call outcomes (True=ok, False=error). Used
        # by the degradation breaker — short-circuit further calls once the
        # data layer is clearly down.
        self._recent_outcomes: list[bool] = []

    def _is_degraded(self) -> bool:
        """True if the recent error rate signals the data layer is down.

        Triggers when we have at least _DEGRADED_WINDOW calls and the
        majority were errors. The breaker resets the moment one call
        succeeds — operators don't have to manually clear it.
        """
        if len(self._recent_outcomes) < _DEGRADED_WINDOW:
            return False
        window = self._recent_outcomes[-_DEGRADED_WINDOW:]
        error_rate = window.count(False) / _DEGRADED_WINDOW
        return error_rate > _DEGRADED_ERROR_RATE

    def _record_outcome(self, success: bool) -> None:
        self._recent_outcomes.append(success)
        # Keep the deque bounded; we only ever look at the last window.
        if len(self._recent_outcomes) > _DEGRADED_WINDOW * 4:
            self._recent_outcomes = self._recent_outcomes[-_DEGRADED_WINDOW * 2 :]

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        """One HTTP call with pacing + 429 retry. Returns canonical envelope.

        Returns ``{"items": [...], "next_token": str | None, "error": str | None}``.

        If the data layer is in a degraded state (recent error rate above
        threshold), short-circuits with a clear envelope BEFORE making the
        network call. Specialists see a single explicit signal rather than
        watching their turn budget drain on dozens of 429 retries.
        """
        if self._is_degraded():
            logger.warning(
                "Allium developer layer degraded (recent error rate > %.0f%% in last %d calls); short-circuiting %s %s",
                _DEGRADED_ERROR_RATE * 100,
                _DEGRADED_WINDOW,
                method,
                path,
            )
            return {
                "items": [],
                "next_token": None,
                "error": (
                    "Allium data layer degraded — recent call success rate is below "
                    f"{(1 - _DEGRADED_ERROR_RATE) * 100:.0f}%. Stop calling this provider "
                    "for the rest of this invocation. Write a transparent failure section "
                    "to your canonical artifact and end your turn."
                ),
                "degraded": True,
            }
        url = f"{self._base}{path}"
        backoff = _BACKOFF_START
        elapsed = 0.0
        last_resp = None
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            while elapsed < _MAX_429_WAIT:
                await _pace_request()
                try:
                    resp = await client.request(
                        method,
                        url,
                        headers=self._headers,
                        params=params,
                        json=json_body,
                    )
                except httpx.HTTPError as e:
                    self._record_outcome(False)
                    return {"items": [], "next_token": None, "error": f"transport error: {e}"}
                last_resp = resp
                if resp.status_code != 429:
                    break
                logger.warning(
                    "Allium developer %s rate-limited; sleeping %.1fs",
                    path,
                    backoff,
                )
                await asyncio.sleep(backoff)
                elapsed += backoff
                backoff = min(backoff * 1.5, _BACKOFF_CAP)

        if last_resp is None:
            self._record_outcome(False)
            return {"items": [], "next_token": None, "error": "no response (timeout)"}
        if last_resp.status_code != 200:
            self._record_outcome(False)
            return {
                "items": [],
                "next_token": None,
                "error": f"HTTP {last_resp.status_code}: {last_resp.text[:300]}",
            }
        try:
            body = last_resp.json()
        except Exception as e:
            self._record_outcome(False)
            return {"items": [], "next_token": None, "error": f"non-JSON response: {e}"}

        items = body.get("items", []) if isinstance(body, dict) else []
        next_token = body.get("next_token") if isinstance(body, dict) else None
        self._record_outcome(True)
        return {"items": items, "next_token": next_token, "error": None}

    async def get_token_transfers(
        self,
        chain: str,
        address: str,
        token: str | None = None,
        min_timestamp: str | None = None,
        max_timestamp: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Token transfers involving a wallet, over an optional date window.

        Despite the path name "tokens/transfers", Allium scopes this to
        a single wallet ``address`` (required). The optional ``token``
        filter restricts the response to transfers of one ERC-20 contract.
        For hack-event studies, point ``address`` at the hacker EOA and
        bound ``min_timestamp``/``max_timestamp`` to the event window.

        Param names verified against
        https://docs.allium.so/_openapi/tokens-api.json (Nov 2026):
        ``min_timestamp`` / ``max_timestamp`` are the SUPPORTED date
        filters — earlier attempts with from/to or block_timestamp_gte
        were silently ignored by Allium.
        """
        params: dict[str, Any] = {
            "chain": chain,
            "address": address,
            "limit": limit,
        }
        if token:
            params["token"] = token
        if min_timestamp:
            params["min_timestamp"] = min_timestamp
        if max_timestamp:
            params["max_timestamp"] = max_timestamp
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/developer/tokens/transfers", params=params)

    async def get_wallet_transactions(
        self,
        chain: str,
        address: str,
        limit: int = 100,
        cursor: str | None = None,
        transaction_hash: str | None = None,
        activity_type: str | None = None,
    ) -> dict[str, Any]:
        """Transaction history for an address.

        **Important**: Allium's ``/developer/wallet/transactions`` does NOT
        support date filters — verified against the live OpenAPI spec
        (https://docs.allium.so/_openapi/wallet-api.json). It returns the
        most recent ``limit`` transactions and pages BACKWARD in time via
        ``cursor``.

        For hack studies where you need transactions from a specific date,
        either:
          1. Filter to a known ``transaction_hash`` if you have it from
             the public post-mortem (cheapest path), OR
          2. Page back from "now" with ``cursor`` until you reach the
             target date (expensive for old hacks — consider using
             ``get_token_transfers`` instead, which DOES support
             min_timestamp/max_timestamp).
        """
        entry: dict[str, Any] = {"chain": chain, "address": address}
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if transaction_hash:
            params["transaction_hash"] = transaction_hash
        if activity_type:
            params["activity_type"] = activity_type
        return await self._request(
            "POST",
            "/developer/wallet/transactions",
            params=params,
            json_body=[entry],
        )

    async def get_wallet_balances_history(
        self,
        chain: str,
        address: str,
        from_ts: str,
        to_ts: str,
    ) -> dict[str, Any]:
        """Daily balance snapshots for an address.

        For hack studies, run this on victim contract addresses or known
        whale wallets to measure the drawdown shape across exploit days.
        Both from and to are required by Allium.
        """
        entry = {
            "addresses": [{"chain": chain, "address": address}],
            "start_timestamp": from_ts,
            "end_timestamp": to_ts,
        }
        return await self._request("POST", "/developer/wallet/balances/history", json_body=entry)

    async def get_token_prices_history(
        self,
        chain: str,
        token_address: str,
        from_ts: str,
        to_ts: str,
    ) -> dict[str, Any]:
        """OHLC price history for a fungible token.

        Returns empty for NFT contracts (ERC-721/1155) — this tier does
        not provide NFT floor prices.
        """
        entry = {
            "addresses": [{"chain": chain, "token_address": token_address}],
            "start_timestamp": from_ts,
            "end_timestamp": to_ts,
            "time_granularity": "1d",
        }
        return await self._request("POST", "/developer/prices/history", json_body=entry)

    async def get_token_latest_price(self, chain: str, token_address: str) -> dict[str, Any]:
        """Latest spot price for a fungible token (no time range).

        Useful as a sanity check that a token contract is indexed at all
        before requesting a history window.
        """
        return await self._request(
            "POST",
            "/developer/prices",
            json_body=[{"chain": chain, "token_address": token_address}],
        )
