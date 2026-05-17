"""Lane C — yfinance provider contract tests.

Hermetic: yfinance's HTTP layer is mocked so these run in <100 ms and
don't hit Yahoo. The provider's contract is:
  - Every method returns ``{source, items, error, ...}``
  - Network/parse errors → structured envelope, NEVER raise
  - Empty results → ``items: []`` + a ``message`` explaining why
  - Pandas timestamps → ISO strings (JSON-serialisable)
  - Curated subset on ``ticker_info`` so 100+ noisy fields don't leak

Live calls happen in the (separate, opt-in) e2e suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.modules.data.yfinance_provider import YFinanceProvider

# ---------- history ----------


def _fake_ohlcv(rows: int = 3) -> pd.DataFrame:
    """Build a yfinance-shaped DataFrame: DatetimeIndex × OHLCV columns.

    The real yfinance ``Ticker.history()`` returns a DataFrame whose
    index is named ``"Date"`` (or ``"Datetime"`` for intraday). The
    provider's ``reset_index()`` lowercases that → ``"date"``. Our test
    fake must preserve the same index name so the contract is honestly
    exercised.
    """
    idx = pd.date_range("2024-01-02", periods=rows, freq="B", name="Date")
    return pd.DataFrame(
        {
            "Open": [185.0, 182.0, 184.0][:rows],
            "High": [186.3, 183.8, 184.5][:rows],
            "Low": [181.8, 181.4, 183.0][:rows],
            "Close": [183.6, 182.2, 184.0][:rows],
            "Volume": [82_488_700, 58_414_500, 71_000_000][:rows],
            "Dividends": [0.0, 0.0, 0.0][:rows],
            "Stock Splits": [0.0, 0.0, 0.0][:rows],
        },
        index=idx,
    )


@pytest.mark.asyncio
async def test_history_happy_path():
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_ohlcv(3)

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.history("AAPL", start="2024-01-02", end="2024-01-05")

    assert result["error"] is None
    assert result["source"] == "yfinance"
    assert result["ticker"] == "AAPL"
    assert result["row_count"] == 3
    first = result["items"][0]
    # Date column normalised to lowercase + iso
    assert "date" in first
    assert isinstance(first["date"], str)
    # OHLCV columns present
    for col in ("open", "high", "low", "close", "volume"):
        assert col in first, f"missing {col!r} in result row"
    assert pytest.approx(first["close"], rel=1e-3) == 183.6


@pytest.mark.asyncio
async def test_history_empty_returns_message_not_error():
    """Bad ticker / out-of-range window → items=[] with a message, error=None."""
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.history("ZZZZZZ", start="2024-01-02", end="2024-01-05")

    assert result["error"] is None, "empty results aren't errors — bad tickers shouldn't trip the breaker"
    assert result["items"] == []
    assert "message" in result
    assert "ZZZZZZ" in result["message"]


@pytest.mark.asyncio
async def test_history_network_failure_returns_error_envelope():
    """A raised exception inside yfinance → structured error envelope."""

    def _boom(*args, **kw):
        raise RuntimeError("Yahoo connection reset")

    fake_ticker = MagicMock()
    fake_ticker.history.side_effect = _boom

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.history("AAPL", start="2024-01-02", end="2024-01-05")

    assert result["error"] is not None
    assert "RuntimeError" in result["error"]
    assert "Yahoo connection reset" in result["error"]
    assert result["items"] == []


@pytest.mark.asyncio
async def test_history_passes_auto_adjust():
    """--raw flag should propagate as auto_adjust=False into yfinance."""
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_ohlcv(1)

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        await provider.history("AAPL", auto_adjust=False)

    fake_ticker.history.assert_called_once()
    kwargs = fake_ticker.history.call_args.kwargs
    assert kwargs.get("auto_adjust") is False


# ---------- ticker_info ----------


@pytest.mark.asyncio
async def test_ticker_info_returns_curated_subset():
    """100+ noisy fields are filtered down to the documented curated subset."""
    fake_ticker = MagicMock()
    fake_ticker.info = {
        "symbol": "AAPL",
        "shortName": "Apple Inc.",
        "sector": "Technology",
        "marketCap": 3_500_000_000_000,
        "regularMarketPrice": 240.5,
        "beta": 1.2,
        "trailingPE": 35.0,
        # Noise we don't want polluting the model's context:
        "uuid": "abc-123",
        "messageBoardId": "finmb_24937",
        "exchangeTimezoneName": "America/New_York",
        "gmtOffSetMilliseconds": -18000000,
        "esgPopulated": False,
        "tradeable": True,
    }

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.ticker_info("AAPL")

    assert result["error"] is None
    assert len(result["items"]) == 1
    info = result["items"][0]
    # Curated fields kept
    assert info["symbol"] == "AAPL"
    assert info["sector"] == "Technology"
    assert info["marketCap"] == 3_500_000_000_000
    # Noise fields dropped
    assert "uuid" not in info
    assert "messageBoardId" not in info
    assert "gmtOffSetMilliseconds" not in info


@pytest.mark.asyncio
async def test_ticker_info_handles_missing_fields():
    """Partially-known tickers (sparse info dict) shouldn't crash."""
    fake_ticker = MagicMock()
    fake_ticker.info = {"symbol": "X", "currency": "USD"}

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.ticker_info("X")

    assert result["error"] is None
    assert result["items"][0]["symbol"] == "X"
    # Absent fields just aren't in the dict — no KeyError, no None placeholders.
    assert "marketCap" not in result["items"][0]


