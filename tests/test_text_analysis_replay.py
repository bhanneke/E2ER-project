"""The text-analysis template end to end, on Project Gutenberg texts recorded through e2er's connector.

The text scenario (tests/fixtures/replay/text) replays a study of the vocabulary
of fear in six works of short fiction (Project Gutenberg 41, 932, 11231, 43,
375, 1952) under the shipped template ``text-analysis``: the data architect's
corpus design is checked and read by the researcher before the corpus is
built; the data analyst's corpus is checked document by document (source,
licence, SHA-256, tokens); the analysis is recounted from the corpus (term
counts, keyness, collocations, dictionary hits, topic stability across seeds);
the text validator's judgements of the dictionary's sample give its precision;
the figures are re-read from the results. Then the panel, publish offline,
``e2er verify`` (results contract and the recount on the exported corpus) and
``e2er reproduce`` with the recorded seeds.

Two variations: a dictionary changed after the design (the analysis uses a
longer word list than the one frozen before it), which stops the run at the
results check until the analysis is sent back; and a validator that leaves an
item of the sample unjudged, sent back once and then stopping the run.
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

TEXT = FIXTURES / "text"
SCENARIO = json.loads((TEXT / "scenario.json").read_text(encoding="utf-8"))
PANEL = ["methods_reviewer", "data_reviewer", "plausibility_reviewer", "writing_reviewer", "technical_reviewer"]
HEADERS = {"x-e2er-token": "replay-session"}


def _events(db: Path, pid: str) -> list[tuple[str, str, dict]]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT event_type, specialist, payload FROM pipeline_events WHERE paper_id = ? ORDER BY id", (pid,)
        ).fetchall()
    finally:
        con.close()
    return [(e, s or "", json.loads(p) if p else {}) for e, s, p in rows]


def _gates(events: list[tuple[str, str, dict]], gate: str) -> list[dict]:
    return [pl for e, _s, pl in events if e in ("gate_enforced", "gate_shadow") and pl.get("gate") == gate]


def _start(api: str) -> str:
    body = {
        "title": SCENARIO["title"],
        "research_question": SCENARIO["research_question"],
        "mode": "single_pass",
        "pipeline": SCENARIO["template"],
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
    }
    r = httpx.post(f"{api}/api/papers", json=body, headers=HEADERS, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["paper_id"]


def _cli(tmp_path: Path, study: Path, *args: str, timeout: int = 300, extra: dict | None = None):
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    return subprocess.run(
        [sys.executable, "-m", "tests.replay.cli", *args],
        cwd=study,
        env={**env, **(extra or {})},
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_a_text_study_replays_to_the_end_with_its_corpus_counts_and_validation_checked(tmp_path: Path):
    with _replay_server(tmp_path, "text", []) as (api, study):
        pid = _start(api)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == ["review_design", "review_draft"]
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)

        # Every check passed, in the order of the work.
        for gate in ("corpus_design", "corpus", "text_results", "text_validation", "estimation", "figure_data"):
            found = _gates(events, gate)
            assert found and all(g["passed"] for g in found), (gate, found)
        order = [(e, s, pl.get("gate")) for e, s, pl in events if e in ("specialist_start", "gate_enforced")]
        designed = order.index(("gate_enforced", "", "corpus_design"))
        assert order.index(("specialist_start", "data_architect", None)) < designed
        assert designed < order.index(("specialist_start", "data_analyst", None))
        built = order.index(("gate_enforced", "", "corpus"))
        assert built < order.index(("specialist_start", "econometrics_specialist", None))
        validated = order.index(("gate_enforced", "", "text_validation"))
        assert order.index(("specialist_start", "text_validator", None)) < validated
        assert validated < order.index(("specialist_start", "paper_drafter", None))

        # The corpus as e2er computed it, and what the results say.
        corpus = json.loads((ws / "corpus_check.json").read_text(encoding="utf-8"))
        assert (corpus["n_documents"], corpus["n_tokens"], corpus["n_types"]) == (6, 69870, 8691)
        assert set(corpus["documents"]) == {"pg41", "pg932", "pg11231", "pg43", "pg375", "pg1952"}
        assert set(corpus["files_sha256"]) == {"stopwords.txt"}
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
        assert results["result_kind"] == "text" and not (ws / "identification_spec.json").exists()
        check = json.loads((ws / "text_check.json").read_text(encoding="utf-8"))
        assert check["passed"] and check["stats"]["keyness_late"] == 15 and check["stats"]["topics_stability"] == 1.0
        validation = json.loads((ws / "text_validation_check.json").read_text(encoding="utf-8"))
        assert validation["measures"]["fear_words"] == {"n_items": 20, "n_correct": 15, "precision": 0.75}

        # The figures were re-read from the results and rendered; tables traced; the template's panel.
        figure_check = json.loads((ws / "figure_check.json").read_text(encoding="utf-8"))
        assert figure_check["passed"] and len(figure_check["figures"]) == 6
        report = json.loads((ws / "figure_render_report.json").read_text(encoding="utf-8"))
        assert {"fig_fear_by_year.pdf", "fig_keyness.pdf", "fig_topics.pdf"} <= set(report["rendered"]), report
        nv = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert nv["passed"] and nv["mismatched"] == 0 and nv["matched"] >= 40, nv
        assert "said & 162 & 72 & 31.49 & 1.10 & 3" in (ws / "tables" / "keyness.tex").read_text(encoding="utf-8")
        agg = json.loads((ws / "review_aggregation.json").read_text(encoding="utf-8"))
        assert sorted(s["reviewer"] for s in agg["panel"]["scores"]) == sorted(PANEL)
        ran = {s for e, s, _pl in events if e == "specialist_start"}
        assert not ran & {"identification_strategist", "identification_reviewer", "mechanism_reviewer"}
        core = next(pl for e, _s, pl in events if e == "template_components")["core"]
        assert core["results"] == "text" and core["causal"] is False and core["base_skill"] == "base/researcher"

    # Published offline, verified (the recount runs again on the exported corpus), reproduced.
    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    for name in (
        "design/corpus_design.json",
        "data/corpus_manifest.json",
        "results/corpus_check.json",
        "results/text_validation.json",
        "results/validation_sample.json",
    ):
        assert (bundle / name).is_file(), name
    db = tmp_path / "home" / ".e2er" / "papers.db"
    out = _cli(
        tmp_path,
        study,
        *["publish", str(bundle), "--owner", "replay", "--project", "text", "--name", "Replay", "--offline"],
        *["--no-stamp", "--out", str(tmp_path / "entry"), "--db", str(db)],
    )
    assert out.returncode == 0, out.stdout + out.stderr
    out = _cli(tmp_path, study, "verify", str(bundle))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[PASS] numbers" in out.stdout and "[PASS] results contract" in out.stdout, out.stdout
    assert "[PASS] method checks" in out.stdout and "recounted from the corpus" in out.stdout, out.stdout

    # A count changed after the export no longer follows from the corpus.
    tampered = tmp_path / "tampered"
    shutil.copytree(bundle, tampered)
    res = tampered / "results" / "estimation_results.json"
    doc = json.loads(res.read_text(encoding="utf-8"))
    doc["models"]["keyness_late"]["outputs"]["terms"][0]["g2"] += 5
    res.write_text(json.dumps(doc), encoding="utf-8")
    out = _cli(tmp_path, study, "verify", str(tampered))
    assert "[FAIL] method checks" in out.stdout and "(m)" in out.stdout, out.stdout

    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    uv_dirs = {}
    for var, cmd in (("UV_CACHE_DIR", "cache"), ("UV_PYTHON_INSTALL_DIR", "python")):
        found = subprocess.run(["uv", cmd, "dir"], capture_output=True, text=True, env={**os.environ, "NO_COLOR": "1"})
        if found.returncode == 0 and found.stdout.strip():
            uv_dirs[var] = found.stdout.strip()
    out = _cli(tmp_path, study, "reproduce", str(bundle), timeout=900, extra={"UV_OFFLINE": "1", **uv_dirs})
    if "could not install" in out.stdout or "could not create the environment" in out.stdout:
        pytest.skip("the requirements or Python are not in uv's cache (offline): " + out.stdout[-400:])
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Reproduced" in out.stdout, out.stdout


def _overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc: dict) -> None:
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(path))


def _stop(api: str, pid: str, at: str) -> tuple[dict, dict, list[str]]:
    stops = []
    for _ in range(4):
        p = _wait(api, pid)
        pending = httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]
        assert pending, (p.get("status"), p.get("last_error"), stops)
        stops.append(pending["stage"])
        if pending["stage"] == at:
            return p, pending, stops
        r = httpx.post(f"{api}/api/papers/{pid}/review", json={"action": "approve"}, headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
    raise AssertionError(f"the run did not stop at {at}: {stops}")


def test_a_dictionary_changed_after_the_design_stops_the_run_until_the_analysis_is_redone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The analysis adds 'ghost*' to the fear dictionary: the results check refuses it, twice, then stops."""
    # The widened analysis's results are computed here from that script and the recorded corpus,
    # as the run would compute them.
    edits = [
        [
            'entries = ANALYSES["fear_words"]["dictionary"]["terms"]',
            'entries = ["ghost*"] + ANALYSES["fear_words"]["dictionary"]["terms"]',
        ],
        [
            '"dictionary": ANALYSES["fear_words"]["dictionary"],',
            '"dictionary": {**ANALYSES["fear_words"]["dictionary"], "terms": entries},',
        ],
    ]
    econ, analyst = TEXT / "files" / "econometrics_specialist", TEXT / "files" / "data_analyst"
    run = tmp_path / "widened"
    run.mkdir()
    for f in (analyst / "data.db", analyst / "stopwords.txt", TEXT / "files" / "data_architect" / "corpus_design.json"):
        shutil.copy(f, run / f.name)
    script = (econ / "run_estimation.py").read_text(encoding="utf-8")
    for old, new in edits:
        assert old in script
        script = script.replace(old, new)
    (run / "run_estimation.py").write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, "run_estimation.py"], cwd=run, check=True, capture_output=True)
    replace = {"run_estimation.py": edits}
    for name in ("estimation_results.json", "validation_sample.json"):
        recorded = (econ / name).read_text(encoding="utf-8")
        replace[name] = [[recorded, (run / name).read_text(encoding="utf-8")]]
    assert '"ghost*"' in replace["estimation_results.json"][0][1]
    widened = {"replace": replace}
    _overrides(tmp_path, monkeypatch, {"econometrics_specialist": {"attempts": [widened, widened]}})
    with _replay_server(tmp_path, "text", []) as (api, _study):
        pid = _start(api)
        p, pending, stops = _stop(api, pid, "text_results_gate")
        assert stops == ["review_design", "text_results_gate"]
        assert any("the dictionary is not the one corpus_design.json froze" in r for r in pending["reasons"])
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        # on_fail = "retry": the analysis was sent back once with the reasons before the run stopped.
        assert [g["passed"] for g in _gates(events, "text_results")] == [False, False]
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("econometrics_specialist") == 2 and "paper_drafter" not in started
        assert not json.loads((ws / "text_check.json").read_text(encoding="utf-8"))["passed"]

        # Sent back by the researcher, the analysis is redone with the frozen dictionary and the run goes on.
        r = httpx.post(
            f"{api}/api/papers/{pid}/review",
            json={"action": "send_back", "step": "econometrics_specialist", "remark": "Use the design's dictionary."},
            headers=HEADERS,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        p, more = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), more)
        assert json.loads((ws / "text_check.json").read_text(encoding="utf-8"))["passed"]


