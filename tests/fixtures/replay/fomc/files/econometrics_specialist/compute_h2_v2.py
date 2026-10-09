import json
import sqlite3
import pandas as pd
import numpy as np
import statsmodels.api as sm

# Load current results to keep H1 intact
with open('estimation_results.json', 'r') as f:
    results = json.load(f)

# Load data
conn = sqlite3.connect('data.db')
kbe = pd.read_sql("SELECT date, close FROM kbe_prices ORDER BY date", conn)
spy = pd.read_sql("SELECT date, close FROM spy_prices ORDER BY date", conn)
dgs2_raw = pd.read_sql("SELECT date, value FROM dgs2 WHERE value IS NOT NULL ORDER BY date", conn)
fomc = pd.read_sql("SELECT announcement_date, direction FROM fomc_announcement_dates ORDER BY announcement_date", conn)
conn.close()

# Normalize dates to naive datetime, sorting out timezone issues
kbe['date'] = pd.to_datetime(kbe['date'], utc=True).dt.tz_localize(None).dt.normalize()
spy['date'] = pd.to_datetime(spy['date'], utc=True).dt.tz_localize(None).dt.normalize()
dgs2_raw['date'] = pd.to_datetime(dgs2_raw['date'], utc=True).dt.tz_localize(None).dt.normalize()

# Deduplicate in case there are multiple rows per day (shouldn't be)
dgs2_raw = dgs2_raw.drop_duplicates(subset=['date'], keep='last')
dgs2_raw = dgs2_raw.sort_values('date')

# Compute returns
kbe['return'] = kbe['close'].pct_change() * 100
spy['return'] = spy['close'].pct_change() * 100

# Merge
merged = kbe.merge(spy, on='date', suffixes=('_kbe', '_spy')).dropna(subset=['return_kbe', 'return_spy'])

# Create arrays
date_list = merged['date'].tolist()
ret_kbe = merged['return_kbe'].values
ret_spy = merged['return_spy'].values

print(f"Merged data has {len(merged)} rows")
print(f"DGS2 data has {len(dgs2_raw)} rows")

# For each event, compute CAR and DGS2
cars_data = []

for event_idx, event_row in fomc.iterrows():
    ann_date = pd.Timestamp(event_row['announcement_date']).normalize()
    direction = event_row['direction']

    # Find event day (first trading day >= announcement date)
    event_date_idx = None
    for i, d in enumerate(date_list):
        if pd.Timestamp(d) >= ann_date:
            event_date_idx = i
            break

    if event_date_idx is None or event_date_idx < 250:
        continue

    # Market model estimation window [-250, -12]
    est_start = event_date_idx - 250
    est_end = event_date_idx - 12

    X_est = sm.add_constant(ret_spy[est_start:est_end])
    y_est = ret_kbe[est_start:est_end]

    try:
        model = sm.OLS(y_est, X_est).fit()
        alpha, beta = model.params
    except:
        continue

    # CAR over [-1, +1]
    win_start = event_date_idx - 1
    win_end = event_date_idx + 2  # +1 inclusive

    if win_end > len(ret_spy):
        continue

    expected = alpha + beta * ret_spy[win_start:win_end]
    ar = ret_kbe[win_start:win_end] - expected
    car = ar.sum()

    # DGS2 change: from previous trading day to event day
    event_date = date_list[event_date_idx]
    event_date_ts = pd.Timestamp(event_date)

    # Get DGS2 value on event day
    dgs2_today_rows = dgs2_raw[dgs2_raw['date'] == event_date_ts]
    if len(dgs2_today_rows) == 0:
        # Event day is not in DGS2 data (maybe a holiday), skip
        continue

    dgs2_today_val = dgs2_today_rows['value'].iloc[0]

    # Get DGS2 value on previous trading day
    # The previous trading day is event_date_idx - 1 in our merged data
    prev_event_date = date_list[event_date_idx - 1]
    prev_event_date_ts = pd.Timestamp(prev_event_date)

    dgs2_prev_rows = dgs2_raw[dgs2_raw['date'] == prev_event_date_ts]
    if len(dgs2_prev_rows) == 0:
        # Previous day is not in DGS2 data, look further back
        dgs2_prev_rows = dgs2_raw[dgs2_raw['date'] < event_date_ts]
        if len(dgs2_prev_rows) == 0:
            continue

    dgs2_prev_val = dgs2_prev_rows['value'].iloc[-1]

    # Compute change in basis points
    ddgs2 = (dgs2_today_val - dgs2_prev_val) * 100

    cars_data.append({
        'car': car,
        'ddgs2': ddgs2,
        'direction': direction,
        'event': event_row['announcement_date'],
        'event_date': event_date,
        'dgs2_today': dgs2_today_val,
        'dgs2_prev': dgs2_prev_val
    })

# Convert to DataFrame
cars_df = pd.DataFrame(cars_data)
print(f"\nSuccessfully computed {len(cars_df)} events")
print(f"Unique directions: {cars_df['direction'].unique()}")
print(f"Hikes: {len(cars_df[cars_df['direction'] == 'increase'])}, Cuts: {len(cars_df[cars_df['direction'] == 'cut'])}")
print(f"\nPooled DGS2 mean: {cars_df['ddgs2'].mean():.4f}, std: {cars_df['ddgs2'].std():.4f}")
print(f"Hikes DGS2 mean: {cars_df[cars_df['direction'] == 'increase']['ddgs2'].mean():.4f}, std: {cars_df[cars_df['direction'] == 'increase']['ddgs2'].std():.4f}")
print(f"Cuts DGS2 mean: {cars_df[cars_df['direction'] == 'cut']['ddgs2'].mean():.4f}, std: {cars_df[cars_df['direction'] == 'cut']['ddgs2'].std():.4f}")
print(f"\nSample DGS2 values:\n{cars_df[['event', 'direction', 'dgs2_prev', 'dgs2_today', 'ddgs2']].head(15)}")

