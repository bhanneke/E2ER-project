"""FRED provider — Federal Reserve Economic Data via the public REST API.

Free key required (~30s to register at https://fredaccount.stlouisfed.org/apikey).
The API is generous: 120 req/min, no data quota, all economic data series free.

Coverage:
  - get_series_observations(): the bread-and-butter — a time series of values
  - get_series_info(): metadata for a series (title, units, frequency, …)
  - search_series(): find series by free-text query
  - get_releases(): browse FRED releases (CPI, employment situation, …)

FRED uses URL query parameters, returns JSON. We use httpx for async HTTP
and the same envelope shape as the other E2ER providers.

Output shape: ``{"source": "fred", "items": [...], "error": str | None, ...}``

Rate-limit handling: FRED's 120 req/min limit is generous, but we still
pace at 0.5s/call as a courtesy + retry once on transient 429s.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred"
_TIMEOUT = 30.0
_MIN_REQUEST_SPACING_SEC = 0.5

_pace_lock = asyncio.Lock()
_last_call_ts: float = 0.0


async def _pace_request() -> None:
    """Module-level pacing across concurrent FRED calls."""
    global _last_call_ts
    async with _pace_lock:
        now = time.monotonic()
        wait = (_last_call_ts + _MIN_REQUEST_SPACING_SEC) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


def _envelope(items: list[Any] | None = None, error: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "fred", "items": items or [], "error": error}
    out.update(extra)
    return out


class FredProvider:
    """Async REST client for the FRED API.

    All methods return the canonical ``{source, items, error, ...}``
    envelope. Network errors are caught and surfaced as ``error`` strings;
    they never raise into specialist code.
    """

    def __init__(self, api_key: str, base_url: str = _BASE_URL) -> None:
        if not api_key:
            raise ValueError("FRED_API_KEY required — get one at https://fredaccount.stlouisfed.org/apikey")
        self._api_key = api_key
        self._base = base_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Single GET with pacing, 429 retry, JSON parse.

        Returns the raw JSON dict on success, or ``{"_error": str}`` on
        failure. Callers wrap into the canonical envelope.
        """
        await _pace_request()
        params = {**params, "api_key": self._api_key, "file_type": "json"}
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as e:
            return {"_error": f"transport error: {e}"}

        # FRED returns 429 on rate-limit; retry once after 1s.
        if resp.status_code == 429:
            await asyncio.sleep(1.0)
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.get(url, params=params)
            except httpx.HTTPError as e:
                return {"_error": f"transport error after 429 retry: {e}"}

        if resp.status_code != 200:
            return {"_error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        try:
            return resp.json()
        except Exception as e:
            return {"_error": f"non-JSON response: {e}"}

    async def get_series_observations(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
        frequency: str | None = None,
        units: str | None = None,
        limit: int = 100000,
    ) -> dict[str, Any]:
        """Time series of values for a FRED series.

        ``series_id`` is e.g. ``CPIAUCSL`` (CPI All Urban Consumers),
        ``UNRATE`` (unemployment rate), ``DGS10`` (10-year Treasury yield).

        Optional aggregation:
        - ``frequency``: "d", "w", "m", "q", "sa", "a" to resample
        - ``units``: "lin" (raw), "chg" (change), "ch1" (year-over-year change),
          "pch" (percent change), "log" (natural log), etc.
        """
        params: dict[str, Any] = {"series_id": series_id, "limit": min(limit, 100000)}
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        if frequency:
            params["frequency"] = frequency
        if units:
            params["units"] = units

        raw = await self._get("/series/observations", params)
        if "_error" in raw:
            return _envelope(error=raw["_error"], series_id=series_id)

        observations = raw.get("observations", [])
        # Coerce "." (FRED's missing-value sentinel) to None, and value
        # strings to float where possible.
        items = []
        for obs in observations:
            v = obs.get("value")
            if v == "." or v is None:
                value = None
            else:
                try:
                    value = float(v)
                except (TypeError, ValueError):
                    value = None
            items.append(
                {
                    "date": obs.get("date"),
                    "value": value,
                    "realtime_start": obs.get("realtime_start"),
                    "realtime_end": obs.get("realtime_end"),
                }
            )
        return _envelope(
            items=items,
            series_id=series_id,
            row_count=len(items),
            frequency=frequency,
            units=units,
        )

    async def get_series_info(self, series_id: str) -> dict[str, Any]:
        """Metadata for a series: title, units, frequency, seasonal adjustment, etc.

        Use to sanity-check a series_id BEFORE pulling observations, and
        to grab citation-ready metadata for the paper.
        """
        raw = await self._get("/series", {"series_id": series_id})
        if "_error" in raw:
            return _envelope(error=raw["_error"], series_id=series_id)
        series_list = raw.get("seriess", [])  # FRED really does spell it "seriess"
        if not series_list:
            return _envelope(
                items=[],
                series_id=series_id,
                message=f"No FRED series found with id {series_id!r}.",
            )
        s = series_list[0]
        # Keep a curated subset.
        keep = (
            "id",
            "title",
            "frequency",
            "frequency_short",
            "units",
            "units_short",
            "seasonal_adjustment",
            "seasonal_adjustment_short",
            "observation_start",
            "observation_end",
            "last_updated",
            "notes",
        )
        curated = {k: s.get(k) for k in keep if k in s}
        return _envelope(items=[curated], series_id=series_id)

    async def search_series(
        self,
        query: str,
        limit: int = 20,
        order_by: str = "popularity",
    ) -> dict[str, Any]:
        """Free-text search across FRED series titles + notes.

        Returns one row per hit with the series id + key metadata. Use
        when you have a concept ("unemployment", "CPI core") but don't
        know the series id.
        """
        params: dict[str, Any] = {
            "search_text": query,
            "limit": min(limit, 1000),
            "order_by": order_by,
        }
        raw = await self._get("/series/search", params)
        if "_error" in raw:
            return _envelope(error=raw["_error"], query=query)

        items = []
        for s in raw.get("seriess", []):
            items.append(
                {
                    "id": s.get("id"),
                    "title": s.get("title"),
                    "frequency": s.get("frequency_short"),
                    "units": s.get("units_short"),
                    "observation_start": s.get("observation_start"),
                    "observation_end": s.get("observation_end"),
                    "popularity": s.get("popularity"),
                }
            )
        return _envelope(items=items, query=query, row_count=len(items))

    async def get_releases(self, limit: int = 100) -> dict[str, Any]:
        """List FRED releases (e.g. "Consumer Price Index", "Employment Situation").

        Useful when you want to find all series in a specific release.
        """
        raw = await self._get("/releases", {"limit": min(limit, 1000)})
        if "_error" in raw:
            return _envelope(error=raw["_error"])
        items = []
        for r in raw.get("releases", []):
            items.append(
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "press_release": r.get("press_release"),
                    "link": r.get("link"),
                }
            )
        return _envelope(items=items, row_count=len(items))
