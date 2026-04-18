-- ============================================================================
-- Data Queries — Institutionalization of Bitcoin
-- Run 16
-- ============================================================================
-- Execute against: postgresql://research_user:...@host.docker.internal:5435/research_data
-- Pre-requisite: SET search_path TO research_data, raw, stage, analytics, nft_data, public;

SET search_path TO research_data, raw, stage, analytics, nft_data, public;

-- ---------------------------------------------------------------------------
-- 1. Yahoo Finance macro data: BTC, ETH, SOL, SPY, GLD daily OHLCV
-- ---------------------------------------------------------------------------
SELECT ticker, date, open, high, low, close, volume, adj_close
FROM yf_macro
WHERE ticker IN ('BTC-USD', 'ETH-USD', 'SOL-USD', 'SPY', 'GLD')
ORDER BY ticker, date;

-- ---------------------------------------------------------------------------
-- 2. CoinGecko BTC daily (longer history back to 2013)
-- ---------------------------------------------------------------------------
SELECT date, price AS close, total_vol AS volume, market_cap
FROM ts.btc
ORDER BY date;

-- ---------------------------------------------------------------------------
-- 3. SPY ETF daily OHLCV
-- ---------------------------------------------------------------------------
SELECT date, open, high, low, close, volume, adj_close
FROM ts.spy
ORDER BY date;

-- ---------------------------------------------------------------------------
-- 4. CBOE VIX daily close
-- ---------------------------------------------------------------------------
SELECT date, close AS vix
FROM ts.vix
ORDER BY date;

-- ---------------------------------------------------------------------------
-- 5. US Dollar Index (DXY) daily
-- ---------------------------------------------------------------------------
SELECT date, price AS dxy
FROM ts.us_dollar_index
ORDER BY date;

-- ---------------------------------------------------------------------------
-- 6. Federal Funds Effective Rate daily
-- ---------------------------------------------------------------------------
SELECT date, value AS fed_funds_rate
FROM ts.fed_funds_rate
ORDER BY date;

-- ---------------------------------------------------------------------------
-- 7. FRED series: Treasury yields, financial conditions (supplementary)
-- ---------------------------------------------------------------------------
SELECT series_id, date, value
FROM fred_series
WHERE series_id IN ('DGS10', 'DGS2', 'T10Y2Y', 'VIXCLS', 'BAMLH0A0HYM2')
ORDER BY series_id, date;

-- ---------------------------------------------------------------------------
-- 8. Multi-crypto daily prices (CoinGecko-sourced table, limited coverage)
-- ---------------------------------------------------------------------------
SELECT date, "BTC", "ETH", "LTC", "XRP", "DOGE", "DASH", "ETC", "ZEC", "BCH", "BSV"
FROM ts.cryptos_price
ORDER BY date;

-- ---------------------------------------------------------------------------
-- 9. ECB rates (supplementary macro controls)
-- ---------------------------------------------------------------------------
SELECT series_key, date, value
FROM ecb_series
ORDER BY series_key, date;

-- ---------------------------------------------------------------------------
-- NOTES
-- ---------------------------------------------------------------------------
-- * Altcoin daily prices (DOGE, XRP, ADA, AVAX, LINK, DOT, UNI, LTC, MATIC)
--   not available in the research DB for the full sample period. Fetched via
--   CoinGecko API (/coins/{id}/market_chart/range) through the internal fetcher
--   service in prior pipeline runs, then carried forward in the estimation panel.
--
-- * VIX and DXY tables end circa April 2023. Later values are forward-filled
--   from Yahoo Finance data fetched in earlier pipeline runs.
--
-- * LTC CoinGecko data ends 2023-03-19 (API returns HTTP 401 for range queries
--   on the free tier). MATIC/POL data ends 2025-10-18.
--
-- * All crypto prices are denominated in USD. Volume is in USD-equivalent units
--   for CoinGecko-sourced data and in share units for Yahoo Finance.
