"""Callaway and Sant'Anna (2021) difference-in-differences on the panel in data.db.

Reads table `panel` (iso3, year, outcome) and table `adoption` (iso3, first_year;
NULL for a unit never treated). Writes estimation_results.json:

- main: the overall ATT (cohort-size weighted average of the post-treatment
  group-time effects), never-treated comparison group;
- event_study: effects by event time -5 to 5, universal base period g - 1
  (event time -1 is the reference and 0 by construction);
- pre_trends: Wald test that the pre-treatment effects are jointly zero, with
  the bootstrap covariance;
- placebo: treatment moved 3 years earlier, on pre-treatment years only;
- sensitivity: the not-yet-treated comparison group, and a conservative
  relative-magnitudes bound on the effect at event time 0 (Rambachan and Roth 2023).

Inference: bootstrap over units (999 draws, seed 20261011); t from estimate / se,
p from Student's t with n_clusters - 1 degrees of freedom.
"""

from __future__ import annotations

import json
import sqlite3

import numpy as np
from scipy import stats

SEED = 20261011
DRAWS = 999
WINDOW = range(-5, 6)


def load():
    con = sqlite3.connect("data.db")
    panel = con.execute("SELECT iso3, year, outcome FROM panel").fetchall()
    adoption = dict(con.execute("SELECT iso3, first_year FROM adoption").fetchall())
    con.close()
    units = sorted({u for u, _y, _o in panel})
    years = sorted({y for _u, y, _o in panel})
    ui = {u: i for i, u in enumerate(units)}
    yi = {y: j for j, y in enumerate(years)}
    Y = np.full((len(units), len(years)), np.nan)
    for u, y, o in panel:
        Y[ui[u], yi[y]] = o
    G = np.array([adoption.get(u) or np.inf for u in units], dtype=float)
    return units, np.array(years), Y, G


def att_gt(Y, G, years, g, t, b, comparison):
    """ATT(g, t) against base period b; None when a period is outside the panel or no unit compares."""
    if t not in years or b not in years:
        return None
    jt, jb = int(np.where(years == t)[0][0]), int(np.where(years == b)[0][0])
    treated = G == g
    if comparison == "never":
        control = np.isinf(G)
    else:
        control = (G > max(t, b)) & (G != g)
    if not treated.any() or not control.any():
        return None
    d = Y[:, jt] - Y[:, jb]
    return float(np.nanmean(d[treated]) - np.nanmean(d[control]))


def estimates(Y, G, years, comparison="never", shift=0, last_year=None):
    """Overall ATT and event-time effects. ``shift`` moves every cohort earlier (placebo);
    ``last_year`` keeps only earlier years (each cohort's own pre-treatment years for the placebo)."""
    cohorts = sorted(set(G[np.isfinite(G)]))
    sizes = {g: int((G == g).sum()) for g in cohorts}
    cells, by_e = [], {e: [] for e in WINDOW}
    for g in cohorts:
        pg = g - shift
        top = (g - 1) if last_year == "own" else years.max()
        for t in years:
            if t > top:
                continue
            b = pg - 1
            a = att_gt(Y, G, years, g, t, b, comparison)
            if a is None:
                continue
            e = int(t - pg)
            if e in by_e:
                by_e[e].append((a, sizes[g]))
            if t >= pg:
                cells.append((a, sizes[g]))
    overall = sum(a * n for a, n in cells) / sum(n for _a, n in cells) if cells else None
    path = {e: sum(a * n for a, n in v) / sum(n for _a, n in v) for e, v in by_e.items() if v}
    return overall, path


def bootstrap(Y, G, years, **kw):
    rng = np.random.default_rng(SEED)
    n = Y.shape[0]
    overall, path = [], []
    for _ in range(DRAWS):
        idx = rng.integers(0, n, n)
        o, p = estimates(Y[idx], G[idx], years, **kw)
        overall.append(o)
        path.append(p)
    return np.array(overall, dtype=float), path


def coef(est, se, df):
    t = est / se
    p = 2 * stats.t.sf(abs(t), df)
    return {
        "estimate": round(est, 4),
        "se": round(se, 4),
        "t_stat": round(t, 4),
        "p_value": round(float(p), 4),
        "df": df,
        "ci_lower": round(est - 1.96 * se, 4),
        "ci_upper": round(est + 1.96 * se, 4),
    }


