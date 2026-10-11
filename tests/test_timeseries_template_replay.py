"""The time-series template end to end, on NASA POWER data recorded through e2er's connector.

The climate scenario (tests/fixtures/replay/climate) replays a study of the
monthly mean temperature at the Frankfurt grid cell, 2001-2023, under the
shipped template ``time-series-forecasting``: the forecast designer declares
the setup, the forecast_design check freezes it with its hold-out before the
analysis, the forecast_evaluation check recomputes every out-of-sample error
from the predictions and the hold-out values in data.db, and the figure check
re-reads every figure. Then: the panel, publish offline, ``e2er verify`` with
the results contract, and ``e2er reproduce``.

Two variations: the optional pre-registration chosen for the run, and an
analysis script that fits the candidate model on the whole series (leakage),
which stops the run at the forecast check until the analysis is sent back.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx

from tests.replay.backend import FIXTURES
from tests.test_replay_level import ROOT, _approve_to_the_end, _replay_server, _wait

CLIMATE = FIXTURES / "climate"
SCENARIO = json.loads((CLIMATE / "scenario.json").read_text(encoding="utf-8"))
PANEL = [
    "methods_reviewer",
    "technical_reviewer",
    "data_reviewer",
    "plausibility_reviewer",
    "literature_reviewer",
    "writing_reviewer",
]
HEADERS = {"x-e2er-token": "replay-session"}


def _events(db: Path, pid: str) -> list[tuple[str, str, str, dict]]:
    """(event type, stage, specialist, payload) of the run's events, in order."""
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT event_type, stage, specialist, payload FROM pipeline_events WHERE paper_id = ? ORDER BY id", (pid,)
        ).fetchall()
    finally:
        con.close()
    return [(e, st or "", s or "", json.loads(p) if p else {}) for e, st, s, p in rows]


