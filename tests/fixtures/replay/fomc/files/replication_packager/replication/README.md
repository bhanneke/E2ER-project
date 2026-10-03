# Replication Package: FOMC Target-Rate Announcements and Bank Stock Returns

**Paper**: How do US bank stocks respond to Federal Reserve target-rate announcements? An event study of FOMC decisions, 2015–2025.

**Paper ID**: @@PAPER_ID@@

**Analysis Date**: September 29, 2026

---

## Overview

This replication package allows any researcher to reproduce the quantitative results presented in the paper. The analysis is an event study examining how US bank stocks (KBE sector ETF) respond to Federal Reserve target-rate announcements using the S&P 500 (SPY) as a market benchmark.

**Study Design**:
- **Sample**: 31 FOMC target-rate announcements (December 2015 – December 2025)
- **Event asset**: KBE (Bank Sector ETF)
- **Market benchmark**: SPY (S&P 500 Index)
- **Event windows**: [-1, +1] days (primary) and [0, +5] days (secondary)
- **Abnormal return model**: Market model estimated over [-250, -12] trading days
- **Hypotheses**:
  - **H1**: Mean cumulative abnormal returns (CAR) differ from zero (tested separately for rate hikes and cuts)
  - **H2**: CAR sensitivity to same-day 2-year Treasury yield changes (tested pooled and by direction)

---

## Data Requirements

### Source Data Tables

The analysis requires the following tables in `data.db`:

| Table | Source | Format | Required Columns |
|-------|--------|--------|------------------|
| `fomc_announcement_dates` | Researcher-supplied | Table | `announcement_date` (TEXT/DATE), `direction` (TEXT: "increase"/"cut"), `dfedtaru_before`, `dfedtaru_after` |
| `kbe_prices` | Yahoo Finance | Table | `date` (TEXT/DATE), `close` (REAL) |
| `spy_prices` | Yahoo Finance | Table | `date` (TEXT/DATE), `close` (REAL) |
| `xlf_prices` | Yahoo Finance | Table | `date` (TEXT/DATE), `close` (REAL) |
| `dgs2` | FRED | Table | `date` (TEXT/DATE), `value` (REAL, in percent) |
| `dfedtaru` | FRED | Table | `date` (TEXT/DATE), `value` (REAL, in basis points) |

### Data Coverage

- **Price data (KBE, SPY, XLF)**: 2014-01-02 to 2025-12-30 (3,017 daily observations each)
- **Yield data (DGS2)**: 2015-01-01 to 2025-12-31 (2,870 rows, 2,750 non-null)
- **Fed Rate (DFEDTARU)**: 2015-01-02 to 2025-12-30 (2,765 observations)
- **FOMC Events**: 31 announcements from 2015-12-16 to 2025-12-10 (20 hikes, 11 cuts)

### Data Acquisition

**Open Data**: All data are obtained from public, free sources:

1. **Yahoo Finance** (via `yfinance` library):
   ```bash
   pip install yfinance
   ```
   Obtain KBE, SPY, XLF daily prices programmatically or manually.

2. **FRED API** (Federal Reserve Economic Data):
   ```bash
   pip install pandas-datareader
   ```
   Series IDs:
   - `DGS2`: 2-year Treasury constant-maturity yield
   - `DFEDTARU`: Federal Funds Target Rate Upper Bound

3. **FOMC Announcement Dates**: Historical archive at https://www.federalreserve.gov/monetarypolicy/fomc.htm

**How to populate data.db**:

Using e2er's data tools (if available in your research workflow):
```bash
e2er-data yahoo-finance --ticker KBE --start 2014-01-02 --end 2025-12-30 --table kbe_prices --paper-id <paper-id>
e2er-data yahoo-finance --ticker SPY --start 2014-01-02 --end 2025-12-30 --table spy_prices --paper-id <paper-id>
e2er-data yahoo-finance --ticker XLF --start 2014-01-02 --end 2025-12-30 --table xlf_prices --paper-id <paper-id>
e2er-data fred series --series-id DGS2 --start 2015-01-01 --end 2025-12-31 --table dgs2 --paper-id <paper-id>
e2er-data fred series --series-id DFEDTARU --start 2015-01-02 --end 2025-12-30 --table dfedtaru --paper-id <paper-id>
```

Or manually load into SQLite:
```python
import pandas as pd
import sqlite3

conn = sqlite3.connect("data.db")

# Example: load DGS2 from CSV
dgs2 = pd.read_csv("DGS2.csv")  # Must have 'date' and 'value' columns
dgs2.to_sql("dgs2", conn, if_exists="replace", index=False)

conn.close()
```

---

## Environment Setup

### Python Requirements

- Python 3.8+
- Dependencies: `pandas`, `numpy`, `scipy`, `statsmodels`, `sqlite3`

### Installation

1. **Clone or navigate to the replication directory**:
   ```bash
   cd replication/
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Or manually:
   ```bash
   pip install pandas>=1.3 numpy>=1.20 scipy>=1.7 statsmodels>=0.13
   ```

### Verify Installation

```python
import sqlite3
import pandas as pd
import numpy as np
from scipy import stats
import statsmodels.api as sm

