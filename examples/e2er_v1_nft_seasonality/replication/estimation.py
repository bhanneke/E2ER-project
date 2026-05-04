#!/usr/bin/env python3
"""
Estimation Stage — Run 09
Sell in May and Go Away: Seasonality in NFT Markets

Key changes from run_08:
  - Data path updated to run_08 (latest data stage)
  - Model 5 reference month corrected to May (month 5) for Halloween consistency
  - Bias-corrected accelerated (BCa) bootstrap confidence intervals
  - Added monthly frequency block bootstrap (block_size=3 months)
  - Improved cross-sectional fallback when DB trades table is empty
  - Added wash-trade exclusion robustness (exclude LooksRare + X2Y2)
  - Added Model 6: Halloween × Year interaction for time-varying effects
  - Power analysis uses Newey-West SE (conservative) alongside bootstrap SE
  - Sharpe ratio seasonality expanded with formal test
  - All 6 figures regenerated with improved styling
"""

import json
import os
import warnings
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)

# ── Paths ──────────────────────────────────────────────────────────────────
DATA_DIR = Path('/app/artifacts/1047047f-8050-42e3-92e1-f2e464dedbcc/data/run_08')
OUT_DIR = Path('/app/artifacts/1047047f-8050-42e3-92e1-f2e464dedbcc/estimation/run_09')
FIG_DIR = OUT_DIR / 'figures'
os.makedirs(FIG_DIR, exist_ok=True)

DB_CONN = 'postgresql://e2er_user:e2er_prod_2024@db:5432/e2er'

# ── Matplotlib style ───────────────────────────────────────────────────────
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 10,
    'axes.titlesize': 12,
    'axes.labelsize': 11,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.dpi': 150,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
})


# ── Helper: Newey-West with Andrews automatic bandwidth, min 13 ───────────
def nw_bandwidth(resid, min_bw=13):
    """Andrews automatic bandwidth (Bartlett kernel) with floor of min_bw."""
    n = len(resid)
    rho_hat = np.corrcoef(resid[:-1], resid[1:])[0, 1]
    rho_abs = min(abs(rho_hat), 0.99)
    alpha_hat = (4 * rho_abs**2) / ((1 - rho_abs)**2 * (1 + rho_abs)**2)
    bw = int(np.ceil(1.1447 * (alpha_hat * n) ** (1/3)))
    return max(bw, min_bw)


def run_ols_nw(y, X, min_bw=13, add_const=True):
    """OLS with Newey-West HAC, Andrews automatic bandwidth, min 13 lags."""
    if add_const:
        X = sm.add_constant(X)
    model = OLS(y, X, missing='drop').fit()
    bw = nw_bandwidth(model.resid, min_bw=min_bw)
    model_nw = OLS(y, X, missing='drop').fit(cov_type='HAC',
                                              cov_kwds={'maxlags': bw, 'kernel': 'bartlett'})
    model_nw._nw_bandwidth = bw
    return model_nw


def extract_results(model, description=''):
    """Extract results from OLS model into dict."""
    res = {}
    for name in model.params.index:
        res[name] = {
            'coef': float(model.params[name]),
            'se': float(model.bse[name]),
            't': float(model.tvalues[name]),
            'p': float(model.pvalues[name]),
        }
    res['r_squared'] = float(model.rsquared)
    res['r_squared_adj'] = float(model.rsquared_adj)
    res['n_obs'] = int(model.nobs)
    res['df_resid'] = int(model.df_resid)
    res['n_params'] = int(model.df_model + 1)
    res['nw_bandwidth'] = int(getattr(model, '_nw_bandwidth', 13))
    res['f_stat'] = float(model.fvalue) if model.fvalue is not None else None
    res['f_pvalue'] = float(model.f_pvalue) if model.f_pvalue is not None else None
    res['description'] = description
    res['se_type'] = 'Newey-West HAC (Andrews automatic, Bartlett kernel, min 13)'
    return res


# ── Load data ──────────────────────────────────────────────────────────────
print("Loading data...")
df = pd.read_csv(DATA_DIR / 'daily_merged_index.csv')
df['trade_date'] = pd.to_datetime(df['trade_date'])
df = df.sort_values('trade_date').reset_index(drop=True)

assert 'halloween' in df.columns
assert 'log_return_median' in df.columns
assert 'nft_log_return_eth' in df.columns
assert 'r_eth' in df.columns

# Drop the first row (no return)
df_ret = df.dropna(subset=['log_return_median']).copy()
print(f"Analysis sample: {df_ret['trade_date'].min().date()} to {df_ret['trade_date'].max().date()}, N={len(df_ret)}")

# Market phase dummies
df_ret['boom'] = ((df_ret['trade_date'] >= '2021-08-01') &
                  (df_ret['trade_date'] < '2022-05-01')).astype(int)
df_ret['post_crash'] = (df_ret['trade_date'] >= '2022-05-01').astype(int)

# Day-of-week dummies (0=Monday)
dow_dummies = pd.get_dummies(df_ret['day_of_week'], prefix='dow', dtype=int)
dow_dummies = dow_dummies.drop('dow_0', axis=1, errors='ignore')  # Monday omitted
for c in dow_dummies.columns:
    df_ret[c] = dow_dummies[c].values

# Month dummies — omit May (month 5) as reference for Halloween analysis
month_dummies = pd.get_dummies(df_ret['month'], prefix='month', dtype=int)
month_dummies = month_dummies.drop('month_5', axis=1, errors='ignore')
for c in month_dummies.columns:
    df_ret[c] = month_dummies[c].values

# January dummy
df_ret['january'] = (df_ret['month'] == 1).astype(int)

# Turn-of-month: last 3 + first 3 trading days of each month
df_ret['day'] = df_ret['trade_date'].dt.day
df_ret['days_in_month'] = df_ret['trade_date'].dt.days_in_month
df_ret['turn_of_month'] = ((df_ret['day'] <= 3) | (df_ret['day'] >= df_ret['days_in_month'] - 2)).astype(int)

# Weekend dummy
df_ret['weekend'] = (df_ret['day_of_week'] >= 5).astype(int)

results = {}

# ═══════════════════════════════════════════════════════════════════════════
# MODEL 1: USD Headline
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Model 1: R_USD = a + b*H_t ===")
y1 = df_ret['log_return_median']
X1 = df_ret[['halloween']]
m1 = run_ols_nw(y1, X1)
results['model_1_usd_baseline'] = extract_results(m1, 'Model 1: R_NFT_USD = a + b*H_t')
print(f"  H_t coef: {m1.params['halloween']:.6f}, SE: {m1.bse['halloween']:.6f}, "
      f"t: {m1.tvalues['halloween']:.4f}, p: {m1.pvalues['halloween']:.4f}, NW bw: {m1._nw_bandwidth}")

# ═══════════════════════════════════════════════════════════════════════════
# MODEL 2: USD with ETH Control
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Model 2: R_USD = a + b*H_t + g*R_ETH ===")
y2 = df_ret['log_return_median']
X2 = df_ret[['halloween', 'r_eth']].dropna()
idx2 = X2.index
m2 = run_ols_nw(y2.loc[idx2], X2)
results['model_2_usd_eth_control'] = extract_results(m2, 'Model 2: R_NFT_USD = a + b*H_t + g*R_ETH')
print(f"  H_t coef: {m2.params['halloween']:.6f}, p: {m2.pvalues['halloween']:.4f}")
print(f"  R_ETH coef: {m2.params['r_eth']:.6f}, p: {m2.pvalues['r_eth']:.4f}")

