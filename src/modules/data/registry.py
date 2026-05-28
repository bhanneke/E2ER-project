"""Data module — provider registry (M3a).

Mirrors the LLM and literature registries. Returns the available
``SeriesFetcher`` providers and a unified catalog (series + the Allium
warehouse) that the ``list_data_sources`` discovery tool serves so agents
can pick the right source for the research question.

``settings`` gates availability: yfinance needs no key (always on); FRED
needs ``FRED_API_KEY``; Allium needs ``ALLIUM_API_KEY``.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from .providers import AlliumWarehouse, FredFetcher, SeriesFetcher, Warehouse, YFinanceFetcher


def series_fetchers(settings: Settings) -> list[SeriesFetcher]:
    """Available series providers, in catalog order."""
    fetchers: list[SeriesFetcher] = [YFinanceFetcher()]
    if settings.fred_api_key:
        fetchers.append(FredFetcher(settings.fred_api_key))
    return fetchers


def warehouses(settings: Settings) -> list[Warehouse]:
    """Available SQL warehouses (contribute their own guarded tools+handler)."""
    whs: list[Warehouse] = []
    if settings.allium_api_key:
        whs.append(AlliumWarehouse())
    return whs


def data_catalog(settings: Settings) -> list[dict[str, Any]]:
    """All available data sources, as agent-facing cards.

    Series providers describe their ``fetch_data`` methods; warehouses point
    at their own guarded tools (e.g. Allium → ``query_allium``).
    """
    catalog: list[dict[str, Any]] = [f.card() for f in series_fetchers(settings)]
    catalog.extend(w.card() for w in warehouses(settings))
    return catalog
