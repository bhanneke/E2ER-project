"""
run_estimation.py -- Spot Bitcoin ETF approval and BTC-US equity co-movement.

Implements the model set specified in econometric_spec.md.
Writes estimation_results.json (core) and robustness_results.json (robustness/placebo).

Primary (`main`): TWFE DiD on the coin-month panel, Fisher-z equity correlation,
coin + year-month fixed effects, no controls, clustered on coin, with randomization
inference as the primary inference procedure (one treated unit).

The runtime has numpy + pandas only, so the distribution functions and the optimiser
used for the DCC-GARCH are implemented here rather than imported.
"""

import json
import math
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

RNG = np.random.default_rng(20240110)

TREAT_MONTH = "2024-02"
DONUT = ["2023-08", "2023-09", "2023-10", "2023-11", "2023-12", "2024-01"]
SAMPLE_START, SAMPLE_END = "2021-01", "2025-12"
CONTROLS = ["LTC", "BNB", "ADA", "DOGE", "BCH", "LINK", "AVAX", "DOT", "XLM"]
HEADLINE = ["BTC"] + CONTROLS
Z95, Z80 = 1.959963985, 0.8416212336
MDE_MULT = Z95 + Z80  # 2.80158


# ==========================================================================
# distribution functions (numpy/pandas-only runtime)
# ==========================================================================
def _betacf(a, b, x):
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
    if t is None or not np.isfinite(t):
        return None
    df = max(float(df), 1.0)
    p = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return float(p if t > 0 else 1.0 - p)


_TPPF_CACHE = {}


def t_ppf(p, df):
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
    if x <= 0 or not np.isfinite(x):
        return 1.0
    a, xx = k / 2.0, x / 2.0
    return float(1.0 - _gser(a, xx) if xx < a + 1.0 else _gcf(a, xx))


def norm_sf(x):
    return float(0.5 * math.erfc(x / math.sqrt(2.0)))


def nelder_mead(f, x0, maxiter=1500, tol=1e-9, step=0.25):
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


# ==========================================================================
# estimation helpers
# ==========================================================================
def _demean(mat, groups, tol=1e-11, maxiter=500):
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
    """OLS with absorbed fixed effects and cluster-robust (or HC) inference."""
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
        meat = (Xd * (resid**2 * w)[:, None]).T @ Xd
        V = XtX_inv @ meat @ XtX_inv
        n_clusters, df_t = None, dof

    V = (V + V.T) / 2.0
    se = np.sqrt(np.clip(np.diag(V), 0.0, None))
    tss = float(((yd - yd.mean()) ** 2).sum())
    within_r2 = (1 - float((resid**2).sum()) / tss) if tss > 0 else None
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
    return max(1, int(np.floor(4 * (T / 100.0) ** (2.0 / 9.0))))


def ols_hac(y, X, names, L=None):
    y, X = np.asarray(y, float), np.asarray(X, float)
    n, k = X.shape
    L = nw_lags(n) if L is None else L
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    e = y - X @ beta
    S = (X * (e**2)[:, None]).T @ X
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
            "names": names, "r_squared": (1 - float((e**2).sum()) / tss) if tss > 0 else None}


def spec_entry(res, name, fes, controls, cluster_level, extra=None, diag_extra=None):
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


# ==========================================================================
# data
# ==========================================================================
print("=== loading ===", flush=True)
panel = pd.read_csv("data/coin_month_panel.csv")
daily = pd.read_csv("data/daily_returns.csv", parse_dates=["date_et"])
roll = pd.read_csv("data/rolling_diagnostics.csv", parse_dates=["date_et"])
panel["is_btc"] = (panel.asset_id == "BTC").astype(int)
print("panel", panel.shape, "daily", daily.shape, "roll", roll.shape, flush=True)


def headline_sample(pnl, assets=None, leg="SPY", donut=True,
                    start=SAMPLE_START, end=SAMPLE_END):
    assets = HEADLINE if assets is None else assets
    d = pnl[(pnl.asset_id.isin(assets)) & (pnl.market_leg == leg)
            & (pnl.year_month >= start) & (pnl.year_month <= end)].copy()
    return d[~d.year_month.isin(DONUT)] if donut else d


def add_treat(d, treated="BTC", month=TREAT_MONTH, col="d_etf_listed"):
    d = d.copy()
    d[col] = ((d.asset_id == treated) & (d.year_month >= month)).astype(int)
    return d


results, robust = {}, {}

# ==========================================================================
# 1. MAIN -- identified TWFE DiD
# ==========================================================================
print("=== main ===", flush=True)
smp = add_treat(headline_sample(panel))
m = feols(smp, "y_fisherz_corr_equity", ["d_etf_listed"],
          fes=["asset_id", "year_month"], cluster="asset_id")
tau = float(m["beta"][0])
se_cl = m["coefficients"]["d_etf_listed"]["se"]
n_pre = int(((smp.asset_id == "BTC") & (smp.year_month < TREAT_MONTH)).sum())
n_post = int(((smp.asset_id == "BTC") & (smp.year_month >= TREAT_MONTH)).sum())
rho_pre = float(smp[(smp.asset_id == "BTC") & (smp.year_month < TREAT_MONTH)].rho_m.mean())
print(f"tau={tau:.5f} se={se_cl:.5f} n={m['n']} G={smp.asset_id.nunique()}", flush=True)

# ---- randomization inference --------------------------------------------
print("--- randomization inference ---", flush=True)
placebo_space = []
for c in CONTROLS:
    s = add_treat(headline_sample(panel), treated=c)
    r = feols(s, "y_fisherz_corr_equity", ["d_etf_listed"],
              fes=["asset_id", "year_month"])
    placebo_space.append(float(r["beta"][0]))

cand = [mm for mm in sorted(panel.year_month.unique()) if "2021-07" <= mm <= "2023-01"]
base_pre = headline_sample(panel, donut=False, end="2023-07")
placebo_time = []
for c in HEADLINE:
    for pm in cand:
        s = add_treat(base_pre, treated=c, month=pm)
        r = feols(s, "y_fisherz_corr_equity", ["d_etf_listed"],
                  fes=["asset_id", "year_month"])
        placebo_time.append(float(r["beta"][0]))

grid = np.array(placebo_space + placebo_time)
p_ri = float((np.sum(np.abs(grid) >= abs(tau)) + 1) / (len(grid) + 1))
p_ri_space = float((np.sum(np.abs(placebo_space) >= abs(tau)) + 1) / (len(placebo_space) + 1))
sd_ri = float(np.std(grid, ddof=1))
ct_lo = float(tau - np.percentile(placebo_space, 97.5))
ct_hi = float(tau - np.percentile(placebo_space, 2.5))
sd_ct = float(np.std(placebo_space, ddof=1))
print(f"RI n={len(grid)} p_ri={p_ri:.3f} p_space={p_ri_space:.3f} sd_ri={sd_ri:.5f}",
      flush=True)