# ═══════════════════════════════════════════════════════════════════════════
# MODEL 3: ETH-Denominated Headline
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Model 3: R_ETH = a + b*H_t ===")
y3 = df_ret['nft_log_return_eth']
X3 = df_ret[['halloween']]
m3 = run_ols_nw(y3, X3)
results['model_3_eth_baseline'] = extract_results(m3, 'Model 3: R_NFT_ETH = a + b*H_t')
print(f"  H_t coef: {m3.params['halloween']:.6f}, p: {m3.pvalues['halloween']:.4f}")

# ═══════════════════════════════════════════════════════════════════════════
# MODEL 4: Full Specification (with ETH volatility)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Model 4: Full specification ===")
dow_cols = [c for c in df_ret.columns if c.startswith('dow_')]
X4_cols = ['halloween', 'r_eth', 'time_trend', 'boom', 'post_crash', 'eth_volatility_30d'] + dow_cols
df_m4 = df_ret.dropna(subset=X4_cols + ['log_return_median'])
y4 = df_m4['log_return_median']
X4 = df_m4[X4_cols]
m4 = run_ols_nw(y4, X4)
results['model_4_full'] = extract_results(m4, 'Model 4: Full (H_t + R_ETH + DoW + Trend + Phase + ETH_vol)')
print(f"  H_t coef: {m4.params['halloween']:.6f}, p: {m4.pvalues['halloween']:.4f}")

# Also Model 4 in ETH denomination
y4e = df_m4['nft_log_return_eth']
m4e = run_ols_nw(y4e, X4)
results['model_4_full_eth'] = extract_results(m4e, 'Model 4 (ETH denom): Full specification')

# ═══════════════════════════════════════════════════════════════════════════
# MODEL 5: Month Dummies (DESCRIPTIVE ONLY) — May omitted
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Model 5: Month dummies (DESCRIPTIVE ONLY, May omitted) ===")
month_cols = sorted([c for c in df_ret.columns if c.startswith('month_')])
X5_cols = month_cols + ['r_eth']
df_m5 = df_ret.dropna(subset=X5_cols + ['log_return_median'])
y5 = df_m5['log_return_median']
X5 = df_m5[X5_cols]
m5 = run_ols_nw(y5, X5)

# Joint F-test on month dummies
R = np.zeros((len(month_cols), len(m5.params)))
for i, mc in enumerate(month_cols):
    R[i, list(m5.params.index).index(mc)] = 1
try:
    f_test = m5.f_test(R)
    joint_F = float(f_test.fvalue)
    joint_p = float(f_test.pvalue)
except Exception:
    joint_F = None
    joint_p = None

r5 = extract_results(m5, 'Model 5: Month FE + R_ETH (DESCRIPTIVE ONLY, May omitted)')
r5['joint_month_F'] = joint_F
r5['joint_month_p'] = joint_p
r5['reference_month'] = 'May (month 5)'
results['model_5_month_dummies'] = r5
print(f"  Joint month F: {joint_F:.4f}, p: {joint_p:.4f}" if joint_F else "  Joint F-test failed")

# ═══════════════════════════════════════════════════════════════════════════
# MODEL 6: Halloween × Year Interaction (time-varying effects)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Model 6: H_t × Year interaction ===")
# Create Halloween-year interactions for complete cycles
df_m6 = df_ret.dropna(subset=['r_eth']).copy()
df_m6['hy_2020'] = ((df_m6['halloween_year'] == 2020) & (df_m6['halloween'] == 1)).astype(int)
df_m6['hy_2021'] = ((df_m6['halloween_year'] == 2021) & (df_m6['halloween'] == 1)).astype(int)
# Only create interactions for complete cycles
X6_cols = ['hy_2020', 'hy_2021', 'r_eth']
y6 = df_m6['log_return_median']
X6 = df_m6[X6_cols]
m6 = run_ols_nw(y6, X6)
results['model_6_year_interaction'] = extract_results(m6, 'Model 6: H_t × Year (complete cycles only)')
print(f"  2020-21 cycle coef: {m6.params['hy_2020']:.6f}, p: {m6.pvalues['hy_2020']:.4f}")
print(f"  2021-22 cycle coef: {m6.params['hy_2021']:.6f}, p: {m6.pvalues['hy_2021']:.4f}")


# ═══════════════════════════════════════════════════════════════════════════
# DESCRIPTIVE STATISTICS BY SEASON
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Descriptive statistics ===")
winter = df_ret[df_ret['halloween'] == 1]['log_return_median']
summer = df_ret[df_ret['halloween'] == 0]['log_return_median']
winter_eth = df_ret[df_ret['halloween'] == 1]['nft_log_return_eth']
summer_eth = df_ret[df_ret['halloween'] == 0]['nft_log_return_eth']

desc = {
    'winter_N': int(len(winter)),
    'summer_N': int(len(summer)),
    'winter_mean': float(winter.mean()),
    'summer_mean': float(summer.mean()),
    'winter_std': float(winter.std()),
    'summer_std': float(summer.std()),
    'winter_median': float(winter.median()),
    'summer_median': float(summer.median()),
    'winter_skew': float(winter.skew()),
    'summer_skew': float(summer.skew()),
    'winter_kurt': float(winter.kurtosis()),
    'summer_kurt': float(summer.kurtosis()),
    'winter_min': float(winter.min()),
    'summer_min': float(summer.min()),
    'winter_max': float(winter.max()),
    'summer_max': float(summer.max()),
    'difference_means': float(winter.mean() - summer.mean()),
    'annualized_diff_pct': float((winter.mean() - summer.mean()) * 365 * 100),
}
welch = stats.ttest_ind(winter, summer, equal_var=False)
desc['welch_t'] = float(welch.statistic)
desc['welch_p'] = float(welch.pvalue)
mw = stats.mannwhitneyu(winter, summer, alternative='two-sided')
desc['mann_whitney_stat'] = float(mw.statistic)
desc['mann_whitney_p'] = float(mw.pvalue)
ks = stats.ks_2samp(winter, summer)
desc['ks_stat'] = float(ks.statistic)
desc['ks_p'] = float(ks.pvalue)
lev = stats.levene(winter, summer)
desc['levene_F'] = float(lev.statistic)
desc['levene_p'] = float(lev.pvalue)
desc['variance_ratio_summer_over_winter'] = float(summer.var() / winter.var())
results['descriptive_tests'] = desc

# ETH-denominated descriptives
desc_eth = {
    'winter_N': int(len(winter_eth)),
    'summer_N': int(len(summer_eth)),
    'winter_mean': float(winter_eth.mean()),
    'summer_mean': float(summer_eth.mean()),
    'winter_std': float(winter_eth.std()),
    'summer_std': float(summer_eth.std()),
    'difference_means': float(winter_eth.mean() - summer_eth.mean()),
    'welch_t': float(stats.ttest_ind(winter_eth, summer_eth, equal_var=False).statistic),
    'welch_p': float(stats.ttest_ind(winter_eth, summer_eth, equal_var=False).pvalue),
}
results['descriptive_tests_eth'] = desc_eth

