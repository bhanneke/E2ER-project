"""AI-written scripts cannot read e2er's folder or the user's secrets (review of 2026-11-21, finding 1).

The reviewer's repro: `e2er serve`, then `e2er-run analysis.py` on a script that reads
<real home>/.e2er/session-*.json and calls the dashboard's API with the token: 200.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.core import script_sandbox
from src.core.child_env import run_in_own_session
from src.core.script_sandbox import SandboxUnavailable, denied_paths, macos_profile, plan


def _sandbox_here() -> bool:
    try:
        return plan(Path.cwd()).kind in ("sandbox-exec", "bwrap")
    except SandboxUnavailable:
        return False


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".e2er").mkdir(parents=True)
    (h / ".e2er" / "session-8280.json").write_text(json.dumps({"token": "SECRET-TOKEN", "port": 8280}))
    (h / ".e2er" / "approval-key").write_text("ab" * 32)
    (h / ".ssh").mkdir()
    (h / ".ssh" / "id_ed25519").write_text("PRIVATE")
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("SCRIPT_SANDBOX", raising=False)
    monkeypatch.delenv("E2ER_SCRIPT_SANDBOX", raising=False)
    monkeypatch.delenv("CODEX_SANDBOX", raising=False)
    monkeypatch.delenv("SANDBOX", raising=False)
    return h


def test_denied_paths_cover_e2er_and_secrets(home, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    denied = denied_paths(workspace=ws, home=home)
    assert (home / ".e2er").resolve() in denied
    assert (home / ".ssh").resolve() in denied
    assert not any(ws.resolve().is_relative_to(d) for d in denied)


@pytest.mark.skipif(sys.platform == "win32", reason="the profile is macOS's; it escapes Windows paths")
def test_profile_denies_the_folders_and_the_dashboard_port(tmp_path):
    prof = macos_profile([tmp_path / ".e2er"], 8280)
    assert f'(subpath "{tmp_path / ".e2er"}")' in prof
    assert '(remote ip "localhost:8280")' in prof
    assert "deny file-read*" in prof


def test_no_sandbox_refuses_unless_off(home, tmp_path, monkeypatch):
    monkeypatch.setattr(script_sandbox.sys, "platform", "win32")
    with pytest.raises(SandboxUnavailable, match="SCRIPT_SANDBOX=off"):
        plan(tmp_path)
    with pytest.raises(OSError):  # callers that catch OSError report it, nothing runs
        run_in_own_session([sys.executable, "-c", "print(1)"], cwd=tmp_path, env={}, timeout=30)
    monkeypatch.setenv("SCRIPT_SANDBOX", "off")
    assert plan(tmp_path).kind == "off"


def test_inside_codex_sandbox_the_outer_one_applies(home, tmp_path, monkeypatch):
    monkeypatch.setattr(script_sandbox.sys, "platform", "win32")
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert plan(tmp_path).kind == "outer"


@pytest.mark.skipif(not _sandbox_here(), reason="no OS sandbox for scripts on this machine")
def test_e2er_run_script_cannot_read_the_session_or_ssh(home, tmp_path, monkeypatch):
    from src.wrappers import run_main

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "analysis.py").write_text(
        "import glob, json, os\n"
        "home = os.environ['REAL_HOME']\n"
        "out = {}\n"
        "for p in glob.glob(home + '/.e2er/*') + [home + '/.e2er/session-8280.json', home + '/.ssh/id_ed25519']:\n"
        "    try:\n"
        "        out[p] = open(p).read()\n"
        "    except OSError as e:\n"
        "        out[p] = 'DENIED ' + type(e).__name__\n"
        "open('out.json', 'w').write(json.dumps(out))\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(ws)
    monkeypatch.setenv("E2ER_REAL_HOME", str(home))  # passed on to the script (an E2ER_ variable)
    (ws / "analysis.py").write_text((ws / "analysis.py").read_text().replace("REAL_HOME", "E2ER_REAL_HOME"))
    assert run_main(["analysis.py"]) == 0
    seen = json.loads((ws / "out.json").read_text())
    assert seen, "the script ran"
    assert not any("SECRET-TOKEN" in v or "PRIVATE" in v for v in seen.values())
    assert all(v.startswith("DENIED") for v in seen.values())


@pytest.mark.skipif(sys.platform != "darwin" or not _sandbox_here(), reason="the port rule is macOS's")
def test_script_cannot_reach_the_dashboard_port(home, tmp_path, monkeypatch):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    monkeypatch.setattr(script_sandbox, "_dashboard_port", lambda: port)
    code = f"import socket; s = socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', {port}))"
    try:
        done = run_in_own_session([sys.executable, "-c", code], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, timeout=30)
    finally:
        srv.close()
    assert done.returncode != 0
    assert "Operation not permitted" in done.stderr or "PermissionError" in done.stderr


@pytest.mark.skipif(not _sandbox_here(), reason="no OS sandbox for scripts on this machine")
def test_sandboxed_script_still_computes(tmp_path):
    done = run_in_own_session(
        [sys.executable, "-c", "import json, statistics; print(json.dumps(statistics.mean([1, 2, 3])))"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "2"


def test_bwrap_hides_folders_behind_empty_ones(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "f").write_text("x")
    args = script_sandbox.bwrap_args([tmp_path / "d", tmp_path / "f", tmp_path / "missing"])
    assert ["--tmpfs", str(tmp_path / "d")] == args[args.index("--tmpfs") : args.index("--tmpfs") + 2]
    assert "/dev/null" in args and str(tmp_path / "f") in args
    assert str(tmp_path / "missing") not in args


def test_bwrap_is_used_when_it_works(tmp_path, monkeypatch, home):
    if shutil.which("bwrap") is None:
        monkeypatch.setattr(script_sandbox.shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    monkeypatch.setattr(script_sandbox.sys, "platform", "linux")
    monkeypatch.setattr(script_sandbox, "_works", lambda argv: True)
    p = plan(tmp_path)
    assert p.kind == "bwrap" and p.prefix[-1] == "--"
    monkeypatch.setattr(script_sandbox, "_works", lambda argv: False)
    with pytest.raises(SandboxUnavailable, match="user namespaces"):
        plan(tmp_path)


def test_subprocess_e2er_run_refuses_without_sandbox(tmp_path):
    """The installed command says so plainly and exits 2 when no sandbox can run."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("print('ran')\n")
    code = (
        "import sys; from src.core import script_sandbox as s; s.sys.platform = 'win32'; "
        "from src.wrappers import run_main; sys.exit(run_main(['a.py']))"
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    done = subprocess.run([sys.executable, "-c", code], cwd=ws, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    assert "ran" not in done.stdout
    assert "SCRIPT_SANDBOX=off" in done.stderr


def test_a_python_above_the_secrets_opens_nothing(home, tmp_path, monkeypatch):
    """A Python whose prefix is the home folder (``~/bin/python``) does not reopen the denied folders."""
    monkeypatch.setattr(script_sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(script_sandbox, "_works", lambda argv: True)
    monkeypatch.setattr(script_sandbox.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    p = plan(tmp_path / "ws", python=str(home / "bin" / "python"))
    profile = p.prefix[2]
    allow = [line for line in profile.splitlines() if line.startswith("(allow file-read* (subpath")]
    assert all(f'"{home}"' not in line and f'"{home.resolve()}"' not in line for line in allow)


@pytest.mark.skipif(sys.platform == "win32", reason="the profile is macOS's; it escapes Windows paths")
def test_the_folders_above_a_readable_python_show_their_metadata_only(tmp_path):
    """Homebrew's Python resolves the folders above itself at start; in a denied folder it could not."""
    denied = tmp_path / "secrets"
    venv = denied / "jobs" / "venv"
    prof = macos_profile([denied], None, readable=[venv])
    assert f'(allow file-read* (subpath "{venv}"))' in prof
    meta = next(line for line in prof.splitlines() if line.startswith("(allow file-read-metadata"))
    assert f'(literal "{denied}")' in meta and f'(literal "{denied / "jobs"}")' in meta
    assert "subpath" not in meta  # the folders themselves, never what they hold


@pytest.mark.skipif(sys.platform != "darwin" or not _sandbox_here(), reason="the link rule is macOS's profile")
def test_a_sandboxed_script_makes_no_links(tmp_path, home):
    """Review of 2026-11-24: a link made in the sandbox would lead e2er's own commands to a denied file."""
    import subprocess

    from src.core.script_sandbox import wrap

    argv, _ = wrap([sys.executable, "-c", "import os; os.symlink('/etc/hosts', 'l')"], tmp_path)
    done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode != 0 and not (tmp_path / "l").is_symlink(), done.stderr


@pytest.mark.skipif(not sys.platform.startswith("linux") or not _sandbox_here(), reason="bubblewrap's pid namespace")
def test_no_process_outlives_a_sandboxed_script(tmp_path, home):
    """Review of 2026-11-24: a double-forked child kept changing the study's files after the script ended."""
    import subprocess
    import time

    from src.core.script_sandbox import wrap

    code = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"
        "    if os.fork() == 0:\n"
        "        time.sleep(1.5); open('late', 'w').write('x')\n"
        "    os._exit(0)\n"
    )
    argv, _ = wrap([sys.executable, "-c", code], tmp_path)
    subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    time.sleep(2.5)
    assert not (tmp_path / "late").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups and sessions")
def test_what_a_script_leaves_running_is_stopped_when_it_ends(tmp_path, home):
    """Re-review of 2026-11-24: a double-forked child (setsid) outlived e2er-run on macOS and changed files."""
    import time

    from src.core.child_env import run_in_own_session

    code = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"
        "    if os.fork() == 0:\n"
        "        os.close(1); os.close(2)\n"
        "        time.sleep(1.5); open('late', 'w').write('x')\n"
        "    os._exit(0)\n"
    )
    # As e2er-run runs a script (its output goes straight to the terminal); the child closes its output.
    run_in_own_session([sys.executable, "-c", code], cwd=tmp_path, env=dict(os.environ), timeout=30, capture=False)
    time.sleep(2.5)
    assert not (tmp_path / "late").exists()
