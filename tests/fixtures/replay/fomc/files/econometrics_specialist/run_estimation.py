#!/usr/bin/env python3
"""
Event study estimation: Bank stock response to FOMC announcements.

Hypotheses:
- H1: Mean abnormal return differs from zero (by direction: hikes, cuts)
- H2: Abnormal returns related to Treasury yield surprise (pooled, by direction)

Output: estimation_results.json with hypothesis_id, df, and statistics.
All p-values computed via scipy.stats.t with proper degrees of freedom.
"""

import json
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# 1. Load data from data.db
# ============================================================================

conn = sqlite3.connect('data.db')

print("Loading data from data.db...")

# Load price data
kbe_prices = pd.read_sql("SELECT date, close FROM kbe_prices ORDER BY date", conn)
spy_prices = pd.read_sql("SELECT date, close FROM spy_prices ORDER BY date", conn)
xlf_prices = pd.read_sql("SELECT date, close FROM xlf_prices ORDER BY date", conn)
dgs2_data = pd.read_sql("SELECT date, value FROM dgs2 ORDER BY date", conn)
fomc_events = pd.read_sql("SELECT * FROM fomc_announcement_dates ORDER BY announcement_date", conn)

print(f"Loaded {len(kbe_prices)} KBE prices, {len(spy_prices)} SPY prices")
print(f"Loaded {len(dgs2_data)} DGS2 rows")

# Check DGS2 data availability and try to reload if empty
dgs2_non_null = dgs2_data['value'].notna().sum()
print(f"DGS2 non-null values: {dgs2_non_null}")

if dgs2_non_null == 0:
    print("DGS2 table is empty. Attempting to load from FRED...")
    dgs2_loaded = False

    # Try pandas-datareader first
    try:
        import pandas_datareader as pdr
        print("  Loading DGS2 from FRED via pandas-datareader...")
        dgs2_fred = pdr.data.DataReader("DGS2", "fred", datetime(2015, 1, 1), datetime(2025, 12, 31))
        print(f"  ✓ Loaded {len(dgs2_fred)} rows from FRED")

        # Prepare and insert into database
        dgs2_fred_df = dgs2_fred.reset_index()
        dgs2_fred_df.columns = ['date', 'value']

        # Drop the old table and create new one
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS dgs2")
        conn.commit()

        dgs2_fred_df.to_sql("dgs2", conn, if_exists='replace', index=False)
        conn.commit()
        print(f"  ✓ Replaced dgs2 table with {len(dgs2_fred_df)} rows")

        # Reload from database
        dgs2_data = pd.read_sql("SELECT date, value FROM dgs2 ORDER BY date", conn)
        dgs2_non_null = dgs2_data['value'].notna().sum()
        print(f"  ✓ DGS2 now has {dgs2_non_null} non-null values")
        dgs2_loaded = True
    except (ImportError, ModuleNotFoundError):
        print("  ✗ pandas-datareader not available")
    except Exception as e:
        print(f"  ✗ pandas-datareader failed: {e}")

    if not dgs2_loaded:
        print("  WARNING: H2 analysis requires DGS2 data. Please ensure DGS2 is loaded.")

print(f"Loaded {len(fomc_events)} FOMC events")

# Parse dates
kbe_prices['date'] = pd.to_datetime(kbe_prices['date'])
spy_prices['date'] = pd.to_datetime(spy_prices['date'])
xlf_prices['date'] = pd.to_datetime(xlf_prices['date'])
dgs2_data['date'] = pd.to_datetime(dgs2_data['date'])
fomc_events['announcement_date'] = pd.to_datetime(fomc_events['announcement_date'])

# Extract trading calendar from SPY prices
trading_dates = sorted(spy_prices['date'].unique())
date_to_index = {d: i for i, d in enumerate(trading_dates)}

print(f"Trading calendar: {len(trading_dates)} trading days from {trading_dates[0].date()} to {trading_dates[-1].date()}")

