-- ============================================================
-- Data Queries for: Sell in May and Go Away — NFT Seasonality
-- Research Design Run 08
-- ============================================================
-- All queries target nft_data.trades (PostgreSQL, ~35.8M rows)
-- Key columns: block_timestamp, price (ETH), price_usd, platform_name,
--   nft_address, project_name, tokenid, buyer_address, seller_address,
--   currency_symbol, total_fees_usd, tx_fee_usd
-- Data coverage: June 2017 — January 2023
-- Analysis sample (USD-priced): May 2020 — January 2023
-- ============================================================

-- 0. Verify sample period and total coverage
SELECT
    MIN(block_timestamp) AS earliest_trade,
    MAX(block_timestamp) AS latest_trade,
    COUNT(*) AS total_trades,
    COUNT(DISTINCT platform_name) AS n_platforms,
    COUNT(DISTINCT nft_address) AS n_collections,
    COUNT(DISTINCT buyer_address) AS n_buyers,
    COUNT(DISTINCT seller_address) AS n_sellers
FROM nft_data.trades
WHERE price_usd > 0;

-- 1. Summary statistics by platform and year
SELECT
    platform_name,
    EXTRACT(YEAR FROM block_timestamp) AS year,
    COUNT(*) AS trade_count,
    SUM(price_usd) AS total_volume_usd,
    AVG(price_usd) AS mean_price_usd,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
    STDDEV(price_usd) AS sd_price_usd,
    MIN(price_usd) AS min_price_usd,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY price_usd) AS p99_price_usd,
    COUNT(DISTINCT nft_address) AS unique_collections,
    COUNT(DISTINCT buyer_address) AS unique_buyers,
    COUNT(DISTINCT seller_address) AS unique_sellers,
    SUM(total_fees_usd) AS total_fees_collected_usd,
    AVG(tx_fee_usd) AS avg_gas_cost_usd,
    -- Wash trade statistics
    COUNT(*) FILTER (WHERE LOWER(buyer_address) = LOWER(seller_address)) AS self_trade_count,
    ROUND(
        COUNT(*) FILTER (WHERE LOWER(buyer_address) = LOWER(seller_address))::numeric
        / NULLIF(COUNT(*), 0) * 100, 4
    ) AS self_trade_pct
FROM nft_data.trades
WHERE price_usd > 0
GROUP BY 1, 2
ORDER BY 2, 1;

-- 2. Monthly distribution of trades and volume (seasonality overview)
-- Used for: Figure 3 (fig:volume_seasonality)
SELECT
    EXTRACT(YEAR FROM block_timestamp) AS year,
    EXTRACT(MONTH FROM block_timestamp) AS month,
    COUNT(*) AS trade_count,
    SUM(price_usd) AS total_volume_usd,
    AVG(price_usd) AS mean_price_usd,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
    COUNT(DISTINCT nft_address) AS unique_collections,
    COUNT(DISTINCT buyer_address) AS unique_buyers,
    COUNT(DISTINCT seller_address) AS unique_sellers,
    CASE
        WHEN EXTRACT(MONTH FROM block_timestamp) BETWEEN 5 AND 10 THEN 'summer'
        ELSE 'winter'
    END AS halloween_season
FROM nft_data.trades
WHERE price_usd > 0
GROUP BY 1, 2
ORDER BY 1, 2;

-- 3a. Wash trade identification — self-trades (buyer = seller)
SELECT
    COUNT(*) AS self_trade_count,
    SUM(price_usd) AS self_trade_volume_usd,
    ROUND(COUNT(*)::numeric / (SELECT COUNT(*) FROM nft_data.trades WHERE price_usd > 0) * 100, 4) AS self_trade_pct
FROM nft_data.trades
WHERE price_usd > 0
  AND LOWER(buyer_address) = LOWER(seller_address);

