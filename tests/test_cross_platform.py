"""e2er on Linux, macOS and Windows (approved 2026-10-30): the fixes the Windows and macOS CI found.

tests/test_reviewer_path.py runs a reviewer's commands end to end on all three; these pin each fix
on its own, on every system.
"""

from __future__ import annotations

import io
import os
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


# ── one lock across processes, also on Windows ──────────────────────────────

_HOLDER = """\
import sys, time
sys.path.insert(0, sys.argv[3])
from src.core.file_lock import exclusive
with open(sys.argv[1], "a+") as fh, exclusive(fh):
    open(sys.argv[2], "w").close()
    time.sleep(1.5)
"""


def test_the_lock_holds_across_processes(tmp_path):
    """Windows fell back to a thread lock: two e2er processes could export the same run at once."""
    import time

    from src.core.file_lock import exclusive

    lock, held = tmp_path / ".lock", tmp_path / "held"
    root = str(Path(__file__).resolve().parents[1])
    child = subprocess.Popen([sys.executable, "-c", _HOLDER, str(lock), str(held), root])
    try:
        deadline = time.monotonic() + 60
        while not held.exists():
            assert time.monotonic() < deadline and child.poll() is None, "the other process never took the lock"
            time.sleep(0.02)
        start = time.monotonic()
        with open(lock, "a+") as fh, exclusive(fh):
            waited = time.monotonic() - start
        assert waited > 0.5, f"took the lock after {waited:.2f} s while the other process held it"
    finally:
        child.wait(timeout=60)
    with open(lock, "a+") as fh, exclusive(fh):
        pass  # released: taken again at once


# ── names a package carries to every system ─────────────────────────────────