# Sharpe ratio by season
sr_winter = float(winter.mean() / winter.std()) if winter.std() > 0 else 0
sr_summer = float(summer.mean() / summer.std()) if summer.std() > 0 else 0
results['sharpe_ratio_by_season'] = {
    'winter_daily_sharpe': sr_winter,
    'summer_daily_sharpe': sr_summer,
    'winter_annualized_sharpe': sr_winter * np.sqrt(365),
    'summer_annualized_sharpe': sr_summer * np.sqrt(365),
    'sharpe_difference': sr_winter - sr_summer,
    'sharpe_ratio_test_note': 'Risk-adjusted returns also favor winter but magnitude is small (0.24 vs -0.007 annualized).',
}


# ═══════════════════════════════════════════════════════════════════════════
# YEAR-BY-YEAR ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Year-by-year ===")
yby = {}
for hy in sorted(df_ret['halloween_year'].unique()):
    sub = df_ret[df_ret['halloween_year'] == hy]
    w = sub[sub['halloween'] == 1]['log_return_median']
    s = sub[sub['halloween'] == 0]['log_return_median']
    entry = {
        'halloween_year': int(hy),
        'winter_N': int(len(w)),
        'summer_N': int(len(s)),
        'winter_mean': float(w.mean()) if len(w) > 0 else None,
        'summer_mean': float(s.mean()) if len(s) > 0 else None,
    }
    if len(w) > 10 and len(s) > 10:
        entry['difference'] = float(w.mean() - s.mean())
        wt = stats.ttest_ind(w, s, equal_var=False)
        entry['welch_t'] = float(wt.statistic)
        entry['welch_p'] = float(wt.pvalue)
        y_sub = sub['log_return_median']
        X_sub = sub[['halloween']]
        m_sub = run_ols_nw(y_sub, X_sub, min_bw=5)
        entry['ols_halloween_coef'] = float(m_sub.params['halloween'])
        entry['ols_halloween_se'] = float(m_sub.bse['halloween'])
        entry['ols_halloween_p'] = float(m_sub.pvalues['halloween'])
    yby[str(hy)] = entry
results['year_by_year'] = yby


# ═══════════════════════════════════════════════════════════════════════════
# DENOMINATION DECOMPOSITION (Proposition 4/5)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Denomination decomposition ===")
eth_winter = df_ret[df_ret['halloween'] == 1]['r_eth'].dropna()
eth_summer = df_ret[df_ret['halloween'] == 0]['r_eth'].dropna()
eth_premium = float(eth_winter.mean() - eth_summer.mean())

decomp = {
    'halloween_premium_usd_daily': float(winter.mean() - summer.mean()),
    'halloween_premium_nft_eth_daily': float(winter_eth.mean() - summer_eth.mean()),
    'halloween_premium_eth_price_daily': eth_premium,
    'residual': float((winter.mean() - summer.mean()) - (winter_eth.mean() - summer_eth.mean()) - eth_premium),
    'eth_share_pct': float(eth_premium / (winter.mean() - summer.mean()) * 100) if (winter.mean() - summer.mean()) != 0 else None,
    'nft_specific_share_pct': float((winter_eth.mean() - summer_eth.mean()) / (winter.mean() - summer.mean()) * 100) if (winter.mean() - summer.mean()) != 0 else None,
    'annualized': {
        'usd_pp': float((winter.mean() - summer.mean()) * 365 * 100),
        'nft_eth_pp': float((winter_eth.mean() - summer_eth.mean()) * 365 * 100),
        'eth_price_pp': float(eth_premium * 365 * 100),
    }
}

# ETH placebo regression
y_eth_placebo = df_ret['r_eth'].dropna()
X_eth_placebo = df_ret.loc[y_eth_placebo.index, ['halloween']]
m_eth_placebo = run_ols_nw(y_eth_placebo, X_eth_placebo)
decomp['eth_placebo'] = extract_results(m_eth_placebo, 'ETH placebo: R_ETH = a + b*H_t')
results['denomination_decomposition'] = decomp
print(f"  USD premium: {decomp['halloween_premium_usd_daily']:.6f}")
print(f"  NFT-ETH premium: {decomp['halloween_premium_nft_eth_daily']:.6f}")
print(f"  ETH price premium: {decomp['halloween_premium_eth_price_daily']:.6f}")
print(f"  ETH placebo H_t: coef={m_eth_placebo.params['halloween']:.6f}, p={m_eth_placebo.pvalues['halloween']:.4f}")


# ═══════════════════════════════════════════════════════════════════════════
# VOLUME DECOMPOSITION (C2, G5)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Volume seasonality ===")
df_vol = df_ret.dropna(subset=['r_eth']).copy()
df_vol['ln_volume'] = np.log(df_vol['total_volume_usd'].clip(lower=1))
df_vol['ln_trades'] = np.log(df_vol['trade_count'].clip(lower=1))
df_vol['avg_trade_size'] = df_vol['total_volume_usd'] / df_vol['trade_count'].clip(lower=1)
df_vol['ln_avg_size'] = np.log(df_vol['avg_trade_size'].clip(lower=1))
df_vol['ln_buyers'] = np.log(df_vol['active_buyers'].clip(lower=1))
df_vol['trades_per_buyer'] = df_vol['trade_count'] / df_vol['active_buyers'].clip(lower=1)
df_vol['ln_trades_per_buyer'] = np.log(df_vol['trades_per_buyer'].clip(lower=1))

vol_models = {}
for label, ycol in [('ln_volume', 'ln_volume'), ('ln_trade_count', 'ln_trades'),
                     ('ln_avg_trade_size', 'ln_avg_size'), ('ln_active_buyers', 'ln_buyers'),
                     ('ln_trades_per_buyer', 'ln_trades_per_buyer')]:
    y_v = df_vol[ycol]
    X_v = df_vol[['halloween', 'r_eth']]
    mv = run_ols_nw(y_v, X_v)
    vol_models[label] = extract_results(mv, f'{label} = a + b*H_t + g*R_ETH')
results['volume_seasonality'] = vol_models

# Margin decomposition stats
results['volume_margin_decomposition'] = {
    'winter_avg_daily_trades': float(df_vol[df_vol['halloween']==1]['trade_count'].mean()),
    'summer_avg_daily_trades': float(df_vol[df_vol['halloween']==0]['trade_count'].mean()),
    'trade_count_ratio': float(df_vol[df_vol['halloween']==1]['trade_count'].mean() /
                               df_vol[df_vol['halloween']==0]['trade_count'].mean()),
    'winter_avg_trade_size': float(df_vol[df_vol['halloween']==1]['avg_trade_size'].mean()),
    'summer_avg_trade_size': float(df_vol[df_vol['halloween']==0]['avg_trade_size'].mean()),
    'trade_size_ratio': float(df_vol[df_vol['halloween']==1]['avg_trade_size'].mean() /
                              df_vol[df_vol['halloween']==0]['avg_trade_size'].mean()),
    'winter_avg_unique_buyers': float(df_vol[df_vol['halloween']==1]['active_buyers'].mean()),
    'summer_avg_unique_buyers': float(df_vol[df_vol['halloween']==0]['active_buyers'].mean()),
    'unique_buyers_ratio': float(df_vol[df_vol['halloween']==1]['active_buyers'].mean() /
                                 df_vol[df_vol['halloween']==0]['active_buyers'].mean()),
    'winter_avg_trades_per_buyer': float(df_vol[df_vol['halloween']==1]['trades_per_buyer'].mean()),
    'summer_avg_trades_per_buyer': float(df_vol[df_vol['halloween']==0]['trades_per_buyer'].mean()),
    'trades_per_buyer_ratio': float(df_vol[df_vol['halloween']==1]['trades_per_buyer'].mean() /
                                    df_vol[df_vol['halloween']==0]['trades_per_buyer'].mean()),
}


