"""A descriptive study end to end: no regression, no identification, its own contract and number check.

The exoplanet scenario (tests/fixtures/replay/exoplanet) is a hand-made replay
of a descriptive study of a SYNTHETIC planet sample under the test template
``descriptive-study`` (in the scenario's ``pipelines/`` folder, copied into the
study's own ``pipelines/`` so the server resolves it like a project template).
The template declares ``results = "descriptive"``, ``causal = false``, the
researcher persona, no blockchain data skills, its own review panel with
weights and its own polish steps (src/core/pipeline/spec.py).
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
from tests.test_replay_level import ROOT, _approve_to_the_end, _replay_server

EXO = FIXTURES / "exoplanet"
SCENARIO = json.loads((EXO / "scenario.json").read_text(encoding="utf-8"))
PANEL = ["data_reviewer", "methods_reviewer", "plausibility_reviewer", "literature_reviewer", "writing_reviewer"]


def _events(db: Path, pid: str) -> list[tuple[str, str, dict]]:
    """(event type, specialist, payload) of the run's events, in order."""
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT event_type, specialist, payload FROM pipeline_events WHERE paper_id = ? ORDER BY id", (pid,)
        ).fetchall()
    finally:
        con.close()
    return [(e, s or "", json.loads(p) if p else {}) for e, s, p in rows]


def test_a_descriptive_study_replays_to_the_end_without_regression_or_identification(tmp_path: Path):
    study = tmp_path / "study"
    shutil.copytree(EXO / "inputs" / "data", study / "data")
    shutil.copytree(EXO / "pipelines", study / "pipelines")
    with _replay_server(tmp_path, "exoplanet", [f"LOCAL_DATA_DIR={study / 'data'}"]) as (api, _):
        body = {
            "title": SCENARIO["title"],
            "research_question": SCENARIO["research_question"],
            "mode": "single_pass",
            "pipeline": SCENARIO["template"],
            "acknowledge_unproven_tuple": True,
            "max_cost_usd": 5,
        }
        r = httpx.post(f"{api}/api/papers", json=body, headers={"x-e2er-token": "replay-session"}, timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["paper_id"]
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == []
        ws = Path(p["workspace"])

        # No regression and no identification were asked for, and none was written.
        assert not (ws / "identification_spec.json").exists()
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
        assert results["result_kind"] == "descriptive"
        assert "coefficients" not in json.dumps(results)

        # The estimation gate held the results to the descriptive contract, and passed.
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        gates = [pl for e, _s, pl in events if e in ("gate_enforced", "gate_shadow") and pl.get("gate") == "estimation"]
        assert gates and all(g.get("passed") for g in gates), gates

        # Its own number check: the tables are records tables filled from the descriptive
        # results, every cell traced, nothing differing; the sources are the kind's files.
        nv = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert nv["passed"] and nv["matched"] >= 20 and nv["mismatched"] == 0, nv
        assert "field_map_results.json" not in nv["source_files_missing"]
        assert {Path(f).name for f in nv["source_files_found"]} >= {
            "estimation_results.json",
            "summary_statistics.json",
        }
        summary_tex = (ws / "tables" / "summary.tex").read_text(encoding="utf-8")
        assert "Radius (Earth radii) & 60 & 3.809 & 3.604" in summary_tex
        assert "1.5 & 2.0 & 7" in (ws / "tables" / "radius_bins.tex").read_text(encoding="utf-8")

        # The template's panel, with its weights, and nothing of the economics panel.
        agg = json.loads((ws / "review_aggregation.json").read_text(encoding="utf-8"))
        assert sorted(s["reviewer"] for s in agg["panel"]["scores"]) == sorted(PANEL)
        assert agg["panel"]["expected"] == 5 and agg["panel"]["complete"]
        weights = {s["reviewer"]: s["weight"] for s in agg["panel"]["scores"]}
        assert weights["methods_reviewer"] == 1.5 and weights["literature_reviewer"] == 0.75
        assert agg["verdict"] == "MINOR_REVISION" and abs(agg["weighted_avg"] - 42.625 / 5.5) < 1e-9
        ran = {sp for e, sp, _pl in events if e == "specialist_start"}
        assert not ran & {
            "identification_strategist",
            "mechanism_reviewer",
            "identification_reviewer",
            "theory_specialist",
        }
        assert set(PANEL) <= ran

        # The run records what the template changed about e2er's defaults.
        core = next(pl for e, _s, pl in events if e == "template_components")["core"]
        assert core["results"] == "descriptive" and core["causal"] is False
        assert core["base_skill"] == "base/researcher" and core["data_skills"] == []
        assert core["panel"] == [
            "literature_reviewer",
            "writing_reviewer",
            "data_reviewer",
            "methods_reviewer",
            "plausibility_reviewer",
        ]

    # Exported, published offline and verified like any study: `e2er verify` reads the kind
    # from the results file (no template outside the run) and checks its numbers.
    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    cli = [sys.executable, "-m", "tests.replay.cli"]
    db = tmp_path / "home" / ".e2er" / "papers.db"
    out = subprocess.run(
        [*cli, "publish", str(bundle), "--owner", "replay", "--project", "exoplanet", "--name", "Replay"]
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
    assert "[PASS] numbers" in out.stdout
    assert "[PASS] results contract" in out.stdout, out.stdout
    assert "[SKIP] spec" in out.stdout  # no identification specification: none was required
