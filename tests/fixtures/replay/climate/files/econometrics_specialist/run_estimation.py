"""Monthly mean temperature at the Frankfurt grid cell (NASA POWER T2M): diagnostics, models, forecasts.

Reads table `t2m_frankfurt` (loaded by e2er-data nasa_power) from data.db and
writes estimation_results.json in the time-series results schema. The setup
is the frozen one of forecast_design.json: training 2001-01 to 2020-12,
hold-out 2021-01 to 2023-12 (36 months), horizon 12, 95% intervals,
baselines naive and seasonal naive, candidate a linear trend with monthly
means (OLS). Standard library only; no network; no randomness.
"""

import json
import math
import sqlite3

HOLDOUT_START = "2021-01"
HORIZON = 12
LEVEL = 0.95
Z = 1.959963984540054  # two-sided 95% normal quantile
SEASON = 12

con = sqlite3.connect("data.db")
rows = con.execute("SELECT date, T2M FROM t2m_frankfurt WHERE T2M IS NOT NULL ORDER BY date").fetchall()
con.close()
periods = [r[0] for r in rows]
values = [float(r[1]) for r in rows]
cut = periods.index(HOLDOUT_START)
train_p, train_y = periods[:cut], values[:cut]
test_p, test_y = periods[cut:], values[cut:]


def month(p):
    return int(p[5:7])


def mean(xs):
    return sum(xs) / len(xs)


def next_periods(last, n):
    y, m = int(last[:4]), int(last[5:7])
    out = []
    for _ in range(n):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        out.append(f"{y:04d}-{m:02d}")
    return out


# ── diagnostics on the training periods only ─────────────────────────────────


def kpss_level(x):
    """KPSS statistic for level stationarity, Bartlett long-run variance with Schwert's lag rule."""
    n = len(x)
    mu = mean(x)
    e = [v - mu for v in x]
    s, partial = 0.0, []
    for v in e:
        s += v
        partial.append(s)
    lags = int(4 * (n / 100) ** 0.25)
    lrv = sum(v * v for v in e) / n
    for k in range(1, lags + 1):
        w = 1 - k / (lags + 1)
        lrv += 2 * w * sum(e[i] * e[i - k] for i in range(k, n)) / n
    stat = sum(p * p for p in partial) / (n * n * lrv)
    # p-value by linear interpolation in KPSS (1992) Table 1, level case, bounded to [0.01, 0.10].
    table = [(0.347, 0.10), (0.463, 0.05), (0.574, 0.025), (0.739, 0.01)]
    if stat <= table[0][0]:
        p = 0.10
    elif stat >= table[-1][0]:
        p = 0.01
    else:
        for (c0, p0), (c1, p1) in zip(table, table[1:]):
            if c0 <= stat <= c1:
                p = p0 + (p1 - p0) * (stat - c0) / (c1 - c0)
                break
    return stat, p, lags


