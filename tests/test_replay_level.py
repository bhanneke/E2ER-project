"""The replay level of the end-to-end stories (tests/replay): the backend, the recorded sandbox, a full run.

The cross-repository stories live in the site repository (tests/e2e); these
tests keep the replay itself in step with the pipeline, so a change here that
breaks it fails in e2er's own suite.
"""

from __future__ import annotations

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


def test_the_fomc_event_study_replays_to_the_end_through_the_server(tmp_path: Path):
    """`e2er serve` under the replay level: the event-study template from the question to a completed run."""
    port = _free_port()
    study, home = tmp_path / "study", tmp_path / "home"
    study.mkdir()
    home.mkdir()
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
                # As in the recorded run: a FRED key, and the researcher's own FOMC
                # dates in the data folder (the data architect may only plan tables
                # from sources the study has).
                "FRED_API_KEY=replay-key",
                f"LOCAL_DATA_DIR={study / 'data'}",
            ]
        )
        + "\n"
    )
    (study / "data").mkdir()
    (study / "data" / "fomc_announcement_dates.csv").write_text("date\n2015-12-16\n", encoding="utf-8")
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(ROOT),
        "E2ER_REPLAY_SCENARIO": "fomc",
        "E2ER_REPLAY_NETLOG": str(tmp_path / "net.txt"),
        "E2ER_SKIP_SETUP_REDIRECT": "1",
        "E2ER_SESSION_TOKEN": "replay-session",
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
        assert p["status"] == "completed", p
        assert stops == ["review_design", "preregister", "review_draft"]
        ws = study / "workspaces" / pid
        assert json.loads((ws / "estimation_results.json").read_text(encoding="utf-8")) == json.loads(
            (FIXTURES / "fomc/files/econometrics_specialist/estimation_results.json").read_text(encoding="utf-8")
        )
        assert (ws / "preregistration.lock.json").is_file() and (ws / "review_aggregation.json").is_file()
        blocked = (tmp_path / "net.txt").read_text() if (tmp_path / "net.txt").exists() else ""
        assert "anthropic" not in blocked and "zenodo" not in blocked
    finally:
        server.terminate()
        server.wait(timeout=10)


def _wait(api: str, pid: str) -> dict:
    for _ in range(600):
        p = httpx.get(f"{api}/api/papers/{pid}", timeout=10).json()
        if p["status"] in {"paused", "completed", "failed", "rejected", "cancelled"} and not p.get("run_owner"):
            return p
        time.sleep(0.2)
    pytest.fail(f"the replayed run did not stop: {p}")
