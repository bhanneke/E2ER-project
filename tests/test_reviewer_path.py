"""What a reviewer does with a study package, on Linux, macOS and Windows, from a clean install.

Björn, 2026-10-30: reviewers must be able to use e2er on any machine. This test installs the built
wheel into a new virtual environment (no checkout on the path, an empty home folder, no token) and
runs the commands docs/REVIEWING.md gives a reviewer, in a working folder whose name has spaces and
characters outside ASCII:

    e2er --version
    e2er fetch <address>              (from a local copy of e2er.org that records the package)
    e2er inspect / unpack / verify    (on a package built here from a small study with open data)
    e2er verify --against <address>   (the same local copy of e2er.org)
    e2er reproduce                    (in the Docker sandbox where Docker runs Linux containers;
                                       elsewhere the plain refusal, then --no-sandbox --yes)

Nothing reaches the network beyond this computer: the dependencies come from a folder of wheels
downloaded before the test (E2ER_REVIEWER_WHEELHOUSE), and the local e2er.org runs on 127.0.0.1.
The CI job "reviewer path" (.github/workflows/tests.yml) prepares that folder and runs
`pytest -m reviewer_path` on all three systems; without the folder the test is skipped, unless
E2ER_REQUIRE_REVIEWER_PATH=1 makes that a failure.

E2ER_REVIEWER_REPRODUCE says what the computer must do with `e2er reproduce`: ``sandbox`` (run in
Docker; GitHub's Linux runners) or ``refusal`` (no Linux containers; macOS and Windows runners).
Unset, the test takes whichever this computer offers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import venv
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.reviewer_path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"
#: A working folder as a reviewer may have one: spaces, umlauts, CJK.
WORK = "Gutachten Prüfung 文献"

# ── the study: a small one with open data (World Bank, Natural Earth; their terms let data travel) ──

RATES = [("AAA", "COUNTRY", 12.5), ("BBB", "COUNTRY", 3.25), ("CCC", "COUNTRY", None), ("AFR", "REGION", 19.4)]
NAMES = [("AAA", "Avalon"), ("BBB", "Brigadoon"), ("CCC", "Cockaigne")]

CLEAN = """\
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")
con = sqlite3.connect(DB)
con.execute("DROP TABLE IF EXISTS rates_clean")
con.execute(
    "CREATE TABLE rates_clean AS SELECT r.location AS iso3, n.name, r.value FROM rates_raw r "
    "JOIN country_names n ON n.iso3 = r.location WHERE r.spatial_type = 'COUNTRY' AND r.value IS NOT NULL"
)
con.commit()
con.close()
"""

ESTIMATE = """\
import json
import sqlite3

con = sqlite3.connect("data.db")
rows = con.execute("SELECT iso3, value FROM rates_clean ORDER BY iso3").fetchall()
values = [v for _iso3, v in rows]
out = {"main": {"n": len(values), "mean": sum(values) / len(values), "max": max(values)}}
with open("estimation_results.json", "w") as f:
    json.dump(out, f, indent=2)