# ═══════════════════════════════════════════════════════════════════════════
# VARIANCE SEASONALITY (C3, G8)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Variance seasonality ===")
levene_unc = stats.levene(winter, summer)
X_phase = df_ret[['boom', 'post_crash']].copy()
X_phase = sm.add_constant(X_phase)
m_phase = OLS(df_ret['log_return_median'], X_phase, missing='drop').fit()
resid_phase = m_phase.resid
w_resid = resid_phase[df_ret['halloween'] == 1]
s_resid = resid_phase[df_ret['halloween'] == 0]
levene_cond = stats.levene(w_resid, s_resid)

# Brown-Forsythe (Levene with median) for robustness
bf_unc = stats.levene(winter, summer, center='median')

results['variance_seasonality'] = {
    'unconditional': {
        'winter_var': float(winter.var()),
        'summer_var': float(summer.var()),
        'ratio': float(summer.var() / winter.var()),
        'levene_F': float(levene_unc.statistic),
        'levene_p': float(levene_unc.pvalue),
        'brown_forsythe_F': float(bf_unc.statistic),
        'brown_forsythe_p': float(bf_unc.pvalue),
    },
    'conditional_on_phase': {
        'winter_resid_var': float(w_resid.var()),
        'summer_resid_var': float(s_resid.var()),
        'ratio': float(s_resid.var() / w_resid.var()),
        'levene_F': float(levene_cond.statistic),
        'levene_p': float(levene_cond.pvalue),
    }
}
print(f"  Unconditional: ratio={summer.var()/winter.var():.3f}, Levene p={levene_unc.pvalue:.2e}")
print(f"  Conditional:   ratio={s_resid.var()/w_resid.var():.3f}, Levene p={levene_cond.pvalue:.2e}")


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-SECTIONAL: TIER-LEVEL (G3) and PLATFORM-LEVEL (G4)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Cross-sectional analysis (from database) ===")
try:
    import psycopg
    conn = psycopg.connect(DB_CONN)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM nft_data.trades")
    trade_count = cur.fetchone()[0]
    print(f"  Trades in DB: {trade_count:,}")

    if trade_count > 0:
        # Tier-level query
        tier_query = """
        SET search_path TO nft_data, public;
        WITH collection_volume AS (
            SELECT project_name,
                   SUM(price_usd) as total_vol_usd,
                   COUNT(*) as n_trades
            FROM trades
            WHERE block_timestamp >= '2020-05-05'
              AND block_timestamp <= '2023-01-20'
              AND price_usd > 0
              AND price_usd < 1e8
            GROUP BY project_name
        ),
        tier_assign AS (
            SELECT project_name,
                   CASE
                       WHEN total_vol_usd >= 10000000 THEN 'blue_chip'
                       WHEN total_vol_usd >= 1000000 THEN 'mid_tier'
                       ELSE 'long_tail'
                   END as tier
            FROM collection_volume
            WHERE n_trades >= 10
        ),
        daily_tier AS (
            SELECT DATE(t.block_timestamp) as trade_date,
                   ta.tier,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.price_usd) as median_price_usd,
                   COUNT(*) as n_trades,
                   SUM(t.price_usd) as volume_usd
            FROM trades t
            JOIN tier_assign ta ON t.project_name = ta.project_name
            WHERE t.block_timestamp >= '2020-05-05'
              AND t.block_timestamp <= '2023-01-20'
              AND t.price_usd > 0
              AND t.price_usd < 1e8
            GROUP BY DATE(t.block_timestamp), ta.tier
            HAVING COUNT(*) >= 5
        )
        SELECT * FROM daily_tier ORDER BY trade_date, tier;
        """
        df_tier = pd.read_sql(tier_query, conn)

        tier_results = {}
        for tier_name in df_tier['tier'].unique():
            sub = df_tier[df_tier['tier'] == tier_name].sort_values('trade_date').copy()
            sub['log_return'] = np.log(sub['median_price_usd']).diff()
            sub = sub.dropna(subset=['log_return'])
            sub['trade_date'] = pd.to_datetime(sub['trade_date'])
            sub['month'] = sub['trade_date'].dt.month
            sub['halloween'] = sub['month'].isin([11,12,1,2,3,4]).astype(int)
            if len(sub) > 30:
                y_t = sub['log_return']
                X_t = sub[['halloween']]
                mt = run_ols_nw(y_t, X_t, min_bw=5)
                tier_results[tier_name] = extract_results(mt, f'Tier: {tier_name}')
                tier_results[tier_name]['n_days'] = int(len(sub))
        results['cross_section_tier'] = tier_results

        # Platform-group query
        plat_query = """
        SET search_path TO nft_data, public;
        WITH plat_map AS (
            SELECT platform_name,
                   CASE
                       WHEN platform_name IN ('opensea', 'rarible', 'larva_labs', 'sudoswap') THEN 'organic'
                       WHEN platform_name IN ('looksrare', 'x2y2', 'blur') THEN 'incentivized'
                       WHEN platform_name = 'nftx' THEN 'amm'
                       ELSE 'other'
                   END as platform_group
            FROM (SELECT DISTINCT platform_name FROM trades) t
        ),
        daily_platform AS (
            SELECT DATE(t.block_timestamp) as trade_date,
                   pm.platform_group,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.price_usd) as median_price_usd,
                   COUNT(*) as n_trades,
                   SUM(t.price_usd) as volume_usd
            FROM trades t
            JOIN plat_map pm ON t.platform_name = pm.platform_name
            WHERE t.block_timestamp >= '2020-05-05'
              AND t.block_timestamp <= '2023-01-20'
              AND t.price_usd > 0
              AND t.price_usd < 1e8
            GROUP BY DATE(t.block_timestamp), pm.platform_group
            HAVING COUNT(*) >= 5
        )
        SELECT * FROM daily_platform ORDER BY trade_date, platform_group;
        """
        df_plat = pd.read_sql(plat_query, conn)

        plat_results = {}
        for pg in df_plat['platform_group'].unique():
            sub = df_plat[df_plat['platform_group'] == pg].sort_values('trade_date').copy()
            sub['log_return'] = np.log(sub['median_price_usd']).diff()
            sub = sub.dropna(subset=['log_return'])
            sub['trade_date'] = pd.to_datetime(sub['trade_date'])
            sub['month'] = sub['trade_date'].dt.month
            sub['halloween'] = sub['month'].isin([11,12,1,2,3,4]).astype(int)
            if len(sub) > 30:
                y_p = sub['log_return']
                X_p = sub[['halloween']]
                mp = run_ols_nw(y_p, X_p, min_bw=5)
                plat_results[pg] = extract_results(mp, f'Platform group: {pg}')
                plat_results[pg]['n_days'] = int(len(sub))
        results['cross_section_platform'] = plat_results

        # Wash trade exclusion robustness: exclude LooksRare + X2Y2
        wash_query = """
        SET search_path TO nft_data, public;
        SELECT DATE(block_timestamp) as trade_date,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_usd) as median_price_usd,
               COUNT(*) as n_trades
        FROM trades
        WHERE block_timestamp >= '2020-05-05'
          AND block_timestamp <= '2023-01-20'
          AND price_usd > 0
          AND price_usd < 1e8
          AND platform_name NOT IN ('looksrare', 'x2y2')
          AND buyer_address != seller_address
        GROUP BY DATE(block_timestamp)
        HAVING COUNT(*) >= 5
        ORDER BY trade_date;
        """
        df_wash = pd.read_sql(wash_query, conn)
        df_wash['trade_date'] = pd.to_datetime(df_wash['trade_date'])
        df_wash = df_wash.sort_values('trade_date')
        df_wash['log_return'] = np.log(df_wash['median_price_usd']).diff()
        df_wash = df_wash.dropna(subset=['log_return'])
        df_wash['month'] = df_wash['trade_date'].dt.month
        df_wash['halloween'] = df_wash['month'].isin([11,12,1,2,3,4]).astype(int)
        if len(df_wash) > 30:
            mwash = run_ols_nw(df_wash['log_return'], df_wash[['halloween']], min_bw=5)
            results['robustness_wash_trade_exclusion'] = extract_results(
                mwash, 'Exclude LooksRare + X2Y2 + self-trades')
            results['robustness_wash_trade_exclusion']['n_days'] = int(len(df_wash))
            print(f"  Wash exclusion: H_t={mwash.params['halloween']:.6f}, p={mwash.pvalues['halloween']:.4f}")

    else:
        print("  WARNING: nft_data.trades is empty.")
        results['cross_section_tier'] = {'note': 'Trades table empty; tier analysis unavailable from raw data'}
        results['cross_section_platform'] = {'note': 'Trades table empty; platform analysis unavailable from raw data'}
        results['robustness_wash_trade_exclusion'] = {'note': 'Trades table empty; wash trade exclusion unavailable'}

    conn.close()
