"""Lane C — FRED provider contract tests.

Hermetic: the FRED REST API is mocked via respx. Pins:
  - Every method returns the {source, items, error, ...} envelope
  - FRED's "." missing-value sentinel coerces to None
  - Value strings coerce to float
  - Bad series_id → empty items + diagnostic message, error=None
  - HTTP non-200 → structured error, never raise
  - 429 → one retry after 1s backoff
  - series-info returns the curated subset, not the full FRED metadata blob
"""

from __future__ import annotations

import httpx
import pytest
import respx

from src.modules.data.fred_provider import FredProvider


def _provider() -> FredProvider:
    return FredProvider(api_key="test-key", base_url="https://api.stlouisfed.org/fred")


# ---------- get_series_observations ----------


@pytest.mark.asyncio
@respx.mock
async def test_series_observations_parses_real_response_shape():
    """A documented FRED observations response should yield clean floats."""
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(
            200,
            json={
                "realtime_start": "2024-06-01",
                "realtime_end": "2024-06-01",
                "observation_start": "2024-01-01",
                "observation_end": "2024-04-01",
                "units": "lin",
                "count": 4,
                "observations": [
                    {
                        "realtime_start": "2024-06-01",
                        "realtime_end": "2024-06-01",
                        "date": "2024-01-01",
                        "value": "308.417",
                    },
                    {
                        "realtime_start": "2024-06-01",
                        "realtime_end": "2024-06-01",
                        "date": "2024-02-01",
                        "value": "310.326",
                    },
                    {
                        "realtime_start": "2024-06-01",
                        "realtime_end": "2024-06-01",
                        "date": "2024-03-01",
                        "value": "312.332",
                    },
                    # FRED's missing-value sentinel
                    {"realtime_start": "2024-06-01", "realtime_end": "2024-06-01", "date": "2024-04-01", "value": "."},
                ],
            },
        )
    )

    p = _provider()
    result = await p.get_series_observations("CPIAUCSL", observation_start="2024-01-01")

    assert result["source"] == "fred"
    assert result["error"] is None
    assert result["series_id"] == "CPIAUCSL"
    assert result["row_count"] == 4

    # Real values coerced to floats
    assert result["items"][0]["value"] == pytest.approx(308.417)
    assert result["items"][2]["value"] == pytest.approx(312.332)
    # Missing-value sentinel "." → None
    assert result["items"][3]["value"] is None
    # Date passed through as-is
    assert result["items"][0]["date"] == "2024-01-01"


@pytest.mark.asyncio
@respx.mock
async def test_series_observations_propagates_optional_params():
    """frequency, units, observation_end all need to land in the query string."""
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json={"observations": []})
    )

    p = _provider()
    await p.get_series_observations(
        "UNRATE",
        observation_start="2020-01-01",
        observation_end="2024-12-31",
        frequency="q",
        units="pc1",
        limit=500,
    )

    assert route.called
    call = route.calls[0].request
    # Convert query string to dict for stable assertions
    qs = dict(call.url.params)
    assert qs["series_id"] == "UNRATE"
    assert qs["observation_start"] == "2020-01-01"
    assert qs["observation_end"] == "2024-12-31"
    assert qs["frequency"] == "q"
    assert qs["units"] == "pc1"
    assert qs["limit"] == "500"
    assert qs["api_key"] == "test-key"
    assert qs["file_type"] == "json"


@pytest.mark.asyncio
@respx.mock
async def test_series_observations_http_500_returns_error_envelope():
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(500, text="internal error")
    )
    p = _provider()
    result = await p.get_series_observations("CPIAUCSL")
    assert result["error"] is not None
    assert "500" in result["error"]
    assert result["items"] == []
    # series_id is still echoed back so the model can correlate the error
    assert result["series_id"] == "CPIAUCSL"


@pytest.mark.asyncio
@respx.mock
async def test_series_observations_429_retries_once():
    """First call 429 → retry → 200. Pins the rate-limit recovery path."""
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        side_effect=[
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json={"observations": [{"date": "2024-01-01", "value": "1.0"}]}),
        ]
    )

    p = _provider()
    result = await p.get_series_observations("UNRATE")
    assert route.call_count == 2
    assert result["error"] is None
    assert len(result["items"]) == 1


# ---------- get_series_info ----------


