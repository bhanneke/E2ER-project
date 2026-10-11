"""Build the DiD replay fixtures: a synthetic staggered-adoption panel and the files computed from it.

Test-only. The data are SYNTHETIC (drawn from a seeded generator below): 24
units ("countries" S01 to S24, no real country) observed 2000 to 2015; 6 adopt a
policy in 2006, 6 in 2010, 12 never. The outcome has a unit level, a common
trend, noise, and an effect of -3 from the adoption year on.

Two scenarios are written:

    did/            parallel trends hold: the run passes every check;
    did-pretrend/   the adopters' outcome drifts upwards before adoption, so the
                    pre-trends test rejects; its results carry no Rambachan-Roth
                    bound (removed after the script ran), so the did_results
                    check stops the run.

Into each, from the generator and the recorded analysis script:

    inputs/data/panel.csv, inputs/data/adoption.csv     the researcher's files (did/ only)
    files/data_analyst/data.db                          tables `panel` and `adoption`
    files/data_analyst/summary_statistics.json, figure_spec.json
    files/econometrics_specialist/estimation_results.json   by running run_estimation.py

Run: ``python tests/fixtures/replay/did/make_fixture.py``. The hand-written
files (plans, reviews, the draft) are not touched.
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
PRETREND = HERE.parent / "did-pretrend"
SEED = 20261011
YEARS = list(range(2000, 2016))
COHORTS = {2006: 6, 2010: 6}
N_UNITS = 24
EFFECT = -3.0


def panel(drift: float) -> tuple[list[dict], dict[str, int | None]]:
    rng = random.Random(SEED)
    units = [f"S{i + 1:02d}" for i in range(N_UNITS)]
    adoption: dict[str, int | None] = {}
    k = 0
    for year, n in COHORTS.items():
        for u in units[k : k + n]:
            adoption[u] = year
        k += n
    for u in units[k:]:
        adoption[u] = None
    rows = []
    for u in units:
        level = rng.gauss(50, 5)
        g = adoption[u]
        for y in YEARS:
            out = level + 0.5 * (y - 2000) + rng.gauss(0, 0.6)
            if g is not None and y >= g:
                out += EFFECT
            if g is not None and y < g:
                out += drift * (y - g)  # rises towards the adoption year: a pre-trend
            rows.append({"iso3": u, "year": y, "outcome": round(out, 3)})
    return rows, adoption


def describe(vals: list[float]) -> dict:
    s = sorted(vals)
    mean = sum(s) / len(s)
    sd = math.sqrt(sum((v - mean) ** 2 for v in s) / (len(s) - 1))
    return {"n": len(s), "mean": round(mean, 4), "sd": round(sd, 4), "min": s[0], "max": s[-1]}


def build(root: Path, drift: float, inputs: bool, drop_sensitivity: tuple[str, ...] = ()) -> None:
    rows, adoption = panel(drift)
    if inputs:
        data = root / "inputs" / "data"
        data.mkdir(parents=True, exist_ok=True)
        with (data / "panel.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["iso3", "year", "outcome"])
            w.writeheader()
            w.writerows(rows)
        with (data / "adoption.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["iso3", "first_year"])
            for u, g in adoption.items():
                w.writerow([u, "" if g is None else g])

    analyst = root / "files" / "data_analyst"
    analyst.mkdir(parents=True, exist_ok=True)
    db = analyst / "data.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE panel (iso3 TEXT, year INTEGER, outcome REAL)")
    con.executemany("INSERT INTO panel VALUES (?, ?, ?)", [(r["iso3"], r["year"], r["outcome"]) for r in rows])
    con.execute("CREATE TABLE adoption (iso3 TEXT, first_year INTEGER)")
    con.executemany("INSERT INTO adoption VALUES (?, ?)", list(adoption.items()))
    con.commit()
    con.close()

    outcome = [r["outcome"] for r in rows]
    summary = {
        "n_observations": len(rows),
        "n_units": N_UNITS,
        "time_coverage": {"start_year": YEARS[0], "end_year": YEARS[-1]},
        "outcome": describe(outcome),
        "treated_units": sum(COHORTS.values()),
        "never_treated_units": N_UNITS - sum(COHORTS.values()),
        "cohorts": {str(k): v for k, v in COHORTS.items()},
        "missing": {"outcome": 0},
        "sample_flow": [{"step": "all rows of data/panel.csv", "rows": len(rows), "dropped": 0}],
    }
    (analyst / "summary_statistics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    def mean_by_year(group: str) -> list[float]:
        out = []
        for y in YEARS:
            vals = [
                r["outcome"]
                for r in rows
                if r["year"] == y
                and (
                    (group == "never" and adoption[r["iso3"]] is None)
                    or (group != "never" and adoption[r["iso3"]] == int(group))
                )
            ]
            out.append(round(sum(vals) / len(vals), 3))
        return out

    figures = {
        "figures": [
            {
                "filename": "fig_outcome_trends.pdf",
                "figure_type": "time_series",
                "label": "fig:trends",
                "caption_hint": "Mean outcome by adoption cohort (synthetic panel)",
                "series": [
                    {"label": "Adopted 2006", "x": YEARS, "y": mean_by_year("2006")},
                    {"label": "Adopted 2010", "x": YEARS, "y": mean_by_year("2010")},
                    {"label": "Never adopted", "x": YEARS, "y": mean_by_year("never")},
                ],
                "x_label": "Year",
                "y_label": "Mean outcome",
            }
        ]
    }
    (analyst / "figure_spec.json").write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")

    script = HERE / "files" / "econometrics_specialist" / "run_estimation.py"
    econ = root / "files" / "econometrics_specialist"
    econ.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(db, Path(tmp) / "data.db")
        shutil.copy(script, Path(tmp) / "run_estimation.py")
        subprocess.run([sys.executable, "run_estimation.py"], cwd=tmp, check=True)
        results = json.loads((Path(tmp) / "estimation_results.json").read_text(encoding="utf-8"))
    for key in drop_sensitivity:
        results["sensitivity"].pop(key, None)
    (econ / "estimation_results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(root.name, "ATT", results["main"]["coefficients"]["att"], "pre-trends p", results["pre_trends"]["p_value"])


def main() -> None:
    build(HERE, drift=0.0, inputs=True)
    # As if the analysis had reported no bound on violations of parallel trends: the
    # pre-trends test rejects and nothing rescues the design, so the check must stop the run.
    build(PRETREND, drift=0.45, inputs=False, drop_sensitivity=("honest_did_rm",))


if __name__ == "__main__":
    main()
