"""Build the spatial replay fixture: a synthetic grid of regions, a regional rate, and the computed files.

Test-only. The regions are SYNTHETIC: a 6 x 5 grid of 2-degree squares
(longitude 0 to 12 E, latitude 44 to 54 N), ids R01 to R30, no real region.
The rate rises from west to east and from south to north with noise, so
neighbours are alike. The rate table also has one row for "RZZ", an
"extra-regio" code with no territory, which the design lists among the units
without geometry.

Writes:

    inputs/data/regions.csv       id, name, geometry (GeoJSON text): the researcher's boundaries
    inputs/data/regional.csv      geo, year, rate
    files/data_analyst/data.db    tables `regions` and `regional`
    files/data_analyst/summary_statistics.json, figure_spec.json
    files/econometrics_specialist/estimation_results.json, spatial_units.csv,
        spatial_weights.csv, spatial_weights_knn4.csv   by running run_estimation.py

Run: ``python tests/fixtures/replay/spatial/make_fixture.py``.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261011
COLS, ROWS = 6, 5
OUTPUTS = ("estimation_results.json", "spatial_units.csv", "spatial_weights.csv", "spatial_weights_knn4.csv")


def regions() -> list[dict]:
    out = []
    k = 0
    for r in range(ROWS):
        for c in range(COLS):
            k += 1
            x0, y0 = 2.0 * c, 44.0 + 2.0 * r
            ring = [[x0, y0], [x0 + 2, y0], [x0 + 2, y0 + 2], [x0, y0 + 2], [x0, y0]]
            out.append(
                {
                    "id": f"R{k:02d}",
                    "name": f"Synthetic region {k}",
                    "col": c,
                    "row": r,
                    "geometry": json.dumps({"type": "Polygon", "coordinates": [ring]}, separators=(",", ":")),
                }
            )
    return out


def main() -> None:
    rng = random.Random(SEED)
    regs = regions()
    rates = []
    for g in regs:
        for year in (2022, 2023):
            base = 4.0 + 0.9 * g["col"] + 0.5 * g["row"] + rng.gauss(0, 0.8) + (0.2 if year == 2023 else 0.0)
            rates.append({"geo": g["id"], "year": year, "rate": round(base, 2)})
    rates += [{"geo": "RZZ", "year": 2022, "rate": 6.1}, {"geo": "RZZ", "year": 2023, "rate": 6.3}]

    data = HERE / "inputs" / "data"
    data.mkdir(parents=True, exist_ok=True)
    with (data / "regions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name", "geometry"])
        for g in regs:
            w.writerow([g["id"], g["name"], g["geometry"]])
    with (data / "regional.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["geo", "year", "rate"])
        w.writeheader()
        w.writerows(rates)

    analyst = HERE / "files" / "data_analyst"
    analyst.mkdir(parents=True, exist_ok=True)
    db = analyst / "data.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE regions (id TEXT, name TEXT, geometry TEXT)")
    con.executemany("INSERT INTO regions VALUES (?, ?, ?)", [(g["id"], g["name"], g["geometry"]) for g in regs])
    con.execute("CREATE TABLE regional (geo TEXT, year INTEGER, rate REAL)")
    con.executemany("INSERT INTO regional VALUES (?, ?, ?)", [(r["geo"], r["year"], r["rate"]) for r in rates])
    con.commit()
    con.close()

    r23 = [r["rate"] for r in rates if r["year"] == 2023 and r["geo"] != "RZZ"]
    summary = {
        "n_observations": len(rates),
        "n_units": len(regs),
        "time_coverage": {"start_year": 2022, "end_year": 2023},
        "outcome": {"n": len(r23), "mean": round(sum(r23) / len(r23), 4), "min": min(r23), "max": max(r23)},
        "missing": {"rate": 0},
        "sample_flow": [
            {"step": "rows of data/regional.csv", "rows": len(rates), "dropped": 0},
            {"step": "2023 rows of regions with geometry (RZZ has none)", "rows": len(r23), "dropped": 1},
        ],
    }
    (analyst / "summary_statistics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (analyst / "figure_spec.json").write_text(json.dumps({"figures": []}, indent=2) + "\n", encoding="utf-8")

    econ = HERE / "files" / "econometrics_specialist"
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(db, Path(tmp) / "data.db")
        shutil.copy(econ / "run_estimation.py", Path(tmp) / "run_estimation.py")
        subprocess.run([sys.executable, "run_estimation.py"], cwd=tmp, check=True)
        for name in OUTPUTS:
            shutil.copy(Path(tmp) / name, econ / name)
    res = json.loads((econ / "estimation_results.json").read_text(encoding="utf-8"))
    print(json.dumps(res["spatial_statistics"], indent=1), res["clusters"])


if __name__ == "__main__":
    main()
