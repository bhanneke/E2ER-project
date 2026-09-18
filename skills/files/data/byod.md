# Bring Your Own Data (BYOD)

When the data module is disabled (`DATA_MODULE_ENABLED=false`) or the
researcher has uploaded files via `POST /api/papers/{id}/files`, the
pipeline runs without Allium. Specialists work with researcher-supplied
files directly.

## How user-provided data appears

Files uploaded via the dashboard/API, or discovered from the researcher's
`LOCAL_DATA_DIR`, land in `workspace/data/`. Tabular files (`.csv`, `.tsv`,
`.parquet`, `.xlsx`, `.jsonl`) are **automatically imported into the paper's
`data.db`** at paper creation and become queryable SQL tables. Free-text
`.txt` files stay file-only.

Allowed extensions: `.csv`, `.tsv`, `.parquet`, `.xlsx`, `.xls`, `.json`,
`.jsonl`, `.txt`. Per-file size cap is 200 MB.

## Querying the data warehouse with `query_data` (preferred)

Your context block **"Local Data Warehouse (data.db)"** lists every imported
table — its name, columns + types, row count, and a few sample rows. Prefer
the `query_data` tool over reading whole files into memory: it runs real
read-only SQL against `data.db` and is the right tool for millions of rows.

```text
query_data(sql="SELECT date, AVG(price) FROM nft_trades_all GROUP BY date ORDER BY date")
```

Rules: a single `SELECT`/`WITH` statement, no writes (it's read-only),
results are capped — aggregate or `LIMIT` rather than selecting everything.
You can also pull an external series into the same warehouse:
`fetch_data(provider="fred", method="get_series_observations",
params={"series_id":"DGS10"}, materialize=true)` then join it with `query_data`.

## Specialist behaviour when BYOD is in play

**`data_architect`**: if `data/` files exist, do NOT propose Allium queries.
Instead, write `data_dictionary.json` describing the columns of each
provided file and any cleaning steps the analyst should apply.

**`data_analyst`**: explore the data with `query_data` (SQL against `data.db`)
to understand distributions, coverage, and key columns before writing code.
For the final `replication/estimation.py`, read the files with
`pd.read_csv` / `pd.read_parquet` so the script is self-contained and runnable
against the same `data/` directory layout — assume the researcher will re-run
it from the workspace root. Use `read_file` only for small text formats.

**Estimation code conventions when using BYOD**:

```python
import pandas as pd
DATA_DIR = "data"  # files live next to this script when run from replication/
df = pd.read_csv(f"../{DATA_DIR}/yourfile.csv")
```

Note the `../` prefix: `replication/estimation.py` lives one level deeper
than the data files.

## When BYOD and Allium are both enabled

If both an Allium key and uploaded files are present, the data_architect
should treat user files as authoritative for any variable they cover, and
use Allium only for variables not already in `data/`. Document this
provenance split in `paper_plan.md`.
