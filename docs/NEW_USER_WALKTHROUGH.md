# New-user walkthrough — bring your own data + papers

This is the canonical "as a real researcher" path: point E2ER at a folder of
**your data** and a folder of **your papers**, and it discovers them, imports
them into the paper's own SQLite warehouse, and does real research against them
— no Postgres, no Docker, no API keys required.

It replaces the old synthetic test cases (which disabled data and produced
fabricated numbers). Everything here runs on the **zero-config SQLite default**.

## 1. Point E2ER at your folders

Two env vars (in `.env` or the shell):

```bash
# Your data files — CSV / TSV / Parquet / XLSX / JSONL. Imported into the
# paper's data.db as queryable SQL tables.
LOCAL_DATA_DIR=~/Documents/Academic/ResearchData

# Your papers — either a plain folder of PDFs, OR a Zotero data folder
# (one containing zotero.sqlite + storage/). Auto-detected. Falls back to
# LOCAL_DATA_DIR if unset.
LITERATURE_DIR=~/Documents/Academic/Literature   # or: ~/Zotero
```

No `DATABASE_URL` → SQLite at `~/.e2er/papers.db`. Leave `ALLIUM_API_KEY` /
`FRED_API_KEY` unset and the run uses only your data + (optionally) keyless
yfinance.

## 2. Run a paper

```bash
e2er run "Does buy/sell pressure predict short-horizon returns on Friend.Tech?" \
  --methodology empirical --mode iterative
```

## 3. What happens (and what to look for)

At **paper creation** the API:

1. **Stages** your files into `workspace/<paper_id>/data/` (data) and
   `workspace/<paper_id>/literature/` (PDFs).
2. **Imports** every tabular file into `workspace/<paper_id>/data.db` as a SQL
   table (one per file; xlsx → one per sheet). Log line:
   `BYOD import: N table(s) into data.db (…)`.
3. **Discovers** your literature folder (PDF metadata via pypdf, or a read-only
   pass over `zotero.sqlite`), enriches via CrossRef/OpenAlex, and **persists**
   each paper into the SQLite `literature_items` table. Log line:
   `BYOD literature: discovered=N stored=M`.

During the run, the **data/econometrics specialists** see a context block
**"Local Data Warehouse (data.db)"** listing each table's columns, row count,
and sample rows, and query it with the **`query_data`** tool:

```text
query_data(sql="SELECT day, AVG(price) FROM nft_trades GROUP BY day ORDER BY day")
```

They can also pull an external series into the same warehouse and join it:

```text
fetch_data(provider="yfinance", method="history", params={"symbol":"ETH-USD"}, materialize=true)
query_data(sql="SELECT ... FROM nft_trades t JOIN yfinance_history_eth_usd e ON ...")
```

The **literature specialists** find your own papers first: on SQLite,
`search_papers` returns the persisted local library (tagged `local_library`)
before falling back to OpenAlex/arXiv, and reads any staged PDF in full via
`read_reference(path="literature/yourpaper.pdf")`.

## 4. Verify the result

A good run produces a paper whose:

- **numbers trace to `data.db`** — open `workspace/<paper_id>/data.db` and the
  `data_query_records` audit (queries the model actually ran), not invented
  figures;
- **citations point to your library** — entries from your folder / Zotero, read
  via `read_reference`.

```bash
sqlite3 workspace/<paper_id>/data.db ".tables"
sqlite3 ~/.e2er/papers.db "SELECT title, year, source FROM literature_items LIMIT 10;"
```

## Notes & limits

- **Caps.** Imports are capped at `MAX_ROWS_PER_PAPER` rows/table; literature
  discovery at `LITERATURE_MAX_INGEST` papers (default 500) to bound startup and
  CrossRef load.
- **Read-only SQL.** `query_data` permits a single `SELECT`/`WITH` only — the DB
  is opened read-only; writes happen only through import/materialize.
- **Zotero is never modified.** The reader copies `zotero.sqlite` and opens the
  copy read-only.
- **Postgres.** With `DATABASE_URL=postgresql://…` the literature path uses the
  pgvector KB instead of the local SQLite library; the data.db path is unchanged.
- Scanned/encrypted PDFs with no text layer fall back to filename-derived titles
  (no OCR).
