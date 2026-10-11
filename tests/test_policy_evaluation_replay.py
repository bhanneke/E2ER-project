"""The policy-evaluation (difference-in-differences) template end to end, under the replay level.

The did scenario (tests/fixtures/replay/did) is a hand-made replay of a
staggered DiD study of a SYNTHETIC panel: 24 units, 2000 to 2015, adoption in
2006 or 2010 or never. Its results were computed by the recorded
run_estimation.py (Callaway and Sant'Anna, bootstrap over units). The
did-pretrend scenario builds on it with an outcome that drifts before adoption
and no bound on violations of parallel trends.
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
import pytest

from tests.replay.backend import FIXTURES
from tests.test_replay_level import ROOT, _approve_to_the_end, _replay_server, _wait

DID = FIXTURES / "did"
SCENARIO = json.loads((DID / "scenario.json").read_text(encoding="utf-8"))
PANEL = ["identification_reviewer", "data_reviewer", "methods_reviewer", "writing_reviewer", "technical_reviewer"]
TOKEN = {"x-e2er-token": "replay-session"}


def _events(db: Path, pid: str) -> list[tuple[str, str, dict]]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT event_type, specialist, payload FROM pipeline_events WHERE paper_id = ? ORDER BY id", (pid,)
        ).fetchall()
    finally:
        con.close()
    return [(e, s or "", json.loads(p) if p else {}) for e, s, p in rows]


def _gates(events: list[tuple[str, str, dict]], name: str) -> list[dict]:
    return [pl for e, _s, pl in events if e in ("gate_enforced", "gate_shadow") and pl.get("gate") == name]


def _start(api: str, title: str) -> str:
    body = {
        "title": title,
        "research_question": SCENARIO["research_question"],
        "mode": "single_pass",
        "pipeline": "policy-evaluation",
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
    }
    r = httpx.post(f"{api}/api/papers", json=body, headers=TOKEN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["paper_id"]


def test_a_staggered_did_study_replays_to_the_end_with_its_design_and_results_checks(tmp_path: Path):
    study = tmp_path / "study"
    shutil.copytree(DID / "inputs" / "data", study / "data")
    with _replay_server(tmp_path, "did", [f"LOCAL_DATA_DIR={study / 'data'}"]) as (api, _):
        pid = _start(api, SCENARIO["title"])
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        # The design was pre-registered (the one stop), after the design check passed.
        assert stops == ["preregister"]
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)

        # Before estimation: the design against the panel. Staggered timing with a robust
        # estimator passes with a warning; the cohorts are recorded.
        design = _gates(events, "did_design")
        assert design and all(g.get("passed") for g in design), design
        found = json.loads((ws / "did_design_check.json").read_text(encoding="utf-8"))
        assert found["staggered"] is True and found["estimator"] == "callaway_santanna"
        assert {k: len(v) for k, v in found["cohorts"].items()} == {"2006": 6, "2010": 6}
        assert len(found["never_treated"]) == 12
        assert "staggered" in design[0]["detail"] and "warning" in design[0]["detail"]

        # The check ran before the pre-registration froze the design, and estimation after it.
        kinds = [(e, s, pl.get("gate")) for e, s, pl in events]
        first_design = next(i for i, k in enumerate(kinds) if k[2] == "did_design")
        frozen = next(i for i, (e, _s, _g) in enumerate(kinds) if e == "preregistration")
        estimated = next(
            i for i, (e, s, _g) in enumerate(kinds) if e == "specialist_start" and s == "econometrics_specialist"
        )
        drafted = next(i for i, (e, s, _g) in enumerate(kinds) if e == "specialist_start" and s == "paper_drafter")
        first_results = next(i for i, k in enumerate(kinds) if k[2] == "did_results")
        assert first_design < frozen < estimated < first_results < drafted
        lock = json.loads((ws / "preregistration.lock.json").read_text(encoding="utf-8"))
        assert "did_design.json" in lock["plan_files"]

        # After estimation: event study, pre-trends test, placebo and sensitivity, estimator.
        results_gate = _gates(events, "did_results")
        assert results_gate and all(g.get("passed") for g in results_gate), results_gate
        check = json.loads((ws / "did_check.json").read_text(encoding="utf-8"))
        assert check["passed"] and check["stats"]["pre_periods"] == 4 and check["stats"]["post_periods"] == 6
        # The event-study plot was drawn from the results and rendered.
        figs = json.loads((ws / "figure_spec.json").read_text(encoding="utf-8"))["figures"]
        es = next(f for f in figs if f["filename"] == "fig_event_study.pdf")
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
        assert es["estimates"] == [p_["estimate"] for p_ in results["event_study"]["periods"]]
        assert (ws / "fig_event_study.pdf").is_file()

        # The number check: the event-study and sensitivity tables traced to the results.
        nv = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert nv["passed"] and nv["matched"] >= 40 and nv["mismatched"] == 0, nv
        assert "-2.9962" in (ws / "tables" / "event_study.tex").read_text(encoding="utf-8")

        # The template's panel, with its weights.
        agg = json.loads((ws / "review_aggregation.json").read_text(encoding="utf-8"))
        assert sorted(s["reviewer"] for s in agg["panel"]["scores"]) == sorted(PANEL)
        weights = {s["reviewer"]: s["weight"] for s in agg["panel"]["scores"]}
        assert weights["identification_reviewer"] == 1.5 and weights["writing_reviewer"] == 0.75
        ran = {sp for e, sp, _pl in events if e == "specialist_start"}
        assert set(PANEL) <= ran and not ran & {"mechanism_reviewer", "literature_reviewer", "theory_specialist"}

    # Exported, published offline, verified (the method checks again on the exported files),
    # and reproduced from the export.
    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    assert (bundle / "design" / "did_design.json").is_file()
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    cli = [sys.executable, "-m", "tests.replay.cli"]
    db = tmp_path / "home" / ".e2er" / "papers.db"
    out = subprocess.run(
        [*cli, "publish", str(bundle), "--owner", "replay", "--project", "did", "--name", "Replay"]
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
    assert "[PASS] spec" in out.stdout  # the identified design: no fixed effects, clustered by unit
    assert "[PASS] method checks" in out.stdout and "difference-in-differences" in out.stdout, out.stdout

    # A changed event-study estimate in the export fails the method check of verify.
    tampered = tmp_path / "tampered"
    shutil.copytree(bundle, tampered)
    res = tampered / "results" / "estimation_results.json"
    doc = json.loads(res.read_text(encoding="utf-8"))
    doc.pop("placebo")
    doc.pop("sensitivity")
    res.write_text(json.dumps(doc), encoding="utf-8")
    out = subprocess.run(
        [*cli, "verify", str(tampered)], cwd=study, env=env, capture_output=True, text=True, timeout=300
    )
    assert "[FAIL] method checks" in out.stdout and "(g)" in out.stdout, out.stdout

    # Reproduce: the analysis runs again from the export in a new environment (from uv's cache, offline).
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed; e2er reproduce would install the requirements with pip from the network")
    uv_dirs = {}
    for var, cmd in (("UV_CACHE_DIR", "cache"), ("UV_PYTHON_INSTALL_DIR", "python")):
        # The test's HOME is a fresh folder: point uv at the real cache and Pythons.
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


def test_a_pre_trend_stops_the_run_before_anything_is_drafted(tmp_path: Path):
    """The adopters' outcome drifts before adoption: the joint pre-trends test rejects and,
    without a bound on violations of parallel trends, the did_results check stops the run."""
    study = tmp_path / "study"
    shutil.copytree(DID / "inputs" / "data", study / "data")
    with _replay_server(tmp_path, "did-pretrend", [f"LOCAL_DATA_DIR={study / 'data'}"]) as (api, _):
        pid = _start(api, "A pre-trend (synthetic)")
        p = _wait(api, pid)
        review = httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]
        assert review["stage"] == "preregister"
        httpx.post(f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=TOKEN, timeout=30)
        p = _wait(api, pid)
        assert p["status"] == "paused", p
        review = httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]
        assert review["stage"] == "did_results_gate", review
        reasons = " ".join(review.get("reasons") or [])
        assert "jointly different from zero" in reasons and "Rambachan" in reasons, review
        ws = Path(p["workspace"])
        assert not (ws / "paper_draft.tex").exists()  # nothing drafted around a design the data contradict
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        gates = _gates(events, "did_results")
        # on_fail = "retry": the econometrics specialist was sent back once, and the rerun failed again.
        assert [g["passed"] for g in gates] == [False, False]
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("econometrics_specialist") == 2
        # The researcher is shown the results and the design, to fix one of them or send a specialist back.
        state = json.loads((ws / ".pipeline_state.json").read_text(encoding="utf-8"))
        assert state["metadata"]["review"]["files"][:2] == ["estimation_results.json", "did_design.json"]

        # Approving does not pass a check: the run stops at it again.
        httpx.post(f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=TOKEN, timeout=30)
        p = _wait(api, pid)
        assert httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]["stage"] == "did_results_gate"
