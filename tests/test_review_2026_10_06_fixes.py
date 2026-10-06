"""Edge cases from the 2026-10-06 review (P1), one section each.

Number check headers in \\hline tables; data_sources.json under parallel loads;
`e2er reproduce` (no comparison of a published file with itself, inputs in the
verdict, someone else's code without the researcher's keys); CLI processes
killed on timeout and cancel; what reaches the model's shell; the local API's
session token; source names and data files in subfolders; agreement across runs;
Codex usage over retries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import get_settings
from src.core import reproduce as rp
from src.core.compare import _agreement
from src.core.pipeline.verify_numbers import _extract_table_numbers
from src.core.specialists.data_sources import Sources, _norm, available_sources, why_unavailable
from src.modules.data.load_record import DATA_SOURCES_FILE, record_load
from src.modules.llm import cli_support
from tests.pipeline.contract.test_cli_backend_fixes import _OK_EVENTS, _call, _events, cfg  # noqa: F401

# ── the number check reads every data row ────────────────────────────────────

HLINE = r"""\begin{tabular}{lcc}\hline
 & 120-day window & 2019 \\ \hline
Mean & 1.23 & 4.56 \\
SD & 0.10 & 0.20 \\ \midrule
N & 100 & 200 \\ \hline
\end{tabular}"""

BOOKTABS = r"""\begin{tabular}{lcc}\toprule
 & \multicolumn{2}{c}{Scaled} \\ \cmidrule(lr){2-3}
 & day 15 & 2019 \\ \midrule
