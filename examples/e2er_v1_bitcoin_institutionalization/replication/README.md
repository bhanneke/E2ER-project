# Replication Package — Institutionalization of Bitcoin

## Data Sources
- See data_selection.sql

## Files
- `data/btc_trad_rv_ratio.csv` — Sample data
- `data/btc_trad_rv_ratio_by_period.csv` — Sample data
- `data/estimation_sample_panel.csv` — Sample data
- `data/event_study_windows.csv` — Sample data
- `data/monthly_panel.csv` — Sample data
- `data/return_correlations.csv` — Sample data
- `data/scm_pretreatment_btc_spot_etf_approval.csv` — Sample data
- `data/scm_pretreatment_cme_futures_launch.csv` — Sample data
- `data/scm_pretreatment_eth_spot_etf_approval.csv` — Sample data
- `data/scm_pretreatment_grayscale_ruling.csv` — Sample data
- `data/summary_statistics.csv` — Sample data
- `data/volatility_by_period.csv` — Sample data
- `data/volatility_by_period_3way.csv` — Sample data
- `data_selection.sql` — SQL queries for data extraction
- `estimation.py` — Main econometric specification (supports --from-csv)
- `fetch_and_build.py` — Public data fetching script
- `figures/fig1_event_study.pdf` — Generated figure
- `figures/fig2_rv_convergence.pdf` — Generated figure
- `figures/fig3_rambachan_roth.pdf` — Generated figure
- `figures/fig4_power_curve.pdf` — Generated figure
- `figures/fig5_permutation.pdf` — Generated figure
- `figures/fig6_rv_comparison.pdf` — Generated figure

## Reproduction Steps

1. Set up a Python environment: `pip install -r requirements.txt`
2. Configure database access (see `data_selection.sql` for required tables)
3. Run data extraction: `psql $DATABASE_URL -f data_selection.sql`
4. Run estimation: `DATABASE_URL=$DATABASE_URL python estimation.py`
   - Or from CSV: `python estimation.py --from-csv` (uses estimation_sample.csv)
5. Run robustness checks: `python robustness.py`
6. Generate figures: `python figures.py`
