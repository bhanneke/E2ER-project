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
from src.core.pipeline.reproduction import CHECK_FILE, check_report, check_reproduction
from src.core.pipeline.sandbox import (
    LOG_FILE,
    Limits,
    env_tag,
    install_argv,
    install_script,
    run_argv,
    run_sandbox,
)
from src.core.pipeline.spec import SCHEMA_PATH, PipelineError, find_spec, spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.specialists.contracts import Contribution
from src.core.strategist.state import GateHaltError
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
}


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
                "exhibit": "table_1",
                "label": "ATT",
                "value": -0.012,
                "reported": "-0.012",
                "source": {"document": "paper.pdf", "page": 12, "table": "Table 1"},
            }
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
        if sub == "run":
            script = argv[-1]
            if script in self.hang:
                raise subprocess.TimeoutExpired(argv, timeout, output=b"partial", stderr=b"")
            if script in self.fail:
                return subprocess.CompletedProcess(argv, 1, b"", b"Error: object 'x' not found")
            out = self.ws / "sandbox" / "run" / "study" / "output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "table1.csv").write_text("term,estimate,se\natt,-0.01214,0.004\n")
            return ok
        raise AssertionError(f"unexpected docker call {argv}")


def _ready(ws: Path, plan: dict | None = None) -> None:
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
    assert log["image_digest"] == "rocker/r-ver@sha256:abc" and log["install"]["installed"] == {"fixest": "0.12.1"}
    written = {o["path"]: o for o in log["outputs"]}
    assert written["study/output/table1.csv"]["state"] == "new"
    assert (
        written["study/output/table1.csv"]["sha256"]
        == hashlib.sha256((workspace / "sandbox/run/study/output/table1.csv").read_bytes()).hexdigest()
    )
    assert "study/output/shipped.csv" not in written  # the package's own result is not an output of the run
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
    assert not any(c[1] == "run" and "--rm" in c for c in fake.calls)


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


def _report(level: str = "reproduced_minor", reproduced: Any = -0.01214, **comp: Any) -> dict:
    c = {
        "target_id": "t1_att",
        "published": -0.012,
        "reproduced": reproduced,
        "abs_diff": None if reproduced is None else round(reproduced + 0.012, 10),
        "source": {"file": "study/output/table1.csv", "locator": {"row": {"term": "att"}, "column": "estimate"}},
    }
    c.update(comp)
    return {"results": [{"id": "table_1", "level": level, "reason": "r", "comparisons": [c]}]}


def _write(ws: Path, report: dict) -> None:
    (ws / "reproduction_report.json").write_text(json.dumps(report))


def test_a_truthful_report_passes_and_every_number_is_recomputed(workspace: Path):
    _ran(workspace)
    _write(workspace, _report())
    r = check_reproduction(workspace)
    assert r.passed, r.reasons
    checked = json.loads((workspace / CHECK_FILE).read_text())["checked"][0]
    assert checked["recomputed"] == -0.01214 and checked["equal_at_published_precision"] is True


def test_equal_at_the_published_precision_may_be_called_reproduced(workspace: Path):
    _ran(workspace)
    _write(workspace, _report(level="reproduced"))
    assert check_reproduction(workspace).passed


@pytest.mark.parametrize(
    ("report", "match"),
    [
        (_report(reproduced=-0.0131), "holds -0.01214, not the claimed -0.0131"),
        (_report(source={"file": "study/output/table1.csv"}, reproduced=-0.5), "no number"),
        (_report(source={"file": "study/output/shipped.csv"}), "not a file the sandbox run wrote"),
        (_report(published=-0.02), "is not the plan's"),
        (_report(target_id="t9"), "not a target"),
        (_report(level="could_not_run"), "could_not_run"),
        (_report(level="reproduced", reproduced=-0.01214, published=-0.012), None),
        (_report(abs_diff=0.5), "abs_diff"),
        ({"results": [], "unassessed": []}, "neither compared nor listed"),
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
    assert not r.passed and "exceeds the minor tolerance" in r.reasons[0]
    _write(workspace, _report(level="not_reproduced", reproduced=-0.015))
    assert check_reproduction(workspace).passed
    _write(workspace, _report(level="reproduced_minor", reproduced=-0.015))
    assert check_reproduction(workspace, minor_rel_tolerance=0.3).passed


def test_an_unassessed_target_with_a_reason_is_accounted_for(workspace: Path):
    _ran(workspace)
    _write(workspace, {"results": [], "unassessed": [{"target_id": "t1_att", "reason": "only in a figure"}]})
    assert check_reproduction(workspace).passed


def test_the_report_schema_accepts_what_the_check_accepts():
    schema = json.loads((ROOT / "docs" / "schemas" / "reproduction_report.schema.json").read_text())
    jsonschema.validators.validator_for(schema)(schema).validate(_report())


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
    assert r._state.is_complete("fetch") and r._state.is_complete("plan") and ran == []
    assert r._state.metadata["review"]["files"] == ["replication_plan.md", "replication_plan.json"]
