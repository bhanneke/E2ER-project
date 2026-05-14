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

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        """One HTTP call with pacing + 429 retry. Returns canonical envelope.

        Returns ``{"items": [...], "next_token": str | None, "error": str | None}``.
        """
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
            return {"items": [], "next_token": None, "error": "no response (timeout)"}
        if last_resp.status_code != 200:
            return {
                "items": [],
                "next_token": None,
                "error": f"HTTP {last_resp.status_code}: {last_resp.text[:300]}",
            }
        try:
            body = last_resp.json()
        except Exception as e:
            return {"items": [], "next_token": None, "error": f"non-JSON response: {e}"}

        items = body.get("items", []) if isinstance(body, dict) else []
        next_token = body.get("next_token") if isinstance(body, dict) else None
        return {"items": items, "next_token": next_token, "error": None}

    async def get_token_transfers(
        self,
        chain: str,
        token_address: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
        next_token: str | None = None,
    ) -> dict[str, Any]:
        """ERC-20 Transfer events for a token over a date window.

        Use this for event-study designs around hacks: pull transfers of
        the affected token ±30d around the exploit timestamp. The window
        is enforced via from/to (block_timestamp); Allium handles the
        time-bound filtering server-side.
        """
        params: dict[str, Any] = {
            "chain": chain,
            "token": token_address,
            "limit": limit,
        }
        if from_ts:
            params["block_timestamp_gte"] = from_ts
        if to_ts:
            params["block_timestamp_lte"] = to_ts
        if next_token:
            params["next_token"] = next_token
        return await self._request("GET", "/developer/tokens/transfers", params=params)

    async def get_wallet_transactions(
        self,
        chain: str,
        address: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Full transaction history for an address.

        For hack studies, point this at the documented hacker EOA and the
        exploit-day window to capture initial drain transactions, then
        widen to study outflow speed and laundering patterns.
        """
        entry: dict[str, Any] = {"chain": chain, "address": address, "limit": limit}
        if from_ts:
            entry["start_timestamp"] = from_ts
        if to_ts:
            entry["end_timestamp"] = to_ts
        return await self._request("POST", "/developer/wallet/transactions", json_body=[entry])

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
