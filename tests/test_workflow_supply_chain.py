"""The workflows' supply chain (security review 2026-10-23): least permissions, actions pinned to
commit SHAs, installs from hash-pinned files. docs/RELEASING.md section 5 says how to refresh them."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
CI_REQUIREMENTS = ROOT / ".github" / "requirements" / "ci.txt"
BUILD_REQUIREMENTS = ROOT / ".github" / "requirements" / "build.txt"
#: Jobs that may write, and what.
WRITERS = {
    ("release.yml", "release"): {"contents": "write"},
    ("release.yml", "zenodo-doi"): {"contents": "write"},
    ("release.yml", "publish"): {"id-token": "write"},
    ("schema-drift.yml", "drift-check"): {"contents": "read", "issues": "write"},
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_there_are_workflows():
    assert {p.name for p in WORKFLOWS} >= {"tests.yml", "release.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_top_level_permissions_are_read_only(path):
    assert _load(path).get("permissions") == {"contents": "read"}, path.name


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_only_the_named_jobs_write(path):
    for name, job in _load(path)["jobs"].items():
        perms = job.get("permissions")
        expected = WRITERS.get((path.name, name))
        if expected is None:
            assert perms is None or all(v in ("read", "none") for v in perms.values()), (path.name, name, perms)
        else:
            assert perms == expected, (path.name, name, perms)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.search(r"uses:\s*(\S+)", line)
        if not m or m.group(1).startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)), line
        assert re.search(r"#\s*v\d+\.\d+\.\d+", line), f"no version comment: {line}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_checkouts_keep_no_credentials(path):
    for job in _load(path)["jobs"].values():
        for step in job.get("steps") or []:
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert (step.get("with") or {}).get("persist-credentials") is False, path.name


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_installs_use_the_hashed_files(path):
    for job in _load(path)["jobs"].values():
        for step in job.get("steps") or []:
            run = str(step.get("run") or "")
            for cmd in re.findall(r"pip install[^\n]*", run):
                ok = (
                    "--require-hashes -r .github/requirements/ci.txt" in cmd
                    or "--require-hashes -r .github/requirements/build.txt" in cmd
                    or "--no-deps --no-build-isolation -e ." in cmd
                )
                assert ok, (path.name, cmd)
            if re.search(r"python -m build\b", run):
                assert "--no-isolation" in run, (path.name, run)
    assert "cache: pip" not in (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


@pytest.mark.parametrize("req", [CI_REQUIREMENTS, BUILD_REQUIREMENTS], ids=lambda p: p.name)
def test_every_pinned_package_carries_a_hash(req):
    text = req.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=[A-Za-z0-9])", text.split("\n", 2)[2] if text.startswith("#") else text)
    pins = [b for b in blocks if re.match(r"[A-Za-z0-9][\w.\-\[\]]*==", b)]
    assert pins
    for b in pins:
        assert "--hash=sha256:" in b, b.splitlines()[0]


def test_the_ci_file_covers_the_dev_extra_and_the_build_tools():
    names = {
        m.lower() for m in re.findall(r"^([A-Za-z0-9][\w.\-]*)==", CI_REQUIREMENTS.read_text(encoding="utf-8"), re.M)
    }
    assert {"pytest", "ruff", "mypy", "build", "setuptools", "fastapi"} <= names