# ---------- fundamentals ----------


@pytest.mark.asyncio
async def test_fundamentals_transposes_yahoo_statement_shape():
    """Yahoo returns statements as (line_item × period) DataFrames; the
    provider transposes so each period becomes a row."""
    # Yahoo's actual shape: rows are line items, columns are period-end dates.
    statement_df = pd.DataFrame(
        {
            pd.Timestamp("2024-12-31"): [100.0, 50.0],
            pd.Timestamp("2023-12-31"): [90.0, 45.0],
        },
        index=["TotalRevenue", "GrossProfit"],
    )
    fake_ticker = MagicMock()
    fake_ticker.income_stmt = statement_df

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.fundamentals("AAPL", statement="income")

    assert result["error"] is None
    assert result["row_count"] == 2  # one row per period
    # Each row carries period_end + the line items
    row = result["items"][0]
    assert "period_end" in row
    assert "totalrevenue" in row
    assert "grossprofit" in row


@pytest.mark.asyncio
async def test_fundamentals_rejects_invalid_statement():
    provider = YFinanceProvider()
    result = await provider.fundamentals("AAPL", statement="not_a_real_statement")
    assert result["error"] is not None
    assert "income" in result["error"]
    assert "balance_sheet" in result["error"]


# ---------- dividends ----------


@pytest.mark.asyncio
async def test_dividends_returns_one_row_per_ex_date():
    series = pd.Series(
        [0.24, 0.25, 0.26],
        index=pd.to_datetime(["2024-02-09", "2024-05-10", "2024-08-12"]),
    )
    fake_ticker = MagicMock()
    fake_ticker.dividends = series

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.dividends("AAPL")

    assert result["error"] is None
    assert result["row_count"] == 3
    assert result["items"][0]["ex_date"].startswith("2024-02-09")
    assert pytest.approx(result["items"][0]["dividend"]) == 0.24


@pytest.mark.asyncio
async def test_dividends_empty_for_non_dividend_payer():
    fake_ticker = MagicMock()
    fake_ticker.dividends = pd.Series(dtype=float)

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        result = await provider.dividends("GOOG")  # historically didn't pay dividends

    assert result["error"] is None
    assert result["items"] == []
    assert "GOOG" in result["message"]


# ---------- search ----------


@pytest.mark.asyncio
async def test_search_returns_curated_candidates():
    fake_search = MagicMock()
    fake_search.quotes = [
        {"symbol": "AAPL", "shortname": "Apple Inc.", "exchange": "NMS", "quoteType": "EQUITY"},
        {"symbol": "APLE", "shortname": "Apple Hospitality REIT", "exchange": "NYQ", "quoteType": "EQUITY"},
    ]

    with patch("yfinance.Search", return_value=fake_search):
        provider = YFinanceProvider()
        result = await provider.search("Apple", max_results=5)

    assert result["error"] is None
    assert result["row_count"] == 2
    symbols = [r["symbol"] for r in result["items"]]
    assert "AAPL" in symbols
    assert "APLE" in symbols


@pytest.mark.asyncio
async def test_search_empty_returns_message():
    fake_search = MagicMock()
    fake_search.quotes = []

    with patch("yfinance.Search", return_value=fake_search):
        provider = YFinanceProvider()
        result = await provider.search("zzznonexistent")

    assert result["error"] is None
    assert result["items"] == []
    assert "zzznonexistent" in result["message"]


# ---------- envelope contract ----------


@pytest.mark.asyncio
async def test_every_response_has_source_and_envelope_keys():
    """Pin the response shape: every method returns {source, items, error}.
    Specialists rely on this contract — drift here would silently break
    downstream parsing."""
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_ohlcv(1)
    fake_ticker.info = {"symbol": "X"}
    fake_ticker.income_stmt = pd.DataFrame({pd.Timestamp("2024-12-31"): [1.0]}, index=["TotalRevenue"])
    fake_ticker.dividends = pd.Series(dtype=float)

    with patch("yfinance.Ticker", return_value=fake_ticker):
        provider = YFinanceProvider()
        for r in [
            await provider.history("X"),
            await provider.ticker_info("X"),
            await provider.fundamentals("X", statement="income"),
            await provider.dividends("X"),
        ]:
            assert r.get("source") == "yfinance"
            assert "items" in r
            assert "error" in r
