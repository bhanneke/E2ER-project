"""The `replication` template: the Zenodo connector, the fetch step, the plan
contract, the Docker sandbox's commands, the reproduction check, and the
runner's handling of fixed specialist steps and checks that run as steps.

No network, no Docker, no model: HTTP goes through an ``httpx.MockTransport``
and every ``docker`` invocation through a recording fake.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest

from src.core.pipeline import replication as repl
from src.core.pipeline.reproduction import (
    CHECK_FILE,
    check_report,
    check_reproduction,
    equal_to_target,
    label_for,
    reason_text_problems,
)
from src.core.pipeline.sandbox import (
    LOG_FILE,
    Limits,
    env_tag,
    install_argv,
    install_script,
    resolve_snapshot,
    run_argv,
    run_sandbox,
)
from src.core.pipeline.spec import SCHEMA_PATH, PipelineError, find_spec, spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.specialists.contracts import Contribution
from src.core.strategist.state import GateHaltError, HumanReviewRequestedError
from src.modules.data.zenodo import (
    ZenodoChecksumError,
    ZenodoClient,
    ZenodoError,
    linked_publications,
    parse_record_id,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "pipelines" / "replication.toml"
PID = "12345678-1234-1234-1234-123456789abc"


# ── fixtures: a small package and a fake Zenodo ─────────────────────────────


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


PACKAGE = {
    "study/README.md": b"# Study\nRun Rscript code/main.R from study/.\n",
    "study/code/main.R": b"x <- read.csv('data/panel.csv')\nwrite.csv(x, 'output/table1.csv')\n",
    "study/data/panel.csv": b"id,y\n1,2\n",
    "study/output/shipped.csv": b"term,estimate\natt,-0.012\n",
    "study/output/untouched.csv": b"term,estimate\nn,5570\n",
}


def _pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {len(objs)} 0 R >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


PAPER = _pdf(["A study of things", "Table 1: ATT -0.012 (0.004) N 5570"])


def _record(files: dict[str, bytes], *, access: str = "open", checksum_override: str | None = None) -> dict:
    return {
        "id": 424242,
        "doi": "10.5281/zenodo.424242",
        "links": {"html": "https://zenodo.org/records/424242"},
        "access": {"files": access},
        "metadata": {
            "title": "Replication package: a study",
            "creators": [{"name": "Doe, Jane"}],
            "license": {"id": "cc-by-4.0"},
            "publication_date": "2026-08-30",
            "version": "v1",
            "description": "<p>Code for the paper.</p>",
            "related_identifiers": [
                {"identifier": "10.2139/ssrn.1", "relation": "isSupplementTo", "resource_type": "publication-preprint"},
                {"identifier": "10.2908/TOUR", "relation": "isDerivedFrom", "resource_type": "dataset"},
            ],
        },
        "files": [
            {
                "key": key,
                "size": len(data),
                "checksum": checksum_override or "md5:" + hashlib.md5(data).hexdigest(),
                "links": {"self": f"https://zenodo.org/api/records/424242/files/{key}/content"},
            }
            for key, data in files.items()
        ],
    }


def _client(record: dict, blobs: dict[str, bytes], calls: list[str] | None = None) -> ZenodoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        assert "authorization" not in {k.lower() for k in request.headers}, "the connector is keyless"
        path = request.url.path
        if path == "/api/records/424242":
            return httpx.Response(200, json=record)
        for key, data in blobs.items():
            if path == f"/api/records/424242/files/{key}/content":
                return httpx.Response(200, content=data)
        return httpx.Response(404)

    return ZenodoClient(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


@pytest.fixture
def workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(
        json.dumps({"research_question": "Computational reproduction of A study (10.5281/zenodo.424242)"})
    )
    yield ws
    for d in ("package", "package_archive"):
        if (ws / d).exists():
            repl.make_writable(ws / d)


def _fetched(ws: Path) -> Path:
    blob = _zip_bytes(PACKAGE)
    result = repl.fetch_package(ws, client=_client(_record({"pkg.zip": blob}), {"pkg.zip": blob}))
    assert result.passed, result.reasons
    return ws / "package"


# ── the Zenodo connector ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "rid"),
    [
        ("Computational reproduction of X (10.5281/zenodo.22179151)", "22179151"),
        ("https://zenodo.org/records/123", "123"),
        ("https://zenodo.org/api/records/77/files", "77"),
        ("no record here", None),
    ],
)
def test_the_record_id_is_read_from_a_doi_or_a_link(text, rid):
    assert parse_record_id(text) == rid


def test_a_record_downloads_verified_with_sha256_and_its_publication(tmp_path: Path):
    blob = b"hello replication"
    calls: list[str] = []
    rec = _client(_record({"a.txt": blob}), {"a.txt": blob}, calls).fetch("424242", tmp_path)
    f = rec.files[0]
    assert f.verified and f.sha256 == hashlib.sha256(blob).hexdigest() and f.size == len(blob)
    assert f.zenodo_checksum == "md5:" + hashlib.md5(blob).hexdigest()
    assert (tmp_path / "a.txt").read_bytes() == blob
    # the paper the record supplements, not the dataset it was derived from
    assert [p["identifier"] for p in rec.publications] == ["10.2139/ssrn.1"]
    assert calls[0].endswith("/api/records/424242")


def test_a_checksum_mismatch_fails_and_leaves_no_file(tmp_path: Path):
    blob = b"tampered"
    client = _client(_record({"a.txt": blob}, checksum_override="md5:" + "0" * 32), {"a.txt": blob})
    with pytest.raises(ZenodoChecksumError, match="does not match"):
        client.fetch("424242", tmp_path)
    assert not (tmp_path / "a.txt").exists()


@pytest.mark.parametrize(
    ("record", "match"),
    [
        (_record({"a.txt": b"x"}, access="restricted"), "restricted"),
        ({**_record({"a.txt": b"x"}), "files": []}, "no files"),
        ({**_record({"../evil": b"x"})}, "refusing file name"),
    ],
)
def test_records_that_are_not_open_packages_are_refused(tmp_path: Path, record, match):
    with pytest.raises(ZenodoError, match=match):
        _client(record, {"a.txt": b"x"}).fetch("424242", tmp_path)


def test_the_size_limit_is_enforced_before_downloading(tmp_path: Path):
    calls: list[str] = []
    blob = b"x" * 100
    with pytest.raises(ZenodoError, match="above the limit"):
        _client(_record({"a.txt": blob}), {"a.txt": blob}, calls).fetch("424242", tmp_path, max_bytes=10)
    assert len(calls) == 1  # the record, and no file


def test_requests_are_paced(tmp_path: Path):
    slept: list[float] = []
    blob = b"x"
    rec, blobs = _record({"a.txt": blob, "b.txt": blob}), {"a.txt": blob, "b.txt": blob}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/424242"):
            return httpx.Response(200, json=rec)
        return httpx.Response(200, content=blobs[request.url.path.split("/")[-2]])

    client = ZenodoClient(client=httpx.Client(transport=httpx.MockTransport(handler)), delay=1.5, sleep=slept.append)
    client.fetch("424242", tmp_path)
    assert slept == [1.5, 1.5]  # between the three requests, not before the first


def test_description_dois_count_as_publications():
    meta = {"description": "Replication for doi.org/10.1016/j.jpubeco.2019.104123.", "related_identifiers": []}
    assert linked_publications(meta)[0]["identifier"] == "10.1016/j.jpubeco.2019.104123"


# ── the fetch step ──────────────────────────────────────────────────────────


def test_fetch_unpacks_hashes_and_freezes_the_package(workspace: Path):
    package = _fetched(workspace)
    manifest = json.loads((workspace / "package_manifest.json").read_text())
    assert manifest["record_id"] == "424242" and manifest["package_root"] == "study"
    paths = {f["path"]: f["sha256"] for f in manifest["package_files"]}
    assert paths["study/code/main.R"] == hashlib.sha256(PACKAGE["study/code/main.R"]).hexdigest()
    assert manifest["files"][0]["verified"] is True
    target = package / "study" / "code" / "main.R"
    with pytest.raises(PermissionError):
        target.write_text("changed")


def test_fetch_on_resume_rehashes_and_catches_a_changed_byte(workspace: Path):
    package = _fetched(workspace)
    again = repl.fetch_package(workspace, client=None)  # no network needed on resume
    assert again.passed and "unchanged" in again.detail()
    f = package / "study" / "data" / "panel.csv"
    f.chmod(0o644)
    f.write_text("id,y\n1,3\n")
    bad = repl.fetch_package(workspace)
    assert not bad.passed and "study/data/panel.csv changed" in bad.reasons[0]


def test_fetch_skips_members_that_escape_the_package(workspace: Path):
    blob = _zip_bytes({"ok/a.R": b"1", "../escape.R": b"2", "/abs.R": b"3"})
    r = repl.fetch_package(workspace, client=_client(_record({"p.zip": blob}), {"p.zip": blob}))
    assert r.passed
    assert not (workspace.parent / "escape.R").exists() and (workspace / "package" / "ok" / "a.R").is_file()
    assert sum("skipped archive member" in n for n in r.notes) == 2


def test_fetch_without_a_zenodo_record_in_the_question_fails(workspace: Path):
    (workspace / "manifest.json").write_text(json.dumps({"research_question": "Reproduce something"}))
    r = repl.fetch_package(workspace)
    assert not r.passed and "names no Zenodo record" in r.reasons[0]


# ── the plan contract ───────────────────────────────────────────────────────


def _plan(**over: Any) -> dict:
    plan = {
        "schema_version": 1,
        "study": {"title": "A study", "zenodo_doi": "10.5281/zenodo.424242"},
        "language": "R",
        "environment": {"image": "rocker/r-ver:4.4.1", "packages": [{"name": "fixest", "version": "0.12.1"}]},
        "entry_points": [{"id": "main", "command": ["Rscript", "code/main.R"], "cwd": "study"}],
        "exhibits": [{"id": "table_1", "label": "Table 1", "kind": "table", "scripts": ["main"]}],
        "targets": [
            {
                "id": "t1_att",
                "level": 2,
                "exhibit": "table_1",
                "label": "ATT",
                "value": -0.012,
                "reported": "-0.012",
                "source": {
                    "kind": "paper",
                    "document": "paper/paper.pdf",
                    "page": 2,
                    "table": "Table 1",
                    "decimals": 3,
                },
            },
            {
                "id": "l1_att",
                "level": 1,
                "exhibit": "table_1",
                "label": "ATT in the shipped result file",
                "value": -0.012,
                "reported": "-0.012",
                "source": {
                    "kind": "package_file",
                    "file": "study/output/shipped.csv",
                    "locator": {"row": {"term": "att"}, "column": "estimate"},
                },
            },
        ],
    }
    plan.update(over)
    return plan


def test_a_sound_plan_passes_against_the_package(workspace: Path):
    package = _fetched(workspace)
    assert repl.validate_plan(_plan(), package) == []


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"environment": {"image": "rocker/r-ver:latest"}}, "pinned official image"),
        ({"environment": {"image": "evil/r:4.4.1"}}, "pinned official image"),
        ({"environment": {"image": "python:3.12-slim"}}, "R study runs on rocker"),
        ({"entry_points": [{"id": "m", "command": ["Rscript", "-e", "system('curl x')"], "cwd": "study"}]}, "flags"),
        ({"entry_points": [{"id": "m", "command": ["bash", "code/main.R"], "cwd": "study"}]}, "allowed for R"),
        ({"entry_points": [{"id": "m", "command": ["Rscript", "../x.R"], "cwd": "study"}]}, "package-relative"),
        ({"entry_points": [{"id": "m", "command": ["Rscript", "code/none.R"], "cwd": "study"}]}, "does not exist"),
        ({"entry_points": [{"id": "m", "command": ["Rscript", "code/main.R"], "cwd": "/etc"}]}, "inside the package"),
        ({"environment": {"image": "rocker/r-ver:4.4.1", "system_packages": ["x; rm -rf /"]}}, "apt package"),
        ({"environment": {"image": "rocker/r-ver:4.4.1", "packages": [{"name": "a'b"}]}}, "plain package name"),
        ({"targets": [{"id": "t", "exhibit": "nope", "value": 1, "reported": "1", "source": {}}]}, "not in exhibits"),
        ({"entry_points": []}, "at least one script"),
    ],
)
def test_an_unsafe_or_broken_plan_is_refused(workspace: Path, over, match):
    package = _fetched(workspace)
    errs = repl.validate_plan(_plan(**over), package)
    assert any(match in e for e in errs), errs


def test_the_plan_schema_accepts_the_documented_example():
    schema = json.loads((ROOT / "docs" / "schemas" / "replication_plan.schema.json").read_text())
    jsonschema.validators.validator_for(schema)(schema).validate(_plan())


def test_the_planner_contract_includes_the_plan_structure(workspace: Path):
    from src.core.specialists.contract_check import check_specialist_artifacts

    _supply_paper(workspace)
    _fetched(workspace)
    (workspace / "replication_plan.md").write_text("# Plan\n" + "x" * 200)
    (workspace / "replication_plan.json").write_text(json.dumps(_plan(language="Stata")))
    bad = [c for c in check_specialist_artifacts(workspace, "replication_planner") if not c.ok]
    assert bad and "language" in bad[0].reason
    (workspace / "replication_plan.json").write_text(json.dumps(_plan()))
    assert all(c.ok for c in check_specialist_artifacts(workspace, "replication_planner"))


# ── the sandbox: commands, without Docker ───────────────────────────────────


def test_the_run_command_has_no_network_a_read_only_package_and_limits(tmp_path: Path):
    pkg, out = tmp_path / "package", tmp_path / "sandbox" / "run"
    argv = run_argv(
        "docker",
        "e2er-sandbox:abc",
        "e2er-run-1",
        pkg,
        out,
        {"command": ["Rscript", "code/main.R"], "cwd": "study"},
        Limits(cpus=2, memory_gb=6, pids=256),
    )
    joined = " ".join(argv)
    assert argv[argv.index("--network") + 1] == "none"
    assert f"type=bind,source={pkg.resolve()},target=/work/package,readonly" in argv
    assert f"type=bind,source={out.resolve()},target=/work/run" in argv
    assert {"--cpus=2", "--memory=6g", "--memory-swap=6g", "--pids-limit=256", "--cap-drop=ALL"} <= set(argv)
    assert "--read-only" in argv and "--security-opt=no-new-privileges" in argv and "--rm" in argv
    assert argv[argv.index("--user") + 1] == "1000:1000"  # never root
    assert argv[argv.index("-w") + 1] == "/work/run/study"
    assert argv[-2:] == ["Rscript", "code/main.R"]  # an argv, never a shell string
    assert str(Path.home()) not in joined.replace(str(tmp_path), "")
    assert sum(a == "--mount" for a in argv) == 2 and "-v" not in argv  # nothing else is mounted


def test_the_install_command_mounts_nothing_and_runs_only_package_managers():
    plan = _plan(
        environment={
            "image": "rocker/r-ver:4.4.1",
            "packages": [{"name": "fixest"}],
            "system_packages": ["libxml2-dev"],
        }
    )
    script = install_script(plan)
    argv = install_argv("docker", "rocker/r-ver:4.4.1", "e2er-install-1", script, Limits())
    assert "--mount" not in argv and "-v" not in argv and "--network" not in argv
    assert "--security-opt=no-new-privileges" in argv and "--memory=4g" in argv
    assert "apt-get install -y --no-install-recommends libxml2-dev" in script
    assert "install.packages(pk" in script and 'c("fixest")' in script
    assert "code/main.R" not in script  # the package's code never runs with network
    py = install_script(
        _plan(
            language="Python",
            environment={"image": "python:3.12-slim", "packages": [{"name": "pandas", "version": "2.2.2"}]},
        )
    )
    assert "pip install --no-cache-dir pandas==2.2.2" in py
    assert env_tag(plan) == env_tag(plan) and env_tag(plan) != env_tag(_plan())


class FakeDocker:
    """Records every command; answers like Docker; writes a result as the 'script' would."""

    def __init__(self, workspace: Path, *, up: bool = True, fail: set[str] = frozenset(), hang: set[str] = frozenset()):
        self.ws, self.up, self.fail, self.hang = workspace, up, fail, hang
        self.calls: list[list[str]] = []
        self.images: set[str] = set()

    def __call__(self, argv, capture_output=True, timeout=None, **kw):
        self.calls.append(list(argv))
        assert argv[0] == "docker", "only docker is ever executed"
        sub = argv[1]
        ok = subprocess.CompletedProcess(argv, 0, b"", b"")
        if sub == "info":
            return ok if self.up else subprocess.CompletedProcess(argv, 1, b"", b"Cannot connect")
        if sub == "image" and argv[2] == "inspect":
            if "--format" in argv:
                return subprocess.CompletedProcess(argv, 0, b'["rocker/r-ver@sha256:abc"]', b"")
            return ok if argv[-1] in self.images else subprocess.CompletedProcess(argv, 1, b"", b"")
        if sub == "pull":
            self.images.add(argv[-1])
            return ok
        if sub == "commit":
            self.images.add(argv[-1])
            return ok
        if sub == "rm":
            return ok
        if sub == "run" and "--rm" not in argv:  # install
            return subprocess.CompletedProcess(
                argv, 0, b"E2ER-INSTALLED-BEGIN\nfixest==0.12.1\nE2ER-INSTALLED-END\n", b""
            )
        if sub == "run" and "E2ER-INSTALLED-BEGIN" in argv[-1]:  # the environment probe (no network)
            assert argv[argv.index("--network") + 1] == "none"
            probe = (
                b"E2ER-REPOS https://p3m.dev/cran/__linux__/noble/2026-08-30\n"
                b"E2ER-PLATFORM aarch64-unknown-linux-gnu\n"
                b"E2ER-INSTALLED-BEGIN\nfixest==0.12.1\nDRDID==1.3.0\nE2ER-INSTALLED-END\n"
            )
            return subprocess.CompletedProcess(argv, 0, probe, b"")
        if sub == "run":
            script = argv[-1]
            if script in self.hang:
                raise subprocess.TimeoutExpired(argv, timeout, output=b"partial", stderr=b"")
            if script in self.fail:
                return subprocess.CompletedProcess(argv, 1, b"", b"Error: object 'x' not found")
            out = self.ws / "sandbox" / "run" / "study" / "output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "table1.csv").write_text("term,estimate,se\natt,-0.01214,0.004\n")
            (out / "shipped.csv").write_text("term,estimate\natt,-0.0131\n")  # the rebuilt shipped file
            return ok
        raise AssertionError(f"unexpected docker call {argv}")


def _supply_paper(ws: Path, pdf: bytes = PAPER) -> Path:
    (ws / "data").mkdir(exist_ok=True)
    (ws / "data" / "paper.pdf").write_bytes(pdf)
    return ws / "data" / "paper.pdf"


def _ready(ws: Path, plan: dict | None = None) -> None:
    _supply_paper(ws)
    _fetched(ws)
    (ws / "replication_plan.json").write_text(json.dumps(plan or _plan()))


def test_the_sandbox_runs_logs_and_hashes_through_docker_only(workspace: Path):
    _ready(workspace)
    fake = FakeDocker(workspace)
    r = run_sandbox(workspace, runner=fake, docker="docker", memory_gb=6)
    assert r.passed, r.reasons
    log = json.loads((workspace / LOG_FILE).read_text())
    run = log["runs"][0]
    assert run["status"] == "ok" and run["exit_code"] == 0 and "--network" in run["argv"]
    assert log["image_digest"] == "rocker/r-ver@sha256:abc" and log["install"]["installed"] == {
        "fixest": "0.12.1",
        "DRDID": "1.3.0",
    }
    written = {o["path"]: o for o in log["outputs"]}
    assert written["study/output/table1.csv"]["state"] == "new"
    assert (
        written["study/output/table1.csv"]["sha256"]
        == hashlib.sha256((workspace / "sandbox/run/study/output/table1.csv").read_bytes()).hexdigest()
    )
    assert written["study/output/shipped.csv"]["state"] == "changed"  # rebuilt by the run
    assert "study/output/untouched.csv" not in written  # a shipped result the run did not write
    assert log["package_intact"] is True
    kinds = [c[1] for c in fake.calls]
    assert kinds.count("pull") == 1 and kinds.count("commit") == 1


def test_a_failing_script_is_a_result_not_a_failed_step(workspace: Path):
    _ready(workspace)
    r = run_sandbox(workspace, runner=FakeDocker(workspace, fail={"code/main.R"}), docker="docker")
    assert r.passed and "main: failed" in r.notes
    run = json.loads((workspace / LOG_FILE).read_text())["runs"][0]
    assert run["exit_code"] == 1 and "not found" in run["stderr_tail"]


def test_a_script_past_its_time_limit_is_killed(workspace: Path):
    _ready(workspace)
    fake = FakeDocker(workspace, hang={"code/main.R"})
    r = run_sandbox(workspace, runner=fake, docker="docker", timeout_minutes=1)
    assert r.passed and json.loads((workspace / LOG_FILE).read_text())["runs"][0]["status"] == "timed_out"
    assert fake.calls[-1][1:3] == ["rm", "-f"] and fake.calls[-1][3].startswith("e2er-run-")


def test_network_scripts_are_skipped_not_run(workspace: Path):
    plan = _plan(
        entry_points=[{"id": "dl", "command": ["Rscript", "code/main.R"], "cwd": "study", "needs_network": True}],
        exhibits=[],
        targets=[],
    )
    _ready(workspace, plan)
    fake = FakeDocker(workspace)
    assert run_sandbox(workspace, runner=fake, docker="docker").passed
    assert not any(c[1] == "run" and "--rm" in c and "E2ER-INSTALLED-BEGIN" not in c[-1] for c in fake.calls)


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        (lambda ws: None, "has not been fetched"),
        (lambda ws: _fetched(ws), "replication_plan.json is missing"),
        (lambda ws: _ready(ws, _plan(environment={"image": "ubuntu:latest"})), "pinned official image"),
    ],
)
def test_the_sandbox_refuses_to_start_without_a_sound_plan(workspace: Path, setup, match):
    setup(workspace)
    fake = FakeDocker(workspace)
    r = run_sandbox(workspace, runner=fake, docker="docker")
    assert not r.passed and match in r.reasons[0] and fake.calls == []


def test_the_sandbox_says_when_docker_is_not_running(workspace: Path):
    _ready(workspace)
    r = run_sandbox(workspace, runner=FakeDocker(workspace, up=False), docker="docker")
    assert not r.passed and "Docker is not running" in r.reasons[0]


# ── the reproduction check ──────────────────────────────────────────────────


def _ran(ws: Path) -> None:
    _ready(ws)
    assert run_sandbox(ws, runner=FakeDocker(ws), docker="docker").passed


def _l1(level: str = "reproduced_minor", reproduced: Any = -0.0131, **comp: Any) -> dict:
    c = {
        "target_id": "l1_att",
        "published": -0.012,
        "reproduced": reproduced,
        "label": level,
        "source": {"file": "study/output/shipped.csv"},
    }
    c.update(comp)
    return {"id": "table_1_l1", "target_level": 1, "level": level, "reason": "r", "comparisons": [c]}


def _report(level: str = "reproduced", reproduced: Any = -0.01214, l1: dict | None = None, **comp: Any) -> dict:
    c = {
        "target_id": "t1_att",
        "published": -0.012,
        "reproduced": reproduced,
        "abs_diff": None if reproduced is None else round(reproduced + 0.012, 10),
        "label": level,
        "source": {"file": "study/output/table1.csv", "locator": {"row": {"term": "att"}, "column": "estimate"}},
    }
    c.update(comp)
    return {
        "results": [
            {"id": "table_1_l2", "target_level": 2, "level": level, "reason": "r", "comparisons": [c]},
            l1 or _l1(),
        ]
    }


def _env(ws: Path) -> dict:
    log = json.loads((ws / LOG_FILE).read_text())
    return {
        "snapshot": {"date": log["snapshot"]["date"], "url": log["snapshot"]["url"]},
        "platform": log["install"]["platform"],
        "installed": dict(log["install"]["installed"]),
    }


def _write(ws: Path, report: dict) -> None:
    if "environment" not in report and (ws / LOG_FILE).is_file():
        report = {**report, "environment": _env(ws)}
    (ws / "reproduction_report.json").write_text(json.dumps(report))


def test_a_truthful_report_passes_and_every_number_is_recomputed(workspace: Path):
    _ran(workspace)
    _write(workspace, _report())
    r = check_reproduction(workspace)
    assert r.passed, r.reasons
    checked = json.loads((workspace / CHECK_FILE).read_text())["checked"][0]
    assert checked["recomputed"] == -0.01214 and checked["equal_to_target"] is True


def test_equal_at_the_published_precision_may_be_called_reproduced(workspace: Path):
    _ran(workspace)
    _write(workspace, _report(level="reproduced"))
    assert check_reproduction(workspace).passed


@pytest.mark.parametrize(
    ("report", "match"),
    [
        (_report(reproduced=-0.0131), "holds -0.01214, not the claimed -0.0131"),
        (_report(source={"file": "study/output/table1.csv"}, reproduced=-0.5), "no number"),
        (_report(source={"file": "study/output/untouched.csv"}), "not a file the sandbox run wrote"),
        (_report(published=-0.02), "is not the plan's"),
        (_report(target_id="t9"), "not a target"),
        (_report(level="could_not_run"), "could_not_run"),
        (_report(level="reproduced", reproduced=-0.01214, published=-0.012), None),
        (_report(abs_diff=0.5), "abs_diff"),
        ({"results": [], "unassessed": []}, "neither compared nor listed"),
        ({"results": [_l1()], "unassessed": []}, "level-2 target(s) neither compared"),
        (_report(l1=_l1(source={"file": "study/output/table1.csv"}, reproduced=-0.01214)), "read from the rebuilt"),
        (_report(l1=_l1(level="reproduced")), "'reproduced' but -0.0131 differs"),
        (_report(l1={**_l1(), "target_level": 2}), "a level-1 target reported under a level-2 result"),
        (_report(l1={**_l1(), "target_level": 3}), "target_level must be 1"),
    ],
)
def test_a_report_that_claims_what_the_outputs_do_not_hold_fails(workspace: Path, report, match):
    _ran(workspace)
    _write(workspace, report)
    r = check_reproduction(workspace)
    if match is None:
        assert r.passed
        return
    assert not r.passed and any(match in x for x in r.reasons), r.reasons


def test_a_level_that_contradicts_the_numbers_fails(workspace: Path):
    _ran(workspace)
    table = workspace / "sandbox/run/study/output/table1.csv"
    table.write_text("term,estimate,se\natt,-0.0150,0.004\n")
    _write(workspace, _report(level="reproduced_minor", reproduced=-0.015))
    r = check_reproduction(workspace)
    assert not r.passed and any("exceeds the minor tolerance" in x for x in r.reasons)
    _write(workspace, _report(level="not_reproduced", reproduced=-0.015))
    assert check_reproduction(workspace).passed
    _write(workspace, _report(level="reproduced_minor", reproduced=-0.015))
    assert check_reproduction(workspace, minor_rel_tolerance=0.3).passed


def test_an_unassessed_target_with_a_reason_is_accounted_for(workspace: Path):
    _ran(workspace)
    _write(
        workspace,
        {"results": [_l1()], "unassessed": [{"target_id": "t1_att", "reason": "only in a figure"}]},
    )
    assert check_reproduction(workspace).passed


def test_the_report_schema_accepts_what_the_check_accepts():
    schema = json.loads((ROOT / "docs" / "schemas" / "reproduction_report.schema.json").read_text())
    env = {"snapshot": {"date": "2026-08-30", "url": "https://p3m.dev/cran/2026-08-30"}, "installed": {"did": "2.5.1"}}
    jsonschema.validators.validator_for(schema)(schema).validate({**_report(), "environment": env})


def test_the_comparer_contract_needs_levels_and_reasons(tmp_path: Path):
    (tmp_path / "reproduction_report.json").write_text(json.dumps({"results": [{"level": "great"}]}))
    assert "level must be one of" in check_report(tmp_path)[0]


# ── the template ────────────────────────────────────────────────────────────


def test_the_template_validates_against_the_published_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    cls(schema).validate(tomllib.loads(TEMPLATE.read_text(encoding="utf-8")))


def test_the_template_loads_in_the_order_of_a_reproduction():
    spec = find_spec("replication")
    assert spec.sequence_for("single_pass") == [
        "fetch",
        "plan",
        "review_plan",
        "sandbox_run",
        "compare",
        "reproduction_gate",
        "review_report",
    ]
    assert spec.checks() == ["contracts", "package_integrity", "reproduction", "sandbox"]
    assert spec.step("review_plan").kind == "researcher" and "replication_plan.md" in spec.step("review_plan").files
    assert spec.step("plan").run == ("replication_planner",)
    assert spec.step("sandbox_run").settings["memory_gb"] == 6
    kinds = {s.kind for s in spec.steps}
    assert "strategist" not in kinds and "aggregate" not in kinds  # no drafting, no review panel
    assert "e2er contributors" in TEMPLATE.read_text()


@pytest.mark.parametrize(
    ("step", "match"),
    [
        ({"kind": "gate", "name": "g", "check": "sandbox", "after": ["replication_planner"]}, "takes no `after`"),
        ({"kind": "gate", "name": "g", "check": "sandbox", "settings": {"gpus": 1}}, "no setting"),
        ({"kind": "gate", "name": "g", "check": "reproduction", "settings": {"minor_rel_tolerance": 2}}, "share"),
        ({"kind": "gate", "name": "g", "check": "package_integrity", "settings": {"max_mb": 1.5}}, "whole number"),
    ],
)
def test_bad_replication_steps_fail_at_load(step, match):
    with pytest.raises(PipelineError, match=match):
        spec_from_dict({"name": "t", "steps": [step]})


def test_the_fetch_and_sandbox_checks_block_in_every_regime():
    from src.core.governance import enforces

    for regime in ("off", "contracts", "full"):
        assert enforces(regime, "package_integrity") and enforces(regime, "sandbox")
    assert not enforces("off", "reproduction") and enforces("full", "reproduction")


# ── the runner: fixed specialists, checks as steps, completion ──────────────


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


def _runner(ws: Path, governance: str = "full"):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id = PID
    r._workspace = ws
    r._mode = "single_pass"
    r._spec = find_spec("replication")
    r._triggers = []
    r._state = PipelineState(paper_id=PID, mode="single_pass")
    r._in_initial = False
    r._contributions = []
    r._governance = governance
    r._failure_counts = {}
    r._last_specialist_errors = {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers = [], []
    r._review_stages = set()
    return r


async def test_a_failed_check_step_halts_with_its_reasons_and_runs_again(workspace: Path, events):
    r = _runner(workspace)
    step = r._spec.step("sandbox_run")
    with pytest.raises(GateHaltError) as halt:
        await r._run_check_step(step, r._state)
    assert halt.value.stage == "sandbox_run" and "has not been fetched" in halt.value.reasons[0]
    assert r._state.pending_review_stage == "sandbox_run"
    assert r._state.metadata["review"]["kind"] == "gate"
    assert [(k, s, p["passed"], p["enforced"]) for k, s, p in events] == [("gate_enforced", "sandbox", False, True)]


async def test_a_reliability_check_blocks_even_with_governance_off(workspace: Path, events):
    (workspace / "manifest.json").write_text(json.dumps({"research_question": "no record"}))
    r = _runner(workspace, governance="off")
    with pytest.raises(GateHaltError):
        await r._run_check_step(r._spec.step("fetch"), r._state)
    assert events[0][0] == "gate_enforced"


async def test_a_fixed_specialist_step_dispatches_with_the_registry_focus(workspace: Path, monkeypatch):
    sent: list = []

    async def _exec(orders, *a, **k):
        sent.extend(orders)
        return [Contribution(paper_id=PID, specialist=o.specialist, output="", success=True) for o in orders]

    monkeypatch.setattr("src.core.strategist.runner.execute_with_dependencies", _exec)
    r = _runner(workspace)
    await r._run_specialists_step(r._spec.step("plan"))
    assert [o.specialist for o in sent] == ["replication_planner"]
    assert "package/" in sent[0].focus and "replication_plan.json" in sent[0].focus


async def test_a_failed_fixed_specialist_stops_the_step(workspace: Path, monkeypatch):
    async def _exec(orders, *a, **k):
        return [
            Contribution(paper_id=PID, specialist=o.specialist, output="", success=False, error="x") for o in orders
        ]

    monkeypatch.setattr("src.core.strategist.runner.execute_with_dependencies", _exec)
    r = _runner(workspace)
    with pytest.raises(RuntimeError, match="replication_planner failed"):
        await r._run_specialists_step(r._spec.step("plan"))


async def test_the_run_stops_at_the_plan_review_after_fetch_and_plan(workspace: Path, events, monkeypatch):
    """fetch -> plan -> review_plan: the run pauses for the researcher and runs nothing further."""
    blob = _zip_bytes(PACKAGE)
    client = _client(_record({"pkg.zip": blob}), {"pkg.zip": blob})
    monkeypatch.setattr("src.modules.data.zenodo.ZenodoClient", lambda: client)

    async def _exec(orders, *a, **k):
        (workspace / "replication_plan.json").write_text(json.dumps(_plan()))
        (workspace / "replication_plan.md").write_text("# Plan\n" + "x" * 200)
        return [Contribution(paper_id=PID, specialist=o.specialist, output="", success=True) for o in orders]

    monkeypatch.setattr("src.core.strategist.runner.execute_with_dependencies", _exec)
    ran: list[str] = []
    monkeypatch.setattr("src.core.pipeline.sandbox.run_sandbox", lambda *a, **k: ran.append("sandbox"))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr("src.modules.tracking.usage.check_budget", _noop)
    r = _runner(workspace)
    r._update_status = _noop
    r._best_effort_finalize = _noop
    r._max_cost_usd = 5.0
    r._pivot_count = r._iteration = 0
    r._deep_revision_count = 0
    r._in_memory_spent = lambda: 0.0
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.load", classmethod(lambda cls, *a: r._state))
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.save", lambda self, ws: None)
    out = await r.run()
    assert out["status"] == "paused" and out["stage"] == "review_plan"
    # fetch runs at every start (it re-verifies the package and picks up the paper), so it is never "complete"
    assert not r._state.is_complete("fetch") and r._state.is_complete("plan") and ran == []
    assert ("gate_enforced", "package_integrity", True) in [(k, st, p.get("passed")) for k, st, p in events]
    assert r._state.metadata["review"]["files"] == ["replication_plan.md", "replication_plan.json"]


# ── two levels of targets ───────────────────────────────────────────────────


def _level_errs(ws: Path, target: dict) -> list[str]:
    plan = _plan()
    plan["targets"] = [target]
    return repl.validate_plan(plan, ws / "package", ws)


def _l2_target(**src: Any) -> dict:
    t = _plan()["targets"][0]
    return {**t, "source": {**t["source"], **src}}


def _l1_target(**over: Any) -> dict:
    return {**_plan()["targets"][1], **over}


def test_both_levels_pass_with_the_paper_supplied(workspace: Path):
    _supply_paper(workspace)
    _fetched(workspace)
    assert repl.validate_plan(_plan(), workspace / "package", workspace) == []


@pytest.mark.parametrize(
    ("target", "match"),
    [
        (_l1_target(level=3), "level must be 1"),
        ({k: v for k, v in _l1_target().items() if k != "level"}, "level must be 1"),
        (_l1_target(source={"kind": "paper"}), "source.kind is 'package_file'"),
        (_l1_target(source={"kind": "package_file", "file": "study/output/shipped.csv"}), "locator needs row"),
        (_l1_target(source={"kind": "package_file", "file": "study/code/main.R", "locator": {}}), ".csv or .tsv"),
        (_l1_target(value=-0.5), "holds -0.012 at that cell, not -0.5"),
        (
            _l1_target(
                source={
                    "kind": "package_file",
                    "file": "study/output/none.csv",
                    "locator": {"row": {"term": "att"}, "column": "estimate"},
                }
            ),
            "is not a file of the package",
        ),
        (
            _l1_target(
                source={
                    "kind": "package_file",
                    "file": "study/output/shipped.csv",
                    "locator": {"row": {"term": "zzz"}, "column": "estimate"},
                }
            ),
            "matches 0 rows",
        ),
        (_l2_target(kind="package_file"), "source.kind is 'paper'"),
        (_l2_target(page=None), "source.page must be the page number"),
        (_l2_target(table=None), "name the table or figure"),
        (_l2_target(decimals=4), "has 3 decimals, source.decimals says 4"),
        (_l2_target(decimals=None), "printed precision"),
        (_l2_target(page=1), "is not printed on page 1"),
        (_l2_target(document="shipped_results.csv"), "must be the paper's PDF"),
        ({**_l2_target(), "value": None}, "belongs in missing_targets"),
    ],
)
def test_each_level_has_its_own_source_rules(workspace: Path, target, match):
    _supply_paper(workspace)
    _fetched(workspace)
    errs = _level_errs(workspace, target)
    assert any(match in e for e in errs), errs


def test_a_level_2_target_needs_the_paper(workspace: Path):
    _fetched(workspace)  # no paper supplied
    errs = _level_errs(workspace, _l2_target())
    assert any("does not exist (the researcher supplies the paper as paper/paper.pdf)" in e for e in errs), errs
    # without it, level 1 still works on its own
    assert _level_errs(workspace, _l1_target()) == []


def test_the_plan_schema_encodes_the_level_rules():
    schema = json.loads((ROOT / "docs" / "schemas" / "replication_plan.schema.json").read_text())
    v = jsonschema.validators.validator_for(schema)(schema)
    v.validate(_plan())
    bad = _plan()
    bad["targets"][1]["source"] = {
        "kind": "paper",
        "document": "paper/paper.pdf",
        "page": 1,
        "decimals": 3,
        "table": "T1",
    }
    with pytest.raises(jsonschema.ValidationError):
        v.validate(bad)
    bad = _plan()
    bad["targets"][0]["source"].pop("decimals")
    with pytest.raises(jsonschema.ValidationError):
        v.validate(bad)


def test_a_report_with_levels_separately_passes_and_counts_each_level(workspace: Path):
    _ran(workspace)
    _write(workspace, _report())
    assert check_reproduction(workspace).passed
    stats = json.loads((workspace / CHECK_FILE).read_text())["stats"]
    assert stats["level_1"] == {"targets": 1, "numbers_checked": 1, "results": {"reproduced_minor": 1}}
    assert stats["level_2"]["numbers_checked"] == 1


def test_the_comparer_contract_needs_the_target_level(tmp_path: Path):
    (tmp_path / "reproduction_report.json").write_text(
        json.dumps({"results": [{"level": "reproduced", "reason": "r"}]})
    )
    assert "target_level" in check_report(tmp_path)[0]


# ── the researcher-supplied paper ───────────────────────────────────────────


def test_the_paper_is_staged_fingerprinted_and_its_text_extracted(workspace: Path):
    src = _supply_paper(workspace)
    blob = _zip_bytes(PACKAGE)
    r = repl.fetch_package(workspace, client=_client(_record({"pkg.zip": blob}), {"pkg.zip": blob}))
    assert r.passed and len(r.inputs) == 1
    rec = r.inputs[0]
    assert rec["supplied_by"] == "researcher" and rec["file"] == "paper/paper.pdf"
    assert rec["sha256"] == hashlib.sha256(PAPER).hexdigest() and rec["pages"] == 2
    assert rec["original_path"] == str(src)
    manifest = json.loads((workspace / "package_manifest.json").read_text())
    assert manifest["paper"]["sha256"] == rec["sha256"] and "new" not in manifest["paper"]
    text = (workspace / "paper_text" / "paper.pdf.txt").read_text()
    assert "=== page 2 ===" in text and "-0.012" in text.split("=== page 2 ===")[1]
    assert (workspace / "paper" / "paper.pdf").read_bytes() == PAPER
    # the paper is researcher input, never part of the package
    assert not any("paper.pdf" in f["path"] for f in manifest["package_files"])
    # on the next start: re-verified, not recorded again
    again = repl.fetch_package(workspace)
    assert again.passed and again.inputs == () and again.stats["paper_pages"] == 2


def test_a_replaced_paper_is_recorded_again_with_what_it_replaces(workspace: Path):
    _supply_paper(workspace)
    first = repl.fetch_package(workspace, client=_client(*_pkg()))
    _supply_paper(workspace, _pdf(["v2", "Table 1: ATT -0.012"]))
    second = repl.fetch_package(workspace)
    assert second.inputs[0]["replaces_sha256"] == first.inputs[0]["sha256"]


def _pkg() -> tuple[dict, dict]:
    blob = _zip_bytes(PACKAGE)
    return _record({"pkg.zip": blob}), {"pkg.zip": blob}


def test_the_paper_can_come_from_the_paper_pdf_setting(workspace: Path, tmp_path: Path, monkeypatch):
    from src.config import get_settings

    elsewhere = tmp_path / "downloads" / "paper.pdf"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(PAPER)
    monkeypatch.setattr(get_settings(), "paper_pdf", str(elsewhere))
    r = repl.fetch_package(workspace, client=_client(*_pkg()))
    assert r.passed and r.inputs[0]["original_path"] == str(elsewhere)


def test_something_that_is_not_a_pdf_is_refused(workspace: Path):
    (workspace / "data").mkdir()
    (workspace / "data" / "paper.pdf").write_text("<html>403 Forbidden</html>")
    r = repl.fetch_package(workspace, client=_client(*_pkg()))
    assert not r.passed and "is not a PDF" in r.reasons[0]


def test_without_a_paper_the_step_passes_and_says_so(workspace: Path):
    r = repl.fetch_package(workspace, client=_client(*_pkg()))
    assert r.passed and r.inputs == () and any("no paper supplied" in n for n in r.notes)


async def test_the_supplied_paper_reaches_the_dossier(workspace: Path, events, tmp_path: Path):
    import sqlite3

    from src.core.dossier import recorded_workflow

    _supply_paper(workspace)
    _fetched(workspace)  # fetched with the paper; manifest records it
    (workspace / "paper" / "paper.pdf").chmod(0o644)
    _supply_paper(workspace, _pdf(["v2", "Table 1: ATT -0.012"]))
    r = _runner(workspace)
    await r._run_check_step(r._spec.step("fetch"), r._state)
    supplied = [p for k, _s, p in events if k == "researcher_input"]
    assert len(supplied) == 1 and supplied[0]["supplied_by"] == "researcher"

    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT);"
        "CREATE TABLE contributions (id TEXT, paper_id TEXT, specialist TEXT, stage TEXT, output_file TEXT,"
        " success INT, error_msg TEXT, usage_tokens INT, cost_usd REAL, duration_sec REAL, created_at TEXT);"
        "CREATE TABLE llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT,"
        " cost_usd REAL, created_at TEXT);"
    )
    con.execute(
        "INSERT INTO pipeline_events VALUES ('1', ?, 'researcher_input', 'fetch', NULL, ?, '2026-09-28 16:00:00')",
        (PID, json.dumps(supplied[0])),
    )
    con.commit()
    con.close()
    step = recorded_workflow(db, PID)[0]
    assert step["type"] == "researcher" and step["action"] == "supplied_input"
    assert step["file"] == "paper/paper.pdf" and step["sha256"] == supplied[0]["sha256"]
    assert step["replaces_sha256"]


async def test_a_send_back_first_refreshes_the_fetch_so_the_planner_sees_the_paper(
    workspace: Path, events, monkeypatch
):
    _fetched(workspace)  # no paper yet
    r = _runner(workspace)
    r._state.pending_review_stage = "review_plan"
    r._state.metadata["rerun"] = [{"target": "replication_planner", "remark": "use the paper"}]
    _supply_paper(workspace)
    order: list[str] = []

    async def _exec(orders):
        order.append("planner:" + str((workspace / "paper_text" / "paper.pdf.txt").is_file()))
        return []

    monkeypatch.setattr(r, "_execute_orders", _exec)
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.save", lambda self, ws: None)
    with pytest.raises(HumanReviewRequestedError):  # stops again at the pending review
        await r._settle_researcher_decisions(r._state)
    assert order == ["planner:True"]
    assert [k for k, _s, _p in events][:2] == ["researcher_input", "gate_enforced"]


# ── packages as of the package date ─────────────────────────────────────────


def _rplan(**env: Any) -> dict:
    return _plan(
        environment={
            "image": "rocker/r-ver:4.6.1",
            "packages": [{"name": "did", "version": "2.5.1"}, {"name": "here"}],
            **env,
        }
    )


def test_r_packages_come_from_the_dated_p3m_snapshot_and_declared_versions_win():
    script = install_script(_rplan(), "2026-08-30")
    # the image's own p3m URL with /latest replaced by the date, written to Rprofile.site for the run too
    assert 'sub(pat, "/2026-08-30", r)' in script and '"https://p3m.dev/cran/2026-08-30"' in script
    assert 'file.path(R.home("etc"), "Rprofile.site"), append = TRUE' in script
    assert script.index("Rprofile.site") < script.index("install.packages(pk")
    assert 'want <- c("did" = "2.5.1")' in script and "remotes::install_version" in script
    latest = install_script(_rplan(), None)
    assert "Rprofile.site" not in latest and "E2ER-SNAPSHOT-URL" not in latest
    assert env_tag(_rplan(), "2026-08-30") != env_tag(_rplan(), None) != env_tag(_rplan(), "2025-01-01")


def test_python_packages_are_those_uploaded_before_the_date():
    plan = _plan(
        language="Python",
        environment={
            "image": "python:3.12-slim",
            "packages": [{"name": "pandas", "version": "2.2.2"}, {"name": "six"}],
        },
    )
    script = install_script(plan, "2026-08-30")
    assert "pip install --no-cache-dir --uploaded-prior-to 2026-08-30T23:59:59Z pandas==2.2.2 six" in script
    assert 'pip install --no-cache-dir --upgrade "pip>=26"' in script
    assert "--uploaded-prior-to" not in install_script(plan, None)


@pytest.mark.parametrize(
    ("setting", "manifest", "date"),
    [
        ("package-date", {"publication_date": "2026-08-30"}, "2026-08-30"),
        ("latest", {"publication_date": "2026-08-30"}, None),
        ("2025-01-15", {}, "2025-01-15"),
    ],
)
def test_the_snapshot_setting_resolves(setting, manifest, date):
    assert resolve_snapshot(setting, manifest)[0] == date


def test_package_date_without_a_publication_date_is_refused():
    with pytest.raises(ValueError, match="no publication date"):
        resolve_snapshot("package-date", {})


@pytest.mark.parametrize("bad", ["yesterday", "2026-8-30", 5])
def test_the_snapshot_setting_is_validated_at_load(bad):
    with pytest.raises(PipelineError, match="snapshot"):
        spec_from_dict(
            {"name": "t", "steps": [{"kind": "gate", "name": "g", "check": "sandbox", "settings": {"snapshot": bad}}]}
        )


def test_the_template_installs_as_of_the_package_date():
    assert find_spec("replication").step("sandbox_run").settings["snapshot"] == "package-date"


def test_the_sandbox_log_records_snapshot_platform_all_versions_and_declared_pins(workspace: Path):
    plan = _plan()
    plan["environment"]["packages"] = [{"name": "fixest", "version": "0.12.1"}, {"name": "did", "version": "2.5.1"}]
    _ready(workspace, plan)
    fake = FakeDocker(workspace)
    assert run_sandbox(workspace, runner=fake, docker="docker").passed
    log = json.loads((workspace / LOG_FILE).read_text())
    assert log["snapshot"]["date"] == "2026-08-30" and log["snapshot"]["setting"] == "package-date"
    assert log["snapshot"]["url"] == "https://p3m.dev/cran/__linux__/noble/2026-08-30"
    assert "publication date" in log["snapshot"]["basis"]
    assert log["install"]["installed"]["DRDID"] == "1.3.0"  # a dependency nobody declared, recorded
    assert log["install"]["platform"] == "aarch64-unknown-linux-gnu"
    assert {d["name"]: d["matches"] for d in log["declared_versions"]} == {"fixest": True, "did": False}
    install = next(c for c in fake.calls if c[1] == "run" and "--rm" not in c)
    assert "2026-08-30" in install[-1]
    # a reused environment is still probed, so the versions are always recorded
    assert run_sandbox(workspace, runner=fake, docker="docker").passed
    again = json.loads((workspace / LOG_FILE).read_text())
    assert "reused" in again["install"] and again["install"]["installed"]["DRDID"] == "1.3.0"


# ── strict labels and honest reasons ────────────────────────────────────────


def test_labels_follow_the_protocol_thresholds():
    assert equal_to_target(-0.00364909844619658 * (1 + 5e-10), -0.00364909844619658, 1, 17)
    assert not equal_to_target(-0.00365238597730994, -0.00364909844619658, 1, 17)  # 0.09 %: not reproduced
    assert equal_to_target(-0.01214, -0.012, 2, 3) and not equal_to_target(-0.0126, -0.012, 2, 3)
    assert label_for(True, 0.0, False, 0.10) == "reproduced"
    assert label_for(False, 0.0009, False, 0.10) == "reproduced_minor"
    assert label_for(False, 0.10, False, 0.10) == "reproduced_minor"
    assert label_for(False, 0.1043, False, 0.10) == "not_reproduced"
    assert label_for(False, 0.05, True, 0.10) == "not_reproduced"


def test_the_protocol_states_the_thresholds_the_check_enforces():
    text = (ROOT / "skills/files/replication/reproduction-protocol.md").read_text()
    assert "1e-9" in text and "10 %" in text and "minor_rel_tolerance" in text
    assert find_spec("replication").step("reproduction_gate").settings["minor_rel_tolerance"] == 0.10


def test_the_case_that_stopped_the_first_run_is_caught(workspace: Path):
    """A 0.09 % level-1 difference labelled 'reproduced', with 'equals at full precision' in its reason."""
    _ran(workspace)
    (workspace / "sandbox/run/study/output/shipped.csv").write_text("term,estimate\natt,-0.0120108\n")
    l1 = _l1(level="reproduced", reproduced=-0.0120108)
    l1["reason"] = "ATT equals at full precision; SE differs by 0.09%."
    _write(workspace, _report(l1=l1))
    r = check_reproduction(workspace)
    assert not r.passed
    assert any("labelled 'reproduced', but the numbers make it 'reproduced_minor'" in x for x in r.reasons)
    assert any("the reason says 'equals'" in x for x in r.reasons)


def test_a_result_takes_its_worst_numbers_label(workspace: Path):
    _ran(workspace)
    rep = _report()
    both = rep["results"][1]
    both["level"] = "reproduced_minor"
    _write(workspace, rep)
    assert check_reproduction(workspace).passed
    both["level"] = "reproduced"
    _write(workspace, rep)
    r = check_reproduction(workspace)
    assert any("its worst number makes it 'reproduced_minor'" in x for x in r.reasons)


@pytest.mark.parametrize(
    ("text", "flags", "problem"),
    [
        ("ATT equals at full precision.", [False], "no compared number equals"),
        ("The rerun is identical to the shipped value.", [False], "no compared number equals"),
        ("The ATT does not equal the shipped value; it differs by 0.09%.", [False], None),
        ("All values equal the shipped file.", [True], None),
        ("The SE differs by 6.8%.", [True], "every compared number equals"),
        ("The sign flips due to DRDID 1.3.0.", [False], "states a cause as established"),
        ("The SE differs because 07_did.R sets no seed.", [False], "states a cause as established"),
        ("A bug in the authors' code.", [False], "states a cause as established"),
        ("Possible causes: DRDID is not pinned; 07_did.R sets no seed before its bootstrap.", [False], None),
        ("The difference may be due to the unpinned DRDID.", [False], None),
        ("Within the 10% tolerance; no sign change.", [False], None),
    ],
)
def test_reason_texts_may_not_contradict_the_numbers_or_assert_causes(text, flags, problem):
    found = reason_text_problems(text, flags)
    if problem is None:
        assert found == []
    else:
        assert any(problem in f for f in found), found


def test_the_report_must_carry_the_sandbox_environment(workspace: Path):
    _ran(workspace)
    # a partial list is fine: the versions the report names must be the log's
    rep = {**_report(), "environment": {**_env(workspace), "installed": {"DRDID": "1.3.0"}}}
    _write(workspace, rep)
    assert check_reproduction(workspace).passed
    full = json.loads((workspace / CHECK_FILE).read_text())["environment"]
    assert full["installed"] == {"fixest": "0.12.1", "DRDID": "1.3.0"} and full["snapshot"]["date"] == "2026-08-30"
    rep = {**_report(), "environment": {**_env(workspace), "installed": {"fixest": "0.12.1", "DRDID": "1.2.0"}}}
    _write(workspace, rep)
    r = check_reproduction(workspace)
    assert any("environment.installed differs from sandbox_log.json for 1 package(s): DRDID" in x for x in r.reasons)
    rep["environment"]["installed"] = {"lme4": "1.1"}
    _write(workspace, rep)
    assert any("did not install: lme4" in x for x in check_reproduction(workspace).reasons)
    rep["environment"] = {**_env(workspace), "snapshot": {"date": None, "url": "latest"}}
    _write(workspace, rep)
    assert any("environment.snapshot.date" in x for x in check_reproduction(workspace).reasons)
    bare = _report()
    (workspace / "reproduction_report.json").write_text(json.dumps(bare))
    assert any("no environment block" in x for x in check_reproduction(workspace).reasons)


def test_the_comparer_contract_catches_labels_causes_and_environment(workspace: Path):
    _ran(workspace)
    rep = _report()
    rep["results"][0]["reason"] = "Differs due to DRDID."
    del rep["results"][1]["comparisons"][0]["label"]
    (workspace / "reproduction_report.json").write_text(json.dumps(rep))
    errs = check_report(workspace)
    assert any("states a cause as established" in e for e in errs)
    assert any("label must be one of" in e for e in errs)
    assert any("no environment block" in e for e in errs)
