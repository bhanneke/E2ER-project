"""
Build the coin-month estimation panel for the spot-Bitcoin-ETF comovement paper.

Implements data_dictionary.json. Reads the frozen yfinance extracts in ./data/,
downloads the Ken French daily factors, and writes:
    data/daily_returns.csv        wide daily return panel (NYSE session spine)
    data/coin_month_panel.csv     the estimation panel (T10)
    data/crypto_offday_returns.csv  crypto returns on non-NYSE days (F14 input)
    summary_statistics.json
    figure_spec.json

Clock: 00:00 UTC (r_utc). The 16:00 ET clock (r_ec) is not constructible over the
pre-period -- see blk_01 in the data dictionary.
"""

import io
import json
import math
import os
import warnings
import zipfile
import urllib.request

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")

SAMPLE_START = "2021-01-01"
SAMPLE_END = "2026-08-31"
PRE_START, PRE_END = "2021-01", "2023-07"
DONUT_START, DONUT_END = "2023-08", "2024-01"
POST_START, POST_END = "2024-02", "2026-08"

TREATED = ["BTC"]
EVENTUALLY_TREATED = ["ETH", "SOL", "XRP"]
NEVER_TREATED = ["LTC", "BNB", "ADA", "DOGE", "BCH", "LINK", "AVAX", "DOT", "XLM"]
CRYPTO = TREATED + EVENTUALLY_TREATED + NEVER_TREATED
ALTIDX_CONSTITUENTS = EVENTUALLY_TREATED + NEVER_TREATED  # frozen 2020-12-31, never rebalanced

EQUITY = {"SPY": "px_SPY", "GSPC": "px_GSPC", "QQQ": "px_QQQ", "IWM": "px_IWM",
          "ARKK": "px_ARKK", "XLK": "px_XLK", "ACWX": "px_ACWX",
          "GLD": "px_GLD", "SLV": "px_SLV"}
MACRO = {"VIX": "px_VIX", "MOVE": "px_MOVE", "DXY": "px_DXY", "TNX": "px_TNX"}
SPOT_ETFS = ["IBIT", "FBTC", "GBTC", "ARKB", "BITB", "BTCO", "EZBC", "BRRR", "HODL", "BTCW"]

EXCEPTIONS = []          # build-time findings, surfaced in data_summary.md
SAMPLE_FLOW = []


def note(msg):
    EXCEPTIONS.append(msg)
    print("  [exception] " + msg)


def flow(step, n, dropped):
    SAMPLE_FLOW.append({"step": step, "n": int(n), "dropped": int(dropped)})


