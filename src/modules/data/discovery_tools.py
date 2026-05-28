"""Data module — discovery + unified fetch tools (M3a).

Agents discover which data sources fit the research question via
``list_data_sources`` (served from the registry catalog), then pull series
data through a single ``fetch_data`` tool. Allium stays its own guarded
``query_allium`` tool — the catalog tells the agent to use that for
blockchain data.

This keeps the data-specialist context tiny (two tools) and lets new
providers appear in the catalog with zero added context.
"""

from __future__ import annotations

import json
from typing import Any

from ...logging_config import get_logger
from ..llm.base import ToolHandler

logger = get_logger(__name__)

DATA_DISCOVERY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_data_sources",
        "description": (
            "List the structured data sources available for this paper and what each is "
            "for. Call this FIRST, in light of the research question, to decide which "
            "source(s) to use. Returns each source's name, purpose, and (for series "
            "sources) the methods and parameters you can pass to fetch_data."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fetch_data",
        "description": (
            "Fetch public series data (macro, markets) from a source listed by "
            "list_data_sources. For blockchain/on-chain data use query_allium instead — "
            "fetch_data does not handle Allium."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Source name, e.g. 'fred' or 'yfinance'"},
                "method": {
                    "type": "string",
                    "description": "Method on that source (see its card from list_data_sources)",
                },
                "params": {
                    "type": "object",
                    "description": "Method parameters (see the card), e.g. {'series_id': 'CPIAUCSL'}",
                },
            },
            "required": ["provider", "method"],
        },
    },
]


class SeriesDataToolHandler(ToolHandler):
    """Handles list_data_sources + fetch_data. One instance per specialist run.

    Budgeted like the literature tools — public APIs are rate-limited and an
    unsteered model can over-fetch.
    """

    _MAX_FETCHES = 20

    def __init__(self) -> None:
        self._fetch_calls = 0

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in {"list_data_sources", "fetch_data"}

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "list_data_sources":
            return self._list_sources()
        if tool_name == "fetch_data":
            if self._fetch_calls >= self._MAX_FETCHES:
                return json.dumps(
                    {
                        "error": f"fetch_data budget exhausted ({self._MAX_FETCHES} calls). "
                        "Proceed with the data you have.",
                    }
                )
            self._fetch_calls += 1
            return await self._fetch(tool_input)
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    def _list_sources(self) -> str:
        from ...config import get_settings
        from .registry import data_catalog

        sources = data_catalog(get_settings())
        if not sources:
            return json.dumps({"sources": [], "note": "No structured data sources are configured for this paper."})
        return json.dumps({"sources": sources}, indent=2)

    async def _fetch(self, inp: dict[str, Any]) -> str:
        from ...config import get_settings
        from .registry import series_fetchers

        provider = (inp.get("provider") or "").strip().lower()
        method = (inp.get("method") or "").strip()
        params = inp.get("params") or {}
        if not provider or not method:
            return json.dumps({"error": "both 'provider' and 'method' are required; call list_data_sources first"})
        if provider == "allium":
            return json.dumps(
                {"error": "use the query_allium tool for blockchain data — fetch_data does not handle Allium"}
            )

        fetchers = {f.name: f for f in series_fetchers(get_settings())}
        fetcher = fetchers.get(provider)
        if fetcher is None:
            return json.dumps(
                {"error": f"unknown or unavailable data source '{provider}'; call list_data_sources for the list"}
            )
        try:
            envelope = await fetcher.fetch(method, params)
        except KeyError as e:
            return json.dumps({"error": f"missing required parameter {e} for {provider}.{method}"})
        except Exception as e:
            logger.warning("fetch_data %s.%s failed: %s", provider, method, e)
            return json.dumps({"error": str(e)})
        return json.dumps(envelope, default=str)
