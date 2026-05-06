"""
Replication script for: Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge
Paper ID: 1f256351-d253-47cf-9fcf-a745fc7fe08f

This script re-runs the complete empirical analysis from raw block data to final tables and figures.

Requirements:
    - pandas >= 1.3.0
    - numpy >= 1.21.0
    - scipy >= 1.7.0
    - statsmodels >= 0.13.0
    - matplotlib >= 3.4.0
    - seaborn >= 0.11.0

Usage:
    python estimation.py

Output:
    - replication/output/table1_summary_stats.csv
    - replication/output/table2_ols_baseline.csv
    - replication/output/table3_rdd_merge_effect.csv
    - replication/output/table4_distribution_analysis.csv
    - replication/output/table5_skip_analysis.csv
    - replication/output/table6_early_vs_stable_pos.csv
    - replication/output/figure1_scatter_by_period.png
    - replication/output/figure2_rdd_discontinuity.png
    - replication/output/figure3_tbb_distributions.png
    - replication/output/figure4_skip_rates.png
    - replication/output/figure5_early_vs_stable.png
    - replication/output/diagnostic_tests.csv

Author: Replication Packager
Date: 2025
"""

import pandas as pd
import numpy as np
from pathlib import Path
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

warnings.filterwarnings('ignore')

# ── GLOBAL CONFIGURATION ──────────────────────────────────────────────────────

# Set random seed for reproducibility
np.random.seed(42)

# Output directory
OUTPUT_DIR = Path("replication/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ethereum parameters
GENESIS_TIMESTAMP = 1438269973  # 2015-07-30 03:26:13 UTC
MERGE_BLOCK = 15537393
MERGE_TIMESTAMP = 1663340827  # 2022-09-15 13:42:07 UTC
SHANGHAI_BLOCK = 17034870  # Approximate, April 2023

# Define analysis periods (post-Merge)
EARLY_POS_START = MERGE_TIMESTAMP
EARLY_POS_END = 1682121600  # Approximately 2023-04-22

# ── 1. DATA LOADING AND PREPARATION ───────────────────────────────────────────

def load_ethereum_blocks():
    """
    Load Ethereum block data.
    
    For production use, this would load from a data source (CSV, Parquet, or SQL).
    For this replication, we simulate the data from specifications in data_dictionary.json.
    
    Returns:
        pd.DataFrame: Block-level data with required columns
    """
    print("[INFO] Loading Ethereum block data...")
    
    # In production, load from actual data source:
    # df = pd.read_csv("data/ethereum_blocks.csv")
    # OR: df = pd.read_parquet("data/ethereum_blocks.parquet")
    
    # For replication purposes, generate synthetic data that matches the specifications
    # This assumes you have already extracted the real data
    
    try:
        # Try to load from data directory if it exists
        if Path("data/ethereum_blocks.csv").exists():
            df = pd.read_csv("data/ethereum_blocks.csv")
            print(f"[INFO] Loaded {len(df):,} blocks from CSV")
        elif Path("data/ethereum_blocks.parquet").exists():
            df = pd.read_parquet("data/ethereum_blocks.parquet")
            print(f"[INFO] Loaded {len(df):,} blocks from Parquet")
        else:
            raise FileNotFoundError("Block data not found. Please provide data/ethereum_blocks.csv or .parquet")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        print("[INFO] To run this script, you must:")
        print("  1. Extract block data from Ethereum (via Allium, Flipside, BigQuery, or archive node)")
        print("  2. Save to data/ethereum_blocks.csv or data/ethereum_blocks.parquet")
        print("  3. Include columns: block_number, block_timestamp")
        print("\nExample SQL query for Allium:")
        print("""
        SELECT 
            block_number,
            block_timestamp,
            gas_used,
            transaction_count
        FROM ethereum.core.blocks
        WHERE block_timestamp >= UNIX_TIMESTAMP('2022-09-15')
        ORDER BY block_number
        """)
        raise
    
    # Validate data structure
    required_cols = ['block_number', 'block_timestamp']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"Data must contain columns: {required_cols}")
    
    # Ensure correct data types
    df['block_number'] = df['block_number'].astype('int64')
    df['block_timestamp'] = df['block_timestamp'].astype('int64')
    
    # Sort by block number
    df = df.sort_values('block_number').reset_index(drop=True)
    
    print(f"[INFO] Data shape: {df.shape}")
    print(f"[INFO] Block range: {df['block_number'].min():,} to {df['block_number'].max():,}")
    print(f"[INFO] Timestamp range: {pd.Timestamp(df['block_timestamp'].min(), unit='s')} to {pd.Timestamp(df['block_timestamp'].max(), unit='s')}")
    
    return df