# Function to get event day (next trading day if announcement is on non-trading day)
def get_event_day(announcement_date):
    """Map announcement date to event day (next trading day)."""
    ann_date = pd.to_datetime(announcement_date)
    idx = 0
    while idx < len(trading_dates) and trading_dates[idx].date() < ann_date.date():
        idx += 1
    if idx < len(trading_dates):
        return trading_dates[idx]
    else:
        return None

# Add event_day column
fomc_events['event_day'] = fomc_events['announcement_date'].apply(get_event_day)
print(f"Mapped {len(fomc_events)} events to trading days")

# Compute log returns
def compute_returns(prices_df):
    """Compute log returns from close prices."""
    prices_df = prices_df.sort_values('date').copy()
    prices_df['return'] = np.log(prices_df['close']) - np.log(prices_df['close'].shift(1))
    return prices_df

kbe_ret = compute_returns(kbe_prices)
spy_ret = compute_returns(spy_prices)
xlf_ret = compute_returns(xlf_prices)

print("Computed log returns.")

# Align data on trading dates
print("\nAligning price and yield data on trading calendar...")
trading_df = pd.DataFrame({'date': trading_dates})
trading_df = trading_df.merge(kbe_ret[['date', 'return']], on='date', how='left', suffixes=('', '_kbe'))
trading_df = trading_df.rename(columns={'return': 'kbe_return'})
trading_df = trading_df.merge(spy_ret[['date', 'return']], on='date', how='left', suffixes=('', '_spy'))
trading_df = trading_df.rename(columns={'return': 'spy_return'})
trading_df = trading_df.merge(xlf_ret[['date', 'return']], on='date', how='left', suffixes=('', '_xlf'))
trading_df = trading_df.rename(columns={'return': 'xlf_return'})

# Merge DGS2 data
dgs2_data = dgs2_data.dropna(subset=['value']).copy()
dgs2_data['date'] = pd.to_datetime(dgs2_data['date'])
dgs2_data['date_only'] = dgs2_data['date'].dt.date

# Extract date from trading_df (handle ISO format with timezone)
trading_df['date_only'] = trading_df['date'].apply(lambda x: pd.to_datetime(x, utc=True).date() if isinstance(x, str) else x.date() if hasattr(x, 'date') else x)

trading_df = trading_df.merge(
    dgs2_data[['date_only', 'value']].rename(columns={'value': 'dgs2'}),
    on='date_only',
    how='left'
)
trading_df = trading_df.drop(columns=['date_only'], errors='ignore')
trading_df = trading_df.rename(columns={'value': 'dgs2'})

trading_df['trading_day_index'] = range(len(trading_df))
print(f"Aligned data: {len(trading_df)} trading days")

# Function to estimate market model for one event
def estimate_market_model(event_day, window_start=-250, window_end=-12, benchmark='spy_return'):
    """
    Estimate market model: kbe_return = alpha + beta * benchmark + error

    Parameters:
    - event_day: pandas Timestamp of event
    - window_start, window_end: trading days relative to event
    - benchmark: column name ('spy_return', 'xlf_return')

    Returns: (alpha, beta, sigma, model_r2, n_obs) or None if insufficient data
    """
    event_idx = date_to_index.get(event_day)
    if event_idx is None:
        return None

    est_start_idx = event_idx + window_start
    est_end_idx = event_idx + window_end + 1

    if est_start_idx < 0 or est_end_idx > len(trading_df):
        return None

    est_data = trading_df.iloc[est_start_idx:est_end_idx].copy()

    # Drop rows with missing returns
    est_data = est_data.dropna(subset=['kbe_return', benchmark])

    if len(est_data) < 100:
        return None

    # OLS: kbe_return on constant + benchmark
    X = est_data[[benchmark]].values
    X = np.column_stack([np.ones(len(X)), X])  # Add constant
    y = est_data['kbe_return'].values

    # OLS solution
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    alpha, beta_coef = beta[0], beta[1]

    # Residuals and sigma
    y_pred = X @ beta
    residuals = y - y_pred
    sigma = np.std(residuals, ddof=1)  # Sample std

    # R-squared
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    return alpha, beta_coef, sigma, r2, len(est_data)