# ---- wild cluster bootstrap (Rademacher, null imposed) -------------------
print("--- wild cluster bootstrap ---", flush=True)
yd, Xd = m["yd"], m["Xd"]
cl = m["data"].asset_id.to_numpy()
cd = pd.Categorical(cl).codes
ncl = cd.max() + 1
XtXi = float(1.0 / (Xd[:, 0] @ Xd[:, 0]))
t_obs = m["coefficients"]["d_etf_listed"]["t_stat"]
nrow = len(yd)
adj_b = (ncl / (ncl - 1)) * ((nrow - 1) / max(nrow - 1 - (m["data"].asset_id.nunique()
                                                          + m["data"].year_month.nunique() - 1), 1))
tstars = []
for _ in range(999):
    w = RNG.choice([-1.0, 1.0], size=ncl)[cd]
    ys = w * yd  # null imposed: tau = 0, so restricted residual = demeaned y
    b = XtXi * float(Xd[:, 0] @ ys)
    e = ys - Xd[:, 0] * b
    sc = np.zeros(ncl)
    np.add.at(sc, cd, Xd[:, 0] * e)
    v = XtXi * (adj_b * float(sc @ sc)) * XtXi
    if v > 0:
        tstars.append(b / math.sqrt(v))
tstars = np.array(tstars)
p_wild = float((np.sum(np.abs(tstars) >= abs(t_obs)) + 1) / (len(tstars) + 1))
print(f"wild bootstrap p={p_wild:.3f}", flush=True)

results["main"] = spec_entry(
    m,
    "TWFE difference-in-differences on the coin-month panel; outcome is the Fisher-z within-"
    "month correlation of the coin's daily return with SPY; coin and year-month fixed effects; "
    "no controls (volume/volatility/market cap are mediators, not confounders); SEs clustered "
    "on coin; randomization inference is the primary inference procedure because there is one "
    "treated unit.",
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
        "correlation_conversion_factor": float(1 - rho_pre**2),
        "effect_in_correlation_units": float((1 - rho_pre**2) * tau),
    },
    diag_extra={"n_coin_fe": int(smp.asset_id.nunique()),
                "n_month_fe": int(smp.year_month.nunique()),
                "n_clusters_coin": int(smp.asset_id.nunique())},
)
results["main"]["diagnostics"]["n_fixed_effect_groups"] = int(
    smp.asset_id.nunique() + smp.year_month.nunique() - 1)

# ==========================================================================
# 2. descriptive raw gap (NOT the headline)
# ==========================================================================
print("=== descriptive raw gap ===", flush=True)
btc = headline_sample(panel, assets=["BTC"]).sort_values("year_month")
Xrg = np.column_stack([np.ones(len(btc)),
                       (btc.year_month >= TREAT_MONTH).astype(float).to_numpy()])
rg = ols_hac(btc.y_fisherz_corr_equity.to_numpy(), Xrg, ["const", "post_etf"], L=6)
results["descriptive_raw_gap"] = {
    "specification": "DESCRIPTIVE BASELINE, NOT IDENTIFIED: Bitcoin-only monthly time series of "
                     "the Fisher-z equity correlation on a post-2024m2 indicator, Newey-West(6). "
                     "Cannot separate the ETF from the 2024 macro regime; reported so the reader "
                     "can see what the control group and month fixed effects are doing.",
    "unit_of_analysis": "month", "outcome": "y_fisherz_corr_equity", "treatment": "post_etf",
    "n_observations": rg["n"], "n_clusters": None, "cluster_level": "none",
    "fixed_effects": [], "controls": [],
    "n_pre_treatment": n_pre, "n_post_treatment": n_post,
    "coefficients": rg["coefficients"],
    "diagnostics": {"r_squared": rg["r_squared"], "newey_west_lags": rg["nw_lags"],
                    "df_residual": int(rg["n"] - 2), "n_fixed_effect_groups": 0,
                    "mean_y_pre": float(
                        btc[btc.year_month < TREAT_MONTH].y_fisherz_corr_equity.mean()),
                    "mean_y_post": float(
                        btc[btc.year_month >= TREAT_MONTH].y_fisherz_corr_equity.mean())},
}

# ==========================================================================
# 3. event study + pre-trends
# ==========================================================================
print("=== event study ===", flush=True)
def kmonth(ym):
    y_, mo = int(ym[:4]), int(ym[5:7])
    return (y_ - int(TREAT_MONTH[:4])) * 12 + (mo - int(TREAT_MONTH[5:7]))


es = headline_sample(panel).copy()
es["K"] = es.year_month.map(kmonth)
# Six-month event-time bins. A month-by-month event study is SATURATED for the single
# treated unit -- BTC's residual is identically zero in every month carrying its own
# dummy -- so its standard errors are computed off the control coins alone and are
# meaningless. Binning gives each coefficient six treated observations and restores a
# non-degenerate residual for BTC.
BIN = 6
es["KB"] = np.floor(es.K / BIN).astype(int)
REF = -2  # the bin covering K = -12..-7, i.e. the six months ending at the donut
kbs = sorted(k for k in es.KB.unique() if k != REF)
for k in kbs:
    es[f"ev_{k}"] = ((es.asset_id == "BTC") & (es.KB == k)).astype(int)
evcols = [f"ev_{k}" for k in kbs]
ev = feols(es, "y_fisherz_corr_equity", evcols, fes=["asset_id", "year_month"],
           cluster="asset_id")
lead_idx = [i for i, k in enumerate(kbs) if k < REF]
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


# The clustered pre-trend F is subject to the same one-treated-unit objection as the
# clustered p-value on tau: the lead coefficients are BTC-specific, so the cluster-robust
# covariance is driven by a single cluster. Randomization inference over placebo treated
# coins is the valid version of the test, and it is the one to read.
def pretrend_F(dfx, treated):
    d2 = dfx.copy()
    for kk in kbs:
        d2[f"ev_{kk}"] = ((d2.asset_id == treated) & (d2.KB == kk)).astype(int)
    rr = feols(d2, "y_fisherz_corr_equity", evcols, fes=["asset_id", "year_month"],
               cluster="asset_id")
    bb = R @ rr["beta"]
    return float(bb @ np.linalg.pinv(R @ rr["vcov"] @ R.T) @ bb) / q


placebo_F = [pretrend_F(es, c) for c in CONTROLS]
p_pre_ri = float((np.sum(np.array(placebo_F) >= F_pre) + 1) / (len(placebo_F) + 1))
placebo_lin = []
for c in CONTROLS:
    p2 = pre.copy()
    p2["btc_trend"] = (p2.asset_id == c).astype(float) * p2.K
    placebo_lin.append(abs(float(feols(p2, "y_fisherz_corr_equity", ["btc_trend"],
                                       fes=["asset_id", "year_month"])["beta"][0])))
p_lin_ri = float((np.sum(np.array(placebo_lin) >= abs(float(lin["beta"][0]))) + 1)
                 / (len(placebo_lin) + 1))

# month-by-month path, point estimates only (saturated -> no valid SEs)
esm = headline_sample(panel).copy()
esm["K"] = esm.year_month.map(kmonth).clip(-24, 24)
kms = sorted(k for k in esm.K.unique() if k != -7)
for k in kms:
    esm[f"m_{k}"] = ((esm.asset_id == "BTC") & (esm.K == k)).astype(int)