def _folder(tmp_path: Path, names: list[str]) -> Path:
    import json

    folder = tmp_path / "study"
    folder.mkdir()
    (folder / "provenance.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    for n in names:
        (folder / n).parent.mkdir(parents=True, exist_ok=True)
        (folder / n).write_text(n, encoding="utf-8")
    return folder


def test_names_that_differ_only_in_case_are_not_packed(tmp_path, monkeypatch):
    """A Linux folder may hold Data.csv and data.csv; macOS and Windows keep one, so the package opened nowhere."""
    from src.core.export import package as pkg

    folder = _folder(tmp_path, ["a/x.csv", "b.csv"])
    files = {"Data/x.csv": folder / "a/x.csv", "data/y.csv": folder / "a/x.csv", "b.csv": folder / "b.csv"}
    monkeypatch.setattr(pkg, "study_files", lambda f: dict(files))
    with pytest.raises(pkg.PackageError, match=r"differ only in case: Data and data\. macOS and Windows"):
        pkg.build(folder, tmp_path / "s.e2er", locker=lambda *a: ("", ""))
    assert not (tmp_path / "s.e2er").exists()
    assert pkg.case_collisions(["R.csv", "r.csv", "Ü/a", "ü/b", "x/y"]) == [("R.csv", "r.csv"), ("Ü", "ü")]


@pytest.mark.parametrize(
    "rel, words",
    [
        ("results/table:1.csv", "has : in its name"),
        ("code/what?.py", "has ? in its name"),
        ("data/NUL", "is named NUL, a device on Windows"),
        ("data/con.txt", "is named con, a device on Windows"),
        ("data/notes.", "ends with a dot or a space"),
    ],
)
def test_names_windows_cannot_hold_are_named(rel, words):
    from src.core.export import package as pkg

    assert words in (pkg.windows_name_problem(rel) or "")


def test_ordinary_names_are_fine_on_windows():
    from src.core.export import package as pkg

    for rel in ("data/consumption.csv", "code/run_estimation.py", "paper/Prüfung 文献.tex", "nul_results/x.json"):
        assert pkg.windows_name_problem(rel) is None, rel


def _zip_package(tmp_path: Path, name: str) -> Path:
    import hashlib
    import json
    import zipfile

    from src.core.export import package as pkg

    data = b"x"
    contents = [{"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": 1, "part": "study"}]
    manifest = {"format": pkg.FORMAT, "contents": contents, "fingerprint": pkg.fingerprint(contents)}
    out = tmp_path / "p.e2er"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(pkg.MANIFEST, json.dumps(manifest))
        zf.writestr(name, data)
    return out


def test_unpacking_on_windows_refuses_a_name_windows_cannot_hold(tmp_path, monkeypatch):
    """`a:b` wrote an NTFS stream of `a`, `NUL` the null device: the folder was not the package."""
    from src.core.export import package as pkg

    package = _zip_package(tmp_path, "results/table:1.csv")
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(pkg.PackageError, match=r"results/table:1.csv cannot be written on Windows: it has :"):
        pkg.open_package(package, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_packing_says_which_names_windows_cannot_open(tmp_path):
    from src.core.export import package as pkg

    folder = _folder(tmp_path, ["results/x.csv"])
    files = {"results/x.csv": folder / "results/x.csv", "data/aux.csv": folder / "results/x.csv"}
    import unittest.mock as um

    with um.patch.object(pkg, "study_files", lambda f: dict(files)):
        packed = pkg.build(folder, tmp_path / "s.e2er", locker=lambda *a: ("", ""))
    assert any(n.startswith("data/aux.csv is named aux, a device on Windows") for n in packed.notes), packed.notes


def test_a_file_that_cannot_be_written_is_named_and_a_long_path_on_windows_says_what_to_do(tmp_path, monkeypatch):
    """A Windows path past 260 characters raised FileNotFoundError out of `e2er unpack` as a traceback."""
    from src.core.export import package as pkg

    package = _zip_package(tmp_path, "data/x.csv")
    real_open = os.open

    def refuse(path, *a, **kw):
        if str(path).endswith("x.csv"):
            raise FileNotFoundError(2, "No such file or directory")
        return real_open(path, *a, **kw)

    monkeypatch.setattr(os, "open", refuse)
    with pytest.raises(pkg.PackageError, match=r"^data/x.csv could not be written \(No such file or directory\)$"):
        pkg.open_package(package, tmp_path / "out")
    deep = tmp_path / ("d" * 120) / ("e" * 120)
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(pkg.PackageError) as e:
        pkg.open_package(package, deep)
    assert "Windows opens at most 259 unless long paths are turned on" in str(e.value)
    assert "Unpack into a short folder (C:\\e2er\\study)" in str(e.value)


# ── line endings: hashes are byte-based, and verify says when only CRLF differs ──


def test_verify_names_files_whose_only_change_is_crlf(tmp_path):
    """Git on Windows (core.autocrlf) checks text out with CRLF: a clone of a study repository failed unexplained."""
    import hashlib
    import json

    from src.cli_verify import FAIL, _check_integrity

    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    lf = b"import json\nprint(1)\n"
    (folder / "code" / "run.py").write_bytes(lf.replace(b"\n", b"\r\n"))
    (folder / "code" / "other.py").write_bytes(b"changed\n")
    files = {
        "code/run.py": {"sha256": hashlib.sha256(lf).hexdigest(), "bytes": len(lf)},
        "code/other.py": {"sha256": hashlib.sha256(b"original\n").hexdigest(), "bytes": 9},
    }
    (folder / "provenance.json").write_text(json.dumps({"schema": "e2er-provenance/1", "files": files}), "utf-8")
    check = _check_integrity(folder)
    assert check.status == FAIL
    assert "2 modified (code/run.py, code/other.py)" in check.detail
    assert "1 of them differs only in line endings (code/run.py)" in check.detail
    assert "git clone -c core.autocrlf=false" in check.detail


# ── a child Python's output, read in UTF-8 ──────────────────────────────────


def test_the_network_guard_probe_reads_a_non_ascii_path_in_utf8(monkeypatch, tmp_path):
    """On Windows the probe of the new environment printed `…\\Prüfung 文献\\…` into a cp1252 pipe and died:
    the reviewer path reported "The network guard could not be put into the environment"."""
    from src.core import reproduce as rp

    site = tmp_path / "Prüfung 文献" / "site-packages"
    site.mkdir(parents=True)
    seen: dict = {}

    def run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, f"{site}\n", "")

    monkeypatch.setattr(rp.subprocess, "run", run)
    assert rp.install_network_guard(tmp_path / "python") is True
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8" and seen["encoding"] == "utf-8"
    assert (site / "e2er_reproduce_netguard.pth").is_file()


def test_steps_write_utf8_into_their_pipes_and_e2er_reads_it(tmp_path):
    from src.core import reproduce as rp

    (tmp_path / "e2er-reproduce-x").mkdir()
    env = rp.step_env(Path(sys.executable), tmp_path / "e2er-reproduce-x")
    assert env["PYTHONIOENCODING"] == "utf-8"
    log = tmp_path / "step.log"
    code, tail = rp._run([sys.executable, "-c", "print('Prüfung 文献 ✓')"], cwd=tmp_path, env=env, timeout=60, log=log)
    assert code == 0 and tail == "Prüfung 文献 ✓"
    assert log.read_text(encoding="utf-8").strip() == "Prüfung 文献 ✓"
