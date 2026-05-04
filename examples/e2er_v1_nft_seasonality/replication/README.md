# Replication Package — Sell in May and Go Away: Seasonality in NFT Markets

## Data Sources
- {'name': 'nft_data.trades', 'columns': ['block_timestamp', 'price_usd', 'platform_name', 'nft_address', 'project_name', 'buyer_address', 'seller_address'], 'description': 'Local PostgreSQL table with 35.8M NFT trades (2017-2023) across OpenSea, LooksRare, Blur, X2Y2, Sudoswap, and other platforms'}
- {'name': 'raw.log (friend.tech)', 'columns': ['block_timestamp', 'price', 'buyer', 'seller'], 'description': '8.1M friend.tech trades for supplementary analysis of social token seasonality'}
- {'name': 'ETH price data', 'columns': ['date', 'price_usd', 'volume_usd'], 'description': 'Daily ETH/USD prices for the sample period, sourced from CoinGecko or the local database if available, for constructing ETH-denominated returns and crypto market controls'}

## Files
- `data/daily_merged_index.csv` — Sample data
- `data/eth_daily_prices.csv` — Sample data
- `data/monthly_aggregation.csv` — Sample data
- `data_selection.sql` — SQL queries for data extraction
- `estimation.py` — Main econometric specification (supports --from-csv)
- `fetch_eth_prices.py` — Public data fetching script
- `figures/fig1_coefficient_comparison.pdf` — Generated figure
- `figures/fig2_seasonal_distributions.pdf` — Generated figure
- `figures/fig3_rolling_halloween.pdf` — Generated figure
- `figures/fig4_year_by_year.pdf` — Generated figure
- `figures/fig5_power_curve.pdf` — Generated figure
- `figures/fig6_bootstrap_distribution.pdf` — Generated figure
- `figures/fig7_calendar_effects.pdf` — Generated figure

## Reproduction Steps

1. Set up a Python environment: `pip install -r requirements.txt`
2. Configure database access (see `data_selection.sql` for required tables)
3. Run data extraction: `psql $DATABASE_URL -f data_selection.sql`
4. Run estimation: `DATABASE_URL=$DATABASE_URL python estimation.py`
   - Or from CSV: `python estimation.py --from-csv` (uses estimation_sample.csv)
5. Run robustness checks: `python robustness.py`
6. Generate figures: `python figures.py`