def read_px(stem):
    """Read a frozen yfinance extract. Date is taken as the first 10 chars of the
    stamp, which is the ET session date for equities and the UTC date for crypto.
    Parsing the offsets would mix tz-aware and tz-naive objects downstream."""
    path = os.path.join(DATA, stem + ".csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    df["date"] = df["date"].astype(str).str.slice(0, 10)
    df = df[["date", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])          # tz-naive throughout
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------- 1. load prices
print("=" * 70)
print("1. LOADING FROZEN EXTRACTS")
print("=" * 70)

crypto_px, raw_crypto_rows = {}, 0
for a in CRYPTO:
    d = read_px("px_%s_USD" % a)
    if d is None:
        note("crypto extract missing for %s" % a)
        continue
    raw_crypto_rows += len(d)
    crypto_px[a] = d.set_index("date")
print("crypto assets loaded: %d, raw daily bars: %d" % (len(crypto_px), raw_crypto_rows))

equity_px = {}
for a, stem in list(EQUITY.items()) + list(MACRO.items()):
    d = read_px(stem)
    if d is None:
        note("equity/macro extract missing for %s" % a)
        continue
    equity_px[a] = d.set_index("date")
print("equity/macro series loaded: %d" % len(equity_px))

# TNX is quoted at 10x the yield (qa_05)
tnx_last = float(equity_px["TNX"]["close"].dropna().iloc[-1])
tnx_div = 1.0
if tnx_last > 20:
    tnx_div = 10.0
    note("^TNX quoted at 10x scale (last raw value %.2f); divided by 10 per qa_05" % tnx_last)
x_dgs10 = equity_px["TNX"]["close"] / tnx_div
assert x_dgs10.dropna().between(0, 20).all(), "qa_05 failed: 10y yield outside (0,20)"
print("qa_05 PASS: 10y yield in (0,20), scale divisor %.0f" % tnx_div)


# ------------------------------------------------------------ 2. session spine
print()
print("=" * 70)
print("2. NYSE SESSION SPINE")
print("=" * 70)

spine = equity_px["SPY"].index
spine = spine[(spine >= SAMPLE_START) & (spine <= SAMPLE_END)]
print("NYSE sessions in %s..%s: %d  (%s to %s)"
      % (SAMPLE_START, SAMPLE_END, len(spine), spine.min().date(), spine.max().date()))


# --------------------------------------------------------------- 3. Ken French
print()
print("=" * 70)
print("3. KEN FRENCH DAILY FACTORS")
print("=" * 70)


def fetch_french(url, value_cols):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (academic research)"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        blob = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(blob))
    name = [n for n in zf.namelist() if n.lower().endswith((".csv", ".CSV".lower()))][0]
    txt = zf.read(name).decode("latin-1").splitlines()
    rows = []
    for line in txt:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 1 + len(value_cols) and parts[0].isdigit() and len(parts[0]) == 8:
            try:
                vals = [float(p) for p in parts[1:1 + len(value_cols)]]
            except ValueError:
                continue
            rows.append([parts[0]] + vals)
    out = pd.DataFrame(rows, columns=["date"] + value_cols)
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d")
    for c in value_cols:
        out[c] = out[c] / 100.0          # Ken French ships PERCENT per day
    return out.sort_values("date").reset_index(drop=True)


ff_status, ff = "not attempted", None
try:
    ff5 = fetch_french(
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
        "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
        ["mktrf", "smb", "hml", "rmw", "cma", "rf"])
    ff = ff5
    try:
        mom = fetch_french(
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
            "F-F_Momentum_Factor_daily_CSV.zip", ["mom"])
        ff = ff.merge(mom, on="date", how="left")
    except Exception as e:
        note("momentum factor download failed (%s); 5 factors retained" % type(e).__name__)
    ff_status = "downloaded"
    print("Ken French factors: %d daily rows, %s to %s"
          % (len(ff), ff["date"].min().date(), ff["date"].max().date()))
except Exception as e:
    ff_status = "FAILED: %s" % e
    note("Ken French download FAILED (%s). MKT-RF is proxied by the SPY excess "
         "return and rf is set to 0. Every MKT-based number must be relabelled "
         "in the paper; this is a substitution, not the CRSP series." % e)
    print("Ken French download FAILED: %s" % e)

# ------------------------------------------------------------ 4. daily returns
print()
print("=" * 70)
print("4. DAILY RETURNS ON THE UTC CLOCK")
print("=" * 70)

panel = pd.DataFrame(index=spine)
panel.index.name = "date_et"

n_in_window = 0
n_nonpos = 0
for a, d in crypto_px.items():
    s = d["close"]
    s = s[(s.index >= SAMPLE_START) & (s.index <= SAMPLE_END)]
    n_in_window += len(s)
    bad = (~np.isfinite(s)) | (s <= 0)
    n_nonpos += int(bad.sum())
    s = s[~bad]
    r = np.log(s).diff()
    panel["r_" + a] = r.reindex(spine)

# crypto returns on days the NYSE is closed -> kept for the weekend test (dv_17)
offday_rows = []
for a, d in crypto_px.items():
    s = d["close"]
    s = s[(s.index >= SAMPLE_START) & (s.index <= SAMPLE_END)]
    r = np.log(s[(s > 0) & np.isfinite(s)]).diff()
    off = r[~r.index.isin(spine)].dropna()
    offday_rows.append(pd.DataFrame({"date_utc": off.index, "asset_id": a, "r_utc": off.values}))
offday = pd.concat(offday_rows, ignore_index=True)
offday.to_csv(os.path.join(DATA, "crypto_offday_returns.csv"), index=False)
print("crypto off-session (NYSE-closed) returns retained: %d rows" % len(offday))

for a, d in equity_px.items():
    if a in ("VIX", "MOVE", "TNX"):
        panel["lvl_" + a] = d["close"].reindex(spine)
        continue
    s = d["close"]
    panel["r_" + a] = np.log(s[s > 0]).diff().reindex(spine)
panel["lvl_TNX"] = (x_dgs10).reindex(spine)

# equal-weighted altcoin index (frozen constituents, daily rebalanced)
alt_cols = ["r_" + a for a in ALTIDX_CONSTITUENTS if "r_" + a in panel.columns]
panel["r_ALTIDX_EW"] = panel[alt_cols].mean(axis=1, skipna=True)

# factors
if ff is not None:
    f = ff.set_index("date").reindex(spine)
    unmatched = int(f["mktrf"].isna().sum())
    if unmatched:
        note("qa_03: %d of %d NYSE sessions have no Ken French factor row. The daily "
             "factor files trail the extract date by about a month; MKT-based "
             "specifications are truncated to the common window, never padded."
             % (unmatched, len(spine)))
    panel["mktrf"] = f["mktrf"]
    panel["rf"] = f["rf"]
    ff_common_end = f["mktrf"].dropna().index.max()
else:
    panel["rf"] = 0.0
    panel["mktrf"] = panel["r_SPY"]
    ff_common_end = spine.max()

panel["rx_SPY"] = panel["r_SPY"] - panel["rf"]
panel["rx_MKT"] = panel["mktrf"]
panel["r_MKT"] = panel["mktrf"] + panel["rf"]
for a in CRYPTO:
    panel["rx_" + a] = panel["r_" + a] - panel["rf"]
panel["rx_ALTIDX_EW"] = panel["r_ALTIDX_EW"] - panel["rf"]
panel["rx_GLD"] = panel["r_GLD"] - panel["rf"]
panel["rx_SLV"] = panel["r_SLV"] - panel["rf"]

panel.to_csv(os.path.join(DATA, "daily_returns.csv"))

coin_day_cells = int(panel[["r_" + a for a in CRYPTO]].notna().sum().sum())
coin_day_both = int((panel[["r_" + a for a in CRYPTO]].notna()
                     .mul(panel["r_SPY"].notna(), axis=0)).sum().sum())
print("coin-day cells with a crypto return on a NYSE session: %d" % coin_day_cells)
print("...of which the SPY leg is also present: %d" % coin_day_both)

flow("raw crypto daily bars retrieved (13 assets, 2020-12-01 to 2026-09-11)", raw_crypto_rows, 0)
flow("restrict to primary window 2021-01-01..2026-08-31", n_in_window, raw_crypto_rows - n_in_window)
flow("drop missing / non-positive closes", n_in_window - n_nonpos, n_nonpos)
n_after_ret = n_in_window - n_nonpos - len(crypto_px)
flow("first observation per asset lost to differencing", n_after_ret, len(crypto_px))
flow("restrict to NYSE trading sessions (crypto off-days kept separately)",
     coin_day_cells, n_after_ret - coin_day_cells)
flow("require the equity leg present on the same session", coin_day_both,
     coin_day_cells - coin_day_both)


# ------------------------------------------------------ 5. rolling diagnostics
print()
print("=" * 70)
print("5. ROLLING CORRELATIONS AND BETAS (FIGURE-ONLY OBJECTS)")
print("=" * 70)

roll = pd.DataFrame(index=spine)
for w in (30, 60, 90):
    for a in CRYPTO + ["ALTIDX_EW", "GLD", "SLV"]:
        rc = "r_" + a
        xc = "rx_" + a
        if rc not in panel.columns:
            continue
        roll["rho%dd_%s_SPY" % (w, a)] = panel[rc].rolling(w, min_periods=int(w * 0.8)).corr(panel["r_SPY"])
        cov = panel[xc].rolling(w, min_periods=int(w * 0.8)).cov(panel["rx_SPY"])
        var = panel["rx_SPY"].rolling(w, min_periods=int(w * 0.8)).var()
        roll["beta%dd_%s_SPY" % (w, a)] = cov / var
        roll["rho%dd_%s_MKT" % (w, a)] = panel[rc].rolling(w, min_periods=int(w * 0.8)).corr(panel["r_MKT"])
        covm = panel[xc].rolling(w, min_periods=int(w * 0.8)).cov(panel["rx_MKT"])
        varm = panel["rx_MKT"].rolling(w, min_periods=int(w * 0.8)).var()
        roll["beta%dd_%s_MKT" % (w, a)] = covm / varm
roll.to_csv(os.path.join(DATA, "rolling_diagnostics.csv"))
print("rolling series built for windows 30/60/90 on both market legs: %d columns" % roll.shape[1])


# ------------------------------------------------------- 6. coin-month panel
print()
print("=" * 70)
print("6. COIN-MONTH ESTIMATION PANEL")
print("=" * 70)

panel["year_month"] = panel.index.to_period("M").astype(str)

COHORT = {}
for a in TREATED:
    COHORT[a] = "treated_btc"
for a in EVENTUALLY_TREATED:
    COHORT[a] = "eventually_treated"
for a in NEVER_TREATED:
    COHORT[a] = "never_treated"
COHORT["ALTIDX_EW"] = "not_applicable"
COHORT["GLD"] = "placebo"
COHORT["SLV"] = "placebo"

rows = []
n_cells_raw = 0
n_cells_shortmonth = 0
n_cells_rho_guard = 0

for leg in ("SPY", "MKT"):
    rmkt, rxmkt = "r_" + leg, "rx_" + leg
    for a in CRYPTO + ["ALTIDX_EW", "GLD", "SLV"]:
        rc, xc = "r_" + a, "rx_" + a
        if rc not in panel.columns:
            continue
        sub = panel[[rc, xc, rmkt, rxmkt, "year_month"]].dropna()
        for ym, g in sub.groupby("year_month"):
            n = len(g)
            n_cells_raw += 1
            if n < 15:
                n_cells_shortmonth += 1
                continue
            rho = float(np.corrcoef(g[rc], g[rmkt])[0, 1])
            if not np.isfinite(rho) or abs(rho) >= 0.999:
                n_cells_rho_guard += 1
                note("qa_06: |rho| >= 0.999 for %s x %s in %s -- flagged, not clipped" % (a, leg, ym))
                continue
            vmkt = float(np.var(g[rxmkt], ddof=1))
            beta = float(np.cov(g[xc], g[rxmkt], ddof=1)[0, 1] / vmkt) if vmkt > 0 else np.nan
            sd_i = float(np.std(g[rc], ddof=1))
            sd_m = float(np.std(g[rmkt], ddof=1))
            rows.append({
                "asset_id": a,
                "year_month": ym,
                "market_leg": leg,
                "n_days_m": n,
                "rho_m": rho,
                "y_fisherz_corr_equity": float(np.arctanh(rho)),
                "se_fisherz": float(1.0 / math.sqrt(n - 3)),
                "beta_m": beta,
                "rho2_m": rho ** 2,
                "ln_sigma_ratio_m": float(np.log(sd_i / sd_m)) if sd_m > 0 and sd_i > 0 else np.nan,
                "rcov_m": float((g[rc] * g[rmkt]).sum()),
                "sd_i_m": sd_i,
                "sd_mkt_m": sd_m,
                "cohort": COHORT[a],
            })

cm = pd.DataFrame(rows)
cm["ym_period"] = pd.PeriodIndex(cm["year_month"], freq="M")
cm["d_donut"] = ((cm["year_month"] >= DONUT_START) & (cm["year_month"] <= DONUT_END)).astype(int)
cm["d_etf_listed"] = ((cm["asset_id"] == "BTC") & (cm["year_month"] >= POST_START)).astype(int)
cm["d_post_listing_raw"] = ((cm["asset_id"] == "BTC") & (cm["year_month"] >= "2024-01")).astype(int)
cm["d_post_etf"] = (cm["year_month"] >= POST_START).astype(int)
cm["d_anticipation"] = cm["d_donut"]
cm["d_in_headline_sample"] = cm["cohort"].isin(["treated_btc", "never_treated"]).astype(int)
btc_t0 = pd.Period("2024-02", freq="M")
cm["event_k"] = np.where(cm["asset_id"] == "BTC",
                         (cm["ym_period"] - btc_t0).apply(lambda x: x.n), np.nan)
cm["event_k"] = cm["event_k"].clip(-24, 24)
cm = cm.drop(columns=["ym_period"])
cm.to_csv(os.path.join(DATA, "coin_month_panel.csv"), index=False)

# qa_10: no eventually-treated unit in the headline sample
assert set(cm.loc[cm["d_in_headline_sample"] == 1, "cohort"]) <= {"treated_btc", "never_treated"}, \
    "qa_10 failed: eventually-treated unit in the headline sample"
print("qa_10 PASS: headline sample contains only treated_btc and never_treated cohorts")

spy = cm[cm["market_leg"] == "SPY"]
head = spy[(spy["d_in_headline_sample"] == 1) & (spy["d_donut"] == 0)]
print("coin-month cells built (both legs): %d" % len(cm))
print("cells dropped for n_days_m < 15: %d" % n_cells_shortmonth)
print("headline sample (SPY leg, non-donut, treated+never-treated): %d cells, %d coins, %d months"
      % (len(head), head["asset_id"].nunique(), head["year_month"].nunique()))

flow("aggregate to coin-months (SPY leg; unit changes from coin-day to coin-month)",
     len(spy), 0)
flow("drop coin-months with fewer than 15 usable sessions",
     len(spy), n_cells_shortmonth // 2)
flow("headline filter: cohort in {treated_btc, never_treated}",
     int((spy["d_in_headline_sample"] == 1).sum()),
     int((spy["d_in_headline_sample"] == 0).sum()))
flow("drop the donut window 2023m8-2024m1", len(head),
     int((spy["d_in_headline_sample"] == 1).sum()) - len(head))
flow("final estimation sample", len(head), 0)


# ------------------------------------------------- 7. raw pre/post contrast
print()
print("=" * 70)
print("7. RAW PRE/POST CONTRAST (BEFORE ANY ESTIMATION)")
print("=" * 70)


def window_mask(df, lo, hi):
    return (df["year_month"] >= lo) & (df["year_month"] <= hi)


def pooled_daily(a, leg, lo, hi):
    """Pearson correlation and OLS beta on pooled daily returns in a window."""
    m = (panel["year_month"] >= lo) & (panel["year_month"] <= hi)
    g = panel.loc[m, ["r_" + a, "rx_" + a, "r_" + leg, "rx_" + leg]].dropna()
    if len(g) < 30:
        return np.nan, np.nan, 0
    rho = float(np.corrcoef(g["r_" + a], g["r_" + leg])[0, 1])
    v = float(np.var(g["rx_" + leg], ddof=1))
    beta = float(np.cov(g["rx_" + a], g["rx_" + leg], ddof=1)[0, 1] / v)
    return rho, beta, len(g)


contrast = {}
for leg in ("SPY", "MKT"):
    sub = cm[cm["market_leg"] == leg]
    per_asset = {}
    for a in sorted(set(sub["asset_id"])):
        s = sub[sub["asset_id"] == a]
        pre, post = s[window_mask(s, PRE_START, PRE_END)], s[window_mask(s, POST_START, POST_END)]
        if len(pre) < 6 or len(post) < 6:
            continue
        prho_pre, pbeta_pre, npre = pooled_daily(a, leg, PRE_START, PRE_END)
        prho_post, pbeta_post, npost = pooled_daily(a, leg, POST_START, POST_END)
        per_asset[a] = {
            "mean_rho_pre": float(pre["rho_m"].mean()),
            "mean_rho_post": float(post["rho_m"].mean()),
            "d_mean_rho": float(post["rho_m"].mean() - pre["rho_m"].mean()),
            "mean_beta_pre": float(pre["beta_m"].mean()),
            "mean_beta_post": float(post["beta_m"].mean()),
            "d_mean_beta": float(post["beta_m"].mean() - pre["beta_m"].mean()),
            "mean_fisherz_pre": float(pre["y_fisherz_corr_equity"].mean()),
            "mean_fisherz_post": float(post["y_fisherz_corr_equity"].mean()),
            "d_mean_fisherz": float(post["y_fisherz_corr_equity"].mean()
                                    - pre["y_fisherz_corr_equity"].mean()),
            "pooled_daily_rho_pre": prho_pre,
            "pooled_daily_rho_post": prho_post,
            "d_pooled_daily_rho": prho_post - prho_pre,
            "pooled_daily_beta_pre": pbeta_pre,
            "pooled_daily_beta_post": pbeta_post,
            "d_pooled_daily_beta": pbeta_post - pbeta_pre,
            "n_months_pre": int(len(pre)),
            "n_months_post": int(len(post)),
            "n_days_pre": int(npre),
            "n_days_post": int(npost),
        }
    ctrl = [a for a in NEVER_TREATED if a in per_asset]
    ctrl_d_rho = float(np.mean([per_asset[a]["d_mean_rho"] for a in ctrl]))
    ctrl_d_beta = float(np.mean([per_asset[a]["d_mean_beta"] for a in ctrl]))
    ctrl_d_fz = float(np.mean([per_asset[a]["d_mean_fisherz"] for a in ctrl]))
    ctrl_d_prho = float(np.mean([per_asset[a]["d_pooled_daily_rho"] for a in ctrl]))
    ctrl_d_pbeta = float(np.mean([per_asset[a]["d_pooled_daily_beta"] for a in ctrl]))
    b = per_asset.get("BTC", {})
    contrast[leg] = {
        "by_asset": per_asset,
        "control_group_mean": {
            "n_control_coins": len(ctrl),
            "d_mean_rho": ctrl_d_rho, "d_mean_beta": ctrl_d_beta,
            "d_mean_fisherz": ctrl_d_fz,
            "d_pooled_daily_rho": ctrl_d_prho, "d_pooled_daily_beta": ctrl_d_pbeta,
            "mean_rho_pre": float(np.mean([per_asset[a]["mean_rho_pre"] for a in ctrl])),
            "mean_rho_post": float(np.mean([per_asset[a]["mean_rho_post"] for a in ctrl])),
            "mean_beta_pre": float(np.mean([per_asset[a]["mean_beta_pre"] for a in ctrl])),
            "mean_beta_post": float(np.mean([per_asset[a]["mean_beta_post"] for a in ctrl])),
        },
        "did_raw": {
            "rho": b.get("d_mean_rho", np.nan) - ctrl_d_rho,
            "beta": b.get("d_mean_beta", np.nan) - ctrl_d_beta,
            "fisherz": b.get("d_mean_fisherz", np.nan) - ctrl_d_fz,
            "pooled_daily_rho": b.get("d_pooled_daily_rho", np.nan) - ctrl_d_prho,
            "pooled_daily_beta": b.get("d_pooled_daily_beta", np.nan) - ctrl_d_pbeta,
        },
    }
    print("--- market leg: %s ---" % leg)
    print("  BTC   rho  %.4f -> %.4f   (delta %+.4f)"
          % (b.get("mean_rho_pre", float("nan")), b.get("mean_rho_post", float("nan")),
             b.get("d_mean_rho", float("nan"))))
    print("  BTC   beta %.4f -> %.4f   (delta %+.4f)"
          % (b.get("mean_beta_pre", float("nan")), b.get("mean_beta_post", float("nan")),
             b.get("d_mean_beta", float("nan"))))
    print("  ctrl  rho  delta %+.4f   beta delta %+.4f (n=%d coins)"
          % (ctrl_d_rho, ctrl_d_beta, len(ctrl)))
    print("  RAW DiD:  rho %+.4f   beta %+.4f   fisher-z %+.4f"
          % (contrast[leg]["did_raw"]["rho"], contrast[leg]["did_raw"]["beta"],
             contrast[leg]["did_raw"]["fisherz"]))
    for a in ctrl:
        print("     %-5s rho %+.4f -> %+.4f (d %+.4f) | beta %+.4f -> %+.4f (d %+.4f)"
              % (a, per_asset[a]["mean_rho_pre"], per_asset[a]["mean_rho_post"],
                 per_asset[a]["d_mean_rho"], per_asset[a]["mean_beta_pre"],
                 per_asset[a]["mean_beta_post"], per_asset[a]["d_mean_beta"]))
    for a in ["GLD", "SLV", "ETH", "ALTIDX_EW"]:
        if a in per_asset:
            print("     %-9s (non-control) rho %+.4f -> %+.4f (d %+.4f)"
                  % (a, per_asset[a]["mean_rho_pre"], per_asset[a]["mean_rho_post"],
                     per_asset[a]["d_mean_rho"]))


# --------------------------------------------------- 8. ETF turnover + GBTC
print()
print("=" * 70)
print("8. ETF SERIES (TURNOVER, NOT NET FLOW) AND THE GBTC DISCOUNT PROXY")
print("=" * 70)

etf_frames, etf_meta = {}, {}
for t in SPOT_ETFS + ["BITO", "DEFI"]:
    d = read_px("etf_" + t)
    if d is None or d.empty:
        note("ETF extract empty for %s" % t)
        continue
    d = d[(d["date"] >= "2021-01-01") & (d["date"] <= SAMPLE_END)]
    if d.empty:
        note("ETF %s has no bars inside the sample window" % t)
        continue
    etf_frames[t] = d.set_index("date")
    etf_meta[t] = {"first_bar": str(d["date"].min().date()),
                   "last_bar": str(d["date"].max().date()),
                   "n_bars": int(len(d))}
    print("  %-5s first bar %s  last %s  n=%d"
          % (t, etf_meta[t]["first_bar"], etf_meta[t]["last_bar"], etf_meta[t]["n_bars"]))

if "DEFI" not in etf_meta or etf_meta.get("DEFI", {}).get("first_bar", "9999") > "2024-06-01":
    note("DEFI (Hashdex) has no usable 2024 listing history in the yfinance extract; "
         "aggregates cover 10 of the 11 spot funds and are labelled as such.")

# qa_08: no zero-padded pre-listing rows
for t, d in etf_frames.items():
    if t in ("GBTC", "BITO"):
        continue
    assert d.index.min() >= pd.Timestamp("2024-01-10"), \
        "qa_08 failed: %s has bars before the 2024-01-11 listing" % t
print("qa_08 PASS: no spot-ETF bars exist before 2024-01-11; pre-listing rows are absent, not zero")

turn = pd.DataFrame(index=spine)
for t in SPOT_ETFS:
    if t in etf_frames:
        d = etf_frames[t]
        turn[t] = (d["close"] * d["volume"]).reindex(spine)
turn_total = turn.sum(axis=1, min_count=1)
turn_ex_gbtc = turn[[c for c in turn.columns if c != "GBTC"]].sum(axis=1, min_count=1)
cum_turn = (turn_total.fillna(0).cumsum() / 1e9)          # USD bn
cum_turn_ex = (turn_ex_gbtc.fillna(0).cumsum() / 1e9)
cum_turn[turn_total.isna() & (spine < "2024-01-11")] = np.nan
print("aggregate spot-ETF turnover, cumulative to %s: $%.1f bn (ex-GBTC $%.1f bn)"
      % (spine.max().date(), float(cum_turn.iloc[-1]), float(cum_turn_ex.iloc[-1])))

# GBTC discount PROXY: price-per-share relative to BTC, anchored on the post-conversion
# window where the fund traded near NAV. Not the true NAV discount -- no holdings source.
gb = etf_frames["GBTC"]["close"].reindex(spine)
btc = crypto_px["BTC"]["close"].reindex(spine)
ratio = gb / btc
anchor_mask = (spine >= "2024-07-01") & (spine <= "2024-12-31")
anchor = float(ratio[anchor_mask].median())
disc = (ratio / anchor - 1.0) * 100.0
print("GBTC discount proxy: min %.1f%% on %s, value on 2024-01-10 %.1f%%, latest %.1f%%"
      % (float(disc.min()), str(disc.idxmin().date()),
         float(disc.reindex([pd.Timestamp("2024-01-10")]).iloc[0]), float(disc.dropna().iloc[-1])))
note("GBTC discount is a PRICE-RATIO PROXY anchored on the 2024-07..2024-12 near-NAV "
     "window, not a NAV-based discount. No configured source serves daily BTC-per-share, "
     "so the level is anchored, not measured, and the pre-2024 path additionally absorbs "
     "cumulative sponsor-fee drag of roughly 1.5 percent per year.")


# ----------------------------------------------------------- 9. descriptives
print()
print("=" * 70)
print("9. DESCRIPTIVES AND SIDECARS")
print("=" * 70)


def desc(s):
    s = pd.Series(s).dropna()
    if len(s) == 0:
        return {k: None for k in ("mean", "sd", "min", "p25", "median", "p75", "max", "n")}
    return {"mean": float(s.mean()), "sd": float(s.std(ddof=1)), "min": float(s.min()),
            "p25": float(s.quantile(.25)), "median": float(s.median()),
            "p75": float(s.quantile(.75)), "max": float(s.max()), "n": int(len(s))}


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(o, (np.bool_, bool)):
        return int(o)
    return o


pre_head = head[window_mask(head, PRE_START, PRE_END)]
post_head = head[window_mask(head, POST_START, POST_END)]
btc_spy = spy[spy["asset_id"] == "BTC"]

# The excess-return legs require rf, so the Ken French publication lag truncates the
# estimation panel even on the SPY leg. Report the realized end, do not claim the price end.
est_start, est_end = head["year_month"].min(), head["year_month"].max()
price_end_month = str(spine.max().to_period("M"))
if est_end < price_end_month:
    note("Estimation panel ends %s, one or more months before the price panel (%s). Cause: "
         "every cell requires the daily risk-free rate for its excess-return leg, and the Ken "
         "French daily files trail the extract date. The panel is truncated to the common "
         "window, never padded." % (est_end, price_end_month))
print("estimation panel months: %s to %s (%d months); price panel ends %s"
      % (est_start, est_end, head["year_month"].nunique(), price_end_month))

stats = {
    "n_observations": int(len(head)),
    "n_units": int(head["asset_id"].nunique()),
    "n_periods": int(head["year_month"].nunique()),
    "n_periods_per_unit_mean": float(len(head) / head["asset_id"].nunique()),
    "n_daily_observations_crypto": coin_day_both,
    "n_nyse_sessions": int(len(spine)),
    "time_coverage": {
        "start_iso": str(spine.min().date()),
        "end_iso": str(spine.max().date()),
        "n_periods": int(len(spine)),
        "n_months": int(pd.PeriodIndex(panel["year_month"].unique(), freq="M").nunique()),
    },
    "estimation_panel_coverage": {
        "start_month_iso": est_start + "-01",
        "end_month_iso": est_end + "-01",
        "n_months": int(head["year_month"].nunique()),
        "n_coins": int(head["asset_id"].nunique()),
        "price_panel_end_month_iso": price_end_month + "-01",
        "months_lost_to_factor_publication_lag": int(
            (pd.Period(price_end_month, freq="M") - pd.Period(est_end, freq="M")).n),
    },
    "clock": {
        "baseline_used_is_equity_close": 0,
        "equity_close_clock_available_pre_period": 0,
        "utc_clock_available_full_sample": 1,
    },
    "sample_flow": SAMPLE_FLOW,
    "outcome": desc(head["y_fisherz_corr_equity"]),
    "outcome_rho": desc(head["rho_m"]),
    "outcome_beta": desc(head["beta_m"]),
    "outcome_rho2": desc(head["rho2_m"]),
    "ln_sigma_ratio": desc(head["ln_sigma_ratio_m"]),
    "n_days_m": desc(head["n_days_m"]),
    "subsample_pre_2024_01_10": {
        "n_observations": int(len(pre_head)),
        "n_units": int(pre_head["asset_id"].nunique()),
        "n_months": int(pre_head["year_month"].nunique()),
        "outcome": desc(pre_head["y_fisherz_corr_equity"]),
        "rho": desc(pre_head["rho_m"]),
        "beta": desc(pre_head["beta_m"]),
    },
    "subsample_post_2024_01_10": {
        "n_observations": int(len(post_head)),
        "n_units": int(post_head["asset_id"].nunique()),
        "n_months": int(post_head["year_month"].nunique()),
        "outcome": desc(post_head["y_fisherz_corr_equity"]),
        "rho": desc(post_head["rho_m"]),
        "beta": desc(post_head["beta_m"]),
    },
    "by_group": {
        "treated_btc": {
            "n": int(len(btc_spy[(btc_spy["d_donut"] == 0)])),
            "n_units": 1,
            "mean_outcome": float(btc_spy.loc[btc_spy["d_donut"] == 0, "y_fisherz_corr_equity"].mean()),
            "sd_outcome": float(btc_spy.loc[btc_spy["d_donut"] == 0, "y_fisherz_corr_equity"].std(ddof=1)),
            "mean_rho": float(btc_spy.loc[btc_spy["d_donut"] == 0, "rho_m"].mean()),
            "mean_beta": float(btc_spy.loc[btc_spy["d_donut"] == 0, "beta_m"].mean()),
        },
        "never_treated_controls": {
            "n": int(len(head[head["cohort"] == "never_treated"])),
            "n_units": int(head[head["cohort"] == "never_treated"]["asset_id"].nunique()),
            "mean_outcome": float(head.loc[head["cohort"] == "never_treated", "y_fisherz_corr_equity"].mean()),
            "sd_outcome": float(head.loc[head["cohort"] == "never_treated", "y_fisherz_corr_equity"].std(ddof=1)),
            "mean_rho": float(head.loc[head["cohort"] == "never_treated", "rho_m"].mean()),
            "mean_beta": float(head.loc[head["cohort"] == "never_treated", "beta_m"].mean()),
        },
    },
    "raw_contrast": contrast,
    "daily_returns": {
        a: desc(panel["r_" + a]) for a in CRYPTO + ["SPY", "MKT", "QQQ", "IWM", "ARKK",
                                                    "ACWX", "GLD", "SLV", "ALTIDX_EW"]
        if "r_" + a in panel.columns
    },
    "macro": {
        "vix": desc(panel["lvl_VIX"]),
        "move": desc(panel["lvl_MOVE"]),
        "dxy": desc(panel["r_DXY"]) if "r_DXY" in panel.columns else None,
        "dgs10_proxy_tnx": desc(panel["lvl_TNX"]),
    },
    "etf": {
        "n_spot_funds_in_price_panel": int(len([t for t in SPOT_ETFS if t in etf_frames])),
        "n_spot_funds_approved": 11,
        "listing_date_iso_all_spot_eleven": None,
        "cum_turnover_usd_bn": float(cum_turn.iloc[-1]),
        "cum_turnover_ex_gbtc_usd_bn": float(cum_turn_ex.iloc[-1]),
        "gbtc_discount_proxy_pct": {
            "min": float(disc.min()),
            "min_date_iso": str(disc.idxmin().date()),
            "on_2024_01_10": float(disc.reindex([pd.Timestamp("2024-01-10")]).iloc[0]),
            "latest": float(disc.dropna().iloc[-1]),
            "mean_2022": float(disc[(spine >= "2022-01-01") & (spine <= "2022-12-31")].mean()),
            "mean_2023": float(disc[(spine >= "2023-01-01") & (spine <= "2023-12-31")].mean()),
            "mean_post_conversion": float(disc[spine >= "2024-02-01"].mean()),
        },
        "per_fund_first_bar_n_bars": {t: etf_meta[t]["n_bars"] for t in etf_meta},
    },
    "missingness": {
        "crypto_coin_day_cells_expected": int(len(spine) * len(crypto_px)),
        "crypto_coin_day_cells_present": coin_day_cells,
        "crypto_pct_missing": float(100.0 * (1 - coin_day_cells / (len(spine) * len(crypto_px)))),
        "coin_months_dropped_short": int(n_cells_shortmonth // 2),
        "coin_months_dropped_rho_guard": int(n_cells_rho_guard // 2),
        "factor_sessions_unmatched": int(panel["mktrf"].isna().sum()),
    },
    "data_gaps": {
        "allium_configured": 0,
        "fred_configured": 0,
        "etf_net_flows_available": 0,
        "hourly_pre_period_available": 0,
        "n_spot_funds_missing_from_price_panel": int(11 - len([t for t in SPOT_ETFS if t in etf_frames])),
    },
}
with open(os.path.join(ROOT, "summary_statistics.json"), "w") as fh:
    json.dump(clean(stats), fh, indent=2)
print("wrote summary_statistics.json")


# ------------------------------------------------------------- 10. figures
def dyear(idx):
    return [round(float(d.year + (d.dayofyear - 1) / 365.25), 4) for d in idx]


APPROVAL_LO = round(2024.0 + (10 - 1) / 365.25, 4)   # 2024-01-10, SEC approval order
APPROVAL_HI = round(2024.0 + (11 - 1) / 365.25, 4)   # 2024-01-11, listing
DONUT_LO = round(2023.0 + (241 - 1) / 365.25, 4)     # 2023-08-29 Grayscale ruling
DONUT_HI = round(2024.0 + (31 - 1) / 365.25, 4)      # 2024-01-31

# A one-day band on a 5.6-year axis renders as a marked date; the renderer has no
# vertical-line primitive for time_series, so the event is marked this way.
EVENT_BANDS = [
    {"x_start": DONUT_LO, "x_end": DONUT_HI, "label": "Donut (excluded): Grayscale ruling to 2024m1"},
    {"x_start": APPROVAL_LO, "x_end": APPROVAL_HI, "label": "SEC approval 2024-01-10 / listing 2024-01-11"},
]


def series(col, label, src=roll):
    s = src[col].dropna()
    return {"label": label, "x": dyear(s.index), "y": [round(float(v), 5) for v in s.values]}


ctrl_present = [a for a in NEVER_TREATED if "rho90d_%s_SPY" % a in roll.columns]
roll["rho90d_CTRLMEAN_SPY"] = roll[["rho90d_%s_SPY" % a for a in ctrl_present]].mean(axis=1)
roll["beta90d_CTRLMEAN_SPY"] = roll[["beta90d_%s_SPY" % a for a in ctrl_present]].mean(axis=1)

cum_s = cum_turn.dropna()
cum_ex_s = cum_turn_ex.reindex(cum_s.index)
disc_s = disc.dropna()

bar_cats, bar_vals, bar_errs = [], [], []
for lab, a in [("BTC", "BTC")] + [(a, a) for a in ctrl_present]:
    s = spy[spy["asset_id"] == a]
    pre_m = s.loc[window_mask(s, PRE_START, PRE_END), "rho_m"]
    post_m = s.loc[window_mask(s, POST_START, POST_END), "rho_m"]
    bar_cats.append(lab)
    bar_vals.append(round(float(post_m.mean() - pre_m.mean()), 4))
    bar_errs.append(round(float(math.sqrt(post_m.var(ddof=1) / len(post_m)
                                          + pre_m.var(ddof=1) / len(pre_m))), 4))

figures = {"figures": [
    {
        "filename": "fig_rolling_btc_spy.pdf",
        "figure_type": "multi_panel",
        "ncols": 1,
        "label": "fig:rolling_btc_spy",
        "caption_hint": ("Rolling 90-trading-day correlation (Panel A) and OLS beta (Panel B) of "
                         "daily Bitcoin returns on SPY, 2021-2026, on the 00:00 UTC clock. The "
                         "shaded band is the excluded donut window, which runs from the Grayscale "
                         "ruling of 2023-08-29 through 2024-01-31 and contains the 2024-01-10 "
                         "approval. Rolling windows overlap by construction, so a true level shift "
                         "appears as a 90-day ramp rather than a jump; these panels show the time "
                         "path and are not the estimation object."),
        "panels": [
            {"figure_type": "time_series", "title": "Panel A. Rolling 90-day correlation, BTC vs SPY",
             "series": [series("rho90d_BTC_SPY", "BTC-SPY correlation")],
             "shaded_regions": EVENT_BANDS,
             "x_label": "Year", "y_label": "Correlation"},
            {"figure_type": "time_series", "title": "Panel B. Rolling 90-day beta, BTC on SPY",
             "series": [series("beta90d_BTC_SPY", "BTC-SPY beta")],
             "shaded_regions": EVENT_BANDS,
             "x_label": "Year", "y_label": "Beta (dimensionless)"},
        ],
    },
    {
        "filename": "fig_rolling_overlay_controls.pdf",
        "figure_type": "time_series",
        "label": "fig:rolling_overlay",
        "caption_hint": ("Rolling 90-day correlation with SPY: Bitcoin, the equal-weighted mean of "
                         "the nine never-treated control coins, the equal-weighted altcoin index, "
                         "and gold as a placebo. If the post-2024 move in Bitcoin were a common "
                         "risk-asset regime shift, the control mean would move with it."),
        "series": [
            series("rho90d_BTC_SPY", "BTC"),
            series("rho90d_CTRLMEAN_SPY", "Never-treated control mean (9 coins)"),
            series("rho90d_ALTIDX_EW_SPY", "Altcoin index (EW, 12 coins)"),
            series("rho90d_GLD_SPY", "Gold (placebo)"),
        ],
        "shaded_regions": EVENT_BANDS,
        "x_label": "Year", "y_label": "Rolling 90-day correlation with SPY",
    },
    {
        "filename": "fig_prepost_correlation_change.pdf",
        "figure_type": "bar",
        "label": "fig:prepost_change",
        "caption_hint": ("Change in the mean monthly return correlation with SPY between the clean "
                         "pre-period (2021m1-2023m7) and the post-period (2024m2-2026m8), by coin. "
                         "Error bars are the standard error of the difference in period means, "
                         "treating months as independent; they are descriptive and are not the "
                         "clustered inference reported in the estimation tables. The difference "
                         "between the BTC bar and the average control bar is the raw "
                         "difference-in-differences contrast."),
        "categories": bar_cats, "values": bar_vals, "errors": bar_errs,
        "y_label": "Change in correlation with SPY (post minus pre)",
    },
    {
        "filename": "fig_etf_cumulative_turnover.pdf",
        "figure_type": "time_series",
        "label": "fig:etf_turnover",
        "caption_hint": ("Cumulative secondary-market dollar turnover of the ten US spot Bitcoin "
                         "ETPs retrievable on the price side, from the 2024-01-11 listing. This is "
                         "TURNOVER (price times share volume), NOT net creations. No configured "
                         "data source serves fund-level creations, redemptions, shares outstanding "
                         "or NAV, so the flow dose-response design cannot be run; turnover is "
                         "reported because it is what the available data measure. The ex-GBTC line "
                         "removes the fund whose 2024 redemptions dominate the aggregate."),
        "series": [
            {"label": "All 10 spot ETPs (cumulative turnover, $bn)",
             "x": dyear(cum_s.index), "y": [round(float(v), 3) for v in cum_s.values]},
            {"label": "Excluding GBTC ($bn)",
             "x": dyear(cum_ex_s.index), "y": [round(float(v), 3) for v in cum_ex_s.values]},
        ],
        "x_label": "Year", "y_label": "Cumulative dollar turnover (USD bn)",
    },
    {
        "filename": "fig_gbtc_discount.pdf",
        "figure_type": "time_series",
        "label": "fig:gbtc_discount",
        "caption_hint": ("GBTC premium/discount PROXY: the GBTC share price divided by the Bitcoin "
                         "price, normalised to zero on the 2024H2 window in which the converted ETF "
                         "traded near NAV. Because no configured source serves daily BTC-per-share, "
                         "the level is anchored rather than measured, and the pre-2024 path also "
                         "absorbs cumulative sponsor-fee drag of roughly 1.5 percent per year. The "
                         "shape -- a deep discount through 2022-23 closing to parity at conversion "
                         "-- is the object of interest; the level is not."),
        "series": [{"label": "GBTC price/BTC price, anchored (percent)",
                    "x": dyear(disc_s.index), "y": [round(float(v), 3) for v in disc_s.values]}],
        "shaded_regions": EVENT_BANDS,
        "x_label": "Year", "y_label": "Discount proxy (percent, 0 = near NAV)",
    },
]}

with open(os.path.join(ROOT, "figure_spec.json"), "w") as fh:
    json.dump(clean(figures), fh, indent=2)
print("wrote figure_spec.json (%d figures)" % len(figures["figures"]))

print()
print("=" * 70)
print("BUILD EXCEPTIONS (%d)" % len(EXCEPTIONS))
print("=" * 70)
for e in EXCEPTIONS:
    print(" - " + e)

print()
print("SAMPLE FLOW")
for s in SAMPLE_FLOW:
    print("  %-72s n=%9d  dropped=%8d" % (s["step"], s["n"], s["dropped"]))

print()
print("Ken French status: %s" % ff_status)
print("factor panel ends: %s ; price panel ends: %s" % (ff_common_end.date(), spine.max().date()))
print("DONE")