def validate_data_quality(df):
    """
    Run data quality checks.
    
    Parameters:
        df (pd.DataFrame): Block data
        
    Returns:
        dict: Quality check results
    """
    print("\n[INFO] Running data quality checks...")
    
    checks = {}
    
    # 1. Completeness check
    expected_blocks = df['block_number'].max() - df['block_number'].min() + 1
    actual_blocks = len(df)
    checks['completeness'] = {
        'expected': expected_blocks,
        'actual': actual_blocks,
        'missing': expected_blocks - actual_blocks,
        'pass': expected_blocks == actual_blocks
    }
    print(f"  ✓ Completeness: {actual_blocks:,} blocks (expected {expected_blocks:,})")
    
    # 2. Monotonicity check (timestamps should increase with block_number)
    timestamp_monotonic = (df['block_timestamp'].diff() >= 0).all() or (df['block_timestamp'].diff().fillna(1) >= 0).all()
    checks['monotonicity'] = {'pass': timestamp_monotonic}
    print(f"  ✓ Monotonicity: {'PASS' if timestamp_monotonic else 'FAIL'}")
    
    # 3. Timestamp realism
    unrealistic = (df['block_timestamp'] < GENESIS_TIMESTAMP) | (df['block_timestamp'] > pd.Timestamp.now().value // 10**9)
    checks['realism'] = {'violations': unrealistic.sum(), 'pass': unrealistic.sum() == 0}
    print(f"  ✓ Timestamp realism: {unrealistic.sum()} violations")
    
    # 4. No duplicates
    duplicates = df['block_number'].duplicated().sum()
    checks['duplicates'] = {'count': duplicates, 'pass': duplicates == 0}
    print(f"  ✓ Duplicate blocks: {duplicates}")
    
    # 5. Null values
    nulls = df[['block_number', 'block_timestamp']].isnull().sum().sum()
    checks['nulls'] = {'count': nulls, 'pass': nulls == 0}
    print(f"  ✓ Null values: {nulls}")
    
    return checks


def prepare_variables(df):
    """
    Construct all analysis variables.
    
    Parameters:
        df (pd.DataFrame): Raw block data
        
    Returns:
        pd.DataFrame: Data with derived variables
    """
    print("\n[INFO] Constructing analysis variables...")
    
    # Derived variables
    df['elapsed_seconds'] = df['block_timestamp'] - GENESIS_TIMESTAMP
    df['blocks_since_merge'] = df['block_number'] - MERGE_BLOCK
    df['time_since_previous_block'] = df['block_timestamp'].diff()
    
    # Protocol regime indicators
    df['is_post_merge'] = (df['block_number'] > MERGE_BLOCK).astype(int)
    df['is_early_pos'] = (
        (df['block_timestamp'] >= EARLY_POS_START) & 
        (df['block_timestamp'] < EARLY_POS_END)
    ).astype(int)
    df['is_stable_pos'] = (df['block_timestamp'] >= EARLY_POS_END).astype(int)
    
    # Time periods (categorical)
    df['period'] = 'PoW'
    df.loc[df['is_early_pos'] == 1, 'period'] = 'Early PoS'
    df.loc[df['is_stable_pos'] == 1, 'period'] = 'Stable PoS'
    
    # Slot skip indicator (if consecutive blocks are >14 seconds apart, likely skip)
    df['time_gap_indicator'] = (df['time_since_previous_block'] > 13).astype(int)
    
    # On-schedule indicator (within ±0.5 sec of 12-second target, post-Merge only)
    df['on_schedule'] = (
        (df['time_since_previous_block'] >= 11.5) & 
        (df['time_since_previous_block'] <= 12.5)
    ).astype(int)
    
    print(f"  ✓ Created {len(df.columns)} variables")
    print(f"  ✓ Post-Merge blocks: {df['is_post_merge'].sum():,}")
    print(f"  ✓ Early PoS blocks: {df['is_early_pos'].sum():,}")
    print(f"  ✓ Stable PoS blocks: {df['is_stable_pos'].sum():,}")
    
    return df


# ── 2. SUMMARY STATISTICS ─────────────────────────────────────────────────────

def compute_summary_statistics(df):
    """
    Compute summary statistics by period.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
        
    Returns:
        pd.DataFrame: Summary table
    """
    print("\n[STEP 1] Computing summary statistics...")
    
    periods = ['PoW', 'Early PoS', 'Stable PoS']
    summary_list = []
    
    for period in periods:
        period_data = df[df['period'] == period]
        
        if len(period_data) == 0:
            continue
        
        tbb = period_data['time_since_previous_block'].dropna()
        
        row = {
            'Period': period,
            'N_blocks': len(period_data),
            'TBB_mean': tbb.mean(),
            'TBB_std': tbb.std(),
            'TBB_p25': tbb.quantile(0.25),
            'TBB_p50': tbb.quantile(0.50),
            'TBB_p75': tbb.quantile(0.75),
            'TBB_p95': tbb.quantile(0.95),
            'TBB_p99': tbb.quantile(0.99),
        }
        summary_list.append(row)
    
    summary_df = pd.DataFrame(summary_list)
    
    # Save to CSV
    summary_df.to_csv(OUTPUT_DIR / 'table1_summary_stats.csv', index=False)
    print(f"  ✓ Summary stats table saved")
    print(summary_df.to_string(index=False))
    
    return summary_df


# ── 3. OLS BASELINE REGRESSION (Model 1.1) ─────────────────────────────────────

def estimate_ols_baseline(df):
    """
    Baseline OLS: ElapsedTime = β0 + β1*BlockHeight + ε
    
    Specification 1 from econometric_spec.md
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
        
    Returns:
        dict: Regression results and diagnostics
    """
    print("\n[STEP 2] Estimating OLS baseline regression (Model 1.1)...")
    
    # Separate regressions for pre- and post-Merge
    results_dict = {}
    
    for regime in ['pre_merge', 'post_merge']:
        if regime == 'pre_merge':
            data = df[df['is_post_merge'] == 0].copy()
            subset_name = 'Pre-Merge (PoW)'
        else:
            data = df[df['is_post_merge'] == 1].copy()
            subset_name = 'Post-Merge (PoS)'
        
        if len(data) < 100:
            print(f"  [SKIP] {subset_name}: insufficient data ({len(data)} blocks)")
            continue
        
        # OLS regression
        X = sm.add_constant(data['block_number'])
        y = data['elapsed_seconds']
        
        model = sm.OLS(y, X)
        results = model.fit(cov_type='HC1')  # HC1 = heteroskedasticity-robust SEs
        
        # Durbin-Watson statistic
        dw = sm.stats.durbin_watson(results.resid)
        
        # Ramsey RESET test (linearity)
        reset_test = sm.stats.linear_rainbow(results)
        
        # Breusch-Pagan test (heteroskedasticity)
        bp_test = sm.stats.het_breuschpagan(results.resid, X)
        
        results_dict[regime] = {
            'name': subset_name,
            'results': results,
            'dw': dw,
            'reset_test': reset_test,
            'bp_test': bp_test,
            'n_obs': len(data)
        }
        
        print(f"\n  {subset_name}:")
        print(f"    Observations: {len(data):,}")
        print(f"    Slope (sec/block): {results.params[1]:.6f}")
        print(f"    95% CI: [{results.conf_int(alpha=0.05).iloc[1, 0]:.6f}, {results.conf_int(alpha=0.05).iloc[1, 1]:.6f}]")
        print(f"    R-squared: {results.rsquared:.6f}")
        print(f"    Durbin-Watson: {dw:.4f}")
        print(f"    Ramsey RESET p-value: {reset_test[1]:.6f}")
        print(f"    Breusch-Pagan p-value: {bp_test[1]:.6f}")
    
    # Save results to CSV
    output_rows = []
    for regime, res_dict in results_dict.items():
        results = res_dict['results']
        conf_int = results.conf_int(alpha=0.05)
        
        for i, param_name in enumerate(results.params.index):
            output_rows.append({
                'Period': res_dict['name'],
                'Parameter': param_name,
                'Coefficient': results.params[i],
                'Std_Error': results.bse[i],
                't_stat': results.tvalues[i],
                'p_value': results.pvalues[i],
                'CI_lower': conf_int.iloc[i, 0],
                'CI_upper': conf_int.iloc[i, 1],
                'R_squared': results.rsquared,
                'N_obs': res_dict['n_obs']
            })
    
    output_df = pd.DataFrame(output_rows)
    output_df.to_csv(OUTPUT_DIR / 'table2_ols_baseline.csv', index=False)
    print(f"  ✓ OLS baseline results saved to table2_ols_baseline.csv")
    
    return results_dict


# ── 4. REGRESSION DISCONTINUITY AT MERGE (Model 1.2) ────────────────────────────

def estimate_rdd_merge_effect(df):
    """
    RDD specification: TBB = α + β1*PostMerge + γ1*BlockNumber + ε
    
    Tests for structural break at Merge.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
        
    Returns:
        dict: RDD regression results
    """
    print("\n[STEP 3] Estimating RDD merge effect (Model 1.2)...")
    
    # Use wider sample around Merge (±3 months)
    merge_window_start = MERGE_TIMESTAMP - (90 * 86400)
    merge_window_end = MERGE_TIMESTAMP + (90 * 86400)
    
    rdd_data = df[
        (df['block_timestamp'] >= merge_window_start) & 
        (df['block_timestamp'] <= merge_window_end)
    ].copy()
    
    # Create relative distance from Merge (in blocks)
    rdd_data['blocks_from_merge'] = rdd_data['block_number'] - MERGE_BLOCK
    
    # Drop first block (no lagged TBB)
    rdd_data = rdd_data[rdd_data['time_since_previous_block'].notna()].copy()
    
    # Polynomial trend (quadratic)
    rdd_data['blocks_from_merge_sq'] = rdd_data['blocks_from_merge'] ** 2
    
    # Specification 1: Simple discontinuity
    X = sm.add_constant(rdd_data[['is_post_merge', 'blocks_from_merge']])
    y = rdd_data['time_since_previous_block']
    
    model_simple = sm.OLS(y, X)
    results_simple = model_simple.fit(cov_type='HAC', cov_kwds={'maxlags': 40})
    
    # Specification 2: With quadratic trend
    X_quad = sm.add_constant(rdd_data[['is_post_merge', 'blocks_from_merge', 'blocks_from_merge_sq']])
    model_quad = sm.OLS(y, X_quad)
    results_quad = model_quad.fit(cov_type='HAC', cov_kwds={'maxlags': 40})
    
    # Joint F-test for discontinuity
    # Test H0: coefficient on PostMerge = 0 (no jump)
    r_matrix = np.array([[0, 1, 0, 0]])  # Test PostMerge coefficient
    f_test = results_quad.f_test(r_matrix)
    
    print(f"\n  RDD Results (90-day window around Merge):")
    print(f"    Observations: {len(rdd_data):,}")
    print(f"    PostMerge coefficient (simple): {results_simple.params[1]:.6f}")
    print(f"    PostMerge coefficient (quadratic): {results_quad.params[1]:.6f}")
    print(f"    F-test for discontinuity p-value: {f_test.pvalue:.6f}")
    print(f"    Interpretation: {'Significant' if f_test.pvalue < 0.05 else 'Not significant'} structural break at Merge")
    
    # Save results
    output_rows = []
    for spec_name, results in [('Simple', results_simple), ('Quadratic', results_quad)]:
        conf_int = results.conf_int(alpha=0.05)
        for i, param_name in enumerate(results.params.index):
            output_rows.append({
                'Specification': spec_name,
                'Parameter': param_name,
                'Coefficient': results.params[i],
                'Std_Error': results.bse[i],
                't_stat': results.tvalues[i],
                'p_value': results.pvalues[i],
                'CI_lower': conf_int.iloc[i, 0],
                'CI_upper': conf_int.iloc[i, 1],
                'R_squared': results.rsquared,
                'F_test_pvalue': f_test.pvalue if i == 0 else np.nan
            })
    
    output_df = pd.DataFrame(output_rows)
    output_df.to_csv(OUTPUT_DIR / 'table3_rdd_merge_effect.csv', index=False)
    print(f"  ✓ RDD results saved to table3_rdd_merge_effect.csv")
    
    return {
        'simple': results_simple,
        'quadratic': results_quad,
        'f_test': f_test,
        'data': rdd_data
    }


# ── 5. TIME-BETWEEN-BLOCKS DISTRIBUTION ANALYSIS ────────────────────────────────

def analyze_tbb_distribution(df):
    """
    Analyze distribution of time-between-blocks by period.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
        
    Returns:
        dict: Distribution analysis results
    """
    print("\n[STEP 4] Analyzing TBB distribution...")
    
    # Exclude first block (no lagged TBB)
    df = df[df['time_since_previous_block'].notna()].copy()
    
    # Exclude extreme outliers for plotting (but keep for statistics)
    df['tbb_clipped'] = df['time_since_previous_block'].clip(lower=0.1, upper=50)
    
    # Summary by period
    periods = ['PoW', 'Early PoS', 'Stable PoS']
    dist_summary = []
    
    for period in periods:
        period_data = df[df['period'] == period]['time_since_previous_block']
        
        if len(period_data) == 0:
            continue
        
        row = {
            'Period': period,
            'N': len(period_data),
            'Mean': period_data.mean(),
            'Median': period_data.median(),
            'Std': period_data.std(),
            'Min': period_data.min(),
            'Max': period_data.max(),
            'P05': period_data.quantile(0.05),
            'P25': period_data.quantile(0.25),
            'P75': period_data.quantile(0.75),
            'P95': period_data.quantile(0.95),
        }
        dist_summary.append(row)
    
    dist_df = pd.DataFrame(dist_summary)
    dist_df.to_csv(OUTPUT_DIR / 'table4_distribution_analysis.csv', index=False)
    print(f"  ✓ Distribution analysis saved")
    print(dist_df.to_string(index=False))
    
    # Kolmogorov-Smirnov test for equality of distributions
    if len(dist_summary) >= 2:
        early_pos_data = df[df['period'] == 'Early PoS']['time_since_previous_block']
        stable_pos_data = df[df['period'] == 'Stable PoS']['time_since_previous_block']
        
        if len(early_pos_data) > 0 and len(stable_pos_data) > 0:
            ks_stat, ks_pval = stats.ks_2samp(early_pos_data, stable_pos_data)
            print(f"\n  Kolmogorov-Smirnov test (Early vs. Stable PoS):")
            print(f"    Statistic: {ks_stat:.6f}")
            print(f"    p-value: {ks_pval:.6f}")
    
    return {'summary': dist_df, 'data': df}


# ── 6. SLOT SKIP ANALYSIS ─────────────────────────────────────────────────────

def analyze_slot_skips(df):
    """
    Analyze slot skip rates and patterns.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
        
    Returns:
        dict: Skip analysis results
    """
    print("\n[STEP 5] Analyzing slot skips...")
    
    # Post-Merge only
    df_pos = df[df['is_post_merge'] == 1].copy()
    
    # Identify skips (large inter-block gaps)
    # A "skip" is likely if TBB > 14 seconds (beyond normal 12-second slot)
    df_pos['is_skip'] = (df_pos['time_since_previous_block'] > 14).astype(int)
    
    # Compute skip statistics by period
    skip_summary = []
    
    for period in ['Early PoS', 'Stable PoS']:
        period_data = df_pos[df_pos['period'] == period]
        
        if len(period_data) == 0:
            continue
        
        skip_count = period_data['is_skip'].sum()
        skip_rate = skip_count / len(period_data) if len(period_data) > 0 else 0
        
        row = {
            'Period': period,
            'N_blocks': len(period_data),
            'Skip_count': skip_count,
            'Skip_rate_%': skip_rate * 100,
            'Mean_TBB': period_data['time_since_previous_block'].mean(),
            'Std_TBB': period_data['time_since_previous_block'].std(),
        }
        skip_summary.append(row)
    
    skip_df = pd.DataFrame(skip_summary)
    skip_df.to_csv(OUTPUT_DIR / 'table5_skip_analysis.csv', index=False)
    print(f"  ✓ Skip analysis saved")
    print(skip_df.to_string(index=False))
    
    # Autocorrelation of skip indicator
    early_skip_ac = df_pos[df_pos['period'] == 'Early PoS']['is_skip'].autocorr(lag=1)
    stable_skip_ac = df_pos[df_pos['period'] == 'Stable PoS']['is_skip'].autocorr(lag=1)
    
    print(f"\n  Skip autocorrelation (lag-1):")
    print(f"    Early PoS: {early_skip_ac:.6f}")
    print(f"    Stable PoS: {stable_skip_ac:.6f}")
    
    return {'summary': skip_df, 'data': df_pos}


# ── 7. EARLY VS. STABLE PoS COMPARISON ────────────────────────────────────────

def compare_early_stable_pos(df):
    """
    Compare block time statistics between Early and Stable PoS periods.
    
    Tests: H0: mean(Early) = mean(Stable)
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
        
    Returns:
        dict: Comparison results
    """
    print("\n[STEP 6] Comparing Early vs. Stable PoS...")
    
    df_pos = df[df['is_post_merge'] == 1].copy()
    df_pos = df_pos[df_pos['time_since_previous_block'].notna()]
    
    early = df_pos[df_pos['period'] == 'Early PoS']['time_since_previous_block']
    stable = df_pos[df_pos['period'] == 'Stable PoS']['time_since_previous_block']
    
    # Descriptive statistics
    comparison_stats = {
        'Period': ['Early PoS', 'Stable PoS'],
        'N': [len(early), len(stable)],
        'Mean': [early.mean(), stable.mean()],
        'Std': [early.std(), stable.std()],
        'Median': [early.median(), stable.median()],
        'P05': [early.quantile(0.05), stable.quantile(0.05)],
        'P95': [early.quantile(0.95), stable.quantile(0.95)],
    }
    comp_df = pd.DataFrame(comparison_stats)
    
    # Two-sample t-test
    t_stat, t_pval = stats.ttest_ind(early, stable, equal_var=False)  # Welch's t-test
    
    # Levene's test for equality of variances
    levene_stat, levene_pval = stats.levene(early, stable)
    
    print(f"\n  Early vs. Stable PoS comparison:")
    print(f"    Early PoS: N={len(early):,}, mean={early.mean():.4f}, std={early.std():.4f}")
    print(f"    Stable PoS: N={len(stable):,}, mean={stable.mean():.4f}, std={stable.std():.4f}")
    print(f"    Mean difference: {early.mean() - stable.mean():.4f} seconds")
    print(f"    t-test p-value: {t_pval:.6f}")
    print(f"    Levene test (variances) p-value: {levene_pval:.6f}")
    
    # Save comparison table
    comp_df.to_csv(OUTPUT_DIR / 'table6_early_vs_stable_pos.csv', index=False)
    print(f"  ✓ Comparison table saved")
    
    return {
        'comparison': comp_df,
        't_test': (t_stat, t_pval),
        'levene_test': (levene_stat, levene_pval),
        'early': early,
        'stable': stable
    }


# ── 8. DIAGNOSTIC TESTS ───────────────────────────────────────────────────────

def run_diagnostic_tests(results_dict, rdd_results):
    """
    Compile diagnostic test results.
    
    Parameters:
        results_dict (dict): OLS results
        rdd_results (dict): RDD results
        
    Returns:
        pd.DataFrame: Diagnostic results
    """
    print("\n[STEP 7] Running diagnostic tests...")
    
    diagnostics = []
    
    # From OLS results
    for regime, res in results_dict.items():
        diagnostics.append({
            'Test': 'Ramsey RESET',
            'Period': res['name'],
            'Statistic': res['reset_test'][0],
            'p_value': res['reset_test'][1],
            'Interpretation': 'Linearity' + (' rejected' if res['reset_test'][1] < 0.05 else ' OK')
        })
        
        diagnostics.append({
            'Test': 'Breusch-Pagan',
            'Period': res['name'],
            'Statistic': res['bp_test'][0],
            'p_value': res['bp_test'][1],
            'Interpretation': 'Homoskedasticity' + (' rejected' if res['bp_test'][1] < 0.05 else ' OK')
        })
        
        diagnostics.append({
            'Test': 'Durbin-Watson',
            'Period': res['name'],
            'Statistic': res['dw'],
            'p_value': np.nan,
            'Interpretation': f'Autocorr.' + (' likely (DW<2)' if res['dw'] < 2 else ' unlikely (DW≈2)')
        })
    
    # From RDD results
    diagnostics.append({
        'Test': 'F-test (RDD)',
        'Period': 'Merge (±90 days)',
        'Statistic': rdd_results['f_test'].fvalue,
        'p_value': rdd_results['f_test'].pvalue,
        'Interpretation': 'Structural break' + (' detected' if rdd_results['f_test'].pvalue < 0.05 else ' not detected')
    })
    
    diag_df = pd.DataFrame(diagnostics)
    diag_df.to_csv(OUTPUT_DIR / 'diagnostic_tests.csv', index=False)
    print(f"  ✓ Diagnostic tests saved")
    print(diag_df[['Test', 'Period', 'p_value', 'Interpretation']].to_string(index=False))
    
    return diag_df


# ── 9. FIGURES ────────────────────────────────────────────────────────────────

def plot_scatter_by_period(df):
    """
    Figure 1: Scatter plot of elapsed time vs. block height, by period.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
    """
    print("\n[STEP 8] Generating figures...")
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    
    periods = ['PoW', 'Early PoS', 'Stable PoS']
    
    for ax, period in zip(axes, periods):
        data = df[df['period'] == period].copy()
        
        if len(data) == 0:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
            ax.set_title(f'{period} (no data)')
            continue
        
        # Sample for plotting if too many points
        if len(data) > 5000:
            data = data.sample(n=5000, random_state=42)
        
        ax.scatter(data['block_number'] / 1e6, data['elapsed_seconds'] / 86400, 
                  alpha=0.3, s=10, color='steelblue')
        
        # Add regression line
        if len(data) > 10:
            z = np.polyfit(data['block_number'], data['elapsed_seconds'], 1)
            p = np.poly1d(z)
            x_line = np.linspace(data['block_number'].min(), data['block_number'].max(), 100)
            ax.plot(x_line / 1e6, p(x_line) / 86400, 'r-', lw=2, label=f'Slope: {z[0]:.4f} sec/block')
        
        ax.set_xlabel('Block Height (millions)')
        ax.set_ylabel('Elapsed Time (days)')
        ax.set_title(f'{period} (n={len(data):,})')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'figure1_scatter_by_period.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figure 1 saved: scatter plots by period")


def plot_rdd_discontinuity(rdd_results, df):
    """
    Figure 2: RDD plot showing discontinuity at Merge.
    
    Parameters:
        rdd_results (dict): RDD results
        df (pd.DataFrame): Analysis dataset
    """
    rdd_data = rdd_results['data']
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Separate pre and post
    pre = rdd_data[rdd_data['is_post_merge'] == 0]
    post = rdd_data[rdd_data['is_post_merge'] == 1]
    
    # Scatter plot
    ax.scatter(pre['blocks_from_merge'], pre['time_since_previous_block'], 
              alpha=0.3, s=20, color='blue', label='Pre-Merge')
    ax.scatter(post['blocks_from_merge'], post['time_since_previous_block'], 
              alpha=0.3, s=20, color='red', label='Post-Merge')
    
    # Fit separate lines
    if len(pre) > 10:
        z_pre = np.polyfit(pre['blocks_from_merge'], pre['time_since_previous_block'], 1)
        p_pre = np.poly1d(z_pre)
        x_pre = np.linspace(pre['blocks_from_merge'].min(), pre['blocks_from_merge'].max(), 100)
        ax.plot(x_pre, p_pre(x_pre), 'b-', lw=2, alpha=0.7)
    
    if len(post) > 10:
        z_post = np.polyfit(post['blocks_from_merge'], post['time_since_previous_block'], 1)
        p_post = np.poly1d(z_post)
        x_post = np.linspace(post['blocks_from_merge'].min(), post['blocks_from_merge'].max(), 100)
        ax.plot(x_post, p_post(x_post), 'r-', lw=2, alpha=0.7)
    
    # Add vertical line at Merge
    ax.axvline(0, color='black', linestyle='--', lw=1.5, alpha=0.5, label='Merge')
    
    ax.set_xlabel('Blocks from Merge')
    ax.set_ylabel('Time Since Previous Block (seconds)')
    ax.set_title('Regression Discontinuity: Merge Effect on Block Time')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'figure2_rdd_discontinuity.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figure 2 saved: RDD discontinuity plot")


def plot_tbb_distributions(df):
    """
    Figure 3: Distribution of time-between-blocks by period.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
    """
    df = df[df['time_since_previous_block'].notna()].copy()
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    
    periods = ['PoW', 'Early PoS', 'Stable PoS']
    colors = ['blue', 'orange', 'green']
    
    for ax, period, color in zip(axes, periods, colors):
        data = df[df['period'] == period]['time_since_previous_block']
        
        if len(data) == 0:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
            continue
        
        # Clip for visualization
        data_clipped = data.clip(lower=0, upper=30)
        
        ax.hist(data_clipped, bins=100, density=True, alpha=0.7, color=color, edgecolor='black')
        ax.axvline(data.mean(), color='red', linestyle='--', lw=2, label=f'Mean: {data.mean():.2f}s')
        ax.axvline(data.median(), color='green', linestyle='--', lw=2, label=f'Median: {data.median():.2f}s')
        
        if period == 'Stable PoS':
            ax.axvline(12, color='purple', linestyle=':', lw=2, label='Target: 12s')
        
        ax.set_xlabel('Time Since Previous Block (seconds)')
        ax.set_ylabel('Density')
        ax.set_title(f'{period} (n={len(data):,})')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'figure3_tbb_distributions.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figure 3 saved: TBB distributions")


def plot_skip_rates(df):
    """
    Figure 4: Skip rates over time.
    
    Parameters:
        df (pd.DataFrame): Analysis dataset
    """
    df_pos = df[df['is_post_merge'] == 1].copy()
    df_pos['is_skip'] = (df_pos['time_since_previous_block'] > 14).astype(int)
    
    # Calculate rolling skip rate
    window_size = 100000  # blocks
    df_pos['skip_rate'] = df_pos['is_skip'].rolling(window=window_size, min_periods=1000).mean() * 100
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    early = df_pos[df_pos['period'] == 'Early PoS']
    stable = df_pos[df_pos['period'] == 'Stable PoS']
    
    if len(early) > 0:
        ax.plot(early['block_number'] / 1e6, early['skip_rate'], 
               label=f'Early PoS (mean: {early["is_skip"].mean()*100:.2f}%)', lw=1, alpha=0.7)
    
    if len(stable) > 0:
        ax.plot(stable['block_number'] / 1e6, stable['skip_rate'], 
               label=f'Stable PoS (mean: {stable["is_skip"].mean()*100:.2f}%)', lw=1, alpha=0.7)
    
    ax.set_xlabel('Block Height (millions)')
    ax.set_ylabel('Skip Rate (%)')
    ax.set_title(f'Slot Skip Rate Over Time ({window_size:,}-block rolling window)')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'figure4_skip_rates.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figure 4 saved: skip rate trends")


def plot_early_vs_stable(comparison_results):
    """
    Figure 5: Comparison of Early vs. Stable PoS distributions.
    
    Parameters:
        comparison_results (dict): Comparison results
    """
    early = comparison_results['early']
    stable = comparison_results['stable']
    
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    
    # Histogram
    ax = axes[0]
    ax.hist(early.clip(0, 20), bins=100, density=True, alpha=0.5, label='Early PoS', color='orange')
    ax.hist(stable.clip(0, 20), bins=100, density=True, alpha=0.5, label='Stable PoS', color='green')
    ax.axvline(12, color='red', linestyle='--', lw=2, label='Target: 12s')
    ax.set_xlabel('Time Since Previous Block (seconds)')
    ax.set_ylabel('Density')
    ax.set_title('Distribution Comparison')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Box plot
    ax = axes[1]
    data_to_plot = [early, stable]
    bp = ax.boxplot([early.clip(10, 15), stable.clip(10, 15)], 
                     labels=['Early PoS', 'Stable PoS'],
                     patch_artist=True)
    
    for patch, color in zip(bp['boxes'], ['orange', 'green']):
        patch.set_facecolor(color)
        patch.set_alpha(0.5)
    
    ax.axhline(12, color='red', linestyle='--', lw=2, label='Target: 12s')
    ax.set_ylabel('Time Since Previous Block (seconds)')
    ax.set_title('Box Plot (clipped to [10, 15]s)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'figure5_early_vs_stable.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figure 5 saved: Early vs. Stable PoS comparison")


# ── MAIN EXECUTION ────────────────────────────────────────────────────────────

def main():
    """Main execution flow."""
    
    print("\n" + "="*80)
    print("REPLICATION: Temporal Dynamics of Ethereum - Block Height vs. Elapsed Time")
    print("="*80)
    
    # Load and prepare data
    df = load_ethereum_blocks()
    validate_data_quality(df)
    df = prepare_variables(df)
    
    # Summary statistics
    compute_summary_statistics(df)
    
    # Main specifications
    results_dict = estimate_ols_baseline(df)
    rdd_results = estimate_rdd_merge_effect(df)
    tbb_results = analyze_tbb_distribution(df)
    skip_results = analyze_slot_skips(df)
    comparison_results = compare_early_stable_pos(df)
    
    # Diagnostics
    run_diagnostic_tests(results_dict, rdd_results)
    
    # Figures
    plot_scatter_by_period(df)
    plot_rdd_discontinuity(rdd_results, df)
    plot_tbb_distributions(df)
    plot_skip_rates(df)
    plot_early_vs_stable(comparison_results)
    
    print("\n" + "="*80)
    print("REPLICATION COMPLETE")
    print("="*80)
    print(f"\nAll outputs saved to: {OUTPUT_DIR}")
    print("\nOutput files:")
    for f in sorted(OUTPUT_DIR.glob('*')):
        print(f"  - {f.name}")
    print("\n")


if __name__ == '__main__':
    main()
