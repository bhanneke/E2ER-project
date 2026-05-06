# Bring Your Own Data (BYOD)

When the data module is disabled (`DATA_MODULE_ENABLED=false`) or the
researcher has uploaded files via `POST /api/papers/{id}/files`, the
pipeline runs without Allium. Specialists work with researcher-supplied
files directly.

## How user-provided data appears

Files uploaded via the dashboard or API land in `workspace/data/`. The
Tier-1 context block lists every file in that directory with size and a
short preview (first 5 non-empty lines for text formats).

Allowed extensions: `.csv`, `.tsv`, `.parquet`, `.xlsx`, `.xls`, `.json`,
`.jsonl`, `.txt`. Per-file size cap is 200 MB.

## Specialist behaviour when BYOD is in play

**`data_architect`**: if `data/` files exist, do NOT propose Allium queries.
Instead, write `data_dictionary.json` describing the columns of each
provided file and any cleaning steps the analyst should apply.

**`data_analyst`**: read the files directly with `read_file` (for small
text formats) or document the appropriate `pd.read_csv` / `pd.read_parquet`
call in `replication/estimation.py`. The estimation script must be runnable
against the same `data/` directory layout — assume the researcher will
re-run it from the workspace root.

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