-- 3b. Wash trade seasonality — monthly wash share by platform and Halloween season
SELECT
    platform_name,
    EXTRACT(YEAR FROM block_timestamp) AS year,
    EXTRACT(MONTH FROM block_timestamp) AS month,
    COUNT(*) FILTER (WHERE LOWER(buyer_address) = LOWER(seller_address)) AS wash_count,
    COUNT(*) AS total_count,
    ROUND(
        COUNT(*) FILTER (WHERE LOWER(buyer_address) = LOWER(seller_address))::numeric
        / NULLIF(COUNT(*), 0) * 100, 4
    ) AS wash_pct,
    CASE
        WHEN EXTRACT(MONTH FROM block_timestamp) BETWEEN 5 AND 10 THEN 'summer'
        ELSE 'winter'
    END AS halloween_season
FROM nft_data.trades
WHERE price_usd > 0
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- 3c. Circular trade detection — A sells to B, B sells back to A within 7 days on same NFT
WITH trade_pairs AS (
    SELECT
        t1.seller_address AS addr_a,
        t1.buyer_address AS addr_b,
        t1.nft_address,
        t1.tokenid,
        t1.block_timestamp AS sale_1_time,
        t2.block_timestamp AS sale_2_time,
        t2.block_timestamp - t1.block_timestamp AS time_gap
    FROM nft_data.trades t1
    JOIN nft_data.trades t2
        ON LOWER(t1.buyer_address) = LOWER(t2.seller_address)
        AND LOWER(t1.seller_address) = LOWER(t2.buyer_address)
        AND t1.nft_address = t2.nft_address
        AND t1.tokenid = t2.tokenid
        AND t2.block_timestamp > t1.block_timestamp
        AND t2.block_timestamp <= t1.block_timestamp + INTERVAL '7 days'
    WHERE t1.price_usd > 0 AND t2.price_usd > 0
      AND LOWER(t1.buyer_address) != LOWER(t1.seller_address)  -- exclude self-trades already counted
)
SELECT
    COUNT(*) AS circular_trade_pairs,
    COUNT(DISTINCT addr_a) AS unique_addresses_involved
FROM trade_pairs;

-- 4. Collection-level aggregation for tier classification
SELECT
    nft_address,
    project_name,
    COUNT(*) AS total_trades,
    SUM(price_usd) AS total_volume_usd,
    AVG(price_usd) AS mean_price_usd,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
    MIN(block_timestamp) AS first_trade,
    MAX(block_timestamp) AS last_trade,
    EXTRACT(EPOCH FROM MAX(block_timestamp) - MIN(block_timestamp)) / 86400 AS active_days,
    COUNT(DISTINCT buyer_address) AS unique_buyers,
    COUNT(DISTINCT seller_address) AS unique_sellers,
    COUNT(DISTINCT DATE(block_timestamp)) AS days_with_trades,
    -- Wash trade share
    COUNT(*) FILTER (WHERE LOWER(buyer_address) = LOWER(seller_address)) AS self_trade_count,
    ROUND(
        COUNT(*) FILTER (WHERE LOWER(buyer_address) = LOWER(seller_address))::numeric
        / NULLIF(COUNT(*), 0) * 100, 2
    ) AS self_trade_pct,
    -- Non-wash volume for tier classification
    SUM(price_usd) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) AS non_wash_volume_usd
FROM nft_data.trades
WHERE price_usd > 0
GROUP BY 1, 2
ORDER BY non_wash_volume_usd DESC;

-- 5. Daily portfolio return index — equal-weighted
-- Used for: Figure 1 (fig:monthly_returns), Figure 8 (fig:return_distributions),
--           Figure 4 (fig:day_of_week), Figure 7 (fig:power_curve)
WITH daily_collection_prices AS (
    SELECT
        DATE(block_timestamp) AS trade_date,
        nft_address,
        project_name,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS median_price_eth,
        COUNT(*) AS daily_trades,
        SUM(price_usd) AS daily_volume_usd
    FROM nft_data.trades
    WHERE price_usd > 0
      AND price > 0
      AND LOWER(buyer_address) != LOWER(seller_address)  -- exclude self-trades
    GROUP BY 1, 2, 3
    HAVING COUNT(*) >= 3  -- minimum trades for reliable median
)
SELECT
    trade_date,
    AVG(median_price_usd) AS ew_index_usd,
    AVG(median_price_eth) AS ew_index_eth,
    COUNT(DISTINCT nft_address) AS collections_in_index,
    SUM(daily_trades) AS total_trades,
    SUM(daily_volume_usd) AS total_volume_usd