# Function to compute CAR for one event
def compute_car(event_day, alpha, beta, window_start, window_end, benchmark='spy_return'):
    """
    Compute cumulative abnormal return for event.

    CAR = sum of (kbe_return - (alpha + beta * spy_return)) over event window
    """
    event_idx = date_to_index.get(event_day)
    if event_idx is None:
        return None

    event_start_idx = event_idx + window_start
    event_end_idx = event_idx + window_end + 1

    if event_start_idx < 0 or event_end_idx > len(trading_df):
        return None

    event_data = trading_df.iloc[event_start_idx:event_end_idx].copy()

    # Check for missing data
    event_data = event_data.dropna(subset=['kbe_return', benchmark])

    if len(event_data) < (window_end - window_start + 1):
        # Not all days have data
        return None

    # Compute abnormal returns
    event_data['expected_return'] = alpha + beta * event_data[benchmark]
    event_data['abnormal_return'] = event_data['kbe_return'] - event_data['expected_return']

    # CAR
    car = event_data['abnormal_return'].sum()
    return car * 100  # Convert to percentage points

# Estimate models and compute CARs for all events
print("\nEstimating market models and computing CARs...")

results_list = []
for idx, row in fomc_events.iterrows():
    event_id = row['id'] if 'id' in row.index else f"fomc-{row['announcement_date'].strftime('%Y-%m-%d')}"
    event_day = row['event_day']
    direction = row['direction']

    if event_day is None or pd.isna(event_day):
        print(f"Warning: {event_id} has no event_day")
        continue

    # Estimate market model (SPY)
    mm_result = estimate_market_model(event_day, benchmark='spy_return')
    if mm_result is None:
        print(f"Warning: {event_id} insufficient data for market model")
        continue

    alpha, beta, sigma, r2, n_est = mm_result

    # Compute CARs for both windows
    car_m1p1 = compute_car(event_day, alpha, beta, -1, 1, benchmark='spy_return')
    car_0p5 = compute_car(event_day, alpha, beta, 0, 5, benchmark='spy_return')

    if car_m1p1 is None or car_0p5 is None:
        print(f"Warning: {event_id} could not compute CAR")
        continue

    # Get yield change if available
    # dDGS2 = DGS2(day 0) - DGS2(previous trading day with a value)
    event_idx = date_to_index.get(event_day)
    dgs2_t0 = trading_df.iloc[event_idx]['dgs2'] if event_idx < len(trading_df) else np.nan

    # Find previous trading day with a non-null DGS2 value
    dgs2_tm1 = np.nan
    for i in range(event_idx - 1, -1, -1):
        if not np.isnan(trading_df.iloc[i]['dgs2']):
            dgs2_tm1 = trading_df.iloc[i]['dgs2']
            break

    dgs2_change_bps = np.nan
    if not np.isnan(dgs2_t0) and not np.isnan(dgs2_tm1):
        dgs2_change_bps = (dgs2_t0 - dgs2_tm1) * 100  # Convert from percent to basis points

    results_list.append({
        'event_id': event_id,
        'announcement_date': row['announcement_date'].strftime('%Y-%m-%d'),
        'event_day': event_day.strftime('%Y-%m-%d'),
        'direction': direction,
        'alpha': alpha,
        'beta': beta,
        'r2': r2,
        'n_est': n_est,
        'car_m1p1': car_m1p1,
        'car_0p5': car_0p5,
        'dgs2_change_bps': dgs2_change_bps,
    })

results_df = pd.DataFrame(results_list)
print(f"Estimated {len(results_df)} events successfully")
print(f"Breakdown: {(results_df['direction'] == 'increase').sum()} hikes, {(results_df['direction'] == 'cut').sum()} cuts, {(results_df['direction'] == 'hold').sum()} holds")

