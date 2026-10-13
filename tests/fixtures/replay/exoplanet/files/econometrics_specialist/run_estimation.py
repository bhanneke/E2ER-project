"""Descriptive analysis of the planet sample: summary statistics, distributions, one rank correlation.

Reads table `exoplanets` from data.db (loaded from data/exoplanets.csv) and
writes estimation_results.json in the descriptive results schema. Standard
library only; no network.
"""

import json
import math
import sqlite3

con = sqlite3.connect("data.db")
rows = con.execute("SELECT period_days, radius_earth, discovery_method FROM exoplanets").fetchall()
con.close()

period = [float(r[0]) for r in rows if r[0] is not None]
radius = [float(r[1]) for r in rows if r[1] is not None]
methods = [r[2] for r in rows]
n = len(rows)


def quantile(sorted_vals, q):
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def describe(vals, unit):
    s = sorted(vals)
    mean = sum(s) / len(s)
    sd = math.sqrt(sum((v - mean) ** 2 for v in s) / (len(s) - 1))
    return {
        "n": len(s),
        "mean": round(mean, 4),
        "sd": round(sd, 4),
        "min": s[0],
        "p25": round(quantile(s, 0.25), 4),
        "median": round(quantile(s, 0.5), 4),
        "p75": round(quantile(s, 0.75), 4),
        "max": s[-1],
        "unit": unit,
    }


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy)


edges = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 10.0, 16.0]
bins = []
for lo, hi in zip(edges, edges[1:]):
    bins.append({"lower": lo, "upper": hi, "count": sum(1 for v in radius if lo <= v < hi)})

counts = {}
for m in methods:
    counts[m] = counts.get(m, 0) + 1

small = [v for v in radius if v < 4.0]
gap = sum(1 for v in small if 1.5 <= v < 2.0)

results = {
    "result_kind": "descriptive",
    "sample": {"n_observations": n, "unit": "planet", "source": "data/exoplanets.csv (synthetic)"},
    "statistics": {
        "radius_earth": describe(radius, "Earth radii"),
        "period_days": describe(period, "days"),
        "transit": {"n": n, "count": counts.get("Transit", 0), "share": round(counts.get("Transit", 0) / n, 4)},
    },
    "distributions": {
        "radius": {"variable": "radius_earth", "n": len(radius), "bins": bins},
        "method": {
            "variable": "discovery_method",
            "n": n,
            "categories": [{"category": k, "count": v} for k, v in sorted(counts.items())],
        },
    },
    "associations": {
        "radius_period": {
            "x": "period_days",
            "y": "radius_earth",
            "method": "spearman",
            "estimate": round(pearson(ranks(period), ranks(radius)), 4),
            "n": n,
        }
    },
    "small_planets": {"n_below_4_earth_radii": len(small), "n_between_1_5_and_2": gap},
    "figures": ["fig_radius_period.pdf", "fig_radius_hist.pdf"],
}

with open("estimation_results.json", "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=2)
    fh.write("\n")