FROM daily_collection_prices
GROUP BY 1
ORDER BY 1;

-- 6. Value-weighted daily index
WITH monthly_collection_volume AS (
    SELECT
        nft_address,
        DATE_TRUNC('month', block_timestamp) AS month,
        SUM(price_usd) AS monthly_volume_usd
    FROM nft_data.trades
    WHERE price_usd > 0
      AND LOWER(buyer_address) != LOWER(seller_address)
    GROUP BY 1, 2
),
daily_collection_prices AS (
    SELECT
        DATE(block_timestamp) AS trade_date,
        nft_address,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS median_price_eth,
        COUNT(*) AS daily_trades
    FROM nft_data.trades
    WHERE price_usd > 0
      AND price > 0
      AND LOWER(buyer_address) != LOWER(seller_address)
    GROUP BY 1, 2
    HAVING COUNT(*) >= 3
),
weighted_prices AS (
    SELECT
        d.trade_date,
        d.nft_address,
        d.median_price_usd,
        d.median_price_eth,
        COALESCE(v.monthly_volume_usd, 0) AS weight
    FROM daily_collection_prices d
    LEFT JOIN monthly_collection_volume v
        ON d.nft_address = v.nft_address
        AND DATE_TRUNC('month', d.trade_date) - INTERVAL '1 month' = v.month
)
SELECT
    trade_date,
    CASE
        WHEN SUM(weight) > 0 THEN SUM(median_price_usd * weight) / SUM(weight)
        ELSE AVG(median_price_usd)
    END AS vw_index_usd,
    CASE
        WHEN SUM(weight) > 0 THEN SUM(median_price_eth * weight) / SUM(weight)
        ELSE AVG(median_price_eth)
    END AS vw_index_eth,
    COUNT(DISTINCT nft_address) AS collections_in_index,
    SUM(weight) AS total_weight
FROM weighted_prices
GROUP BY 1
ORDER BY 1;

-- 7. Monthly aggregated return series with Halloween dummy
WITH daily_index AS (
    SELECT
        DATE(block_timestamp) AS trade_date,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS median_price_eth,
        COUNT(*) AS n_trades,
        SUM(price_usd) AS total_volume_usd
    FROM nft_data.trades
    WHERE price_usd > 0
      AND price > 0
      AND LOWER(buyer_address) != LOWER(seller_address)
    GROUP BY 1
),
monthly_agg AS (
    SELECT
        DATE_TRUNC('month', trade_date) AS month,
        AVG(median_price_usd) AS avg_median_price_usd,
        AVG(median_price_eth) AS avg_median_price_eth,
        SUM(n_trades) AS monthly_trades,
        SUM(total_volume_usd) AS monthly_volume_usd,
        COUNT(DISTINCT trade_date) AS trading_days
    FROM daily_index
    GROUP BY 1
)
SELECT
    month,
    avg_median_price_usd,
    avg_median_price_eth,
    LN(avg_median_price_usd / LAG(avg_median_price_usd) OVER (ORDER BY month)) AS log_return_usd,
    LN(avg_median_price_eth / LAG(avg_median_price_eth) OVER (ORDER BY month)) AS log_return_eth,
    monthly_trades,
    monthly_volume_usd,
    trading_days,
    CASE
        WHEN EXTRACT(MONTH FROM month) BETWEEN 5 AND 10 THEN 0  -- Summer
        ELSE 1  -- Winter
    END AS halloween_dummy,
    EXTRACT(MONTH FROM month) AS calendar_month,
    EXTRACT(YEAR FROM month) AS calendar_year
