#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
================================================================================
REPLICATION SCRIPT
No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement
================================================================================

Paper ID : e432cf3f-9008-4202-8ee6-ff09a93948ec
Question : Did the January 2024 approval of US spot Bitcoin ETFs change the
           co-movement between Bitcoin returns and US equity returns?
Design   : TWFE difference-in-differences on a coin-month panel of Fisher-z
           equity correlations, Bitcoin treated from 2024m2, nine never-listed
           crypto assets as controls, coin and year-month fixed effects,
           randomization inference as the governing inference procedure.

Specification source : ../econometric_spec.md   (equations, samples, inference)
Design source        : ../identification_strategy.md, ../identification_spec.json
Data source          : ../data_summary.md, ../data_dictionary.json

--------------------------------------------------------------------------------
REQUIREMENTS
--------------------------------------------------------------------------------
    python >= 3.9
    numpy  >= 1.24        (required)
    pandas >= 2.0         (required)
    matplotlib >= 3.7     (optional; figures are skipped if absent)

No scipy, statsmodels or linearmodels are required. Every distribution
function (incomplete beta / incomplete gamma / Student-t / F / chi-square),
the fixed-effect absorption, the cluster-robust and HAC covariance estimators,
the Nelder-Mead optimiser used for the DCC-GARCH, and the dynamic-programming
Bai-Perron routine are implemented in this file. This is deliberate: it removes
every version-dependent numerical dependency from the replication path, so the
published numbers are reproducible from numpy and pandas alone.

--------------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------------
    python estimation.py                       # everything (~5-15 min; DCC dominates)
    python estimation.py --skip-dcc            # everything except the DCC-GARCH (~1 min)
    python estimation.py --sections main       # headline DiD + its inference only
    python estimation.py --sections main,robustness
    python estimation.py --list-sections       # show the section map and exit
    python estimation.py --no-figures          # tables only

Sections declare their own dependencies and any missing prerequisite is run
automatically, so `--sections power` works without naming `main` first. Every
section is otherwise self-contained: section 5 (robustness) does not require
section 4b (returns-level models) to have been run.

--------------------------------------------------------------------------------
DATA REQUIREMENTS
--------------------------------------------------------------------------------
All inputs are researcher-supplied CSV files in `../data/` relative to this
script (override with --data-dir). No database, no API key, no credential is
used anywhere in this file. `replication/data_queries.sql` is present in the
package and contains only a header: none of the analysis data came from a
warehouse query, so there is no Allium table to re-query. `audit_log.csv` is
likewise header-only, and both are retained as the (empty) audit trail they are.

    coin_month_panel.csv        REQUIRED. The analysis panel. One row per
                                (asset_id, year_month, market_leg). Columns used:
                                y_fisherz_corr_equity, rho_m, beta_m, rho2_m,
                                ln_sigma_ratio_m, n_days_m, sd_i_m, sd_mkt_m,
                                cohort, d_donut, d_in_headline_sample, market_leg.
    daily_returns.csv           REQUIRED. Daily returns, ET-dated, one column per
                                asset (r_BTC ... r_XLM), equity legs (r_SPY,
                                r_ACWX, mktrf ...) and macro levels (lvl_VIX,
                                lvl_MOVE). Crypto legs are struck 00:00-00:00 UTC.
    rolling_diagnostics.csv     REQUIRED for the daily/break sections. 30/60/90-day
                                rolling correlations and betas, rho{w}d_{ASSET}_{LEG}.
    crypto_offday_returns.csv   REQUIRED for the off-day-span alignment row.
    px_{ASSET}_USD.csv          REQUIRED for the UTC-alignment row (one per coin).

If an optional input is missing the dependent row is skipped with a printed
warning and the rest of the script still completes.

--------------------------------------------------------------------------------
OUTPUT
--------------------------------------------------------------------------------
Everything is written to `replication/output/`:
    * one CSV per paper table (table1_*.csv ... table15_*.csv), plus the
      supporting coefficient/diagnostic files;
    * `output_map.csv`, the machine-readable table-to-file map;
    * PNG figures;
    * `estimation_results.json` and `robustness_results.json`, byte-comparable
      in content with the sidecars the paper's numbers are drawn from.
Running the script also (re)writes `replication/README.md` and
`replication/requirements.txt` from the registry built during the run, so the
documentation cannot drift away from what the code actually produces.

--------------------------------------------------------------------------------
REPRODUCIBILITY
--------------------------------------------------------------------------------
`np.random.seed(42)` is set at import. The only stochastic procedure in the
paper is the wild cluster bootstrap, which draws Rademacher weights from a
dedicated generator seeded with 20240110 (BOOTSTRAP_SEED) -- the seed used for
the published run. Changing it moves the bootstrap p-value by roughly +/-0.02
and nothing else. Everything else -- randomization inference, Conley-Taber,
Bai-Perron, the BDM collapse -- is deterministic: the placebo grid enumerates
assignments exhaustively rather than sampling them.

--------------------------------------------------------------------------------
STANDARD ERRORS
--------------------------------------------------------------------------------
The headline reports cluster-robust standard errors on the coin dimension
because referees expect the column, but **they are not the inferential basis**.
With one treated cluster the CRVE has no valid asymptotic justification
(Conley-Taber 2011; MacKinnon-Webb 2017) and is roughly three times too narrow
here. The p-value the paper quotes is the randomization p-value over the
combined placebo-in-space-and-time grid (econometric_spec.md section 8). Where
this script prints both, the randomization one governs. Returns-level and
time-series specifications use Newey-West HAC standard errors with the
Andrews/Newey-West rule L = floor(4*(T/100)^(2/9)); the Chow test additionally
reports an HC3 Wald, and the Andrews sup-Wald is reported in both an iid and an
L=60 HAC version because the rolling-window overlap makes the iid version
useless (140.41 vs 6.39).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Reproducibility ───────────────────────────────────────────────────────────
np.random.seed(42)          # global seed, per replication policy
BOOTSTRAP_SEED = 20240110   # wild cluster bootstrap; seed of the published run
RNG = np.random.default_rng(BOOTSTRAP_SEED)

# ── Paths (no hardcoded absolute paths, no credentials) ───────────────────────
HERE = Path(__file__).resolve().parent          # .../replication
ROOT = HERE.parent                              # workspace root
DATA_DIR = ROOT / "data"
OUTPUT_DIR = HERE / "output"

# ── Design constants (econometric_spec.md sections 1 and 3.2) ────────────────
TREAT_MONTH = "2024-02"          # treatment month: 2024m2, after the donut
LISTING_DATE = "2024-01-11"      # commencement of trading, 09:30 ET
TREAT_DATE = "2024-02-01"        # daily-frequency counterpart of TREAT_MONTH
DONUT = ["2023-08", "2023-09", "2023-10", "2023-11", "2023-12", "2024-01"]
DONUT_START, DONUT_END = "2023-08-01", "2024-01-31"
SAMPLE_START, SAMPLE_END = "2021-01", "2025-12"
PANEL_END_FULL = "2026-07"       # the full delivered panel
CONTROLS = ["LTC", "BNB", "ADA", "DOGE", "BCH", "LINK", "AVAX", "DOT", "XLM"]
HEADLINE = ["BTC"] + CONTROLS    # 1 treated + 9 never-treated
EXCLUDED_EVENTUALLY_TREATED = ["ETH", "SOL", "XRP"]  # never in the control group

Z95, Z80 = 1.959963985, 0.8416212336
MDE_MULT = Z95 + Z80             # 2.80158, alpha = 0.05 two-sided, power = 0.80

BIN = 6                          # event-study bin width, months
REF_BIN = -2                     # reference bin: K = -12..-7 (ends at the donut)

# ── Global state, populated by load_data() ───────────────────────────────────
PANEL: pd.DataFrame | None = None
DAILY: pd.DataFrame | None = None
ROLL: pd.DataFrame | None = None

RESULTS: dict = {}    # -> estimation_results.json
ROBUST: dict = {}     # -> robustness_results.json
OUTPUT_MAP: list = []  # -> output_map.csv and the README output map


# =============================================================================
# 0. UTILITIES: distribution functions and the optimiser
#    (implemented here so the replication path needs only numpy + pandas)
# =============================================================================
def _betacf(a, b, x):
    """Continued-fraction expansion for the incomplete beta function."""
    MAXIT, EPS, FPMIN = 400, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for mm in range(1, MAXIT + 1):
        m2 = 2 * mm
        aa = mm * (b - mm) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = FPMIN if abs(d) < FPMIN else d
        c = 1.0 + aa / c
        c = FPMIN if abs(c) < FPMIN else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + mm) * (qab + mm) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = FPMIN if abs(d) < FPMIN else d
        c = 1.0 + aa / c
        c = FPMIN if abs(c) < FPMIN else c
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def betainc(a, b, x):
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lb = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
          + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(lb)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_sf(t, df):
    """Upper-tail survival function of Student's t."""
    if t is None or not np.isfinite(t):
        return None
    df = max(float(df), 1.0)
    p = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return float(p if t > 0 else 1.0 - p)


_TPPF_CACHE: dict = {}


def t_ppf(p, df):
    """Student-t quantile by bisection (cached)."""
    key = (round(float(p), 8), round(float(df), 4))
    if key in _TPPF_CACHE:
        return _TPPF_CACHE[key]
    lo, hi = -1.0e3, 1.0e3
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        if (1.0 - t_sf(mid, df)) < p:
            lo = mid
        else:
            hi = mid
    _TPPF_CACHE[key] = 0.5 * (lo + hi)
    return _TPPF_CACHE[key]


def f_sf(f, d1, d2):
    """Upper-tail survival function of the F distribution."""
    if f <= 0 or not np.isfinite(f):
        return 1.0
    return float(betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f)))


def _gser(a, x):
    ap, s, d = a, 1.0 / a, 1.0 / a
    for _ in range(800):
        ap += 1.0
        d *= x / ap
        s += d
        if abs(d) < abs(s) * 3e-16:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a, x):
    FPMIN = 1e-300
    b, c, d = x + 1.0 - a, 1.0 / FPMIN, 1.0 / (x + 1.0 - a)
    h = d
    for i in range(1, 800):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = FPMIN if abs(d) < FPMIN else d
        c = b + an / c
        c = FPMIN if abs(c) < FPMIN else c
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-16:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x, k):
    """Upper-tail survival function of the chi-square distribution."""
    if x <= 0 or not np.isfinite(x):
        return 1.0
    a, xx = k / 2.0, x / 2.0
    return float(1.0 - _gser(a, xx) if xx < a + 1.0 else _gcf(a, xx))


def norm_sf(x):
    """Upper-tail survival function of the standard normal."""
    return float(0.5 * math.erfc(x / math.sqrt(2.0)))


def nelder_mead(f, x0, maxiter=1500, tol=1e-9, step=0.25):
    """Derivative-free simplex minimiser; used for the GARCH/DCC QML stages."""
    n = len(x0)
    sim = [np.asarray(x0, float)]
    for i in range(n):
        y = np.asarray(x0, float).copy()
        y[i] += step if y[i] == 0 else step * abs(y[i])
        sim.append(y)
    sim = np.array(sim)
    fs = np.array([f(s) for s in sim])
    nit = 0
    for nit in range(maxiter):
        o = np.argsort(fs)
        sim, fs = sim[o], fs[o]
        if (np.max(np.abs(fs[1:] - fs[0])) < tol
                and np.max(np.abs(sim[1:] - sim[0])) < tol):
            break
        cen = sim[:-1].mean(axis=0)
        xr = cen + (cen - sim[-1])
        fr = f(xr)
        if fr < fs[0]:
            xe = cen + 2.0 * (cen - sim[-1])
            fe = f(xe)
            if fe < fr:
                sim[-1], fs[-1] = xe, fe
            else:
                sim[-1], fs[-1] = xr, fr
        elif fr < fs[-2]:
            sim[-1], fs[-1] = xr, fr
        else:
            xc = cen + 0.5 * (sim[-1] - cen)
            fc = f(xc)
            if fc < fs[-1]:
                sim[-1], fs[-1] = xc, fc
            else:
                sim[1:] = sim[0] + 0.5 * (sim[1:] - sim[0])
                fs[1:] = np.array([f(s) for s in sim[1:]])
    o = np.argsort(fs)
    return sim[o][0], float(fs[o][0]), nit < maxiter - 1


# =============================================================================
# 0b. ESTIMATORS: absorbed fixed effects, cluster-robust / HC / HAC covariance
# =============================================================================
def _demean(mat, groups, tol=1e-11, maxiter=500):
    """Alternating-projections within transformation for multiple FE dimensions."""
    X = np.asarray(mat, dtype=float)
    X = X[:, None].copy() if X.ndim == 1 else X.copy()
    if not groups:
        return X
    codes = [pd.Categorical(g).codes for g in groups]
    for _ in range(maxiter):
        dev = 0.0
        for cd in codes:
            k = cd.max() + 1
            cnt = np.bincount(cd, minlength=k).astype(float)[:, None]
            sums = np.zeros((k, X.shape[1]))
            np.add.at(sums, cd, X)
            means = sums / cnt
            X -= means[cd]
            dev = max(dev, float(np.abs(means).max()))
        if dev < tol:
            break
    return X


def _cluster_meat(Xd, resid, gvals, k):
    cd = pd.Categorical(gvals).codes
    ng = cd.max() + 1
    scores = np.zeros((ng, k))
    np.add.at(scores, cd, Xd * resid[:, None])
    return scores.T @ scores, ng


def feols(df, y, xs, fes=(), cluster=None, cluster2=None, hc="HC1"):
    """
    OLS with absorbed fixed effects.

    cluster       one-way cluster-robust covariance on this column
    cluster2      adds the second dimension (Cameron-Gelbach-Miller two-way)
    hc            heteroskedasticity-robust variant when no cluster is given
                  ("HC1" default, "HC3" available)

    Degrees of freedom subtract the absorbed FE parameters; the small-sample
    cluster adjustment is G/(G-1) * (n-1)/dof and t-tests use G-1 df.
    """
    xs = list(xs)
    d = df.dropna(subset=[y] + xs + list(fes)).copy()
    n = len(d)
    yv = d[y].to_numpy(float)
    Xv = d[xs].to_numpy(float)
    glist = [d[f].to_numpy() for f in fes]
    names = xs

    if fes:
        yd = _demean(yv, glist).ravel()
        Xd = _demean(Xv, glist)
        n_fe = sum(len(np.unique(g)) for g in glist) - (len(glist) - 1)
    else:
        yd, Xd = yv, np.column_stack([np.ones(n), Xv])
        n_fe = 0
        names = ["const"] + xs

    XtX_inv = np.linalg.pinv(Xd.T @ Xd)
    beta = XtX_inv @ (Xd.T @ yd)
    resid = yd - Xd @ beta
    k = Xd.shape[1]
    dof = max(n - k - n_fe, 1)

    if cluster is not None:
        meat, G = _cluster_meat(Xd, resid, d[cluster].to_numpy(), k)
        if cluster2 is not None:
            m2, G2 = _cluster_meat(Xd, resid, d[cluster2].to_numpy(), k)
            inter = (pd.Series(d[cluster].astype(str).to_numpy())
                     + "_" + pd.Series(d[cluster2].astype(str).to_numpy())).to_numpy()
            m12, _ = _cluster_meat(Xd, resid, inter, k)
            meat = meat + m2 - m12
            G = min(G, G2)
        adj = (G / (G - 1)) * ((n - 1) / dof)
        V = XtX_inv @ (adj * meat) @ XtX_inv
        n_clusters, df_t = G, G - 1
    else:
        w = np.full(n, n / dof)
        if hc == "HC3":
            lev = np.einsum("ij,jk,ik->i", Xd, XtX_inv, Xd)
            w = 1.0 / np.clip(1.0 - lev, 1e-8, None) ** 2
        meat = (Xd * (resid ** 2 * w)[:, None]).T @ Xd
        V = XtX_inv @ meat @ XtX_inv
        n_clusters, df_t = None, dof

    V = (V + V.T) / 2.0
    se = np.sqrt(np.clip(np.diag(V), 0.0, None))
    tss = float(((yd - yd.mean()) ** 2).sum())
    within_r2 = (1 - float((resid ** 2).sum()) / tss) if tss > 0 else None
    crit = t_ppf(0.975, max(df_t, 1))

    coefs = {}
    for j, nm in enumerate(names):
        t = float(beta[j] / se[j]) if se[j] > 0 else None
        p = (2 * t_sf(abs(t), max(df_t, 1))) if t is not None else None
        coefs[nm] = {
            "estimate": float(beta[j]),
            "se": float(se[j]),
            "t_stat": t,
            "p_value": float(p) if p is not None else None,
            "ci_lower": float(beta[j] - crit * se[j]),
            "ci_upper": float(beta[j] + crit * se[j]),
        }
    return {"coefficients": coefs, "n": n, "n_clusters": n_clusters,
            "within_r2": within_r2, "df_residual": int(dof), "vcov": V,
            "beta": beta, "names": names, "resid": resid, "yd": yd, "Xd": Xd,
            "data": d}