evm = feols(esm, "y_fisherz_corr_equity", [f"m_{k}" for k in kms],
            fes=["asset_id", "year_month"])
monthly_path = {str(k): round(float(evm["beta"][i]), 6) for i, k in enumerate(kms)}

results["event_study"] = {
    "specification": "Event study in six-month event-time bins relative to 2024m2, with coin "
                     f"and year-month fixed effects; reference bin {REF} (K = -12 to -7, the "
                     "six months ending at the donut, since the conventional k=-1 falls inside "
                     "the donut). Bins rather than single months because a month-by-month "
                     "specification is saturated for the single treated unit: BTC's residual is "
                     "identically zero in any month carrying its own dummy, so the standard "
                     "errors would be computed off the control coins alone. Clustered on coin.",
    "unit_of_analysis": "coin-month", "outcome": "y_fisherz_corr_equity",
    "treatment": "btc_x_event_bin", "bin_width_months": BIN,
    "n_observations": int(ev["n"]), "n_clusters": int(es.asset_id.nunique()),
    "cluster_level": "coin", "fixed_effects": ["coin", "year_month"], "controls": [],
    "n_pre_treatment": n_pre, "n_post_treatment": n_post,
    "reference_period": REF,
    "coefficients": ev["coefficients"],
    "pre_trend_f_stat": F_pre, "pre_trend_p_value": p_pre, "n_pre_coefficients": q,
    "pre_trend_p_value_ri": p_pre_ri,
    "pre_trend_placebo_F_max": float(np.max(placebo_F)),
    "pre_trend_placebo_F_median": float(np.median(placebo_F)),
    "n_placebo_assignments": len(placebo_F),
    "pre_trend_inference_note": "pre_trend_p_value is the clustered/asymptotic F p-value and is "
                                "subject to the same one-treated-unit objection as the clustered "
                                "p-value on tau: the lead coefficients are BTC-specific, so the "
                                "cluster-robust covariance is driven by a single cluster. "
                                "pre_trend_p_value_ri -- the share of placebo treated coins whose "
                                "own pre-trend F is at least as large -- is the valid test and "
                                "the one the paper quotes.",
    "linear_pre_trend_estimate": float(lin["beta"][0]),
    "linear_pre_trend_se": lin["coefficients"]["btc_trend"]["se"],
    "linear_pre_trend_p_value": lin["coefficients"]["btc_trend"]["p_value"],
    "linear_pre_trend_p_value_ri": p_lin_ri,
    "monthly_path_point_estimates": monthly_path,
    "monthly_path_note": "Point estimates only. The month-by-month specification is saturated "
                         "for the single treated unit, so no standard error reported against "
                         "it would be interpretable; use the binned coefficients for inference.",
    "diagnostics": {"within_r_squared": round(ev["within_r2"], 6),
                    "df_residual": int(ev["df_residual"]),
                    "n_fixed_effect_groups": int(es.asset_id.nunique()
                                                 + es.year_month.nunique() - 1)},
}
print(f"pre-trend F={F_pre:.3f} p_asym={p_pre:.4f} p_RI={p_pre_ri:.3f} (q={q}, "
      f"placebo F max={max(placebo_F):.2f} med={np.median(placebo_F):.2f}) | "
      f"linear={lin['beta'][0]:+.5f} p={lin['coefficients']['btc_trend']['p_value']:.4f} "
      f"p_RI={p_lin_ri:.3f}", flush=True)

# ==========================================================================
# 4. daily rolling-window panel DiD
# ==========================================================================
print("=== daily rolling DiD ===", flush=True)
def daily_panel(window, leg="SPY", assets=None, treated="BTC", stat="rho",
                treat_date="2024-02-01", donut=True,
                start="2021-01-01", end="2025-12-31"):
    assets = HEADLINE if assets is None else assets
    have = {a: f"{stat}{window}d_{a}_{leg}" for a in assets
            if f"{stat}{window}d_{a}_{leg}" in roll.columns}
    sub = roll[["date_et"] + list(have.values())]
    sub = sub[(sub.date_et >= start) & (sub.date_et <= end)]
    long = sub.melt("date_et", var_name="col", value_name="val").dropna()
    long["asset_id"] = long.col.map({v: k for k, v in have.items()})
    if donut:
        long = long[~((long.date_et >= "2023-08-01") & (long.date_et <= "2024-01-31"))]
    long["y"] = (np.arctanh(long.val.clip(-0.999, 0.999)) if stat == "rho" else long.val)
    long["d_etf_listed"] = ((long.asset_id == treated)
                            & (long.date_et >= treat_date)).astype(int)
    long["date_s"] = long.date_et.dt.strftime("%Y-%m-%d")
    return long


for w, key in [(30, "daily_rolling_did"), (60, "window_60d"), (90, "window_90d")]:
    lp = daily_panel(w)
    rr = feols(lp, "y", ["d_etf_listed"], fes=["asset_id", "date_s"], cluster="asset_id")
    rr2 = feols(lp, "y", ["d_etf_listed"], fes=["asset_id", "date_s"],
                cluster="asset_id", cluster2="date_s")
    ent = spec_entry(
        rr,
        f"Daily rolling-window DiD: Fisher-z of the {w}-day rolling correlation with SPY, asset "
        "and date fixed effects, clustered on asset. Windows overlap, so the number of "
        "independent blocks is far below the row count (reported as n_effective_blocks) and the "
        "standard error must not be read as coming from n_observations independent draws.",
        fes=["asset", "date"], controls=[], cluster_level="asset",
        extra={"unit_of_analysis": "asset-day", "outcome": f"fisherz_rho{w}d_spy",
               "treatment": "d_etf_listed", "treated_units": 1, "rolling_window_days": w,
               "n_effective_blocks": int(round(rr["n"] / w)),
               "n_pre_treatment": int(((lp.asset_id == "BTC")
                                       & (lp.date_et < "2024-02-01")).sum()),
               "n_post_treatment": int(((lp.asset_id == "BTC")
                                        & (lp.date_et >= "2024-02-01")).sum()),
               "se_twoway_cluster": rr2["coefficients"]["d_etf_listed"]["se"],
               "p_value_twoway_cluster": rr2["coefficients"]["d_etf_listed"]["p_value"]},
        diag_extra={"n_dates": int(lp.date_s.nunique()),
                    "n_assets": int(lp.asset_id.nunique())})
    ent["diagnostics"]["n_fixed_effect_groups"] = int(lp.asset_id.nunique()
                                                      + lp.date_s.nunique() - 1)
    (results if key == "daily_rolling_did" else robust)[key] = ent
    print(f"  w={w}: tau={rr['beta'][0]:+.5f} n={rr['n']}", flush=True)