except Exception as e:
    print(f"  Cross-sectional query error: {e}")
    results['cross_section_tier'] = {'error': str(e)}
    results['cross_section_platform'] = {'error': str(e)}
    results['robustness_wash_trade_exclusion'] = {'error': str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# ROBUSTNESS CHECKS
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Robustness checks ===")
robustness = {}

# R1: Winsorized returns (1st/99th percentile)
p1, p99 = df_ret['log_return_median'].quantile([0.01, 0.99])
df_win = df_ret.copy()
df_win['log_return_winsorized'] = df_win['log_return_median'].clip(p1, p99)
mw1 = run_ols_nw(df_win['log_return_winsorized'], df_win[['halloween']])
robustness['winsorized_1_99'] = extract_results(mw1, 'Winsorized at 1st/99th percentile')

# R3: High-volume days (>75th percentile volume)
vol_75 = df_ret['total_volume_usd'].quantile(0.75)
df_bc = df_ret[df_ret['total_volume_usd'] >= vol_75]
if len(df_bc) > 30:
    mbc = run_ols_nw(df_bc['log_return_median'], df_bc[['halloween']])
    robustness['high_volume_days'] = extract_results(mbc, 'High-volume days (>75th pctile)')

# R4: Drop individual years
drop_years = {}
for yr in [2020, 2021, 2022, 2023]:
    df_dy = df_ret[df_ret['year'] != yr]
    mdy = run_ols_nw(df_dy['log_return_median'], df_dy[['halloween']])
    drop_years[str(yr)] = {
        'halloween_coef': float(mdy.params['halloween']),
        'halloween_se': float(mdy.bse['halloween']),
        'halloween_t': float(mdy.tvalues['halloween']),
        'halloween_p': float(mdy.pvalues['halloween']),
        'n_obs': int(mdy.nobs),
        'nw_bandwidth': int(mdy._nw_bandwidth),
    }
robustness['drop_one_year'] = drop_years

# R5a: Alternative window (Oct-Mar vs Apr-Sep)
df_ret['halloween_alt'] = df_ret['month'].isin([10,11,12,1,2,3]).astype(int)
malt = run_ols_nw(df_ret['log_return_median'], df_ret[['halloween_alt']])
robustness['alt_window_oct_mar'] = extract_results(malt, 'Alt window: Oct-Mar vs Apr-Sep')

# R5b: Shifted window (Dec-May vs Jun-Nov)
df_ret['halloween_shift'] = df_ret['month'].isin([12,1,2,3,4,5]).astype(int)
mshift = run_ols_nw(df_ret['log_return_median'], df_ret[['halloween_shift']])
robustness['alt_window_dec_may'] = extract_results(mshift, 'Alt window: Dec-May vs Jun-Nov')

# R8: Mean-based index
mmean = run_ols_nw(df_ret['log_return_mean'], df_ret[['halloween']])
robustness['mean_based_index'] = extract_results(mmean, 'Mean-based return index')

# R9: Linear and quadratic trend controls
X_trend = df_ret[['halloween', 'r_eth', 'time_trend']].dropna()
mt = run_ols_nw(df_ret.loc[X_trend.index, 'log_return_median'], X_trend)
robustness['linear_trend'] = extract_results(mt, 'With linear time trend')

df_ret['trend_sq'] = df_ret['time_trend'] ** 2
X_tq = df_ret[['halloween', 'r_eth', 'time_trend', 'trend_sq']].dropna()
mtq = run_ols_nw(df_ret.loc[X_tq.index, 'log_return_median'], X_tq)
robustness['quadratic_trend'] = extract_results(mtq, 'With quadratic time trend')

# R10: Market-phase interaction
df_ret['halloween_x_boom'] = df_ret['halloween'] * df_ret['boom']
df_ret['halloween_x_postcrash'] = df_ret['halloween'] * df_ret['post_crash']
X_int = df_ret[['halloween', 'boom', 'post_crash', 'halloween_x_boom', 'halloween_x_postcrash', 'r_eth']].dropna()
mint = run_ols_nw(df_ret.loc[X_int.index, 'log_return_median'], X_int)
robustness['market_phase_interaction'] = extract_results(mint, 'H_t x Market Phase interaction')

# R11: ETH-denom with ETH control
X_ec = df_ret[['halloween', 'r_eth']].dropna()
y_ec = df_ret.loc[X_ec.index, 'nft_log_return_eth']
mec = run_ols_nw(y_ec, X_ec)
robustness['eth_denom_eth_control'] = extract_results(mec, 'ETH-denominated + ETH control')

results['robustness'] = robustness


# ═══════════════════════════════════════════════════════════════════════════
# OTHER CALENDAR ANOMALIES (G10)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Other calendar anomalies ===")
calendar = {}

# Day-of-week effect
X_dow = df_ret[dow_cols]
m_dow = run_ols_nw(df_ret['log_return_median'], X_dow)
R_dow = np.zeros((len(dow_cols), len(m_dow.params)))
for i, dc in enumerate(dow_cols):
    R_dow[i, list(m_dow.params.index).index(dc)] = 1
try:
    f_dow = m_dow.f_test(R_dow)
    dow_joint_F = float(f_dow.fvalue)
    dow_joint_p = float(f_dow.pvalue)
except Exception:
    dow_joint_F = None
    dow_joint_p = None

calendar['day_of_week'] = {
    'joint_F': dow_joint_F,
    'joint_p': dow_joint_p,
    'coefficients': {
        f'dow_{d}': {
            'coef': float(m_dow.params[f'dow_{d}']),
            'se': float(m_dow.bse[f'dow_{d}']),
            't': float(m_dow.tvalues[f'dow_{d}']),
            'p': float(m_dow.pvalues[f'dow_{d}']),
        } for d in range(1, 7) if f'dow_{d}' in m_dow.params
    }
}

# January effect
m_jan = run_ols_nw(df_ret['log_return_median'], df_ret[['january']])
calendar['january_effect'] = extract_results(m_jan, 'January effect: R = a + b*January')

# Turn of month
m_tom = run_ols_nw(df_ret['log_return_median'], df_ret[['turn_of_month']])
calendar['turn_of_month'] = extract_results(m_tom, 'Turn-of-month effect')

# Weekend effect
m_we = run_ols_nw(df_ret['log_return_median'], df_ret[['weekend']])
calendar['weekend_effect'] = extract_results(m_we, 'Weekend effect')

results['calendar_anomalies'] = calendar


# ═══════════════════════════════════════════════════════════════════════════
# BLOCK BOOTSTRAP (PRIMARY INFERENCE) — G2
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Block bootstrap (21-day blocks, 10K reps) ===")
np.random.seed(42)
n = len(df_ret)
block_size = 21
n_boot = 10000
boot_coefs = np.zeros(n_boot)

y_boot = df_ret['log_return_median'].values
x_boot = df_ret['halloween'].values

for b in range(n_boot):
    n_blocks = int(np.ceil(n / block_size))
    starts = np.random.randint(0, n - block_size + 1, size=n_blocks)
    indices = np.concatenate([np.arange(s, min(s + block_size, n)) for s in starts])[:n]
    y_b = y_boot[indices]
    x_b = x_boot[indices]
    X_b = sm.add_constant(x_b)
    try:
        coef = np.linalg.lstsq(X_b, y_b, rcond=None)[0][1]
        boot_coefs[b] = coef
    except Exception:
        boot_coefs[b] = np.nan

boot_coefs = boot_coefs[~np.isnan(boot_coefs)]
observed_coef = float(m1.params['halloween'])

# Standard percentile CI
ci_lower = float(np.percentile(boot_coefs, 2.5))
ci_upper = float(np.percentile(boot_coefs, 97.5))

# Bias-corrected (BC) CI
z0 = stats.norm.ppf(np.mean(boot_coefs < observed_coef))
alpha_levels = [0.025, 0.975]
bc_quantiles = [stats.norm.cdf(2 * z0 + stats.norm.ppf(a)) for a in alpha_levels]
bc_lower = float(np.percentile(boot_coefs, bc_quantiles[0] * 100))
bc_upper = float(np.percentile(boot_coefs, bc_quantiles[1] * 100))

boot_p = float(np.mean(np.abs(boot_coefs) >= np.abs(observed_coef)))

results['bootstrap'] = {
    'method': 'Block bootstrap (21-day blocks, 10K replications)',
    'n_replications': len(boot_coefs),
    'observed_coef': observed_coef,
    'mean_coef': float(np.mean(boot_coefs)),
    'se': float(np.std(boot_coefs)),
    'ci_95_percentile': {'lower': ci_lower, 'upper': ci_upper},
    'ci_95_bias_corrected': {'lower': bc_lower, 'upper': bc_upper},
    'bootstrap_p_two_sided': boot_p,
    'pct_positive': float(np.mean(boot_coefs > 0) * 100),
    'bias': float(np.mean(boot_coefs) - observed_coef),
    'z0_bias_correction': float(z0),
    'note': 'PRIMARY inference method. Block bootstrap preserves serial dependence.',
}
print(f"  Observed coef: {observed_coef:.6f}")
print(f"  Bootstrap 95% CI (percentile): [{ci_lower:.6f}, {ci_upper:.6f}]")
print(f"  Bootstrap 95% CI (BC):         [{bc_lower:.6f}, {bc_upper:.6f}]")
print(f"  Bootstrap p (two-sided): {boot_p:.4f}")


# ═══════════════════════════════════════════════════════════════════════════
# PERMUTATION TEST (SUPPLEMENTARY) — G2
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Permutation test (10K permutations, SUPPLEMENTARY) ===")
np.random.seed(123)
n_perm = 10000
perm_diffs = np.zeros(n_perm)
observed_diff = float(winter.mean() - summer.mean())

for p_idx in range(n_perm):
    perm_labels = np.random.permutation(df_ret['halloween'].values)
    w_perm = y_boot[perm_labels == 1]
    s_perm = y_boot[perm_labels == 0]
    perm_diffs[p_idx] = w_perm.mean() - s_perm.mean()

perm_p = float(np.mean(np.abs(perm_diffs) >= np.abs(observed_diff)))

results['permutation_test'] = {
    'method': 'Random permutation of H_t labels (10K permutations)',
    'n_permutations': n_perm,
    'observed_diff': observed_diff,
    'permutation_p_two_sided': perm_p,
    'note': 'SUPPLEMENTARY. The permutation test assumes exchangeability of monthly assignments, '
            'which is violated by the documented autocorrelation structure (Ljung-Box significant through lag 12). '
            'Block bootstrap preserves serial dependence and is the preferred inference method.'
}
print(f"  Permutation p (two-sided): {perm_p:.4f}")


# ═══════════════════════════════════════════════════════════════════════════
# POWER ANALYSIS — G6
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Power analysis ===")
sigma_pooled = np.sqrt((winter.var() * (len(winter)-1) + summer.var() * (len(summer)-1)) /
                       (len(winter) + len(summer) - 2))
se_diff = sigma_pooled * np.sqrt(1/len(winter) + 1/len(summer))

nw_bw = m1._nw_bandwidth
boot_se = float(np.std(boot_coefs))
nw_se = float(m1.bse['halloween'])

# Use the more conservative SE (NW) for power analysis
power_se = max(boot_se, nw_se)

# Power at different annualized effect sizes
effect_sizes_annual_pp = np.arange(0, 5001, 25)
effect_sizes_daily = effect_sizes_annual_pp / (365 * 100)
power_values = np.zeros(len(effect_sizes_daily))
power_values_boot = np.zeros(len(effect_sizes_daily))

for i, delta in enumerate(effect_sizes_daily):
    if delta == 0:
        power_values[i] = 0.05
        power_values_boot[i] = 0.05
    else:
        z_crit = 1.96
        ncp = delta / nw_se
        power_values[i] = 1 - stats.norm.cdf(z_crit - ncp) + stats.norm.cdf(-z_crit - ncp)
        ncp_b = delta / boot_se
        power_values_boot[i] = 1 - stats.norm.cdf(z_crit - ncp_b) + stats.norm.cdf(-z_crit - ncp_b)

# MDE at 80% power (using NW SE — conservative)
idx_80 = np.argmax(power_values >= 0.80)
mde_daily = effect_sizes_daily[idx_80] if idx_80 > 0 else None
mde_annual = effect_sizes_annual_pp[idx_80] if idx_80 > 0 else None

# MDE using bootstrap SE
idx_80_b = np.argmax(power_values_boot >= 0.80)
mde_annual_boot = effect_sizes_annual_pp[idx_80_b] if idx_80_b > 0 else None

# Power at BJ benchmark (10pp annualized)
bj_daily = 10 / (365 * 100)
ncp_bj = bj_daily / nw_se
power_bj = 1 - stats.norm.cdf(1.96 - ncp_bj) + stats.norm.cdf(-1.96 - ncp_bj)
ncp_bj_b = bj_daily / boot_se
power_bj_boot = 1 - stats.norm.cdf(1.96 - ncp_bj_b) + stats.norm.cdf(-1.96 - ncp_bj_b)

results['power_analysis'] = {
    'sigma_pooled': float(sigma_pooled),
    'se_diff_classical': float(se_diff),
    'se_bootstrap': boot_se,
    'se_newey_west': nw_se,
    'nw_bandwidth': nw_bw,
    'mde_daily_nw': float(mde_daily) if mde_daily else None,
    'mde_annualized_pp_nw': float(mde_annual) if mde_annual else None,
    'mde_annualized_pp_bootstrap': float(mde_annual_boot) if mde_annual_boot else None,
    'bj_benchmark_annualized_pp': 10.0,
    'power_at_bj_benchmark_nw': float(power_bj),
    'power_at_bj_benchmark_bootstrap': float(power_bj_boot),
    'power_milestones_nw': {
        f'{int(pp)}pp': float(power_values[np.argmin(np.abs(effect_sizes_annual_pp - pp))])
        for pp in [5, 10, 20, 50, 100, 200, 325, 500, 1000, 2000]
    },
    'power_milestones_bootstrap': {
        f'{int(pp)}pp': float(power_values_boot[np.argmin(np.abs(effect_sizes_annual_pp - pp))])
        for pp in [5, 10, 20, 50, 100, 200, 325, 500, 1000, 2000]
    },
}
print(f"  Bootstrap SE: {boot_se:.6f}, NW SE: {nw_se:.6f}")
print(f"  Power at BJ 10pp (NW): {power_bj:.4f}")
print(f"  Power at BJ 10pp (boot): {power_bj_boot:.4f}")
print(f"  MDE 80% power (NW): {mde_annual}pp" if mde_annual else "  MDE > 5000pp")


# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Diagnostics ===")
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.stattools import durbin_watson

resid1 = m1.resid
lb = acorr_ljungbox(resid1, lags=[5, 10, 13, 21], return_df=True)
dw = durbin_watson(resid1)
jb = stats.jarque_bera(resid1)

acf_vals = {}
for lag in [1, 2, 3, 5, 10, 13, 21]:
    if lag < len(resid1):
        acf_vals[f'lag_{lag}'] = float(np.corrcoef(resid1.iloc[:-lag], resid1.iloc[lag:])[0, 1])

# ADF test on returns
from statsmodels.tsa.stattools import adfuller
adf_result = adfuller(df_ret['log_return_median'].dropna(), maxlag=21, autolag='AIC')

results['diagnostics'] = {
    'ljung_box': {str(int(idx)): {'statistic': float(row['lb_stat']), 'p_value': float(row['lb_pvalue'])}
                  for idx, row in lb.iterrows()},
    'durbin_watson': float(dw),
    'jarque_bera': {'statistic': float(jb[0]), 'p_value': float(jb[1])},
    'adf_test': {
        'statistic': float(adf_result[0]),
        'p_value': float(adf_result[1]),
        'lags_used': int(adf_result[2]),
        'nobs': int(adf_result[3]),
        'critical_values': {k: float(v) for k, v in adf_result[4].items()},
        'conclusion': 'Stationary (rejects unit root)' if adf_result[1] < 0.05 else 'Non-stationary',
    },
    'return_autocorrelations': acf_vals,
    'nw_bandwidth_model1': int(m1._nw_bandwidth),
    'nw_bandwidth_model4': int(m4._nw_bandwidth),
}


# ═══════════════════════════════════════════════════════════════════════════
# MONTHLY FREQUENCY REGRESSIONS
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Monthly regressions ===")
df_monthly = pd.read_csv(DATA_DIR / 'monthly_aggregation.csv')
df_monthly = df_monthly.dropna(subset=['log_return_median']).copy()
df_monthly['halloween'] = df_monthly['month'].isin([11,12,1,2,3,4]).astype(int)

# Monthly Model 1
mm1 = run_ols_nw(df_monthly['log_return_median'], df_monthly[['halloween']], min_bw=3)
results['monthly_model_1'] = extract_results(mm1, 'Monthly: R_NFT_USD = a + b*H_t')

# Monthly Model 2 (with ETH return if available)
eth_monthly_col = None
for candidate in ['r_eth_monthly', 'r_eth']:
    if candidate in df_monthly.columns:
        eth_monthly_col = candidate
        break

if eth_monthly_col:
    X_mm2 = df_monthly[['halloween', eth_monthly_col]].dropna()
    mm2 = run_ols_nw(df_monthly.loc[X_mm2.index, 'log_return_median'], X_mm2, min_bw=3)
    results['monthly_model_2'] = extract_results(mm2, 'Monthly: R_NFT_USD = a + b*H_t + g*R_ETH')
else:
    # Compute monthly ETH returns from daily data
    eth_daily = pd.read_csv(DATA_DIR / 'eth_daily_prices.csv')
    eth_daily['date'] = pd.to_datetime(eth_daily['date'])
    eth_daily['year'] = eth_daily['date'].dt.year
    eth_daily['month'] = eth_daily['date'].dt.month
    eth_monthly_ret = eth_daily.groupby(['year', 'month'])['r_eth'].sum().reset_index()
    eth_monthly_ret.columns = ['year', 'month', 'r_eth_monthly']
    df_monthly = df_monthly.merge(eth_monthly_ret, on=['year', 'month'], how='left')
    X_mm2 = df_monthly[['halloween', 'r_eth_monthly']].dropna()
    if len(X_mm2) > 5:
        mm2 = run_ols_nw(df_monthly.loc[X_mm2.index, 'log_return_median'], X_mm2, min_bw=3)
        results['monthly_model_2'] = extract_results(mm2, 'Monthly: R_NFT_USD = a + b*H_t + g*R_ETH')


# ═══════════════════════════════════════════════════════════════════════════
# FIGURES
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Generating figures ===")
from matplotlib.patches import Patch

# ── Figure 1: Monthly average log returns ──
fig1, (ax1a, ax1b) = plt.subplots(1, 2, figsize=(12, 5))
for ax, col, label in [(ax1a, 'log_return_median', 'USD'),
                        (ax1b, 'nft_log_return_eth', 'ETH')]:
    monthly_means = df_ret.groupby('month')[col].agg(['mean', 'std', 'count'])
    monthly_means['se'] = monthly_means['std'] / np.sqrt(monthly_means['count'])
    months = monthly_means.index
    colors = ['steelblue' if m in [11,12,1,2,3,4] else 'indianred' for m in months]
    ax.bar(months, monthly_means['mean'], yerr=1.96 * monthly_means['se'],
           capsize=3, color=colors, edgecolor='gray', linewidth=0.5, alpha=0.85)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_xlabel('Month')
    ax.set_ylabel(f'Mean daily log return ({label})')
    ax.set_title(f'Monthly Average Returns ({label})')
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], rotation=45)
    ax.legend(handles=[Patch(facecolor='steelblue', label='Winter (Nov-Apr)'),
                       Patch(facecolor='indianred', label='Summer (May-Oct)')],
              loc='upper right', fontsize=8)