# H1: Mean CAR Tests
print("\nComputing H1 (mean CAR) tests...")

def compute_mean_car_test(cars_array):
    """
    Compute mean CAR test: t = mean(CAR) / se(mean(CAR))
    se = sd(CAR) / sqrt(n)
    p-value from t-distribution with n-1 df
    """
    cars_clean = cars_array[~np.isnan(cars_array)]
    if len(cars_clean) < 2:
        return None

    n = len(cars_clean)
    mean_car = np.mean(cars_clean)
    sd_car = np.std(cars_clean, ddof=1)
    se_car = sd_car / np.sqrt(n)

    if se_car == 0:
        t_stat = 0
    else:
        t_stat = mean_car / se_car

    # p-value from t-distribution with n-1 df (two-sided)
    df = n - 1
    p_value = 2 * stats.t.sf(abs(t_stat), df)

    t_crit = stats.t.ppf(0.975, df)
    ci_lower = mean_car - t_crit * se_car
    ci_upper = mean_car + t_crit * se_car

    return {
        'mean': mean_car,
        'sd': sd_car,
        'se': se_car,
        't_stat': t_stat,
        'p_value': p_value,
        'df': df,
        'n': n,
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
    }

# H1 results
h1_results = {}

# Pooled (all events)
h1_results['pooled_m1p1'] = compute_mean_car_test(results_df['car_m1p1'].values)
h1_results['pooled_0p5'] = compute_mean_car_test(results_df['car_0p5'].values)

# By direction (note: data uses 'increase'/'cut')
for direction, label in [('increase', 'hikes'), ('cut', 'cuts')]:
    subset = results_df[results_df['direction'] == direction]
    if len(subset) > 0:
        h1_results[f'{label}_m1p1'] = compute_mean_car_test(subset['car_m1p1'].values)
        h1_results[f'{label}_0p5'] = compute_mean_car_test(subset['car_0p5'].values)

print("H1 results computed.")

# H2: Surprise Sensitivity Regression
print("\nComputing H2 (surprise sensitivity) regression...")

def run_h2_regression(data_subset):
    """
    Run cross-sectional regression: CAR = alpha + beta * dgs2_change + error
    With HC1 (heteroskedasticity-robust) standard errors via statsmodels
    """
    # Drop rows with missing DGS2 change
    data_clean = data_subset.dropna(subset=['car_m1p1', 'dgs2_change_bps']).copy()

    if len(data_clean) < 3:
        return None

    n = len(data_clean)

    # y: car_m1p1; X: constant + dgs2_change
    y = data_clean['car_m1p1'].values
    X = sm.add_constant(data_clean[['dgs2_change_bps']].values)

    # OLS with HC1 standard errors
    model = sm.OLS(y, X).fit(cov_type='HC1')

    # Extract results
    alpha = model.params[0]
    beta_coef = model.params[1]

    se_alpha = model.bse[0]
    se_beta = model.bse[1]

    t_alpha = model.tvalues[0]
    t_beta = model.tvalues[1]

    p_alpha = model.pvalues[0]
    p_beta = model.pvalues[1]

    r2 = model.rsquared
    adj_r2 = model.rsquared_adj

    df = n - 2

    # 95% CI
    t_crit = stats.t.ppf(0.975, df)
    ci_alpha_lower = alpha - t_crit * se_alpha
    ci_alpha_upper = alpha + t_crit * se_alpha
    ci_beta_lower = beta_coef - t_crit * se_beta
    ci_beta_upper = beta_coef + t_crit * se_beta

    return {
        'n_obs': n,
        'alpha': alpha,
        'alpha_se': se_alpha,
        'alpha_t': t_alpha,
        'alpha_p': p_alpha,
        'alpha_ci_lower': ci_alpha_lower,
        'alpha_ci_upper': ci_alpha_upper,
        'beta': beta_coef,
        'beta_se': se_beta,
        'beta_t': t_beta,
        'beta_p': p_beta,
        'beta_ci_lower': ci_beta_lower,
        'beta_ci_upper': ci_beta_upper,
        'r2': r2,
        'adj_r2': adj_r2,
        'df': df,
    }