# H2 Pooled
X_pooled = sm.add_constant(cars_df['ddgs2'].values)
y_pooled = cars_df['car'].values
model_pooled = sm.OLS(y_pooled, X_pooled).fit(cov_type='HC1', use_t=True)
ci_pooled = model_pooled.conf_int()

results['H2'] = {
    "specification": "H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, pooled over all 31 events",
    "hypothesis": "H2",
    "estimator": "OLS",
    "standard_errors": "HC1 (heteroskedasticity-robust via statsmodels)",
    "event_window": [-1, 1],
    "n_observations": len(y_pooled),
    "df": len(y_pooled) - 2,
    "coefficients": {
        "beta": {
            "estimate": float(model_pooled.params[1]),
            "se": float(model_pooled.bse[1]),
            "t_stat": float(model_pooled.tvalues[1]),
            "p_value": float(model_pooled.pvalues[1]),
            "ci_lower": float(ci_pooled[1, 0]),
            "ci_upper": float(ci_pooled[1, 1])
        }
    },
    "diagnostics": {
        "n_obs": len(y_pooled),
        "df": len(y_pooled) - 2,
        "r_squared": float(model_pooled.rsquared),
        "adj_r_squared": float(model_pooled.rsquared_adj)
    }
}

# H2 Hikes
hikes_df = cars_df[cars_df['direction'] == 'increase']
X_hikes = sm.add_constant(hikes_df['ddgs2'].values)
y_hikes = hikes_df['car'].values
model_hikes = sm.OLS(y_hikes, X_hikes).fit(cov_type='HC1', use_t=True)
ci_hikes = model_hikes.conf_int()

results['H2_hikes'] = {
    "specification": "H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, rate hikes only (n=20)",
    "hypothesis": "H2a",
    "estimator": "OLS",
    "standard_errors": "HC1 (heteroskedasticity-robust via statsmodels)",
    "event_window": [-1, 1],
    "n_observations": len(y_hikes),
    "df": len(y_hikes) - 2,
    "coefficients": {
        "beta": {
            "estimate": float(model_hikes.params[1]),
            "se": float(model_hikes.bse[1]),
            "t_stat": float(model_hikes.tvalues[1]),
            "p_value": float(model_hikes.pvalues[1]),
            "ci_lower": float(ci_hikes[1, 0]),
            "ci_upper": float(ci_hikes[1, 1])
        }
    },
    "diagnostics": {
        "n_obs": len(y_hikes),
        "df": len(y_hikes) - 2,
        "r_squared": float(model_hikes.rsquared),
        "adj_r_squared": float(model_hikes.rsquared_adj)
    }
}

# H2 Cuts
cuts_df = cars_df[cars_df['direction'] == 'cut']
if len(cuts_df) > 0:
    X_cuts = sm.add_constant(cuts_df['ddgs2'].values)
    y_cuts = cuts_df['car'].values
    model_cuts = sm.OLS(y_cuts, X_cuts).fit(cov_type='HC1', use_t=True)
    ci_cuts = model_cuts.conf_int()

    results['H2_cuts'] = {
        "specification": "H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, rate cuts only (n=11)",
        "hypothesis": "H2b",
        "estimator": "OLS",
        "standard_errors": "HC1 (heteroskedasticity-robust via statsmodels)",
        "event_window": [-1, 1],
        "n_observations": len(y_cuts),
        "df": len(y_cuts) - 2,
        "coefficients": {
            "beta": {
                "estimate": float(model_cuts.params[1]),
                "se": float(model_cuts.bse[1]),
                "t_stat": float(model_cuts.tvalues[1]),
                "p_value": float(model_cuts.pvalues[1]),
                "ci_lower": float(ci_cuts[1, 0]),
                "ci_upper": float(ci_cuts[1, 1])
            }
        },
        "diagnostics": {
            "n_obs": len(y_cuts),
            "df": len(y_cuts) - 2,
            "r_squared": float(model_cuts.rsquared),
            "adj_r_squared": float(model_cuts.rsquared_adj)
        }
    }

# Write results
with open('estimation_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\n\nH2 results updated with correct use_t=True p-values")
print(f"H2 pooled (n={len(y_pooled)}): beta={results['H2']['coefficients']['beta']['estimate']:.6f}, p={results['H2']['coefficients']['beta']['p_value']:.6f}")
print(f"H2 hikes (n={len(y_hikes)}): beta={results['H2_hikes']['coefficients']['beta']['estimate']:.6f}, p={results['H2_hikes']['coefficients']['beta']['p_value']:.6f}")
if 'H2_cuts' in results:
    print(f"H2 cuts (n={len(y_cuts)}): beta={results['H2_cuts']['coefficients']['beta']['estimate']:.6f}, p={results['H2_cuts']['coefficients']['beta']['p_value']:.6f}")