FROM monthly_agg
ORDER BY month;

-- 8. Repeat-sale pairs for blue-chip index
WITH ranked_sales AS (
    SELECT
        nft_address,
        project_name,
        tokenid,
        block_timestamp,
        price_usd,
        price AS price_eth,
        currency_symbol,
        buyer_address,
        seller_address,
        platform_name,
        ROW_NUMBER() OVER (
            PARTITION BY nft_address, tokenid
            ORDER BY block_timestamp
        ) AS sale_seq
    FROM nft_data.trades
    WHERE price_usd > 0
      AND price > 0
      AND LOWER(buyer_address) != LOWER(seller_address)
)
SELECT
    s1.nft_address,
    s1.project_name,
    s1.tokenid,
    s1.block_timestamp AS buy_timestamp,
    s2.block_timestamp AS sell_timestamp,
    s1.price_usd AS buy_price_usd,
    s2.price_usd AS sell_price_usd,
    s1.price_eth AS buy_price_eth,
    s2.price_eth AS sell_price_eth,
    LN(s2.price_usd / NULLIF(s1.price_usd, 0)) AS log_return_usd,
    LN(s2.price_eth / NULLIF(s1.price_eth, 0)) AS log_return_eth,
    s2.block_timestamp - s1.block_timestamp AS holding_period,
    EXTRACT(EPOCH FROM s2.block_timestamp - s1.block_timestamp) / 86400 AS holding_days,
    DATE(s2.block_timestamp) AS sale_date,
    EXTRACT(MONTH FROM s2.block_timestamp) AS sale_month,
    EXTRACT(YEAR FROM s2.block_timestamp) AS sale_year,
    CASE
        WHEN EXTRACT(MONTH FROM s2.block_timestamp) BETWEEN 5 AND 10 THEN 0
        ELSE 1
    END AS halloween_dummy_at_sale,
    s2.platform_name AS sale_platform
FROM ranked_sales s1
JOIN ranked_sales s2
    ON s1.nft_address = s2.nft_address
    AND s1.tokenid = s2.tokenid
    AND s2.sale_seq = s1.sale_seq + 1
WHERE s1.price_usd > 0 AND s2.price_usd > 0
  AND s1.price_eth > 0 AND s2.price_eth > 0
ORDER BY s2.block_timestamp;

-- 9. Platform entry timeline
SELECT
    platform_name,
    MIN(block_timestamp) AS first_trade,
    MAX(block_timestamp) AS last_trade,
    COUNT(*) AS total_trades,
    SUM(price_usd) AS total_volume_usd,
    COUNT(DISTINCT nft_address) AS unique_collections
FROM nft_data.trades
WHERE price_usd > 0
GROUP BY 1
ORDER BY first_trade;

-- 10. Monthly returns by platform (for platform-level Halloween analysis)
WITH platform_daily AS (
    SELECT
        DATE(block_timestamp) AS trade_date,
        platform_name,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) AS median_price_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS median_price_eth,
        COUNT(*) AS n_trades,
        SUM(price_usd) AS volume_usd
    FROM nft_data.trades
    WHERE price_usd > 0
      AND price > 0
      AND LOWER(buyer_address) != LOWER(seller_address)
    GROUP BY 1, 2
    HAVING COUNT(*) >= 5
),
platform_monthly AS (
    SELECT
        platform_name,
        DATE_TRUNC('month', trade_date) AS month,
        AVG(median_price_usd) AS avg_median_price_usd,
        AVG(median_price_eth) AS avg_median_price_eth,
        SUM(n_trades) AS monthly_trades,
        SUM(volume_usd) AS monthly_volume_usd
    FROM platform_daily
    GROUP BY 1, 2
)
SELECT
    platform_name,
    month,
    avg_median_price_usd,
    avg_median_price_eth,
    LN(avg_median_price_usd / LAG(avg_median_price_usd) OVER (PARTITION BY platform_name ORDER BY month)) AS log_return_usd,
    LN(avg_median_price_eth / LAG(avg_median_price_eth) OVER (PARTITION BY platform_name ORDER BY month)) AS log_return_eth,
    monthly_trades,
    monthly_volume_usd,
    CASE
        WHEN EXTRACT(MONTH FROM month) BETWEEN 5 AND 10 THEN 0
        ELSE 1
    END AS halloween_dummy