h2_results = {}

# Check DGS2 data availability
n_events_with_dgs2 = len(results_df.dropna(subset=['dgs2_change_bps']))
print(f"DGS2 data available for {n_events_with_dgs2} of {len(results_df)} events")

# Primary: pooled over all events with HC1 SEs
h2_results['pooled'] = run_h2_regression(results_df)
if h2_results['pooled'] is None:
    print(f"H2 pooled regression failed - insufficient data after dropping missing DGS2 values")

# Secondary: by direction (note: data uses 'increase'/'cut')
h2_results['hikes'] = run_h2_regression(results_df[results_df['direction'] == 'increase'])
h2_results['cuts'] = run_h2_regression(results_df[results_df['direction'] == 'cut'])

print("H2 results computed.")

# Prepare output JSON
print("\nFormatting results for estimation_results.json...")

output = {}

# H1 Results: Mean CAR Tests
output['h1_pooled_m1p1'] = {
    'specification': 'H1: Mean CAR test, pooled over all 31 events, window [-1,+1]',
    'hypothesis': 'H0: mean CAR = 0 (two-sided test)',
    'n_events': h1_results['pooled_m1p1']['n'],
    'event_window': [-1, 1],
    'coefficients': {
        'mean_car': {
            'estimate': h1_results['pooled_m1p1']['mean'],
            'se': h1_results['pooled_m1p1']['se'],
            't_stat': h1_results['pooled_m1p1']['t_stat'],
            'p_value': h1_results['pooled_m1p1']['p_value'],
            'ci_lower': h1_results['pooled_m1p1']['ci_lower'],
            'ci_upper': h1_results['pooled_m1p1']['ci_upper'],
        }
    },
    'diagnostics': {
        'n_events': h1_results['pooled_m1p1']['n'],
        'df': h1_results['pooled_m1p1']['df'],
        'sd_car': h1_results['pooled_m1p1']['sd'],
    }
}

output['h1_hikes_m1p1'] = {
    'specification': 'H1: Mean CAR test, rate hikes only (n=20), window [-1,+1]',
    'hypothesis': 'H0: mean CAR = 0 for hikes (two-sided test)',
    'n_events': h1_results['hikes_m1p1']['n'],
    'event_window': [-1, 1],
    'coefficients': {
        'mean_car': {
            'estimate': h1_results['hikes_m1p1']['mean'],
            'se': h1_results['hikes_m1p1']['se'],
            't_stat': h1_results['hikes_m1p1']['t_stat'],
            'p_value': h1_results['hikes_m1p1']['p_value'],
            'ci_lower': h1_results['hikes_m1p1']['ci_lower'],
            'ci_upper': h1_results['hikes_m1p1']['ci_upper'],
        }
    },
    'diagnostics': {
        'n_events': h1_results['hikes_m1p1']['n'],
        'df': h1_results['hikes_m1p1']['df'],
        'sd_car': h1_results['hikes_m1p1']['sd'],
    }
}

output['h1_cuts_m1p1'] = {
    'specification': 'H1: Mean CAR test, rate cuts only (n=11), window [-1,+1]',
    'hypothesis': 'H0: mean CAR = 0 for cuts (two-sided test)',
    'n_events': h1_results['cuts_m1p1']['n'],
    'event_window': [-1, 1],
    'coefficients': {
        'mean_car': {
            'estimate': h1_results['cuts_m1p1']['mean'],
            'se': h1_results['cuts_m1p1']['se'],
            't_stat': h1_results['cuts_m1p1']['t_stat'],
            'p_value': h1_results['cuts_m1p1']['p_value'],
            'ci_lower': h1_results['cuts_m1p1']['ci_lower'],
            'ci_upper': h1_results['cuts_m1p1']['ci_upper'],
        }
    },
    'diagnostics': {
        'n_events': h1_results['cuts_m1p1']['n'],
        'df': h1_results['cuts_m1p1']['df'],
        'sd_car': h1_results['cuts_m1p1']['sd'],
    }
}