print("All dependencies installed successfully!")
```

---

## Steps to Reproduce Results

### Step 1: Ensure Data Files Are Available

Verify that `data.db` is present in the parent directory with all required tables:
```bash
cd replication/
python -c "
import sqlite3
conn = sqlite3.connect('../data.db')
cursor = conn.cursor()
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
tables = [row[0] for row in cursor.fetchall()]
required = {'fomc_announcement_dates', 'kbe_prices', 'spy_prices', 'xlf_prices', 'dgs2', 'dfedtaru'}
print('Tables in data.db:', tables)
print('All required tables present:', required.issubset(set(tables)))
conn.close()
"
```

### Step 2: Run the Estimation Script

```bash
python estimation.py
```

**Expected output**:
- Console: Progress messages and summary statistics for H1 and H2 tests
- Directory `replication/output/`: CSV files with results

**Runtime**: ~1–2 minutes on a standard laptop

### Step 3: Verify Output Files

Check that the following files were created in `replication/output/`:
```bash
ls -lah output/
```

Expected files:
- `event_study_results.csv` – Event-level abnormal returns and market model parameters
- `table_h1_mean_car.csv` – Hypothesis 1 results (mean CAR tests)
- `table_h2_surprise_sensitivity.csv` – Hypothesis 2 results (CAR vs. yield change regression)
- `summary.json` – Metadata and test count

---

## Output Map

### Main Results Tables

#### Table 1: Hypothesis 1 — Mean Cumulative Abnormal Returns

**File**: `output/table_h1_mean_car.csv`

| Column | Description |
|--------|-------------|
| Hypothesis | H1a (hikes) or H1b (cuts) |
| Window | Event window: [-1, +1] or [0, +5] (trading days) |
| Direction | increase (rate hike) or cut (rate decrease) |
| N | Number of events in subsample |
| df | Degrees of freedom (N – 1) |
| Mean CAR (%) | Point estimate of mean cumulative abnormal return, in percentage points |
| Std Dev (%) | Cross-sectional standard deviation of CARs |
| SE (%) | Standard error of mean CAR |
| t-stat | t-statistic for H0: mean CAR = 0 |
| p-value | Two-sided p-value from t-distribution with df degrees of freedom |
| CI Lower / CI Upper | 95% confidence interval bounds |

**Interpretation**:
- Primary (pre-registered): Hikes and cuts in window [-1, +1]
- Secondary (not pre-registered): Pooled estimate in window [0, +5]

#### Table 2: Hypothesis 2 — CAR Sensitivity to Treasury Yield Surprise

**File**: `output/table_h2_surprise_sensitivity.csv`

Regression: CAR[−1,+1] = α + β·ΔDG S2 + ε

| Column | Description |
|--------|-------------|
| Hypothesis | H2 (pooled), H2_hikes, or H2_cuts |
| N | Number of events in regression sample |
| df | Degrees of freedom (N – 2) |
| Intercept | Estimated constant term (α) |
| Beta Coefficient | Sensitivity of CAR (%) to ΔDG S2 (bps); main parameter of interest |
| HC1 SE | Heteroskedasticity-consistent standard error (HC1) of β |
| t-stat | t-statistic for H0: β = 0 |
| p-value | Two-sided p-value from t-distribution with df degrees of freedom |
| CI Lower / CI Upper | 95% confidence interval bounds |
| R-squared | Model R² (fit of CAR by yield change) |

**Interpretation**:
- Primary (pre-registered): Pooled regression over all 31 events
- Secondary (exploratory): Separate regressions for hikes and cuts
- β = -0.0165 means: for every 1 basis point increase in the 2-year Treasury yield on announcement day, KBE abnormal return decreases by 0.0165 percentage points

#### Event-Level Results

**File**: `output/event_study_results.csv`

| Column | Description |
|--------|-------------|
| event_id | Unique event identifier (1–31) |
| announcement_date | FOMC announcement date (YYYY-MM-DD) |
| direction | increase (rate hike) or cut (rate decrease) |
| car_m1p1 | Cumulative abnormal return over [-1, +1] window (%) |
| car_0p5 | Cumulative abnormal return over [0, +5] window (%) |
| dgs2_change | Change in 2-year Treasury yield on announcement day (basis points) |
| alpha | Market model intercept (α̂) |
| beta | Market model slope (β̂, KBE sensitivity to SPY) |
| model_r2 | R² from market model estimation |
| n_obs_est | Number of observations used in market model estimation |

Use this table to:
- Examine individual event effects (e.g., identify most negative/positive CARs)
- Assess heterogeneity in market model fits
- Cross-check results with the aggregated H1 and H2 tables

#### Summary Metadata

**File**: `output/summary.json`

JSON structure with:
- `analysis_date`: ISO timestamp of analysis execution
- `events_total`: Total number of FOMC announcements analyzed
- `events_with_dgs2`: Number of events with non-missing 2-year yield data
- `hikes` / `cuts`: Breakdown by announcement type
- `data_period`: Date range and trading day count
- `hypotheses_tested`: Lists of hypothesis test IDs completed

---

## Paper Results Reference

### Mapping Results to Paper Sections

| Paper Table/Figure | Replication Output | Description |
|---|---|---|
| Table 1 (main results) | `table_h1_mean_car.csv` (rows: Hikes & Cuts, window [-1,+1]) | H1a and H1b pre-registered mean CAR tests |
| Extended Table (robustness) | `table_h2_surprise_sensitivity.csv` (row: H2_pooled) | H2 primary regression (all 31 events) |
| Appendix (by direction) | `table_h2_surprise_sensitivity.csv` (rows: H2_hikes, H2_cuts) | H2 secondary regressions |

---

## Diagnostic Checks

### Market Model Quality

Inspect `event_study_results.csv` columns `model_r2` and `n_obs_est`:

```python
import pandas as pd
results = pd.read_csv("output/event_study_results.csv")
print("Market model R² statistics:")
print(results["model_r2"].describe())
print("\nNumber of observations in estimation window:")
print(results["n_obs_est"].describe())
```

Expected:
- `model_r2`: mean ~0.87, range [0.70, 0.95] (typical for broad market indices)
- `n_obs_est`: all ≥ 100 (sufficient for stable parameter estimates)

### Pre-Event Drift

To check for anticipation bias, compute the mean CAR over days [-10, -2] (not included in the main specification):

```python
# Code to add to estimation.py if needed
pre_event_car = results_df.groupby("direction")["car_pre"].mean()
print("Pre-event CAR (days -10 to -2):", pre_event_car)
```

If negative, suggests market begins discounting rate hikes before announcement.

---

## Known Limitations & Caveats

1. **Event window overlap**: The 31 events span 10 years. Estimation windows [−250, −12] are designed to avoid overlap, but back-to-back FOMC meetings (rare) may violate this assumption. The script reports excluded events if found.

2. **Yield data missingness**: DGS2 has no values on market holidays. The script handles this by using the most recent prior trading day's yield. Check `summary.json` field `events_with_dgs2` to confirm coverage.

3. **COVID-19 period (March 2020)**: Emergency rate cuts during the pandemic may not follow typical monetary policy dynamics. Pre-registered robustness check available (sample n=29 excluding March 2020 events); see `econometric_spec.md`.

4. **March 2023 banking stress**: The March 16, 2023 rate hike coincided with regional bank failures (SVB collapse), confounding announcement effects. Pre-registered robustness check available; see `econometric_spec.md`.

---

## Audit Trail & Reproducibility

### Data Processing Log

- **Input data acquisition**: 2026-09-29
- **Market model estimation date**: 2026-09-29 (blind to results until pre-registration frozen)
- **DGS2 reload by researcher**: 2026-09-29 15:27 UTC (initial data analyst load returned null values due to API key error; researcher reloaded)

### Computational Environment

- **Python version**: 3.8+
- **Random seed**: 42 (set at script start for reproducibility)
- **Operating system**: Linux/macOS/Windows (platform-agnostic)

### Verification Steps

1. **Verify 31 events loaded**:
   ```bash
   python -c "
   import pandas as pd
   df = pd.read_csv('output/event_study_results.csv')
   print(f'Events in output: {len(df)}')
   print(f'Hikes: {(df[\"direction\"] == \"increase\").sum()}')
   print(f'Cuts: {(df[\"direction\"] == \"cut\").sum()}')
   "
   ```

2. **Verify hypothesis tests are present**:
   ```bash
   head output/table_h1_mean_car.csv
   head output/table_h2_surprise_sensitivity.csv
   ```

3. **Re-run full pipeline**:
   ```bash
   rm -rf output/  # Remove prior results
   python estimation.py
   # Compare new results to prior runs; should be numerically identical
   ```

---

## Contact & Citation

If you use this replication package, please cite:

```bibtex
@paper{fomc2025,
  title={How do {US} bank stocks respond to {Federal} {Reserve} target-rate announcements? An event study of {FOMC} decisions, 2015–2025},
  author={Anonymous},
  year={2026},
  note={Replication package: \url{https://...}}
}
```

---

## License & Terms

This replication package is provided for transparency and educational purposes. The underlying data (prices, yields) are public domain or licensed for research use. The code and methodology are available under standard academic license.

---

## Troubleshooting

### "data.db not found"

**Solution**: Ensure `data.db` is in the parent directory of `replication/`:
```bash
cd replication/
ls -la ../data.db
```

### "table 'fomc_announcement_dates' does not exist"

**Solution**: Load the FOMC events table:
```bash
# Insert 31 events into data.db (see data acquisition section)
```

### "ImportError: No module named statsmodels"

**Solution**:
```bash
pip install statsmodels
```

### Results differ between runs

**Cause**: Numerical precision in matrix inversion or platform differences.

**Solution**: Exact replication is guaranteed only on the same machine and Python/library versions. Differences should be < 0.001% in magnitude.

---

**End of README**
