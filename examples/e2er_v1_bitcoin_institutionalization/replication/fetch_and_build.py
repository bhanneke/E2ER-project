"""
Data Stage — Run 16
====================
Build the estimation panel for "Institutionalization of Bitcoin."

Sources:
  - yf_macro  (BTC, ETH, SOL from Yahoo Finance)
  - ts.btc        (BTC from CoinGecko, longer history)
  - ts.spy / ts.vix / ts.us_dollar_index (traditional)
  - CoinGecko API via fetcher (altcoins not in DB)
  - Yahoo Finance API via fetcher (GLD)
  - Previous run panel (run_15) as base for altcoin histories

Panel assets (12 crypto + 2 traditional benchmarks):
  Crypto:  BTC, ETH, SOL, DOGE, XRP, ADA, AVAX, LINK, DOT, UNI, LTC, MATIC
  Trad:    SPY, GLD

Realized volatility windows: 30d (primary), 21d, 60d, 90d
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from io import StringIO

import numpy as np
import pandas as pd
import psycopg

OUT = "/app/artifacts/d860d9fe-f100-4153-963e-c783681917cf/data/run_16"
PREV_PANEL = "/app/artifacts/d860d9fe-f100-4153-963e-c783681917cf/data/run_15/estimation_sample_panel.csv"
CONN_STR = "postgresql://research_user:4887b13abdd49846b19e1075adee4708@host.docker.internal:5435/research_data"

CRYPTO_TICKERS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "LINK", "DOT", "UNI", "LTC", "MATIC"]
TRAD_TICKERS = ["SPY", "GLD"]
ALL_TICKERS = CRYPTO_TICKERS + TRAD_TICKERS

# ---------------------------------------------------------------------------
# Fetcher helper
# ---------------------------------------------------------------------------
def fetch_url(url: str) -> str:
    req = urllib.request.Request(
        "http://fetcher:8000/fetch",
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if result.get("status") == "ok":
        return result["content"]
    raise RuntimeError(result.get("error", "fetch failed"))


# ---------------------------------------------------------------------------
# CoinGecko daily price fetcher
# ---------------------------------------------------------------------------
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "MATIC": "matic-network",
}


def fetch_coingecko_range(cg_id, vs="usd", from_ts=None, to_ts=None):
    """Fetch daily close + volume from CoinGecko market_chart/range endpoint."""
    if from_ts is None:
        from_ts = int(datetime(2014, 1, 1).timestamp())
    if to_ts is None:
        to_ts = int(datetime(2026, 3, 18).timestamp())
    url = (
        f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart/range"
        f"?vs_currency={vs}&from={from_ts}&to={to_ts}"
    )
    raw = fetch_url(url)
    data = json.loads(raw)
    prices = data.get("prices", [])
    volumes = data.get("total_volumes", [])
    rows = []
    for p, v in zip(prices, volumes):
        ts_ms = p[0]
        dt = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        rows.append({"date": dt, "close": p[1], "volume": v[1]})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["date"], keep="last")
    return df.sort_values("date").reset_index(drop=True)


def fetch_yahoo_chart(ticker, period1, period2):
    """Fetch daily OHLCV from Yahoo Finance v8 chart API."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    raw = fetch_url(url)
    data = json.loads(raw)
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, ts in enumerate(timestamps):
        dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        rows.append({
            "date": dt,
            "open": quote["open"][i],
            "high": quote["high"][i],
            "low": quote["low"][i],
            "close": quote["close"][i],
            "volume": quote["volume"][i],
            "adj_close": adj[i],
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["close"])
    return df.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Load from database
# ---------------------------------------------------------------------------
def load_db_data():
    """Load all available data from the PostgreSQL research database."""
    conn = psycopg.connect(CONN_STR, autocommit=True)
    conn.execute("SET search_path TO research_data, raw, stage, analytics, nft_data, public")

    # yf_macro: BTC, ETH, SOL, SPY, GLD
    yf = pd.read_sql("""
        SELECT ticker, date, open, high, low, close, volume, adj_close
        FROM yf_macro
        WHERE ticker IN ('BTC-USD','ETH-USD','SOL-USD','SPY','GLD')
        ORDER BY ticker, date
    """, conn)
    yf["ticker"] = yf["ticker"].str.replace("-USD", "")
    yf["date"] = pd.to_datetime(yf["date"])

    # ts.btc for longer BTC history
    btc_cg = pd.read_sql("""
        SELECT date, price as close, total_vol as volume, market_cap
        FROM ts.btc ORDER BY date
    """, conn)
    btc_cg["date"] = pd.to_datetime(btc_cg["date"])
    btc_cg["ticker"] = "BTC"

    # ts.spy
    spy = pd.read_sql("""
        SELECT date, open, high, low, close, volume, adj_close
        FROM ts.spy ORDER BY date
    """, conn)
    spy["date"] = pd.to_datetime(spy["date"])
    spy["ticker"] = "SPY"

    # VIX
    vix = pd.read_sql("""
        SELECT date, close as vix FROM ts.vix ORDER BY date
    """, conn)
    vix["date"] = pd.to_datetime(vix["date"])

    # DXY
    dxy = pd.read_sql("""
        SELECT date, price as dxy FROM ts.us_dollar_index ORDER BY date
    """, conn)
    dxy["date"] = pd.to_datetime(dxy["date"])

    # Fed funds rate
    ffr = pd.read_sql("""
        SELECT date, value as fed_funds_rate FROM ts.fed_funds_rate ORDER BY date
    """, conn)
    ffr["date"] = pd.to_datetime(ffr["date"])

    conn.close()
    return yf, btc_cg, spy, vix, dxy, ffr


# ---------------------------------------------------------------------------
# Build unified daily price panel
# ---------------------------------------------------------------------------
def build_price_panel():
    """Assemble daily close prices and volumes for all 14 assets."""
    print("Loading database data...")
    yf, btc_cg, spy_db, vix_db, dxy_db, ffr_db = load_db_data()

    # Use previous run panel as base for all asset price histories
    print(f"Loading previous panel from {PREV_PANEL}...")
    prev_panel = pd.read_csv(PREV_PANEL, parse_dates=["date"])

    # Extract close and volume per ticker from the previous panel
    prev_prices = prev_panel[["ticker", "date", "close", "volume", "open", "high", "low"]].copy()

    # Start with previous panel data
    frames = {}
    for tk in ALL_TICKERS:
        sub = prev_prices[prev_prices["ticker"] == tk].copy()
        sub = sub.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        frames[tk] = sub

    # Try to extend LTC via CoinGecko
    ltc_max = frames["LTC"]["date"].max()
    print(f"LTC max date in prev panel: {ltc_max}")
    if ltc_max < pd.Timestamp("2026-03-01"):
        print("Fetching LTC from CoinGecko to extend coverage...")
        try:
            from_ts = int((ltc_max + timedelta(days=1)).timestamp())
            to_ts = int(datetime(2026, 3, 18).timestamp())
            ltc_new = fetch_coingecko_range("litecoin", from_ts=from_ts, to_ts=to_ts)
            ltc_new["ticker"] = "LTC"
            ltc_new["open"] = np.nan
            ltc_new["high"] = np.nan
            ltc_new["low"] = np.nan
            if len(ltc_new) > 0:
                frames["LTC"] = pd.concat([frames["LTC"], ltc_new], ignore_index=True)
                frames["LTC"] = frames["LTC"].drop_duplicates(subset=["date"], keep="last").sort_values("date")
                print(f"  Extended LTC to {frames['LTC']['date'].max()}, added {len(ltc_new)} rows")
        except Exception as e:
            print(f"  Warning: CoinGecko LTC fetch failed: {e}")

    # Try to extend MATIC/POL via CoinGecko
    matic_max = frames["MATIC"]["date"].max()
    print(f"MATIC max date in prev panel: {matic_max}")
    if matic_max < pd.Timestamp("2026-03-01"):
        print("Fetching MATIC/POL from CoinGecko to extend coverage...")
        try:
            from_ts = int((matic_max + timedelta(days=1)).timestamp())
            to_ts = int(datetime(2026, 3, 18).timestamp())
            matic_new = fetch_coingecko_range("matic-network", from_ts=from_ts, to_ts=to_ts)
            matic_new["ticker"] = "MATIC"
            matic_new["open"] = np.nan
            matic_new["high"] = np.nan
            matic_new["low"] = np.nan
            if len(matic_new) > 0:
                frames["MATIC"] = pd.concat([frames["MATIC"], matic_new], ignore_index=True)
                frames["MATIC"] = frames["MATIC"].drop_duplicates(subset=["date"], keep="last").sort_values("date")
                print(f"  Extended MATIC to {frames['MATIC']['date'].max()}, added {len(matic_new)} rows")
        except Exception as e:
            print(f"  Warning: CoinGecko MATIC fetch failed: {e}")

    # Try to update BTC/ETH/SOL/SPY/GLD from yf_macro (may have more recent data)
    for tk in ["BTC", "ETH", "SOL", "SPY", "GLD"]:
        yf_tk = yf[yf["ticker"] == tk].copy()
        if len(yf_tk) == 0:
            continue
        yf_tk["date"] = pd.to_datetime(yf_tk["date"])
        existing_max = pd.to_datetime(frames[tk]["date"]).max()
        yf_tk = yf_tk[yf_tk["date"] > existing_max]
        if len(yf_tk) > 0:
            frames[tk] = pd.concat([frames[tk], yf_tk[["ticker", "date", "close", "volume", "open", "high", "low"]]], ignore_index=True)
            frames[tk] = frames[tk].drop_duplicates(subset=["date"], keep="last").sort_values("date")
            print(f"  Extended {tk} from yf_macro: +{len(yf_tk)} rows to {frames[tk]['date'].max()}")

    # Combine all price data
    combined = pd.concat(frames.values(), ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)

    print("\nPrice panel summary:")
    for tk in ALL_TICKERS:
        sub = combined[combined["ticker"] == tk]
        print(f"  {tk:6s}: {sub['date'].min().date()} to {sub['date'].max().date()}, N={len(sub)}")

    return combined, vix_db, dxy_db, ffr_db, spy_db


# ---------------------------------------------------------------------------
# Compute derived variables
# ---------------------------------------------------------------------------
def compute_returns_and_vol(panel):
    """Compute log returns, realized volatility, and risk measures."""
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Log return
    panel["log_return"] = panel.groupby("ticker")["close"].transform(
        lambda x: np.log(x).diff()
    )

    # Log volume
    panel["log_volume"] = np.log1p(panel["volume"].fillna(0))

    # Absolute and squared returns
    panel["abs_return"] = panel["log_return"].abs()
    panel["sq_return"] = panel["log_return"] ** 2

    # Realized volatility: annualized std of log returns over rolling windows
    for window in [21, 30, 60, 90]:
        col = f"rvol_{window}d"
        panel[col] = panel.groupby("ticker")["log_return"].transform(
            lambda x: x.rolling(window, min_periods=max(window - 5, 15)).std() * np.sqrt(365)
        )

    # Parkinson range-based volatility (30-day rolling)
    if "high" in panel.columns and "low" in panel.columns:
        panel["log_hl"] = np.log(panel["high"] / panel["low"]) ** 2 / (4 * np.log(2))
        panel["parkinson_30d"] = panel.groupby("ticker")["log_hl"].transform(
            lambda x: np.sqrt(x.rolling(30, min_periods=25).mean() * 365)
        )
        panel.drop(columns=["log_hl"], inplace=True)

    # Rolling skewness, kurtosis (90d)
    panel["rolling_skew_90d"] = panel.groupby("ticker")["log_return"].transform(
        lambda x: x.rolling(90, min_periods=60).skew()
    )
    panel["rolling_kurt_90d"] = panel.groupby("ticker")["log_return"].transform(
        lambda x: x.rolling(90, min_periods=60).kurt()
    )

    # Rolling autocorrelation (30d)
    panel["rolling_autocorr_30d"] = panel.groupby("ticker")["log_return"].transform(
        lambda x: x.rolling(30, min_periods=25).apply(lambda s: s.autocorr(lag=1), raw=False)
    )

    # Volatility of volatility (30d rolling std of rvol_30d changes)
    panel["vol_of_vol_30d"] = panel.groupby("ticker")["rvol_30d"].transform(
        lambda x: x.diff().rolling(30, min_periods=25).std()
    )

    # Downside volatility (30d, only negative returns)
    panel["downside_vol_30d"] = panel.groupby("ticker")["log_return"].transform(
        lambda x: x.clip(upper=0).rolling(30, min_periods=25).std() * np.sqrt(365)
    )

    # VaR estimates
    panel["var_5pct_30d"] = panel.groupby("ticker")["log_return"].transform(
        lambda x: x.rolling(30, min_periods=25).quantile(0.05)
    )
    panel["var_1pct_30d"] = panel.groupby("ticker")["log_return"].transform(
        lambda x: x.rolling(30, min_periods=25).quantile(0.01)
    )

    return panel


def add_controls(panel, vix_db, dxy_db, ffr_db, spy_db):
    """Merge macro controls into the panel."""
    # VIX: combine from DB + previous panel
    vix = vix_db.copy()
    prev_panel = pd.read_csv(PREV_PANEL, parse_dates=["date"])
    prev_vix = prev_panel[["date", "vix"]].drop_duplicates(subset=["date"]).dropna()
    vix_combined = pd.concat([vix, prev_vix], ignore_index=True)
    vix_combined = vix_combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")

    # DXY
    dxy = dxy_db.copy()
    prev_dxy = prev_panel[["date", "dxy"]].drop_duplicates(subset=["date"]).dropna()
    dxy_combined = pd.concat([dxy, prev_dxy], ignore_index=True)
    dxy_combined = dxy_combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")

    # Fed funds rate
    ffr = ffr_db.copy()

    # SPY close and return
    spy_prices = spy_db.copy()
    spy_prices["spy_close"] = spy_prices["close"]
    spy_prices["sp500_logret"] = np.log(spy_prices["close"]).diff()
    spy_ctrl = spy_prices[["date", "spy_close", "sp500_logret"]].copy()
    prev_spy = prev_panel[["date", "spy_close", "sp500_logret"]].drop_duplicates(subset=["date"]).dropna()
    spy_ctrl = pd.concat([spy_ctrl, prev_spy], ignore_index=True)
    spy_ctrl = spy_ctrl.drop_duplicates(subset=["date"], keep="last").sort_values("date")

    # Merge all controls
    panel = panel.merge(vix_combined[["date", "vix"]], on="date", how="left")
    panel = panel.merge(dxy_combined[["date", "dxy"]], on="date", how="left")
    panel = panel.merge(ffr[["date", "fed_funds_rate"]], on="date", how="left")
    panel = panel.merge(spy_ctrl[["date", "spy_close", "sp500_logret"]], on="date", how="left")

    # Forward-fill controls (weekends/holidays)
    for col in ["vix", "dxy", "fed_funds_rate", "spy_close", "sp500_logret"]:
        panel[col] = panel.groupby("ticker")[col].transform(lambda x: x.ffill())

    return panel


def add_treatment_indicators(panel):
    """Add DiD/SCM treatment indicators and event study variables."""
    panel["asset_type"] = panel["ticker"].apply(lambda x: "crypto" if x in CRYPTO_TICKERS else "traditional")
    panel["is_btc"] = (panel["ticker"] == "BTC").astype(int)
    panel["is_eth"] = (panel["ticker"] == "ETH").astype(int)
    panel["is_crypto"] = panel["ticker"].isin(CRYPTO_TICKERS).astype(int)
    panel["is_trad"] = panel["ticker"].isin(TRAD_TICKERS).astype(int)

    # Institutional events
    events = {
        "cme_futures_launch": pd.Timestamp("2017-12-18"),
        "grayscale_ruling": pd.Timestamp("2023-08-29"),
        "btc_spot_etf_approval": pd.Timestamp("2024-01-10"),
        "eth_spot_etf_approval": pd.Timestamp("2024-05-23"),
        "oct_2025_liquidation": pd.Timestamp("2025-10-01"),
    }

    for event_name, event_date in events.items():
        post_col = f"post_{event_name}"
        btc_x_col = f"btc_x_post_{event_name}"
        rel_days_col = f"rel_days_{event_name}"

        panel[post_col] = (panel["date"] >= event_date).astype(int)
        panel[btc_x_col] = panel["is_btc"] * panel[post_col]
        panel[rel_days_col] = (panel["date"] - event_date).dt.days

    # ETH x post_eth_spot_etf
    panel["eth_x_post_eth_spot_etf_approval"] = panel["is_eth"] * panel["post_eth_spot_etf_approval"]

    # Year-month for FE
    panel["year_month"] = panel["date"].dt.to_period("M").astype(str)

    # Sub-periods (2-way)
    def assign_period(d):
        if d < pd.Timestamp("2017-12-18"):
            return "pre_cme"
        elif d < pd.Timestamp("2024-01-10"):
            return "post_cme_pre_etf"
        else:
            return "post_etf"

    # Sub-periods (3-way)
    def assign_period_3way(d):
        if d < pd.Timestamp("2017-12-18"):
            return "pre_institutional"
        elif d < pd.Timestamp("2023-08-29"):
            return "early_institutional"
        else:
            return "late_institutional"

    panel["period"] = panel["date"].apply(assign_period)
    panel["period_3way"] = panel["date"].apply(assign_period_3way)

    # BTC-to-traditional RV ratio
    btc_rv = panel.loc[panel["ticker"] == "BTC", ["date", "rvol_30d"]].rename(columns={"rvol_30d": "btc_rv30"})
    spy_rv = panel.loc[panel["ticker"] == "SPY", ["date", "rvol_30d"]].rename(columns={"rvol_30d": "spy_rv30"})
    rv_ratio = btc_rv.merge(spy_rv, on="date", how="inner")
    rv_ratio["btc_trad_rv_ratio"] = rv_ratio["btc_rv30"] / rv_ratio["spy_rv30"]
    panel = panel.merge(rv_ratio[["date", "btc_trad_rv_ratio"]], on="date", how="left")

    return panel


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------
def compute_summary_stats(panel):
    """Compute per-asset summary statistics."""
    stats_rows = []
    for tk in ALL_TICKERS:
        sub = panel[panel["ticker"] == tk].dropna(subset=["log_return"])
        row = {
            "asset": tk,
            "N": len(sub),
            "start_date": str(sub["date"].min().date()),
            "end_date": str(sub["date"].max().date()),
            "mean_return": sub["log_return"].mean(),
            "sd_return": sub["log_return"].std(),
            "annualized_return": sub["log_return"].mean() * 365,
            "annualized_vol": sub["log_return"].std() * np.sqrt(365),
            "min_return": sub["log_return"].min(),
            "max_return": sub["log_return"].max(),
            "skewness": sub["log_return"].skew(),
            "kurtosis": sub["log_return"].kurt(),
            "mean_rvol_30d": sub["rvol_30d"].mean(),
            "sd_rvol_30d": sub["rvol_30d"].std(),
            "mean_volume": sub["volume"].mean(),
            "median_volume": sub["volume"].median(),
        }
        stats_rows.append(row)
    return pd.DataFrame(stats_rows)


def compute_subperiod_stats(panel):
    """Compute summary statistics by sub-period for all assets."""
    periods = {
        "pre_cme": ("2014-09-18", "2017-12-17"),
        "post_cme_pre_etf": ("2017-12-18", "2024-01-09"),
        "post_etf": ("2024-01-10", "2026-03-18"),
    }
    results = {}
    for period_name, (start, end) in periods.items():
        period_stats = []
        for tk in ALL_TICKERS:
            sub = panel[
                (panel["ticker"] == tk)
                & (panel["date"] >= start)
                & (panel["date"] <= end)
            ].dropna(subset=["log_return"])
            if len(sub) < 10:
                continue
            period_stats.append({
                "asset": tk,
                "period": period_name,
                "N": len(sub),
                "mean_return": round(sub["log_return"].mean(), 6),
                "sd_return": round(sub["log_return"].std(), 6),
                "annualized_vol": round(sub["log_return"].std() * np.sqrt(365), 4),
                "mean_rvol_30d": round(sub["rvol_30d"].mean(), 4) if sub["rvol_30d"].notna().sum() > 0 else None,
                "skewness": round(sub["log_return"].skew(), 4),
                "kurtosis": round(sub["log_return"].kurt(), 4),
            })
        results[period_name] = period_stats
    return results


def compute_correlations(panel):
    """Compute return correlations across assets."""
    pivot = panel[panel["ticker"].isin(ALL_TICKERS)].pivot_table(
        index="date", columns="ticker", values="log_return"
    )
    return pivot.corr()


def build_monthly_panel(panel):
    """Aggregate daily panel to monthly for DiD estimation."""
    panel["ym"] = panel["date"].dt.to_period("M")
    monthly = panel.groupby(["ticker", "ym"]).agg(
        mean_rvol_30d=("rvol_30d", "mean"),
        mean_rvol_21d=("rvol_21d", "mean"),
        mean_rvol_60d=("rvol_60d", "mean"),
        mean_rvol_90d=("rvol_90d", "mean"),
        mean_log_return=("log_return", "mean"),
        sd_log_return=("log_return", "std"),
        mean_log_volume=("log_volume", "mean"),
        mean_abs_return=("abs_return", "mean"),
        n_obs=("log_return", "count"),
        mean_vix=("vix", "mean"),
        mean_dxy=("dxy", "mean"),
        mean_sp500_logret=("sp500_logret", "mean"),
    ).reset_index()
    monthly["date"] = monthly["ym"].dt.to_timestamp()

    # Asset-level indicators
    monthly["is_btc"] = (monthly["ticker"] == "BTC").astype(int)
    monthly["is_eth"] = (monthly["ticker"] == "ETH").astype(int)
    monthly["is_crypto"] = monthly["ticker"].isin(CRYPTO_TICKERS).astype(int)

    # Treatment indicators at monthly boundaries
    events = {
        "cme_futures_launch": pd.Timestamp("2017-12-01"),
        "grayscale_ruling": pd.Timestamp("2023-09-01"),
        "btc_spot_etf_approval": pd.Timestamp("2024-02-01"),
        "eth_spot_etf_approval": pd.Timestamp("2024-06-01"),
        "oct_2025_liquidation": pd.Timestamp("2025-10-01"),
    }
    for evt, dt in events.items():
        monthly[f"post_{evt}"] = (monthly["date"] >= dt).astype(int)
        monthly[f"btc_x_post_{evt}"] = monthly["is_btc"] * monthly[f"post_{evt}"]

    monthly["eth_x_post_eth_spot_etf_approval"] = monthly["is_eth"] * monthly["post_eth_spot_etf_approval"]
    monthly["year_month"] = monthly["ym"].astype(str)
    monthly.drop(columns=["ym"], inplace=True)

    return monthly


def build_scm_pretreatment(panel, event_name, pre_start, pre_end):
    """Build pre-treatment panel for synthetic control matching."""
    sub = panel[
        (panel["ticker"].isin(CRYPTO_TICKERS))
        & (panel["date"] >= pre_start)
        & (panel["date"] <= pre_end)
    ].copy()

    sub["ym"] = sub["date"].dt.to_period("M")
    monthly = sub.groupby(["ticker", "ym"]).agg(
        rvol_30d=("rvol_30d", "mean"),
        rvol_21d=("rvol_21d", "mean"),
        mean_return=("log_return", "mean"),
        sd_return=("log_return", "std"),
        log_volume=("log_volume", "mean"),
        skewness=("log_return", "skew"),
        n_obs=("log_return", "count"),
    ).reset_index()
    monthly["date"] = monthly["ym"].dt.to_timestamp()
    monthly.drop(columns=["ym"], inplace=True)
    monthly["event"] = event_name

    return monthly


def build_event_study_windows(panel, window_days=180):
    """Build event study windows for each institutional event."""
    events = {
        "cme_futures_launch": pd.Timestamp("2017-12-18"),
        "grayscale_ruling": pd.Timestamp("2023-08-29"),
        "btc_spot_etf_approval": pd.Timestamp("2024-01-10"),
        "eth_spot_etf_approval": pd.Timestamp("2024-05-23"),
        "oct_2025_liquidation": pd.Timestamp("2025-10-01"),
    }
    frames = []
    for evt_name, evt_date in events.items():
        start = evt_date - timedelta(days=window_days)
        end = evt_date + timedelta(days=window_days)
        sub = panel[
            (panel["ticker"].isin(CRYPTO_TICKERS))
            & (panel["date"] >= start)
            & (panel["date"] <= end)
        ].copy()
        sub["event"] = evt_name
        sub["event_date"] = evt_date
        sub["rel_days"] = (sub["date"] - evt_date).dt.days
        frames.append(sub)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_volatility_by_period(panel):
    """Compute volatility statistics by sub-period."""
    vol_rows = []
    for tk in ALL_TICKERS:
        for period in ["pre_cme", "post_cme_pre_etf", "post_etf"]:
            sub = panel[(panel["ticker"] == tk) & (panel["period"] == period)].dropna(subset=["rvol_30d"])
            if len(sub) < 10:
                continue
            vol_rows.append({
                "asset": tk, "period": period, "N": len(sub),
                "mean_rvol_30d": round(sub["rvol_30d"].mean(), 4),
                "sd_rvol_30d": round(sub["rvol_30d"].std(), 4),
                "mean_rvol_60d": round(sub["rvol_60d"].mean(), 4) if sub["rvol_60d"].notna().sum() > 0 else None,
            })
    return pd.DataFrame(vol_rows)


def build_volatility_by_period_3way(panel):
    """Compute volatility and return statistics by 3-way sub-period."""
    vol_rows = []
    for tk in ALL_TICKERS:
        for period in ["pre_institutional", "early_institutional", "late_institutional"]:
            sub = panel[(panel["ticker"] == tk) & (panel["period_3way"] == period)].dropna(subset=["log_return"])
            if len(sub) < 10:
                continue
            vol_rows.append({
                "asset": tk, "period": period, "N": len(sub),
                "mean_rvol_30d": round(sub["rvol_30d"].mean(), 4) if sub["rvol_30d"].notna().sum() > 0 else None,
                "sd_rvol_30d": round(sub["rvol_30d"].std(), 4) if sub["rvol_30d"].notna().sum() > 0 else None,
                "mean_return": round(sub["log_return"].mean() * 365, 4),
                "sd_return": round(sub["log_return"].std() * np.sqrt(365), 4),
            })
    return pd.DataFrame(vol_rows)


def build_btc_trad_rv_ratio_by_period(panel):
    """Compute BTC-to-SPY RV ratio by sub-period."""
    btc_rv = panel.loc[panel["ticker"] == "BTC", ["date", "rvol_30d", "btc_trad_rv_ratio", "period"]].dropna(subset=["btc_trad_rv_ratio"])
    rows = []
    for period in ["pre_cme", "post_cme_pre_etf", "post_etf"]:
        sub = btc_rv[btc_rv["period"] == period]
        if len(sub) < 10:
            continue
        rows.append({
            "period": period,
            "mean_ratio": sub["btc_trad_rv_ratio"].mean(),
            "median_ratio": sub["btc_trad_rv_ratio"].median(),
            "sd_ratio": sub["btc_trad_rv_ratio"].std(),
            "N": len(sub),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("DATA STAGE — Run 16: Institutionalization of Bitcoin")
    print("=" * 70)

    # Step 1: Build price panel
    prices, vix_db, dxy_db, ffr_db, spy_db = build_price_panel()

    # Step 2: Compute returns and volatility
    print("\nComputing returns and volatility measures...")
    panel = compute_returns_and_vol(prices)

    # Step 3: Add macro controls
    print("Adding macro controls...")
    panel = add_controls(panel, vix_db, dxy_db, ffr_db, spy_db)

    # Step 4: Add treatment indicators
    print("Adding treatment indicators...")
    panel = add_treatment_indicators(panel)

    # Step 5: Summary statistics
    print("Computing summary statistics...")
    summary = compute_summary_stats(panel)
    subperiod = compute_subperiod_stats(panel)
    correlations = compute_correlations(panel)

    # Step 6: Monthly panel
    print("Building monthly panel...")
    monthly = build_monthly_panel(panel)

    # Step 7: SCM pre-treatment panels
    print("Building SCM pre-treatment panels...")
    scm_cme = build_scm_pretreatment(panel, "cme_futures_launch", "2015-01-01", "2017-11-30")
    scm_grayscale = build_scm_pretreatment(panel, "grayscale_ruling", "2022-01-01", "2023-07-31")
    scm_btc_etf = build_scm_pretreatment(panel, "btc_spot_etf_approval", "2022-01-01", "2023-12-31")
    scm_eth_etf = build_scm_pretreatment(panel, "eth_spot_etf_approval", "2022-01-01", "2024-04-30")

    # Step 8: Event study windows
    print("Building event study windows...")
    event_windows = build_event_study_windows(panel)

    # Step 9: Volatility by period
    vol_by_period = build_volatility_by_period(panel)
    vol_by_period_3way = build_volatility_by_period_3way(panel)

    # Step 10: BTC-to-traditional RV ratio
    btc_rv = panel.loc[panel["ticker"] == "BTC", ["date", "rvol_30d", "btc_trad_rv_ratio"]].dropna(subset=["btc_trad_rv_ratio"])
    rv_ratio_by_period = build_btc_trad_rv_ratio_by_period(panel)

    # -----------------------------------------------------------------------
    # Save artifacts
    # -----------------------------------------------------------------------
    print("\nSaving artifacts...")

    panel.to_csv(f"{OUT}/estimation_sample_panel.csv", index=False)
    print(f"  estimation_sample_panel.csv: {len(panel)} rows, {len(panel.columns)} cols")

    monthly.to_csv(f"{OUT}/monthly_panel.csv", index=False)
    print(f"  monthly_panel.csv: {len(monthly)} rows")

    summary.to_csv(f"{OUT}/summary_statistics.csv", index=False)
    summary_dict = summary.to_dict(orient="records")
    with open(f"{OUT}/summary_statistics.json", "w") as f:
        json.dump(summary_dict, f, indent=2, default=str)

    with open(f"{OUT}/subperiod_statistics.json", "w") as f:
        json.dump(subperiod, f, indent=2, default=str)

    correlations.to_csv(f"{OUT}/return_correlations.csv")

    vol_by_period.to_csv(f"{OUT}/volatility_by_period.csv", index=False)
    vol_by_period_3way.to_csv(f"{OUT}/volatility_by_period_3way.csv", index=False)

    btc_rv.to_csv(f"{OUT}/btc_trad_rv_ratio.csv", index=False)
    rv_ratio_by_period.to_csv(f"{OUT}/btc_trad_rv_ratio_by_period.csv", index=False)

    event_windows.to_csv(f"{OUT}/event_study_windows.csv", index=False)
    print(f"  event_study_windows.csv: {len(event_windows)} rows")

    for name, df in [("cme_futures_launch", scm_cme), ("grayscale_ruling", scm_grayscale),
                     ("btc_spot_etf_approval", scm_btc_etf), ("eth_spot_etf_approval", scm_eth_etf)]:
        df.to_csv(f"{OUT}/scm_pretreatment_{name}.csv", index=False)

    print("\nDone. All artifacts saved to", OUT)
    return panel, summary


if __name__ == "__main__":
    panel, summary = main()
    print("\n=== SUMMARY STATISTICS ===")
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 200)
    print(summary[["asset", "N", "start_date", "end_date", "annualized_return", "annualized_vol", "skewness", "kurtosis", "mean_rvol_30d"]].to_string(index=False))
