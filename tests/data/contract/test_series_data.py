"""Lane C — series providers, registry, and discovery/fetch tools (M3a).

Mock-only. Pins the registry availability/catalog, the SeriesFetcher
dispatch + param mapping, and the list_data_sources / fetch_data handler
(including the Allium redirect and the fetch budget).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.modules.data.discovery_tools import SeriesDataToolHandler
from src.modules.data.providers import AlliumWarehouse, FredFetcher, SeriesFetcher, Warehouse, YFinanceFetcher
from src.modules.data.registry import data_catalog, series_fetchers, warehouses


def _settings(fred_api_key=None, allium_api_key=None):
    return SimpleNamespace(fred_api_key=fred_api_key, allium_api_key=allium_api_key)


# ---------------------------------------------------------------------------
# Registry availability + catalog
# ---------------------------------------------------------------------------


def test_yfinance_always_available():
    assert [f.name for f in series_fetchers(_settings())] == ["yfinance"]


def test_fred_available_with_key():
    names = [f.name for f in series_fetchers(_settings(fred_api_key="k"))]
    assert names == ["yfinance", "fred"]


def test_catalog_includes_allium_card_only_with_key():
    plain = {c["name"] for c in data_catalog(_settings())}
    assert plain == {"yfinance"}
    withallium = {c["name"] for c in data_catalog(_settings(allium_api_key="k"))}
    assert withallium == {"yfinance", "allium"}


def test_allium_card_points_to_query_allium_not_fetch_data():
    card = next(c for c in data_catalog(_settings(allium_api_key="k")) if c["name"] == "allium")
    assert card["kind"] == "warehouse"
    assert "query_allium" in card["tool"]


def test_cards_advertise_methods():
    fred_card = FredFetcher.__new__(FredFetcher).card()  # card() needs no provider
    assert "observations" in fred_card["methods"]
    yf_card = YFinanceFetcher.__new__(YFinanceFetcher).card()
    assert "history" in yf_card["methods"]


# ---------------------------------------------------------------------------
# SeriesFetcher dispatch + param mapping
# ---------------------------------------------------------------------------


async def test_fred_dispatch_maps_params():
    fetcher = FredFetcher("KEY")
    fetcher._provider.get_series_observations = AsyncMock(return_value={"source": "fred", "items": []})
    await fetcher.fetch("observations", {"series_id": "CPIAUCSL", "observation_start": "2020-01-01"})
    fetcher._provider.get_series_observations.assert_awaited_once()
    kwargs = fetcher._provider.get_series_observations.await_args.kwargs
    args = fetcher._provider.get_series_observations.await_args.args
    assert args[0] == "CPIAUCSL"
    assert kwargs["observation_start"] == "2020-01-01"


async def test_fred_unknown_method_errors():
    fetcher = FredFetcher("KEY")
    out = await fetcher.fetch("nonsense", {})
    assert "unknown method" in out["error"]


async def test_yfinance_dispatch_maps_params():
    fetcher = YFinanceFetcher()
    fetcher._provider.history = AsyncMock(return_value={"source": "yfinance", "items": []})
    await fetcher.fetch("history", {"ticker": "SPY", "interval": "1wk"})
    fetcher._provider.history.assert_awaited_once()
    assert fetcher._provider.history.await_args.args[0] == "SPY"
    assert fetcher._provider.history.await_args.kwargs["interval"] == "1wk"


def test_fetchers_are_series_fetchers():
    assert isinstance(YFinanceFetcher(), SeriesFetcher)


# ---------------------------------------------------------------------------
# Warehouse capability (Allium) — M3b
# ---------------------------------------------------------------------------


def test_no_warehouses_without_allium_key():
    assert warehouses(_settings()) == []


def test_allium_warehouse_present_with_key():
    whs = warehouses(_settings(allium_api_key="k"))
    assert [w.name for w in whs] == ["allium"]
    assert isinstance(whs[0], Warehouse)


def test_allium_warehouse_contributes_query_allium_tool():
    tools = AlliumWarehouse().tools()
    assert "query_allium" in [t["name"] for t in tools]


def test_allium_warehouse_handler_is_deferred_handler():
    from pathlib import Path

    from src.modules.data.tools import DeferredAlliumToolHandler

    h = AlliumWarehouse().handler("paper-1", Path("/tmp"))
    assert isinstance(h, DeferredAlliumToolHandler)


def test_catalog_allium_card_comes_from_warehouse():
    card = next(c for c in data_catalog(_settings(allium_api_key="k")) if c["name"] == "allium")
    assert card == AlliumWarehouse().card()


# ---------------------------------------------------------------------------
# Discovery + fetch_data handler
# ---------------------------------------------------------------------------

_REG = "src.modules.data.registry.series_fetchers"
_SETTINGS = "src.config.get_settings"


def _fake_fetcher(name="fred", envelope=None):
    f = SimpleNamespace(name=name)
    f.fetch = AsyncMock(return_value=envelope or {"source": name, "items": [1, 2]})
    return f


async def test_list_data_sources_returns_catalog():
    handler = SeriesDataToolHandler()
    with patch(_SETTINGS, return_value=_settings(fred_api_key="k", allium_api_key="k")):
        out = json.loads(await handler.handle("list_data_sources", {}))
    names = {s["name"] for s in out["sources"]}
    assert names == {"yfinance", "fred", "allium"}


async def test_fetch_data_dispatches_to_provider():
    handler = SeriesDataToolHandler()
    fake = _fake_fetcher("fred", {"source": "fred", "items": [42]})
    with patch(_SETTINGS, return_value=_settings(fred_api_key="k")), patch(_REG, return_value=[fake]):
        out = json.loads(
            await handler.handle("fetch_data", {"provider": "fred", "method": "search", "params": {"query": "cpi"}})
        )
    assert out["items"] == [42]
    fake.fetch.assert_awaited_once_with("search", {"query": "cpi"})


async def test_fetch_data_allium_redirects_to_query_allium():
    handler = SeriesDataToolHandler()
    with patch(_SETTINGS, return_value=_settings(allium_api_key="k")), patch(_REG, return_value=[]):
        out = json.loads(await handler.handle("fetch_data", {"provider": "allium", "method": "x"}))
    assert "query_allium" in out["error"]


async def test_fetch_data_unknown_provider_errors():
    handler = SeriesDataToolHandler()
    with patch(_SETTINGS, return_value=_settings()), patch(_REG, return_value=[_fake_fetcher("yfinance")]):
        out = json.loads(await handler.handle("fetch_data", {"provider": "bloomberg", "method": "x"}))
    assert "unknown or unavailable" in out["error"]


async def test_fetch_data_requires_provider_and_method():
    handler = SeriesDataToolHandler()
    with patch(_SETTINGS, return_value=_settings()):
        out = json.loads(await handler.handle("fetch_data", {"provider": "fred"}))
    assert "required" in out["error"]


async def test_fetch_data_budget_enforced():
    handler = SeriesDataToolHandler()
    fake = _fake_fetcher("yfinance")
    cap = SeriesDataToolHandler._MAX_FETCHES
    with patch(_SETTINGS, return_value=_settings()), patch(_REG, return_value=[fake]):
        for _ in range(cap):
            r = await handler.handle(
                "fetch_data", {"provider": "yfinance", "method": "history", "params": {"ticker": "SPY"}}
            )
            assert "budget exhausted" not in r
        over = await handler.handle(
            "fetch_data", {"provider": "yfinance", "method": "history", "params": {"ticker": "SPY"}}
        )
    assert "budget exhausted" in json.loads(over)["error"]


def test_can_handle():
    h = SeriesDataToolHandler()
    assert h.can_handle("list_data_sources") and h.can_handle("fetch_data")
    assert not h.can_handle("query_allium")