"""


def _study(where: Path) -> Path:
    """A finished study, exported: rates loaded from open sources, cleaned, estimated (no third-party package)."""
    from src.core.export.structured import export_paper
    from src.core.specialists.post_execution import _run_recorded

    ws = where / "workspaces" / "2026-10-30-road-deaths"
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": "p-reviewer", "title": "Road deaths"}), "utf-8", newline="\n"
    )
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE rates_raw (location TEXT, spatial_type TEXT, value REAL)")
    con.executemany("INSERT INTO rates_raw VALUES (?,?,?)", RATES)
    con.execute("CREATE TABLE country_names (iso3 TEXT, name TEXT)")
    con.executemany("INSERT INTO country_names VALUES (?,?)", NAMES)
    con.commit()
    con.close()
    loads = [
        {
            "connector": "worldbank",
            "table": "rates_raw",
            "dataset": "World Development Indicators",
            "series": "rates_raw",
            "request": {"command": "series", "indicator": "SH.STA.TRAF.P5"},
            "retrieved_at": "2026-10-29T21:10:05Z",
        },
        {
            "connector": "naturalearth",
            "table": "country_names",
            "dataset": "Natural Earth",
            "series": "country_names",
            "request": {"command": "countries", "scale": "50m"},
            "retrieved_at": "2026-10-29T21:10:05Z",
        },
    ]
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8", newline="\n")
    for name, text in (("clean_rates.py", CLEAN), ("run_estimation.py", ESTIMATE)):
        (ws / name).write_text(text, encoding="utf-8", newline="\n")
        assert _run_recorded(ws, ws / name, 120, by="e2er-run") == 0
    return export_paper(ws, where / "exports", date_str="20261030")


def _pack(folder: Path, out: Path) -> dict[str, Any]:
    """The study as a .e2er file (as its authors would make it); the package's manifest."""
    from src.core.export import package as pkg

    # The study imports no package: its lock is empty (offline, as `uv pip compile` resolves it).
    packed = pkg.build(folder, out, locker=lambda requirements, python_minor, as_of: ("", ""))
    return packed.manifest


# ── the reviewer's computer ─────────────────────────────────────────────────


def _wheelhouse() -> Path:
    raw = os.environ.get("E2ER_REVIEWER_WHEELHOUSE", "").strip()
    if raw and Path(raw).is_dir():
        return Path(raw)
    why = (
        "needs E2ER_REVIEWER_WHEELHOUSE: a folder with the wheels of e2er's dependencies, downloaded before the "
        "test (`pip download --require-hashes -r .github/requirements/ci.txt -d <folder>`), so the install needs "
        "no network"
    )
    if os.environ.get("E2ER_REQUIRE_REVIEWER_PATH") == "1":
        pytest.fail(why)
    pytest.skip(why)


def _wheel(tmp: Path) -> Path:
    """The wheel CI built (E2ER_REVIEWER_WHEEL: the file or its folder), else one built here, offline."""
    raw = os.environ.get("E2ER_REVIEWER_WHEEL", "").strip()
    if raw:
        given = Path(raw)
        wheels = sorted(given.glob("e2er-*.whl")) if given.is_dir() else [given] if given.is_file() else []
        assert len(wheels) == 1, f"E2ER_REVIEWER_WHEEL={raw} names no single e2er wheel: {wheels}"
        return wheels[0]
    out = tmp / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(out), str(ROOT)],
        check=True,
        capture_output=True,
        timeout=600,
    )
    (wheel,) = out.glob("e2er-*.whl")
    return wheel


def _scripts(env_dir: Path) -> Path:
    return env_dir / ("Scripts" if WINDOWS else "bin")


def _exe(env_dir: Path, name: str) -> Path:
    return _scripts(env_dir) / (f"{name}.exe" if WINDOWS else name)


#: What a program needs from Windows itself to start (SYSTEMROOT: sockets and random numbers).
_SYSTEM_VARS = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
)  # fmt: skip


