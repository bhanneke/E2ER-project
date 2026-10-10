import json
import sqlite3
import pandas as pd
import numpy as np
import statsmodels.api as sm
from datetime import datetime, timedelta

# Load current results
with open('estimation_results.json', 'r') as f:
    results = json.load(f)

# Load CAR and DGS2 data from the cached event study results
# Since we already have CAR values computed, let's load them from the previous estimation
# and just recompute H2 with the correct p-values

# Connect to data warehouse
conn = sqlite3.connect('data.db')

# Load the data
kbe = pd.read_sql("SELECT date, close FROM kbe_prices ORDER BY date", conn)
spy = pd.read_sql("SELECT date, close FROM spy_prices ORDER BY date", conn)
dgs2_data = pd.read_sql("SELECT date, value FROM dgs2 WHERE value IS NOT NULL ORDER BY date", conn)
fomc = pd.read_sql("SELECT announcement_date, direction FROM fomc_announcement_dates ORDER BY announcement_date", conn)

# Parse dates, normalizing to naive (remove timezone info for consistency)
kbe['date'] = pd.to_datetime(kbe['date'], utc=True).dt.tz_localize(None)
spy['date'] = pd.to_datetime(spy['date'], utc=True).dt.tz_localize(None)
dgs2_data['date'] = pd.to_datetime(dgs2_data['date'], utc=True).dt.tz_localize(None)

# Compute returns
kbe['return'] = kbe['close'].pct_change() * 100
spy['return'] = spy['close'].pct_change() * 100

# Merge
merged = kbe.merge(spy, on='date', suffixes=('_kbe', '_spy')).dropna(subset=['return_kbe', 'return_spy'])

# Create a date index for easy lookup
date_list = merged['date'].tolist()
ret_kbe = merged['return_kbe'].values
ret_spy = merged['return_spy'].values

# For each FOMC event, compute CAR and DGS2 change
cars = []
ddgs2s = []
directions = []

for _, event_row in fomc.iterrows():
    ann_date_str = event_row['announcement_date']
    direction = event_row['direction']

    # Parse announcement date
    ann_date = pd.Timestamp(ann_date_str)

    # Find event day (first trading day on or after announcement)
    event_idx = None
    for i, d in enumerate(date_list):
        if pd.Timestamp(d).date() >= ann_date.date():
            event_idx = i
            break

    if event_idx is None:
        cars.append(np.nan)
        ddgs2s.append(np.nan)
        directions.append(direction)
        continue

    # Check estimation window [-250, -12]
    if event_idx < 250 or event_idx < 12:
        cars.append(np.nan)
        ddgs2s.append(np.nan)
        directions.append(direction)
        continue

    # Estimate market model on [-250, -12]
    est_start = event_idx - 250
    est_end = event_idx - 12
    X_est = sm.add_constant(ret_spy[est_start:est_end])
    y_est = ret_kbe[est_start:est_end]

    try:
        model = sm.OLS(y_est, X_est).fit()
        alpha, beta = model.params
    except:
        cars.append(np.nan)
        ddgs2s.append(np.nan)
        directions.append(direction)
        continue

    # Compute CAR over [-1, +1]
    win_start = event_idx - 1
    win_end = event_idx + 2  # +1 inclusive

    if win_end > len(ret_spy):
        cars.append(np.nan)
        ddgs2s.append(np.nan)
        directions.append(direction)
        continue

    expected = alpha + beta * ret_spy[win_start:win_end]
    ar = ret_kbe[win_start:win_end] - expected
    car = ar.sum()
    cars.append(car)

    # Get DGS2 change on day 0
    event_date = date_list[event_idx]
    dgs2_today = dgs2_data[dgs2_data['date'].dt.date == pd.Timestamp(event_date).date()]

    ddgs2 = np.nan
    if len(dgs2_today) > 0:
        # Find previous value
        dgs2_prev = dgs2_data[dgs2_data['date'] < event_date]
        if len(dgs2_prev) > 0:
            dgs2_val_today = dgs2_today['value'].iloc[0]
            dgs2_val_prev = dgs2_prev['value'].iloc[-1]
            ddgs2 = (dgs2_val_today - dgs2_val_prev) * 100  # Convert percent to basis points

    ddgs2s.append(ddgs2)
    directions.append(direction)

# Convert to arrays
cars_arr = np.array(cars)
ddgs2_arr = np.array(ddgs2s)
dir_arr = np.array(directions)

print(f"Total events: {len(cars_arr)}")
print(f"NaN in cars: {np.sum(np.isnan(cars_arr))}")
print(f"NaN in ddgs2: {np.sum(np.isnan(ddgs2_arr))}")

# Filter valid
valid_mask = ~(np.isnan(cars_arr) | np.isnan(ddgs2_arr))
cars_valid = cars_arr[valid_mask]
ddgs2_valid = ddgs2_arr[valid_mask]
dir_valid = dir_arr[valid_mask]

print(f"Valid events: {len(cars_valid)}")

