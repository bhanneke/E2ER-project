# Querying the local data warehouse with `query_data`

When the researcher's data has been imported into this paper's SQLite warehouse,
your context contains a **"Local Data Warehouse (data.db)"** block listing every
table — its columns + types, row count, and a few sample rows. The
`query_data(sql)` tool runs **read-only SQL** against that warehouse. Use it.

## Check the real columns BEFORE you define anything

The single most important rule: **never invent a proxy for something the data
already records.** Inspect the actual columns and their values first.

```text
query_data(sql="SELECT DISTINCT aggregator_name FROM nft_trades_sample LIMIT 20")
query_data(sql="SELECT aggregator_name, COUNT(*) FROM nft_trades_sample GROUP BY aggregator_name ORDER BY 2 DESC")
```

If a labelled column exists (e.g. `aggregator_name` with values `Blur`, `Gem`),
build your treatment/variable from it — do **not** derive a noisy proxy from
other fields (e.g. comparing addresses). A wrong proxy is the kind of
construct-validity error referees reject.

## Profile and aggregate in SQL, not in memory

The warehouse can hold millions of rows. `query_data` returns only the window or
aggregate you ask for, so prefer SQL for distributions, group means, coverage,
time ranges, and missingness:

```text
query_data(sql="SELECT MIN(block_timestamp), MAX(block_timestamp) FROM nft_trades_sample")
query_data(sql="SELECT channel, AVG(creator_fee_usd) AS mean_fee, COUNT(*) AS n FROM ... GROUP BY channel")
```

Do not `read_file` a multi-million-row CSV into memory just to compute a mean.

## Pulling in external series

You can materialize an external series into the same warehouse and then join it:

```text
fetch_data(provider="yfinance", method="history", params={"symbol":"ETH-USD"}, materialize=true)
query_data(sql="SELECT t.day, AVG(t.price_usd), e.close FROM trades t JOIN yfinance_history_eth_usd e ON ...")
```

## Provenance + the final script

Every `query_data` call is recorded for the replication package — so the queries
you run **are** your data-provenance trail. Document the key ones in your output
(`data_summary.md` / the spec you produce).

The final reproducible estimation script (`run_estimation.py`) may still read the
data files with `pandas` — that's expected. But **verify the columns and their
meanings with `query_data` first**, so the script operates on real fields rather
than assumptions. Explore with SQL; reproduce with pandas.

Rules: one `SELECT`/`WITH` statement per call; it is read-only (no writes);
results are capped — aggregate or `LIMIT` rather than selecting everything.