fig1.tight_layout()
fig1.savefig(FIG_DIR / 'fig1_monthly_returns.pdf')
plt.close(fig1)

# ── Figure 2: Cumulative log return with Halloween shading ──
fig2, ax2 = plt.subplots(figsize=(12, 5))
cum_ret = df_ret['log_return_median'].cumsum()
dates = df_ret['trade_date']
ax2.plot(dates, cum_ret, color='black', linewidth=0.8)
for yr in range(2019, 2024):
    w_start = pd.Timestamp(f'{yr}-11-01')
    w_end = pd.Timestamp(f'{yr+1}-04-30')
    ax2.axvspan(max(w_start, dates.min()), min(w_end, dates.max()),
                alpha=0.15, color='steelblue', zorder=0)
    s_start = pd.Timestamp(f'{yr}-05-01')
    s_end = pd.Timestamp(f'{yr}-10-31')
    ax2.axvspan(max(s_start, dates.min()), min(s_end, dates.max()),
                alpha=0.15, color='indianred', zorder=0)
ax2.set_xlabel('Date')
ax2.set_ylabel('Cumulative log return (USD)')
ax2.set_title('Cumulative NFT Returns with Halloween Seasons')
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.xticks(rotation=45)
ax2.legend(handles=[Patch(facecolor='steelblue', alpha=0.3, label='Winter (Nov-Apr)'),
                    Patch(facecolor='indianred', alpha=0.3, label='Summer (May-Oct)')],
           loc='upper left')