def nw_lags(T):
    """Newey-West lag rule L = floor(4 * (T/100)^(2/9))."""
    return max(1, int(np.floor(4 * (T / 100.0) ** (2.0 / 9.0))))


def ols_hac(y, X, names, L=None):
    """OLS with Newey-West HAC covariance (Bartlett kernel)."""
    y, X = np.asarray(y, float), np.asarray(X, float)
    n, k = X.shape
    L = nw_lags(n) if L is None else L
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    e = y - X @ beta
    S = (X * (e ** 2)[:, None]).T @ X
    for lg in range(1, L + 1):
        w = 1.0 - lg / (L + 1.0)
        G = (X[lg:] * e[lg:, None]).T @ (X[:-lg] * e[:-lg, None])
        S += w * (G + G.T)
    S *= n / max(n - k, 1)
    V = (XtX_inv @ S @ XtX_inv)
    V = (V + V.T) / 2.0
    se = np.sqrt(np.clip(np.diag(V), 0.0, None))
    out = {}
    for j, nm in enumerate(names):
        t = float(beta[j] / se[j]) if se[j] > 0 else None
        out[nm] = {"estimate": float(beta[j]), "se": float(se[j]), "t_stat": t,
                   "p_value": float(2 * t_sf(abs(t), n - k)) if t else None,
                   "ci_lower": float(beta[j] - 1.96 * se[j]),
                   "ci_upper": float(beta[j] + 1.96 * se[j])}
    tss = float(((y - y.mean()) ** 2).sum())
    return {"coefficients": out, "n": n, "nw_lags": L, "V": V, "beta": beta,
            "names": names,
            "r_squared": (1 - float((e ** 2).sum()) / tss) if tss > 0 else None}


def spec_entry(res, name, fes, controls, cluster_level, extra=None, diag_extra=None):
    """Normalise an feols result into the sidecar schema."""
    out = {
        "specification": name,
        "n_observations": int(res["n"]),
        "n_clusters": int(res["n_clusters"]) if res["n_clusters"] else None,
        "cluster_level": cluster_level,
        "fixed_effects": list(fes),
        "controls": list(controls),
        "coefficients": dict(res["coefficients"]),
        "diagnostics": {
            "within_r_squared": (round(res["within_r2"], 6)
                                 if res["within_r2"] is not None else None),
            "df_residual": int(res["df_residual"]),
            "n_fixed_effect_groups": None,
        },
    }
    if diag_extra:
        out["diagnostics"].update(diag_extra)
    if extra:
        out.update(extra)
    return out


# =============================================================================
# 0c. OUTPUT HELPERS
# =============================================================================
def register(filename, paper_object, description):
    OUTPUT_MAP.append({"paper_object": paper_object, "file": filename,
                       "description": description})


def write_table(df, filename, paper_object, description):
    """Write one CSV and register it in the output map."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_DIR / filename, index=False)
    register(filename, paper_object, description)
    print(f"    -> output/{filename}   [{paper_object}]")


def coef_frame(spec, label=None):
    """Flatten a spec's coefficient block into a tidy frame."""
    rows = []
    for term, c in spec.get("coefficients", {}).items():
        row = {"specification": label or spec.get("specification", "")[:60],
               "term": term}
        for f in ("estimate", "se", "t_stat", "p_value", "ci_lower", "ci_upper"):
            row[f] = c.get(f)
        rows.append(row)
    return pd.DataFrame(rows)


def stat_frame(spec, fields, labels=None):
    """Pull named scalar fields (top level or inside diagnostics) into a frame."""
    labels = labels or {}
    rows = []
    for f in fields:
        val = spec.get(f, spec.get("diagnostics", {}).get(f))
        rows.append({"statistic": labels.get(f, f), "value": val})
    return pd.DataFrame(rows)


def _clean(o):
    """JSON-safe conversion; drops the heavy arrays feols carries around."""
    DROP = {"vcov", "beta", "names", "resid", "data", "V", "yd", "Xd"}
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if k not in DROP}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer, int)) and not isinstance(o, bool):
        return int(o)
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else round(f, 8)
    return o


# =============================================================================
# 1. LOAD DATA
# =============================================================================
def _require(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required input not found: {path}\n"
            f"Point --data-dir at the directory holding the researcher-supplied "
            f"CSVs (see DATA REQUIREMENTS in the header of this file)."
        )
    return path


def load_data():
    """Section 1. Load the three core inputs and add derived indicators."""
    global PANEL, DAILY, ROLL
    if PANEL is not None:
        return
    print("=== 1. loading data ===", flush=True)
    PANEL = pd.read_csv(_require(DATA_DIR / "coin_month_panel.csv"))
    DAILY = pd.read_csv(_require(DATA_DIR / "daily_returns.csv"),
                        parse_dates=["date_et"])
    roll_path = DATA_DIR / "rolling_diagnostics.csv"
    ROLL = (pd.read_csv(roll_path, parse_dates=["date_et"])
            if roll_path.exists() else pd.DataFrame())

    # ── 2. Variable construction ─────────────────────────────────────────────
    # The panel already carries the generated outcome
    #   y_fisherz_corr_equity = atanh(rho_im),  se ~ (n_im - 3)^(-1/2)
    # built by build_panel.py; see data_summary.md. The only variables
    # constructed here are the treatment indicators, which are rebuilt from
    # (asset_id, year_month) rather than read from the file so that the
    # treatment definition lives in exactly one place.
    PANEL["is_btc"] = (PANEL.asset_id == "BTC").astype(int)
    print(f"    panel {PANEL.shape}  daily {DAILY.shape}  rolling {ROLL.shape}",
          flush=True)


def headline_sample(assets=None, leg="SPY", donut=True,
                    start=SAMPLE_START, end=SAMPLE_END):
    """
    Headline estimation sample (econometric_spec.md section 3.2):
      BTC + 9 never-treated coins, SPY leg, donut 2023m8-2024m1 dropped,
      2021m1-2025m12. ETH/SOL/XRP are excluded because they are eventually
      treated: keeping them would create not-yet-treated vs already-treated
      comparisons and the negative weights that come with them.
    """
    assets = HEADLINE if assets is None else assets
    d = PANEL[(PANEL.asset_id.isin(assets)) & (PANEL.market_leg == leg)
              & (PANEL.year_month >= start) & (PANEL.year_month <= end)].copy()
    return d[~d.year_month.isin(DONUT)] if donut else d


def add_treat(d, treated="BTC", month=TREAT_MONTH, col="d_etf_listed"):
    """D_im = 1{i = treated} * 1{m >= month}. Treated x Post; both mains absorbed."""
    d = d.copy()
    d[col] = ((d.asset_id == treated) & (d.year_month >= month)).astype(int)
    return d


def kmonth(ym):
    """Event time in months relative to TREAT_MONTH."""
    y_, mo = int(ym[:4]), int(ym[5:7])
    return (y_ - int(TREAT_MONTH[:4])) * 12 + (mo - int(TREAT_MONTH[5:7]))


def build_monthly(dfd, assets, mkt="r_SPY", exclude=None, winsor=False):
    """
    Rebuild the monthly Fisher-z outcome from daily returns.

    Used by the robustness rows that change the daily inputs (alignment,
    winsorizing, dropped news days, alternative equity leg). A coin-month needs
    at least 10 overlapping sessions. Correlations are clipped at +/-0.999
    before atanh so the transform stays finite.
    """
    d = dfd.copy()
    if exclude is not None:
        d = d[~d.date_et.isin(exclude)]
    d["year_month"] = d.date_et.dt.strftime("%Y-%m")
    rows = []
    for a in assets:
        col_ = f"r_{a}"
        if col_ not in d.columns:
            continue
        s = d[["year_month", col_, mkt]].dropna().copy()
        if winsor:
            lo_, hi_ = s[col_].quantile([0.005, 0.995])
            s[col_] = s[col_].clip(lo_, hi_)
        for ym, g in s.groupby("year_month"):
            if len(g) < 10 or g[col_].std() == 0 or g[mkt].std() == 0:
                continue
            rho = float(np.clip(np.corrcoef(g[col_], g[mkt])[0, 1], -0.999, 0.999))
            beta = float(np.cov(g[col_], g[mkt])[0, 1] / np.var(g[mkt], ddof=1))
            rows.append({"asset_id": a, "year_month": ym, "n_days_m": len(g),
                         "rho_m": rho, "y_fisherz_corr_equity": float(np.arctanh(rho)),
                         "beta_m": beta})
    o = pd.DataFrame(rows)
    return o[(o.year_month >= SAMPLE_START) & (o.year_month <= SAMPLE_END)]


# =============================================================================
# 3. SUMMARY STATISTICS  (paper Table 1 and Table 2)
# =============================================================================
def section_summary(ctx):
    """Descriptives and the model-free pre/post contrast. No estimation."""
    print("=== 3. summary statistics ===", flush=True)
    full = PANEL[(PANEL.asset_id.isin(HEADLINE)) & (PANEL.market_leg == "SPY")
                 & (PANEL.year_month >= SAMPLE_START)
                 & (PANEL.year_month <= PANEL_END_FULL)]
    full = full[~full.year_month.isin(DONUT)]

    # ---- Table 1: summary statistics on the coin-month panel ----------------
    vars_ = [("y_fisherz_corr_equity", "Fisher-z correlation with SPY"),
             ("rho_m", "Correlation with SPY, rho_im"),
             ("rho2_m", "Variance share, rho_im^2"),
             ("beta_m", "Equity beta, beta_im"),
             ("ln_sigma_ratio_m", "ln(sigma_i / sigma_mkt)"),
             ("n_days_m", "Sessions per coin-month, n_im")]
    rows = []
    for col, lab in vars_:
        if col not in full.columns:
            continue
        s = full[col].dropna()
        rows.append({"variable": lab, "column": col, "n": int(s.size),
                     "mean": float(s.mean()), "sd": float(s.std(ddof=1)),
                     "p25": float(s.quantile(0.25)), "median": float(s.median()),
                     "p75": float(s.quantile(0.75)),
                     "min": float(s.min()), "max": float(s.max())})
    for a, lab in [("BTC", "Daily return SD, Bitcoin"), ("SPY", "Daily return SD, SPY")]:
        c = f"r_{a}"
        if c in DAILY.columns:
            s = DAILY[c].dropna()
            rows.append({"variable": lab, "column": c, "n": int(s.size),
                         "mean": float(s.mean()), "sd": float(s.std(ddof=1)),
                         "p25": None, "median": None, "p75": None,
                         "min": float(s.min()), "max": float(s.max())})
    tab1 = pd.DataFrame(rows)
    # Table 1 in the paper: "Summary statistics, coin-month panel" (tab:sumstats)
    write_table(tab1, "table1_summary_statistics.csv", "Table 1 (tab:sumstats)",
                "Descriptives for the coin-month panel, 2021m1-2026m7, donut excluded.")

    counts = pd.DataFrame([{"statistic": "coin-month observations", "value": int(len(full))},
                           {"statistic": "coins", "value": int(full.asset_id.nunique())},
                           {"statistic": "months", "value": int(full.year_month.nunique())},
                           {"statistic": "headline sample observations",
                            "value": int(len(headline_sample()))}])
    write_table(counts, "table1b_panel_counts.csv", "Table 1 footer (tab:sumstats)",
                "Panel dimensions for the descriptive and the headline samples.")

    # ---- Table 2: raw (model-free) pre/post contrast -------------------------
    pre = full[full.year_month < "2023-08"]
    post = full[full.year_month >= TREAT_MONTH]
    rc_rows = []
    for stat, col in [("rho", "rho_m"), ("fisherz", "y_fisherz_corr_equity"),
                      ("beta", "beta_m")]:
        b_pre = float(pre[pre.asset_id == "BTC"][col].mean())
        b_post = float(post[post.asset_id == "BTC"][col].mean())
        c_pre = float(pre[pre.asset_id != "BTC"].groupby("asset_id")[col].mean().mean())
        c_post = float(post[post.asset_id != "BTC"].groupby("asset_id")[col].mean().mean())
        rc_rows.append({"statistic": stat, "btc_pre": b_pre, "btc_post": b_post,
                        "btc_change": b_post - b_pre,
                        "control_mean_pre": c_pre, "control_mean_post": c_post,
                        "control_change": c_post - c_pre,
                        "raw_did": (b_post - b_pre) - (c_post - c_pre)})
    # Table 2 in the paper: "Raw pre/post contrast in mean correlation with SPY"
    write_table(pd.DataFrame(rc_rows), "table2_raw_contrast.csv",
                "Table 2 (tab:rawcontrast)",
                "Model-free pre/post means and the raw DiD, before any estimation.")

    by_asset = (full.assign(period=np.where(full.year_month >= TREAT_MONTH, "post",
                                            np.where(full.year_month < "2023-08",
                                                     "pre", "donut")))
                .query("period != 'donut'")
                .groupby(["asset_id", "period"], as_index=False)
                .agg(rho=("rho_m", "mean"),
                     fisherz=("y_fisherz_corr_equity", "mean"),
                     beta=("beta_m", "mean"), n_months=("rho_m", "size")))
    write_table(by_asset, "table2b_prepost_by_asset.csv", "Figure 5 input (fig:prepost_change)",
                "Pre- and post-period means of each outcome, by asset.")
    ctx["prepost_by_asset"] = by_asset
    return ctx


