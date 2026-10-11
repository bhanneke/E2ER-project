"""Spatial autocorrelation of the regional rate: Moran's I with permutation inference, LISA clusters.

Reads table `regions` (id, name, geometry as GeoJSON text, EPSG:4326) and table
`regional` (geo, year, rate) from data.db. Units: the regions with a rate in
2023 and a geometry. Writes:

- spatial_units.csv: id, rate, lisa (the unit's LISA category);
- spatial_weights.csv: queen contiguity (regions sharing a boundary vertex), row-standardised;
- spatial_weights_knn4.csv: the 4 nearest regions by centroid distance, row-standardised;
- estimation_results.json: the spatial results (result_kind "spatial").

Inference by permutation: 999 random permutations of the values over the
regions (seed 20261011); pseudo p-values two-sided around E[I] = -1/(n - 1).
LISA (Anselin 1995): conditional permutations, 999 per region, significance 0.05.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3

import numpy as np

SEED = 20261011
PERMS = 999
YEAR = 2023


def load():
    con = sqlite3.connect("data.db")
    geoms = {i: json.loads(g) for i, g in con.execute("SELECT id, geometry FROM regions")}
    rates = dict(con.execute("SELECT geo, rate FROM regional WHERE year = ?", (YEAR,)).fetchall())
    con.close()
    ids = sorted(u for u in rates if u in geoms and rates[u] is not None)
    return ids, np.array([rates[u] for u in ids], dtype=float), {u: geoms[u] for u in ids}


def rings(g):
    return [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]


def queen(ids, geoms):
    owners = {}
    for u in ids:
        for poly in rings(geoms[u]):
            for ring in poly:
                for x, y in ring:
                    owners.setdefault((round(x, 6), round(y, 6)), set()).add(u)
    nb = {u: set() for u in ids}
    for us in owners.values():
        for a in us:
            nb[a] |= us - {a}
    return nb


def centroid(g):
    """Area-weighted centroid of the exterior rings (planar, in degrees: fine for a small grid)."""
    ax = ay = aa = 0.0
    for poly in rings(g):
        ring = poly[0]
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            c = x0 * y1 - x1 * y0
            aa += c
            ax += (x0 + x1) * c
            ay += (y0 + y1) * c
    return ax / (3 * aa), ay / (3 * aa)


def knn(ids, geoms, k):
    cs = {u: centroid(geoms[u]) for u in ids}

    def km(a, b):
        (x0, y0), (x1, y1) = cs[a], cs[b]
        dx = (x1 - x0) * 111.32 * math.cos(math.radians((y0 + y1) / 2))
        return math.hypot(dx, (y1 - y0) * 110.57)

    return {u: set(sorted((v for v in ids if v != u), key=lambda v: (km(u, v), v))[:k]) for u in ids}


def matrix(ids, nb):
    idx = {u: i for i, u in enumerate(ids)}
    W = np.zeros((len(ids), len(ids)))
    for u, vs in nb.items():
        for v in vs:
            W[idx[u], idx[v]] = 1.0
    rows = W.sum(axis=1, keepdims=True)
    return np.divide(W, rows, out=np.zeros_like(W), where=rows > 0)


def moran(x, W):
    z = x - x.mean()
    return len(x) / W.sum() * (z @ W @ z) / (z @ z)


def moran_test(x, W, rng):
    n = len(x)
    i_obs = moran(x, W)
    e = -1 / (n - 1)
    sims = np.array([moran(rng.permutation(x), W) for _ in range(PERMS)])
    p = (1 + np.sum(np.abs(sims - e) >= abs(i_obs - e))) / (PERMS + 1)
    z = (i_obs - sims.mean()) / sims.std(ddof=1)
    return i_obs, e, z, p


def lisa(x, W, rng):
    n = len(x)
    z = (x - x.mean()) / x.std()
    lag = W @ z
    local = z * lag
    cats = []
    for i in range(n):
        others = np.delete(z, i)
        w = np.delete(W[i], i)
        sims = np.array([z[i] * (w @ rng.permutation(others)) for _ in range(PERMS)])
        p = (1 + np.sum(np.abs(sims) >= abs(local[i]))) / (PERMS + 1)
        if p >= 0.05:
            cats.append("ns")
        else:
            cats.append(("H" if z[i] > 0 else "L") + ("H" if lag[i] > 0 else "L"))
    return cats


def write_weights(path, ids, W):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from", "to", "weight"])
        for i, u in enumerate(ids):
            for j, v in enumerate(ids):
                if W[i, j] > 0:
                    w.writerow([u, v, repr(float(W[i, j]))])


def main():
    rng = np.random.default_rng(SEED)
    ids, x, geoms = load()
    Wq = matrix(ids, queen(ids, geoms))
    Wk = matrix(ids, knn(ids, geoms, 4))
    iq, e, zq, pq = moran_test(x, Wq, rng)
    ik, _, zk, pk = moran_test(x, Wk, rng)
    cats = lisa(x, Wq, rng)
    write_weights("spatial_weights.csv", ids, Wq)
    write_weights("spatial_weights_knn4.csv", ids, Wk)
    with open("spatial_units.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "rate", "lisa"])
        for u, v, c in zip(ids, x, cats):
            w.writerow([u, repr(float(v)), c])
    s = np.sort(x)
    results = {
        "result_kind": "spatial",
        "units": {"type": "region (synthetic grid)", "n_units": len(ids), "id_field": "id", "file": "spatial_units.csv",
                  "crs": "EPSG:4326", "year": YEAR},
        "variables": {"rate": {"n": len(ids), "mean": round(float(x.mean()), 4), "sd": round(float(x.std(ddof=1)), 4),
                               "min": round(float(s[0]), 4), "median": round(float(np.median(x)), 4),
                               "max": round(float(s[-1]), 4)}},
        "spatial_statistics": {
            "moran_rate_queen": {"statistic": "morans_i", "variable": "rate",
                                 "weights": "queen contiguity, row-standardised", "weights_file": "spatial_weights.csv",
                                 "estimate": round(float(iq), 4), "expected": round(e, 6), "z": round(float(zq), 4),
                                 "p_value": round(float(pq), 4), "p_value_method": "permutation",
                                 "n_permutations": PERMS, "alternative": "two-sided"},
            "moran_rate_knn4": {"statistic": "morans_i", "variable": "rate",
                                "weights": "4 nearest neighbours, row-standardised",
                                "weights_file": "spatial_weights_knn4.csv",
                                "estimate": round(float(ik), 4), "expected": round(e, 6), "z": round(float(zk), 4),
                                "p_value": round(float(pk), 4), "p_value_method": "permutation",
                                "n_permutations": PERMS, "alternative": "two-sided"},
        },
        "clusters": {k: {"count": cats.count(k)} for k in ("HH", "LL", "HL", "LH", "ns")},
        "maps": [
            {"id": "map_rate", "variable": "rate", "classification": "quantiles", "classes": 5,
             "legend_label": "Rate 2023 (%)"},
            {"id": "map_lisa", "variable": "lisa", "classification": "categories",
             "legend_label": "LISA cluster (queen, p < 0.05)",
             "categories": {"HH": {"label": "High-high", "color": "#b2182b"},
                            "LL": {"label": "Low-low", "color": "#2166ac"},
                            "HL": {"label": "High-low", "color": "#f4a582"},
                            "LH": {"label": "Low-high", "color": "#92c5de"},
                            "ns": {"label": "Not significant", "color": "#d9d9d9"}}},
        ],
    }
    with open("estimation_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