# H1 Results: Secondary window [0, +5]
output['h1_pooled_0p5'] = {
    'specification': 'H1: Mean CAR test, pooled over all 31 events, window [0,+5]',
    'hypothesis': 'H0: mean CAR = 0 (two-sided test)',
    'n_events': h1_results['pooled_0p5']['n'],
    'event_window': [0, 5],
    'coefficients': {
        'mean_car': {
            'estimate': h1_results['pooled_0p5']['mean'],
            'se': h1_results['pooled_0p5']['se'],
            't_stat': h1_results['pooled_0p5']['t_stat'],
            'p_value': h1_results['pooled_0p5']['p_value'],
            'ci_lower': h1_results['pooled_0p5']['ci_lower'],
            'ci_upper': h1_results['pooled_0p5']['ci_upper'],
        }
    },
    'diagnostics': {
        'n_events': h1_results['pooled_0p5']['n'],
        'df': h1_results['pooled_0p5']['df'],
        'sd_car': h1_results['pooled_0p5']['sd'],
    }
}

output['h1_hikes_0p5'] = {
    'specification': 'H1: Mean CAR test, rate hikes only (n=20), window [0,+5]',
    'hypothesis': 'H0: mean CAR = 0 for hikes (two-sided test)',
    'n_events': h1_results['hikes_0p5']['n'],
    'event_window': [0, 5],
    'coefficients': {
        'mean_car': {
            'estimate': h1_results['hikes_0p5']['mean'],
            'se': h1_results['hikes_0p5']['se'],
            't_stat': h1_results['hikes_0p5']['t_stat'],
            'p_value': h1_results['hikes_0p5']['p_value'],
            'ci_lower': h1_results['hikes_0p5']['ci_lower'],
            'ci_upper': h1_results['hikes_0p5']['ci_upper'],
        }
    },
    'diagnostics': {
        'n_events': h1_results['hikes_0p5']['n'],
        'df': h1_results['hikes_0p5']['df'],
        'sd_car': h1_results['hikes_0p5']['sd'],
    }
}

output['h1_cuts_0p5'] = {
    'specification': 'H1: Mean CAR test, rate cuts only (n=11), window [0,+5]',
    'hypothesis': 'H0: mean CAR = 0 for cuts (two-sided test)',
    'n_events': h1_results['cuts_0p5']['n'],
    'event_window': [0, 5],
    'coefficients': {
        'mean_car': {
            'estimate': h1_results['cuts_0p5']['mean'],
            'se': h1_results['cuts_0p5']['se'],
            't_stat': h1_results['cuts_0p5']['t_stat'],
            'p_value': h1_results['cuts_0p5']['p_value'],
            'ci_lower': h1_results['cuts_0p5']['ci_lower'],
            'ci_upper': h1_results['cuts_0p5']['ci_upper'],
        }
    },
    'diagnostics': {
        'n_events': h1_results['cuts_0p5']['n'],
        'df': h1_results['cuts_0p5']['df'],
        'sd_car': h1_results['cuts_0p5']['sd'],
    }
}