# =============================================================================
# 4. MAIN SPECIFICATION  (paper Table 3) AND ITS INFERENCE (paper Table 4)
#
#     y_im = tau * D_im + alpha_i + delta_m + eps_im
#
#     y_im  Fisher-z within-month correlation of coin i's daily return with SPY
#     D_im  1{i = BTC} * 1{m >= 2024m2}
#     alpha_i  coin FE          delta_m  year-month FE          controls: none
#
# Controls are deliberately empty: volume, market cap and realized volatility
# are mediators of the ETF treatment, not confounders (bad controls). VIX and
# MOVE main effects are absorbed by delta_m; their *interacted* form is a
# robustness row (R4), which is the version month FE cannot absorb.
# =============================================================================
def section_main(ctx):
    print("=== 4. main specification (TWFE DiD) ===", flush=True)
    smp = add_treat(headline_sample())
    m = feols(smp, "y_fisherz_corr_equity", ["d_etf_listed"],
              fes=["asset_id", "year_month"], cluster="asset_id")
    tau = float(m["beta"][0])
    se_cl = m["coefficients"]["d_etf_listed"]["se"]
    n_pre = int(((smp.asset_id == "BTC") & (smp.year_month < TREAT_MONTH)).sum())
    n_post = int(((smp.asset_id == "BTC") & (smp.year_month >= TREAT_MONTH)).sum())
    rho_pre = float(smp[(smp.asset_id == "BTC")
                        & (smp.year_month < TREAT_MONTH)].rho_m.mean())
    print(f"    tau = {tau:+.5f}  (cluster SE {se_cl:.5f})  N = {m['n']}  "
          f"G = {smp.asset_id.nunique()}", flush=True)

    # ── Randomization inference: PRIMARY (econometric_spec.md section 8.2) ────
    # Placebo-in-space: give the real date to each never-treated coin in turn.
    # Placebo-in-time: give every month in 2021m7-2023m1 to every coin, on the
    # pre-period sample only, so the real treatment cannot contaminate the grid.
    # p_RI = (#{|tau_placebo| >= |tau|} + 1) / (#placebos + 1).
    print("    randomization inference (placebo-in-space x placebo-in-time)...",
          flush=True)
    placebo_space = []
    for c in CONTROLS:
        s = add_treat(headline_sample(), treated=c)
        r = feols(s, "y_fisherz_corr_equity", ["d_etf_listed"],
                  fes=["asset_id", "year_month"])
        placebo_space.append(float(r["beta"][0]))

    cand = [mm for mm in sorted(PANEL.year_month.unique()) if "2021-07" <= mm <= "2023-01"]
    base_pre = headline_sample(donut=False, end="2023-07")
    placebo_time = []
    for c in HEADLINE:
        for pm in cand:
            s = add_treat(base_pre, treated=c, month=pm)
            r = feols(s, "y_fisherz_corr_equity", ["d_etf_listed"],
                      fes=["asset_id", "year_month"])
            placebo_time.append(float(r["beta"][0]))

    grid = np.array(placebo_space + placebo_time)
    p_ri = float((np.sum(np.abs(grid) >= abs(tau)) + 1) / (len(grid) + 1))
    p_ri_space = float((np.sum(np.abs(placebo_space) >= abs(tau)) + 1)
                       / (len(placebo_space) + 1))
    sd_ri = float(np.std(grid, ddof=1))
    # Conley-Taber: the control-group placebo distribution supplies the
    # reference distribution for the single treated unit.
    ct_lo = float(tau - np.percentile(placebo_space, 97.5))
    ct_hi = float(tau - np.percentile(placebo_space, 2.5))
    sd_ct = float(np.std(placebo_space, ddof=1))
    print(f"    RI grid n={len(grid)}  p_RI={p_ri:.3f}  p_space={p_ri_space:.3f}  "
          f"sd_RI={sd_ri:.5f}", flush=True)

    # ── Wild cluster bootstrap (Rademacher, null imposed) ─────────────────────
    # Reported with the MacKinnon-Webb caveat: with a single treated cluster
    # this procedure is unreliable. It is not the inferential basis.
    yd, Xd = m["yd"], m["Xd"]
    cd = pd.Categorical(m["data"].asset_id.to_numpy()).codes
    ncl = cd.max() + 1
    XtXi = float(1.0 / (Xd[:, 0] @ Xd[:, 0]))
    t_obs = m["coefficients"]["d_etf_listed"]["t_stat"]
    nrow = len(yd)
    adj_b = (ncl / (ncl - 1)) * (
        (nrow - 1) / max(nrow - 1 - (m["data"].asset_id.nunique()
                                     + m["data"].year_month.nunique() - 1), 1))
    tstars = []
    for _ in range(999):
        w = RNG.choice([-1.0, 1.0], size=ncl)[cd]
        ys = w * yd                      # null imposed: restricted resid = demeaned y
        b = XtXi * float(Xd[:, 0] @ ys)
        e = ys - Xd[:, 0] * b
        sc = np.zeros(ncl)
        np.add.at(sc, cd, Xd[:, 0] * e)
        v = XtXi * (adj_b * float(sc @ sc)) * XtXi
        if v > 0:
            tstars.append(b / math.sqrt(v))
    tstars = np.array(tstars)
    p_wild = float((np.sum(np.abs(tstars) >= abs(t_obs)) + 1) / (len(tstars) + 1))
    print(f"    wild cluster bootstrap p = {p_wild:.3f} (unreliable; 1 treated cluster)",
          flush=True)

    RESULTS["main"] = spec_entry(
        m,
        "TWFE difference-in-differences on the coin-month panel; outcome is the Fisher-z "
        "within-month correlation of the coin's daily return with SPY; coin and year-month "
        "fixed effects; no controls (volume/volatility/market cap are mediators, not "
        "confounders); SEs clustered on coin; randomization inference is the primary "
        "inference procedure because there is one treated unit.",
        fes=["coin", "year_month"], controls=[], cluster_level="coin",
        extra={
            "unit_of_analysis": "coin-month",
            "outcome": "y_fisherz_corr_equity",
            "treatment": "d_etf_listed",
            "treated_units": 1,
            "n_pre_treatment": n_pre,
            "n_post_treatment": n_post,
            "sample_window": f"{SAMPLE_START} to {SAMPLE_END}; donut 2023m8-2024m1 excluded",
            "p_value_ri": p_ri,
            "p_value_ri_space_only": p_ri_space,
            "p_value_wild_bootstrap": p_wild,
            "n_placebo_assignments": int(len(grid)),
            "ri_sd": sd_ri,
            "conley_taber_ci_lower": ct_lo,
            "conley_taber_ci_upper": ct_hi,
            "ri_ci95_lower": float(tau - Z95 * sd_ri),
            "ri_ci95_upper": float(tau + Z95 * sd_ri),
            "rho_pre_treatment_mean": rho_pre,
            "correlation_conversion_factor": float(1 - rho_pre ** 2),
            "effect_in_correlation_units": float((1 - rho_pre ** 2) * tau),
        },
        diag_extra={"n_coin_fe": int(smp.asset_id.nunique()),
                    "n_month_fe": int(smp.year_month.nunique()),
                    "n_clusters_coin": int(smp.asset_id.nunique())})
    RESULTS["main"]["diagnostics"]["n_fixed_effect_groups"] = int(
        smp.asset_id.nunique() + smp.year_month.nunique() - 1)

    # ── Descriptive raw gap: NOT the headline (econometric_spec.md section 4) ──
    # Bitcoin only, no control group, no fixed effects, Newey-West(6). Reported
    # so the reader can see what the control group and month FE are doing.
    btc = headline_sample(assets=["BTC"]).sort_values("year_month")
    Xrg = np.column_stack([np.ones(len(btc)),
                           (btc.year_month >= TREAT_MONTH).astype(float).to_numpy()])
    rg = ols_hac(btc.y_fisherz_corr_equity.to_numpy(), Xrg, ["const", "post_etf"], L=6)
    RESULTS["descriptive_raw_gap"] = {
        "specification": "DESCRIPTIVE BASELINE, NOT IDENTIFIED: Bitcoin-only monthly time "
                         "series of the Fisher-z equity correlation on a post-2024m2 "
                         "indicator, Newey-West(6). Cannot separate the ETF from the 2024 "
                         "macro regime.",
        "unit_of_analysis": "month", "outcome": "y_fisherz_corr_equity",
        "treatment": "post_etf", "n_observations": rg["n"], "n_clusters": None,
        "cluster_level": "none", "fixed_effects": [], "controls": [],
        "n_pre_treatment": n_pre, "n_post_treatment": n_post,
        "coefficients": rg["coefficients"],
        "diagnostics": {"r_squared": rg["r_squared"], "newey_west_lags": rg["nw_lags"],
                        "df_residual": int(rg["n"] - 2), "n_fixed_effect_groups": 0,
                        "mean_y_pre": float(
                            btc[btc.year_month < TREAT_MONTH].y_fisherz_corr_equity.mean()),
                        "mean_y_post": float(
                            btc[btc.year_month >= TREAT_MONTH].y_fisherz_corr_equity.mean())},
    }

    # ---- Table 3: the headline DiD -----------------------------------------
    t3 = coef_frame(RESULTS["main"], "main (TWFE DiD)")
    t3 = pd.concat([t3, coef_frame(RESULTS["descriptive_raw_gap"],
                                   "descriptive raw gap (NOT identified)")],
                   ignore_index=True)
    # Table 3 in the paper: "The spot-ETF listing and Bitcoin's equity co-movement"
    write_table(t3, "table3_main_did.csv", "Table 3 (tab:main)",
                "Headline TWFE DiD coefficient and the descriptive Bitcoin-only gap.")

    t3b = stat_frame(RESULTS["main"],
                     ["within_r_squared", "n_pre_treatment", "n_post_treatment",
                      "n_clusters", "n_observations", "df_residual",
                      "n_fixed_effect_groups"])
    write_table(t3b, "table3b_main_diagnostics.csv", "Table 3 footer (tab:main)",
                "Sample and fixed-effect diagnostics for the headline specification.")

    # ---- Table 4: inference procedures under a single treated unit ----------
    t4 = stat_frame(RESULTS["main"],
                    ["effect_in_correlation_units", "rho_pre_treatment_mean",
                     "p_value_ri", "p_value_ri_space_only", "p_value_wild_bootstrap",
                     "n_placebo_assignments", "ri_sd", "ri_ci95_lower", "ri_ci95_upper",
                     "conley_taber_ci_lower", "conley_taber_ci_upper", "n_observations"])
    t4 = pd.concat([
        pd.DataFrame([{"statistic": "tau (Fisher-z)", "value": tau},
                      {"statistic": "cluster-robust SE (NOT the inferential basis)",
                       "value": se_cl},
                      {"statistic": "cluster-robust p (NOT the inferential basis)",
                       "value": m["coefficients"]["d_etf_listed"]["p_value"]},
                      {"statistic": "cluster-robust CI lower",
                       "value": m["coefficients"]["d_etf_listed"]["ci_lower"]},
                      {"statistic": "cluster-robust CI upper",
                       "value": m["coefficients"]["d_etf_listed"]["ci_upper"]}]),
        t4], ignore_index=True)
    # Table 4 in the paper: "Inference procedures ... under a single treated unit"
    write_table(t4, "table4_inference.csv", "Table 4 (tab:inference)",
                "Randomization, Conley-Taber, wild bootstrap and clustered inference "
                "side by side. The randomization p-value governs.")

    write_table(pd.DataFrame({"placebo_estimate": grid,
                              "kind": (["space"] * len(placebo_space)
                                       + ["time"] * len(placebo_time))}),
                "table4b_randomization_grid.csv", "Figure 4 input (RI density)",
                "The full placebo-in-space-and-time grid behind the headline p-value.")

    ctx.update(dict(smp=smp, m=m, tau=tau, se_cl=se_cl, n_pre=n_pre, n_post=n_post,
                    rho_pre=rho_pre, grid=grid, placebo_space=placebo_space,
                    placebo_time=placebo_time, p_ri=p_ri, p_ri_space=p_ri_space,
                    sd_ri=sd_ri, sd_ct=sd_ct, ct_lo=ct_lo, ct_hi=ct_hi))
    return ctx


# =============================================================================
# 4b. EVENT STUDY AND PARALLEL TRENDS  (paper Table 5)
#
# Six-month event-time bins relative to 2024m2, reference bin -2 (K = -12..-7).
# Bins rather than single months: a month-by-month event study is SATURATED for
# a single treated unit -- BTC's residual is identically zero in every month
# carrying its own dummy -- so the SEs would be computed off the control coins
# alone. The joint pre-trend F is reported both asymptotically and, the version
# that counts, as a randomization p-value over placebo treated coins.
# =============================================================================
def section_event(ctx):
    print("=== 4b. event study and pre-trends ===", flush=True)
    n_pre, n_post = ctx["n_pre"], ctx["n_post"]
    es = headline_sample().copy()
    es["K"] = es.year_month.map(kmonth)
    es["KB"] = np.floor(es.K / BIN).astype(int)
    kbs = sorted(k for k in es.KB.unique() if k != REF_BIN)
    for k in kbs:
        es[f"ev_{k}"] = ((es.asset_id == "BTC") & (es.KB == k)).astype(int)
    evcols = [f"ev_{k}" for k in kbs]
    ev = feols(es, "y_fisherz_corr_equity", evcols,
               fes=["asset_id", "year_month"], cluster="asset_id")

    lead_idx = [i for i, k in enumerate(kbs) if k < REF_BIN]
    R = np.zeros((len(lead_idx), len(kbs)))
    for r_, i_ in enumerate(lead_idx):
        R[r_, i_] = 1.0
    Rb = R @ ev["beta"]
    W = float(Rb @ np.linalg.pinv(R @ ev["vcov"] @ R.T) @ Rb)
    q = len(lead_idx)
    F_pre = W / q
    p_pre = f_sf(F_pre, q, es.asset_id.nunique() - 1)

    pre = es[es.K <= -7].copy()
    pre["btc_trend"] = (pre.asset_id == "BTC").astype(float) * pre.K
    lin = feols(pre, "y_fisherz_corr_equity", ["btc_trend"],
                fes=["asset_id", "year_month"], cluster="asset_id")

    def pretrend_F(dfx, treated):
        d2 = dfx.copy()
        for kk in kbs:
            d2[f"ev_{kk}"] = ((d2.asset_id == treated) & (d2.KB == kk)).astype(int)
        rr = feols(d2, "y_fisherz_corr_equity", evcols,
                   fes=["asset_id", "year_month"], cluster="asset_id")
        bb = R @ rr["beta"]
        return float(bb @ np.linalg.pinv(R @ rr["vcov"] @ R.T) @ bb) / q

    placebo_F = [pretrend_F(es, c) for c in CONTROLS]
    p_pre_ri = float((np.sum(np.array(placebo_F) >= F_pre) + 1) / (len(placebo_F) + 1))

    placebo_lin = []
    for c in CONTROLS:
        p2 = pre.copy()
        p2["btc_trend"] = (p2.asset_id == c).astype(float) * p2.K
        placebo_lin.append(abs(float(
            feols(p2, "y_fisherz_corr_equity", ["btc_trend"],
                  fes=["asset_id", "year_month"])["beta"][0])))
    p_lin_ri = float((np.sum(np.array(placebo_lin) >= abs(float(lin["beta"][0]))) + 1)
                     / (len(placebo_lin) + 1))

    # Month-by-month path: point estimates only (saturated -> no valid SEs).
    esm = headline_sample().copy()
    esm["K"] = esm.year_month.map(kmonth).clip(-24, 24)
    kms = sorted(k for k in esm.K.unique() if k != -7)
    for k in kms:
        esm[f"m_{k}"] = ((esm.asset_id == "BTC") & (esm.K == k)).astype(int)
    evm = feols(esm, "y_fisherz_corr_equity", [f"m_{k}" for k in kms],
                fes=["asset_id", "year_month"])
    monthly_path = {str(k): round(float(evm["beta"][i]), 6) for i, k in enumerate(kms)}

    RESULTS["event_study"] = {
        "specification": "Event study in six-month event-time bins relative to 2024m2, with "
                         f"coin and year-month fixed effects; reference bin {REF_BIN} "
                         "(K = -12 to -7, the six months ending at the donut, since the "
                         "conventional k = -1 falls inside the donut). Clustered on coin.",
        "unit_of_analysis": "coin-month", "outcome": "y_fisherz_corr_equity",
        "treatment": "btc_x_event_bin", "bin_width_months": BIN,
        "n_observations": int(ev["n"]), "n_clusters": int(es.asset_id.nunique()),
        "cluster_level": "coin", "fixed_effects": ["coin", "year_month"], "controls": [],
        "n_pre_treatment": n_pre, "n_post_treatment": n_post,
        "reference_period": REF_BIN,
        "coefficients": ev["coefficients"],
        "pre_trend_f_stat": F_pre, "pre_trend_p_value": p_pre, "n_pre_coefficients": q,
        "pre_trend_p_value_ri": p_pre_ri,
        "pre_trend_placebo_F_max": float(np.max(placebo_F)),
        "pre_trend_placebo_F_median": float(np.median(placebo_F)),
        "n_placebo_assignments": len(placebo_F),
        "pre_trend_inference_note": "pre_trend_p_value is the clustered/asymptotic F "
                                    "p-value and is subject to the same one-treated-unit "
                                    "objection as the clustered p-value on tau. "
                                    "pre_trend_p_value_ri is the valid test.",
        "linear_pre_trend_estimate": float(lin["beta"][0]),
        "linear_pre_trend_se": lin["coefficients"]["btc_trend"]["se"],
        "linear_pre_trend_p_value": lin["coefficients"]["btc_trend"]["p_value"],
        "linear_pre_trend_p_value_ri": p_lin_ri,
        "monthly_path_point_estimates": monthly_path,
        "monthly_path_note": "Point estimates only; the month-by-month specification is "
                             "saturated for the single treated unit.",
        "diagnostics": {"within_r_squared": round(ev["within_r2"], 6),
                        "df_residual": int(ev["df_residual"]),
                        "n_fixed_effect_groups": int(es.asset_id.nunique()
                                                     + es.year_month.nunique() - 1)},
    }
    print(f"    pre-trend F = {F_pre:.3f}  p_asym = {p_pre:.4f}  p_RI = {p_pre_ri:.3f}  "
          f"(median placebo F = {np.median(placebo_F):.2f})", flush=True)

    # ---- Table 5: event study + pre-trend tests -----------------------------
    t5 = coef_frame(RESULTS["event_study"], "event study (6-month bins)")
    ref_row = pd.DataFrame([{"specification": "event study (6-month bins)",
                             "term": f"ev_{REF_BIN} (reference)", "estimate": 0.0,
                             "se": None, "t_stat": None, "p_value": None,
                             "ci_lower": None, "ci_upper": None}])
    t5 = pd.concat([t5, ref_row], ignore_index=True)
    # Table 5 in the paper: "Event study in six-month bins, and tests of parallel pre-trends"
    write_table(t5, "table5_event_study.csv", "Table 5 (tab:event_study)",
                "Binned event-study coefficients, reference bin -2.")

    t5b = stat_frame(RESULTS["event_study"],
                     ["pre_trend_f_stat", "pre_trend_p_value", "pre_trend_p_value_ri",
                      "pre_trend_placebo_F_median", "pre_trend_placebo_F_max",
                      "linear_pre_trend_estimate", "linear_pre_trend_se",
                      "linear_pre_trend_p_value", "linear_pre_trend_p_value_ri",
                      "n_observations"])
    write_table(t5b, "table5b_pretrend_tests.csv", "Table 5 panel B (tab:event_study)",
                "Joint and linear pre-trend tests, asymptotic and randomization versions.")

    write_table(pd.DataFrame({"event_month_K": list(monthly_path.keys()),
                              "estimate": list(monthly_path.values())}),
                "table5c_monthly_path.csv", "Section 5 text (descriptive)",
                "Month-by-month event-time point estimates; saturated, no valid SEs.")

    ctx["event_coefs"] = ev["coefficients"]
    return ctx