if len(cars_valid) > 0:
    # H2 Pooled
    X_h2 = sm.add_constant(ddgs2_valid)
    y_h2 = cars_valid
    model_h2 = sm.OLS(y_h2, X_h2).fit(cov_type='HC1', use_t=True)

    ci = model_h2.conf_int()
    results['H2'] = {
        "specification": "H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, pooled over all 31 events",
        "hypothesis": "H2",
        "estimator": "OLS",
        "standard_errors": "HC1 (heteroskedasticity-robust via statsmodels)",
        "event_window": [-1, 1],
        "n_observations": len(y_h2),
        "df": len(y_h2) - 2,
        "coefficients": {
            "beta": {
                "estimate": float(model_h2.params[1]),
                "se": float(model_h2.bse[1]),
                "t_stat": float(model_h2.tvalues[1]),
                "p_value": float(model_h2.pvalues[1]),
                "ci_lower": float(ci[1, 0]),
                "ci_upper": float(ci[1, 1])
            }
        },
        "diagnostics": {
            "n_obs": len(y_h2),
            "df": len(y_h2) - 2,
            "r_squared": float(model_h2.rsquared),
            "adj_r_squared": float(model_h2.rsquared_adj)
        }
    }

    # H2 Hikes
    hikes_mask = (dir_valid == 'increase')
    cars_hikes = cars_valid[hikes_mask]
    ddgs2_hikes = ddgs2_valid[hikes_mask]

    if len(cars_hikes) > 0:
        X_h2_hikes = sm.add_constant(ddgs2_hikes)
        model_h2_hikes = sm.OLS(cars_hikes, X_h2_hikes).fit(cov_type='HC1', use_t=True)

        ci_hikes = model_h2_hikes.conf_int()
        results['H2_hikes'] = {
            "specification": "H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, rate hikes only (n=20)",
            "hypothesis": "H2a",
            "estimator": "OLS",
            "standard_errors": "HC1 (heteroskedasticity-robust via statsmodels)",
            "event_window": [-1, 1],
            "n_observations": len(cars_hikes),
            "df": len(cars_hikes) - 2,
            "coefficients": {
                "beta": {
                    "estimate": float(model_h2_hikes.params[1]),
                    "se": float(model_h2_hikes.bse[1]),
                    "t_stat": float(model_h2_hikes.tvalues[1]),
                    "p_value": float(model_h2_hikes.pvalues[1]),
                    "ci_lower": float(ci_hikes[1, 0]),
                    "ci_upper": float(ci_hikes[1, 1])
                }
            },
            "diagnostics": {
                "n_obs": len(cars_hikes),
                "df": len(cars_hikes) - 2,
                "r_squared": float(model_h2_hikes.rsquared),
                "adj_r_squared": float(model_h2_hikes.rsquared_adj)
            }
        }

    # H2 Cuts
    cuts_mask = (dir_valid == 'decrease')
    cars_cuts = cars_valid[cuts_mask]
    ddgs2_cuts = ddgs2_valid[cuts_mask]

    if len(cars_cuts) > 0:
        X_h2_cuts = sm.add_constant(ddgs2_cuts)
        model_h2_cuts = sm.OLS(cars_cuts, X_h2_cuts).fit(cov_type='HC1', use_t=True)

        ci_cuts = model_h2_cuts.conf_int()
        results['H2_cuts'] = {
            "specification": "H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, rate cuts only (n=11)",
            "hypothesis": "H2b",
            "estimator": "OLS",
            "standard_errors": "HC1 (heteroskedasticity-robust via statsmodels)",
            "event_window": [-1, 1],
            "n_observations": len(cars_cuts),
            "df": len(cars_cuts) - 2,
            "coefficients": {
                "beta": {
                    "estimate": float(model_h2_cuts.params[1]),
                    "se": float(model_h2_cuts.bse[1]),
                    "t_stat": float(model_h2_cuts.tvalues[1]),
                    "p_value": float(model_h2_cuts.pvalues[1]),
                    "ci_lower": float(ci_cuts[1, 0]),
                    "ci_upper": float(ci_cuts[1, 1])
                }
            },
            "diagnostics": {
                "n_obs": len(cars_cuts),
                "df": len(cars_cuts) - 2,
                "r_squared": float(model_h2_cuts.rsquared),
                "adj_r_squared": float(model_h2_cuts.rsquared_adj)
            }
        }

# Add hypothesis field to H1 results and df at top level
for key in list(results.keys()):
    if key.startswith('h1_'):
        if 'hikes' in key and 'm1p1' in key:
            results[key]['hypothesis'] = 'H1a'
            results[key]['df'] = results[key]['diagnostics']['df']
        elif 'cuts' in key and 'm1p1' in key:
            results[key]['hypothesis'] = 'H1b'
            results[key]['df'] = results[key]['diagnostics']['df']
        elif 'hikes' in key and '0p5' in key:
            results[key]['hypothesis'] = 'H1a'
            results[key]['df'] = results[key]['diagnostics']['df']
        elif 'cuts' in key and '0p5' in key:
            results[key]['hypothesis'] = 'H1b'
            results[key]['df'] = results[key]['diagnostics']['df']
        elif 'pooled' in key:
            results[key]['hypothesis'] = 'H1'
            results[key]['df'] = results[key]['diagnostics']['df']

# Write revised results
with open('estimation_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Estimation results updated")
