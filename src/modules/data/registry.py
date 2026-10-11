"""Data module — provider registry (M3a).

Mirrors the LLM and literature registries. Returns the available
``SeriesFetcher`` providers and a unified catalog (series + the Allium
warehouse) that the ``list_data_sources`` discovery tool serves so agents
can pick the right source for the research question.

The series providers are the connector kit's sources (sources/), in their
catalogue order: a source written before the kit brings its own fetcher, a kit
source gets a ``KitFetcher`` from its definition. ``settings`` gates
availability: keyless sources are always on; FRED needs ``FRED_API_KEY``;
Allium (a warehouse, outside the kit) needs ``ALLIUM_API_KEY``.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from .providers import AlliumWarehouse, SeriesFetcher, Warehouse


def series_fetchers(settings: Settings) -> list[SeriesFetcher]:
    """Available series providers, in catalog order."""
    from .sources import all_sources
    from .sources.runtime import KitFetcher

    fetchers: list[SeriesFetcher] = []
    for source in all_sources():
        if not source.available(settings):
            continue
        fetcher = source.fetcher(settings) if source.fetcher else KitFetcher(source, settings)
        fetchers.append(fetcher)
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
