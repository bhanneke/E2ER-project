"""
Replication script: How do US bank stocks respond to FOMC target-rate announcements?
Paper ID: @@PAPER_ID@@

Event study of 31 FOMC target-rate announcements (December 2015 – December 2025).
Analysis: KBE (bank sector ETF) abnormal returns relative to SPY (S&P 500).
Market model estimation: [-250, -12] trading days per event.
Event windows: [-1, +1] and [0, +5].
Hypotheses:
  H1: Mean CAR differs from zero (separately for hikes and cuts)
  H2: CAR sensitivity to same-day 2-year Treasury yield change (pooled and by direction)

Requirements: pandas, numpy, scipy, statsmodels, sqlite3
Usage: python estimation.py
Output: replication/output/ (CSV tables with results)
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats
import statsmodels.api as sm
import json
from datetime import datetime, timedelta

# ── Setup ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(__file__).parent.parent / "data.db"
if not DB_PATH.exists():
    raise FileNotFoundError(f"Database not found at {DB_PATH}")

np.random.seed(42)

# ── 1. Load data ──────────────────────────────────────────────────────────────
print("Loading data from data.db...")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Load events
fomc_events = pd.read_sql(
    "SELECT * FROM fomc_announcement_dates ORDER BY announcement_date",
    conn
)
fomc_events["announcement_date"] = pd.to_datetime(fomc_events["announcement_date"])
print(f"Loaded {len(fomc_events)} FOMC events")
print(f"  Hikes: {(fomc_events['direction'] == 'increase').sum()}")
print(f"  Cuts: {(fomc_events['direction'] == 'cut').sum()}")

# Load price data
kbe = pd.read_sql("SELECT * FROM kbe_prices ORDER BY date", conn)
spy = pd.read_sql("SELECT * FROM spy_prices ORDER BY date", conn)
xlf = pd.read_sql("SELECT * FROM xlf_prices ORDER BY date", conn)

# Parse dates and extract close prices
for df in [kbe, spy, xlf]:
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

kbe_close = kbe[["date", "close"]].set_index("date")["close"]
spy_close = spy[["date", "close"]].set_index("date")["close"]
xlf_close = xlf[["date", "close"]].set_index("date")["close"]

# Load yield data (2-year Treasury)
dgs2 = pd.read_sql(
    "SELECT date, value FROM dgs2 WHERE value IS NOT NULL ORDER BY date",
    conn
)
dgs2["date"] = pd.to_datetime(dgs2["date"])
dgs2.sort_values("date", inplace=True)
dgs2_series = dgs2.set_index("date")["value"]  # In percent from FRED

conn.close()

print(f"Loaded {len(kbe_close)} KBE prices")
print(f"Loaded {len(spy_close)} SPY prices")
print(f"Loaded {len(xlf_close)} XLF prices")
print(f"Loaded {len(dgs2_series)} DGS2 values (non-null)")

# ── 2. Compute returns ────────────────────────────────────────────────────────
# Log returns
kbe_returns = np.log(kbe_close / kbe_close.shift(1))
spy_returns = np.log(spy_close / spy_close.shift(1))
xlf_returns = np.log(xlf_close / xlf_close.shift(1))

# Build trading day calendar
trading_dates = sorted(set(kbe_close.index) & set(spy_close.index) & set(xlf_close.index))
date_to_idx = {d: i for i, d in enumerate(trading_dates)}

print(f"Trading calendar: {len(trading_dates)} days from {trading_dates[0]} to {trading_dates[-1]}")

# ── 3. Event preprocessing ────────────────────────────────────────────────────
events = []
for idx, row in fomc_events.iterrows():
    ann_date = row["announcement_date"].date()

    # Find t=0: announcement_date or next trading day
    t0_date = ann_date
    while t0_date not in date_to_idx:
        t0_date += timedelta(days=1)

    t0_idx = date_to_idx[t0_date]

    # Check if we have enough history (need t=-250)
    if t0_idx < 250:
        print(f"  WARNING: Event {idx} ({ann_date}) has insufficient history; skipping")
        continue

    events.append({
        "event_id": idx,
        "announcement_date": ann_date,
        "trading_day_0": t0_date,
        "t0_idx": t0_idx,
        "direction": row["direction"],
        "dfedtaru_before": row["dfedtaru_before"],
        "dfedtaru_after": row["dfedtaru_after"],
    })

print(f"Events with sufficient history: {len(events)}")

# ── 4. For each event: estimate market model and compute abnormal returns ────
results = []

for event in events:
    event_id = event["event_id"]
    t0_idx = event["t0_idx"]
    direction = event["direction"]

    # Estimation window: [-250, -12] trading days
    est_start_idx = t0_idx - 250
    est_end_idx = t0_idx - 12

    # Event window indices
    w1_start_idx = t0_idx - 1
    w1_end_idx = t0_idx + 1
    w2_start_idx = t0_idx
    w2_end_idx = t0_idx + 5

    # Extract returns for estimation
    est_dates = trading_dates[est_start_idx:est_end_idx + 1]
    est_kbe = kbe_returns.loc[est_dates].dropna()
    est_spy = spy_returns.loc[est_dates].dropna()

    # Match returns
    common_est_dates = sorted(set(est_kbe.index) & set(est_spy.index))
    if len(common_est_dates) < 100:
        print(f"  Event {event_id}: insufficient data ({len(common_est_dates)} obs)")
        continue

    est_kbe = est_kbe.loc[common_est_dates]
    est_spy = est_spy.loc[common_est_dates]

    # Market model: KBE = alpha + beta * SPY + epsilon
    X = sm.add_constant(est_spy.values)
    y = est_kbe.values
    market_model = sm.OLS(y, X).fit()

    alpha_hat = market_model.params[0]
    beta_hat = market_model.params[1]
    model_r2 = market_model.rsquared

    # Compute abnormal returns for event windows
    def compute_car(start_idx, end_idx):
        window_dates = [d for d in trading_dates[start_idx:end_idx + 1]
                       if d in kbe_close.index and d in spy_close.index]
        if len(window_dates) == 0:
            return np.nan

        ar_sum = 0.0
        for d in window_dates:
            r_kbe = kbe_returns.loc[d]
            r_spy = spy_returns.loc[d]
            expected_return = alpha_hat + beta_hat * r_spy
            ar = r_kbe - expected_return
            ar_sum += ar

        return ar_sum * 100  # Convert to percentage

    car_w1 = compute_car(w1_start_idx, w1_end_idx)  # [-1, +1]
    car_w2 = compute_car(w2_start_idx, w2_end_idx)  # [0, +5]

    # Get DGS2 change on event day
    event_date = event["trading_day_0"]
    dgs2_day0 = dgs2_series.get(pd.Timestamp(event_date), np.nan)

    # Get previous trading day's DGS2
    prev_idx = t0_idx - 1
    while prev_idx >= 0:
        prev_date = trading_dates[prev_idx]
        dgs2_prev = dgs2_series.get(pd.Timestamp(prev_date), np.nan)
        if not np.isnan(dgs2_prev):
            break
        prev_idx -= 1

    if not np.isnan(dgs2_day0) and not np.isnan(dgs2_prev):
        dgs2_change = (dgs2_day0 - dgs2_prev) * 100  # Convert from percent to basis points
    else:
        dgs2_change = np.nan

    results.append({
        "event_id": event_id,
        "announcement_date": event["announcement_date"],
        "direction": direction,
        "car_m1p1": car_w1,  # CAR[-1, +1]
        "car_0p5": car_w2,   # CAR[0, +5]
        "dgs2_change": dgs2_change,
        "alpha": alpha_hat,
        "beta": beta_hat,
        "model_r2": model_r2,
        "n_obs_est": len(common_est_dates),
    })

results_df = pd.DataFrame(results)
print(f"Computed abnormal returns for {len(results_df)} events")

# ── 5. Hypothesis 1: Mean CAR tests ───────────────────────────────────────────
print("\n" + "="*70)
print("HYPOTHESIS 1: Mean CAR Test")
print("="*70)

h1_results = {}

# H1a: Hikes, window [-1, +1]
h1_hikes_m1p1 = results_df[results_df["direction"] == "increase"]["car_m1p1"].dropna()
if len(h1_hikes_m1p1) > 1:
    mean_car = h1_hikes_m1p1.mean()
    std_car = h1_hikes_m1p1.std()
    se = std_car / np.sqrt(len(h1_hikes_m1p1))
    t_stat = mean_car / se
    df = len(h1_hikes_m1p1) - 1
    p_value = 2 * stats.t.sf(np.abs(t_stat), df)
    ci_lower = mean_car - stats.t.ppf(0.975, df) * se
    ci_upper = mean_car + stats.t.ppf(0.975, df) * se

    h1_results["H1a_hikes_m1p1"] = {
        "hypothesis": "H1a",
        "window": "[-1, +1]",
        "direction": "increase",
        "n": len(h1_hikes_m1p1),
        "df": df,
        "mean_car": mean_car,
        "std_car": std_car,
        "se": se,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
    }
    print(f"\nH1a: Rate Hikes, Window [-1, +1]")
    print(f"  N = {len(h1_hikes_m1p1)}, df = {df}")
    print(f"  Mean CAR = {mean_car:.4f}%, SE = {se:.4f}%")
    print(f"  t = {t_stat:.4f}, p = {p_value:.4f}")

# H1b: Cuts, window [-1, +1]
h1_cuts_m1p1 = results_df[results_df["direction"] == "cut"]["car_m1p1"].dropna()
if len(h1_cuts_m1p1) > 1:
    mean_car = h1_cuts_m1p1.mean()
    std_car = h1_cuts_m1p1.std()
    se = std_car / np.sqrt(len(h1_cuts_m1p1))
    t_stat = mean_car / se
    df = len(h1_cuts_m1p1) - 1
    p_value = 2 * stats.t.sf(np.abs(t_stat), df)
    ci_lower = mean_car - stats.t.ppf(0.975, df) * se
    ci_upper = mean_car + stats.t.ppf(0.975, df) * se

    h1_results["H1b_cuts_m1p1"] = {
        "hypothesis": "H1b",
        "window": "[-1, +1]",
        "direction": "cut",
        "n": len(h1_cuts_m1p1),
        "df": df,
        "mean_car": mean_car,
        "std_car": std_car,
        "se": se,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
    }
    print(f"\nH1b: Rate Cuts, Window [-1, +1]")
    print(f"  N = {len(h1_cuts_m1p1)}, df = {df}")
    print(f"  Mean CAR = {mean_car:.4f}%, SE = {se:.4f}%")
    print(f"  t = {t_stat:.4f}, p = {p_value:.4f}")

# Pooled, window [0, +5]
h1_pooled_0p5 = results_df["car_0p5"].dropna()
if len(h1_pooled_0p5) > 1:
    mean_car = h1_pooled_0p5.mean()
    std_car = h1_pooled_0p5.std()
    se = std_car / np.sqrt(len(h1_pooled_0p5))
    t_stat = mean_car / se
    df = len(h1_pooled_0p5) - 1
    p_value = 2 * stats.t.sf(np.abs(t_stat), df)
    ci_lower = mean_car - stats.t.ppf(0.975, df) * se
    ci_upper = mean_car + stats.t.ppf(0.975, df) * se

    h1_results["H1_pooled_0p5"] = {
        "hypothesis": "H1_pooled_secondary",
        "window": "[0, +5]",
        "direction": "pooled",
        "n": len(h1_pooled_0p5),
        "df": df,
        "mean_car": mean_car,
        "std_car": std_car,
        "se": se,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
    }
    print(f"\nH1 (Pooled, Secondary): Window [0, +5]")
    print(f"  N = {len(h1_pooled_0p5)}, df = {df}")
    print(f"  Mean CAR = {mean_car:.4f}%, SE = {se:.4f}%")
    print(f"  t = {t_stat:.4f}, p = {p_value:.4f}")

# ── 6. Hypothesis 2: CAR vs. DGS2 Change ──────────────────────────────────────
print("\n" + "="*70)
print("HYPOTHESIS 2: CAR Sensitivity to 2-Year Yield Change")
print("="*70)

h2_results = {}

# H2 Primary: Pooled regression
h2_data = results_df[["car_m1p1", "dgs2_change"]].dropna()
if len(h2_data) > 2:
    y = h2_data["car_m1p1"].values
    X = sm.add_constant(h2_data["dgs2_change"].values)
    h2_model = sm.OLS(y, X).fit(cov_type="HC1", use_t=True)

    n = len(h2_data)
    df = n - 2

    # Extract results
    alpha = h2_model.params[0]
    beta = h2_model.params[1]
    se_beta = h2_model.bse[1]
    t_stat = h2_model.tvalues[1]
    p_value = h2_model.pvalues[1]  # From t-distribution with use_t=True
    r2 = h2_model.rsquared

    ci_lower = beta - stats.t.ppf(0.975, df) * se_beta
    ci_upper = beta + stats.t.ppf(0.975, df) * se_beta

    h2_results["H2_pooled"] = {
        "hypothesis": "H2",
        "n": n,
        "df": df,
        "alpha": alpha,
        "beta": beta,
        "se_beta": se_beta,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "r2": r2,
    }
    print(f"\nH2 (Primary): Pooled Regression")
    print(f"  N = {n}, df = {df}")
    print(f"  β = {beta:.6f} (SE = {se_beta:.6f})")
    print(f"  t = {t_stat:.4f}, p = {p_value:.4f}")
    print(f"  R² = {r2:.4f}")

# H2 Secondary: Separate by direction (Hikes)
h2_hikes = results_df[results_df["direction"] == "increase"][["car_m1p1", "dgs2_change"]].dropna()
if len(h2_hikes) > 2:
    y = h2_hikes["car_m1p1"].values
    X = sm.add_constant(h2_hikes["dgs2_change"].values)
    h2_hikes_model = sm.OLS(y, X).fit(cov_type="HC1", use_t=True)

    n = len(h2_hikes)
    df = n - 2
    beta = h2_hikes_model.params[1]
    se_beta = h2_hikes_model.bse[1]
    t_stat = h2_hikes_model.tvalues[1]
    p_value = h2_hikes_model.pvalues[1]
    r2 = h2_hikes_model.rsquared

    alpha = h2_hikes_model.params[0]
    ci_lower = beta - stats.t.ppf(0.975, df) * se_beta
    ci_upper = beta + stats.t.ppf(0.975, df) * se_beta

    h2_results["H2_hikes"] = {
        "hypothesis": "H2_hikes",
        "n": n,
        "df": df,
        "alpha": alpha,
        "beta": beta,
        "se_beta": se_beta,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "r2": r2,
    }
    print(f"\nH2 (Secondary): Rate Hikes")
    print(f"  N = {n}, df = {df}")
    print(f"  β = {beta:.6f} (SE = {se_beta:.6f})")
    print(f"  t = {t_stat:.4f}, p = {p_value:.4f}")

# H2 Secondary: Separate by direction (Cuts)
h2_cuts = results_df[results_df["direction"] == "cut"][["car_m1p1", "dgs2_change"]].dropna()
if len(h2_cuts) > 2:
    y = h2_cuts["car_m1p1"].values
    X = sm.add_constant(h2_cuts["dgs2_change"].values)
    h2_cuts_model = sm.OLS(y, X).fit(cov_type="HC1", use_t=True)

    n = len(h2_cuts)
    df = n - 2
    beta = h2_cuts_model.params[1]
    se_beta = h2_cuts_model.bse[1]
    t_stat = h2_cuts_model.tvalues[1]
    p_value = h2_cuts_model.pvalues[1]
    r2 = h2_cuts_model.rsquared

    alpha = h2_cuts_model.params[0]
    ci_lower = beta - stats.t.ppf(0.975, df) * se_beta
    ci_upper = beta + stats.t.ppf(0.975, df) * se_beta

    h2_results["H2_cuts"] = {
        "hypothesis": "H2_cuts",
        "n": n,
        "df": df,
        "alpha": alpha,
        "beta": beta,
        "se_beta": se_beta,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "r2": r2,
    }
    print(f"\nH2 (Secondary): Rate Cuts")
    print(f"  N = {n}, df = {df}")
    print(f"  β = {beta:.6f} (SE = {se_beta:.6f})")
    print(f"  t = {t_stat:.4f}, p = {p_value:.4f}")

# ── 7. Export results ─────────────────────────────────────────────────────────
print("\n" + "="*70)
print("Exporting results")
print("="*70)

# Event-level results
results_df.to_csv(OUTPUT_DIR / "event_study_results.csv", index=False)
print(f"Wrote event_study_results.csv ({len(results_df)} events)")

# H1 Results Table
h1_table = pd.DataFrame([
    {
        "Hypothesis": r["hypothesis"],
        "Window": r["window"],
        "Direction": r["direction"],
        "N": r["n"],
        "df": r["df"],
        "Mean CAR (%)": r["mean_car"],
        "Std Dev (%)": r["std_car"],
        "SE (%)": r["se"],
        "t-stat": r["t_stat"],
        "p-value": r["p_value"],
        "CI Lower": r["ci_lower"],
        "CI Upper": r["ci_upper"],
    }
    for r in h1_results.values()
])
h1_table.to_csv(OUTPUT_DIR / "table_h1_mean_car.csv", index=False)
print(f"Wrote table_h1_mean_car.csv ({len(h1_table)} rows)")

# H2 Results Table
h2_table = pd.DataFrame([
    {
        "Hypothesis": r["hypothesis"],
        "N": r["n"],
        "df": r["df"],
        "Intercept": r["alpha"],
        "Beta Coefficient": r["beta"],
        "HC1 SE": r["se_beta"],
        "t-stat": r["t_stat"],
        "p-value": r["p_value"],
        "CI Lower": r["ci_lower"],
        "CI Upper": r["ci_upper"],
        "R-squared": r["r2"],
    }
    for r in h2_results.values()
])
h2_table.to_csv(OUTPUT_DIR / "table_h2_surprise_sensitivity.csv", index=False)
print(f"Wrote table_h2_surprise_sensitivity.csv ({len(h2_table)} rows)")

# Summary statistics
summary = {
    "analysis_date": datetime.now().isoformat(),
    "events_total": len(results_df),
    "events_with_dgs2": results_df["dgs2_change"].notna().sum(),
    "hikes": (results_df["direction"] == "increase").sum(),
    "cuts": (results_df["direction"] == "cut").sum(),
    "data_period": {
        "start": trading_dates[0].isoformat(),
        "end": trading_dates[-1].isoformat(),
        "trading_days": len(trading_dates),
    },
    "hypotheses_tested": {
        "H1": list(h1_results.keys()),
        "H2": list(h2_results.keys()),
    }
}

with open(OUTPUT_DIR / "summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"Wrote summary.json")

print("\n" + "="*70)
print("Replication complete!")
print(f"Results saved to {OUTPUT_DIR}")
print("="*70)