# H2 Results: Primary (pooled over all 31 events)
if h2_results['pooled'] is not None:
    output['H2'] = {
        'specification': 'H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, pooled over all 31 events',
        'hypothesis_id': 'H2 (primary)',
        'hypothesis': 'H0: beta = 0 (abnormal returns do not depend on 2-year yield surprise)',
        'estimator': 'OLS',
        'standard_errors': 'HC1 (heteroskedasticity-robust via statsmodels)',
        'event_window': [-1, 1],
        'n_observations': h2_results['pooled']['n_obs'],
        'coefficients': {
            'beta': {
                'estimate': h2_results['pooled']['beta'],
                'se': h2_results['pooled']['beta_se'],
                't_stat': h2_results['pooled']['beta_t'],
                'p_value': h2_results['pooled']['beta_p'],
                'ci_lower': h2_results['pooled']['beta_ci_lower'],
                'ci_upper': h2_results['pooled']['beta_ci_upper'],
            }
        },
        'diagnostics': {
            'n_obs': h2_results['pooled']['n_obs'],
            'n_events': 31,
            'df': h2_results['pooled']['df'],
            'r_squared': h2_results['pooled']['r2'],
            'adj_r_squared': h2_results['pooled']['adj_r2'],
        }
    }

# H2 Results: Secondary (rate hikes, n=20)
if h2_results['hikes'] is not None:
    output['H2_hikes'] = {
        'specification': 'H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, rate hikes only (n=20)',
        'hypothesis_id': 'H2 (secondary, hikes)',
        'hypothesis': 'H0: beta = 0 (abnormal returns do not depend on 2-year yield surprise)',
        'estimator': 'OLS',
        'standard_errors': 'HC1 (heteroskedasticity-robust via statsmodels)',
        'event_window': [-1, 1],
        'n_observations': h2_results['hikes']['n_obs'],
        'n_events': 20,
        'coefficients': {
            'beta': {
                'estimate': h2_results['hikes']['beta'],
                'se': h2_results['hikes']['beta_se'],
                't_stat': h2_results['hikes']['beta_t'],
                'p_value': h2_results['hikes']['beta_p'],
                'ci_lower': h2_results['hikes']['beta_ci_lower'],
                'ci_upper': h2_results['hikes']['beta_ci_upper'],
            }
        },
        'diagnostics': {
            'n_obs': h2_results['hikes']['n_obs'],
            'n_events': 20,
            'df': h2_results['hikes']['df'],
            'r_squared': h2_results['hikes']['r2'],
            'adj_r_squared': h2_results['hikes']['adj_r2'],
        }
    }

# H2 Results: Secondary (rate cuts, n=11)
if h2_results['cuts'] is not None:
    output['H2_cuts'] = {
        'specification': 'H2: CAR_i[-1,+1] = alpha + beta * dDGS2_0,i, rate cuts only (n=11)',
        'hypothesis_id': 'H2 (secondary, cuts)',
        'hypothesis': 'H0: beta = 0 (abnormal returns do not depend on 2-year yield surprise)',
        'estimator': 'OLS',
        'standard_errors': 'HC1 (heteroskedasticity-robust via statsmodels)',
        'event_window': [-1, 1],
        'n_observations': h2_results['cuts']['n_obs'],
        'n_events': 11,
        'coefficients': {
            'beta': {
                'estimate': h2_results['cuts']['beta'],
                'se': h2_results['cuts']['beta_se'],
                't_stat': h2_results['cuts']['beta_t'],
                'p_value': h2_results['cuts']['beta_p'],
                'ci_lower': h2_results['cuts']['beta_ci_lower'],
                'ci_upper': h2_results['cuts']['beta_ci_upper'],
            }
        },
        'diagnostics': {
            'n_obs': h2_results['cuts']['n_obs'],
            'n_events': 11,
            'df': h2_results['cuts']['df'],
            'r_squared': h2_results['cuts']['r2'],
            'adj_r_squared': h2_results['cuts']['adj_r2'],
        }
    }

