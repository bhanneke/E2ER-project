"""e2er on Linux, macOS and Windows (approved 2026-10-30): the fixes the Windows and macOS CI found.

tests/test_reviewer_path.py runs a reviewer's commands end to end on all three; these pin each fix
on its own, on every system.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from src import console
from src.core import reproduce_sandbox as rs
from src.core import study_package as sp

# ── console output: UTF-8 also into a pipe or a file on Windows ─────────────


def _stream(encoding: str) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict")


def test_a_code_page_stdout_is_switched_to_utf8(monkeypatch):
    """Windows writes to a pipe in its code page (cp1252): `e2er verify … > report.txt` stopped at the first ✓."""
    out, err = _stream("cp1252"), _stream("cp1252")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    with pytest.raises(UnicodeEncodeError):
        print("✓ Prüfung 文献", file=out)
    console.utf8_stdio()
    print("✓ Prüfung 文献", file=sys.stdout)
    print("→ fertig", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    assert out.buffer.getvalue().decode("utf-8").endswith("✓ Prüfung 文献\n")  # type: ignore[attr-defined]
    assert err.buffer.getvalue().decode("utf-8").endswith("→ fertig\n")  # type: ignore[attr-defined]


def test_pythonioencoding_is_the_users_choice(monkeypatch):
    out = _stream("cp1252")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    console.utf8_stdio()
    assert sys.stdout.encoding == "cp1252"


def test_a_utf8_stream_is_left_as_it_is(monkeypatch):
    out = _stream("utf-8")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(sys, "stdout", out)
    console.utf8_stdio()
    assert sys.stdout is out and out.errors == "strict"


def test_the_e2er_command_prints_utf8_into_a_pipe(tmp_path):
    """The real entry point, its output piped: UTF-8 bytes whatever this system's code page is."""
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; sys.argv[0] = 'e2er'; sys.argv.insert(1, 'inspect'); "
         "from src.__main__ import main; main()",
         str(tmp_path / "Prüfung 文献.e2er")],
        capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=120,
    )  # fmt: skip
    assert proc.returncode == 1
    assert proc.stdout.decode("utf-8") == f"error: {tmp_path / 'Prüfung 文献.e2er'} is not a file\n"


# ── commands e2er prints for the reader to paste ────────────────────────────


def test_a_printed_path_with_spaces_is_quoted_for_a_posix_shell(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert console.shell_arg("study.e2er") == "study.e2er"
    assert console.shell_arg("downloads ü/study.e2er") == "'downloads ü/study.e2er'"
    assert console.shell_arg("it's here") == "'it'\"'\"'s here'"


def test_a_printed_path_with_spaces_is_quoted_for_cmd_and_powershell(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert console.shell_arg(r"C:\Users\ann\study.e2er") == r"C:\Users\ann\study.e2er"
    assert console.shell_arg(r"C:\Users\Ann Lee\study ü.e2er") == r'"C:\Users\Ann Lee\study ü.e2er"'


# ── Docker with Windows containers is no sandbox ────────────────────────────


def test_docker_with_windows_containers_is_refused_with_what_to_switch(monkeypatch):
    """GitHub's Windows runners, and Docker Desktop in its Windows-containers mode, cannot run python:3.12-slim."""
    monkeypatch.setattr(rs, "docker_binary", lambda: "docker")

    def engine(os_type: bytes):
        def run(argv, **kw):
            out = os_type if "{{.OSType}}" in argv else b"27.0.0\n"
            return subprocess.CompletedProcess(argv, 0, out, b"")

        return run

    docker, why = rs.available(engine(b"windows\n"))
    assert docker is None
    assert why.startswith("Docker runs Windows containers on this computer, and the sandbox needs Linux containers")
    assert 'choose "Switch to Linux containers"' in why
    assert rs.available(engine(b"linux\n")) == ("docker", "")
    assert rs.available(engine(b"")) == ("docker", ""), "an engine that does not say is tried"


# ── a package served by a test's own server ─────────────────────────────────

RECORD = {"sha256": "a" * 64, "bytes": 10, "host": "github", "fingerprint": "sha256:" + "b" * 64}


def test_a_loopback_package_address_is_accepted_in_a_test_run_only(monkeypatch):
    local = {**RECORD, "url": "http://127.0.0.1:8123/files/study-v1.e2er"}
    assert sp.record_problems(local) == []  # pytest sets PYTEST_CURRENT_TEST
    for var in ("PYTEST_CURRENT_TEST", "E2ER_TEST", "CI"):
        monkeypatch.delenv(var, raising=False)
    assert sp.record_problems(local) == ["its address is not an https address"]
    with pytest.raises(sp.PackageHostError, match="not https"):
        sp._check_hop(local["url"])


def test_a_test_run_still_refuses_http_to_another_computer():
    remote = {**RECORD, "url": "http://example.org/files/study-v1.e2er"}
    assert sp.record_problems(remote) == ["its address is not an https address"]
    with pytest.raises(sp.PackageHostError, match="not https"):
        sp._check_hop(remote["url"])


# ── a study whose code needs Python alone ───────────────────────────────────


def test_an_empty_lock_says_the_study_needs_python_alone(tmp_path):
    """`uv pip compile` of a requirements file without packages writes nothing: that is not a failure."""
    import json

    from src.core.export import package as pkg

    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    (folder / "code" / "run.py").write_text("print(1)\n", encoding="utf-8")
    (folder / "code" / "requirements.txt").write_text("# no packages\n", encoding="utf-8")
    (folder / "provenance.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    (folder / "results").mkdir()
    (folder / "results" / "r.json").write_text('{"main": 1}', encoding="utf-8")
    recipe = {
        "schema": "e2er-reproduce/1",
        "requirements": "code/requirements.txt",
        "files": {"run.py": "code/run.py"},
        "steps": [{"run": ["python", "run.py"]}],
        "compare": [{"published": "results/r.json", "produced": "r.json"}],
    }
    (folder / "reproduce.json").write_text(json.dumps(recipe), encoding="utf-8")
    packed = pkg.build(folder, tmp_path / "study.e2er", locker=lambda *a: ("", ""))
    env = packed.manifest["environment"]
    assert env["note"] == "code/requirements.txt lists no packages: the study's code needs Python alone."
    assert env["lock"] is None
    assert not any(n.startswith(". ") for n in packed.notes)
    failed = pkg.build(folder, tmp_path / "failed.e2er", locker=lambda *a: (None, ""))
    assert failed.manifest["environment"]["note"].startswith("the packages could not be resolved. The package carries")