# =============================================================================
# 4c. COMPLEMENTARY SPECIFICATIONS
#     daily rolling panel DiD, returns-level interacted model and triple
#     difference, Chow test, Bai-Perron endogenous break dating.
#     (paper Tables 6, 7 and the complementary table; Figures 1-2)
# =============================================================================
def daily_panel(window, leg="SPY", assets=None, treated="BTC", stat="rho",
                treat_date=TREAT_DATE, donut=True,
                start="2021-01-01", end="2025-12-31"):
    """Long asset-day panel of Fisher-z rolling correlations from rolling_diagnostics.csv."""
    assets = HEADLINE if assets is None else assets
    have = {a: f"{stat}{window}d_{a}_{leg}" for a in assets
            if f"{stat}{window}d_{a}_{leg}" in ROLL.columns}
    sub = ROLL[["date_et"] + list(have.values())]
    sub = sub[(sub.date_et >= start) & (sub.date_et <= end)]
    long = sub.melt("date_et", var_name="col", value_name="val").dropna()
    long["asset_id"] = long.col.map({v: k for k, v in have.items()})
    if donut:
        long = long[~((long.date_et >= DONUT_START) & (long.date_et <= DONUT_END))]
    long["y"] = (np.arctanh(long.val.clip(-0.999, 0.999)) if stat == "rho" else long.val)
    long["d_etf_listed"] = ((long.asset_id == treated)
                            & (long.date_et >= treat_date)).astype(int)
    long["date_s"] = long.date_et.dt.strftime("%Y-%m-%d")
    return long


def section_daily(ctx):
    """Daily rolling-window panel DiD at 30 / 60 / 90 days (R1)."""
    print("=== 4c. daily rolling-window panel DiD ===", flush=True)
    if ROLL is None or ROLL.empty:
        print("    [skip] rolling_diagnostics.csv not available", flush=True)
        return ctx
    for w, key in [(30, "daily_rolling_did"), (60, "window_60d"), (90, "window_90d")]:
        lp = daily_panel(w)
        if lp.empty:
            print(f"    [skip] no {w}d columns found", flush=True)
            continue
        rr = feols(lp, "y", ["d_etf_listed"], fes=["asset_id", "date_s"],
                   cluster="asset_id")
        rr2 = feols(lp, "y", ["d_etf_listed"], fes=["asset_id", "date_s"],
                    cluster="asset_id", cluster2="date_s")
        ent = spec_entry(
            rr,
            f"Daily rolling-window DiD: Fisher-z of the {w}-day rolling correlation with "
            "SPY, asset and date fixed effects, clustered on asset. Windows overlap, so "
            "the number of independent blocks (n_effective_blocks) is far below the row "
            "count and the SE must not be read as coming from n_observations "
            "independent draws.",
            fes=["asset", "date"], controls=[], cluster_level="asset",
            extra={"unit_of_analysis": "asset-day", "outcome": f"fisherz_rho{w}d_spy",
                   "treatment": "d_etf_listed", "treated_units": 1,
                   "rolling_window_days": w,
                   "n_effective_blocks": int(round(rr["n"] / w)),
                   "n_pre_treatment": int(((lp.asset_id == "BTC")
                                           & (lp.date_et < TREAT_DATE)).sum()),
                   "n_post_treatment": int(((lp.asset_id == "BTC")
                                            & (lp.date_et >= TREAT_DATE)).sum()),
                   "se_twoway_cluster": rr2["coefficients"]["d_etf_listed"]["se"],
                   "p_value_twoway_cluster": rr2["coefficients"]["d_etf_listed"]["p_value"]},
            diag_extra={"n_dates": int(lp.date_s.nunique()),
                        "n_assets": int(lp.asset_id.nunique())})
        ent["diagnostics"]["n_fixed_effect_groups"] = int(lp.asset_id.nunique()
                                                          + lp.date_s.nunique() - 1)
        (RESULTS if key == "daily_rolling_did" else ROBUST)[key] = ent
        print(f"    w = {w:>2}d: tau = {rr['beta'][0]:+.5f}  N = {rr['n']}  "
              f"(effective blocks {ent['n_effective_blocks']})", flush=True)

    rows = []
    for key in ["daily_rolling_did", "window_60d", "window_90d"]:
        s = RESULTS.get(key) or ROBUST.get(key)
        if not s:
            continue
        c = s["coefficients"]["d_etf_listed"]
        rows.append({"window_days": s["rolling_window_days"], "estimate": c["estimate"],
                     "se_cluster_asset": c["se"], "p_value": c["p_value"],
                     "se_twoway": s["se_twoway_cluster"],
                     "n_observations": s["n_observations"],
                     "n_effective_blocks": s["n_effective_blocks"]})
    if rows:
        # Table 15 in the paper: alternative rolling windows (robustness_windows)
        write_table(pd.DataFrame(rows), "table15_rolling_windows.csv",
                    "Table 15 (tab:robustness_windows)",
                    "Daily rolling-window DiD at 30/60/90 days, with effective block counts.")
    return ctx


def section_returns(ctx):
    """Returns-level interacted model (Table 6), triple difference (Table 7), Chow test."""
    print("=== 4d. returns-level models ===", flush=True)
    dd = DAILY[(DAILY.date_et >= "2021-01-01") & (DAILY.date_et <= "2025-12-31")].copy()
    dd = dd[~((dd.date_et >= DONUT_START) & (dd.date_et <= DONUT_END))]
    dd["post"] = (dd.date_et >= TREAT_DATE).astype(int)

    # ---- per-asset interacted model: r_i = a + b r_spy + d (r_spy x Post) + g Post
    per_delta = {}
    for a in HEADLINE:
        if f"r_{a}" not in dd.columns:
            continue
        s = dd[["date_et", f"r_{a}", "r_SPY", "post"]].dropna()
        X = np.column_stack([np.ones(len(s)), s.r_SPY.to_numpy(),
                             (s.r_SPY * s.post).to_numpy(), s.post.to_numpy(float)])
        r = ols_hac(s[f"r_{a}"].to_numpy(), X, ["const", "r_spy", "r_spy_x_post", "post"])
        per_delta[a] = r
        if a == "BTC":
            RESULTS["returns_interacted_BTC"] = {
                "specification": "Returns-level interacted model for Bitcoin: r_btc = a + "
                                 "b*r_spy + delta*(r_spy x Post) + g*Post, Newey-West HAC "
                                 "standard errors. delta is the change in the equity "
                                 "loading, estimated without a generated-regressor step.",
                "unit_of_analysis": "day", "outcome": "r_BTC",
                "treatment": "r_spy_x_post", "n_observations": r["n"],
                "n_clusters": None, "cluster_level": "none", "fixed_effects": [],
                "controls": ["r_spy", "post"],
                "n_pre_treatment": int((s.post == 0).sum()),
                "n_post_treatment": int((s.post == 1).sum()),
                "coefficients": r["coefficients"],
                "diagnostics": {"r_squared": r["r_squared"],
                                "newey_west_lags": r["nw_lags"],
                                "df_residual": int(r["n"] - 4),
                                "n_fixed_effect_groups": 0},
            }
    ctrl_d = [per_delta[a]["coefficients"]["r_spy_x_post"]["estimate"]
              for a in CONTROLS if a in per_delta]
    btc_d = per_delta["BTC"]["coefficients"]["r_spy_x_post"]["estimate"]
    RESULTS["returns_interacted_BTC"].update({
        "p_value_ri_across_control_coins": float(
            (np.sum(np.abs(ctrl_d) >= abs(btc_d)) + 1) / (len(ctrl_d) + 1)),
        "control_coin_delta_mean": float(np.mean(ctrl_d)),
        "control_coin_delta_sd": float(np.std(ctrl_d, ddof=1)),
        "control_coin_deltas": {a: float(per_delta[a]["coefficients"]["r_spy_x_post"]
                                         ["estimate"]) for a in CONTROLS if a in per_delta},
    })
    print(f"    BTC delta = {btc_d:+.5f};  control mean = "
          f"{np.mean(ctrl_d):+.5f} (sd {np.std(ctrl_d, ddof=1):.4f});  "
          f"p_RI = {RESULTS['returns_interacted_BTC']['p_value_ri_across_control_coins']:.2f}",
          flush=True)

    # Table 6 in the paper: "Bitcoin's equity loading before and after the listing"
    t6 = coef_frame(RESULTS["returns_interacted_BTC"], "returns interacted, BTC")
    write_table(t6, "table6_returns_interacted.csv", "Table 6 (tab:returns_interacted)",
                "Returns-level equity loading for Bitcoin with an interacted post dummy, HAC SEs.")
    write_table(pd.DataFrame([{"asset": a, "delta_r_spy_x_post": v}
                              for a, v in RESULTS["returns_interacted_BTC"]
                              ["control_coin_deltas"].items()]
                             + [{"asset": "BTC", "delta_r_spy_x_post": btc_d}]),
                "table6b_control_coin_deltas.csv", "Table 6 panel B (tab:returns_interacted)",
                "Per-coin change in the equity loading; the control distribution is the "
                "randomization reference for Bitcoin's.")

    # ---- pooled returns-level triple difference -----------------------------
    have = [f"r_{a}" for a in HEADLINE if f"r_{a}" in dd.columns]
    rl = dd.melt(["date_et", "r_SPY", "post"], value_vars=have,
                 var_name="col", value_name="r").dropna()
    rl["asset_id"] = rl.col.str[2:]
    isb = (rl.asset_id == "BTC").astype(float)
    rl["reqXbtc"] = rl.r_SPY * isb
    rl["reqXpostXbtc"] = rl.r_SPY * rl.post * isb
    rl["date_s"] = rl.date_et.dt.strftime("%Y-%m-%d")
    ddd = feols(rl, "r", ["reqXpostXbtc", "reqXbtc"], fes=["asset_id", "date_s"],
                cluster="date_s")
    ddd_a = feols(rl, "r", ["reqXpostXbtc", "reqXbtc"], fes=["asset_id", "date_s"],
                  cluster="asset_id")
    ent = spec_entry(
        ddd,
        "Pooled returns-level triple difference: r_it on (r_spy x Post x BTC) and "
        "(r_spy x BTC), with asset and date fixed effects, which absorb r_spy and "
        "r_spy x Post. Uses no generated regressor, so the Fisher-z transform cannot "
        "drive the result. Clustered on date.",
        fes=["asset", "date"], controls=["reqXbtc"], cluster_level="date",
        extra={"unit_of_analysis": "asset-day", "outcome": "r_asset",
               "treatment": "reqXpostXbtc", "treated_units": 1,
               "n_pre_treatment": int((rl.post == 0).sum()),
               "n_post_treatment": int((rl.post == 1).sum()),
               "se_cluster_asset": ddd_a["coefficients"]["reqXpostXbtc"]["se"],
               "p_value_cluster_asset": ddd_a["coefficients"]["reqXpostXbtc"]["p_value"]},
        diag_extra={"n_dates": int(rl.date_s.nunique()),
                    "n_assets": int(rl.asset_id.nunique())})
    ent["diagnostics"]["n_fixed_effect_groups"] = int(rl.asset_id.nunique()
                                                      + rl.date_s.nunique() - 1)
    RESULTS["returns_ddd"] = ent
    print(f"    DDD = {ddd['beta'][0]:+.5f} "
          f"(se {ddd['coefficients']['reqXpostXbtc']['se']:.5f})", flush=True)
    # Table 7 in the paper: "Returns-level triple difference"
    write_table(coef_frame(RESULTS["returns_ddd"], "returns DDD"),
                "table7_returns_ddd.csv", "Table 7 (tab:ddd)",
                "Triple-difference estimate of the differential change in Bitcoin's "
                "equity loading; no generated regressor.")

    # ---- Chow test at the imposed break date --------------------------------
    def chow(s, ycol, brk=TREAT_DATE):
        s = s.dropna(subset=[ycol, "r_SPY"])
        post = (s.date_et >= brk).astype(float).to_numpy()
        x, y = s.r_SPY.to_numpy(), s[ycol].to_numpy()
        X = np.column_stack([np.ones(len(s)), x, post, x * post])
        n, k = X.shape
        XtXi = np.linalg.pinv(X.T @ X)
        b = XtXi @ (X.T @ y)
        e = y - X @ b
        Rm = np.zeros((2, k))
        Rm[0, 2] = 1.0
        Rm[1, 3] = 1.0
        Vc = (float(e @ e) / (n - k)) * XtXi
        F_cl = float((Rm @ b) @ np.linalg.pinv(Rm @ Vc @ Rm.T) @ (Rm @ b) / 2.0)
        lev = np.einsum("ij,jk,ik->i", X, XtXi, X)
        V3 = XtXi @ ((X * (e ** 2 / np.clip(1 - lev, 1e-8, None) ** 2)[:, None]).T @ X) @ XtXi
        W3 = float((Rm @ b) @ np.linalg.pinv(Rm @ V3 @ Rm.T) @ (Rm @ b))
        hac = ols_hac(y, X, ["const", "r_spy", "post", "r_spy_x_post"])
        Wh = float((Rm @ hac["beta"]) @ np.linalg.pinv(Rm @ hac["V"] @ Rm.T)
                   @ (Rm @ hac["beta"]))
        return {"f_stat_classical": F_cl, "p_value_classical": f_sf(F_cl, 2, n - k),
                "wald_hc3": W3, "p_value_hc3": chi2_sf(W3, 2),
                "wald_hac_newey_west": Wh, "p_value_hac": chi2_sf(Wh, 2),
                "n": n, "nw_lags": hac["nw_lags"], "coefficients": hac["coefficients"]}

    ch = chow(dd[["date_et", "r_BTC", "r_SPY"]], "r_BTC")
    raw = DAILY[(DAILY.date_et >= "2021-01-01") & (DAILY.date_et <= "2025-12-31")]
    chn = chow(raw[["date_et", "r_BTC", "r_SPY"]], "r_BTC", brk=LISTING_DATE)
    RESULTS["chow_test"] = {
        "specification": "Chow test for a structural break in Bitcoin's equity-loading "
                         "regression at the imposed date 2024-02-01 (donut sample). "
                         "Classical F, HC3 Wald and HAC (Newey-West) Wald are all reported "
                         "because they differ; the HAC Wald is the one to quote.",
        "unit_of_analysis": "day", "outcome": "r_BTC", "treatment": "break_2024_02_01",
        "n_observations": ch["n"], "n_clusters": None, "cluster_level": "none",
        "fixed_effects": [], "controls": ["r_spy", "post"],
        "n_pre_treatment": int((dd.date_et < TREAT_DATE).sum()),
        "n_post_treatment": int((dd.date_et >= TREAT_DATE).sum()),
        "coefficients": ch["coefficients"],
        "f_stat_classical": ch["f_stat_classical"],
        "p_value_classical": ch["p_value_classical"],
        "wald_hc3": ch["wald_hc3"], "p_value_hc3": ch["p_value_hc3"],
        "wald_hac_newey_west": ch["wald_hac_newey_west"], "p_value_hac": ch["p_value_hac"],
        "wald_hac_no_donut_2024_01_11": chn["wald_hac_newey_west"],
        "p_value_hac_no_donut": chn["p_value_hac"],
        "diagnostics": {"newey_west_lags": ch["nw_lags"],
                        "df_residual": int(ch["n"] - 4), "n_fixed_effect_groups": 0},
    }
    print(f"    Chow: classical F = {ch['f_stat_classical']:.3f}, HC3 W = "
          f"{ch['wald_hc3']:.3f}, HAC W = {ch['wald_hac_newey_west']:.3f} "
          f"(p = {ch['p_value_hac']:.3f})", flush=True)
    write_table(stat_frame(RESULTS["chow_test"],
                           ["f_stat_classical", "p_value_classical", "wald_hc3",
                            "p_value_hc3", "wald_hac_newey_west", "p_value_hac",
                            "wald_hac_no_donut_2024_01_11", "p_value_hac_no_donut",
                            "n_observations", "newey_west_lags"]),
                "table8b_chow_test.csv", "Complementary table (tab:complementary)",
                "Chow test at the imposed break date in three covariance flavours.")
    return ctx