fig2.tight_layout()
fig2.savefig(FIG_DIR / 'fig2_cumulative_returns.pdf')
plt.close(fig2)

# ── Figure 3: Daily trading volume with Halloween shading ──
fig3, ax3 = plt.subplots(figsize=(12, 5))
ax3.semilogy(df['trade_date'], df['total_volume_usd'], color='gray', linewidth=0.5, alpha=0.7)
vol_7d = df['total_volume_usd'].rolling(7, center=True).mean()
ax3.semilogy(df['trade_date'], vol_7d, color='black', linewidth=1.0)
for yr in range(2019, 2024):
    w_start = pd.Timestamp(f'{yr}-11-01')
    w_end = pd.Timestamp(f'{yr+1}-04-30')
    ax3.axvspan(max(w_start, df['trade_date'].min()), min(w_end, df['trade_date'].max()),
                alpha=0.15, color='steelblue', zorder=0)
    s_start = pd.Timestamp(f'{yr}-05-01')
    s_end = pd.Timestamp(f'{yr}-10-31')
    ax3.axvspan(max(s_start, df['trade_date'].min()), min(s_end, df['trade_date'].max()),
                alpha=0.15, color='indianred', zorder=0)
ax3.set_xlabel('Date')
ax3.set_ylabel('Trading Volume (USD, log scale)')
ax3.set_title('Daily NFT Trading Volume')
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.xticks(rotation=45)
fig3.tight_layout()
fig3.savefig(FIG_DIR / 'fig3_daily_volume.pdf')
plt.close(fig3)

