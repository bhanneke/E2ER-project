"""Build the climate replay fixture from a recorded NASA POWER response.

Test-only. The data are real: NASA POWER's monthly mean 2 m air temperature
(T2M) at 50.11 N, 8.68 E (the grid cell of Frankfurt am Main), 2001 to 2023,
recorded once live through e2er's connector (``inputs/nasa_power_monthly_t2m.json``,
POWER Monthly and Annual API v2.10.0, read 2026-10-11) and replayed here
without the network. Writes, from that response and the recorded analysis script:

    files/data_analyst/data.db                     table t2m_frankfurt, loaded by `e2er-data nasa_power point`
    files/data_analyst/data_sources.json           the load's record (terms, citation, request, SHA-256)
    files/data_analyst/summary_statistics.json     computed here
    files/data_analyst/figure_spec.json            the series figure
    files/econometrics_specialist/estimation_results.json   by running run_estimation.py
    files/econometrics_specialist/figure_spec.json the series figure and the hold-out figure

Run from the repository root: ``python tests/fixtures/replay/climate/make_fixture.py``.
The hand-written files (plans, the forecast setup, the draft, the reviews) are not touched.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CASSETTE = HERE / "inputs" / "nasa_power_monthly_t2m.json"
TABLE = "t2m_frankfurt"


def load(tmp: Path) -> Path:
    """Run the connector on the recorded response, as the data analyst would; return the workspace."""
    os.environ["E2ER_WORKSPACE_ROOT"] = str(tmp / "ws")
    os.environ["E2ER_CACHE_DIR"] = str(tmp / "cache")
    ws = tmp / "ws" / "fixture"
    ws.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    from src.modules.data import cli
    from src.modules.data.sources import http

    http.PACING = False
    with http.use_cassette(CASSETTE, record=False), contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(
            ["--paper-id", "fixture", "--specialist", "data_analyst", "nasa_power", "point", "--lat", "50.11",
             "--lon", "8.68", "--parameters", "T2M", "--temporal", "monthly", "--start", "2001", "--end", "2023",
             "--table", TABLE]
        )  # fmt: skip
    if code != 0:
        raise SystemExit(f"the connector failed on the recorded response (exit {code})")
    return ws


def describe(vals: list[float]) -> dict:
    s = sorted(vals)
    n = len(s)
    mean = sum(s) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in s) / (n - 1))

    def q(p: float) -> float:
        pos = (n - 1) * p
        lo, hi = math.floor(pos), math.ceil(pos)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)

    return {"n": n, "mean": round(mean, 4), "sd": round(sd, 4), "min": s[0], "p25": round(q(0.25), 4),
            "median": round(q(0.5), 4), "p75": round(q(0.75), 4), "max": s[-1]}  # fmt: skip


def series_figure(rows: list[tuple[str, float]]) -> dict:
    return {
        "filename": "fig_series.pdf",
        "figure_type": "time_series",
        "label": "fig:series",
        "caption_hint": "Monthly mean 2 m air temperature at the Frankfurt grid cell, 2001-2023 (NASA POWER)",
        "series": [
            {
                "label": "T2M",
                "x": [r[0] for r in rows],
                "y": [r[1] for r in rows],
                "source": {"table": TABLE, "columns": {"x": "date", "y": "T2M"}},
            }
        ],
        "x_label": "Month",
        "y_label": "Temperature (degrees C)",
    }


def main() -> None:
    analyst = HERE / "files" / "data_analyst"
    econ = HERE / "files" / "econometrics_specialist"
    analyst.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        ws = load(Path(t))
        shutil.copy(ws / "data.db", analyst / "data.db")
        record = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))
    # The record names the paper the load was made for; the replay fills in the run's own.
    text = json.dumps(record, indent=2, ensure_ascii=False).replace('"fixture"', '"@@PAPER_ID@@"')
    (analyst / "data_sources.json").write_text(text + "\n", encoding="utf-8")

    con = sqlite3.connect(analyst / "data.db")
    rows = con.execute(f"SELECT date, T2M FROM {TABLE} ORDER BY date").fetchall()  # noqa: S608
    con.close()
    values = [r[1] for r in rows]
    summary = {
        "n_observations": len(rows),
        "n_units": 1,
        "time_coverage": {"start": rows[0][0], "end": rows[-1][0], "frequency": "monthly"},
        "outcome": {**describe(values), "unit": "degrees C", "variable": "T2M"},
        "missing": {"T2M": sum(v is None for v in values)},
        "sample_flow": [{"step": "NASA POWER monthly T2M, 2001-01 to 2023-12", "rows": len(rows), "dropped": 0}],
    }
    (analyst / "summary_statistics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (analyst / "figure_spec.json").write_text(
        json.dumps({"figures": [series_figure(rows)]}, indent=2) + "\n", encoding="utf-8"
    )

    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(analyst / "data.db", Path(tmp) / "data.db")
        shutil.copy(econ / "run_estimation.py", Path(tmp) / "run_estimation.py")
        subprocess.run([sys.executable, "run_estimation.py"], cwd=tmp, check=True)
        results = json.loads((Path(tmp) / "estimation_results.json").read_text(encoding="utf-8"))
    (econ / "estimation_results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    oos = results["out_of_sample"]
    actual = [r for r in rows if r[0] >= oos["trend_season_test"]["test_start"]]
    holdout = {
        "filename": "fig_holdout.pdf",
        "figure_type": "time_series",
        "label": "fig:holdout",
        "caption_hint": "Hold-out 2021-2023: observed temperature, the trend-and-season forecast with its 95% "
        "interval, and the seasonal naive forecast",
        "series": [
            {
                "label": "Observed",
                "x": [r[0] for r in actual],
                "y": [r[1] for r in actual],
                "source": {"table": TABLE, "columns": {"x": "date", "y": "T2M"}, "where": "date >= '2021-01'"},
            },
            {
                "label": "Trend and monthly means (95% interval)",
                "x": [p["period"] for p in oos["trend_season_test"]["predictions"]],
                "y": [p["forecast"] for p in oos["trend_season_test"]["predictions"]],
                "lower": [p["lower"] for p in oos["trend_season_test"]["predictions"]],
                "upper": [p["upper"] for p in oos["trend_season_test"]["predictions"]],
                "source": {
                    "results": "out_of_sample.trend_season_test.predictions",
                    "fields": {"x": "period", "y": "forecast", "lower": "lower", "upper": "upper"},
                },
            },
            {
                "label": "Seasonal naive",
                "x": [p["period"] for p in oos["seasonal_naive_test"]["predictions"]],
                "y": [p["forecast"] for p in oos["seasonal_naive_test"]["predictions"]],
                "source": {
                    "results": "out_of_sample.seasonal_naive_test.predictions",
                    "fields": {"x": "period", "y": "forecast"},
                },
            },
        ],
        "x_label": "Month",
        "y_label": "Temperature (degrees C)",
    }
    (econ / "figure_spec.json").write_text(
        json.dumps({"figures": [series_figure(rows), holdout]}, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
