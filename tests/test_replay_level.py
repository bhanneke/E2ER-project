"""The replay level of the end-to-end stories (tests/replay): the backend, the recorded sandbox, a full run.

The cross-repository stories live in the site repository (tests/e2e); these
tests keep the replay itself in step with the pipeline, so a change here that
breaks it fails in e2er's own suite.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from src.modules.llm.tools import FileToolHandler
from tests.replay.backend import FIXTURES, ReplayBackend

ROOT = Path(__file__).resolve().parent.parent
FOMC = json.loads((FIXTURES / "fomc" / "scenario.json").read_text(encoding="utf-8"))
REPL = json.loads((FIXTURES / "replication" / "scenario.json").read_text(encoding="utf-8"))


async def _call(backend: ReplayBackend, ws: Path, specialist: str | None, prompt: str = "", paper_id: str = "p-1"):
    return await backend.tool_loop(
        system="",
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        tool_handler=FileToolHandler(ws),
        paper_id=paper_id,
        specialist=specialist,
    )


async def test_a_specialist_writes_the_files_the_recorded_run_wrote(tmp_path: Path):
    ReplayBackend._attempts.clear()
    b = ReplayBackend("fomc")
    r = await _call(b, tmp_path, "idea_developer")
    assert r.success and r.usage.output_tokens == FOMC["specialists"]["idea_developer"]["usage"]["output_tokens"]
    fixture = (FIXTURES / "fomc" / "files" / "idea_developer" / "paper_plan.md").read_bytes()
    assert (tmp_path / "paper_plan.md").read_bytes() == fixture

    r = await _call(b, tmp_path, "econometrics_specialist", paper_id="paper-42")
    script = (tmp_path / "run_estimation.py").read_text(encoding="utf-8")
    assert "@@" not in script and str(tmp_path.resolve()) in script
    assert json.loads((tmp_path / "estimation_results.json").read_text(encoding="utf-8"))

    r = await _call(b, tmp_path, "data_analyst")
    assert (tmp_path / "data.db").read_bytes() == (FIXTURES / "fomc/files/data_analyst/data.db").read_bytes()


async def test_a_call_without_a_recording_fails_visibly(tmp_path: Path):
    r = await _call(ReplayBackend("fomc"), tmp_path, "theory_specialist")
    assert not r.success and "no recording for theory_specialist" in (r.error or "")
    r = await _call(ReplayBackend("fomc"), tmp_path, None, "Summarise this corpus.")
    assert not r.success and "no recording" in (r.error or "")


async def test_the_strategist_answers_with_the_recorded_plan(tmp_path: Path):
    r = await _call(ReplayBackend("fomc"), tmp_path, None, "Paper status: designing\n...Decide what to do next.")
    d = json.loads(r.output)
    groups: dict[int, list[str]] = {}
    for wo in d["work_orders"]:
        groups.setdefault(wo["parallel_group"], []).append(wo["specialist"])
    assert [groups[g] for g in sorted(groups)] == FOMC["initial_groups"]
    r = await _call(ReplayBackend("fomc"), tmp_path, None, "Paper status: in_progress\nDecide what to do next.")
    assert json.loads(r.output)["action"] == "complete"


async def test_overrides_vary_one_attempt_and_then_replay_the_recording(tmp_path: Path, monkeypatch):
    ReplayBackend._attempts.clear()
    over = tmp_path / "over.json"
    over.write_text(
        json.dumps(
            {
                "identification_strategist": {
                    "attempts": [{"replace": {"event_design.json": [['"2020-03-16"', '"2020-03-15"']]}}, {"fail": "x"}]
                }
            }
        )
    )
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(over))
    ws = tmp_path / "ws"
    b = ReplayBackend("fomc")
    assert (await _call(b, ws, "identification_strategist")).success
    assert '"2020-03-15"' in (ws / "event_design.json").read_text(encoding="utf-8")
    second = await _call(b, ws, "identification_strategist")
    assert not second.success and second.error == "replay: x"
    assert (await _call(b, ws, "identification_strategist")).success
    assert '"2020-03-16"' in (ws / "event_design.json").read_text(encoding="utf-8")


async def test_a_wait_override_makes_the_attempt_take_that_long(tmp_path: Path, monkeypatch):
    ReplayBackend._attempts.clear()
    over = tmp_path / "over.json"
    over.write_text(json.dumps({"idea_developer": {"attempts": [{"wait": 0.3}]}}))
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(over))
    b = ReplayBackend("fomc")
    t0 = time.monotonic()
    assert (await _call(b, tmp_path / "ws", "idea_developer")).success
    assert time.monotonic() - t0 >= 0.3
    t0 = time.monotonic()
    assert (await _call(b, tmp_path / "ws", "idea_developer")).success
    assert time.monotonic() - t0 < 0.3


async def test_the_replay_stands_in_for_the_backend_and_model_the_run_names(tmp_path: Path, monkeypatch):
    """A run on codex under the replay level is recorded as a run on codex with its model (`backend_identity`)."""
    from src.config import get_settings
    from src.modules.llm import registry
    from tests.replay.harness import _patch_backend

    monkeypatch.setattr(registry, "get_backend", registry.get_backend)  # restored after the test
    monkeypatch.setenv("CODEX_MODEL", "gpt-6-luna")
    get_settings.cache_clear()
    try:
        _patch_backend()
        settings = get_settings()
        b = registry.get_backend(settings, "codex", "gpt-6-luna")
        assert isinstance(b, ReplayBackend)
        assert b.identity() == {"backend": "codex", "model": "gpt-6-luna", "replay": "fomc"}
        # No model named: the backend's configured one, as the real registry resolves it.
        assert registry.get_backend(settings, "codex").identity()["model"] == "gpt-6-luna"
        assert registry.get_backend(settings, "claude_code", "sonnet").identity()["backend"] == "claude_code"
    finally:
        get_settings.cache_clear()
    # Without a backend (the unit tests' own instances): the recording's model.
    assert ReplayBackend("fomc").identity()["model"] == FOMC["model"]


async def test_overrides_under_backends_vary_only_that_backends_runs(tmp_path: Path, monkeypatch):
    ReplayBackend._attempts.clear()
    over = tmp_path / "over.json"
    over.write_text(
        json.dumps(
            {
                "identification_strategist": {"attempts": [{"fail": "top level"}]},
                "backends": {
                    "codex": {
                        "identification_strategist": {
                            "attempts": [
                                {"replace": {"identification_spec.json": [['"outcome": "car",', '"outcome": "x",']]}}
                            ]
                        }
                    }
                },
            }
        )
    )
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(over))
    codex, claude = tmp_path / "codex", tmp_path / "claude"
    assert (await _call(ReplayBackend("fomc", backend="codex"), codex, "identification_strategist")).success
    assert '"outcome": "x"' in (codex / "identification_spec.json").read_text(encoding="utf-8")
    # Another backend (and a paper of its own) gets the top-level entry.
    r = await _call(ReplayBackend("fomc", backend="claude_code"), claude, "identification_strategist", paper_id="p-2")
    assert not r.success and r.error == "replay: top level"


async def test_the_two_backend_fixture_gives_compare_a_real_difference(tmp_path: Path, monkeypatch):
    """tests/fixtures/replay/fomc/two-backends.json (E2E-20): one run reports the declared treatment term with its
    standard error, the other three means; `e2er compare` marks the second with † and counts the gaps as differences."""
    from src.core.compare import build_comparison, load_run_record, render_report

    ReplayBackend._attempts.clear()
    monkeypatch.setenv("E2ER_REPLAY_OVERRIDES", str(FIXTURES / "fomc" / "two-backends.json"))
    records = []
    for backend, model in (("claude_code", "sonnet"), ("codex", "gpt-6-luna")):
        ws, bundle = tmp_path / backend / "ws", tmp_path / backend / "bundle"
        b = ReplayBackend("fomc", backend=backend, model=model)
        for sp in ("identification_strategist", "econometrics_specialist", "idea_developer"):
            assert (await _call(b, ws, sp, paper_id=backend)).success
        (bundle / "design").mkdir(parents=True)
        (bundle / "results").mkdir()
        shutil.copy(ws / "identification_spec.json", bundle / "design")
        shutil.copy(ws / "paper_plan.md", bundle / "design")
        shutil.copy(ws / "estimation_results.json", bundle / "results")
        records.append(load_run_record(bundle, f"{backend}/rep-1", backend_hint=backend, model_hint=model))
    comparison = build_comparison(records)
    assert comparison["divergent_fields"] == ["outcome", "coef_term", "coef_estimate", "coef_se", "coef_p_value"]
    assert [r["coef_fallback"] for r in comparison["runs"]] == [False, True]
    assert not comparison["variance"]["available"]
    report = render_report(comparison)
    # A bare bundle has no provenance.json, so no governance.
    assert "| claude_code/rep-1 | claude_code | sonnet | n/a |" in report
    assert "| codex/rep-1 | codex | gpt-6-luna | n/a |" in report
    assert "| `coef_estimate` ⚠️ | 0.50 | -0.02084 | -0.7108 † |" in report
    assert "| `coef_se` ⚠️ | 0.50 | 0.04367 | n/a † |" in report


def _fetched_replication(ws: Path) -> None:
    """The package of the replication fixture as the fetch step leaves it (without Zenodo)."""
    from src.core.pipeline.replication import hash_tree

    rec_dir = FIXTURES / "replication" / "zenodo" / REPL["zenodo"]["record_id"]
    record = json.loads((rec_dir / "record.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(rec_dir / "files" / record["files"][0]["key"]) as zf:
        zf.extractall(ws / "package")
    tree = hash_tree(ws / "package")
    (ws / "package_manifest.json").write_text(
        json.dumps(
            {
                "record_id": REPL["zenodo"]["record_id"],
                "publication_date": record["metadata"]["publication_date"],
                "package_files": [{"path": p, **v} for p, v in tree.items()],
                "files": [],
            }
        )
    )
    shutil.copy(FIXTURES / "replication/files/replication_planner/replication_plan.json", ws / "replication_plan.json")


def test_the_recorded_docker_rebuilds_what_the_reproduction_report_compares(tmp_path: Path):
    """The fixture is consistent: the real sandbox code with the recorded Docker, then the real reproduction check."""
    from src.core.pipeline.reproduction import check_reproduction
    from src.core.pipeline.sandbox import run_sandbox
    from tests.replay.harness import RecordedDocker

    _fetched_replication(tmp_path)
    docker = RecordedDocker(FIXTURES / "replication")
    r = run_sandbox(tmp_path, runner=docker, docker="docker")
    assert r.passed, r.reasons
    log = json.loads((tmp_path / "sandbox_log.json").read_text(encoding="utf-8"))
    assert [x["status"] for x in log["runs"]] == ["ok"] * len(REPL["sandbox"]["entry_points"])
    assert log["install"]["installed"] == REPL["sandbox"]["installed"] and log["package_intact"]
    for name in ("reproduction_report.json", "reproduction_report.md"):
        shutil.copy(FIXTURES / "replication/files/reproduction_comparer" / name, tmp_path / name)
    check = check_reproduction(tmp_path)
    assert check.passed, check.reasons


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.contextmanager
def _replay_server(tmp_path: Path, scenario: str, settings: list[str]):
    """`e2er serve` under the replay level for a study folder in tmp; yields (api, study folder)."""
    port = _free_port()
    study, home = tmp_path / "study", tmp_path / "home"
    study.mkdir(exist_ok=True)
    home.mkdir(exist_ok=True)
    (study / ".env").write_text(
        "\n".join(
            [
                "LLM_BACKEND=claude_code",
                "CLAUDE_CODE_MODEL=claude-haiku-4-5-20251001",
                f"WORKSPACE_ROOT={study / 'workspaces'}",
                f"OUTPUT_DIR={study / 'exports'}",
                f"PORT={port}",
                "CORPUS_AUTOINGEST=false",
                "LITERATURE_ACQUIRE_LIMIT=0",
                *settings,
            ]
        )
        + "\n"
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(ROOT),
        "E2ER_REPLAY_SCENARIO": scenario,
        "E2ER_REPLAY_NETLOG": str(tmp_path / "net.txt"),
        "E2ER_SKIP_SETUP_REDIRECT": "1",
        "E2ER_SESSION_TOKEN": "replay-session",
        # Matplotlib builds its font cache in a fresh HOME, inside the server's event loop: about ten
        # seconds in which the server does not answer. Its cache of the real home is reused.
        "MPLCONFIGDIR": os.environ.get("MPLCONFIGDIR") or str(Path.home() / ".matplotlib"),
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    env.pop("TECTONIC_CACHE_DIR", None)
    server = subprocess.Popen(
        [sys.executable, "-m", "tests.replay.cli", "serve", "--no-browser", "--port", str(port)],
        cwd=study,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    api = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{api}/api/papers", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        yield api, study
    finally:
        server.terminate()
        server.wait(timeout=10)


def _approve_to_the_end(api: str, pid: str) -> tuple[dict, list[str]]:
    stops = []
    for _ in range(8):
        p = _wait(api, pid)
        if p["status"] == "completed":
            break
        stage = httpx.get(f"{api}/api/papers/{pid}/review", timeout=10).json()["pending"]["stage"]
        stops.append(stage)
        r = httpx.post(
            f"{api}/api/papers/{pid}/review",
            json={"action": "approve"},
            headers={"x-e2er-token": "replay-session"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
    return p, stops


def test_the_fomc_event_study_replays_to_the_end_through_the_server(tmp_path: Path):
    """`e2er serve` under the replay level: the event-study template from the question to a completed run."""
    study = tmp_path / "study"
    (study / "data").mkdir(parents=True)
    (study / "data" / "fomc_announcement_dates.csv").write_text("date\n2015-12-16\n", encoding="utf-8")
    # As in the recorded run: a FRED key, and the researcher's own FOMC dates in the data
    # folder (the data architect may only plan tables from sources the study has).
    with _replay_server(tmp_path, "fomc", ["FRED_API_KEY=replay-key", f"LOCAL_DATA_DIR={study / 'data'}"]) as (api, _):
        body = {
            "title": FOMC["title"],
            "research_question": FOMC["research_question"],
            "mode": "single_pass",
            "pipeline": FOMC["template"],
            "acknowledge_unproven_tuple": True,
            "max_cost_usd": 5,
        }
        pid = httpx.post(f"{api}/api/papers", json=body, headers={"x-e2er-token": "replay-session"}, timeout=30).json()[
            "paper_id"
        ]
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", p
        assert stops == ["review_design", "preregister", "review_draft"]
        ws = Path(p["workspace"])  # named after the date and title since 0.14.0
        assert ws.parent == (study / "workspaces").resolve() and ws.name != pid
        assert json.loads((ws / "estimation_results.json").read_text(encoding="utf-8")) == json.loads(
            (FIXTURES / "fomc/files/econometrics_specialist/estimation_results.json").read_text(encoding="utf-8")
        )
        assert (ws / "preregistration.lock.json").is_file() and (ws / "review_aggregation.json").is_file()
        blocked = (tmp_path / "net.txt").read_text() if (tmp_path / "net.txt").exists() else ""
        assert "anthropic" not in blocked and "zenodo" not in blocked


def test_a_study_with_chosen_data_and_papers_replays_to_the_end(tmp_path: Path):
    """The byod scenario: the researcher chooses 3 of 4 data files and 2 PDFs + 1 of 2 .bib entries.

    Exactly those reach the study: the 3 files are staged and imported into data.db
    (the recorded data analyst adds its tables without replacing them), the 3 papers
    are in literature.bib with the keys the draft cites (tagged as the researcher's),
    the citation check finds every cited key, and the run page's panel lists them.
    """
    byod = json.loads((FIXTURES / "byod" / "scenario.json").read_text(encoding="utf-8"))
    inputs = FIXTURES / "byod" / "inputs"
    study = tmp_path / "study"
    shutil.copytree(inputs / "data", study / "data")
    shutil.copytree(inputs / "literature", study / "literature")
    lit = (study / "literature").resolve()
    with _replay_server(
        tmp_path,
        "byod",
        ["FRED_API_KEY=replay-key", f"LOCAL_DATA_DIR={study / 'data'}", f"LITERATURE_DIR={lit}"],
    ) as (api, _):
        papers = [
            f"bib:{lit / 'refs.bib'}#{p.split('#')[1]}" if "#" in p else str(lit / p) for p in byod["inputs"]["papers"]
        ]
        body = {
            "title": FOMC["title"],
            "research_question": FOMC["research_question"],
            "mode": "single_pass",
            "pipeline": FOMC["template"],
            "acknowledge_unproven_tuple": True,
            "data_files": [str((study / "data" / n).resolve()) for n in byod["inputs"]["data"]],
            "papers": papers,
        }
        r = httpx.post(f"{api}/api/papers", json=body, headers={"x-e2er-token": "replay-session"}, timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["paper_id"]
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        ws = Path(p["workspace"])

        assert sorted(x.name for x in (ws / "data").iterdir()) == sorted(byod["inputs"]["data"])
        import sqlite3

        con = sqlite3.connect(ws / "data.db")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        con.close()
        assert {"bank_tickers", "target_rate_changes", "fomc_announcement_dates"} <= tables
        assert {"spy_prices", "dgs2"} <= tables, "the recorded analyst's tables join the researcher's"
        assert not any("unrelated" in t for t in tables)
        loads = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))["loads"]
        mine = sorted(x["series"] for x in loads if x["connector"] == "data-folder")
        assert mine == sorted(byod["inputs"]["data"])

        from src.core.pipeline.verify_citations import load_bib

        bib = load_bib(ws / "literature.bib")
        assert set(bib) == set(byod["inputs"]["cited_keys"])
        assert {f["e2er_source"] for f in bib.values()} == {"researcher"}
        integrity = json.loads((ws / "citation_integrity.json").read_text(encoding="utf-8"))
        assert integrity["total_cites"] == 3 and integrity["missing_in_bib"] == 0

        panel = httpx.get(
            f"{api}/htmx/papers/{pid}/inputs", headers={"x-e2er-token": "replay-session"}, timeout=10
        ).text
        assert "Your papers (3)" in panel and "target_rate_changes.csv" in panel
        assert "Not searched" not in panel and "unrelated_survey" not in panel


def _wait(api: str, pid: str) -> dict:
    for _ in range(600):
        p = httpx.get(f"{api}/api/papers/{pid}", timeout=30).json()
        if p["status"] in {"paused", "completed", "failed", "rejected", "cancelled"} and not p.get("run_owner"):
            return p
        time.sleep(0.2)
    pytest.fail(f"the replayed run did not stop: {p}")


ITER = json.loads((FIXTURES / "fomc-iterative" / "scenario.json").read_text(encoding="utf-8"))


async def test_the_iterative_scenario_scripts_the_rounds_the_ceiling_checks_and_the_self_critique(tmp_path: Path):
    """Round n's decision and the ceiling check after it are chosen by the round number in the prompt."""
    b = ReplayBackend("fomc-iterative")

    def decide(n: int) -> str:
        return f"Paper status: in_progress\nIteration: {n}\nDecide what to do next."

    r1 = json.loads((await _call(b, tmp_path, None, decide(1))).output)
    assert r1["action"] == "dispatch_parallel"
    assert [w["specialist"] for w in r1["work_orders"]] == ["econometrics_specialist", "paper_drafter"]
    r2 = json.loads((await _call(b, tmp_path, None, decide(2))).output)
    assert [w["specialist"] for w in r2["work_orders"]] == ["section_writer"]
    r3 = json.loads((await _call(b, tmp_path, None, decide(3))).output)
    assert r3["action"] == "complete"
    c1 = json.loads((await _call(b, tmp_path, None, "Iteration: 1, Pivots used: 0\n... verdict")).output)
    c2 = json.loads((await _call(b, tmp_path, None, "Iteration: 2, Pivots used: 0\n... verdict")).output)
    assert (c1["verdict"], c2["verdict"]) == ("continue", "pivot")
    assert [w["specialist"] for w in c2["suggested_pivots"]] == ["abstract_writer"]
    attack = json.loads((await _call(b, tmp_path, None, "Find all flaws. Output JSON SelfAttackReport.")).output)
    assert [f["severity"] for f in attack["findings"]] == [7, 4]
    # The base scenario is unchanged: no rounds, proceed to review, no findings.
    fomc = ReplayBackend("fomc")
    base = json.loads((await _call(fomc, tmp_path, None, "Iteration: 1, Pivots used: 0 verdict")).output)
    assert base["verdict"] == "proceed_to_review"


async def test_calls_replay_one_recording_per_call_and_then_the_last(tmp_path: Path):
    """``calls``: the targeted corrections after the self-critique, then the recorded ones after the review panel."""
    ReplayBackend._calls.clear()
    b = ReplayBackend("fomc-iterative")
    assert (await _call(b, tmp_path, "patch_revisor")).success
    first = json.loads((tmp_path / "paper_draft.tex.edits.json").read_text(encoding="utf-8"))
    assert [e["target"] for e in first] == ["section:introduction"]
    r = await _call(b, tmp_path, "patch_revisor")
    assert r.success and r.usage.output_tokens == FOMC["specialists"]["patch_revisor"]["usage"]["output_tokens"]
    assert json.loads((tmp_path / "paper_draft.tex.edits.json").read_text(encoding="utf-8")) == []
    assert (await _call(b, tmp_path, "patch_revisor")).success  # later calls: the last recording
    # The abstract: the recorded one first, the change of approach's second.
    assert (await _call(b, tmp_path, "abstract_writer")).success
    assert "secondary, non-pre-registered" in (tmp_path / "abstract.tex").read_text(encoding="utf-8")
    assert (await _call(b, tmp_path, "abstract_writer")).success
    assert "exploratory window" in (tmp_path / "abstract.tex").read_text(encoding="utf-8")


def test_the_iterative_mode_replays_to_the_end_through_the_server(tmp_path: Path):
    """`--mode iterative` on the current engine, end to end (the fomc-iterative scenario).

    Initial phase, round 1 (estimation confirmed, draft redone), ceiling check: another
    round; round 2 (a section rewritten), ceiling check: a change of approach (the
    abstract); then the estimation check, the draft review, the self-critique (one
    serious finding, corrected in the introduction), the polish, the review panel and
    the revision. The number check passes; the dossier and the run view say what each
    round did, the ceiling decisions and the change of approach in plain words.
    """
    import sqlite3

    from src.core.dossier import read_run
    from tests.test_dashboard_vocabulary import problems, visible_text

    study = tmp_path / "study"
    (study / "data").mkdir(parents=True)
    (study / "data" / "fomc_announcement_dates.csv").write_text("date\n2015-12-16\n", encoding="utf-8")
    files = FIXTURES / "fomc-iterative" / "files"
    with _replay_server(
        tmp_path, "fomc-iterative", ["FRED_API_KEY=replay-key", f"LOCAL_DATA_DIR={study / 'data'}"]
    ) as (api, _):
        body = {
            "title": FOMC["title"],
            "research_question": FOMC["research_question"],
            "mode": "iterative",
            "pipeline": FOMC["template"],
            "acknowledge_unproven_tuple": True,
            "max_cost_usd": 5,
        }
        pid = httpx.post(f"{api}/api/papers", json=body, headers={"x-e2er-token": "replay-session"}, timeout=30).json()[
            "paper_id"
        ]
        p, stops = _approve_to_the_end(api, pid)
        assert p["status"] == "completed", (p.get("last_error"), stops)
        assert stops == ["review_design", "preregister", "review_draft"]
        ws = Path(p["workspace"])

        db = tmp_path / "home" / ".e2er" / "papers.db"
        con = sqlite3.connect(db)
        rows = con.execute(
            "SELECT event_type, stage, specialist, payload FROM pipeline_events WHERE paper_id = ? "
            "ORDER BY created_at, rowid",
            (pid,),
        ).fetchall()
        con.close()
        phases = [st for et, st, _, _ in rows if et == "phase_start"]
        order = list(dict.fromkeys(phases))
        assert order == [
            "initial",
            "iterative",
            "estimation_gate",
            "self_attack",
            "polish",
            "review",
            "revision",
            "replication",
        ], order
        rec = {et: json.loads(pl) for et, _, _, pl in rows if et in ("pivot", "self_critique")}
        rounds = [json.loads(pl) for et, _, _, pl in rows if et == "improvement_round"]
        checks = [json.loads(pl) for et, _, _, pl in rows if et == "ceiling_check"]
        assert [(r["round"], r["specialists"]) for r in rounds] == [
            (1, ["econometrics_specialist", "paper_drafter"]),
            (2, ["section_writer"]),
        ]
        assert [(c["round"], c["verdict"]) for c in checks] == [(1, "continue"), (2, "pivot")]
        assert rec["pivot"]["specialists"] == ["abstract_writer"] and rec["pivot"]["round"] == 2
        assert rec["self_critique"] == {
            "findings": 2,
            "serious": 1,
            "max_severity": 7,
            "categories": ["framing", "numerics"],
            "corrections_made": 1,
            "corrections_failed": 0,
        }
        iterative = [sp for et, st, sp, _ in rows if et == "specialist_end" and sp]
        assert iterative.count("abstract_writer") == 2 and "section_writer" in iterative

        # What each step left in the draft: round 2's paragraph, the self-critique's correction
        # in the introduction, the change of approach's abstract; the polish notes the self-critique asked for.
        draft = (ws / "paper_draft.tex").read_text(encoding="utf-8")
        assert "do not grow with the yield surprise" in draft
        assert "which we did not pre-register and report as exploratory" in draft
        assert "However, a longer post-announcement window" not in draft
        assert (ws / "abstract.tex").read_text(encoding="utf-8") == (
            files / "abstract_writer.pivot" / "abstract.tex"
        ).read_text(encoding="utf-8")
        corrections = json.loads((ws / "self_attack_corrections.json").read_text(encoding="utf-8"))
        assert corrections["applied"] == 1 and not corrections["failed"]
        assert "report as exploratory" in corrections["diff"]
        assert sorted(x.name for x in ws.glob("polish_*.md")) == ["polish_formula.md", "polish_numerics.md"]
        # The number check passes on the revised draft: no table number differs from the results.
        numbers = json.loads((ws / "number_verification.json").read_text(encoding="utf-8"))
        assert numbers["passed"] and numbers["mismatched"] == 0 and numbers["matched"] > 0

        # The dossier's record of the run: each round, its ceiling check and the change of approach.
        run = read_run(db, pid)
        assert [(r["round"], r["label"], r["specialists"]) for r in run.rounds] == [
            (1, "Round 1", ["econometrics_specialist", "paper_drafter"]),
            (2, "Round 2", ["section_writer"]),
        ]
        assert run.rounds[0]["specialist_labels"] == ["Estimation", "Paper draft"]
        assert [(r["ceiling_check"]["verdict"], r["ceiling_check"]["decision"]) for r in run.rounds] == [
            ("continue", "another round"),
            ("pivot", "a change of approach"),
        ]
        assert run.rounds[1]["pivot"]["label"] == "Change of approach"
        assert run.rounds[1]["pivot"]["specialist_labels"] == ["Abstract"]
        in_rounds = [
            (s["specialist"], s["round"], s.get("pivot", False)) for s in run.workflow if s.get("phase") == "iterative"
        ]
        assert in_rounds == [
            ("econometrics_specialist", 1, False),
            ("paper_drafter", 1, False),
            ("section_writer", 2, False),
            ("abstract_writer", 2, True),
        ]
        critique = next(e for e in run.events if e["event"] == "self_critique")
        assert critique["label"] == "Self-critique" and critique["corrections_made"] == 1
        assert not any(s.get("round") for s in run.workflow if s.get("phase") != "iterative")

        # The run view: the rounds in plain words, no internal names.
        h = {"x-e2er-token": "replay-session"}
        live = httpx.get(f"{api}/htmx/papers/{pid}/live", headers=h, timeout=10).text
        text = visible_text(live).replace(" :", ":")  # the text of <strong>Round 1</strong>: …
        assert "Rounds of improvement" in text
        assert "Round 1: Estimation, Paper draft" in text and "Round 2: Sections and table layout" in text
        assert "Ceiling check: another round" in text and "Ceiling check: a change of approach" in text
        assert "Change of approach: Abstract" in text
        assert "2 rounds, then a change of approach" in text
        assert "Self-critique: 2 findings, 1 serious; 1 correction made in the draft" in text
        assert not problems(live), problems(live)
        page = httpx.get(f"{api}/papers/{pid}", headers=h, timeout=10).text
        assert not problems(page), problems(page)

    # Published (offline: nothing is sent) and verified like any study: the dossier carries the rounds.
    bundle = next(x for x in (study / "exports").iterdir() if (x / "provenance.json").is_file())
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT), "E2ER_SKIP_SETUP_REDIRECT": "1"}
    cli = [sys.executable, "-m", "tests.replay.cli"]
    out = subprocess.run(
        [*cli, "publish", str(bundle), "--owner", "replay", "--project", "fomc-iterative", "--name", "Replay"]
        + ["--offline", "--no-stamp", "--out", str(tmp_path / "entry"), "--db", str(db)],
        cwd=study,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    doc = json.loads((bundle / "e2er.json").read_text(encoding="utf-8"))["dossier"]["doc"]
    assert [r["ceiling_check"]["decision"] for r in doc["run"]["rounds"]] == ["another round", "a change of approach"]
    assert doc["run"]["mode"] == "iterative"
    out = subprocess.run([*cli, "verify", str(bundle)], cwd=study, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[PASS] numbers" in out.stdout
