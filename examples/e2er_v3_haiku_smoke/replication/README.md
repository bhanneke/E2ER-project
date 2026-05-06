# Replication Package: Temporal Dynamics of Ethereum

**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Title:** Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge  
**Author:** [Anonymous]  
**Date:** 2025  

---

## Overview

This replication package allows researchers to reproduce all quantitative results from the paper using Python and publicly available Ethereum blockchain data. The analysis examines the empirical relationship between Ethereum block height and wall-clock elapsed time since the September 2022 Merge (transition from Proof-of-Work to Proof-of-Stake consensus).

---

## Quick Start

### 1. Install Dependencies

```bash
# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### 2. Obtain Data

Extract Ethereum block data from one of these sources:

#### Option A: Google BigQuery (Recommended)
```sql
-- Query for Google BigQuery Ethereum dataset
SELECT 
    number as block_number,
    timestamp as block_timestamp,
    gas_used,
    transaction_count
FROM `bigquery-public-data.ethereum_mainnet.blocks`
WHERE timestamp >= UNIX_DATE('2022-09-15')
ORDER BY number
```

Save as `data/ethereum_blocks.csv` or `data/ethereum_blocks.parquet`.

#### Option B: Allium Data Platform
```sql
-- Query for Allium (production recommended)
SELECT 
    block_number,
    block_timestamp,
    gas_used,
    transaction_count,
    from_address as miner_address
FROM ethereum.core.blocks
WHERE block_timestamp >= 1663340827  -- 2022-09-15 00:00:00 UTC
ORDER BY block_number
```

See `data_queries.sql` for complete extraction queries.

#### Option C: Archive Node (via JSON-RPC)

Use an archive node endpoint (Infura, Alchemy, or self-hosted) to fetch blocks:

```bash
# Example: fetch blocks via curl
for block in {15537394..15600000}; do
    curl -X POST https://mainnet.infura.io/v3/{PROJECT_ID} \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"eth_getBlockByNumber","params":["0x'$(printf '%x' $block)'",false],"id":1}' \
      | jq '.result' >> blocks.jsonl
done
```

Then convert JSONL to CSV with `scripts/jsonl_to_csv.py`.

### 3. Run the Replication Script

```bash
python replication/estimation.py
```

**Execution time:** ~5-10 minutes (depending on dataset size and machine)

**Output location:** `replication/output/`

### 4. View Results

Results are saved as CSV tables and PNG figures:

```bash
ls replication/output/
```

Expected files:
- `table1_summary_stats.csv` — Summary statistics by period
- `table2_ols_baseline.csv` — OLS regression results
- `table3_rdd_merge_effect.csv` — Regression discontinuity (Merge effect)
- `table4_distribution_analysis.csv` — TBB distribution statistics
- `table5_skip_analysis.csv` — Slot skip rates and patterns
- `table6_early_vs_stable_pos.csv` — Early vs. Stable PoS comparison
- `diagnostic_tests.csv` — Statistical test results
- `figure1_scatter_by_period.png` — Scatter plots by period
- `figure2_rdd_discontinuity.png` — RDD discontinuity plot
- `figure3_tbb_distributions.png` — Kernel density plots
- `figure4_skip_rates.png` — Skip rate trends over time
- `figure5_early_vs_stable.png` — Early vs. Stable PoS distributions

---

## Environment Setup

### Requirements

- **Python:** 3.8+
- **Operating System:** Linux, macOS, or Windows
- **Storage:** ~2-5 GB for raw data; ~500 MB for processed output
- **RAM:** 8+ GB recommended
- **Internet:** Required for data extraction (first run only)

### Install Package Versions

```bash
pip install pandas==1.5.3 \
            numpy==1.24.1 \
            scipy==1.10.0 \
            statsmodels==0.14.0 \
            matplotlib==3.7.0 \
            seaborn==0.12.2