# ==========================================================================
# 5. returns-level models
# ==========================================================================
print("=== returns-level ===", flush=True)
dd = daily[(daily.date_et >= "2021-01-01") & (daily.date_et <= "2025-12-31")].copy()
dd = dd[~((dd.date_et >= "2023-08-01") & (dd.date_et <= "2024-01-31"))]
dd["post"] = (dd.date_et >= "2024-02-01").astype(int)

per_delta = {}
for a in HEADLINE:
    s = dd[["date_et", f"r_{a}", "r_SPY", "post"]].dropna()
    X = np.column_stack([np.ones(len(s)), s.r_SPY.to_numpy(),
                         (s.r_SPY * s.post).to_numpy(), s.post.to_numpy(float)])
    r = ols_hac(s[f"r_{a}"].to_numpy(), X, ["const", "r_spy", "r_spy_x_post", "post"])
    per_delta[a] = r
    if a == "BTC":
        results["returns_interacted_BTC"] = {
            "specification": "Returns-level interacted model for Bitcoin: r_btc = a + b*r_spy + "
                             "delta*(r_spy x Post) + g*Post, Newey-West HAC standard errors. "
                             "delta is the change in the equity loading, estimated without a "
                             "generated-regressor step.",
            "unit_of_analysis": "day", "outcome": "r_BTC", "treatment": "r_spy_x_post",
            "n_observations": r["n"], "n_clusters": None, "cluster_level": "none",
            "fixed_effects": [], "controls": ["r_spy", "post"],
            "n_pre_treatment": int((s.post == 0).sum()),
            "n_post_treatment": int((s.post == 1).sum()),
            "coefficients": r["coefficients"],
            "diagnostics": {"r_squared": r["r_squared"], "newey_west_lags": r["nw_lags"],
                            "df_residual": int(r["n"] - 4), "n_fixed_effect_groups": 0},
        }

ctrl_d = [per_delta[a]["coefficients"]["r_spy_x_post"]["estimate"] for a in CONTROLS]
btc_d = per_delta["BTC"]["coefficients"]["r_spy_x_post"]["estimate"]
results["returns_interacted_BTC"].update({
    "p_value_ri_across_control_coins": float(
        (np.sum(np.abs(ctrl_d) >= abs(btc_d)) + 1) / (len(ctrl_d) + 1)),
    "control_coin_delta_mean": float(np.mean(ctrl_d)),
    "control_coin_delta_sd": float(np.std(ctrl_d, ddof=1)),
    "control_coin_deltas": {a: float(per_delta[a]["coefficients"]["r_spy_x_post"]["estimate"])
                            for a in CONTROLS},
})

rl = dd.melt(["date_et", "r_SPY", "post"], value_vars=[f"r_{a}" for a in HEADLINE],
             var_name="col", value_name="r").dropna()
rl["asset_id"] = rl.col.str[2:]
isb = (rl.asset_id == "BTC").astype(float)
rl["reqXbtc"] = rl.r_SPY * isb
rl["reqXpostXbtc"] = rl.r_SPY * rl.post * isb
rl["date_s"] = rl.date_et.dt.strftime("%Y-%m-%d")
ddd = feols(rl, "r", ["reqXpostXbtc", "reqXbtc"], fes=["asset_id", "date_s"], cluster="date_s")
ddd_a = feols(rl, "r", ["reqXpostXbtc", "reqXbtc"], fes=["asset_id", "date_s"],
              cluster="asset_id")
ent = spec_entry(
    ddd,
    "Pooled returns-level triple difference: r_it on (r_spy x Post x BTC) and (r_spy x BTC), "
    "with asset and date fixed effects, which absorb r_spy and r_spy x Post. The triple "
    "interaction is the differential change in Bitcoin's equity loading relative to the "
    "never-treated coins. Uses no generated regressor, so the Fisher-z transform cannot drive "
    "the result. Clustered on date.",
    fes=["asset", "date"], controls=["reqXbtc"], cluster_level="date",
    extra={"unit_of_analysis": "asset-day", "outcome": "r_asset",
           "treatment": "reqXpostXbtc", "treated_units": 1,
           "n_pre_treatment": int((rl.post == 0).sum()),
           "n_post_treatment": int((rl.post == 1).sum()),
           "se_cluster_asset": ddd_a["coefficients"]["reqXpostXbtc"]["se"],
           "p_value_cluster_asset": ddd_a["coefficients"]["reqXpostXbtc"]["p_value"]},
    diag_extra={"n_dates": int(rl.date_s.nunique()), "n_assets": int(rl.asset_id.nunique())})
ent["diagnostics"]["n_fixed_effect_groups"] = int(rl.asset_id.nunique() + rl.date_s.nunique() - 1)
results["returns_ddd"] = ent
print(f"  DDD={ddd['beta'][0]:+.5f} se={ddd['coefficients']['reqXpostXbtc']['se']:.5f}",
      flush=True)

# ==========================================================================
# 6. Chow test at the imposed date
# ==========================================================================
print("=== chow test ===", flush=True)
def chow(s, ycol, brk="2024-02-01"):
    s = s.dropna(subset=[ycol, "r_SPY"])
    post = (s.date_et >= brk).astype(float).to_numpy()
    x, y = s.r_SPY.to_numpy(), s[ycol].to_numpy()
    X = np.column_stack([np.ones(len(s)), x, post, x * post])
    n, k = X.shape
    XtXi = np.linalg.pinv(X.T @ X)
    b = XtXi @ (X.T @ y)
    e = y - X @ b
    R = np.zeros((2, k)); R[0, 2] = 1.0; R[1, 3] = 1.0
    Vc = (float(e @ e) / (n - k)) * XtXi
    F_cl = float((R @ b) @ np.linalg.pinv(R @ Vc @ R.T) @ (R @ b) / 2.0)
    lev = np.einsum("ij,jk,ik->i", X, XtXi, X)
    V3 = XtXi @ ((X * (e**2 / np.clip(1 - lev, 1e-8, None) ** 2)[:, None]).T @ X) @ XtXi
    W3 = float((R @ b) @ np.linalg.pinv(R @ V3 @ R.T) @ (R @ b))
    hac = ols_hac(y, X, ["const", "r_spy", "post", "r_spy_x_post"])
    Wh = float((R @ hac["beta"]) @ np.linalg.pinv(R @ hac["V"] @ R.T) @ (R @ hac["beta"]))
    return {"f_stat_classical": F_cl, "p_value_classical": f_sf(F_cl, 2, n - k),
            "wald_hc3": W3, "p_value_hc3": chi2_sf(W3, 2),
            "wald_hac_newey_west": Wh, "p_value_hac": chi2_sf(Wh, 2),
            "n": n, "nw_lags": hac["nw_lags"], "coefficients": hac["coefficients"]}


