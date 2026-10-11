"""Build the exoplanet replay fixture: a synthetic dataset and the files computed from it.

Test-only. The data are SYNTHETIC (drawn from a seeded generator below), shaped
loosely like transit-survey planets: two small-planet groups around 1.4 and 2.6
Earth radii, a few giants, orbital periods log-uniform from 0.8 to 300 days.
They are not NASA Exoplanet Archive data and describe no real planet.

Writes, from the generator and the recorded analysis script:

    inputs/data/exoplanets.csv                       the researcher's data file
    files/data_analyst/data.db                       the file loaded as table `exoplanets`
    files/data_analyst/summary_statistics.json       computed here
    files/data_analyst/figure_spec.json              computed here
    files/econometrics_specialist/estimation_results.json   by running run_estimation.py

Run from anywhere: ``python tests/fixtures/replay/exoplanet/make_fixture.py``.
The hand-written files (plans, reviews, the draft) are not touched.
"""

from __future__ import annotations

import csv
import json
import math
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
N = 60
SEED = 20261011


def planets() -> list[dict]:
    rng = random.Random(SEED)
    rows = []
    for i in range(N):
        period = round(math.exp(rng.uniform(math.log(0.8), math.log(300.0))), 3)
        u = rng.random()
        if u < 0.42:
            radius = rng.gauss(1.4, 0.25)
        elif u < 0.9:
            radius = rng.gauss(2.6, 0.45)
        else:
            radius = rng.gauss(11.0, 1.5)
        radius = round(max(0.6, radius), 2)
        method = "Transit" if rng.random() < 0.75 else "Radial velocity"
        year = rng.randint(2009, 2024)
        rows.append(
            {
                "planet": f"SYN-{i + 1:03d} b",
                "period_days": period,
                "radius_earth": radius,
                "discovery_method": method,
                "discovery_year": year,
            }
        )
    return rows


def quantile(sorted_vals: list[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy's default)."""
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def describe(vals: list[float]) -> dict:
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
    }


def main() -> None:
    rows = planets()
    data_dir = HERE / "inputs" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "exoplanets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    analyst = HERE / "files" / "data_analyst"
    analyst.mkdir(parents=True, exist_ok=True)
    db = analyst / "data.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE exoplanets (planet TEXT, period_days REAL, radius_earth REAL, "
        "discovery_method TEXT, discovery_year INTEGER)"
    )
    con.executemany(
        "INSERT INTO exoplanets VALUES (?, ?, ?, ?, ?)",
        [(r["planet"], r["period_days"], r["radius_earth"], r["discovery_method"], r["discovery_year"]) for r in rows],
    )
    con.commit()
    con.close()

    radius = [r["radius_earth"] for r in rows]
    period = [r["period_days"] for r in rows]
    summary = {
        "n_observations": N,
        "n_units": N,
        "time_coverage": {"start_year": min(r["discovery_year"] for r in rows), "end_year": max(r["discovery_year"] for r in rows)},
        "outcome": describe(radius),
        "period_days": describe(period),
        "missing": {"radius_earth": 0, "period_days": 0},
        "sample_flow": [{"step": "all rows of data/exoplanets.csv", "rows": N, "dropped": 0}],
    }
    (analyst / "summary_statistics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # The analysis, by the recorded script, in a folder of its own.
    script = HERE / "files" / "econometrics_specialist" / "run_estimation.py"
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(db, Path(tmp) / "data.db")
        shutil.copy(script, Path(tmp) / "run_estimation.py")
        subprocess.run([sys.executable, "run_estimation.py"], cwd=tmp, check=True)
        results = json.loads((Path(tmp) / "estimation_results.json").read_text(encoding="utf-8"))
    (HERE / "files" / "econometrics_specialist" / "estimation_results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )

    figures = {
        "figures": [
            {
                "filename": "fig_radius_period.pdf",
                "figure_type": "scatter",
                "label": "fig:radius_period",
                "caption_hint": "Radius against orbital period, by discovery method (synthetic sample)",
                "x": period,
                "y": radius,
                "groups": [r["discovery_method"] for r in rows],
                "log_x": True,
                "log_y": True,
                "x_label": "Orbital period (days)",
                "y_label": "Radius (Earth radii)",
            },
            {
                "filename": "fig_radius_hist.pdf",
                "figure_type": "histogram",
                "label": "fig:radius_hist",
                "caption_hint": "Planets by radius bin (synthetic sample)",
                "bins": results["distributions"]["radius"]["bins"],
                "log_x": True,
                "x_label": "Radius (Earth radii)",
                "y_label": "Planets",
            },
        ]
    }
    (analyst / "figure_spec.json").write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
