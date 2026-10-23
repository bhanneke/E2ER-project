"""What AI CLIs and AI-written scripts see of this computer (security review 2026-10-23).

The reviewer's envtest.py: SSH_AUTH_SOCK and a DATABASE_URL with its password reached the CLI's
shell, and the AI-written scripts (post-run of an analysis script, the meta-analysis script,
``e2er-run``) got e2er's whole environment and the user's HOME.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from src.core import child_env as ce

SECRETS = {
    "FAKE_GH": "ghp_FAKE",  # a token under a name that does not say so
    "GH_TOKEN": "ghp_FAKE2",
    "SSH_AUTH_SOCK": "/tmp/ssh-agent.sock",
    "DATABASE_URL": "postgresql://u:hunter2@db/x",
    "OPENAI_API_KEY": "sk-FAKE",
    "ZENODO_TOKEN": "z-FAKE",
    "E2ER_SESSION_TOKEN": "session-FAKE",
    "AWS_SECRET_ACCESS_KEY": "aws-FAKE",
    "HTTPS_PROXY": "http://user:pass@proxy:3128",
}


@pytest.fixture
def leaky(monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("FRED_API_KEY", "fred-FAKE")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKE")
    monkeypatch.setenv("E2ER_PAPER_ID", "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0")
    monkeypatch.setenv("LOCAL_DATA_DIR", "/data")


def test_the_cli_shell_gets_an_allowlist(leaky):
    """The reviewer's envtest.py, as a test."""
    from src.modules.llm.cli_support import run_env

    s = SimpleNamespace(resolved_database_url="postgresql://u:hunter2@db/x")
    env = run_env(s, paper_id=None, specialist="econometrics_specialist", workspace_root_abs=None,
                  cli_keys=("ANTHROPIC_API_KEY",))  # fmt: skip
    for k in SECRETS:
        assert k not in env, k
    assert env["FRED_API_KEY"] == "fred-FAKE"  # a wrapper's data key
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-FAKE"  # the CLI's own sign-in
    assert env["LOCAL_DATA_DIR"] == "/data"  # an e2er setting the wrappers read
    assert env["E2ER_PAPER_ID"].startswith("0f1e2d3c")
    assert "hunter2" not in json.dumps(env)


def test_the_cli_shell_gets_the_run_database_only_as_a_sqlite_path(leaky, tmp_path):
    from src.modules.llm.cli_support import run_env

    s = SimpleNamespace(resolved_database_url=f"sqlite:///{tmp_path}/papers.db")
    env = run_env(s, paper_id=None, specialist=None, workspace_root_abs=None)
    assert env["DATABASE_URL"] == f"sqlite:///{(tmp_path / 'papers.db').resolve()}"
    assert "DB_PASSWORD" not in env


def test_an_ai_written_script_gets_no_key_and_an_empty_home(leaky, tmp_path):
    home = ce.empty_home()
    try:
        env = ce.script_env(home=home)
        for k in [*SECRETS, "FRED_API_KEY", "ANTHROPIC_API_KEY"]:
            assert k not in env, k
        for var in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "USERPROFILE", "APPDATA"):
            assert env[var] == str(home)
        assert env["E2ER_PAPER_ID"].startswith("0f1e2d3c")
    finally:
        import shutil

        shutil.rmtree(home, ignore_errors=True)


def test_the_post_run_of_an_analysis_script_sees_no_secret(leaky, tmp_path, monkeypatch):
    from src.core.specialists.post_execution import maybe_execute_specialist_script

    ws = tmp_path / "ws"
    ws.mkdir()
    real_home = tmp_path / "realhome"
    (real_home / ".ssh").mkdir(parents=True)
    (real_home / ".ssh" / "id_rsa").write_text("PRIVATE")
    monkeypatch.setenv("HOME", str(real_home))
    (ws / "run_estimation.py").write_text(
        "import json, os\n"
        "seen = {k: os.environ.get(k) for k in " + repr(sorted([*SECRETS, "FRED_API_KEY", "ANTHROPIC_API_KEY"])) + "}\n"
        "ssh = os.path.exists(os.path.expanduser('~/.ssh/id_rsa'))\n"
        "json.dump({'models': [{'n': 1}], 'seen': seen, 'ssh': ssh}, open('estimation_results.json', 'w'))\n"
    )
    attempt = maybe_execute_specialist_script(ws, "econometrics_specialist")
    assert attempt.ran, attempt.reason
    out = json.loads((ws / "estimation_results.json").read_text())
    assert all(v is None for v in out["seen"].values()), out["seen"]
    assert out["ssh"] is False


def test_e2er_run_passes_no_key_to_the_script(leaky, tmp_path, monkeypatch):
    from src import wrappers

    (tmp_path / "s.py").write_text(
        "import json, os\n"
        "json.dump({'fred': os.environ.get('FRED_API_KEY'), 'anth': os.environ.get('ANTHROPIC_API_KEY'), "
        "'home': os.environ['HOME']}, open('o.json', 'w'))\n"
    )
    monkeypatch.chdir(tmp_path)
    assert wrappers.run_main(["s.py"]) == 0
    out = json.loads((tmp_path / "o.json").read_text())
    assert out["fred"] is None and out["anth"] is None and out["home"] != os.environ["HOME"]


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups")
def test_a_scripts_own_child_is_stopped_at_the_time_limit(tmp_path):
    marker = tmp_path / "child-alive"
    child = tmp_path / "child.py"
    child.write_text(f"import time\ntime.sleep(3)\nopen({str(marker)!r}, 'w').write('x')\n")
    script = tmp_path / "s.py"
    script.write_text(
        f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, {str(child)!r}])\ntime.sleep(30)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        ce.run_in_own_session([sys.executable, str(script)], cwd=tmp_path, env=dict(os.environ), timeout=1)
    time.sleep(3.5)
    assert not marker.exists(), "the script's child kept running after the time limit"