ch = chow(dd[["date_et", "r_BTC", "r_SPY"]], "r_BTC")
raw = daily[(daily.date_et >= "2021-01-01") & (daily.date_et <= "2025-12-31")]
chn = chow(raw[["date_et", "r_BTC", "r_SPY"]], "r_BTC", brk="2024-01-11")
results["chow_test"] = {
    "specification": "Chow test for a structural break in Bitcoin's equity-loading regression at "
                     "the imposed date 2024-02-01 (donut sample). Classical F, HC3 Wald and HAC "
                     "(Newey-West) Wald are all reported because they differ; the HAC Wald is "
                     "the one to quote, the classical F is reported for completeness only.",
    "unit_of_analysis": "day", "outcome": "r_BTC", "treatment": "break_2024_02_01",
    "n_observations": ch["n"], "n_clusters": None, "cluster_level": "none",
    "fixed_effects": [], "controls": ["r_spy", "post"],
    "n_pre_treatment": int((dd.date_et < "2024-02-01").sum()),
    "n_post_treatment": int((dd.date_et >= "2024-02-01").sum()),
    "coefficients": ch["coefficients"],
    "f_stat_classical": ch["f_stat_classical"], "p_value_classical": ch["p_value_classical"],
    "wald_hc3": ch["wald_hc3"], "p_value_hc3": ch["p_value_hc3"],
    "wald_hac_newey_west": ch["wald_hac_newey_west"], "p_value_hac": ch["p_value_hac"],
    "wald_hac_no_donut_2024_01_11": chn["wald_hac_newey_west"],
    "p_value_hac_no_donut": chn["p_value_hac"],
    "diagnostics": {"newey_west_lags": ch["nw_lags"], "df_residual": int(ch["n"] - 4),
                    "n_fixed_effect_groups": 0},
}
print(f"  chow HAC W={ch['wald_hac_newey_west']:.3f} p={ch['p_value_hac']:.4f}", flush=True)

# ==========================================================================
# 7. Bai-Perron structural breaks + Andrews sup-Wald
# ==========================================================================
print("=== bai-perron ===", flush=True)
def bai_perron(y, m_max=5, trim=0.15):
    y = np.asarray(y, float)
    T = len(y)
    h = max(2, int(np.floor(trim * T)))
    cs = np.concatenate([[0.0], np.cumsum(y)])
    cs2 = np.concatenate([[0.0], np.cumsum(y**2)])
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
            "note": "Break-date confidence intervals are not reported: the Bai-Perron interval "
                    "requires a HAC break-fraction asymptotic that is not implemented here."}


rb = roll[(roll.date_et >= "2021-01-01") & (roll.date_et <= "2025-12-31")]
bbeta = rb[["date_et", "beta30d_BTC_SPY"]].dropna()
bp_beta = bp_report(bbeta.date_et.to_numpy(), bbeta.beta30d_BTC_SPY.to_numpy(),
                    "beta30d_BTC_SPY")
ctrl_cols = [f"rho30d_{a}_SPY" for a in CONTROLS]
dfm = rb[["date_et", "rho30d_BTC_SPY"] + ctrl_cols].dropna()
z_btc = np.arctanh(dfm.rho30d_BTC_SPY.clip(-0.999, 0.999))
z_ctl = np.arctanh(dfm[ctrl_cols].clip(-0.999, 0.999)).mean(axis=1)
diff_series = (z_btc - z_ctl).to_numpy()
bp_diff = bp_report(dfm.date_et.to_numpy(), diff_series,
                    "fisherz_rho30d_BTC_minus_control_mean")

def lrv(x, L):
    """Newey-West long-run variance of the sample mean of x."""
    e = np.asarray(x, float) - np.mean(x)
    n = len(e)
    s = float(e @ e) / n
    for lg in range(1, min(L, n - 1) + 1):
        s += 2.0 * (1.0 - lg / (L + 1.0)) * float(e[lg:] @ e[:-lg]) / n
    return max(s, 1e-16)


# The rolling series overlaps on 29 of 30 days, so an iid sup-Wald is badly oversized.
# Both the iid and the Newey-West (L = 60, twice the window) versions are reported.
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
    wst = dm**2 / (s2 * (1.0 / n1 + 1.0 / n2))
    if wst > best_w:
        best_w, best_b = wst, b
    wh = dm**2 / (lrv(g1, NW_L) / n1 + lrv(g2, NW_L) / n2)
    if wh > best_wh:
        best_wh, best_bh = wh, b
results["bai_perron"] = {
    "specification": "Bai-Perron multiple structural break tests (15% trimming, up to 5 breaks, "
                     "BIC and LWZ selection, sequential supF(l+1|l)) on Bitcoin's 30-day rolling "
                     "beta and on the BTC-minus-control-mean differential Fisher-z series. Every "
                     "estimated break date is reported whether or not it supports the hypothesis. "
                     "Andrews (1993) sup-Wald with unknown breakpoint reported alongside.",
    "unit_of_analysis": "day", "outcome": "rolling_beta_and_differential_fisherz",
    "treatment": "endogenous_break_date", "n_observations": int(T),
    "n_clusters": None, "cluster_level": "none", "fixed_effects": [], "controls": [],
    "n_pre_treatment": int((dfm.date_et < "2024-02-01").sum()),
    "n_post_treatment": int((dfm.date_et >= "2024-02-01").sum()),
    "coefficients": {},
    "btc_rolling_beta": bp_beta, "differential_fisherz": bp_diff,
    "andrews_sup_wald": float(best_w),
    "andrews_break_date": str(pd.Timestamp(dfm.date_et.to_numpy()[best_b]).date()),
    "andrews_sup_wald_hac": float(best_wh),
    "andrews_break_date_hac": str(pd.Timestamp(dfm.date_et.to_numpy()[best_bh]).date()),
    "andrews_hac_lags": NW_L,
    "andrews_p_value": None,
    "andrews_note": "The sup-Wald null distribution is non-standard (Andrews 1993), so no "
                    "p-value is computed; the 5% asymptotic critical value for a one-parameter "
                    "mean break with 15% trimming is approximately 8.85. The iid version is "
                    "badly oversized here because the 30-day rolling windows overlap on 29 of "
                    "30 days; the Newey-West version (L = 60, twice the window length) is the "
                    "one to read.",
    "diagnostics": {"n_fixed_effect_groups": 0, "df_residual": int(T - 2)},
}
print("  BP beta:", bp_beta["break_dates_bic"], flush=True)
print("  BP diff:", bp_diff["break_dates_bic"], flush=True)
print(f"  Andrews supW(iid)={best_w:.2f} at {results['bai_perron']['andrews_break_date']} | "
      f"supW(HAC60)={best_wh:.2f} at {results['bai_perron']['andrews_break_date_hac']}",
      flush=True)

