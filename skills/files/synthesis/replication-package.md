# Replication Package

You are producing the replication materials that allow any researcher to reproduce every quantitative result in the paper from the raw data.

---

## What to produce

Write `replication/estimation.py` — a single self-contained Python script that re-runs the full analysis. Also produce `replication/README.md` documenting how to use the package.

---

## estimation.py — required structure

```python
"""
Replication script for: [paper title]
Paper ID: [paper_id]

Requirements: pandas, statsmodels, linearmodels, numpy
Usage: python estimation.py
Output: replication/output/ (tables as CSV, figures as PNG)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import statsmodels.formula.api as smf   # or linearmodels for panel

OUTPUT_DIR = Path("replication/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 1. Load data ──────────────────────────────────────────────────────────────
# Load from the workspace data files (e.g. data_summary.md describes the format)
# df = pd.read_csv("data/main_dataset.csv")

# ── 2. Variable construction ──────────────────────────────────────────────────
# Construct all variables exactly as described in the paper

# ── 3. Summary statistics ─────────────────────────────────────────────────────
# Table 1: summary stats
# summary = df.describe(); summary.to_csv(OUTPUT_DIR / "table1_summary.csv")

# ── 4. Main specification ─────────────────────────────────────────────────────
# Exactly replicates Table 2 in the paper
# model = smf.ols("y ~ x + controls", data=df).fit(cov_type="HC3")
# ...

# ── 5. Robustness checks ──────────────────────────────────────────────────────
# Alternative specifications matching Section 5 of the paper

# ── 6. Export results ─────────────────────────────────────────────────────────
# All tables to CSV, all figures to PNG
```

---

## Rules for estimation.py

**Variable naming:** Use exactly the same names as in the econometric specification (`econometric_spec.md`). Readers cross-referencing equations must find the same symbols.

**One regression per section:** Group by paper section (main, robustness, heterogeneity). A reader should be able to run section 4 without running section 5.

**No hardcoded credentials or paths:** Use `Path(__file__).parent` for relative paths. Data files load from the workspace.

**Reproducible:** Set `numpy.random.seed(42)` at the top. All stochastic operations must be seeded.

**Commented output:** Every `to_csv()` call gets a one-line comment saying which paper table it corresponds to.

**Standard errors:** Always use heteroskedasticity-robust SEs unless the econometric spec explicitly specifies otherwise. Document the choice.

---

## replication/README.md — required sections

1. **Data requirements**: what data files are needed and where to obtain them (reference `data_queries.sql` and the Allium tables used)
2. **Environment**: `pip install -r requirements.txt` with pinned versions
3. **Steps**: numbered steps from raw data to final tables and figures
4. **Output map**: table in paper → file in `replication/output/`
5. **Audit trail**: mention `audit_log.csv` and `data_queries.sql` in `replication/`

---

## What NOT to include

- Do NOT include actual data files (data stays with the researcher)
- Do NOT include API keys or database credentials
- Do NOT include intermediate cached results — the script should run clean from raw data
- Do NOT write a Jupyter notebook — a `.py` script is required for reproducibility auditing
