"""Yahoo Finance provider — public financial data via the `yfinance` library.

No API key required. The underlying library scrapes Yahoo Finance, so:
  - Rate limits exist but aren't documented; we add modest per-request
    pacing as a courtesy.
  - Yahoo can rate-limit / temporarily block aggressive callers. The
    provider returns a structured error envelope on failure rather than
    raising into specialist code.
  - Data lineage is "Yahoo Finance" — academic use is widely accepted
    for daily / weekly equity prices, but cite carefully for anything
    intraday or fundamentals.

Async surface: yfinance is a synchronous library. We use ``asyncio.to_thread``
so the provider matches the rest of E2ER's async-first interface and doesn't
block the FastAPI event loop.

Coverage (what specialists can actually pull):
  - history(): OHLCV time series for one or more tickers
  - ticker_info(): current snapshot (price, market cap, sector, beta, ...)
  - fundamentals(): financial statements — income / balance sheet / cash flow
  - dividends(): dividend history
  - search(): name-to-ticker lookup (best-effort)

Output shape (every method): ``{"items": [...], "error": str | None,
"source": "yfinance"}`` for consistency with the Allium developer provider.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

_MIN_REQUEST_SPACING_SEC = 0.2  # Modest pacing; Yahoo throttles aggressive callers.

_pace_lock = asyncio.Lock()
_last_call_ts: float = 0.0


async def _pace_request() -> None:
    """Module-level pacing across concurrent yfinance calls."""
    global _last_call_ts
    async with _pace_lock:
        now = time.monotonic()
        wait = (_last_call_ts + _MIN_REQUEST_SPACING_SEC) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


def _envelope(items: list[Any] | None = None, error: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": "yfinance",
        "items": items or [],
        "error": error,
    }
    out.update(extra)
    return out


class YFinanceProvider:
    """Async wrapper around the synchronous yfinance library.

    Each method delegates to ``asyncio.to_thread`` so callers can ``await``
    without blocking the event loop. Returns ``{items, error, source}``
    envelopes for uniformity with other E2ER data providers.
    """

    async def history(
        self,
        ticker: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
        auto_adjust: bool = True,
    ) -> dict[str, Any]:
        """OHLCV time series for a single ticker.

        ``interval`` accepts yfinance's vocabulary: 1m, 2m, 5m, 15m, 30m,
        60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo. Intraday intervals (≤1h) are
        rate-limited by Yahoo to roughly the last 60 days.

        ``auto_adjust=True`` (default in modern yfinance) adjusts OHLC for
        dividends and splits — what you want for total-return research.
        Set False for raw close prices.
        """
        await _pace_request()
        return await asyncio.to_thread(self._history_sync, ticker, start, end, interval, auto_adjust)

    def _history_sync(
        self,
        ticker: str,
        start: str | None,
        end: str | None,
        interval: str,
        auto_adjust: bool,
    ) -> dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as e:
            return _envelope(error=f"yfinance not installed: {e}")

        try:
            t = yf.Ticker(ticker)
            df = t.history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=auto_adjust,
            )
        except Exception as e:
            logger.warning("yfinance history(%s) failed: %s", ticker, e)
            return _envelope(error=f"{type(e).__name__}: {e}", ticker=ticker)

        if df is None or df.empty:
            return _envelope(
                items=[],
                error=None,
                ticker=ticker,
                message=(
                    f"No data returned for {ticker!r} in window {start}→{end} "
                    f"(interval={interval}). Ticker may be invalid, delisted, or "
                    "outside the requested range."
                ),
            )

        # Index is timestamps; reset so rows have an explicit date column.
        df = df.reset_index()
        # Standardise column names to lowercase snake_case for consistency
        # across providers.
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        items = df.to_dict(orient="records")
        # Coerce pandas Timestamps to ISO strings — JSON-serializable.
        for row in items:
            for k, v in list(row.items()):
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
        return _envelope(items=items, ticker=ticker, interval=interval, row_count=len(items))

    async def ticker_info(self, ticker: str) -> dict[str, Any]:
        """Current snapshot — price, market cap, sector, beta, ...

        Returns a flattened dict under ``items[0]``. yfinance's ``info``
        is unstable across versions and tickers; expect missing fields.
        """
        await _pace_request()
        return await asyncio.to_thread(self._info_sync, ticker)

    def _info_sync(self, ticker: str) -> dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as e:
            return _envelope(error=f"yfinance not installed: {e}")

        try:
            t = yf.Ticker(ticker)
            info = t.info
        except Exception as e:
            return _envelope(error=f"{type(e).__name__}: {e}", ticker=ticker)

        if not info:
            return _envelope(items=[], ticker=ticker, message=f"No info returned for {ticker!r}")
        # Keep a curated subset to avoid dumping 100+ noisy fields.
        keep = (
            "symbol",
            "shortName",
            "longName",
            "currency",
            "exchange",
            "quoteType",
            "sector",
            "industry",
            "marketCap",
            "regularMarketPrice",
            "previousClose",
            "beta",
            "trailingPE",
            "forwardPE",
            "dividendYield",
            "fiftyTwoWeekHigh",
            "fiftyTwoWeekLow",
            "averageVolume",
            "country",
            "website",
        )
        curated = {k: info.get(k) for k in keep if k in info}
        return _envelope(items=[curated], ticker=ticker, raw_field_count=len(info))

    async def fundamentals(self, ticker: str, statement: str = "income") -> dict[str, Any]:
        """Annual financial statements: 'income', 'balance_sheet', or 'cash_flow'.

        Returns one row per fiscal year in ``items``. Yahoo provides ~4
        years of history for most public companies.
        """
        await _pace_request()
        return await asyncio.to_thread(self._fundamentals_sync, ticker, statement)

    def _fundamentals_sync(self, ticker: str, statement: str) -> dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as e:
            return _envelope(error=f"yfinance not installed: {e}")

        valid_statements = ("income", "balance_sheet", "cash_flow")
        if statement not in valid_statements:
            return _envelope(error=f"statement must be one of {valid_statements}; got {statement!r}")

        try:
            t = yf.Ticker(ticker)
            attr_map = {
                "income": "income_stmt",
                "balance_sheet": "balance_sheet",
                "cash_flow": "cashflow",
            }
            df = getattr(t, attr_map[statement])
        except Exception as e:
            return _envelope(error=f"{type(e).__name__}: {e}", ticker=ticker, statement=statement)

        if df is None or df.empty:
            return _envelope(items=[], ticker=ticker, statement=statement)

        # Yahoo orients statements as (line_item × period). Transpose so each
        # period is a row.
        df_t = df.T.reset_index().rename(columns={"index": "period_end"})
        df_t.columns = [str(c).lower().replace(" ", "_") for c in df_t.columns]
        items = df_t.to_dict(orient="records")
        for row in items:
            for k, v in list(row.items()):
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
        return _envelope(items=items, ticker=ticker, statement=statement, row_count=len(items))

    async def dividends(self, ticker: str) -> dict[str, Any]:
        """Full dividend history for a ticker.

        Returns one row per ex-dividend date with the dividend amount.
        """
        await _pace_request()
        return await asyncio.to_thread(self._dividends_sync, ticker)

    def _dividends_sync(self, ticker: str) -> dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as e:
            return _envelope(error=f"yfinance not installed: {e}")

        try:
            t = yf.Ticker(ticker)
            series = t.dividends
        except Exception as e:
            return _envelope(error=f"{type(e).__name__}: {e}", ticker=ticker)

        if series is None or series.empty:
            return _envelope(items=[], ticker=ticker, message=f"No dividends recorded for {ticker!r}")

        items = [
            {
                "ex_date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                "dividend": float(amount),
            }
            for d, amount in series.items()
        ]
        return _envelope(items=items, ticker=ticker, row_count=len(items))

    async def search(self, query: str, max_results: int = 10) -> dict[str, Any]:
        """Best-effort name-to-ticker lookup via yfinance's search.

        Useful when the model has a company name but doesn't know the
        exchange ticker. Returns up to ``max_results`` candidates.
        """
        await _pace_request()
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as e:
            return _envelope(error=f"yfinance not installed: {e}")

        try:
            s = yf.Search(query, max_results=max_results)
            quotes = s.quotes
        except Exception as e:
            return _envelope(error=f"{type(e).__name__}: {e}", query=query)

        if not quotes:
            return _envelope(items=[], query=query, message=f"No tickers found matching {query!r}")

        items = [
            {
                "symbol": q.get("symbol"),
                "shortname": q.get("shortname") or q.get("longname"),
                "exchange": q.get("exchange"),
                "quote_type": q.get("quoteType"),
                "sector": q.get("sector"),
            }
            for q in quotes
        ]
        return _envelope(items=items, query=query, row_count=len(items))