FROM platform_monthly
ORDER BY platform_name, month;

-- 11. Collection tier assignment
WITH collection_ranking AS (
    SELECT
        nft_address,
        project_name,
        SUM(price_usd) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) AS non_wash_volume_usd,
        COUNT(*) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) AS non_wash_trades,
        RANK() OVER (
            ORDER BY SUM(price_usd) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) DESC
        ) AS volume_rank
    FROM nft_data.trades
    WHERE price_usd > 0
    GROUP BY 1, 2
)
SELECT
    nft_address,
    project_name,
    non_wash_volume_usd,
    non_wash_trades,
    volume_rank,
    CASE
        WHEN volume_rank <= 20 THEN 'blue_chip'
        WHEN volume_rank <= 200 THEN 'mid_tier'
        ELSE 'long_tail'
    END AS collection_tier
FROM collection_ranking
ORDER BY volume_rank
LIMIT 500;

-- 12. Monthly returns by collection tier (for tier-level Halloween analysis)
WITH collection_tier_map AS (
    SELECT
        nft_address,
        RANK() OVER (
            ORDER BY SUM(price_usd) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) DESC
        ) AS volume_rank,
        CASE
            WHEN RANK() OVER (ORDER BY SUM(price_usd) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) DESC) <= 20 THEN 'blue_chip'
            WHEN RANK() OVER (ORDER BY SUM(price_usd) FILTER (WHERE LOWER(buyer_address) != LOWER(seller_address)) DESC) <= 200 THEN 'mid_tier'
            ELSE 'long_tail'
        END AS collection_tier
    FROM nft_data.trades
    WHERE price_usd > 0
    GROUP BY 1
),
tier_daily AS (
    SELECT
        DATE(t.block_timestamp) AS trade_date,
        ct.collection_tier,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.price_usd) AS median_price_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.price) AS median_price_eth,
        COUNT(*) AS n_trades,
        SUM(t.price_usd) AS volume_usd
    FROM nft_data.trades t
    JOIN collection_tier_map ct ON t.nft_address = ct.nft_address
    WHERE t.price_usd > 0
      AND t.price > 0
      AND LOWER(t.buyer_address) != LOWER(t.seller_address)
    GROUP BY 1, 2
    HAVING COUNT(*) >= 3
),
tier_monthly AS (
    SELECT
        collection_tier,
        DATE_TRUNC('month', trade_date) AS month,
        AVG(median_price_usd) AS avg_median_price_usd,
        AVG(median_price_eth) AS avg_median_price_eth,
        SUM(n_trades) AS monthly_trades,
        SUM(volume_usd) AS monthly_volume_usd
    FROM tier_daily
    GROUP BY 1, 2
)
SELECT
    collection_tier,
    month,
    avg_median_price_usd,
    avg_median_price_eth,
    LN(avg_median_price_usd / LAG(avg_median_price_usd) OVER (PARTITION BY collection_tier ORDER BY month)) AS log_return_usd,
    LN(avg_median_price_eth / LAG(avg_median_price_eth) OVER (PARTITION BY collection_tier ORDER BY month)) AS log_return_eth,
    monthly_trades,
    monthly_volume_usd,
    CASE
        WHEN EXTRACT(MONTH FROM month) BETWEEN 5 AND 10 THEN 0
        ELSE 1
    END AS halloween_dummy
FROM tier_monthly
ORDER BY collection_tier, month;
