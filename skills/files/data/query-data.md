# Querying the local data warehouse with `e2er-data query`

When the researcher's data has been imported into this paper's SQLite warehouse,
your context contains a **"Local Data Warehouse (data.db)"** block listing every
table — its columns + types, row count, and a few sample rows. Run **read-only
SQL** against that warehouse with the `e2er-data query` command (via Bash):

```bash
e2er-data query tables                              # list tables, columns, samples
e2er-data query sql "SELECT COUNT(*) FROM nft_trades_sample"
```

(On the SDK backends this same capability is exposed as a `query_data(sql=...)`
tool; on the Claude Code CLI use the `e2er-data query` command above.)

## Check the real columns BEFORE you define anything

The single most important rule: **never invent a proxy for something the data
already records.** Inspect the actual columns and their values first.

```bash
e2er-data query sql "SELECT DISTINCT aggregator_name FROM nft_trades_sample LIMIT 20"
e2er-data query sql "SELECT aggregator_name, COUNT(*) FROM nft_trades_sample GROUP BY aggregator_name ORDER BY 2 DESC"
```

If a labelled column exists (e.g. `aggregator_name` with values `Blur`, `Gem`),
build your treatment/variable from it — do **not** derive a noisy proxy from
other fields (e.g. comparing addresses). A wrong proxy is the kind of
construct-validity error referees reject.

## Profile and aggregate in SQL, not in memory

The warehouse can hold millions of rows. `query_data` returns only the window or
aggregate you ask for, so prefer SQL for distributions, group means, coverage,
time ranges, and missingness:

```bash
e2er-data query sql "SELECT MIN(block_timestamp), MAX(block_timestamp) FROM nft_trades_sample"
e2er-data query sql "SELECT channel, AVG(creator_fee_usd) AS mean_fee, COUNT(*) AS n FROM ... GROUP BY channel"
```

Do not read a multi-million-row CSV into memory just to compute a mean.

## Provenance + the final script

Every `e2er-data query` call is recorded for the replication package — so the
queries you run **are** your data-provenance trail. Document the key ones in your
output (`data_summary.md` / the spec you produce).

The final reproducible estimation script (`run_estimation.py`) may still read the
data files with `pandas` — that's expected. But **verify the columns and their
meanings with `e2er-data query` first**, so the script operates on real fields
rather than assumptions. Explore with SQL; reproduce with pandas.

Rules: one `SELECT`/`WITH` statement per call; it is read-only (no writes);
results are capped — aggregate or `LIMIT` rather than selecting everything.