def section_breaks(ctx):
    """Bai-Perron endogenous break dating and the Andrews sup-Wald."""
    print("=== 4e. endogenous break dating ===", flush=True)
    if ROLL is None or ROLL.empty:
        print("    [skip] rolling_diagnostics.csv not available", flush=True)
        return ctx

    def bai_perron(y, m_max=5, trim=0.15):
        """Global SSR minimisation by dynamic programming; BIC and LWZ selection."""
        y = np.asarray(y, float)
        T = len(y)
        h = max(2, int(np.floor(trim * T)))
        cs = np.concatenate([[0.0], np.cumsum(y)])
        cs2 = np.concatenate([[0.0], np.cumsum(y ** 2)])
        ii = np.arange(T)[:, None]
        jj = np.arange(T)[None, :]
        nn = jj - ii + 1
        sm = cs[jj + 1] - cs[ii]
        sq = cs2[jj + 1] - cs2[ii]
        with np.errstate(invalid="ignore", divide="ignore"):
            S = np.where(nn >= h, sq - sm * sm / np.maximum(nn, 1), np.inf)
        out = {0: {"ssr": float(S[0, T - 1]), "breaks": []}}
        prev = S[0, :].copy()
        prev_idx = [[] for _ in range(T)]
        for mb in range(1, m_max + 1):
            cur = np.full(T, np.inf)
            cur_idx = [[] for _ in range(T)]
            lo_b = h * mb - 1
            for j in range(h * (mb + 1) - 1, T):
                hi_b = j - h
                if hi_b < lo_b:
                    continue
                cand = prev[lo_b:hi_b + 1] + S[lo_b + 1:hi_b + 2, j]
                if not np.any(np.isfinite(cand)):
                    continue
                a_ = int(np.nanargmin(np.where(np.isfinite(cand), cand, np.inf)))
                b_ = lo_b + a_
                cur[j] = cand[a_]
                cur_idx[j] = prev_idx[b_] + [b_]
            if not np.isfinite(cur[T - 1]):
                break
            out[mb] = {"ssr": float(cur[T - 1]), "breaks": list(cur_idx[T - 1])}
            prev, prev_idx = cur, cur_idx
        sel = {}
        for mb, r in out.items():
            k = mb + 1
            sig2 = max(r["ssr"] / T, 1e-300)
            sel[mb] = (T * math.log(sig2) + k * math.log(T),
                       math.log(sig2) + (k * 0.299 / T) * (math.log(T)) ** 2.1)
        m_bic = int(min(sel, key=lambda z: sel[z][0]))
        m_lwz = int(min(sel, key=lambda z: sel[z][1]))
        supf = {}
        for mb in range(0, max(out.keys())):
            if mb + 1 not in out:
                break
            s0, s1 = out[mb]["ssr"], out[mb + 1]["ssr"]
            supf[mb + 1] = float((s0 - s1) / (s1 / (T - (mb + 2))))
        return out, m_bic, m_lwz, supf

    def bp_report(dates, y, label, m_max=5):
        res, mb, ml, sf = bai_perron(y, m_max=m_max)
        brks = res.get(mb, {"breaks": []})["breaks"]
        return {"series": label, "n_observations": int(len(y)), "trimming": 0.15,
                "max_breaks": m_max, "n_breaks_bic": mb, "n_breaks_lwz": ml,
                "break_dates_bic": [str(pd.Timestamp(dates[b]).date()) for b in brks],
                "all_break_dates_by_m": {
                    str(k_): [str(pd.Timestamp(dates[b]).date()) for b in v["breaks"]]
                    for k_, v in res.items() if k_ > 0},
                "sequential_supF": {str(k_): round(float(v), 4) for k_, v in sf.items()},
                "ssr_by_m": {str(k_): round(float(v["ssr"]), 6) for k_, v in res.items()},
                "break_ci_90": None,
                "note": "Break-date confidence intervals are not reported: the Bai-Perron "
                        "interval requires a HAC break-fraction asymptotic that is not "
                        "implemented here."}

    rb = ROLL[(ROLL.date_et >= "2021-01-01") & (ROLL.date_et <= "2025-12-31")]
    bbeta = rb[["date_et", "beta30d_BTC_SPY"]].dropna()
    bp_beta = bp_report(bbeta.date_et.to_numpy(), bbeta.beta30d_BTC_SPY.to_numpy(),
                        "beta30d_BTC_SPY")
    ctrl_cols = [f"rho30d_{a}_SPY" for a in CONTROLS if f"rho30d_{a}_SPY" in rb.columns]
    dfm = rb[["date_et", "rho30d_BTC_SPY"] + ctrl_cols].dropna()
    z_btc = np.arctanh(dfm.rho30d_BTC_SPY.clip(-0.999, 0.999))
    z_ctl = np.arctanh(dfm[ctrl_cols].clip(-0.999, 0.999)).mean(axis=1)
    diff_series = (z_btc - z_ctl).to_numpy()
    bp_diff = bp_report(dfm.date_et.to_numpy(), diff_series,
                        "fisherz_rho30d_BTC_minus_control_mean")

    def lrv(x, L):
        """Newey-West long-run variance of the sample mean."""
        e = np.asarray(x, float) - np.mean(x)
        n = len(e)
        s = float(e @ e) / n
        for lg in range(1, min(L, n - 1) + 1):
            s += 2.0 * (1.0 - lg / (L + 1.0)) * float(e[lg:] @ e[:-lg]) / n
        return max(s, 1e-16)

    # The 30-day windows overlap on 29 of 30 days, so an iid sup-Wald is badly
    # oversized. Both the iid and the L=60 HAC versions are reported.
    T = len(diff_series)
    lo_i, hi_i = int(0.15 * T), int(0.85 * T)
    NW_L = 60
    best_w, best_b = -np.inf, lo_i
    best_wh, best_bh = -np.inf, lo_i
    for b in range(lo_i, hi_i):
        g1, g2 = diff_series[:b], diff_series[b:]
        n1, n2 = len(g1), len(g2)
        dm = g1.mean() - g2.mean()
        s2 = (((g1 - g1.mean()) ** 2).sum() + ((g2 - g2.mean()) ** 2).sum()) / (T - 2)
        wst = dm ** 2 / (s2 * (1.0 / n1 + 1.0 / n2))
        if wst > best_w:
            best_w, best_b = wst, b
        wh = dm ** 2 / (lrv(g1, NW_L) / n1 + lrv(g2, NW_L) / n2)
        if wh > best_wh:
            best_wh, best_bh = wh, b

    RESULTS["bai_perron"] = {
        "specification": "Bai-Perron multiple structural break tests (15% trimming, up to "
                         "5 breaks, BIC and LWZ selection, sequential supF(l+1|l)) on "
                         "Bitcoin's 30-day rolling beta and on the BTC-minus-control-mean "
                         "differential Fisher-z series. Every estimated break date is "
                         "reported whether or not it supports the hypothesis.",
        "unit_of_analysis": "day", "outcome": "rolling_beta_and_differential_fisherz",
        "treatment": "endogenous_break_date", "n_observations": int(T),
        "n_clusters": None, "cluster_level": "none", "fixed_effects": [], "controls": [],
        "n_pre_treatment": int((dfm.date_et < TREAT_DATE).sum()),
        "n_post_treatment": int((dfm.date_et >= TREAT_DATE).sum()),
        "coefficients": {},
        "btc_rolling_beta": bp_beta, "differential_fisherz": bp_diff,
        "andrews_sup_wald": float(best_w),
        "andrews_break_date": str(pd.Timestamp(dfm.date_et.to_numpy()[best_b]).date()),
        "andrews_sup_wald_hac": float(best_wh),
        "andrews_break_date_hac": str(pd.Timestamp(dfm.date_et.to_numpy()[best_bh]).date()),
        "andrews_hac_lags": NW_L,
        "andrews_p_value": None,
        "andrews_note": "The sup-Wald null distribution is non-standard (Andrews 1993), so "
                        "no p-value is computed; the 5% asymptotic critical value for a "
                        "one-parameter mean break with 15% trimming is approximately 8.85. "
                        "The iid version is badly oversized because the 30-day rolling "
                        "windows overlap on 29 of 30 days; the Newey-West version "
                        "(L = 60) is the one to read.",
        "diagnostics": {"n_fixed_effect_groups": 0, "df_residual": int(T - 2)},
    }
    print(f"    BP breaks, differential : {bp_diff['break_dates_bic']}", flush=True)
    print(f"    BP breaks, rolling beta : {bp_beta['break_dates_bic']}", flush=True)
    print(f"    Andrews supW iid = {best_w:.2f}; HAC(60) = {best_wh:.2f} "
          f"(5% cv ~ 8.85)", flush=True)

    bp_rows = [{"series": s["series"], "selection": "BIC", "n_breaks": s["n_breaks_bic"],
                "break_dates": "; ".join(s["break_dates_bic"])}
               for s in (bp_diff, bp_beta)]
    bp_rows += [{"series": s["series"], "selection": "LWZ", "n_breaks": s["n_breaks_lwz"],
                 "break_dates": "; ".join(
                     s["all_break_dates_by_m"].get(str(s["n_breaks_lwz"]), []))}
                for s in (bp_diff, bp_beta)]
    bp_rows += [{"series": "andrews_sup_wald (iid)", "selection": "sup-Wald",
                 "n_breaks": 1, "break_dates":
                     f"{RESULTS['bai_perron']['andrews_break_date']} "
                     f"(W = {best_w:.2f})"},
                {"series": "andrews_sup_wald (HAC L=60)", "selection": "sup-Wald",
                 "n_breaks": 1, "break_dates":
                     f"{RESULTS['bai_perron']['andrews_break_date_hac']} "
                     f"(W = {best_wh:.2f})"}]
    write_table(pd.DataFrame(bp_rows), "table8c_break_dating.csv",
                "Section 6.5 / complementary table", "Endogenous break dates. Nothing is "
                "dated at the January 2024 approval.")
    return ctx


# =============================================================================
# 4f. DCC-GARCH(1,1) WITH A POST DUMMY IN THE CORRELATION TARGET (Table 8)
#
#   q12_t = (1 - a - b)(qbar + phi * Post_t) + a u1_{t-1} u2_{t-1} + b q12_{t-1}
#
# Fitted for BTC-SPY and for every control-coin-SPY pair; the cross-sectional
# distribution of phi over the control pairs is the randomization distribution.
# Second-stage SEs ignore first-stage GARCH estimation error, so the
# control-pair distribution, not the QML SE, is the inference channel.
# =============================================================================
def section_dcc(ctx):
    print("=== 4f. DCC-GARCH (slow; --skip-dcc to omit) ===", flush=True)

    def garch11(r):
        r = np.asarray(r, float)
        r = r - r.mean()
        v = float(r.var())
        n = len(r)

        def nll(p):
            om = math.exp(p[0])
            al = 1 / (1 + math.exp(-p[1]))
            be = 1 / (1 + math.exp(-p[2]))
            if al + be >= 0.9995:
                return 1e10
            h, tot = v, 0.0
            for t in range(n):
                if t > 0:
                    h = om + al * r[t - 1] ** 2 + be * h
                if h <= 1e-16:
                    return 1e10
                tot += math.log(h) + r[t] ** 2 / h
            return 0.5 * tot

        x0 = np.array([math.log(max(v * 0.05, 1e-12)), math.log(0.08 / 0.92),
                       math.log(0.90 / 0.10)])
        xo, _, ok = nelder_mead(nll, x0, maxiter=1200, step=0.3)
        om = math.exp(xo[0])
        al = 1 / (1 + math.exp(-xo[1]))
        be = 1 / (1 + math.exp(-xo[2]))
        h = np.empty(n)
        h[0] = v
        for t in range(1, n):
            h[t] = om + al * r[t - 1] ** 2 + be * h[t - 1]
        return r / np.sqrt(h), {"omega": float(om), "alpha": float(al),
                                "beta": float(be), "converged": bool(ok)}

    def dcc_post(u1, u2, post):
        u1 = np.asarray(u1, float) / np.std(u1)
        u2 = np.asarray(u2, float) / np.std(u2)
        qb = float(np.corrcoef(u1, u2)[0, 1])
        n = len(u1)
        pv = np.asarray(post, float)

        def nll(p):
            a = 1 / (1 + math.exp(-p[0]))
            b = 1 / (1 + math.exp(-p[1]))
            if a + b >= 0.9995:
                return 1e10
            phi = p[2]
            q11 = q22 = 1.0
            q12 = qb
            tot = 0.0
            for t in range(n):
                if t > 0:
                    tg = qb + phi * pv[t]
                    q11 = (1 - a - b) * 1.0 + a * u1[t - 1] ** 2 + b * q11
                    q22 = (1 - a - b) * 1.0 + a * u2[t - 1] ** 2 + b * q22
                    q12 = (1 - a - b) * tg + a * u1[t - 1] * u2[t - 1] + b * q12
                else:
                    q12 = qb + phi * pv[t]
                den = math.sqrt(max(q11, 1e-12) * max(q22, 1e-12))
                rho = max(-0.9995, min(0.9995, q12 / den))
                det = 1.0 - rho * rho
                quad = (u1[t] ** 2 + u2[t] ** 2 - 2 * rho * u1[t] * u2[t]) / det
                tot += math.log(det) + quad - u1[t] ** 2 - u2[t] ** 2
            return 0.5 * tot

        x0 = np.array([math.log(0.05 / 0.95), math.log(0.90 / 0.10), 0.0])
        xo, f0, ok = nelder_mead(nll, x0, maxiter=1200, step=0.3)
        a = 1 / (1 + math.exp(-xo[0]))
        b = 1 / (1 + math.exp(-xo[1]))
        phi = float(xo[2])
        eps = max(1e-3, abs(phi) * 5e-2)
        hess = (nll(xo + np.array([0, 0, eps])) - 2 * f0
                + nll(xo - np.array([0, 0, eps]))) / eps ** 2
        se = float(math.sqrt(1.0 / hess)) if hess > 1e-12 else None
        return {"a": float(a), "b": float(b), "phi": phi, "se_phi": se,
                "loglik": float(-f0), "converged": bool(ok), "qbar": qb}

    # The DCC uses the uninterrupted daily series (no donut): the recursion
    # needs a continuous sample.
    dgs = DAILY[(DAILY.date_et >= "2021-01-01") & (DAILY.date_et <= "2025-12-31")].copy()
    dgs["post"] = (dgs.date_et >= TREAT_DATE).astype(int)
    cols = ["date_et", "post", "r_SPY"] + [f"r_{a}" for a in HEADLINE
                                           if f"r_{a}" in dgs.columns]
    dgs = dgs[cols].dropna()
    u_spy, g_spy = garch11(dgs.r_SPY.to_numpy())
    u_btc, g_btc = garch11(dgs.r_BTC.to_numpy())
    postv = dgs.post.to_numpy(float)
    dcc = dcc_post(u_btc, u_spy, postv)
    phi, se_phi = dcc["phi"], dcc["se_phi"]
    t_phi = (phi / se_phi) if se_phi else None
    p_phi = (2 * norm_sf(abs(t_phi))) if t_phi is not None else None

    ctrl_phi = {}
    for a in CONTROLS:
        if f"r_{a}" not in dgs.columns:
            continue
        try:
            ua, _ = garch11(dgs[f"r_{a}"].to_numpy())
            ctrl_phi[a] = float(dcc_post(ua, u_spy, postv)["phi"])
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] DCC failed for {a}: {exc}", flush=True)
    vals = list(ctrl_phi.values())
    p_phi_ri = (float((np.sum(np.abs(vals) >= abs(phi)) + 1) / (len(vals) + 1))
                if vals else None)

    RESULTS["dcc_garch_btc_spy"] = {
        "specification": "DCC-GARCH(1,1) on the BTC-SPY pair, two-stage QML, with a "
                         "post-treatment dummy shifting the off-diagonal long-run "
                         "correlation target. The same model is fitted to every "
                         "control-coin-SPY pair, and that cross-sectional distribution of "
                         "phi is the placebo distribution for Bitcoin's.",
        "unit_of_analysis": "day", "outcome": "conditional_correlation_btc_spy",
        "treatment": "post_etf", "n_observations": int(len(dgs)), "n_clusters": None,
        "cluster_level": "none", "fixed_effects": [], "controls": [],
        "n_pre_treatment": int((dgs.post == 0).sum()),
        "n_post_treatment": int((dgs.post == 1).sum()),
        "coefficients": {
            "phi_post": {"estimate": phi, "se": se_phi, "t_stat": t_phi, "p_value": p_phi,
                         "ci_lower": (phi - 1.96 * se_phi) if se_phi else None,
                         "ci_upper": (phi + 1.96 * se_phi) if se_phi else None},
            "dcc_a": {"estimate": dcc["a"], "se": None, "t_stat": None, "p_value": None},
            "dcc_b": {"estimate": dcc["b"], "se": None, "t_stat": None, "p_value": None},
        },
        "p_value_ri_across_control_pairs": p_phi_ri,
        "control_pair_phi": ctrl_phi,
        "unconditional_corr_btc_spy": dcc["qbar"],
        "diagnostics": {"loglik": dcc["loglik"], "converged": dcc["converged"],
                        "dcc_a_plus_b": float(dcc["a"] + dcc["b"]),
                        "garch_btc_alpha": g_btc["alpha"], "garch_btc_beta": g_btc["beta"],
                        "garch_spy_alpha": g_spy["alpha"], "garch_spy_beta": g_spy["beta"],
                        "n_fixed_effect_groups": 0, "df_residual": int(len(dgs) - 3),
                        "note": "Second-stage standard errors ignore first-stage GARCH "
                                "estimation error; the control-pair placebo distribution "
                                "is the reliable inference channel."},
    }
    print(f"    phi = {phi:+.5f} (se {se_phi})  p_RI across control pairs = {p_phi_ri}",
          flush=True)
    # Table 8 in the paper: "DCC-GARCH ..." (tab:dcc)
    write_table(coef_frame(RESULTS["dcc_garch_btc_spy"], "DCC-GARCH BTC-SPY"),
                "table8_dcc.csv", "Table 8 (tab:dcc)",
                "Post-listing shift in the BTC-SPY long-run correlation target.")
    write_table(pd.DataFrame([{"pair": f"{a}-SPY", "phi": v} for a, v in ctrl_phi.items()]
                             + [{"pair": "BTC-SPY", "phi": phi}]),
                "table8b_dcc_control_pairs.csv", "Table 8 panel B (tab:dcc)",
                "phi for every control-coin-SPY pair: the randomization distribution. "
                "Every control pair is also positive.")
    return ctx


