# Data Description

## Data Sources

This pipeline uses synthetic panel data generated for pipeline validation. The intended production source (`test` table in the research database) was unavailable; the synthetic data generator produces a balanced DiD panel that mirrors the target structure.

**Source**: `generate_synthetic_data()` in `data_extract.py` (seed=42 for reproducibility).

## Sample Construction

The synthetic panel comprises 200 cross-sectional units observed over 5 time periods (t=0,...,4), yielding 1,000 unit-period observations. Treatment is assigned at the unit level: units with `unit_id >= 100` constitute the treatment group (50% of units). The treatment activates at period 3 (`post = 1` for t >= 3).

No observations are dropped during cleaning. Winsorization is applied to the outcome variable at the 1st and 99th percentiles.

## Variable Definitions

| Variable | Type | Description |
|----------|------|-------------|
| `unit_id` | integer | Cross-sectional unit identifier (0–199) |
| `time` | integer | Time period (0–4) |
| `treated` | binary | Treatment group indicator: 1 if unit_id >= 100 |
| `post` | binary | Post-treatment indicator: 1 if time >= 3 |
| `treatment` | binary | DiD interaction: `treated` × `post` |
| `x` | continuous | Covariate, N(5, 4) + 0.3 × unit fixed effect |
| `y` | continuous | Outcome: unit FE + time FE + 2.5 × treatment + N(0,1) |
| `y_winsorized` | continuous | `y` winsorized at 1st/99th percentiles |
| `log_x` | continuous | log(x − min(x) + 1) |

The true treatment effect (δ) is 2.5.

## Summary Statistics

| Variable | N | Mean | SD | Min | Max | Missing % |
|----------|---|------|----|-----|-----|-----------|
| x | 1,000 | 5.05 | 1.99 | −0.98 | 11.38 | 0.0 |
| y | 1,000 | 1.51 | 2.09 | −3.16 | 8.78 | 0.0 |
| treated | 1,000 | 0.50 | 0.50 | 0 | 1 | 0.0 |
| post | 1,000 | 0.40 | 0.49 | 0 | 1 | 0.0 |
| treatment | 1,000 | 0.20 | 0.40 | 0 | 1 | 0.0 |

The balanced panel has no missing values. Treatment and control groups are equal in size (100 units each). The post-treatment period covers 2 of 5 periods, so 40% of observations fall in the post period and 20% receive treatment.

## Data Limitations

1. **Synthetic data**: This dataset is generated for pipeline validation only. Production runs must connect to the research database.
2. **No real covariates**: The single covariate `x` is randomly generated and does not represent a meaningful economic variable.
3. **Known DGP**: The true treatment effect is known (δ = 2.5), which is useful for validation but not representative of empirical research.

## CSV Files Produced

| File | Location | Contents |
|------|----------|----------|
| `raw_extract.csv` | `raw/` | Raw synthetic panel (7 columns, 1,000 rows) |
| `panel_data.csv` | `clean/` | Analysis-ready panel with constructed variables (9 columns, 1,000 rows) |