```

See `requirements.txt` for exact pinned versions.

---

## Data Requirements

### Data Source Options

| Source | Format | Coverage | Latency | Cost |
|--------|--------|----------|---------|------|
| **Google BigQuery** | Query API | Complete mainnet | Real-time | $7/TB (after free tier) |
| **Allium** | SQL + API | Complete mainnet | Real-time | Enterprise pricing |
| **Flipside Crypto** | Query API | Complete mainnet | ~5 min | Variable by plan |
| **Archive Node** | JSON-RPC | Complete mainnet | Depends on node | Infrastructure cost or service fee |

### Required Data Fields

The extraction query must return these columns:

| Column | Data Type | Description |
|--------|-----------|-------------|
| `block_number` | INTEGER | Ethereum block height |
| `block_timestamp` | BIGINT | Unix timestamp (seconds since 1970-01-01) |
| `gas_used` | BIGINT | (Optional) Total gas in block |
| `transaction_count` | INTEGER | (Optional) Number of transactions |

**Important:** Ensure timestamps are in **UTC** (seconds since Unix epoch, not milliseconds).

### Data Extraction Queries

Complete extraction SQL queries are provided in `data_queries.sql`:

- **Allium:** Complete query with all fields, optimized for large extraction
- **BigQuery:** Google's public Ethereum dataset format
- **Alternative sources:** Template for other data providers

### Data Quality

After extraction, the script performs automatic validation:

1. **Completeness:** Checks for missing or skipped blocks
2. **Monotonicity:** Verifies timestamps are non-decreasing
3. **Realism:** Flags timestamp anomalies (unrealistic dates, duplicates)
4. **Consistency:** Validates derived fields

If validation fails, the script will report errors and stop. Review the data source.

---

## Econometric Specifications

### Overview

The paper estimates 5 main regression specifications:

| Model | Specification | Purpose | Reference |
|-------|---------------|---------|-----------|
| **1.1** | `ElapsedTime = β0 + β1*BlockHeight + ε` | Linear baseline (pre/post-Merge) | `table2_ols_baseline.csv` |
| **1.2** | `TBB = α + β1*PostMerge + γ*Trend + ε` | RDD discontinuity at Merge | `table3_rdd_merge_effect.csv` |
| **1.3** | Distributional analysis | Summary statistics and quantiles | `table4_distribution_analysis.csv` |
| **1.4** | Slot skip patterns | Skip rates, autocorrelation | `table5_skip_analysis.csv` |
| **1.5** | Stratified comparison | Early vs. Stable PoS | `table6_early_vs_stable_pos.csv` |

Full specifications are in `econometric_spec.md`.

### Standard Errors

- **Model 1.1:** HC1 (heteroskedasticity-robust) standard errors
- **Model 1.2:** Newey-West HAC with 40-lag truncation (for autocorrelation robustness)
- **All models:** Report both OLS and robust SEs for comparison

### Interpretation

See **Interpretation Guidance** (Section 8.2 of `econometric_spec.md`) for expected findings and how to interpret results.

---

## Output Map: Paper Tables and Figures

### Tables in Paper ↔ Replication Output

| Paper | Section | Content | Output File |
|-------|---------|---------|-------------|
| Table 1 | Results | Summary statistics (N, mean, std, quantiles by period) | `table1_summary_stats.csv` |
| Table 2 | Results | OLS baseline (pre/post-Merge slopes, SEs, R²) | `table2_ols_baseline.csv` |
| Table 3 | Results | RDD merge effect (discontinuity, trend, F-test) | `table3_rdd_merge_effect.csv` |
| Table 4 | Results | TBB distribution (mean, std, quantiles by period) | `table4_distribution_analysis.csv` |
| Table 5 | Results | Skip analysis (skip rates, autocorrelation by period) | `table5_skip_analysis.csv` |
| Table 6 | Results | Early vs. Stable PoS (mean comparison, t-test) | `table6_early_vs_stable_pos.csv` |
| A1 | Appendix | Diagnostic tests (RESET, BP, DW, F-test) | `diagnostic_tests.csv` |

### Figures in Paper ↔ Replication Output

| Paper | Section | Content | Output File |
|-------|---------|---------|-------------|
| Figure 1 | Results | Elapsed time vs. block height (3 panels: PoW, Early PoS, Stable PoS) | `figure1_scatter_by_period.png` |
| Figure 2 | Results | Regression discontinuity at Merge (with trend lines) | `figure2_rdd_discontinuity.png` |
| Figure 3 | Results | TBB density distributions by period (3 panels) | `figure3_tbb_distributions.png` |
| Figure 4 | Results | Skip rate trends over time (rolling window) | `figure4_skip_rates.png` |
| Figure 5 | Results | Early vs. Stable PoS comparison (histogram + box plot) | `figure5_early_vs_stable.png` |

---

## Audit Trail and Reproducibility

### Version Control

All analysis code is tracked:

- **Code:** `replication/estimation.py` (self-contained Python script)
- **Metadata:** Paper ID, research stage, timestamps
- **Data provenance:** Data extraction date, source, version recorded in output

### Audit Log

For each run, record:

```
Date: YYYY-MM-DD HH:MM:SS UTC
Data source: [BigQuery / Allium / other]
Data extracted: YYYY-MM-DD
Blocks analyzed: [min_block] to [max_block]
Python version: [version]
Package versions: [statsmodels version], [pandas version]
Output location: replication/output/
```

### Reproduction Checklist

- [ ] Python 3.8+ installed
- [ ] All packages installed (`pip install -r requirements.txt`)
- [ ] Block data extracted to `data/ethereum_blocks.csv` or `.parquet`
- [ ] Data validation passed (script should confirm)
- [ ] Script runs without errors (`python replication/estimation.py`)
- [ ] All output files generated in `replication/output/`
- [ ] Results match paper tables and figures

---

## Data Extraction Guide

### Step 1: Choose Data Source

Pick one of the recommended sources based on your access and budget:

#### Google BigQuery (Free tier available)

**Pros:** Public dataset, free up to 1 TB/month, easy SQL  
**Cons:** Requires Google Cloud account

1. Go to https://console.cloud.google.com/
2. Enable BigQuery API
3. Run the query in `data_queries.sql` (Allium section, adapted to BigQuery)
4. Export results to Cloud Storage or download as CSV

#### Allium Data (Recommended for production)

**Pros:** Optimized for blockchain data, cross-chain, real-time updates  
**Cons:** Enterprise pricing (contact for free trial)

1. Sign up: https://www.allium.so/
2. Query editor: Use SQL from `data_queries.sql`
3. Select output format: CSV or Parquet
4. Schedule or run one-off extraction

#### Flipside Crypto (Alternative)

**Pros:** Free tier available, user-friendly SQL editor  
**Cons:** Rate limits on free tier

1. Sign up: https://flipsidecrypto.xyz/
2. Query Ethereum tables
3. Export results

### Step 2: Format Data

Ensure extracted data is saved as:

```
data/ethereum_blocks.csv
```

or:

```
data/ethereum_blocks.parquet
```

Required columns (case-sensitive):
- `block_number`
- `block_timestamp`

Example CSV header:
```
block_number,block_timestamp,gas_used,transaction_count
15537394,1663340827,18500000,145
15537395,1663340839,21000000,202
...
```

### Step 3: Validate Data

The script validates automatically, but you can pre-check:

```python
import pandas as pd