# =============================================================================
# 4g. BDM COLLAPSE AND POWER / MDE  (paper Table 10)
# =============================================================================
def section_power(ctx):
    print("=== 4g. BDM collapse and power analysis ===", flush=True)
    smp, m = ctx["smp"], ctx["m"]
    tau, se_cl = ctx["tau"], ctx["se_cl"]
    sd_ri, sd_ct = ctx["sd_ri"], ctx["sd_ct"]
    rho_pre, n_pre, n_post = ctx["rho_pre"], ctx["n_pre"], ctx["n_post"]

    # Bertrand-Duflo-Mullainathan: two periods per coin removes serial
    # correlation in eps_im by construction.
    col = smp.copy()
    col["per"] = np.where(col.year_month >= TREAT_MONTH, "post", "pre")
    cm = col.groupby(["asset_id", "per"], as_index=False).y_fisherz_corr_equity.mean()
    cm["d_etf_listed"] = ((cm.asset_id == "BTC") & (cm.per == "post")).astype(int)
    bdm = feols(cm, "y_fisherz_corr_equity", ["d_etf_listed"],
                fes=["asset_id", "per"], cluster="asset_id")
    RESULTS["bdm_collapsed"] = spec_entry(
        bdm,
        "Bertrand-Duflo-Mullainathan collapse: the panel is reduced to one pre-mean and "
        "one post-mean per coin and the DiD re-estimated, which removes serial correlation "
        "in the idiosyncratic error by construction.",
        fes=["coin", "period"], controls=[], cluster_level="coin",
        extra={"unit_of_analysis": "coin-period", "outcome": "y_fisherz_corr_equity",
               "treatment": "d_etf_listed", "treated_units": 1,
               "n_pre_treatment": int(cm.asset_id.nunique()),
               "n_post_treatment": int(cm.asset_id.nunique())})
    RESULTS["bdm_collapsed"]["diagnostics"]["n_fixed_effect_groups"] = int(
        cm.asset_id.nunique() + 1)

    # MDE = (z_0.975 + z_0.80) * se, computed from three reference
    # distributions. The randomization one is the honest number under a single
    # treated unit; the cluster-robust one is reported only for comparability.
    mde_cl, mde_ri, mde_ct = MDE_MULT * se_cl, MDE_MULT * sd_ri, MDE_MULT * sd_ct
    conv = 1 - rho_pre ** 2          # d(rho)/d(z) at the pre-period mean correlation
    RESULTS["power_analysis"] = {
        "specification": "Minimum detectable effect for the primary specification at "
                         "alpha = 0.05 two-sided and 80% power: MDE = 2.80158 * se, from "
                         "three reference distributions. Pre-specified in "
                         "econometric_spec.md section 9 before estimation.",
        "unit_of_analysis": "coin-month", "outcome": "y_fisherz_corr_equity",
        "treatment": "d_etf_listed", "n_observations": int(m["n"]),
        "n_clusters": int(smp.asset_id.nunique()), "cluster_level": "coin",
        "fixed_effects": ["coin", "year_month"], "controls": [],
        "n_pre_treatment": n_pre, "n_post_treatment": n_post,
        "coefficients": {
            "mde_fisherz_ri": {"estimate": float(mde_ri), "se": None, "t_stat": None,
                               "p_value": None},
            "mde_fisherz_cluster": {"estimate": float(mde_cl), "se": None, "t_stat": None,
                                    "p_value": None},
            "mde_fisherz_conley_taber": {"estimate": float(mde_ct), "se": None,
                                         "t_stat": None, "p_value": None},
        },
        "alpha": 0.05, "power": 0.80, "mde_multiplier": MDE_MULT,
        "se_cluster": float(se_cl), "sd_randomization": sd_ri, "sd_conley_taber": sd_ct,
        "mde_correlation_units_ri": float(mde_ri * conv),
        "mde_correlation_units_cluster": float(mde_cl * conv),
        "mde_correlation_units_conley_taber": float(mde_ct * conv),
        "rho_pre_treatment_mean": rho_pre, "point_estimate": tau,
        "correlation_conversion_factor": float(conv),
        "ci95_lower_fisherz": m["coefficients"]["d_etf_listed"]["ci_lower"],
        "ci95_upper_fisherz": m["coefficients"]["d_etf_listed"]["ci_upper"],
        "ci95_upper_correlation_units": float(
            m["coefficients"]["d_etf_listed"]["ci_upper"] * conv),
        "ri_ci95_lower_fisherz": float(tau - Z95 * sd_ri),
        "ri_ci95_upper_fisherz": float(tau + Z95 * sd_ri),
        "ri_ci95_lower_correlation_units": float((tau - Z95 * sd_ri) * conv),
        "ri_ci95_upper_correlation_units": float((tau + Z95 * sd_ri) * conv),
        "conley_taber_ci_lower_correlation_units": float(ctx["ct_lo"] * conv),
        "conley_taber_ci_upper_correlation_units": float(ctx["ct_hi"] * conv),
        "prespecified_null_threshold_fisherz": 0.10,
        "prespecified_mde_bar_correlation_units": 0.10,
        "prespecified_bar_met": bool(float(mde_ri * conv) <= 0.10),
        "verdict": ("The randomization-based MDE in correlation units is "
                    f"{mde_ri * conv:.3f}. Section 9.2 of econometric_spec.md pre-committed "
                    "to licensing a null claim only if this was at or below 0.10 and to "
                    "making no null claim if it exceeded 0.20. The realized value falls "
                    "between the two bars, so the paper reports a null on every "
                    "pre-specified dimension while stating that effects below roughly 0.15 "
                    "in correlation units could not have been detected with 80% power. The "
                    "randomization 95% interval separately excludes increases above "
                    f"{(tau + Z95 * sd_ri) * conv:.3f} in correlation units."),
        "diagnostics": {"n_fixed_effect_groups": 0, "df_residual": int(m["df_residual"])},
    }
    print(f"    MDE: RI {mde_ri:.4f} ({mde_ri * conv:.4f} in rho), "
          f"Conley-Taber {mde_ct:.4f}, cluster {mde_cl:.4f} (invalid)", flush=True)

    pw = pd.DataFrame([
        {"reference_distribution": "randomization grid", "sd": sd_ri,
         "mde_fisherz": mde_ri, "mde_correlation_units": mde_ri * conv, "valid": True},
        {"reference_distribution": "Conley-Taber", "sd": sd_ct,
         "mde_fisherz": mde_ct, "mde_correlation_units": mde_ct * conv, "valid": True},
        {"reference_distribution": "cluster-robust", "sd": se_cl,
         "mde_fisherz": mde_cl, "mde_correlation_units": mde_cl * conv, "valid": False},
    ])
    # Table 10 in the paper: "Minimum detectable effect" (tab:power)
    write_table(pw, "table10_power_mde.csv", "Table 10 (tab:power)",
                "Minimum detectable effect from three reference distributions; only the "
                "two randomization-based rows are valid with one treated unit.")
    write_table(stat_frame(RESULTS["power_analysis"],
                           ["point_estimate", "rho_pre_treatment_mean",
                            "correlation_conversion_factor",
                            "ri_ci95_lower_correlation_units",
                            "ri_ci95_upper_correlation_units",
                            "conley_taber_ci_lower_correlation_units",
                            "conley_taber_ci_upper_correlation_units",
                            "prespecified_bar_met"]),
                "table10b_power_intervals.csv", "Table 10 panel B (tab:power)",
                "Intervals translated into correlation units and the pre-specified bar.")
    return ctx


# =============================================================================
# 5. ROBUSTNESS CHECKS  (paper Tables 9, 11, 12, 13, 14)
#
# Every row re-estimates the headline equation on a perturbed sample, outcome
# or specification, and recomputes its OWN placebo-in-space randomization
# p-value on its OWN sample rather than copying the headline's.
# =============================================================================
def rob(key, name, d, ycol="y_fisherz_corr_equity", xcols=("d_etf_listed",),
        cluster="asset_id", cluster2=None, controls=(), treated="BTC"):
    xcols = list(xcols)
    r = feols(d, ycol, xcols, fes=["asset_id", "year_month"],
              cluster=cluster, cluster2=cluster2)
    est = float(r["beta"][0])
    post_months = set(d.loc[d[xcols[0]] == 1, "year_month"])
    donors = [a for a in d.asset_id.unique() if a != treated]
    pl = []
    for c in donors:
        d2 = d.copy()
        d2[xcols[0]] = ((d2.asset_id == c) & (d2.year_month.isin(post_months))).astype(int)
        try:
            pl.append(float(feols(d2, ycol, xcols,
                                  fes=["asset_id", "year_month"])["beta"][0]))
        except Exception:  # noqa: BLE001
            pass
    p_sp = (float((np.sum(np.abs(pl) >= abs(est)) + 1) / (len(pl) + 1)) if pl else None)
    ent = spec_entry(r, name, fes=["coin", "year_month"], controls=list(controls),
                     cluster_level="coin_and_month" if cluster2 else "coin",
                     extra={"unit_of_analysis": "coin-month", "outcome": ycol,
                            "treatment": xcols[0], "treated_units": 1,
                            "n_pre_treatment": int(((d.asset_id == treated)
                                                    & (d[xcols[0]] == 0)).sum()),
                            "n_post_treatment": int((d[xcols[0]] == 1).sum()),
                            "p_value_ri_space": p_sp,
                            "n_placebo_assignments": len(pl),
                            "ri_sd": (float(np.std(pl, ddof=1)) if len(pl) > 1 else None)},
                     diag_extra={"n_coin_fe": int(d.asset_id.nunique()),
                                 "n_month_fe": int(d.year_month.nunique())})
    ent["diagnostics"]["n_fixed_effect_groups"] = int(d.asset_id.nunique()
                                                      + d.year_month.nunique() - 1)
    ROBUST[key] = ent
    print(f"    {key:<26s} {est:+.5f}  (se {r['coefficients'][xcols[0]]['se']:.5f})  "
          f"N = {r['n']:<6d} p_RI = {p_sp}", flush=True)
    return r