def _start(api: str, review_stages: list[str] | None = None) -> str:
    body = {
        "title": SCENARIO["title"],
        "research_question": SCENARIO["research_question"],
        "mode": "single_pass",
        "pipeline": SCENARIO["template"],
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
        "review_stages": review_stages or [],
    }
    r = httpx.post(f"{api}/api/papers", json=body, headers=HEADERS, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["paper_id"]


def _gates(events: list[tuple[str, str, str, dict]], gate: str) -> list[dict]:
    return [pl for e, _st, _s, pl in events if e in ("gate_enforced", "gate_shadow") and pl.get("gate") == gate]


def test_a_forecasting_study_replays_to_the_end_with_its_hold_out_frozen_before_fitting(tmp_path: Path):
    with _replay_server(tmp_path, "climate", []) as (api, study):
        pid = _start(api)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == ["review_design", "review_draft"]  # the pre-registration is optional and was not chosen
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)

        # The setup was frozen after the forecast designer and before the analysis.
        order = [(e, s, pl.get("gate")) for e, _st, s, pl in events if e in ("specialist_start", "gate_enforced")]
        frozen = order.index(("gate_enforced", "", "forecast_design"))
        assert order.index(("specialist_start", "forecast_designer", None)) < frozen
        assert frozen < order.index(("specialist_start", "econometrics_specialist", None))
        freeze = json.loads((ws / "holdout_freeze.json").read_text(encoding="utf-8"))
        assert (freeze["start"], freeze["end"], freeze["n_periods"], freeze["train_end"]) == (
            "2021-01",
            "2023-12",
            36,
            "2020-12",
        )
        assert len(freeze["values_sha256"]) == 64 and freeze["changes"] == []

        # Every check passed; the forecast check recomputed the errors from the predictions and data.db.
        for gate in ("forecast_design", "estimation", "forecast_evaluation", "figure_data"):
            found = _gates(events, gate)
            assert found and all(g["passed"] for g in found), (gate, found)
        check = json.loads((ws / "forecast_check.json").read_text(encoding="utf-8"))
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
        assert results["result_kind"] == "timeseries" and not (ws / "identification_spec.json").exists()
        for key, rec in check["out_of_sample"].items():
            assert abs(rec["rmse"] - results["out_of_sample"][key]["rmse"]) < 1e-4
            assert abs(rec["mae"] - results["out_of_sample"][key]["mae"]) < 1e-4
        assert check["out_of_sample"]["trend_season_test"]["relative_rmse"] < 1  # beats the best baseline

        # The number check traced the tables to the results; the panel is the template's.
        nv = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert nv["passed"] and nv["mismatched"] == 0 and nv["matched"] >= 20, nv
        assert "Trend and monthly means & 36 & 1.788 & 1.497 & 0.711 & 0.944" in (
            ws / "tables" / "holdout.tex"
        ).read_text(encoding="utf-8")
        agg = json.loads((ws / "review_aggregation.json").read_text(encoding="utf-8"))
        assert sorted(s["reviewer"] for s in agg["panel"]["scores"]) == sorted(PANEL)
        ran = {s for e, _st, s, _pl in events if e == "specialist_start"}
        assert set(PANEL) <= ran and not ran & {
            "identification_strategist",
            "mechanism_reviewer",
            "identification_reviewer",
        }

    # Published offline, verified, reproduced.
    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    for name in ("design/forecast_design.json", "design/holdout_freeze.json", "results/forecast_check.json"):
        assert (bundle / name).is_file(), name
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    cli = [sys.executable, "-m", "tests.replay.cli"]
    db = tmp_path / "home" / ".e2er" / "papers.db"
    out = subprocess.run(
        [*cli, "publish", str(bundle), "--owner", "replay", "--project", "climate", "--name", "Replay"]
        + ["--offline", "--no-stamp", "--out", str(tmp_path / "entry"), "--db", str(db)],
        cwd=study,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    out = subprocess.run([*cli, "verify", str(bundle)], cwd=study, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[PASS] numbers" in out.stdout and "[PASS] results contract" in out.stdout, out.stdout
    out = subprocess.run(
        [*cli, "reproduce", str(bundle)], cwd=study, env=env, capture_output=True, text=True, timeout=600
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Reproduced" in out.stdout, out.stdout


def test_the_optional_pre_registration_freezes_the_forecast_setup(tmp_path: Path):
    with _replay_server(tmp_path, "climate", []) as (api, _study):
        pid = _start(api, ["preregister"])
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == ["review_design", "preregister", "review_draft"]
        ws = Path(p["workspace"])
        lock = json.loads((ws / "preregistration.lock.json").read_text(encoding="utf-8"))
        assert "forecast_design.json" in lock["plan_files"]
        text = (ws / "preregistration.md").read_text(encoding="utf-8")
        assert "Forecast setup and hold-out (machine-readable)" in text and '"n_periods": 36' in text


def test_a_model_fitted_on_the_hold_out_stops_the_run_until_the_analysis_is_redone(tmp_path: Path, monkeypatch):
    # The first analysis fits the candidate model on every month, the hold-out included.
    # Its results are computed here from that script and the recorded data, as the run would compute them.
    econ = CLIMATE / "files" / "econometrics_specialist"
    leak = ["ts_fit = fit_trend_season(train_p, train_y)", "ts_fit = fit_trend_season(periods, values)"]
    run = tmp_path / "leaky"
    run.mkdir()
    shutil.copy(CLIMATE / "files" / "data_analyst" / "data.db", run / "data.db")
    (run / "run_estimation.py").write_text(
        (econ / "run_estimation.py").read_text(encoding="utf-8").replace(*leak), encoding="utf-8"
    )
    subprocess.run([sys.executable, "run_estimation.py"], cwd=run, check=True)
    recorded = (econ / "estimation_results.json").read_text(encoding="utf-8")
    leaked = (run / "estimation_results.json").read_text(encoding="utf-8")
    overrides = tmp_path / "overrides.json"
    replace = {"run_estimation.py": [leak], "estimation_results.json": [[recorded, leaked]]}
    overrides.write_text(
        json.dumps({"econometrics_specialist": {"attempts": [{"replace": replace}]}}), encoding="utf-8"
    )
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(overrides))  # read by the server the next line starts
    with _replay_server(tmp_path, "climate", []) as (api, _study):
        if True:
            pid = _start(api)
            stops = []
            for _ in range(4):
                p = _wait(api, pid)
                pending = httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]
                assert pending, (p.get("status"), p.get("last_error"), stops)
                stops.append(pending["stage"])
                if pending["stage"] == "forecast_gate":
                    break
                r = httpx.post(
                    f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=HEADERS, timeout=30
                )
                assert r.status_code == 200, r.text
            assert stops == ["review_design", "forecast_gate"], stops
            assert any(
                "leakage: models.trend_season was fitted on periods up to 2023-12" in r for r in pending["reasons"]
            )
            ws = Path(p["workspace"])
            assert not json.loads((ws / "forecast_check.json").read_text(encoding="utf-8"))["passed"]

            # Approving does not pass a failed check; sending the analysis back does, once it is redone.
            r = httpx.post(
                f"{api}/api/papers/{pid}/review",
                json={
                    "action": "send_back",
                    "step": "econometrics_specialist",
                    "remark": "Fit on the training months only.",
                },
                headers=HEADERS,
                timeout=30,
            )
            assert r.status_code == 200, r.text
            p, more = _approve_to_the_end(api, pid)
            assert p["status"] == "completed", (p.get("last_error"), more)
            assert json.loads((ws / "forecast_check.json").read_text(encoding="utf-8"))["passed"]