df = pd.read_csv('data/ethereum_blocks.csv')

# Check shape
print(df.shape)  # Should be millions of rows

# Check columns
print(df.columns.tolist())

# Check data types
print(df.dtypes)

# Check ranges
print(f"Block range: {df['block_number'].min()} to {df['block_number'].max()}")
print(f"Timestamp range: {df['block_timestamp'].min()} to {df['block_timestamp'].max()}")

# Check for nulls
print(df.isnull().sum())

# Ensure no duplicates
assert df['block_number'].is_unique, "Duplicate blocks found!"
```

---

## Troubleshooting

### Error: "Block data not found"

**Solution:** Extract and save data to `data/ethereum_blocks.csv` or `.parquet` (see Data Extraction Guide above).

### Error: "Data must contain columns: ['block_number', 'block_timestamp']"

**Solution:** Ensure CSV/Parquet has correct column names (case-sensitive, lowercase).

### Error: "Timestamp monotonicity check failed"

**Solution:** Data may contain reorgs or out-of-order records. Check data source for completeness.

### Script runs slowly

**Solution:**
1. Ensure adequate RAM (8+ GB)
2. Consider subsetting data for testing (e.g., first 100,000 blocks)
3. Use Parquet format (faster than CSV) if available

### Figures not generated

**Solution:** Check `replication/output/` directory permissions. Ensure matplotlib can write PNG files.

### Results differ from paper

**Possible causes:**
1. Different data extraction date (blocks after paper submission)
2. Data quality issues (missing blocks, timestamp errors)
3. Different software versions (see requirements.txt)

**Action:** Report discrepancies with data extraction date and software versions.

---

## Customization and Extension

### Running Specific Analyses

To run only certain analyses, modify `replication/estimation.py`:

```python
# Comment out specific sections in main()
# e.g., to skip RDD analysis:
# rdd_results = estimate_rdd_merge_effect(df)  # <- Comment out
```

### Subsetting Data

For testing, limit the data in `load_ethereum_blocks()`:

```python
# Add to load_ethereum_blocks():
# df = df[df['block_number'] <= 16000000]  # First 500K blocks post-Merge
```

### Adding Variables

Add new analysis variables in `prepare_variables()`:

```python
# Example: cumulative transaction volume
df['cumulative_transactions'] = df['transaction_count'].cumsum()
```

### Extending Analysis

Add new regression specifications in separate functions following the pattern of `estimate_ols_baseline()`.

---

## References and Documentation

### Core Documentation

- **`econometric_spec.md`** — Full econometric specifications, identification strategy, hypothesis tests
- **`data_dictionary.json`** — Schema, data quality checks, extraction strategies
- **`identification_strategy.md`** — Causal inference framework, identification assumptions
- **`paper_draft.tex`** — Full paper manuscript (LaTeX)

### Data Sources

- **Ethereum Specification:** https://ethereum.org/en/developers/docs/
- **Beacon Chain Spec:** https://github.com/ethereum/consensus-specs
- **BigQuery Ethereum Dataset:** https://cloud.google.com/bigquery/public-data#ethereum

### Literature

Key references cited in the paper:

1. Buterin, V., et al. (2020). "Combining GHOST and Casper." *arXiv preprint*.
2. Ethereum 2.0 Specification. https://github.com/ethereum/consensus-specs
3. Lamport, L., Shostak, R., & Pease, M. (1982). "The Byzantine Generals Problem." *ACM Transactions on Programming Languages and Systems*.

---

## Contact and Support

For questions about this replication package:

1. Check the **Troubleshooting** section above
2. Review `econometric_spec.md` for methodology details
3. Consult `data_dictionary.json` for data schema questions
4. Open an issue or contact the authors

---

## Citation

If you use this replication package, please cite:

```bibtex
@article{ethereum_timing_2025,
  title={Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge},
  author={[Anonymous]},
  journal={[To be determined]},
  year={2025},
  note={Paper ID: 1f256351-d253-47cf-9fcf-a745fc7fe08f}
}
```

---

## License

This replication package is provided under the [MIT License](LICENSE). 

Ethereum block data is public domain (no copyright).

---

## Appendix: Quick Reference

### Key Constants

| Parameter | Value | Note |
|-----------|-------|------|
| Genesis Timestamp | 1438269973 | 2015-07-30 03:26:13 UTC |
| Merge Block | 15537393 | 2022-09-15 13:42:07 UTC |
| Merge Timestamp | 1663340827 | 2022-09-15 13:42:07 UTC |
| Early PoS End | ~1682121600 | ~2023-04-22 (Shanghai upgrade) |
| Target Block Time (PoW) | 15 seconds | Pre-Merge |
| Target Block Time (PoS) | 12 seconds | Post-Merge |

### Common Commands

```bash
# Run replication
python replication/estimation.py

# View results
head replication/output/table1_summary_stats.csv

# Display figure
open replication/output/figure1_scatter_by_period.png  # macOS
# or
display replication/output/figure1_scatter_by_period.png  # Linux
# or
start replication/output/figure1_scatter_by_period.png  # Windows

# Check data
python -c "import pandas as pd; df = pd.read_csv('data/ethereum_blocks.csv'); print(df.info())"
```

---

**Document Version:** 1.0  
**Last Updated:** 2025  
**Status:** Ready for Replication  