def section_robustness(ctx):
    print("=== 5. robustness and placebo grid ===", flush=True)
    smp, tau = ctx["smp"], ctx["tau"]
    m, se_cl = ctx["m"], ctx["se_cl"]
    grid, sd_ri = ctx["grid"], ctx["sd_ri"]
    n_pre, n_post = ctx["n_pre"], ctx["n_post"]

    # Diagnostic: does the delivered outcome match one rebuilt from daily data?
    sanity = build_monthly(DAILY, ["BTC"])
    chk = sanity.merge(PANEL[(PANEL.asset_id == "BTC") & (PANEL.market_leg == "SPY")],
                       on="year_month", suffixes=("_new", "_old"))
    sanity_corr = float(chk.y_fisherz_corr_equity_new.corr(chk.y_fisherz_corr_equity_old))
    print(f"    sanity: corr(rebuilt, delivered) = {sanity_corr:.4f} over {len(chk)} months",
          flush=True)

    # ── R2: 24h-UTC alignment, rebuilt from the raw price files ──────────────
    frames = []
    for a in HEADLINE:
        p = DATA_DIR / f"px_{a}_USD.csv"
        if not p.exists():
            continue
        px = pd.read_csv(p)
        try:
            px["d"] = pd.to_datetime(px["date"], utc=True, format="ISO8601").dt.tz_localize(None)
        except (TypeError, ValueError):
            px["d"] = pd.to_datetime(px["date"], utc=True).dt.tz_localize(None)
        px = px.sort_values("d")
        px[f"r_{a}"] = np.log(px["close"]).diff()
        frames.append(px[["d", f"r_{a}"]].dropna().set_index("d"))
    if frames:
        utc = pd.concat(frames, axis=1).reset_index().rename(columns={"d": "date_et"})
        utc["date_et"] = utc.date_et.dt.normalize()
        utc = utc.merge(DAILY[["date_et", "r_SPY"]], on="date_et", how="inner")
        mu = add_treat(build_monthly(utc, HEADLINE)
                       .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
        r_utc = rob("utc_alignment",
                    "24h-UTC return alignment: crypto returns rebuilt as 00:00-00:00 UTC "
                    "log close-to-close from the raw price files. NOTE: the delivered "
                    "daily_returns.csv crypto series are already on the UTC clock, so this "
                    "row reproduces `main` rather than testing against it. The "
                    "equity-close (16:00-16:00 ET) clock is not constructible from the "
                    "delivered data.", mu)
        ROBUST["utc_alignment"]["reproduces_main_exactly"] = bool(
            abs(float(r_utc["beta"][0]) - tau) < 1e-8)
    else:
        print("    [skip] utc_alignment: px_{ASSET}_USD.csv files not found", flush=True)

    # ── R2b: off-day-span alignment ──────────────────────────────────────────
    off_path = DATA_DIR / "crypto_offday_returns.csv"
    if off_path.exists():
        off = pd.read_csv(off_path, parse_dates=["date_utc"])
        eq_dates = np.sort(DAILY.date_et.unique())
        pos = np.searchsorted(eq_dates, off.date_utc.to_numpy(), side="left")
        off = off.assign(_p=pos)
        off = off[off._p < len(eq_dates)]
        off["map_date"] = eq_dates[off._p.to_numpy()]
        addm = off.groupby(["map_date", "asset_id"], as_index=False).r_utc.sum()
        wide = addm.pivot(index="map_date", columns="asset_id", values="r_utc")
        span = DAILY[["date_et", "r_SPY"] + [f"r_{a}" for a in HEADLINE
                                             if f"r_{a}" in DAILY.columns]].copy()
        n_span_assets = 0
        for a in HEADLINE:
            if a in wide.columns and f"r_{a}" in span.columns:
                span[f"r_{a}"] = span[f"r_{a}"] + span.date_et.map(wide[a]).fillna(0.0)
                n_span_assets += 1
        ms = add_treat(build_monthly(span, HEADLINE)
                       .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
        rob("alignment_offday_span",
            "Off-day-span alignment: weekend and holiday crypto returns are cumulated into "
            "the next equity session, so each crypto return spans exactly the same calendar "
            "interval as the equity return it is correlated with. Applied to "
            f"{n_span_assets} of {len(HEADLINE)} sample assets.", ms)
    else:
        print("    [skip] alignment_offday_span: crypto_offday_returns.csv not found",
              flush=True)

    # ── R3: exclude the April 2024 halving window ────────────────────────────
    rob("excl_halving",
        "Excludes 2024m4-2024m5, the April 19-20 2024 Bitcoin halving window: the largest "
        "BTC-specific post-treatment shock the DiD cannot difference out.",
        smp[~smp.year_month.isin(["2024-04", "2024-05"])])

    # ── R4: VIX and MOVE interacted with the Bitcoin indicator ───────────────
    # Main effects are collinear with the month FE and absorbed; the
    # interactions let the macro regime load differentially on Bitcoin, which
    # is the version of the macro story month FE do not kill.
    mac = DAILY[["date_et", "lvl_VIX", "lvl_MOVE"]].copy()
    mac["year_month"] = mac.date_et.dt.strftime("%Y-%m")
    mmv = mac.groupby("year_month", as_index=False)[["lvl_VIX", "lvl_MOVE"]].mean()
    sv = smp.merge(mmv, on="year_month", how="left")
    sv["vix_x_btc"] = sv.lvl_VIX * sv.is_btc
    sv["move_x_btc"] = sv.lvl_MOVE * sv.is_btc
    rob("ctrl_vix_move",
        "Adds monthly VIX and MOVE levels interacted with the Bitcoin indicator, letting "
        "the macro regime load differentially on Bitcoin.",
        sv.dropna(subset=["vix_x_btc", "move_x_btc"]),
        xcols=("d_etf_listed", "vix_x_btc", "move_x_btc"),
        controls=("vix_x_btc", "move_x_btc"))

    # ── R5: the placebo grid, reported as its own row ────────────────────────
    ROBUST["placebo_dates_pre"] = {
        "specification": "Placebo treatment dates drawn from the pre-period (every month "
                         "2021m7-2023m1 for every coin including Bitcoin) combined with "
                         "placebo-in-space at the true date. This grid is the randomization "
                         "distribution from which the headline p-value is computed.",
        "unit_of_analysis": "coin-month", "outcome": "y_fisherz_corr_equity",
        "treatment": "placebo_d_etf_listed", "n_observations": int(m["n"]),
        "n_clusters": int(smp.asset_id.nunique()), "cluster_level": "coin",
        "fixed_effects": ["coin", "year_month"], "controls": [],
        "n_pre_treatment": n_pre, "n_post_treatment": n_post,
        "coefficients": {
            "placebo_mean": {"estimate": float(np.mean(grid)), "se": sd_ri,
                             "t_stat": None, "p_value": None},
            "placebo_abs_p90": {"estimate": float(np.percentile(np.abs(grid), 90)),
                                "se": None, "t_stat": None, "p_value": None},
            "actual_estimate": {"estimate": tau, "se": se_cl, "t_stat": None,
                                "p_value": ctx["p_ri"]},
        },
        "n_placebo_assignments": int(len(grid)),
        "n_placebo_space": int(len(ctx["placebo_space"])),
        "n_placebo_time": int(len(ctx["placebo_time"])),
        "share_abs_ge_actual": float(np.mean(np.abs(grid) >= abs(tau))),
        "p_value_ri": ctx["p_ri"],
        "diagnostics": {"placebo_sd": sd_ri,
                        "placebo_q025": float(np.percentile(grid, 2.5)),
                        "placebo_q975": float(np.percentile(grid, 97.5)),
                        "n_fixed_effect_groups": int(smp.asset_id.nunique()
                                                     + smp.year_month.nunique() - 1),
                        "df_residual": int(m["df_residual"])},
    }

    # ── R6: BITO futures-ETF placebo (2021-10-19 launch) ─────────────────────
    bito = add_treat(headline_sample(donut=False, start="2021-01", end="2023-07"),
                     month="2021-11")
    rob("placebo_bito_2021",
        "Placebo event: the 2021-10-19 launch of BITO, a US-listed futures-based Bitcoin "
        "ETF that did not change spot plumbing. Sample restricted to 2021m1-2023m7 so the "
        "2024 spot approval cannot contaminate it.", bito)

    # ── R7: drop extreme crypto-idiosyncratic news days ──────────────────────
    absr = DAILY.r_BTC.abs()
    cut = float(absr.quantile(0.99))
    bad = set(DAILY.loc[absr > cut, "date_et"]) | set(
        DAILY.loc[(DAILY.date_et >= "2022-11-06")
                  & (DAILY.date_et <= "2022-11-20"), "date_et"])
    mn = add_treat(build_monthly(DAILY, HEADLINE, exclude=bad)
                   .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
    rob("excl_extreme_news",
        f"Drops days with extreme crypto-idiosyncratic news: |r_BTC| above its 99th "
        f"percentile ({cut:.4f}) plus the 2022-11-06 to 2022-11-20 FTX-collapse window, "
        "with monthly outcomes rebuilt on the surviving days.", mn)

    # ── R8: no donut ─────────────────────────────────────────────────────────
    nd = headline_sample(donut=False)
    nd["d_etf_listed"] = ((nd.asset_id == "BTC") & (nd.year_month >= "2024-01")).astype(int)
    rob("no_donut",
        "No donut: treatment switched on at the 2024-01-11 listing (2024m1) with "
        "2023m8-2024m1 retained. Shows how much of the estimate the donut absorbs.", nd)

    # ── R9: excess-return market factor leg ──────────────────────────────────
    rob("leg_mkt", "Excess-return market factor leg instead of SPY.",
        add_treat(headline_sample(leg="MKT")))

    # ── R10: alternative outcomes (the beta decomposition) ───────────────────
    rob("outcome_beta",
        "Monthly equity beta instead of the Fisher-z correlation. beta = rho * "
        "(sigma_i/sigma_mkt), so it mixes the co-movement margin with the "
        "relative-volatility margin.", smp, ycol="beta_m")
    rob("outcome_ln_sigma_ratio",
        "Log relative volatility ln(sigma_i/sigma_mkt), the second factor in beta, which "
        "isolates the volatility margin from the correlation margin.",
        smp, ycol="ln_sigma_ratio_m")

    # ── R11: placebo assets (gold, silver) ───────────────────────────────────
    for key, asset in [("placebo_gold", "GLD"), ("placebo_silver", "SLV")]:
        pa_src = headline_sample(assets=[asset] + CONTROLS)
        if (pa_src.asset_id == asset).sum() == 0:
            print(f"    [skip] {key}: {asset} not in the panel", flush=True)
            continue
        rob(key,
            f"Placebo asset: {asset} assigned Bitcoin's treatment date against the "
            "never-treated crypto controls. Same macro regime, long-standing ETF, no 2024 "
            "access change -- a break here would falsify the design's macro-neutrality.",
            add_treat(pa_src, treated=asset), treated=asset)

    # ── R12: winsorized daily returns ────────────────────────────────────────
    mw = add_treat(build_monthly(DAILY, HEADLINE, winsor=True)
                   .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
    rob("winsorized",
        "Daily returns winsorized at the 0.5/99.5 within-asset percentiles before the "
        "monthly correlation is computed.", mw)

    # ── R13: extended estimation window ──────────────────────────────────────
    rob("sample_extended_2026",
        "Estimation window extended to 2026m7, the full delivered panel.",
        add_treat(headline_sample(end=PANEL_END_FULL)))

    # ── R14: two-way clustering ──────────────────────────────────────────────
    rob("twoway_cluster",
        "Primary specification with two-way clustering on coin and month. Subject to the "
        "same one-treated-unit objection as one-way clustering on coin.",
        smp, cluster2="year_month")

    # ── R15: sub-windows isolating the halving and the election ──────────────
    rob("subwindow_pre_halving",
        "Post window truncated at 2024m3, entirely before the April 2024 halving. Rests on "
        "two post-treatment months; not to be over-read.",
        add_treat(headline_sample(end="2024-03")))
    rob("subwindow_pre_election",
        "Post window truncated at 2024m10, before the November 2024 US election. This is "
        "the estimate to treat as ETF-attributable.",
        add_treat(headline_sample(end="2024-10")))
    rob("subwindow_post_election",
        "Post period restricted to 2024m11-2025m12, after the November 2024 US election.",
        add_treat(headline_sample().pipe(
            lambda x: x[(x.year_month < TREAT_MONTH) | (x.year_month >= "2024-11")]),
            month="2024-11"))

    # ── R16: non-US equity leg ───────────────────────────────────────────────
    if "r_ACWX" in DAILY.columns:
        acw = DAILY[["date_et", "r_ACWX"] + [f"r_{a}" for a in HEADLINE
                                             if f"r_{a}" in DAILY.columns]].dropna()
        ma = add_treat(build_monthly(acw, HEADLINE, mkt="r_ACWX")
                       .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
        rob("leg_acwx_non_us",
            "Non-US equity leg (ACWX, MSCI ACWI ex-US). If the mechanism is a US brokerage "
            "habitat, co-movement should rise more against US than non-US equities.", ma)

    ROBUST["sanity_rebuild_check"] = {
        "specification": "Diagnostic, not a specification: correlation between the "
                         "delivered coin_month_panel Fisher-z outcome for Bitcoin and the "
                         "same object rebuilt from daily_returns.csv inside this script.",
        "unit_of_analysis": "month", "outcome": "y_fisherz_corr_equity",
        "treatment": "none", "n_observations": int(len(chk)), "n_clusters": None,
        "cluster_level": "none", "fixed_effects": [], "controls": [],
        "n_pre_treatment": n_pre, "n_post_treatment": n_post,
        "coefficients": {"rebuild_correlation": {"estimate": sanity_corr, "se": None,
                                                 "t_stat": None, "p_value": None}},
        "diagnostics": {"n_fixed_effect_groups": 0, "df_residual": int(len(chk) - 1)},
    }

    # ---- Assemble the robustness tables -------------------------------------
    def rob_rows(keys):
        rows = []
        for k in keys:
            s = ROBUST.get(k)
            if not s:
                continue
            term = s["treatment"]
            c = s["coefficients"].get(term, {})
            rows.append({"key": k, "outcome": s["outcome"], "estimate": c.get("estimate"),
                         "se": c.get("se"), "p_value_clustered": c.get("p_value"),
                         "p_value_ri_space": s.get("p_value_ri_space"),
                         "n_observations": s["n_observations"],
                         "n_post_treatment": s.get("n_post_treatment"),
                         "description": s["specification"][:180]})
        return pd.DataFrame(rows)

    head = pd.DataFrame([{"key": "main (reference)", "outcome": "y_fisherz_corr_equity",
                          "estimate": tau, "se": se_cl,
                          "p_value_clustered": m["coefficients"]["d_etf_listed"]["p_value"],
                          "p_value_ri_space": ctx["p_ri_space"],
                          "n_observations": int(m["n"]), "n_post_treatment": n_post,
                          "description": "Headline TWFE DiD."}])

    # Table 11: sample-perturbation robustness
    sample_keys = ["excl_halving", "excl_extreme_news", "no_donut",
                   "sample_extended_2026", "subwindow_pre_halving",
                   "subwindow_pre_election", "subwindow_post_election", "winsorized"]
    write_table(pd.concat([head, rob_rows(sample_keys)], ignore_index=True),
                "table11_robustness_sample.csv", "Table 11 (tab:robustness_sample)",
                "Sample-perturbation robustness: halving, news days, donut, window, "
                "sub-windows, winsorizing.")

    # Table 12: specification robustness
    spec_keys = ["utc_alignment", "alignment_offday_span", "leg_mkt", "leg_acwx_non_us",
                 "twoway_cluster"]
    write_table(pd.concat([head, rob_rows(spec_keys)], ignore_index=True),
                "table12_robustness_spec.csv", "Table 12 (tab:robustness_spec)",
                "Specification robustness: return alignment, equity leg, clustering.")

    # Table 13: macro controls (the substantively important row)
    t13 = coef_frame(ROBUST["ctrl_vix_move"], "ctrl_vix_move") if "ctrl_vix_move" in ROBUST \
        else pd.DataFrame()
    write_table(pd.concat([t13, rob_rows(["ctrl_vix_move"])], ignore_index=False,
                          axis=0, sort=False),
                "table13_macro_controls.csv", "Table 13 (tab:macro_controls)",
                "VIX and MOVE interacted with the Bitcoin indicator. The sign of tau flips; "
                "the null does not.")

    # Table 14: placebos
    placebo_keys = ["placebo_gold", "placebo_silver", "placebo_bito_2021"]
    write_table(pd.concat([head, rob_rows(placebo_keys)], ignore_index=True),
                "table14_placebos.csv", "Table 14 (tab:placebos)",
                "Placebo assets and the BITO futures-ETF placebo event. Gold 'rejects' "
                "under clustering and does not under randomization inference.")

    # Table 9: the correlation-versus-beta decomposition
    decomp_keys = ["outcome_beta", "outcome_ln_sigma_ratio"]
    write_table(pd.concat([head, rob_rows(decomp_keys)], ignore_index=True),
                "table9_decomposition.csv", "Table 9 (tab:decomposition)",
                "beta = rho * (sigma_i/sigma_mkt): which margin moves. Correlation is flat; "
                "relative volatility falls.")

    write_table(rob_rows(sorted(ROBUST.keys())), "table_all_robustness_rows.csv",
                "All robustness rows", "Every robustness and placebo row in one frame.")
    return ctx


# =============================================================================
# 5b. COMPLEMENTARY SUMMARY TABLE (one row per estimator)
# =============================================================================
def section_complementary(ctx):
    print("=== 5b. complementary summary ===", flush=True)
    rows = []
    spec_map = [
        ("main", "d_etf_listed", "TWFE DiD, monthly Fisher-z (headline)"),
        ("daily_rolling_did", "d_etf_listed", "Daily 30d rolling-window panel DiD"),
        ("returns_ddd", "reqXpostXbtc", "Returns-level triple difference"),
        ("returns_interacted_BTC", "r_spy_x_post", "BTC returns-level equity loading (HAC)"),
        ("dcc_garch_btc_spy", "phi_post", "DCC-GARCH post shift in correlation target"),
        ("bdm_collapsed", "d_etf_listed", "BDM two-period collapse"),
    ]
    for key, term, label in spec_map:
        s = RESULTS.get(key)
        if not s:
            continue
        c = s["coefficients"].get(term, {})
        rows.append({"specification": label, "key": key, "term": term,
                     "estimate": c.get("estimate"), "se": c.get("se"),
                     "p_value": c.get("p_value"),
                     "p_value_randomization": (s.get("p_value_ri")
                                               or s.get("p_value_ri_across_control_coins")
                                               or s.get("p_value_ri_across_control_pairs")),
                     "n_observations": s.get("n_observations")})
    if "chow_test" in RESULTS:
        rows.append({"specification": "Chow test, HAC Wald at 2024-02-01",
                     "key": "chow_test", "term": "break_2024_02_01",
                     "estimate": RESULTS["chow_test"]["wald_hac_newey_west"], "se": None,
                     "p_value": RESULTS["chow_test"]["p_value_hac"],
                     "p_value_randomization": None,
                     "n_observations": RESULTS["chow_test"]["n_observations"]})
    if rows:
        write_table(pd.DataFrame(rows), "table_complementary.csv",
                    "Complementary table (tab:complementary)",
                    "Six methodologically distinct estimators side by side.")
    return ctx


# =============================================================================
# 6. FIGURES
# =============================================================================
def section_figures(ctx):
    print("=== 6. figures ===", flush=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"    [skip] matplotlib unavailable ({exc}); figures not produced", flush=True)
        return ctx

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def finish(fig, fname, paper_object, description):
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / fname, dpi=200)
        plt.close(fig)
        register(fname, paper_object, description)
        print(f"    -> output/{fname}   [{paper_object}]")

    approval = pd.Timestamp("2024-01-10")

    # Figure 1: BTC-SPY 30-day rolling correlation
    if ROLL is not None and not ROLL.empty and "rho30d_BTC_SPY" in ROLL.columns:
        s = ROLL[["date_et", "rho30d_BTC_SPY"]].dropna()
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(s.date_et, s.rho30d_BTC_SPY, lw=1.0, color="#1f3b73")
        ax.axhline(0, lw=0.6, color="0.6")
        ax.axvspan(pd.Timestamp(DONUT_START), pd.Timestamp(DONUT_END),
                   color="0.85", label="donut (2023m8-2024m1)")
        ax.axvline(approval, color="#b22222", lw=1.2, ls="--", label="SEC approval")
        ax.set_title("Bitcoin's 30-day rolling correlation with SPY")
        ax.set_ylabel(r"$\rho^{(30)}_t$")
        ax.legend(frameon=False, fontsize=8)
        finish(fig, "fig1_rolling_btc_spy.png", "Figure 1 (fig:rolling_btc_spy)",
               "30-day rolling BTC-SPY correlation with the donut and the approval marked.")

        # Figure 2: BTC against the never-treated control mean
        cc = [f"rho30d_{a}_SPY" for a in CONTROLS if f"rho30d_{a}_SPY" in ROLL.columns]
        if cc:
            d2 = ROLL[["date_et", "rho30d_BTC_SPY"] + cc].dropna()
            fig, ax = plt.subplots(figsize=(9, 4.5))
            for c in cc:
                ax.plot(d2.date_et, d2[c], lw=0.5, color="0.75")
            ax.plot(d2.date_et, d2[cc].mean(axis=1), lw=1.6, color="#2e7d32",
                    label="never-treated control mean")
            ax.plot(d2.date_et, d2.rho30d_BTC_SPY, lw=1.4, color="#1f3b73", label="Bitcoin")
            ax.axvspan(pd.Timestamp(DONUT_START), pd.Timestamp(DONUT_END), color="0.85")
            ax.axvline(approval, color="#b22222", lw=1.2, ls="--", label="SEC approval")
            ax.set_title("Bitcoin versus the never-listed control coins, 30-day correlation "
                         "with SPY")
            ax.set_ylabel(r"$\rho^{(30)}_t$")
            ax.legend(frameon=False, fontsize=8)
            finish(fig, "fig2_rolling_overlay_controls.png",
                   "Figure 2 (fig:rolling_overlay)",
                   "Bitcoin against the nine control coins; the 2024 move is crypto-wide.")

    # Figure 3: binned event study
    if "event_study" in RESULTS:
        co = RESULTS["event_study"]["coefficients"]
        pts = []
        for term, c in co.items():
            if not term.startswith("ev_"):
                continue
            pts.append((int(term[3:]), c["estimate"], c["se"]))
        pts.append((REF_BIN, 0.0, 0.0))
        pts.sort()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        es_ = [1.96 * (p[2] or 0.0) for p in pts]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.errorbar(xs, ys, yerr=es_, fmt="o", color="#1f3b73", capsize=3, lw=1.2)
        ax.axhline(0, color="0.4", lw=0.8)
        ax.axvline(-0.5, color="#b22222", lw=1.0, ls="--", label="listing")
        ax.set_xlabel(f"event time, {BIN}-month bins (reference bin {REF_BIN})")
        ax.set_ylabel("Fisher-z correlation, BTC relative to controls")
        ax.set_title("Event study: no level shift at the listing")
        ax.legend(frameon=False, fontsize=8)
        finish(fig, "fig3_event_study.png", "Figure 3 (event study)",
               "Binned event-study coefficients with 95% clustered intervals.")

    # Figure 4: the randomization distribution
    if "grid" in ctx:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.hist(ctx["grid"], bins=30, color="0.8", edgecolor="0.4")
        ax.axvline(ctx["tau"], color="#b22222", lw=1.8,
                   label=fr"$\hat\tau$ = {ctx['tau']:.4f} (p$^{{RI}}$ = {ctx['p_ri']:.3f})")
        ax.axvline(np.percentile(ctx["grid"], 2.5), color="#1f3b73", ls=":", lw=1.1)
        ax.axvline(np.percentile(ctx["grid"], 97.5), color="#1f3b73", ls=":", lw=1.1,
                   label="placebo 2.5 / 97.5 pct")
        ax.set_xlabel(r"placebo $\hat\tau$")
        ax.set_ylabel("count")
        ax.set_title("Randomization distribution over placebo assignments in space and time")
        ax.legend(frameon=False, fontsize=8)
        finish(fig, "fig4_randomization_distribution.png", "Figure 4 (RI density)",
               "The headline estimate sits near the middle of the placebo distribution.")

    # Figure 5: pre/post change in mean correlation, by asset
    bya = ctx.get("prepost_by_asset")
    if bya is not None and len(bya):
        w = bya.pivot(index="asset_id", columns="period", values="rho")
        if {"pre", "post"}.issubset(w.columns):
            w = w.dropna()
            w["change"] = w["post"] - w["pre"]
            w = w.sort_values("change")
            colors = ["#b22222" if i == "BTC" else "0.65" for i in w.index]
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.bar(w.index, w["change"], color=colors)
            ax.axhline(0, color="0.3", lw=0.8)
            ax.set_ylabel(r"change in mean $\rho$ with SPY")
            ax.set_title("Pre/post change in equity correlation, Bitcoin (red) and controls")
            finish(fig, "fig5_prepost_correlation_change.png",
                   "Figure 5 (fig:prepost_change)",
                   "Bitcoin's pre/post change is unexceptional against the control coins.")
    return ctx


# =============================================================================
# 7. EXPORT: JSON sidecars, the output map, the README and requirements.txt
# =============================================================================
README_TEMPLATE = """# Replication package

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec

This directory reproduces every quantitative result in the paper from the
researcher-supplied data. `estimation.py` is the single entry point; this file is
generated by that script, so it cannot drift away from what the code produces.

---

## 1. Data requirements

All inputs are CSV files supplied by the researcher and read from `../data/`
(override with `--data-dir`). **No data files are shipped in this package** — the
data stays with the researcher. No API key, database credential or network call
appears anywhere in `estimation.py`.

| File | Required for | Contents |
|---|---|---|
| `coin_month_panel.csv` | everything | The analysis panel: one row per (asset, month, equity leg), with the Fisher-z outcome `y_fisherz_corr_equity`, `rho_m`, `beta_m`, `ln_sigma_ratio_m`, `n_days_m`, cohort labels and the donut flag. |
| `daily_returns.csv` | returns-level, DCC, rebuilt-outcome robustness | Daily ET-dated returns per asset (`r_BTC` … `r_XLM`), equity legs (`r_SPY`, `r_ACWX`, `mktrf`) and macro levels (`lvl_VIX`, `lvl_MOVE`). Crypto legs are struck 00:00–00:00 UTC. |
| `rolling_diagnostics.csv` | daily rolling DiD, break tests | 30/60/90-day rolling correlations and betas, `rho{{w}}d_{{ASSET}}_{{LEG}}`. |
| `crypto_offday_returns.csv` | off-day-span alignment row | UTC returns on non-equity-session days. |
| `px_{{ASSET}}_USD.csv` | UTC-alignment row | Raw daily OHLCV per coin. |

**On `data_queries.sql` and the Allium tables.** `replication/data_queries.sql`
is present and contains only a generated header: none of the analysis data came
from a warehouse query, so there is no Allium table to re-run. The price and
return series were pulled from public market-data sources by the researcher and
delivered as the CSVs above; `../build_panel.py` documents how the coin-month
panel was constructed from them, and `../data_summary.md` records the three
material departures from the frozen `data_dictionary.json` specification — most
importantly that the headline is computed on the 00:00 UTC clock rather than the
16:00 ET clock, which is not constructible in the pre-period.

If an optional input is missing, the dependent row is skipped with a warning and
the rest of the script still completes.

## 2. Environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` (written by this script, pinned to the versions of the run):

```
{requirements}
```

scipy, statsmodels and linearmodels are **not** required. Every distribution
function, the fixed-effect absorption, the cluster-robust/HC/HAC covariance
estimators, the Nelder–Mead optimiser behind the DCC-GARCH and the
dynamic-programming Bai–Perron routine are implemented inside `estimation.py`,
so the published numbers do not depend on any third-party solver version.
matplotlib is optional: without it the tables are still produced and the figures
are skipped.

## 3. Steps

1. Place the researcher-supplied CSVs in `../data/` (or note their path).
2. `cd replication`
3. `python estimation.py --list-sections` to see the section map.
4. `python estimation.py` runs everything and writes to `output/`.
   Expected wall-clock: roughly one minute for everything except the DCC-GARCH,
   which is a pure-Python QML fit over ten asset pairs and dominates the total.
   Use `python estimation.py --skip-dcc` for a fast full pass.
5. Selective runs: `python estimation.py --sections main,robustness`. Sections
   declare their prerequisites and any missing one is run automatically, so
   `--sections power` works on its own and section 5 (robustness) does not
   require section 4c (returns-level models) to have been run first.
6. Compare `output/estimation_results.json` and `output/robustness_results.json`
   against the sidecars in the paper directory (`../estimation_results.json`,
   `../robustness_results.json`). These are the files every number in the
   manuscript traces to.

Reproducibility: `np.random.seed(42)` is set at import. The only stochastic
procedure is the wild cluster bootstrap, seeded separately with 20240110 (the
seed of the published run). Everything else — randomization inference,
Conley–Taber, Bai–Perron, the BDM collapse — enumerates its placebo grid
exhaustively and is deterministic.

Standard errors: heteroskedasticity-robust or cluster-robust throughout, and
Newey–West HAC for the returns-level and time-series specifications. **The
clustered column is reported for convention only.** With one treated cluster it
has no valid asymptotic justification and is about a third as wide as it should
be; the randomization p-value governs every claim in the paper
(`econometric_spec.md` §8).

## 4. Output map

Paper object → file in `replication/output/`:

{output_map}

## 5. Audit trail

* `replication/data_queries.sql` — header only; no warehouse query was used.
  Retained so the absence is recorded rather than implied.
* `replication/audit_log.csv` — header only, for the same reason: no query was
  submitted, approved or executed.
* `../build_panel.py` — how `coin_month_panel.csv` was built from the raw price
  and return files.
* `../data_summary.md` — the data-construction record, including the three
  material departures from `data_dictionary.json`.
* `../econometric_spec.md` — the pre-committed model set, the inference
  procedure and the pre-specified null (§9), all written before estimation.
* `../identification_strategy.md`, `../identification_spec.json` — the design
  and its machine-readable contract.
* `output/output_map.csv` — machine-readable version of the map above.

## 6. What is specified but not estimable on this build

Stated here because `econometric_spec.md` §15 commits to stating it rather than
substituting proxies: the full intraday session triple-difference (no intraday
data), the staggered Callaway–Sant'Anna multi-cohort extension (the delivered
panel flags only BTC as treated), the prior-halving placebo (the panel starts
2021m1), the false-news placebos (both dates fall inside the donut), the
Rambachan–Roth breakdown values (the variance estimate is not credible with one
treated unit — the randomization interval is reported in its place), and the
synthetic control (the placebo-in-space grid supplies the same inference
channel).
"""


def section_export(ctx):
    print("=== 7. export ===", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_DIR / "estimation_results.json", "w") as fh:
        json.dump(_clean(RESULTS), fh, indent=2)
    register("estimation_results.json", "Core sidecar",
             "Every core specification in the schema the paper's numbers are keyed to.")
    print("    -> output/estimation_results.json   [Core sidecar]")

    with open(OUTPUT_DIR / "robustness_results.json", "w") as fh:
        json.dump(_clean(ROBUST), fh, indent=2)
    register("robustness_results.json", "Robustness sidecar",
             "Every robustness and placebo row.")
    print("    -> output/robustness_results.json   [Robustness sidecar]")

    omap = pd.DataFrame(OUTPUT_MAP)
    omap.to_csv(OUTPUT_DIR / "output_map.csv", index=False)
    print("    -> output/output_map.csv")

    reqs = "\n".join([
        f"numpy=={np.__version__}",
        f"pandas=={pd.__version__}",
    ] + ([f"matplotlib=={__import__('matplotlib').__version__}"]
         if "matplotlib" in sys.modules else ["matplotlib>=3.7  # optional, figures only"]))
    (HERE / "requirements.txt").write_text(reqs + "\n")
    print("    -> requirements.txt")

    rows = "\n".join(f"| {r['paper_object']} | `output/{r['file']}` | {r['description']} |"
                     for r in OUTPUT_MAP)
    table = ("| Paper object | File | Contents |\n|---|---|---|\n" + rows) if rows else "_(none)_"
    (HERE / "README.md").write_text(
        README_TEMPLATE.format(requirements=reqs, output_map=table))
    print("    -> README.md")
    return ctx


# =============================================================================
# SECTION MAP AND CLI
# =============================================================================
SECTIONS = {
    "summary":       (section_summary, (), "Table 1-2: descriptives and the raw contrast"),
    "main":          (section_main, (), "Table 3-4: headline TWFE DiD and its inference"),
    "event":         (section_event, ("main",), "Table 5: event study and pre-trends"),
    "daily":         (section_daily, (), "Table 15: daily rolling-window DiD, 30/60/90d"),
    "returns":       (section_returns, (), "Table 6-7: returns-level models and Chow test"),
    "breaks":        (section_breaks, (), "Bai-Perron and Andrews sup-Wald"),
    "dcc":           (section_dcc, (), "Table 8: DCC-GARCH with a post dummy (slow)"),
    "power":         (section_power, ("main",), "Table 10: BDM collapse and the MDE"),
    "robustness":    (section_robustness, ("main",), "Tables 9, 11-14: robustness and placebos"),
    "complementary": (section_complementary, (), "Complementary table across estimators"),
    "figures":       (section_figures, (), "Figures 1-5 as PNG"),
    "export":        (section_export, (), "JSON sidecars, output map, README, requirements"),
}
DEFAULT_ORDER = ["summary", "main", "event", "daily", "returns", "breaks", "dcc",
                 "power", "robustness", "complementary", "figures", "export"]


def resolve(names):
    """Expand the requested sections with their prerequisites, preserving run order."""
    wanted = set()

    def add(n):
        if n in wanted:
            return
        for dep in SECTIONS[n][1]:
            add(dep)
        wanted.add(n)

    for n in names:
        if n not in SECTIONS:
            raise SystemExit(f"unknown section '{n}'; choose from {', '.join(DEFAULT_ORDER)}")
        add(n)
    return [n for n in DEFAULT_ORDER if n in wanted]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Replication script for 'No Cash Flows, New Owners: Spot Bitcoin "
                    "ETFs and the Origins of Co-movement'.")
    ap.add_argument("--sections", default=",".join(DEFAULT_ORDER),
                    help="comma-separated section names (prerequisites are added "
                         "automatically); default: all")
    ap.add_argument("--skip-dcc", action="store_true",
                    help="omit the DCC-GARCH section, which dominates runtime")
    ap.add_argument("--no-figures", action="store_true", help="skip the PNG figures")
    ap.add_argument("--data-dir", default=None,
                    help="directory holding the researcher-supplied CSVs "
                         "(default: ../data relative to this script)")
    ap.add_argument("--output-dir", default=None,
                    help="directory for tables and figures (default: ./output)")
    ap.add_argument("--list-sections", action="store_true",
                    help="print the section map and exit")
    args = ap.parse_args(argv)

    if args.list_sections:
        print("Sections (run in this order; prerequisites are added automatically):\n")
        for n in DEFAULT_ORDER:
            deps = SECTIONS[n][1]
            dep = f"  [requires: {', '.join(deps)}]" if deps else ""
            print(f"  {n:<14s} {SECTIONS[n][2]}{dep}")
        return 0

    global DATA_DIR, OUTPUT_DIR
    if args.data_dir:
        DATA_DIR = Path(args.data_dir).expanduser().resolve()
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir).expanduser().resolve()

    names = [s.strip() for s in args.sections.split(",") if s.strip()]
    if args.skip_dcc:
        names = [n for n in names if n != "dcc"]
    if args.no_figures:
        names = [n for n in names if n != "figures"]
    order = resolve(names)

    print("=" * 78)
    print("Replication: Spot Bitcoin ETFs and the origins of co-movement")
    print(f"  data   : {DATA_DIR}")
    print(f"  output : {OUTPUT_DIR}")
    print(f"  running: {', '.join(order)}")
    print("=" * 78, flush=True)

    load_data()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ctx: dict = {}
    for n in order:
        fn = SECTIONS[n][0]
        try:
            ctx = fn(ctx) or ctx
        except Exception as exc:  # noqa: BLE001
            # A failing section must not take the rest of the package down; the
            # failure is printed and the run continues so that `export` still
            # writes whatever was successfully estimated.
            print(f"    [ERROR] section '{n}' failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)

    print("=" * 78)
    print(f"done. {len(OUTPUT_MAP)} artefacts in {OUTPUT_DIR}")
    if "main" in RESULTS:
        c = RESULTS["main"]["coefficients"]["d_etf_listed"]
        print(f"  headline tau = {c['estimate']:+.4f}  "
              f"(cluster SE {c['se']:.4f}; randomization p = "
              f"{RESULTS['main']['p_value_ri']:.3f})")
        print("  The randomization p-value is the one the paper quotes; the clustered "
              "column is reported for convention only.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
