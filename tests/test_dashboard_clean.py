"""The local dashboard end to end on localhost, without breaks (0.14.0).

One test or more per fix of the 2026-10-08 plan:

* publishing from the browser never asks on the server's terminal;
* a tab left open across a restart keeps working (one session secret per
  computer, a cookie that lasts), ``localhost`` is sent to ``127.0.0.1``;
* the session file is written only once this server has the port;
* the Zenodo key saved under Settings is used;
* "Also stop for you after these steps" offers the chosen template's steps;
* one studies folder, remembered, used from any folder; a folder with its own
  settings still works on its own; new run folders have readable names;
* earlier versions of outputs go to a hidden ``.history`` folder and are never
  exported or downloaded; backups and lock files neither;
* the sign-in command of a CLI provider, with the full path when needed.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import local_session as ls

BASE = "http://127.0.0.1:8290"
TOKEN = "clean-test-token-0123456789"


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: h))
    monkeypatch.delenv("E2ER_PROJECT_DIR", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    from src.config import get_settings

    get_settings.cache_clear()
    yield h
    get_settings.cache_clear()


def _client(cookie: bool = True) -> TestClient:
    from src.api.app import app

    c = TestClient(app, base_url=BASE, client=("127.0.0.1", 50000))
    if cookie:
        c.cookies.set("e2er_session_8290", TOKEN)
    return c


# ── publishing never asks on the server's terminal ───────────────────────────


def test_publish_from_the_server_never_reads_the_terminal(tmp_path, monkeypatch):
    """With the server started at a terminal, `input()` hung the page (cli_publish asked [y/N])."""
    from src import cli_publish

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

    def _no_input(*a, **k):
        raise AssertionError("publish asked on the terminal")

    monkeypatch.setattr("builtins.input", _no_input)
    seen = {}
    monkeypatch.setattr(cli_publish, "_describe", lambda *a, **kw: (seen.update(kw) or 1, None))
    cli_publish.publish(str(bundle), offline=True, interactive=False, data="public", code="private")
    assert "interactive" not in seen  # used up here, never passed on


def test_the_finish_page_publishes_without_a_terminal():
    """The finish endpoint passes interactive=False (checked in the source the endpoint runs)."""
    import inspect

    from src.api import finish

    assert "interactive=False" in inspect.getsource(finish.publish_study)


# ── a tab left open across a restart ────────────────────────────────────────


def test_one_session_secret_per_computer(home):
    a = ls.stable_token()
    assert len(a) >= 24 and ls.stable_token() == a, "the same token after every start"
    assert stat.S_IMODE(ls.secret_file().stat().st_mode) == 0o600


def test_the_session_cookie_lasts_and_works_on_every_port(monkeypatch):
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    r = _client(cookie=False).get(f"/?t={TOKEN}", follow_redirects=False)
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("e2er_session_8290=") and "Max-Age=31536000" in c for c in cookies)
    assert any(c.startswith("e2er_session=") for c in cookies)
    # A tab on another port of the same computer carries the shared cookie.
    from src.api.app import app

    other = TestClient(app, base_url="http://127.0.0.1:8299", client=("127.0.0.1", 50000))
    other.cookies.set("e2er_session", TOKEN)
    assert other.post("/api/papers/x/cancel").status_code != 403


def test_localhost_pages_go_to_127_0_0_1():
    """A localhost tab and the 127.0.0.1 link carried different cookies; every button failed."""
    from src.api.app import app

    c = TestClient(app, base_url="http://localhost:8290", client=("127.0.0.1", 50000))
    r = c.get("/library?q=x", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "http://127.0.0.1:8290/library?q=x"
    assert c.get("/api/papers", follow_redirects=False).status_code == 200  # the API answers where asked


def test_every_page_loads_the_error_handler():
    html = _client().get("/library").text
    assert '<script src="/static/e2er.js"></script>' in html
    js = (Path(__file__).parents[1] / "src" / "api" / "static" / "e2er.js").read_text()
    assert "htmx:responseError" in js and "htmx:sendError" in js and "e2er is not reachable" in js


def test_the_session_file_is_written_only_once_this_server_has_the_port(home, monkeypatch):
    import threading

    from src import __main__ as cli

    answers = {"pid": -1}

    class _R:
        def json(self):
            return {"process": {"pid": answers["pid"], "ppid": -1}}

    monkeypatch.setattr("httpx.get", lambda *a, **k: _R())
    stop = cli._write_session_file_when_up("127.0.0.1", 8295, "tok-1")
    try:
        threading.Event().wait(0.6)
        assert not ls.session_file(8295).exists(), "another server on the port must not get our file"
        answers["pid"] = os.getpid()
        for _ in range(30):
            if ls.session_file(8295).exists():
                break
            threading.Event().wait(0.1)
        assert ls.read_session_token(8295) == "tok-1"
    finally:
        stop.set()


# ── Zenodo key from Settings ─────────────────────────────────────────────────


def test_the_zenodo_key_saved_under_settings_is_used(home, monkeypatch, tmp_path):
    from src.config import get_settings
    from src.core import zenodo

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("LLM_BACKEND=claude_code\nZENODO_TOKEN= zen-from-settings \n")
    monkeypatch.chdir(proj)
    monkeypatch.delenv("ZENODO_TOKEN", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)
    get_settings.cache_clear()
    assert zenodo.load_token() == "zen-from-settings"
    monkeypatch.setenv("ZENODO_TOKEN", "from-env")
    assert zenodo.load_token() == "from-env"


def test_setup_offers_the_zenodo_key_and_the_github_login(home, monkeypatch, tmp_path):
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    monkeypatch.chdir(tmp_path)
    page = _client().get("/setup").text
    assert 'name="key-ZENODO_TOKEN"' in page and "Zenodo key" in page
    assert 'name="github_login"' in page


# ── stops after steps of the chosen template ─────────────────────────────────


def test_the_stops_on_offer_are_the_chosen_templates_steps(monkeypatch):
    from src.api.app import _pipeline_choices

    choices = {p["name"]: [c["name"] for c in p["review_choices"]] for p in _pipeline_choices()}
    assert choices["empirical"] == [
        "initial",
        "iterative",
        "estimation_gate",
        "self_attack",
        "polish",
        "review",
        "revision",
        "replication",
    ]
    assert "fetch" in choices["replication"] and "review" not in choices["replication"]
    assert "review_design" not in choices["empirical-preregistered"]  # a stop of its own already
    html = _client().get("/papers/new").text
    assert 'data-template="replication"' in html and 'value="sandbox_run"' in html


def test_a_stop_after_a_replication_step_is_accepted(monkeypatch):
    """The replication template's steps were refused: only the empirical step names were allowed."""
    from src.api.app import _review_at_choices
    from src.core.pipeline.spec import find_spec

    assert "compare" in _review_at_choices(find_spec("replication"))