\multicolumn{3}{l}{Panel A} \\
Mean & 1.23 & 4.56 \\ \midrule
\multicolumn{3}{l}{Panel B} \\
SD & 0.10 & 0.20 \\ \bottomrule
\end{tabular}"""

NO_HEADER = r"""\begin{tabular}{lcc}\hline
Mean & 1.23 & 4.56 \\
SD & 0.10 & 0.20 \\ \hline
\end{tabular}"""


@pytest.mark.parametrize(
    ("tex", "values"),
    [
        (HLINE, ["1.23", "4.56", "0.10", "0.20", "100", "200"]),  # up to 0.13.7: 100 and 200 only
        (BOOKTABS, ["1.23", "4.56", "0.10", "0.20"]),  # the two header rows stay out
        (NO_HEADER, ["1.23", "4.56", "0.10", "0.20"]),
    ],
)
def test_the_number_check_reads_the_data_rows_and_skips_the_headers(tex: str, values: list[str]):
    assert [n for n, _ in _extract_table_numbers(tex)] == values


# ── data_sources.json under parallel loads ───────────────────────────────────


def test_parallel_loads_are_all_recorded(tmp_path: Path):
    def load(i: int) -> None:
        record_load(tmp_path, {"connector": "fred", "series": f"S{i}", "saved_to": f"data/s{i}.csv"})

    threads = [threading.Thread(target=load, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    doc = json.loads((tmp_path / DATA_SOURCES_FILE).read_text())
    assert sorted(x["series"] for x in doc["loads"]) == sorted(f"S{i}" for i in range(24))
    assert not list(tmp_path.glob(".*.tmp"))
    # The side files start with a dot: export leaves them out of the study folder.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".data_sources.json.bak",
        ".data_sources.json.lock",
        DATA_SOURCES_FILE,
    ]


def test_a_file_that_cannot_be_read_is_kept_and_the_backup_used(tmp_path: Path):
    record_load(tmp_path, {"connector": "fred", "series": "A", "saved_to": "data/a.csv"})
    record_load(tmp_path, {"connector": "fred", "series": "B", "saved_to": "data/b.csv"})  # backup holds A
    (tmp_path / DATA_SOURCES_FILE).write_text('{"loads": [{"connector": "fr')  # half a file
    record_load(tmp_path, {"connector": "yfinance", "series": "C", "saved_to": "data/c.csv"})
    doc = json.loads((tmp_path / DATA_SOURCES_FILE).read_text())
    assert [x["series"] for x in doc["loads"]] == ["A", "C"]
    kept = list(tmp_path.glob(f".{DATA_SOURCES_FILE}.unreadable-*"))
    assert len(kept) == 1 and kept[0].read_text().startswith('{"loads"')


# ── e2er reproduce ───────────────────────────────────────────────────────────


def _study(tmp_path: Path, script: str, *, data: str = "1\n2\n4\n", files: bool = True) -> Path:
    folder = tmp_path / "study"
    for d in ("code", "results", "data"):
        (folder / d).mkdir(parents=True, exist_ok=True)
    (folder / "code" / "run.py").write_text(script, encoding="utf-8")
    (folder / "code" / "requirements.txt").write_text("# no packages\n", encoding="utf-8")
    (folder / "data" / "x.csv").write_text(data, encoding="utf-8")
    (folder / "results" / "results.json").write_text(json.dumps({"main": {"estimate": 2.333333}}), encoding="utf-8")
    recipe = {
        "schema": rp.SCHEMA,
        "requirements": "code/requirements.txt",
        "steps": [{"run": ["python", "code/run.py"] if not files else ["python", "run.py"], "about": "estimate"}],
        "inputs": [{"path": "data/x.csv", "sha256": hashlib.sha256(b"1\n2\n4\n").hexdigest()}],
        # The script is to write the published file's own path: copied with the study, it was there already.
        "compare": [{"published": "results/results.json", "produced": "results/results.json"}],
    }
    if files:
        recipe["files"] = {"run.py": "code/run.py", "data": "data", "results": "results"}
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe), encoding="utf-8")
    return folder


WRITES = """\
import json
rows = [float(x) for x in open("data/x.csv").read().split()]
json.dump({"main": {"estimate": round(sum(rows) / len(rows), 6)}}, open("results/results.json", "w"))
"""


@pytest.mark.parametrize("files", [True, False])
def test_a_script_that_writes_nothing_does_not_reproduce(tmp_path: Path, capsys, files: bool):
    from src.cli_reproduce import reproduce

    folder = _study(tmp_path, "print('nothing written')\n", files=files)
    assert reproduce(str(folder)) == 1
    out = capsys.readouterr().out
    assert "Not reproduced: the study's code ran but wrote none of the result files" in out
    assert "Reproduced:" not in out


def test_a_script_that_writes_its_results_reproduces(tmp_path: Path, capsys):
    from src.cli_reproduce import reproduce

    assert reproduce(str(_study(tmp_path, WRITES))) == 0
    assert "Reproduced:" in capsys.readouterr().out


def test_other_inputs_are_no_reproduction(tmp_path: Path):
    steps = [rp.StepResult("python run.py", "", 0, 0.1, "", "log")]
    fc = rp.FileComparison("results/results.json", "results.json")
    fc.counts[rp.IDENTICAL] = 3
    ok = [{"path": "data/x.csv", "status": "identical"}]
    assert rp.verdict([fc], None, steps, ok)[1] == 0
    words, code = rp.verdict([fc], None, steps, [{"path": "data/x.csv", "status": "differs"}])
    assert code == 1 and "1 input file(s) differ from the study's (data/x.csv)" in words
    words, code = rp.verdict([fc], None, steps, [{"path": "data/y.csv", "status": "missing"}])
    assert code == 1 and "1 input file(s) are missing (data/y.csv)" in words


def test_someone_elses_code_runs_without_the_researchers_keys(monkeypatch, tmp_path: Path):
    for k, v in {
        "ANTHROPIC_API_KEY": "sk-ant-x",
        "GITHUB_TOKEN": "ghp_x",
        "ZENODO_TOKEN": "z",
        "FRED_API_KEY": "f",
        "E2ER_SESSION_TOKEN": "s",
        "UV_INDEX_URL": "https://mirror.example/simple",
        "UV_PUBLISH_TOKEN": "t",
        "LANG": "en_US.UTF-8",
    }.items():
        monkeypatch.setenv(k, v)
    env = rp.step_env(tmp_path / ".venv" / "bin" / "python")
    for k in (
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "ZENODO_TOKEN",
        "FRED_API_KEY",
        "E2ER_SESSION_TOKEN",
        "UV_PUBLISH_TOKEN",
    ):
        assert k not in env, k
    assert env["LANG"] == "en_US.UTF-8" and env["UV_INDEX_URL"].startswith("https://")
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / ".venv" / "bin") and "HOME" in env
    assert "ANTHROPIC_API_KEY" not in rp.minimal_env()  # the installer's environment too


# ── CLI processes: killed with everything they started ───────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="process groups")
def test_a_cancel_kills_the_cli_and_its_children(tmp_path: Path):
    pidfile = tmp_path / "child.pid"
    script = (
        "import subprocess, time\n"
        "p = subprocess.Popen(['sleep', '60'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )

    async def scenario() -> int:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script, stdin=asyncio.subprocess.PIPE, start_new_session=True
        )

        async def call() -> None:
            try:
                await proc.communicate(b"")
            except asyncio.CancelledError:
                await cli_support.stop_on_cancel(proc)
                raise

        task = asyncio.create_task(call())
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text():
                break
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return int(pidfile.read_text())

    child = asyncio.run(scenario())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)  # the CLI's child is gone too
    try:
        os.kill(child, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _hanging_exec(seen: dict):
    async def _exec(*args, **kwargs):
        seen["kwargs"] = kwargs
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = None

        async def _comm(input: bytes = b""):
            await asyncio.sleep(3600)

        proc.communicate = _comm
        proc.wait = AsyncMock(return_value=-9)
        return proc

    return _exec


@pytest.mark.parametrize("backend", ["claude_code", "codex", "gemini"])
async def test_every_cli_backend_kills_its_process_group_on_cancel(cfg, backend: str):  # noqa: F811
    from src.modules.llm.claude_code import ClaudeCodeBackend
    from src.modules.llm.codex import CodexBackend
    from src.modules.llm.gemini import GeminiBackend

    b = {"claude_code": ClaudeCodeBackend, "codex": CodexBackend, "gemini": GeminiBackend}[backend]()
    seen: dict = {}
    killed: list = []
    module = f"src.modules.llm.{backend}"
    with (
        patch(f"{module}.asyncio.create_subprocess_exec", new=_hanging_exec(seen)),
        patch("src.modules.llm.cli_support.kill_process_group", new=lambda p: killed.append(p.pid)),
        patch("src.modules.llm.gemini._probe_gemini_flags", new=lambda _p: (True, True)),
    ):
        task = asyncio.create_task(_call(b))
        for _ in range(100):
            if "kwargs" in seen:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert seen["kwargs"].get("start_new_session") is True
    assert killed == [4242]


async def test_claude_code_kills_its_process_group_on_timeout(cfg):  # noqa: F811
    from src.modules.llm import claude_code

    seen: dict = {}
    killed: list = []
    with (
        patch("src.modules.llm.claude_code.asyncio.create_subprocess_exec", new=_hanging_exec(seen)),
        patch("src.modules.llm.claude_code.kill_process_group", new=lambda p: killed.append(p.pid)),
    ):
        b = claude_code.ClaudeCodeBackend()
        b._timeout = 0.05  # noqa: SLF001
        r = await _call(b)
    assert not r.success and "timed out" in (r.error or "")
    assert killed == [4242] and seen["kwargs"].get("start_new_session") is True


# ── the model's shell gets no credentials it does not need ───────────────────


def test_the_model_shell_gets_only_the_wrappers_keys_and_the_clis_own(monkeypatch, cfg):  # noqa: F811
    for k in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ZENODO_TOKEN",
        "ZENODO_SANDBOX_TOKEN",
        "E2ER_SESSION_TOKEN",
        "API_AUTH_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "FRED_API_KEY",
        "ALLIUM_API_KEY",
    ):
        monkeypatch.setenv(k, "secret-value")
    monkeypatch.setenv("MAX_TOKENS_PER_CALL", "1000")  # a setting, not a credential
    env = cli_support.run_env(
        get_settings(), paper_id="p", specialist="data_analyst", workspace_root_abs=None, cli_keys=("OPENAI_API_KEY",)
    )
    for k in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "ZENODO_TOKEN"):
        assert k not in env, k
    for k in ("ZENODO_SANDBOX_TOKEN", "E2ER_SESSION_TOKEN", "API_AUTH_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        assert k not in env, k
    assert env["FRED_API_KEY"] == env["ALLIUM_API_KEY"] == env["OPENAI_API_KEY"] == "secret-value"
    assert env["MAX_TOKENS_PER_CALL"] == "1000"


@pytest.mark.parametrize(
    ("backend", "own", "other"),
    [
        ("claude_code", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY"),
        ("codex", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"),
        ("gemini", "GEMINI_API_KEY", "OPENAI_API_KEY"),
    ],
)
async def test_each_cli_keeps_its_own_sign_in_only(cfg, monkeypatch, backend, own, other):  # noqa: F811
    from tests.pipeline.contract.test_cli_backend_fixes import _fake_proc

    monkeypatch.setenv(own, "mine")
    monkeypatch.setenv(other, "not-mine")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    out = _OK_EVENTS if backend == "codex" else b'{"response": "ok"}' if backend == "gemini" else b'{"result": "ok"}'
    fake, calls = _fake_proc(out)
    from src.modules.llm.registry import get_backend

    with (
        patch(f"src.modules.llm.{backend}.asyncio.create_subprocess_exec", new=fake),
        patch("src.modules.llm.gemini._probe_gemini_flags", new=lambda _p: (True, True)),
    ):
        await _call(get_backend(get_settings(), name=backend))
    env = calls["kwargs"]["env"]
    assert env[own] == "mine" and other not in env and "GITHUB_TOKEN" not in env


# ── the local API: steering a run needs this server's session token ─────────


def test_starting_or_steering_a_run_needs_the_session_token(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.app import app

    anonymous = TestClient(app, headers={"x-e2er-token": ""})
    for path in ("/api/papers", "/api/papers/x/resume", "/api/papers/x/cancel", "/api/papers/x/review"):
        r = anonymous.post(path, json={})
        assert r.status_code == 403 and "only from the e2er that runs this dashboard" in r.json()["detail"], path
    wrong = TestClient(app, headers={"x-e2er-token": "guessed"})
    assert wrong.post("/api/papers", json={}).status_code == 403
    # With the token the request reaches the endpoint (which then checks the body).
    assert TestClient(app).post("/api/papers", json={}).status_code == 422


def test_a_bearer_token_works_when_api_auth_token_is_set(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.app import app

    monkeypatch.setenv("API_AUTH_TOKEN", "operator-token")
    get_settings.cache_clear()
    try:
        anonymous = TestClient(app, headers={"x-e2er-token": ""})
        assert anonymous.post("/api/papers", json={}).status_code == 401
        bearer = TestClient(app, headers={"x-e2er-token": "", "Authorization": "Bearer operator-token"})
        assert bearer.post("/api/papers", json={}).status_code == 422
        assert TestClient(app).post("/api/papers", json={}).status_code == 422  # the session token still works
    finally:
        get_settings.cache_clear()


def test_e2er_commands_send_the_session_token_of_the_server_they_talk_to(monkeypatch, tmp_path: Path):
    from src.api import local_session as ls
    from src.cli_run import api_headers

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("E2ER_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("E2ER_API_TOKEN", raising=False)
    monkeypatch.setenv("E2ER_API_URL", "http://127.0.0.1:8391")
    assert ls.HEADER not in api_headers()
    ls.write_session_file(8391, "from-the-file")
    assert api_headers()[ls.HEADER] == "from-the-file"
    monkeypatch.setenv("E2ER_SESSION_TOKEN", "from-the-env")
    assert api_headers()[ls.HEADER] == "from-the-env"


# ── source names and data files in subfolders ────────────────────────────────


@pytest.mark.parametrize(
    ("given", "want"),
    [("Yahoo-Finance", "yfinance"), ("yahoo finance", "yfinance"), ("Global-Macro-Database", "gmd"), ("FRED", "fred")],
)
def test_source_names_are_normalised_before_the_alias_lookup(given: str, want: str):
    assert _norm(given) == want


def test_a_data_file_in_a_subfolder_is_available(tmp_path: Path):
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "fomc_dates.csv").write_text("date\n2020-03-15\n")
    (tmp_path / "data" / ".hidden").mkdir()
    (tmp_path / "data" / ".hidden" / "x.csv").write_text("a\n")
    settings = MagicMock(local_data_dir="", fred_api_key=None, allium_api_key=None)
    sources = available_sources(tmp_path, settings)
    assert sources.files == ("raw/fomc_dates.csv",)
    for file in ("raw/fomc_dates.csv", "data/raw/fomc_dates.csv", "fomc_dates.csv"):
        assert why_unavailable({"name": "t", "source": "local", "file": file}, sources) is None, file
    assert why_unavailable({"name": "fomc_dates", "source": "data folder"}, sources) is None
    assert why_unavailable(
        {"name": "t", "source": "local", "file": "other.csv"}, Sources({}, ("raw/x.csv",), frozenset())
    )


# ── agreement across runs ────────────────────────────────────────────────────


def test_not_reported_is_no_value_runs_agree_on():
    runs = [{"fields": {"se_type": None}}, {"fields": {"se_type": None}}, {"fields": {"se_type": "HC1"}}]
    got = _agreement(runs, "se_type")
    assert got["modal"] == "HC1" and got["score"] == pytest.approx(1 / 3)
    one = [{"fields": {"se_type": "HC1"}}, {"fields": {"se_type": None}}]
    assert _agreement(one, "se_type")["score"] == pytest.approx(0.5)  # one run's SE alone does not agree 1.0


# ── Codex usage over retries ─────────────────────────────────────────────────


async def test_codex_usage_counts_every_attempt(cfg):  # noqa: F811
    from src.modules.llm.codex import CodexBackend

    failed = _events(
        {"type": "turn.completed", "usage": {"input_tokens": 300, "cached_input_tokens": 0, "output_tokens": 7}},
        {"type": "turn.failed", "error": {"message": "stream disconnected"}},
    )
    outputs = [(failed, 1), (_OK_EVENTS, 0)]
    n = {"i": 0}

    async def fake(*args, **kwargs):
        out, rc = outputs[n["i"]]
        n["i"] += 1
        proc = MagicMock()
        proc.pid = 1
        proc.communicate = AsyncMock(return_value=(out, b""))
        proc.returncode = rc
        return proc

    with (
        patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake),
        patch("src.modules.llm.codex.asyncio.sleep", new=AsyncMock()),
    ):
        r = await _call(CodexBackend())
    assert r.success and n["i"] == 2
    assert (r.usage.input_tokens, r.usage.cache_read_tokens, r.usage.output_tokens) == (700, 600, 57)