# ==========================================================================
# 8. DCC-GARCH(1,1) with a post dummy in the correlation target
# ==========================================================================
print("=== DCC-GARCH ===", flush=True)
def garch11(r):
    r = np.asarray(r, float)
    r = r - r.mean()
    v = float(r.var())
    n = len(r)

    def nll(p):
        om, al, be = math.exp(p[0]), 1 / (1 + math.exp(-p[1])), 1 / (1 + math.exp(-p[2]))
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

    x0 = np.array([math.log(max(v * 0.05, 1e-12)), math.log(0.08 / 0.92), math.log(0.90 / 0.10)])
    xo, _, ok = nelder_mead(nll, x0, maxiter=1200, step=0.3)
    om, al, be = math.exp(xo[0]), 1 / (1 + math.exp(-xo[1])), 1 / (1 + math.exp(-xo[2]))
    h = np.empty(n); h[0] = v
    for t in range(1, n):
        h[t] = om + al * r[t - 1] ** 2 + be * h[t - 1]
    return r / np.sqrt(h), {"omega": float(om), "alpha": float(al), "beta": float(be),
                            "converged": bool(ok)}


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
            rho = q12 / den
            rho = max(-0.9995, min(0.9995, rho))
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
            + nll(xo - np.array([0, 0, eps]))) / eps**2
    se = float(math.sqrt(1.0 / hess)) if hess > 1e-12 else None
    return {"a": float(a), "b": float(b), "phi": phi, "se_phi": se,
            "loglik": float(-f0), "converged": bool(ok), "qbar": qb}


dgs = daily[(daily.date_et >= "2021-01-01") & (daily.date_et <= "2025-12-31")].copy()
dgs["post"] = (dgs.date_et >= "2024-02-01").astype(int)
dgs = dgs[["date_et", "post", "r_SPY"] + [f"r_{a}" for a in HEADLINE]].dropna()
u_spy, g_spy = garch11(dgs.r_SPY.to_numpy())
u_btc, g_btc = garch11(dgs.r_BTC.to_numpy())
postv = dgs.post.to_numpy(float)
dcc = dcc_post(u_btc, u_spy, postv)
phi, se_phi = dcc["phi"], dcc["se_phi"]
t_phi = (phi / se_phi) if se_phi else None
p_phi = (2 * norm_sf(abs(t_phi))) if t_phi is not None else None

ctrl_phi = {}
for a in CONTROLS:
    try:
        ua, _ = garch11(dgs[f"r_{a}"].to_numpy())
        ctrl_phi[a] = float(dcc_post(ua, u_spy, postv)["phi"])
    except Exception as exc:  # noqa: BLE001
        print("  DCC failed for", a, exc, flush=True)
vals = list(ctrl_phi.values())
p_phi_ri = (float((np.sum(np.abs(vals) >= abs(phi)) + 1) / (len(vals) + 1)) if vals else None)

results["dcc_garch_btc_spy"] = {
    "specification": "DCC-GARCH(1,1) on the BTC-SPY pair, two-stage QML, with a post-treatment "
                     "dummy shifting the off-diagonal long-run correlation target: q12_t = "
                     "(1-a-b)(qbar + phi*Post_t) + a u1_{t-1}u2_{t-1} + b q12_{t-1}. phi is the "
                     "post-listing shift in the correlation target. The same model is fitted to "
                     "every control-coin-SPY pair, and that cross-sectional distribution of phi "
                     "is the placebo distribution for Bitcoin's.",
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
                    "note": "Second-stage standard errors ignore first-stage GARCH estimation "
                            "error; the control-pair placebo distribution is the reliable "
                            "inference channel. The DCC uses the uninterrupted daily series "
                            "(no donut) because the recursion needs a continuous sample."},
}
print(f"  phi={phi:.6f} se={se_phi} p_ri={p_phi_ri}", flush=True)

# ==========================================================================
# 9. BDM collapse + power/MDE
# ==========================================================================
print("=== BDM + power ===", flush=True)
col = smp.copy()
col["per"] = np.where(col.year_month >= TREAT_MONTH, "post", "pre")
cm = col.groupby(["asset_id", "per"], as_index=False).y_fisherz_corr_equity.mean()
cm["d_etf_listed"] = ((cm.asset_id == "BTC") & (cm.per == "post")).astype(int)
bdm = feols(cm, "y_fisherz_corr_equity", ["d_etf_listed"], fes=["asset_id", "per"],
            cluster="asset_id")
results["bdm_collapsed"] = spec_entry(
    bdm,
    "Bertrand-Duflo-Mullainathan collapse: the panel is reduced to one pre-mean and one "
    "post-mean per coin and the DiD re-estimated, which removes serial correlation in the "
    "idiosyncratic error by construction.",
    fes=["coin", "period"], controls=[], cluster_level="coin",
    extra={"unit_of_analysis": "coin-period", "outcome": "y_fisherz_corr_equity",
           "treatment": "d_etf_listed", "treated_units": 1,
           "n_pre_treatment": int(cm.asset_id.nunique()),
           "n_post_treatment": int(cm.asset_id.nunique())})
results["bdm_collapsed"]["diagnostics"]["n_fixed_effect_groups"] = int(cm.asset_id.nunique() + 1)

mde_cl, mde_ri, mde_ct = MDE_MULT * se_cl, MDE_MULT * sd_ri, MDE_MULT * sd_ct
conv = 1 - rho_pre**2
results["power_analysis"] = {
    "specification": "Minimum detectable effect for the primary specification at alpha=0.05 "
                     "two-sided and 80% power: MDE = (z_0.975 + z_0.80) * se = 2.80158 * se, "
                     "computed from three reference distributions. The randomization-based "
                     "number is the honest one under a single treated unit. Pre-specified in "
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
        "mde_fisherz_conley_taber": {"estimate": float(mde_ct), "se": None, "t_stat": None,
                                     "p_value": None},
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
    "conley_taber_ci_lower_correlation_units": float(ct_lo * conv),
    "conley_taber_ci_upper_correlation_units": float(ct_hi * conv),
    "prespecified_null_threshold_fisherz": 0.10,
    "prespecified_mde_bar_correlation_units": 0.10,
    "prespecified_bar_met": bool(float(mde_ri * conv) <= 0.10),
    "verdict": ("The randomization-based MDE in correlation units is "
                f"{mde_ri * conv:.3f}. Section 9.2 of econometric_spec.md pre-committed to "
                "licensing a null claim only if this was at or below 0.10 and to making no "
                "null claim if it exceeded 0.20. The realized value falls between the two "
                "bars, so the paper reports a null on every pre-specified dimension while "
                "stating that effects below roughly 0.15 in correlation units could not have "
                "been detected with 80% power. The randomization 95% interval separately "
                f"excludes increases above {(tau + Z95 * sd_ri) * conv:.3f} in correlation "
                "units."),
    "diagnostics": {"n_fixed_effect_groups": 0, "df_residual": int(m["df_residual"])},
}
print(f"  MDE ri={mde_ri:.5f} ({mde_ri*conv:.5f} rho) cl={mde_cl:.5f} ct={mde_ct:.5f}",
      flush=True)