def mann_kendall(x):
    """Mann-Kendall S, its normal approximation with ties and continuity correction, and Sen's slope."""
    n = len(x)
    s = sum((x[j] > x[i]) - (x[j] < x[i]) for i in range(n) for j in range(i + 1, n))
    counts = {}
    for v in x:
        counts[v] = counts.get(v, 0) + 1
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in counts.values())) / 18
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    slopes = sorted((x[j] - x[i]) / (j - i) for i in range(n) for j in range(i + 1, n))
    m = len(slopes)
    sen = slopes[m // 2] if m % 2 else (slopes[m // 2 - 1] + slopes[m // 2]) / 2
    return s, z, p, sen


monthly_mean = {mm: mean([v for p, v in zip(train_p, train_y) if month(p) == mm]) for mm in range(1, 13)}
deseason = [v - monthly_mean[month(p)] for p, v in zip(train_p, train_y)]
kpss_stat, kpss_p, kpss_lags = kpss_level(deseason)
years = sorted({p[:4] for p in train_p})
annual = [mean([v for p, v in zip(train_p, train_y) if p[:4] == y]) for y in years]
mk_s, mk_z, mk_p, sen = mann_kendall(annual)


# ── models fitted on the training periods ────────────────────────────────────


def solve(a, b):
    """Solve a x = b by Gauss-Jordan elimination with partial pivoting; also return a's inverse."""
    n = len(a)
    m = [row[:] + [b[i]] + [1.0 if j == i else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        d = m[c][c]
        m[c] = [v / d for v in m[c]]
        for r in range(n):
            if r != c and m[r][c] != 0.0:
                f = m[r][c]
                m[r] = [vr - f * vc for vr, vc in zip(m[r], m[c])]
    return [m[i][n] for i in range(n)], [m[i][n + 1 :] for i in range(n)]


def design_row(t, mm):
    """Intercept, linear trend in years (t = months since 2001-01 / 12), dummies for months 2..12."""
    return [1.0, t / 12.0] + [1.0 if mm == k else 0.0 for k in range(2, 13)]


def index_of(p):
    return (int(p[:4]) - 2001) * 12 + int(p[5:7]) - 1


def fit_trend_season(ps, ys):
    x = [design_row(index_of(p), month(p)) for p in ps]
    k = len(x[0])
    xtx = [[sum(r[i] * r[j] for r in x) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * y for r, y in zip(x, ys)) for i in range(k)]
    beta, inv = solve(xtx, xty)
    resid = [y - sum(b * v for b, v in zip(beta, r)) for r, y in zip(x, ys)]
    n = len(ys)
    sigma2 = sum(e * e for e in resid) / (n - k)
    rss = sum(e * e for e in resid)
    aic = n * math.log(rss / n) + 2 * k
    tss = sum((y - mean(ys)) ** 2 for y in ys)
    return {"beta": beta, "inv": inv, "sigma2": sigma2, "aic": aic, "r2": 1 - rss / tss, "n": n, "k": k,
            "train_end": ps[-1]}


def predict_trend_season(fit, ps):
    out = []
    for p in ps:
        r = design_row(index_of(p), month(p))
        f = sum(b * v for b, v in zip(fit["beta"], r))
        lev = sum(r[i] * fit["inv"][i][j] * r[j] for i in range(len(r)) for j in range(len(r)))
        se = math.sqrt(fit["sigma2"] * (1 + lev))
        out.append({"period": p, "forecast": round(f, 4), "lower": round(f - Z * se, 4), "upper": round(f + Z * se, 4)})
    return out


def naive_predictions(ps_train, ys_train, ps):
    diffs = [b - a for a, b in zip(ys_train, ys_train[1:])]
    sd = math.sqrt(sum(d * d for d in diffs) / (len(diffs) - 1))
    last = ys_train[-1]
    return sd * sd, [
        {"period": p, "forecast": round(last, 4), "lower": round(last - Z * sd * math.sqrt(h), 4),
         "upper": round(last + Z * sd * math.sqrt(h), 4)}
        for h, p in enumerate(ps, start=1)
    ]


def seasonal_naive_predictions(ps_train, ys_train, ps):
    sdiff = [ys_train[i] - ys_train[i - SEASON] for i in range(SEASON, len(ys_train))]
    sd = math.sqrt(sum(d * d for d in sdiff) / (len(sdiff) - 1))
    out = []
    for h, p in enumerate(ps, start=1):
        k = (h - 1) // SEASON + 1
        f = ys_train[len(ys_train) - SEASON + (h - 1) % SEASON]
        out.append({"period": p, "forecast": round(f, 4), "lower": round(f - Z * sd * math.sqrt(k), 4),
                    "upper": round(f + Z * sd * math.sqrt(k), 4)})
    return sd * sd, out


def errors(preds, actual):
    e = [a - q["forecast"] for q, a in zip(preds, actual)]
    rmse = math.sqrt(sum(x * x for x in e) / len(e))
    mae = sum(abs(x) for x in e) / len(e)
    cover = sum(q["lower"] <= a <= q["upper"] for q, a in zip(preds, actual)) / len(actual)
    return rmse, mae, cover


# Scale of MASE: in-sample MAE of the seasonal naive method on the training periods.
scale = mean([abs(train_y[i] - train_y[i - SEASON]) for i in range(SEASON, len(train_y))])

naive_s2, naive_pred = naive_predictions(train_p, train_y, test_p)
snaive_s2, snaive_pred = seasonal_naive_predictions(train_p, train_y, test_p)
ts_fit = fit_trend_season(train_p, train_y)
ts_pred = predict_trend_season(ts_fit, test_p)

out_of_sample = {}
for key, model, preds in (
    ("naive_test", "naive", naive_pred),
    ("seasonal_naive_test", "seasonal_naive", snaive_pred),
    ("trend_season_test", "trend_season", ts_pred),
):
    rmse, mae, cover = errors(preds, test_y)
    out_of_sample[key] = {
        "model": model,
        "train_end": train_p[-1],
        "test_start": test_p[0],
        "test_end": test_p[-1],
        "n_test": len(test_p),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "mase": round(mae / scale, 4),
        "coverage": round(cover, 4),
        "predictions": preds,
    }

# The forecast beyond the data: the same model refitted on every period.
full_fit = fit_trend_season(periods, values)
future = next_periods(periods[-1], HORIZON)
forecast_points = predict_trend_season(full_fit, future)

results = {
    "result_kind": "timeseries",
    "series": {
        "name": "monthly mean 2 m air temperature, NASA POWER grid cell at 50.11 N, 8.68 E (Frankfurt am Main)",
        "frequency": "monthly",
        "start": periods[0],
        "end": periods[-1],
        "n_observations": len(periods),
        "unit": "degrees C",
        "n_train": len(train_p),
        "n_holdout": len(test_p),
    },
    "diagnostics": {
        "kpss_level": {
            "test": "KPSS, level stationarity, monthly means removed",
            "statistic": round(kpss_stat, 4),
            "p_value": round(kpss_p, 4),
            "lags": kpss_lags,
            "sample_end": train_p[-1],
            "note": "p-value interpolated in the KPSS table and bounded to [0.01, 0.10]",
        },
        "mann_kendall_annual": {
            "test": "Mann-Kendall on annual means, normal approximation with continuity correction",
            "statistic": round(mk_z, 4),
            "s": mk_s,
            "p_value": round(mk_p, 4),
            "sen_slope": round(sen, 4),
            "sen_slope_per_decade": round(10 * sen, 4),
            "n_years": len(annual),
            "sample_end": train_p[-1],
        },
    },
    "models": {
        "naive": {"model": "naive (last training value)", "train_end": train_p[-1], "fit": {"sigma2": round(naive_s2, 4)}},
        "seasonal_naive": {"model": "seasonal naive (same month of the last training year)", "train_end": train_p[-1],
                           "fit": {"sigma2": round(snaive_s2, 4)}},
        "trend_season": {
            "model": "linear trend plus monthly means (OLS)",
            "train_end": ts_fit["train_end"],
            "fit": {"sigma2": round(ts_fit["sigma2"], 4), "aic": round(ts_fit["aic"], 2), "r_squared": round(ts_fit["r2"], 4)},
            "parameters": {"trend_per_decade": {"estimate": round(10 * ts_fit["beta"][1], 4),
                                                 "se": round(10 * math.sqrt(ts_fit["sigma2"] * ts_fit["inv"][1][1]), 4)}},
        },
        "trend_season_full": {
            "model": "linear trend plus monthly means (OLS), refitted on every period for the forecast beyond the data",
            "train_end": full_fit["train_end"],
            "fit": {"sigma2": round(full_fit["sigma2"], 4), "aic": round(full_fit["aic"], 2), "r_squared": round(full_fit["r2"], 4)},
            "parameters": {"trend_per_decade": {"estimate": round(10 * full_fit["beta"][1], 4),
                                                 "se": round(10 * math.sqrt(full_fit["sigma2"] * full_fit["inv"][1][1]), 4)}},
        },
    },
    "out_of_sample": out_of_sample,
    "forecasts": {
        "trend_season_2024": {"model": "trend_season_full", "horizon": HORIZON, "interval_level": LEVEL,
                              "points": forecast_points},
    },
    "mase_scale": round(scale, 4),
    "figures": ["fig_series.pdf", "fig_holdout.pdf"],
}

with open("estimation_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