# ── one studies folder ───────────────────────────────────────────────────────


def test_a_new_researcher_gets_a_remembered_studies_folder(home, tmp_path, monkeypatch):
    from src import home as h
    from src.config import get_settings

    elsewhere = tmp_path / "Downloads"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    assert h.kind() == "none"
    r = _client().post(
        "/api/setup/save", json={"backend": "claude_code", "studies_folder": ""}, headers={"origin": BASE}
    )
    assert r.status_code == 200, r.text
    folder = home / "e2er-studies"
    assert (folder / ".env").is_file() and not (elsewhere / ".env").exists()
    assert json.loads((home / ".e2er" / "settings.json").read_text())["studies_folder"] == str(folder.resolve())
    # e2er started from any other folder uses it: settings, studies and exports.
    other = tmp_path / "Desktop"
    other.mkdir()
    monkeypatch.chdir(other)
    get_settings.cache_clear()
    s = get_settings()
    assert s.llm_backend == "claude_code"
    assert Path(s.workspace_root) == folder.resolve() / "workspaces"
    assert s.resolved_output_root() == folder.resolve() / "exports"
    assert h.kind() == "studies"
    assert "Your studies folder" in _client().get("/library").text


def test_a_folder_with_its_own_settings_keeps_working_as_before(home, tmp_path, monkeypatch):
    """Existing users: the folder they start e2er in, with its .env, is used exactly as before."""
    from src import home as h
    from src.config import get_settings

    studies = h.remember_studies_folder(tmp_path / "studies")
    proj = tmp_path / "old-project"
    proj.mkdir()
    (proj / ".env").write_text("LLM_BACKEND=codex\n")
    monkeypatch.chdir(proj)
    get_settings.cache_clear()
    assert h.kind() == "project" and h.project_dir() == proj
    assert get_settings().llm_backend == "codex" and get_settings().workspace_root == "workspaces"
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    page = _client().get("/setup").text
    assert "Make this folder my studies folder" in page and str(studies) in page
    r = _client().post(
        "/api/setup/save", json={"backend": "codex", "make_studies_folder": True}, headers={"origin": BASE}
    )
    assert r.status_code == 200, r.text
    assert h.remembered_studies_folder() == proj.resolve() and h.kind() == "studies"