# ==========================================================================
# 10. ROBUSTNESS
# ==========================================================================
print("=== robustness ===", flush=True)
def rob(key, name, d, ycol="y_fisherz_corr_equity", xcols=("d_etf_listed",),
        cluster="asset_id", cluster2=None, controls=(), treated="BTC"):
    xcols = list(xcols)
    r = feols(d, ycol, xcols, fes=["asset_id", "year_month"],
              cluster=cluster, cluster2=cluster2)
    est = float(r["beta"][0])
    # placebo-in-space randomization p-value on this row's own sample: reassign the
    # same post-period to each untreated coin in turn. With one treated unit the
    # clustered p-value is not the inferential basis (see econometric_spec.md sec 8).
    post_months = set(d.loc[d[xcols[0]] == 1, "year_month"])
    donors = [a for a in d.asset_id.unique() if a != treated]
    pl = []
    for c in donors:
        d2 = d.copy()
        d2[xcols[0]] = ((d2.asset_id == c) & (d2.year_month.isin(post_months))).astype(int)
        try:
            pl.append(float(feols(d2, ycol, xcols, fes=["asset_id", "year_month"])["beta"][0]))
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
    robust[key] = ent
    print(f"  {key}: {est:+.5f} (se {r['coefficients'][xcols[0]]['se']:.5f}) "
          f"n={r['n']} p_ri={p_sp}", flush=True)
    return r


def build_monthly(dfd, assets, mkt="r_SPY", exclude=None, winsor=False):
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


sanity = build_monthly(daily, ["BTC"])
chk = sanity.merge(panel[(panel.asset_id == "BTC") & (panel.market_leg == "SPY")],
                   on="year_month", suffixes=("_new", "_old"))
sanity_corr = float(chk.y_fisherz_corr_equity_new.corr(chk.y_fisherz_corr_equity_old))
print(f"  sanity corr(rebuilt, delivered) = {sanity_corr:.4f}", flush=True)

# R2 -- return alignment
frames = []
for a in HEADLINE:
    try:
        px = pd.read_csv(f"data/px_{a}_USD.csv")
    except FileNotFoundError:
        continue
    px["d"] = pd.to_datetime(px["date"], utc=True, format="ISO8601").dt.tz_localize(None)
    px = px.sort_values("d")
    px[f"r_{a}"] = np.log(px["close"]).diff()
    frames.append(px[["d", f"r_{a}"]].dropna().set_index("d"))
utc = pd.concat(frames, axis=1).reset_index().rename(columns={"d": "date_et"})
utc["date_et"] = utc.date_et.dt.normalize()
utc = utc.merge(daily[["date_et", "r_SPY"]], on="date_et", how="inner")
mu = add_treat(build_monthly(utc, HEADLINE).pipe(lambda x: x[~x.year_month.isin(DONUT)]))
r_utc = rob("utc_alignment",
            "24h-UTC return alignment: crypto returns rebuilt as 00:00-00:00 UTC log close-to-"
            "close from the raw price files and matched to ET-dated equity returns. NOTE: the "
            "delivered daily_returns.csv crypto series are already on the UTC clock, so this "
            "row reproduces `main` rather than testing against it. The equity-close "
            "(16:00-16:00 ET) clock is not constructible from the delivered data; the "
            "alignment_offday_span row below is the alignment test that is feasible here.",
            mu)
utc_matches_main = bool(abs(float(r_utc["beta"][0]) - tau) < 1e-8)
robust["utc_alignment"]["reproduces_main_exactly"] = utc_matches_main

# R2b -- off-day-span alignment: cumulate weekend/holiday crypto returns into the next
# equity session, so the crypto return spans exactly the same calendar time as the equity one.
off = pd.read_csv("data/crypto_offday_returns.csv", parse_dates=["date_utc"])
eq_dates = np.sort(daily.date_et.unique())
pos = np.searchsorted(eq_dates, off.date_utc.to_numpy(), side="left")
off = off.assign(_p=pos)
off = off[off._p < len(eq_dates)]
off["map_date"] = eq_dates[off._p.to_numpy()]
addm = off.groupby(["map_date", "asset_id"], as_index=False).r_utc.sum()
wide = addm.pivot(index="map_date", columns="asset_id", values="r_utc")
span = daily[["date_et", "r_SPY"] + [f"r_{a}" for a in HEADLINE]].copy()
n_span_assets = 0
for a in HEADLINE:
    if a in wide.columns:
        span[f"r_{a}"] = span[f"r_{a}"] + span.date_et.map(wide[a]).fillna(0.0)
        n_span_assets += 1
ms = add_treat(build_monthly(span, HEADLINE).pipe(lambda x: x[~x.year_month.isin(DONUT)]))
rob("alignment_offday_span",
    "Off-day-span alignment: weekend and holiday crypto returns (crypto_offday_returns.csv) "
    "are cumulated into the next equity session, so each crypto return spans exactly the same "
    "calendar interval as the equity return it is correlated with. This removes the "
    f"non-synchronicity that 24/7 trading creates. Applied to {n_span_assets} of "
    f"{len(HEADLINE)} sample assets.", ms)

# R3 -- exclude the halving window
rob("excl_halving",
    "Excludes 2024m4-2024m5, the April 19-20 2024 Bitcoin halving window: the largest "
    "BTC-specific post-treatment shock the DiD cannot difference out.",
    smp[~smp.year_month.isin(["2024-04", "2024-05"])])

# R4 -- VIX / MOVE interacted with the BTC indicator
mac = daily[["date_et", "lvl_VIX", "lvl_MOVE"]].copy()
mac["year_month"] = mac.date_et.dt.strftime("%Y-%m")
mmv = mac.groupby("year_month", as_index=False)[["lvl_VIX", "lvl_MOVE"]].mean()
sv = smp.merge(mmv, on="year_month", how="left")
sv["vix_x_btc"] = sv.lvl_VIX * sv.is_btc
sv["move_x_btc"] = sv.lvl_MOVE * sv.is_btc
rob("ctrl_vix_move",
    "Adds monthly VIX and MOVE levels interacted with the Bitcoin indicator, letting the macro "
    "regime load differentially on Bitcoin -- the version of the macro story that month fixed "
    "effects do not absorb. Main effects are collinear with the month FE and are absorbed.",
    sv.dropna(subset=["vix_x_btc", "move_x_btc"]),
    xcols=("d_etf_listed", "vix_x_btc", "move_x_btc"),
    controls=("vix_x_btc", "move_x_btc"))

# R5 -- placebo date density
robust["placebo_dates_pre"] = {
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
        "actual_estimate": {"estimate": tau, "se": se_cl, "t_stat": None, "p_value": p_ri},
    },
    "n_placebo_assignments": int(len(grid)),
    "n_placebo_space": int(len(placebo_space)), "n_placebo_time": int(len(placebo_time)),
    "share_abs_ge_actual": float(np.mean(np.abs(grid) >= abs(tau))),
    "p_value_ri": p_ri,
    "diagnostics": {"placebo_sd": sd_ri,
                    "placebo_q025": float(np.percentile(grid, 2.5)),
                    "placebo_q975": float(np.percentile(grid, 97.5)),
                    "n_fixed_effect_groups": int(smp.asset_id.nunique()
                                                 + smp.year_month.nunique() - 1),
                    "df_residual": int(m["df_residual"])},
}

# R6 -- BITO futures-ETF placebo
bito = add_treat(headline_sample(panel, donut=False, start="2021-01", end="2023-07"),
                 month="2021-11")