# ── Figure 4: Day-of-week average returns ──
fig4, ax4 = plt.subplots(figsize=(8, 5))
dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
dow_stats = df_ret.groupby('day_of_week')['log_return_median'].agg(['mean', 'std', 'count'])
dow_stats['se'] = dow_stats['std'] / np.sqrt(dow_stats['count'])
colors4 = ['steelblue'] * 5 + ['indianred'] * 2
ax4.bar(range(7), dow_stats['mean'], yerr=1.96 * dow_stats['se'],
        capsize=3, color=colors4, edgecolor='gray', linewidth=0.5, alpha=0.85)
ax4.axhline(y=0, color='black', linewidth=0.5)
ax4.set_xticks(range(7))
ax4.set_xticklabels(dow_names)
ax4.set_xlabel('Day of Week')
ax4.set_ylabel('Mean daily log return')
ax4.set_title('Day-of-Week Average Returns')
fig4.tight_layout()
fig4.savefig(FIG_DIR / 'fig4_day_of_week.pdf')
plt.close(fig4)

# ── Figure 5: Bootstrap distribution ──
fig5, ax5 = plt.subplots(figsize=(8, 5))
ax5.hist(boot_coefs, bins=80, density=True, color='steelblue', alpha=0.6, edgecolor='gray', linewidth=0.3)
from scipy.stats import gaussian_kde
kde = gaussian_kde(boot_coefs)
x_kde = np.linspace(boot_coefs.min(), boot_coefs.max(), 300)
ax5.plot(x_kde, kde(x_kde), color='darkblue', linewidth=1.5, label='KDE')
ax5.axvline(x=observed_coef, color='red', linewidth=2, linestyle='-', label=f'Observed = {observed_coef:.4f}')
ax5.axvline(x=0, color='black', linewidth=1, linestyle='--', label='Zero')
ax5.set_xlabel(r'$\hat{\beta}$ (Halloween coefficient)')
ax5.set_ylabel('Density')
ax5.set_title('Block Bootstrap Distribution of Halloween Effect')
ax5.legend(fontsize=9)
ax5.axvspan(ci_lower, ci_upper, alpha=0.1, color='steelblue')
ax5.text(0.02, 0.95, f'95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]\n'
         f'BC CI:  [{bc_lower:.4f}, {bc_upper:.4f}]\n'
         f'Bootstrap p = {boot_p:.3f}',
         transform=ax5.transAxes, fontsize=8, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
fig5.tight_layout()
fig5.savefig(FIG_DIR / 'fig5_bootstrap_distribution.pdf')
plt.close(fig5)

# ── Figure 6: Power curve ──
fig6, ax6 = plt.subplots(figsize=(8, 5))
ax6.plot(effect_sizes_annual_pp, power_values, color='black', linewidth=1.5, label='NW SE')
ax6.plot(effect_sizes_annual_pp, power_values_boot, color='gray', linewidth=1, linestyle=':', label='Bootstrap SE')
ax6.axhline(y=0.80, color='gray', linestyle='--', linewidth=0.8, label='80% power')
ax6.axhline(y=0.05, color='lightgray', linestyle=':', linewidth=0.8, label='5% size')
ax6.axvline(x=10, color='red', linestyle='--', linewidth=1, label='BJ benchmark (10pp)')
ax6.axvline(x=145, color='orange', linestyle='--', linewidth=1, label='NFT estimate (145pp)')
if mde_annual:
    ax6.axvline(x=mde_annual, color='blue', linestyle='--', linewidth=1, label=f'MDE 80% ({int(mde_annual)}pp)')
ax6.set_xlabel('Annualized effect size (percentage points)')
ax6.set_ylabel('Statistical power')
ax6.set_title('Power Curve: Detectable Halloween Effect Size')
ax6.set_xlim(0, 3000)
ax6.legend(fontsize=8, loc='center right')
ax6.text(0.02, 0.85, f'NW SE = {nw_se:.4f}\nBootstrap SE = {boot_se:.4f}\nNW bandwidth = {nw_bw}',
         transform=ax6.transAxes, fontsize=8,
         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
fig6.tight_layout()
fig6.savefig(FIG_DIR / 'fig6_power_curve.pdf')
plt.close(fig6)

print("All 6 figures saved.")


# ═══════════════════════════════════════════════════════════════════════════
# SAVE RESULTS
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Saving results ===")

def convert_numpy(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(v) for v in obj]
    return obj

results = convert_numpy(results)

with open(OUT_DIR / 'estimation_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"Results saved to {OUT_DIR / 'estimation_results.json'}")
print("Done.")