@pytest.mark.asyncio
@respx.mock
async def test_series_info_returns_curated_subset():
    respx.get("https://api.stlouisfed.org/fred/series").mock(
        return_value=httpx.Response(
            200,
            json={
                "seriess": [
                    {
                        "id": "CPIAUCSL",
                        "title": "Consumer Price Index for All Urban Consumers",
                        "frequency": "Monthly",
                        "frequency_short": "M",
                        "units": "Index 1982-1984=100",
                        "units_short": "Index 1982-1984=100",
                        "seasonal_adjustment": "Seasonally Adjusted",
                        "seasonal_adjustment_short": "SA",
                        "observation_start": "1947-01-01",
                        "observation_end": "2024-04-01",
                        "last_updated": "2024-05-15",
                        "notes": "The CPI measures…",
                        # Noise we don't want in the prompt:
                        "popularity": 95,
                        "group_popularity": 95,
                        "realtime_start": "2024-06-01",
                        "realtime_end": "2024-06-01",
                    }
                ]
            },
        )
    )

    p = _provider()
    result = await p.get_series_info("CPIAUCSL")

    assert result["error"] is None
    assert len(result["items"]) == 1
    info = result["items"][0]
    # Curated fields kept
    assert info["id"] == "CPIAUCSL"
    assert info["frequency_short"] == "M"
    assert info["seasonal_adjustment_short"] == "SA"
    assert "notes" in info
    # Noise filtered out
    assert "popularity" not in info
    assert "realtime_start" not in info


@pytest.mark.asyncio
@respx.mock
async def test_series_info_empty_returns_diagnostic_message():
    respx.get("https://api.stlouisfed.org/fred/series").mock(return_value=httpx.Response(200, json={"seriess": []}))
    p = _provider()
    result = await p.get_series_info("NOPE_NOT_A_SERIES")
    assert result["error"] is None
    assert result["items"] == []
    assert "NOPE_NOT_A_SERIES" in result["message"]


# ---------- search_series ----------


@pytest.mark.asyncio
@respx.mock
async def test_search_series_returns_curated_hits():
    respx.get("https://api.stlouisfed.org/fred/series/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "seriess": [
                    {
                        "id": "UNRATE",
                        "title": "Unemployment Rate",
                        "frequency_short": "M",
                        "units_short": "%",
                        "observation_start": "1948-01-01",
                        "observation_end": "2024-04-01",
                        "popularity": 99,
                        # Noise:
                        "group_popularity": 99,
                        "realtime_start": "2024-05-01",
                    },
                    {
                        "id": "UNRATENSA",
                        "title": "Unemployment Rate (NSA)",
                        "frequency_short": "M",
                        "units_short": "%",
                        "observation_start": "1948-01-01",
                        "observation_end": "2024-04-01",
                        "popularity": 75,
                    },
                ]
            },
        )
    )

    p = _provider()
    result = await p.search_series("unemployment")
    assert result["error"] is None
    assert result["row_count"] == 2
    assert result["items"][0]["id"] == "UNRATE"
    assert result["items"][0]["frequency"] == "M"
    # Noise dropped
    assert "group_popularity" not in result["items"][0]
    assert "realtime_start" not in result["items"][0]


@pytest.mark.asyncio
@respx.mock
async def test_search_series_passes_order_by_param():
    route = respx.get("https://api.stlouisfed.org/fred/series/search").mock(
        return_value=httpx.Response(200, json={"seriess": []})
    )
    p = _provider()
    await p.search_series("cpi", order_by="observation_end", limit=5)
    qs = dict(route.calls[0].request.url.params)
    assert qs["order_by"] == "observation_end"
    assert qs["limit"] == "5"


# ---------- releases ----------


@pytest.mark.asyncio
@respx.mock
async def test_releases_returns_curated_list():
    respx.get("https://api.stlouisfed.org/fred/releases").mock(
        return_value=httpx.Response(
            200,
            json={
                "releases": [
                    {
                        "id": 10,
                        "name": "Consumer Price Index",
                        "press_release": True,
                        "link": "https://www.bls.gov/cpi/",
                        # Noise:
                        "realtime_start": "2024-06-01",
                        "realtime_end": "2024-06-01",
                    }
                ]
            },
        )
    )

    p = _provider()
    result = await p.get_releases()
    assert result["error"] is None
    assert result["items"][0]["id"] == 10
    assert result["items"][0]["name"] == "Consumer Price Index"
    assert "realtime_start" not in result["items"][0]


# ---------- envelope contract ----------


def test_constructor_rejects_empty_api_key():
    """Missing api_key should fail loudly at construction, not silently 401 later."""
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        FredProvider(api_key="")
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        FredProvider(api_key=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
@respx.mock
async def test_every_method_returns_envelope_keys():
    """Pin the response shape across all four methods."""
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json={"observations": []})
    )
    respx.get("https://api.stlouisfed.org/fred/series").mock(return_value=httpx.Response(200, json={"seriess": []}))
    respx.get("https://api.stlouisfed.org/fred/series/search").mock(
        return_value=httpx.Response(200, json={"seriess": []})
    )
    respx.get("https://api.stlouisfed.org/fred/releases").mock(return_value=httpx.Response(200, json={"releases": []}))

    p = _provider()
    for r in [
        await p.get_series_observations("X"),
        await p.get_series_info("X"),
        await p.search_series("anything"),
        await p.get_releases(),
    ]:
        assert r.get("source") == "fred"
        assert "items" in r
        assert "error" in r
