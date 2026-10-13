"""The spatial-analysis template end to end, under the replay level.

The spatial scenario (tests/fixtures/replay/spatial) is a hand-made replay of
a spatial analysis of a SYNTHETIC grid of 30 square regions with a regional
rate; one data unit (RZZ, an extra-regio code) has no geometry and is listed
with its reason. Its results were computed by the recorded run_estimation.py
(queen and 4-nearest-neighbour weights, Moran's I with 999 permutations, LISA).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.replay.backend import FIXTURES
from tests.test_policy_evaluation_replay import TOKEN, _events, _gates
from tests.test_replay_level import ROOT, _approve_to_the_end, _replay_server, _wait

SPATIAL = FIXTURES / "spatial"
SCENARIO = json.loads((SPATIAL / "scenario.json").read_text(encoding="utf-8"))
PANEL = ["methods_reviewer", "data_reviewer", "plausibility_reviewer", "writing_reviewer", "technical_reviewer"]


def _start(api: str) -> str:
    body = {
        "title": SCENARIO["title"],
        "research_question": SCENARIO["research_question"],
        "mode": "single_pass",
        "pipeline": "spatial-analysis",
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
    }
    r = httpx.post(f"{api}/api/papers", json=body, headers=TOKEN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["paper_id"]


def test_a_spatial_study_replays_to_the_end_with_its_geometry_weights_and_maps_checked(tmp_path: Path):
    study = tmp_path / "study"
    shutil.copytree(SPATIAL / "inputs" / "data", study / "data")
    with _replay_server(tmp_path, "spatial", [f"LOCAL_DATA_DIR={study / 'data'}"]) as (api, _):
        pid = _start(api)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == []
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)

        # No causal claim: no identification asked for; the spatial results contract held.
        assert not (ws / "identification_spec.json").exists()
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
        assert results["result_kind"] == "spatial"
        estimation = _gates(events, "estimation")
        assert estimation and all(g.get("passed") for g in estimation)

        # Before the analysis: boundaries' source, CRS, the unit without geometry, the weights.
        design = _gates(events, "spatial_design")
        assert design and all(g.get("passed") for g in design), design
        match = json.loads((ws / "spatial_design_check.json").read_text(encoding="utf-8"))
        assert match["data_units"] == 31 and match["with_geometry"] == 30 and match["without_geometry"] == ["RZZ"]
        assert match["crs"] == "EPSG:4326"

        # After it: Moran's I recomputed from the units and weights files, permutation inference, maps.
        after = _gates(events, "spatial_results")
        assert after and all(g.get("passed") for g in after), after
        check = json.loads((ws / "spatial_check.json").read_text(encoding="utf-8"))
        assert check["stats"]["moran_rate_queen"] == results["spatial_statistics"]["moran_rate_queen"]["estimate"]
        order = [(e, s, pl.get("gate")) for e, s, pl in events]
        checked = next(i for i, k in enumerate(order) if k[2] == "spatial_results")
        drafted = next(i for i, (e, s, _g) in enumerate(order) if e == "specialist_start" and s == "paper_drafter")
        assert checked < drafted

        # The map figures were built from the design's boundaries and the units file, and rendered.
        figs = {f["filename"]: f for f in json.loads((ws / "figure_spec.json").read_text(encoding="utf-8"))["figures"]}
        assert figs["fig_map_rate.pdf"]["figure_type"] == "map"
        assert figs["fig_map_rate.pdf"]["boundaries"]["table"] == "regions"
        assert figs["fig_map_lisa.pdf"]["map_type"] == "categories"
        report = json.loads((ws / "figure_render_report.json").read_text(encoding="utf-8"))
        assert {"fig_map_rate.pdf", "fig_map_lisa.pdf"} <= set(report["rendered"]), report
        assert (ws / "fig_map_rate.pdf").stat().st_size > 1000

        # Number check over the kind's files; the template's panel.
        nv = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert nv["passed"] and nv["matched"] >= 10 and nv["mismatched"] == 0, nv
        agg = json.loads((ws / "review_aggregation.json").read_text(encoding="utf-8"))
        assert sorted(s["reviewer"] for s in agg["panel"]["scores"]) == sorted(PANEL)
        ran = {sp for e, sp, _pl in events if e == "specialist_start"}
        assert not ran & {"identification_strategist", "identification_reviewer", "mechanism_reviewer"}
        core = next(pl for e, _s, pl in events if e == "template_components")["core"]
        assert core["results"] == "spatial" and core["causal"] is False and core["base_skill"] == "base/researcher"

    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    assert (bundle / "design" / "spatial_design.json").is_file()
    assert (bundle / "results" / "spatial_weights.csv").is_file()
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    cli = [sys.executable, "-m", "tests.replay.cli"]
    db = tmp_path / "home" / ".e2er" / "papers.db"
    out = subprocess.run(
        [*cli, "publish", str(bundle), "--owner", "replay", "--project", "spatial", "--name", "Replay"]
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
    assert "[PASS] method checks" in out.stdout and "spatial" in out.stdout, out.stdout

    # A weights file changed after the export: Moran's I no longer follows from it.
    tampered = tmp_path / "tampered"
    shutil.copytree(bundle, tampered)
    wfile = tampered / "results" / "spatial_weights.csv"
    rows = list(csv.DictReader(wfile.open(encoding="utf-8")))
    with wfile.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["from", "to", "weight"])
        w.writeheader()
        w.writerows(r for r in rows if not (r["from"] == "R01" or r["to"] == "R01"))
    out = subprocess.run(
        [*cli, "verify", str(tampered)], cwd=study, env=env, capture_output=True, text=True, timeout=300
    )
    assert "[FAIL] method checks" in out.stdout and "(g)" in out.stdout, out.stdout

    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    uv_dirs = {}
    for var, cmd in (("UV_CACHE_DIR", "cache"), ("UV_PYTHON_INSTALL_DIR", "python")):
        found = subprocess.run(["uv", cmd, "dir"], capture_output=True, text=True, env={**os.environ, "NO_COLOR": "1"})
        if found.returncode == 0 and found.stdout.strip():
            uv_dirs[var] = found.stdout.strip()
    out = subprocess.run(
        [*cli, "reproduce", str(bundle)],
        cwd=study,
        env={**env, "UV_OFFLINE": "1", **uv_dirs},
        capture_output=True,
        text=True,
        timeout=900,
    )
    if "could not install" in out.stdout or "could not create the environment" in out.stdout:
        pytest.skip("the requirements or Python are not in uv's cache (offline): " + out.stdout[-400:])
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Reproduced" in out.stdout, out.stdout


def test_a_data_unit_without_geometry_that_is_not_listed_stops_the_run_before_the_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The data architect leaves RZZ off units_without_geometry: the design check stops the run."""
    overrides = tmp_path / "overrides.json"
    unlisted = {
        "replace": {
            "spatial_design.json": [
                [
                    '"units_without_geometry": [{"id": "RZZ", "reason": "extra-regio code: '
                    'data not attributed to any region, no territory"}],',
                    '"units_without_geometry": [],',
                ]
            ]
        }
    }
    # The same file twice: the first answer and the one after the check sent the data architect back.
    overrides.write_text(json.dumps({"data_architect": {"attempts": [unlisted, unlisted]}}), encoding="utf-8")
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(overrides))
    study = tmp_path / "study"
    shutil.copytree(SPATIAL / "inputs" / "data", study / "data")
    with _replay_server(tmp_path, "spatial", [f"LOCAL_DATA_DIR={study / 'data'}"]) as (api, _):
        pid = _start(api)
        p = _wait(api, pid)
        assert p["status"] == "paused", p
        review = httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]
        assert review["stage"] == "spatial_design_gate", review
        reasons = " ".join(review.get("reasons") or [])
        assert "have no geometry" in reasons and "RZZ" in reasons, reasons
        ws = Path(p["workspace"])
        assert not (ws / "estimation_results.json").exists()  # the analysis did not run
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert "econometrics_specialist" not in started
        # on_fail = "retry": the data architect was sent back once with the reasons before the run stopped.
        assert started.count("data_architect") == 2
        assert [g["passed"] for g in _gates(events, "spatial_design")] == [False, False]

        # The researcher lists the unit with its reason; the check runs again on resume and passes.
        design = json.loads((ws / "spatial_design.json").read_text(encoding="utf-8"))
        design["units_without_geometry"] = [{"id": "*ZZ", "reason": "extra-regio codes, no territory"}]
        (ws / "spatial_design.json").write_text(json.dumps(design), encoding="utf-8")
        httpx.post(f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=TOKEN, timeout=30)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        gates = _gates(_events(tmp_path / "home" / ".e2er" / "papers.db", pid), "spatial_design")
        assert [g["passed"] for g in gates] == [False, False, True]
