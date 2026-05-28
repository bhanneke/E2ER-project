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
from .providers import FredFetcher, SeriesFetcher, YFinanceFetcher


def series_fetchers(settings: Settings) -> list[SeriesFetcher]:
    """Available series providers, in catalog order."""
    fetchers: list[SeriesFetcher] = [YFinanceFetcher()]
    if settings.fred_api_key:
        fetchers.append(FredFetcher(settings.fred_api_key))
    return fetchers


def _allium_card() -> dict[str, Any]:
    return {
        "name": "allium",
        "kind": "warehouse",
        "use": "On-chain / blockchain data via SQL — transactions, transfers, DEX/NFT "
        "events, balances. Use for crypto / web3 research questions.",
        "requires": "ALLIUM_API_KEY",
        "tool": "Use the `query_allium` tool (NOT fetch_data) — it enforces field "
        "whitelisting, mandatory time bounds, and human approval for production runs.",
    }


def data_catalog(settings: Settings) -> list[dict[str, Any]]:
    """All available data sources, as agent-facing cards.

    Series providers describe their ``fetch_data`` methods; the Allium
    warehouse points at its own guarded ``query_allium`` tool.
    """
    catalog: list[dict[str, Any]] = [f.card() for f in series_fetchers(settings)]
    if settings.allium_api_key:
        catalog.append(_allium_card())
    return catalog