rob("placebo_bito_2021",
    "Placebo event: the 2021-10-19 launch of BITO, a US-listed futures-based Bitcoin ETF that "
    "did not change spot plumbing (no spot creation/redemption, roll costs). Sample restricted "
    "to 2021m1-2023m7 so the 2024 spot approval cannot contaminate it. Informative in either "
    "direction.", bito)

# R7 -- drop extreme crypto-idiosyncratic news days
absr = daily.r_BTC.abs()
cut = float(absr.quantile(0.99))
bad = set(daily.loc[absr > cut, "date_et"]) | set(
    daily.loc[(daily.date_et >= "2022-11-06") & (daily.date_et <= "2022-11-20"), "date_et"])
mn = add_treat(build_monthly(daily, HEADLINE, exclude=bad)
               .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
rob("excl_extreme_news",
    f"Drops days with extreme crypto-idiosyncratic news: |r_BTC| above its 99th percentile "
    f"({cut:.4f}) plus the 2022-11-06 to 2022-11-20 FTX-collapse window, with monthly outcomes "
    "rebuilt on the surviving days.", mn)

# R8 -- no donut
nd = headline_sample(panel, donut=False)
nd["d_etf_listed"] = ((nd.asset_id == "BTC") & (nd.year_month >= "2024-01")).astype(int)
rob("no_donut",
    "No donut: treatment switched on at the 2024-01-11 listing (2024m1) with 2023m8-2024m1 "
    "retained in the sample. Shows how much of the estimate the donut is absorbing.", nd)

# R9 -- market-factor leg
rob("leg_mkt", "Excess-return market factor leg instead of SPY.",
    add_treat(headline_sample(panel, leg="MKT")))

# R10 -- alternative outcomes
rob("outcome_beta",
    "Monthly equity beta instead of the Fisher-z correlation. beta = rho * "
    "(sigma_i/sigma_mkt), so it mixes the co-movement margin with the relative-volatility "
    "margin.", smp, ycol="beta_m")
rob("outcome_ln_sigma_ratio",
    "Log relative volatility ln(sigma_i/sigma_mkt), the second factor in beta, which isolates "
    "the volatility margin from the correlation margin.", smp, ycol="ln_sigma_ratio_m")

# R11 -- placebo assets
for key, asset in [("placebo_gold", "GLD"), ("placebo_silver", "SLV")]:
    pa = add_treat(headline_sample(panel, assets=[asset] + CONTROLS), treated=asset)
    rob(key,
        f"Placebo asset: {asset} assigned Bitcoin's treatment date against the never-treated "
        "crypto controls. Same macro regime, long-standing ETF, no 2024 access change -- a "
        "break here would falsify the design's macro-neutrality.", pa, treated=asset)

# R12 -- winsorized
mw = add_treat(build_monthly(daily, HEADLINE, winsor=True)
               .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
rob("winsorized",
    "Daily returns winsorized at the 0.5/99.5 within-asset percentiles before the monthly "
    "correlation is computed.", mw)

# R13 -- extended sample
rob("sample_extended_2026",
    "Estimation window extended to 2026m7, the full delivered panel. The declared window ends "
    "2025m12; this row shows what the extra seven months do rather than hiding the choice.",
    add_treat(headline_sample(panel, end="2026-07")))

# R14 -- two-way clustering
rob("twoway_cluster",
    "Primary specification with two-way clustering on coin and month. Subject to the same "
    "one-treated-unit objection as one-way clustering on coin.", smp, cluster2="year_month")

# R15 -- sub-windows isolating the halving and the election
rob("subwindow_pre_halving",
    "Post window truncated at 2024m3, entirely before the April 2024 halving.",
    add_treat(headline_sample(panel, end="2024-03")))
rob("subwindow_pre_election",
    "Post window truncated at 2024m10, before the November 2024 US election. This is the "
    "estimate to treat as ETF-attributable.",
    add_treat(headline_sample(panel, end="2024-10")))
rob("subwindow_post_election",
    "Post period restricted to 2024m11-2025m12, after the November 2024 US election; the "
    "pre-period is unchanged. Interpreted as ETF plus the post-election policy regime, not as "
    "an ETF effect.",
    add_treat(headline_sample(panel).pipe(
        lambda x: x[(x.year_month < TREAT_MONTH) | (x.year_month >= "2024-11")]),
        month="2024-11"))

# R16 -- non-US equity placebo leg
acw = daily[["date_et", "r_ACWX"] + [f"r_{a}" for a in HEADLINE]].dropna()
ma = add_treat(build_monthly(acw, HEADLINE, mkt="r_ACWX")
               .pipe(lambda x: x[~x.year_month.isin(DONUT)]))
rob("leg_acwx_non_us",
    "Non-US equity leg (ACWX, MSCI ACWI ex-US). If the mechanism is a US brokerage habitat, "
    "co-movement should rise more against US equities than against non-US equities; a uniform "
    "rise would point to global macro instead.", ma)

robust["sanity_rebuild_check"] = {
    "specification": "Diagnostic, not a specification: correlation between the delivered "
                     "coin_month_panel Fisher-z outcome for Bitcoin and the same object "
                     "rebuilt from daily_returns.csv inside this script. Confirms that the "
                     "rebuilt-outcome robustness rows (utc_alignment, excl_extreme_news, "
                     "winsorized, leg_acwx_non_us) are built on the same construct as `main`.",
    "unit_of_analysis": "month", "outcome": "y_fisherz_corr_equity",
    "treatment": "none", "n_observations": int(len(chk)), "n_clusters": None,
    "cluster_level": "none", "fixed_effects": [], "controls": [],
    "n_pre_treatment": n_pre, "n_post_treatment": n_post,
    "coefficients": {"rebuild_correlation": {"estimate": sanity_corr, "se": None,
                                             "t_stat": None, "p_value": None}},
    "diagnostics": {"n_fixed_effect_groups": 0, "df_residual": int(len(chk) - 1)},
}

# ==========================================================================
# write
# ==========================================================================
DROP = {"vcov", "beta", "names", "resid", "data", "V", "yd", "Xd"}


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if k not in DROP}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer, int)) and not isinstance(o, bool):
        return int(o)
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else round(f, 8)
    return o


with open("estimation_results.json", "w") as fh:
    json.dump(clean(results), fh, indent=2)
with open("robustness_results.json", "w") as fh:
    json.dump(clean(robust), fh, indent=2)

print("\n=== estimation_results.json:", list(results.keys()), flush=True)
print("=== robustness_results.json:", list(robust.keys()), flush=True)
print(f"\nHEADLINE tau={tau:.6f} se_cl={se_cl:.6f} p_ri={p_ri:.4f} p_cl="
      f"{m['coefficients']['d_etf_listed']['p_value']:.4f} "
      f"CI=[{m['coefficients']['d_etf_listed']['ci_lower']:.4f},"
      f"{m['coefficients']['d_etf_listed']['ci_upper']:.4f}] "
      f"MDE_ri={mde_ri:.5f} ({mde_ri*conv:.5f} rho) N={m['n']} "
      f"G={smp.asset_id.nunique()} within_R2={m['within_r2']:.5f}", flush=True)
