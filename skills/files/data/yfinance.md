# Yahoo Finance via `e2er-data yfinance`

Free public market data — equities, ETFs, mutual funds, crypto, FX,
indices. No API key. Goes through the same `e2er-data` gatekeeper that
fronts Allium and the other data sources.

When to use this:
- **Equity / ETF prices** for event studies, portfolio analysis,
  factor regressions, finance pedagogy.
- **Index / FX time series** as market controls in any empirical model.
- **Crypto spot prices** as a cheaper alternative to Allium when you
  only need the asset price (e.g. BTC-USD, ETH-USD).
- **Company snapshots** for cross-sectional regressors (sector,
  market cap, beta, P/E).
- **Financial statements** when you need 4-year-back fundamentals at
  no cost — for serious accounting research, prefer Compustat/WRDS.

When NOT to use this:
- High-frequency / intraday data > 60 days back (Yahoo caps it).
- Survivorship-bias-free historical universes — Yahoo drops delisted
  stocks. Use CRSP for that.
- Anything where strict provenance matters (Yahoo can change methodology
  silently). Cite as "Yahoo Finance, accessed YYYY-MM-DD" and pull a
  fresh extract when finalising the paper.

## Subcommands

### `history` — OHLCV time series

```
e2er-data yfinance history \
  --ticker AAPL \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --interval 1d \
  --save-to AAPL_2020_2024.csv
```

**ALWAYS pass `--save-to <name>.csv`.** The wrapper writes the rows to
`workspace/data/<name>.csv` so the replication package can be run offline
later. Without `--save-to`, the data only lives in the in-memory tool
result — replication scripts would have to re-hit Yahoo every time,
which is fragile (Yahoo silently revises data + delists tickers).

Returns rows with `date`, `open`, `high`, `low`, `close`, `volume`,
`dividends`, `stock_splits`. The `close` is split + dividend adjusted by
default (use `--raw` for unadjusted closes if you specifically need them).

Intervals: `1m`, `5m`, `15m`, `30m`, `60m`, `1d` (default), `5d`, `1wk`,
`1mo`. Intraday intervals are limited to roughly the last 60 days.

For event studies: daily resolution is the right default. Don't reach for
intraday unless the research design genuinely requires it.

### `ticker-info` — current snapshot

```
e2er-data yfinance ticker-info --ticker AAPL
```

Returns a single-row snapshot with `symbol`, `sector`, `industry`,
`marketCap`, `regularMarketPrice`, `beta`, `trailingPE`, `forwardPE`,
`dividendYield`, etc. Use for cross-sectional regressors, sector dummies,
or as a sanity check that a ticker exists before pulling history.

### `fundamentals` — annual financial statements

```
e2er-data yfinance fundamentals --ticker AAPL --statement income
e2er-data yfinance fundamentals --ticker AAPL --statement balance_sheet
e2er-data yfinance fundamentals --ticker AAPL --statement cash_flow
```

Returns one row per fiscal year (typically 4 years). Yahoo's coverage
beyond 4 years is unreliable; for deeper history use Compustat or
SEC EDGAR (`e2er-data edgar 10-K …`, coming next release).

### `dividends` — full dividend history

```
e2er-data yfinance dividends --ticker AAPL
```

One row per ex-dividend date with the cash amount. Useful for total-
return decomposition or dividend-yield studies.

### `search` — name → ticker lookup

```
e2er-data yfinance search --query "Apple" --max-results 5
```

Use when you know the company name but not the exchange ticker. Returns
candidates with their symbol, exchange, sector. Not exhaustive — falls
back gracefully when no matches.

## Output shape (uniform across subcommands)

```json
{
  "source": "yfinance",
  "items": [ /* one or more rows */ ],
  "error": null | "<error string>",
  "ticker": "AAPL",     // when relevant
  "row_count": N        // when relevant
}
```

**Always check `error` before iterating `items`.** On error, do NOT
fabricate substitute data — report the failure in `data_summary.md`
with the actual error string.

Empty `items` with `error: null` means "no data in this window" (often a
bad ticker or a date range before the asset existed). The `message` field
explains.

## Bad-ticker behaviour

A non-existent ticker (e.g. `ZZZZZZ`) returns `items: []` with a
diagnostic message — no exception. Always verify by trying `ticker-info`
first if the ticker is unusual.

## Citation guidance for the paper

For data sourced via this wrapper, cite as:

> Daily price data: Yahoo Finance, retrieved YYYY-MM-DD via the
> `yfinance` Python library (https://pypi.org/project/yfinance/).

The audit log records every call's parameters + timestamp so the
replication package can be regenerated.

## What this is NOT

- Not a replacement for Allium when on-chain transaction-level data is
  the question
- Not a replacement for CRSP for survivorship-bias-free finance research
- Not real-time — quotes are delayed 15+ minutes
- Not for high-volume / commercial use — Yahoo may rate-limit aggressive
  callers. The wrapper paces requests by 0.2s as a courtesy.
