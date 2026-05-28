"""Data module — provider capability interfaces and series adapters (M3a).

M3 of docs/MODULARIZATION_PLAN.md, series side. The data lane has two
capability sub-types (locked decision #2):

- ``SeriesFetcher`` — parameterized reads of public series data (FRED macro,
  yfinance markets). Exposed in the agent loop via the unified ``fetch_data``
  tool, discovered through ``list_data_sources``.
- ``Warehouse`` — Allium's SQL + 5-rule guardrails + approval flow. Stays
  its own ``query_allium`` tool (M3b folds it behind this interface); for
  now it's advertised in the catalog as a card.

Each fetcher wraps an existing provider and exposes:
  - ``card()`` — catalog metadata so an agent can pick the right source for
    the research question (and knows each method's params, which covers the
    unified tool's looser schema),
  - ``fetch(method, params)`` — dispatch to the wrapped provider, returning
    its canonical ``{source, items, error, ...}`` envelope.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SeriesFetcher(ABC):
    """A parameterized public-data series source (no SQL, no approval flow)."""

    name: str

    @abstractmethod
    def card(self) -> dict[str, Any]:
        """Catalog entry: name, what the source is for, and method params."""
        ...

    @abstractmethod
    async def fetch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch ``method`` to the wrapped provider. Returns the provider's
        canonical envelope; an unknown method returns an ``error`` envelope."""
        ...


def _unknown_method(provider: str, method: str, known: list[str]) -> dict[str, Any]:
    return {"source": provider, "error": f"unknown method '{method}' for {provider}; available: {', '.join(known)}"}


class FredFetcher(SeriesFetcher):
    """Federal Reserve Economic Data — US macro time series."""

    name = "fred"

    def __init__(self, api_key: str) -> None:
        from .fred_provider import FredProvider

        self._provider = FredProvider(api_key)

    def card(self) -> dict[str, Any]:
        return {
            "name": "fred",
            "kind": "series",
            "use": "US macroeconomic time series — GDP, CPI/inflation, interest rates, "
            "employment, money supply, etc. Good for macro controls and conditioning variables.",
            "requires": "FRED_API_KEY",
            "methods": {
                "observations": "series_id (e.g. 'CPIAUCSL'); optional observation_start, "
                "observation_end (YYYY-MM-DD), frequency, units",
                "search": "query (free text); optional limit",
                "info": "series_id — sanity-check a series before pulling observations",
                "releases": "optional limit — list FRED data releases",
            },
        }

    async def fetch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "observations":
            return await self._provider.get_series_observations(
                params["series_id"],
                observation_start=params.get("observation_start"),
                observation_end=params.get("observation_end"),
                frequency=params.get("frequency"),
                units=params.get("units"),
            )
        if method == "info":
            return await self._provider.get_series_info(params["series_id"])
        if method == "search":
            return await self._provider.search_series(params["query"], limit=int(params.get("limit", 20)))
        if method == "releases":
            return await self._provider.get_releases(limit=int(params.get("limit", 100)))
        return _unknown_method("fred", method, ["observations", "info", "search", "releases"])


class YFinanceFetcher(SeriesFetcher):
    """Yahoo Finance — market data (no API key required)."""

    name = "yfinance"

    def __init__(self) -> None:
        from .yfinance_provider import YFinanceProvider

        self._provider = YFinanceProvider()

    def card(self) -> dict[str, Any]:
        return {
            "name": "yfinance",
            "kind": "series",
            "use": "Equity / ETF / FX / crypto market data — OHLCV prices, company "
            "fundamentals, dividends. Good for asset returns and firm-level variables.",
            "requires": "(none)",
            "methods": {
                "history": "ticker (e.g. 'SPY'); optional start, end (YYYY-MM-DD), interval (1d/1wk/1mo/...)",
                "info": "ticker — snapshot of quote/company fields",
                "fundamentals": "ticker; statement in {income, balance_sheet, cash_flow}",
                "dividends": "ticker — full ex-dividend history",
                "search": "query — best-effort name → ticker lookup",
            },
        }

    async def fetch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "history":
            return await self._provider.history(
                params["ticker"],
                start=params.get("start"),
                end=params.get("end"),
                interval=params.get("interval", "1d"),
            )
        if method == "info":
            return await self._provider.ticker_info(params["ticker"])
        if method == "fundamentals":
            return await self._provider.fundamentals(params["ticker"], statement=params.get("statement", "income"))
        if method == "dividends":
            return await self._provider.dividends(params["ticker"])
        if method == "search":
            return await self._provider.search(params["query"], max_results=int(params.get("max_results", 10)))
        return _unknown_method("yfinance", method, ["history", "info", "fundamentals", "dividends", "search"])