def main():
    units, years, Y, G = load()
    n_units = len(units)
    df = n_units - 1
    overall, path = estimates(Y, G, years)
    boot_o, boot_p = bootstrap(Y, G, years)
    se_o = float(np.nanstd(boot_o, ddof=1))

    periods = []
    for e in sorted(path):
        if e == -1:
            periods.append({"relative_period": -1, "estimate": 0.0, "se": 0.0, "ci_lower": 0.0, "ci_upper": 0.0})
            continue
        draws = np.array([p.get(e, np.nan) for p in boot_p], dtype=float)
        se = float(np.nanstd(draws, ddof=1))
        periods.append(
            {
                "relative_period": e,
                "estimate": round(path[e], 4),
                "se": round(se, 4),
                "ci_lower": round(path[e] - 1.96 * se, 4),
                "ci_upper": round(path[e] + 1.96 * se, 4),
            }
        )

    leads = [e for e in sorted(path) if e < -1]
    theta = np.array([path[e] for e in leads])
    draws = np.array([[p.get(e, np.nan) for e in leads] for p in boot_p], dtype=float)
    draws = draws[~np.isnan(draws).any(axis=1)]
    V = np.cov(draws, rowvar=False)
    wald = float(theta @ np.linalg.solve(V, theta))
    p_pre = float(stats.chi2.sf(wald, len(leads)))

    plac, _ = estimates(Y, G, years, shift=3, last_year="own")
    boot_plac = [estimates(Y[i], G[i], years, shift=3, last_year="own")[0] for i in _indices(n_units)]
    se_plac = float(np.nanstd(np.array(boot_plac, dtype=float), ddof=1))

    nyt, _ = estimates(Y, G, years, comparison="notyet")
    boot_nyt = [estimates(Y[i], G[i], years, comparison="notyet")[0] for i in _indices(n_units)]
    se_nyt = float(np.nanstd(np.array(boot_nyt, dtype=float), ddof=1))

    # Conservative relative-magnitudes bound at event time 0: the largest change between
    # consecutive pre-period effects (the reference included) times Mbar = 1.
    pre_path = [path[e] for e in sorted(path) if e < 0]
    m = max(abs(b - a) for a, b in zip(pre_path, pre_path[1:]))
    e0 = next(p for p in periods if p["relative_period"] == 0)

    results = {
        "main": {
            "specification": "Callaway-Sant'Anna overall ATT, never-treated comparison group, universal base period",
            "estimator": "callaway_santanna",
            "hypothesis": "H1",
            "n_observations": int(np.isfinite(Y).sum()),
            "n_clusters": n_units,
            "cluster_level": "iso3",
            "fixed_effects": [],
            "controls": [],
            "inference": f"bootstrap over units, {DRAWS} draws, seed {SEED}",
            "coefficients": {"att": coef(overall, se_o, df)},
        },
        "event_study": {
            "estimator": "callaway_santanna",
            "reference_period": -1,
            "base": "universal (g - 1)",
            "periods": periods,
        },
        "pre_trends": {
            "test": "Wald test that the pre-treatment event-time effects are jointly zero (bootstrap covariance)",
            "statistic": round(wald, 4),
            "df": len(leads),
            "p_value": round(p_pre, 4),
            "n_pre_periods": len(leads),
        },
        "placebo": {
            "fake_date_minus_3": {
                "description": "treatment moved 3 years earlier, each cohort's post-treatment years dropped",
                "estimate": round(plac, 4),
                "se": round(se_plac, 4),
                "p_value": round(float(2 * stats.t.sf(abs(plac / se_plac), df)), 4),
            }
        },
        "sensitivity": {
            "not_yet_treated": {
                "method": "comparison group: not yet treated",
                "estimate": round(nyt, 4),
                "se": round(se_nyt, 4),
                "ci_lower": round(nyt - 1.96 * se_nyt, 4),
                "ci_upper": round(nyt + 1.96 * se_nyt, 4),
            },
            "honest_did_rm": {
                "method": "Rambachan-Roth relative magnitudes, conservative bound at event time 0, Mbar = 1",
                "mbar": 1.0,
                "max_pre_change": round(m, 4),
                "estimate": e0["estimate"],
                "se": e0["se"],
                "ci_lower": round(e0["estimate"] - m - 1.96 * e0["se"], 4),
                "ci_upper": round(e0["estimate"] + m + 1.96 * e0["se"], 4),
            },
        },
    }
    with open("estimation_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def _indices(n):
    rng = np.random.default_rng(SEED)
    for _ in range(DRAWS):
        yield rng.integers(0, n, n)


if __name__ == "__main__":
    main()