def test_exports_never_land_in_the_data_folder(home, tmp_path, monkeypatch):
    from src.config import Settings

    monkeypatch.chdir(tmp_path)
    s = Settings(local_data_dir=str(tmp_path / "data"))
    assert "data" not in s.resolved_output_root().relative_to(home).parts


def test_a_run_folder_is_found_from_its_id(tmp_path, monkeypatch):
    from src import home as h

    root = tmp_path / "workspaces"
    ws = h.new_workspace(root, "Ünïcode & FOMC: a test!", "abc")
    (ws / "manifest.json").write_text('{"paper_id": "abc"}')
    assert ws.name.endswith("-unicode-fomc-a-test")
    h._KNOWN.clear()
    assert h.find_workspace("abc", root) == ws
    monkeypatch.setenv("E2ER_PAPER_ID", "zzz")
    monkeypatch.setenv("E2ER_WORKSPACE", str(ws))
    assert h.find_workspace("zzz", root) == ws  # a wrapper inside a run gets its folder from the runner


def test_the_wrappers_get_the_runs_folder(tmp_path, monkeypatch):
    from src import home as h
    from src.modules.llm.cli_support import run_env

    root = tmp_path / "workspaces"
    ws = h.new_workspace(root, "A study", "pid-1")

    class S:
        workspace_root = str(root)
        database_url = ""

        @property
        def resolved_database_url(self):
            return ""

    monkeypatch.setattr("src.modules.llm.cli_support.db_path", lambda s: None)
    env = run_env(S(), paper_id="pid-1", specialist="data_analyst", workspace_root_abs=root.resolve())
    assert env["E2ER_WORKSPACE"] == str(ws.resolve())


# ── earlier outputs, backups and locks ───────────────────────────────────────


def test_leftovers_are_never_exported(tmp_path):
    from src.core.export.bundle_files import is_leftover
    from src.core.export.structured import _skip

    for name in ("review_technical.md.previous", "x.bak", "draft.tex~", ".~lock.data.xlsx#", "a.lock", "n.swp"):
        assert is_leftover(name) or name.startswith("."), name
        assert _skip(tmp_path / name, tmp_path), name
    for name in ("preregistration.lock.json", "paper_draft.tex", "review_technical.md"):
        assert not _skip(tmp_path / name, tmp_path), name