def test_an_unjudged_item_of_the_sample_sends_the_validator_back_and_then_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = TEXT / "files" / "text_validator" / "text_validation.json"
    recorded = path.read_text(encoding="utf-8")
    judged = json.loads(recorded)
    assert json.dumps(judged, indent=2, ensure_ascii=False) == recorded
    judged["fear_words"]["items"].pop()
    drop = {"replace": {"text_validation.json": [[recorded, json.dumps(judged, indent=2, ensure_ascii=False)]]}}
    _overrides(tmp_path, monkeypatch, {"text_validator": {"attempts": [drop, drop]}})
    with _replay_server(tmp_path, "text", []) as (api, _study):
        pid = _start(api)
        p, pending, stops = _stop(api, pid, "text_validation_gate")
        assert stops == ["review_design", "text_validation_gate"]
        assert any("1 item(s) of the sample are not judged" in r for r in pending["reasons"]), pending["reasons"]
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        assert [g["passed"] for g in _gates(events, "text_validation")] == [False, False]
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("text_validator") == 2 and "paper_drafter" not in started


def test_specialists_the_plan_left_out_are_sent_out_by_the_checks_that_need_their_work(tmp_path: Path):
    """The strategist plans neither the data analyst nor the text validator (as in the live run).

    The corpus check runs before the analysis, finds no corpus and sends the data analyst out for its
    whole task. The validation check must pass before the draft (``before = ["paper_drafter"]``): the
    text validator is sent out before the drafter is dispatched, the check passes at its first run,
    and the draft is written once, on validated results (no send-back).
    """
    with _replay_server(tmp_path, "text-unplanned", []) as (api, _study):
        pid = _start(api)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == ["review_design", "review_draft"]
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        assert [g["passed"] for g in _gates(events, "corpus")] == [False, True]
        assert [g["passed"] for g in _gates(events, "text_validation")] == [True]
        order = [(e, s, pl.get("gate")) for e, s, pl in events if e in ("specialist_start", "gate_enforced")]
        analyst = order.index(("specialist_start", "data_analyst", None))
        assert analyst < order.index(("specialist_start", "econometrics_specialist", None))
        validator = order.index(("specialist_start", "text_validator", None))
        validated = order.index(("gate_enforced", "", "text_validation"))
        assert validator < validated < order.index(("specialist_start", "paper_drafter", None))
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("data_analyst") == 1 and started.count("text_validator") == 1
        assert started.count("paper_drafter") == 1
        sent = [pl for e, _s, pl in events if e == "sent_out_before"]
        assert sent == [{"check": "text_validation", "specialists": ["text_validator"], "before": ["paper_drafter"]}]


