# FRED via `e2er-data fred`

Federal Reserve Economic Data — the gold standard for US (and increasingly
global) macro time series. Free, ~30s to register at
https://fredaccount.stlouisfed.org/apikey. Once `FRED_API_KEY` is set in
`.env`, every `e2er-data fred …` subcommand works.

When to use this:
- **CPI, PCE, core inflation** for inflation studies
- **Unemployment rate, labor force, payrolls** for labor research
- **Treasury yields (any maturity), Fed funds rate** for monetary research
- **GDP, productivity, business cycle indicators** for macro
- **Financial-stress indices, credit spreads** for crisis / risk studies
- **International macro** — FRED carries a lot of OECD / IMF series too
- **Anything where citation provenance must be airtight** — FRED is the
  authoritative source for the underlying series

When NOT to use this:
- High-frequency intraday data (FRED is daily at finest for most series)
- Firm-level / micro data (FRED is aggregate / macro)
- Non-public series (proprietary surveys, restricted research datasets)

## Subcommands

### `series` — pull a time series

```
e2er-data fred series \
  --series-id CPIAUCSL \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --save-to fred_CPIAUCSL.csv
```

**ALWAYS pass `--save-to <name>.csv`.** The wrapper writes the
observations to `workspace/data/<name>.csv` so the replication package
runs offline. FRED revises series occasionally (the `realtime_start` /
`realtime_end` columns track this); without `--save-to`, replication
would silently get different numbers on a re-fetch.

Returns one row per observation with `date`, `value`, plus
`realtime_start` / `realtime_end` (FRED tracks data revisions; these
indicate when this specific value was current).

The `value` is coerced to a float when possible. FRED's missing-value
sentinel `"."` is converted to `null`, so downstream parsing doesn't
break on dot-strings.

Common series ids:
- `CPIAUCSL` — CPI all urban consumers (headline inflation)
- `CPILFESL` — Core CPI (excludes food + energy)
- `PCEPILFE` — Core PCE (Fed's preferred inflation gauge)
- `UNRATE` — Unemployment rate (U-3)
- `U6RATE` — U-6 (broader unemployment)
- `PAYEMS` — Total nonfarm payrolls
- `DGS10` — 10-year Treasury yield (daily)
- `DGS2` — 2-year Treasury yield
- `DFF` — Federal funds rate (effective, daily)
- `FEDFUNDS` — Federal funds rate (monthly average)
- `GDPC1` — Real GDP (quarterly, chained 2017 dollars)
- `VIXCLS` — VIX (CBOE volatility index)

Don't have the id? Use `search` (below).

Transformations: `--units` accepts FRED's standard codes:
- `lin` (raw, default)
- `chg` (period-over-period change)
- `ch1` (year-over-year change)
- `pch` (% change vs previous)
- `pc1` (% change vs year ago — annualised rate)
- `log` (natural log)

For inflation regressions on CPI, `--units pc1` gives you the YoY %
inflation directly — saves a post-processing step.

### `series-info` — metadata BEFORE you pull

```
e2er-data fred series-info --series-id CPIAUCSL
```

Returns `title`, `units`, `frequency`, `seasonal_adjustment`,
`observation_start`, `observation_end`, `last_updated`, `notes`. **Run
this first** if you're unsure about a series — confirms the units (level
vs. index), the seasonal adjustment, and the data span. Saves you from
pulling 100K observations of the wrong thing.

### `search` — find a series by description

```
e2er-data fred search --query "core CPI" --limit 5
e2er-data fred search --query "10-year Treasury yield" --limit 5
e2er-data fred search --query "unemployment rate Germany"
```

Returns hits sorted by FRED's popularity score (override with
`--order-by observation_start` / `observation_end` / `search_rank`).
Use when you know the concept but not the series id.

### `releases` — browse FRED releases

```
e2er-data fred releases --limit 50
```

Lists FRED "releases" (the publication source — "Consumer Price Index",
"Employment Situation", "H.15 Selected Interest Rates", etc.). Less
often needed; useful when you want every series in a specific release.

## Output shape (uniform across subcommands)

```json
{
  "source": "fred",
  "items": [
    {"date": "2020-01-01", "value": 257.971, "realtime_start": "2020-02-13", ...},
    ...
  ],
  "error": null,
  "series_id": "CPIAUCSL",
  "row_count": 60
}
```

Always check `error` before iterating `items`. On error, do NOT fabricate
substitute data — report the failure transparently in `data_summary.md`.

## Citation guidance

For data sourced via this wrapper:

> Series `<ID>`: Federal Reserve Bank of St. Louis, FRED, retrieved
> YYYY-MM-DD. https://fred.stlouisfed.org/series/`<ID>`

The audit log records every call's parameters + timestamp so the
replication package can be regenerated exactly.

## Rate limit + behavior

- FRED's documented limit: 120 requests/minute per API key. Very
  generous for academic work.
- The wrapper paces requests by 0.5s as a courtesy + retries once on a
  transient 429.
- Errors → structured envelope, never raise.

## What this is NOT

- Not a real-time data feed (most series are released with a 1-4 week lag)
- Not a microdata source — for firm-level fundamentals use yfinance,
  SEC EDGAR, or Compustat (WRDS)
- Not free of revisions — the `realtime_start` / `realtime_end` columns
  matter if you're doing forecast-evaluation work. Use ALFRED
  (FRED's revision-tracking sibling) for full vintage data if needed