def test_download_all_files_leaves_out_hidden_history_and_backups(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, patch

    pid = "5f0c4a63-8a61-4a5e-9d4e-3c2b1a0f9e8d"
    ws = tmp_path / "ws"
    (ws / ".history").mkdir(parents=True)
    (ws / ".history" / "review_technical.md.1").write_text("old")
    (ws / "review_technical.md").write_text("new")
    (ws / "review_technical.md.previous").write_text("older e2er")
    (ws / ".pipeline_state.json").write_text("{}")
    (ws / "manifest.json").write_text("{}")
    row = {"id": pid, "title": "FOMC study", "workspace": str(ws), "status": "completed", "max_cost_usd": 5}
    with (
        patch("src.db.client.fetch_one", AsyncMock(return_value=row)),
        patch("src.db.client.fetch_all", AsyncMock(return_value=[])),
        patch("src.modules.tracking.usage.get_paper_usage", AsyncMock(return_value={})),
    ):
        r = _client().get(f"/api/papers/{pid}/audit-bundle")
    assert r.status_code == 200 and "e2er-fomc-study-files.tar.gz" in r.headers["content-disposition"]
    names = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz").getnames()
    assert "review_technical.md" in names and "run-manifest.json" in names and "manifest.json" in names
    assert not any(".history" in n or n.endswith(".previous") or "pipeline_state" in n for n in names)


# ── signing in an AI provider ────────────────────────────────────────────────


def test_the_sign_in_command_names_the_program_the_terminal_finds(tmp_path, monkeypatch):
    from src.doctor import signin_command

    app_codex = tmp_path / "ChatGPT.app" / "Contents" / "Resources" / "codex"
    app_codex.parent.mkdir(parents=True)
    app_codex.write_text("")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert signin_command("codex", str(app_codex)) == f"{app_codex} login"  # the full path
    spaced = tmp_path / "My Apps" / "codex"
    spaced.parent.mkdir()
    spaced.write_text("")
    assert signin_command("codex", str(spaced)) == f"'{spaced}' login"  # quoted for the terminal
    monkeypatch.setattr("shutil.which", lambda name: str(app_codex))
    assert signin_command("codex", str(app_codex)) == "codex login"
    assert signin_command("claude_code", str(app_codex)) == "claude"
    assert signin_command("anthropic", "x") == ""


# ── plain names ──────────────────────────────────────────────────────────────


def test_plain_names_for_everything_on_screen():
    from src.core import labels

    assert labels.step("number_check") == "Number check"
    assert labels.specialist("paper_drafter") == "Paper draft"
    assert labels.step_or_specialist("paper_drafter") == "Paper draft (one specialist)"
    assert labels.event("phase_start") == "Step started"
    assert labels.check("skills.installed") == "Specialists' instructions"
    assert labels.check("backend.codex") == "AI provider (Codex)"
    assert labels.status("rejected") == "stopped by a check" and labels.status("designing") == "running"
    assert labels.template("empirical-preregistered") == "Empirical study, pre-registered"


def test_a_stored_error_reads_as_a_sentence():
    from src.api.app import _plain_error

    assert _plain_error("BudgetExceededError: spent $0.52 of $0.50") == "The spending limit was reached."
    assert _plain_error("RuntimeError: All specialists failed: technical_reviewer; x") == (
        "All specialists failed: Technical review"
    )


def test_a_stop_you_asked_for_lists_what_the_step_wrote(tmp_path):
    """The strategist logs its specialists without a stage: the step's window of events names them."""
    from src.api.app import _step_outputs

    for name in ("paper_plan.md", "econometric_spec.md", "estimation_results.json", "data_summary.md"):
        (tmp_path / name).write_text("x")
    events = [
        {"event_type": "specialist_end", "stage": None, "specialist": "data_analyst"},  # before the step
        {"event_type": "phase_start", "stage": "initial", "specialist": None},
        {"event_type": "specialist_end", "stage": None, "specialist": "idea_developer"},
        {"event_type": "specialist_end", "stage": None, "specialist": "econometrics_specialist"},
        {"event_type": "phase_end", "stage": "initial", "specialist": None},
    ]
    got = _step_outputs(tmp_path, "initial", events, None)
    assert "paper_plan.md" in got and "estimation_results.json" in got and "econometric_spec.md" in got
    assert "data_summary.md" not in got