def test_checks_of_the_results_wait_for_an_analysis_left_to_the_iterative_rounds(tmp_path: Path):
    """The initial phase ends with the design (as in the live run): the corpus check sends the data
    analyst out, and the checks of the results run only once the first round has analysed."""
    body = {
        "title": SCENARIO["title"],
        "research_question": SCENARIO["research_question"],
        "mode": "iterative",
        "pipeline": SCENARIO["template"],
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
    }
    with _replay_server(tmp_path, "text-design-first", []) as (api, _study):
        r = httpx.post(f"{api}/api/papers", json=body, headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["paper_id"]
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        assert [g["passed"] for g in _gates(events, "corpus")] == [False, True]
        assert all(g["passed"] for g in _gates(events, "text_results")), _gates(events, "text_results")
        assert all(g["passed"] for g in _gates(events, "text_validation"))
        order = [(e, s, pl.get("gate")) for e, s, pl in events if e in ("specialist_start", "gate_enforced")]
        analysed = order.index(("specialist_start", "econometrics_specialist", None))
        assert analysed < order.index(("gate_enforced", "", "text_results"))
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("econometrics_specialist") == 1 and started.count("data_analyst") == 1


def test_a_round_that_leaves_out_the_validator_gets_it_before_the_draft(tmp_path: Path):
    """The iterative mode: the first round analyses and drafts without the text validator (the 2026-10-11
    live run). The validation check must pass before the draft, so the validator is sent out before the
    drafter is dispatched, the check passes at its first run, and the draft is written once."""
    body = {
        "title": SCENARIO["title"],
        "research_question": SCENARIO["research_question"],
        "mode": "iterative",
        "pipeline": SCENARIO["template"],
        "acknowledge_unproven_tuple": True,
        "max_cost_usd": 5,
    }
    with _replay_server(tmp_path, "text-iterative-unplanned", []) as (api, _study):
        r = httpx.post(f"{api}/api/papers", json=body, headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["paper_id"]
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        assert [g["passed"] for g in _gates(events, "text_validation")] == [True]
        assert all(g["passed"] for g in _gates(events, "text_results"))
        order = [(e, s, pl.get("gate")) for e, s, pl in events if e in ("specialist_start", "gate_enforced")]
        drafted = order.index(("specialist_start", "paper_drafter", None))
        assert order.index(("specialist_start", "text_validator", None)) < drafted
        assert order.index(("gate_enforced", "", "text_validation")) < drafted
        assert order.index(("gate_enforced", "", "text_results")) < drafted
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("text_validator") == 1 and started.count("paper_drafter") == 1
        assert started.count("econometrics_specialist") == 1


def test_the_template_method_sources_are_in_the_bibliography_and_the_nndsvd_note_is_kept(tmp_path: Path):
    """The text template's nine method sources are in literature.bib from the start, tagged as the
    template's; the results check notes that NMF from nndsvd ignores the seed, and the draft (which says
    so) passes the phrase check."""
    with _replay_server(tmp_path, "text", []) as (api, _study):
        pid = _start(api)
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        ws = Path(p["workspace"])
        events = _events(tmp_path / "home" / ".e2er" / "papers.db", pid)
        added = next(pl for e, _s, pl in events if e == "method_sources")["keys"]
        assert {"dunning1993accurate", "lee1999learning", "grimmer2013text", "blei2003latent"} <= set(added)
        assert len(added) == 9
        bib = (ws / "literature.bib").read_text(encoding="utf-8")
        assert bib.count("e2er_source = {template}") == 9 and "doi = {10.1038/44565}" in bib
        check = json.loads((ws / "text_check.json").read_text(encoding="utf-8"))
        assert check["seed_independent_models"] == ["topics"]
        assert any("ignores the seed" in n for n in check["notes"])
        started = [s for e, s, _pl in events if e == "specialist_start"]
        assert started.count("paper_drafter") == 1