def _reviewer_env(home: Path, temp: Path, env_dir: Path) -> dict[str, str]:
    """A reviewer's shell: the new environment on PATH, an empty home, no token or key, nothing of the checkout."""
    env = {k: os.environ[k] for k in _SYSTEM_VARS if k in os.environ}
    path = [str(_scripts(env_dir))]
    docker = shutil.which("docker")
    if docker:  # Docker as the reviewer's computer has it (or not)
        path.append(str(Path(docker).parent))
    if WINDOWS:
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        path += [os.path.join(root, "System32"), root]
    else:
        path += ["/usr/local/bin", "/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(path)
    for var in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        env[var] = str(home)
    env["APPDATA"] = str(home / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    for var in ("TMPDIR", "TEMP", "TMP"):
        env[var] = str(temp)
    # e2er's test guard: nothing leaves this computer, the keychain is never touched.
    env["E2ER_TEST"] = "1"
    return env


class Reviewer:
    def __init__(self, env_dir: Path, cwd: Path, env: dict[str, str]):
        self.env_dir, self.cwd, self.env = env_dir, cwd, env

    def e2er(self, *args: str, timeout: float = 600, stdin: str | None = "") -> tuple[int, str]:
        """Run the installed `e2er`; (exit code, stdout and stderr). The output must be UTF-8 on every system."""
        proc = subprocess.run(
            [str(_exe(self.env_dir, "e2er")), *args],
            cwd=self.cwd,
            env=self.env,
            input=None if stdin is None else stdin.encode(),
            capture_output=True,
            timeout=timeout,
        )
        out = proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8")  # strict: a code page would fail here
        return proc.returncode, out.replace("\r\n", "\n")  # Windows ends lines with CRLF

    def python(self, code: str) -> str:
        """What the new environment's Python prints for ``code`` (a probe of the test's own, in UTF-8)."""
        proc = subprocess.run(
            [str(_exe(self.env_dir, "python")), "-c", code],
            capture_output=True, env={**self.env, "PYTHONIOENCODING": "utf-8"}, cwd=self.cwd, timeout=120,
        )  # fmt: skip
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        return proc.stdout.decode("utf-8").strip()


@pytest.fixture(scope="module")
def reviewer(tmp_path_factory) -> Reviewer:
    wheelhouse = _wheelhouse()
    base = tmp_path_factory.mktemp("reviewer") / WORK
    base.mkdir()
    wheel = _wheel(base.parent)
    env_dir = base / "e2er env"
    venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    py = _exe(env_dir, "python")
    proc = subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-index",
         "--find-links", str(wheelhouse), str(wheel)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=1200,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    home, temp, cwd = base / "home (empty)", base / "temp ü, 2", base / "Arbeitsordner ä"
    for d in (home, temp, cwd):
        d.mkdir()
    return Reviewer(env_dir, cwd, _reviewer_env(home, temp, env_dir))


@pytest.fixture(scope="module")
def study_package(reviewer: Reviewer, tmp_path_factory) -> tuple[Path, Path, dict[str, Any]]:
    """(the exported study folder, its .e2er file in the reviewer's folder, the package's manifest)."""
    author = tmp_path_factory.mktemp("author") / "Autorin ç"
    folder = _study(author)
    package = reviewer.cwd / "road deaths ü.e2er"
    return folder, package, _pack(folder, package)


# ── a local copy of e2er.org that records the package, and the file host ────


class _Site:
    """e2er.org's GET endpoints for one study, and the file host (GitHub's place) on 127.0.0.1."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes, str]] = {}
        self.seen: list[str] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server's name
                site.seen.append(self.path)
                code, body, kind = site.routes.get(self.path.split("?")[0], (404, b'{"error":"not found"}', "json"))
                self.send_response(code)
                self.send_header("content-type", "application/json" if kind == "json" else "application/octet-stream")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def json(self, path: str, doc: Any) -> None:
        self.routes[path] = (200, json.dumps(doc).encode(), "json")

    def file(self, path: str, data: bytes) -> None:
        self.routes[path] = (200, data, "file")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(scope="module")
def site(study_package) -> Iterator[_Site]:
    folder, package, manifest = study_package
    s = _Site()
    data = package.read_bytes()
    s.file("/files/road-deaths-v1.e2er", data)
    record = {
        "url": f"{s.base}/files/road-deaths-v1.e2er",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "host": "github",
        "fingerprint": manifest["fingerprint"],
    }
    content_id = "sha256:" + hashlib.sha256((folder / "provenance.json").read_bytes()).hexdigest()
    s.json(
        "/api/v1/studies/ada/road-deaths",
        {"versions": [{"number": 1, "content_id": content_id, "package": record}], "latest": {"number": 1}},
    )
    # Another study: what e2er.org says about it is not this package.
    s.json(
        "/api/v1/studies/ada/other",
        {"versions": [{"number": 1, "content_id": "sha256:" + "0" * 64, "package": None}], "latest": {"number": 1}},
    )
    # A record whose SHA-256 is not the file's (the file changed after publishing).
    s.json(
        "/api/v1/studies/ada/changed",
        {
            "versions": [{"number": 1, "content_id": content_id, "package": {**record, "sha256": "f" * 64}}],
            "latest": {"number": 1},
        },
    )
    yield s
    s.close()


# ── the reviewer's commands ─────────────────────────────────────────────────


def test_the_installed_e2er_names_its_version_and_runs_outside_the_checkout(reviewer):
    code, out = reviewer.e2er("--version")
    assert code == 0, out
    version = reviewer.python("import importlib.metadata as m; print(m.version('e2er'))")
    assert out.strip() == f"e2er {version}"
    where = reviewer.python("import src; print(src.__file__)")
    assert Path(where).resolve().is_relative_to(reviewer.env_dir.resolve()), where


def test_inspect_shows_what_the_package_holds_and_unpacks_nothing(reviewer, study_package):
    _folder, package, manifest = study_package
    before = sorted(p.name for p in reviewer.cwd.iterdir())
    code, out = reviewer.e2er("inspect", package.name)
    assert code == 0, out
    assert "road deaths ü.e2er" in out
    assert "Title: Road deaths" in out
    assert "included: data/data.db" in out
    assert f"Fingerprint: {manifest['fingerprint']}" in out
    assert "Packages: code/requirements.txt lists no packages" in out
    assert "  3. python run_estimation.py" in out
    assert sorted(p.name for p in reviewer.cwd.iterdir()) == before, "inspect wrote nothing"


def test_unpack_checks_every_file_into_a_folder_with_spaces_and_umlauts(reviewer, study_package):
    folder, package, manifest = study_package
    code, out = reviewer.e2er("unpack", package.name, "entpackt ö")
    assert code == 0, out
    root = reviewer.cwd / "entpackt ö"
    assert f"{len(manifest['contents'])} file(s) match e2er-package.json" in out
    quoted = f'"{root}"' if WINDOWS else f"'{root}'"
    assert f"Next: e2er verify {quoted}    e2er reproduce {quoted}" in out, out
    assert (root / "provenance.json").read_bytes() == (folder / "provenance.json").read_bytes()
    assert (root / "data" / "data.db").read_bytes() == (folder / "data" / "data.db").read_bytes()
    code, out = reviewer.e2er("verify", "entpackt ö")
    assert code == 0, out
    assert "Bundle verified" in out


def test_verify_the_package_offline(reviewer, study_package):
    _folder, package, _ = study_package
    code, out = reviewer.e2er("verify", package.name)
    assert code == 0, out
    assert "[PASS] package" in out and "[PASS] integrity" in out
    assert "Bundle verified" in out
    code, out = reviewer.e2er("verify", "--json", package.name)
    assert code == 0, out
    assert {c["name"]: c["status"] for c in json.loads(out)["checks"]}["package"] == "PASS"


def test_verify_against_the_published_record(reviewer, study_package, site):
    _folder, package, _ = study_package
    code, out = reviewer.e2er("verify", package.name, "--against", f"{site.base}/ada/road-deaths")
    assert code == 0, out
    assert "[PASS] published" in out, out
    assert re.search(r"\[PASS\] package published\s+its fingerprint is the one", out), out
    assert "byte for byte" in out
    # The same file against a study it is not.
    code, out = reviewer.e2er("verify", package.name, "--against", f"{site.base}/ada/other")
    assert code == 1, out
    assert "[FAIL] published" in out


def test_fetch_downloads_the_recorded_package_and_checks_it(reviewer, study_package, site):
    _folder, package, _ = study_package
    (reviewer.cwd / "downloads ü").mkdir()
    code, out = reviewer.e2er("fetch", f"{site.base}/ada/road-deaths", "-o", "downloads ü")
    assert code == 0, out
    got = reviewer.cwd / "downloads ü" / "road-deaths-v1.e2er"
    assert got.read_bytes() == package.read_bytes()
    assert "as e2er.org records it" in out
    assert "Nothing was opened or run" in out
    # The printed commands work when pasted: the path with its spaces is quoted for this system's shell.
    shown = Path("downloads ü") / "road-deaths-v1.e2er"  # as the reader gave the folder: relative
    quoted = f'"{shown}"' if WINDOWS else f"'{shown}'"
    assert f"e2er verify {quoted} --against {site.base}/ada/road-deaths" in out, out
    code, out = reviewer.e2er("verify", str(shown), "--against", f"{site.base}/ada/road-deaths")
    assert code == 0, out
    # A file whose SHA-256 is not the recorded one is not kept.
    (reviewer.cwd / "changed").mkdir()
    code, out = reviewer.e2er("fetch", f"{site.base}/ada/changed", "-o", "changed")
    assert code == 1, out
    assert "SHA-256 is not the one e2er.org records" in out
    assert list((reviewer.cwd / "changed").iterdir()) == []


def _docker_runs_linux(reviewer: Reviewer) -> bool:
    """Whether `e2er reproduce` on the reviewer's computer gets a sandbox (asked of the installed e2er)."""
    probe = "from src.core import reproduce_sandbox as rs; print('yes' if rs.available()[0] else 'no')"
    return reviewer.python(probe) == "yes"


def _reproduced(out: str) -> None:
    assert "Reproduced: every compared value is identical" in out, out
    assert "results/estimation_results.json: 3 values: 3 identical" in out, out
    assert "Inputs, compared with the study's own files (SHA-256):\n  1 of 1 identical" in out, out
    plan = out.index("The study's reproduce.json runs these commands, in this order:")
    assert plan < out.index("Running the study's code in"), "the commands are shown before anything runs"


def test_reproduce_in_the_sandbox_or_the_plain_refusal(reviewer, study_package):
    _folder, package, _ = study_package
    expected = os.environ.get("E2ER_REVIEWER_REPRODUCE", "").strip()
    sandbox = _docker_runs_linux(reviewer)
    if expected:
        assert expected in ("sandbox", "refusal"), expected
        assert sandbox == (expected == "sandbox"), (
            f"E2ER_REVIEWER_REPRODUCE={expected}, but this computer "
            + ("offers" if sandbox else "does not offer")
            + " a Docker sandbox with Linux containers"
        )
    if sandbox:
        code, out = reviewer.e2er("reproduce", package.name)
        assert code == 2 and "Nothing was run: without a terminal to ask in, --yes runs these commands." in out
        code, out = reviewer.e2er("reproduce", "--yes", package.name, timeout=1800)
        assert code == 0, out
        assert "They run in a Docker container (python:" in out
        _reproduced(out)
        return
    code, out = reviewer.e2er("reproduce", package.name)
    assert code == 2, out
    assert out.startswith("Unpacked road deaths ü.e2er into "), out
    assert "error: nothing was run. " in out
    assert "e2er reproduce runs the study's code in a Docker sandbox" in out
    assert "--no-sandbox runs the code on this computer as you instead" in out
    assert "Traceback" not in out


def test_reproduce_without_the_sandbox_reproduces_the_study_exactly(reviewer, study_package):
    _folder, package, _ = study_package
    code, out = reviewer.e2er("reproduce", "--no-sandbox", "--yes", package.name, timeout=1800)
    assert code == 0, out
    assert "with --no-sandbox they run on this computer AS YOU" in out
    _reproduced(out)
    assert "The network guard could not be put into the environment" not in out
    leftovers = [p.name for p in Path(reviewer.env["TEMP"]).iterdir() if p.name.startswith("e2er-")]
    assert leftovers == [], "the run folder and the unpacked package are removed"
    # e2er keeps nothing in the reviewer's home (pip, which builds the study's environment, keeps its cache there).
    assert not [p for p in Path(reviewer.env["HOME"]).rglob("*") if p.name in (".e2er", "e2er-studies")]
