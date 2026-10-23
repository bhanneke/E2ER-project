"""The systematic-review template end to end, under the replay level.

The scenario (tests/fixtures/replay/systematic-review) is a hand-made replay of
a review of SYNTHETIC records on grit and grades (tests/meta_fixture.py). The
search and the full-text step run their real code on recorded OpenAlex pages
and PDFs; screening, extraction, the trace of every extracted number, the
synthesis by e2er's run_estimation.py, the figures, the number check, the
panel, export, publish, verify and reproduce are the real code on the recorded
specialists' files.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.replay import uv
from tests.replay.backend import FIXTURES
from tests.test_policy_evaluation_replay import TOKEN, _events, _gates
from tests.test_replay_level import ROOT, _approve_to_the_end, _replay_server, _wait

SR = FIXTURES / "systematic-review"
SCENARIO = json.loads((SR / "scenario.json").read_text(encoding="utf-8"))
PANEL = ["methods_reviewer", "data_reviewer", "plausibility_reviewer", "writing_reviewer", "technical_reviewer"]


def _start(api: str) -> str:
    body = {
        "title": SCENARIO["title"],
        "research_question": SCENARIO["research_question"],
        "mode": "single_pass",
        "pipeline": "systematic-review",
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
    }
    r = httpx.post(f"{api}/api/papers", json=body, headers=TOKEN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["paper_id"]


def test_a_systematic_review_replays_from_the_protocol_to_a_reproduced_meta_analysis(tmp_path: Path):
    with _replay_server(tmp_path, "systematic-review", []) as (api, study):
        pid = _start(api)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        # The researcher's stops: the protocol with the counts, the screening sample, the draft.
        assert stops == ["review_protocol", "review_screening", "review_draft"], stops
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)

        # The search ran on the recorded OpenAlex pages: two searches, one duplicate.
        log = json.loads((ws / "search_log.json").read_text(encoding="utf-8"))
        assert log["identified"] == 12 and log["duplicates_removed"] == 1 and log["records"] == 11
        assert [s["name"] for s in log["searches"]] == ["main", "grades"]
        assert all("title_and_abstract.search" in s["query"] for s in log["searches"])
        sources = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))
        assert any(x.get("connector") == "openalex" for x in (sources.get("loads") or sources))

        # Every check passed and was recorded; nothing was estimated by a model.
        for gate in ("meta_screening", "meta_extraction", "meta_synthesis"):
            got = _gates(events, gate)
            assert got and all(g.get("passed") for g in got), (gate, got)
        assert (ws / "screening_sample.md").is_file()
        ft = json.loads((ws / "fulltext_log.json").read_text(encoding="utf-8"))
        assert ft["counts"] == {"sought": 9, "retrieved": 8, "not_retrieved": 1}
        assert ft["records"]["W108"]["status"] == "not available"
        trace = json.loads((ws / "extraction_check.json").read_text(encoding="utf-8"))
        assert trace["numbers"] == 24 and trace["traced"] == 24
        ran = [s for e, s, _pl in events if e == "specialist_start"]
        assert not {"econometrics_specialist", "data_analyst", "identification_strategist"} & set(ran)

        # The meta-analysis by e2er's script, held to the contract; the figures drawn.
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
        assert results["result_kind"] == "metaanalysis" and results["k"] == 8 and not results["narrative_only"]
        assert results["prisma"]["included_in_meta_analysis"] == 8
        assert 0 < results["heterogeneity"]["i2"] < 100
        assert "e2er's meta-analysis code" in (ws / "run_estimation.py").read_text(encoding="utf-8")
        report = json.loads((ws / "figure_render_report.json").read_text(encoding="utf-8"))
        assert {"fig_forest.pdf", "fig_funnel.pdf", "fig_prisma.pdf"} <= set(report["rendered"]), report

        # The number check traced the tables to the results; the template's panel scored.
        nv = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert nv["passed"] and nv["matched"] >= 60 and nv["mismatched"] == 0, nv
        agg = json.loads((ws / "review_aggregation.json").read_text(encoding="utf-8"))
        assert sorted(s["reviewer"] for s in agg["panel"]["scores"]) == sorted(PANEL)
        core = next(pl for e, _s, pl in events if e == "template_components")["core"]
        assert core["results"] == "metaanalysis" and core["causal"] is False

    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    for rel in (
        "design/review_protocol.json",
        "design/screening.json",
        "design/extraction.json",
        "results/records.json",
        "results/search_log.json",
        "results/meta_studies.csv",
        "results/extraction_check.json",
        "code/run_estimation.py",
    ):
        assert (bundle / rel).is_file(), rel
    assert not list(bundle.rglob("fulltext")), "full texts are not exported"

    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    cli = [sys.executable, "-m", "tests.replay.cli"]
    db = tmp_path / "home" / ".e2er" / "papers.db"
    out = subprocess.run(
        [*cli, "publish", str(bundle), "--owner", "replay", "--project", "sr", "--name", "Replay"]
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
    assert "[PASS] method checks" in out.stdout and "meta-analysis" in out.stdout, out.stdout

    # An extracted number changed after the export: it is no longer printed in its quote.
    tampered = tmp_path / "tampered"
    shutil.copytree(bundle, tampered)
    ext = tampered / "design" / "extraction.json"
    data = json.loads(ext.read_text(encoding="utf-8"))
    data["studies"][0]["n_total"] = 421
    ext.write_text(json.dumps(data), encoding="utf-8")
    out = subprocess.run(
        [*cli, "verify", str(tampered)], cwd=study, env=env, capture_output=True, text=True, timeout=300
    )
    assert "[FAIL] method checks" in out.stdout and "not printed in its quote" in out.stdout, out.stdout

    uv_dirs = uv.reproduce_env()
    out = subprocess.run(
        [*cli, "reproduce", str(bundle), "--yes", "--no-sandbox"],
        cwd=study,
        env={**env, **uv_dirs},
        capture_output=True,
        text=True,
        timeout=900,
    )
    uv.check_installed(out.stdout)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Reproduced" in out.stdout, out.stdout


def test_an_extracted_number_that_is_not_in_its_quote_stops_the_run_before_the_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The extractor cites a passage that does not print the number: e2er stops before anything is pooled."""
    overrides = tmp_path / "overrides.json"
    wrong = {"replace": {"extraction.json": [['"n_total": 412', '"n_total": 421']]}}
    overrides.write_text(json.dumps({"study_extractor": {"attempts": [wrong, wrong, wrong]}}), encoding="utf-8")
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(overrides))
    with _replay_server(tmp_path, "systematic-review", []) as (api, _):
        pid = _start(api)
        for _ in range(2):  # the protocol and the screening stops
            _wait(api, pid)
            httpx.post(f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=TOKEN, timeout=30)
        p = _wait(api, pid)
        assert p["status"] == "paused", p
        review = httpx.get(
            f"{api}/api/papers/{pid}/review", headers={"x-e2er-token": "replay-session"}, timeout=10
        ).json()["pending"]
        text = json.dumps(review)
        assert "421" in text and "is not printed in the quote" in text, review
        ws = Path(p["workspace"])
        assert not (ws / "estimation_results.json").exists()  # nothing was pooled
        assert not (ws / "meta_studies.csv").exists()

        # The researcher corrects the number to what the paper prints and approves: the check runs
        # again, passes, and the review goes on to the synthesis.
        ext = ws / "extraction.json"
        ext.write_text(ext.read_text(encoding="utf-8").replace('"n_total": 421', '"n_total": 412'), encoding="utf-8")
        monkeypatch.delenv("E2ER_REPLAY_OVERRIDES")
        overrides.write_text("{}", encoding="utf-8")
        httpx.post(f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=TOKEN, timeout=30)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        gates = _gates(_events(tmp_path / "home" / ".e2er" / "papers.db", pid), "meta_extraction")
        assert gates and gates[-1]["passed"], gates
        assert json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))["k"] == 8