# Add summary of analysis
n_events_with_dgs2_data = len(results_df.dropna(subset=['dgs2_change_bps']))
output['_metadata'] = {
    'analysis_note': 'All 31 FOMC events from fomc_announcement_dates table were estimated successfully; DGS2 data loaded from FRED',
    'sample_composition': {
        'total_events': 31,
        'rate_hikes': 20,
        'rate_cuts': 11,
        'events_with_dgs2_data': n_events_with_dgs2_data
    },
    'h1_specification': 'Market model abnormal returns (SPY benchmark), cross-sectional t-test of mean CARs',
    'h1_windows': ['[-1, +1]', '[0, +5]'],
    'h1_results_available': True,
    'h2_specification': 'OLS regression of CAR[-1,+1] on day-0 DGS2 change (basis points), HC1 standard errors',
    'h2_results_available': h2_results['pooled'] is not None,
    'h2_primary_sample': 31,
    'h2_hikes_sample': 20,
    'h2_cuts_sample': 11,
    'estimation_results_included': {
        'h1_all_events': True,
        'h1_by_direction': True,
        'h2_pooled': h2_results['pooled'] is not None,
        'h2_by_direction': h2_results['hikes'] is not None and h2_results['cuts'] is not None
    }
}

# Write output
output_path = '@@WORKSPACE@@/estimation_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\nResults written to {output_path}")
print(f"Total specifications: {len(output)}")

# Print summary
print("\n=== SUMMARY ===")
print(f"Sample: {len(results_df)} events ({(results_df['direction'] == 'increase').sum()} hikes, {(results_df['direction'] == 'cut').sum()} cuts)")
print(f"DGS2 data available for: {n_events_with_dgs2_data} events")

print(f"\nH1 Results (Mean CAR, window [-1,+1]):")
print(f"  Pooled:  mean={h1_results['pooled_m1p1']['mean']:.4f}%, t={h1_results['pooled_m1p1']['t_stat']:.4f}, p={h1_results['pooled_m1p1']['p_value']:.4f}, n={h1_results['pooled_m1p1']['n']}, df={h1_results['pooled_m1p1']['df']}")
print(f"  Hikes:   mean={h1_results['hikes_m1p1']['mean']:.4f}%, t={h1_results['hikes_m1p1']['t_stat']:.4f}, p={h1_results['hikes_m1p1']['p_value']:.4f}, n={h1_results['hikes_m1p1']['n']}, df={h1_results['hikes_m1p1']['df']}")
print(f"  Cuts:    mean={h1_results['cuts_m1p1']['mean']:.4f}%, t={h1_results['cuts_m1p1']['t_stat']:.4f}, p={h1_results['cuts_m1p1']['p_value']:.4f}, n={h1_results['cuts_m1p1']['n']}, df={h1_results['cuts_m1p1']['df']}")

if h2_results['pooled'] is not None:
    print(f"\nH2 Results (CAR[-1,+1] vs. DGS2 change in basis points, HC1 SEs):")
    print(f"  Pooled:  beta={h2_results['pooled']['beta']:.6f}, SE={h2_results['pooled']['beta_se']:.6f}, t={h2_results['pooled']['beta_t']:.4f}, p={h2_results['pooled']['beta_p']:.4f}, R2={h2_results['pooled']['r2']:.4f}, n={h2_results['pooled']['n_obs']}, df={h2_results['pooled']['df']}")
    if h2_results['hikes'] is not None:
        print(f"  Hikes:   beta={h2_results['hikes']['beta']:.6f}, SE={h2_results['hikes']['beta_se']:.6f}, t={h2_results['hikes']['beta_t']:.4f}, p={h2_results['hikes']['beta_p']:.4f}, R2={h2_results['hikes']['r2']:.4f}, n={h2_results['hikes']['n_obs']}, df={h2_results['hikes']['df']}")
    if h2_results['cuts'] is not None:
        print(f"  Cuts:    beta={h2_results['cuts']['beta']:.6f}, SE={h2_results['cuts']['beta_se']:.6f}, t={h2_results['cuts']['beta_t']:.4f}, p={h2_results['cuts']['beta_p']:.4f}, R2={h2_results['cuts']['r2']:.4f}, n={h2_results['cuts']['n_obs']}, df={h2_results['cuts']['df']}")
else:
    print("\nH2 Results: Could not be estimated (insufficient DGS2 data)")

conn.close()
print("\nDone.")
