"""The release workflow's gates (review 2026-11-22): a tag must be on main, the wheel is
install-tested before anything is uploaded, PyPI's files are compared with dist/ after publishing;
and the schema-drift check does not stay silent while it compares nothing."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import subprocess
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
DRIFT = ROOT / ".github" / "workflows" / "schema-drift.yml"

_spec = importlib.util.spec_from_file_location("release_pypi_check", ROOT / "scripts" / "release_pypi_check.py")
assert _spec and _spec.loader
rpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rpc)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _needs(job: dict) -> set[str]:
    n = job.get("needs") or []
    return {n} if isinstance(n, str) else set(n)


def _upstream(jobs: dict, name: str) -> set[str]:
    seen: set[str] = set()
    todo = list(_needs(jobs[name]))
    while todo:
        j = todo.pop()
        if j not in seen:
            seen.add(j)
            todo += _needs(jobs[j])
    return seen


# ---------- release.yml ----------


def test_the_first_job_refuses_a_tag_that_is_not_on_main():
    job = _load(RELEASE)["jobs"]["version-check"]
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0  # origin/main must be there
    runs = [str(s.get("run") or "") for s in job["steps"]]
    gate = next(i for i, r in enumerate(runs) if "merge-base --is-ancestor" in r)
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" refs/remotes/origin/main' in runs[gate]
    assert "exit 1" in runs[gate]
    assert gate < next(i for i, r in enumerate(runs) if "release.py --check" in r)


def test_every_job_that_writes_or_publishes_waits_for_the_main_check():
    jobs = _load(RELEASE)["jobs"]
    for name in ("release", "zenodo-doi", "publish", "pypi-check"):
        assert "version-check" in _upstream(jobs, name), name


def test_publish_stays_in_the_pypi_environment():
    job = _load(RELEASE)["jobs"]["publish"]
    assert job["environment"]["name"] == "pypi"
    assert job["permissions"] == {"id-token": "write"}


def test_the_released_wheel_is_install_tested_before_any_upload():
    jobs = _load(RELEASE)["jobs"]
    check = jobs["check-wheel"]
    assert _needs(check) == {"build"}
    runs = "\n".join(str(s.get("run") or "") for s in check["steps"])
    assert "scripts/check_wheel.sh" in runs
    downloads = [s for s in check["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact@")]
    assert downloads and downloads[0]["with"]["name"] == "dist"  # the very files the run releases
    assert "check-wheel" in _upstream(jobs, "release")
    assert "check-wheel" in _upstream(jobs, "publish")
    assert "permissions" not in check


def test_pypi_is_compared_with_dist_after_publishing():
    jobs = _load(RELEASE)["jobs"]
    job = jobs["pypi-check"]
    assert _needs(job) == {"publish"}
    assert "permissions" not in job  # the top level's contents: read
    runs = "\n".join(str(s.get("run") or "") for s in job["steps"])
    assert "scripts/release_pypi_check.py dist/" in runs
    assert '--version "$GITHUB_REF_NAME"' in runs


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_run_script_interpolates_an_expression(path):
    """Values reach a script through env:, never as ${{ … }} pasted into the shell code."""
    for name, job in _load(path)["jobs"].items():
        for step in job.get("steps") or []:
            assert "${{" not in str(step.get("run") or ""), (path.name, name, step.get("name"))


# ---------- schema-drift.yml ----------


def _drift_steps() -> list[dict]:
    return _load(DRIFT)["jobs"]["drift-check"]["steps"]


def _unavailable_step() -> dict:
    return next(s for s in _drift_steps() if s.get("if") == "steps.diff.outputs.status == 'unavailable'")


def test_unavailable_specs_are_passed_through_env():
    step = _unavailable_step()
    assert step["env"]["UNAVAILABLE"] == "${{ steps.diff.outputs.unavailable }}"
    assert "$UNAVAILABLE" in step["run"]


def _run_unavailable(tmp_path: Path, nights: int, unavailable: str = "tokens-api (HTTPError)") -> list[int]:
    """Runs the step's script ``nights`` times against a fake `gh` that keeps one issue's body."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'S="$STATE"\n'
        'case "$1 $2" in\n'
        '  "label create") exit 0;;\n'
        '  "issue list") [ -f "$S/open" ] && echo 7; exit 0;;\n'
        '  "issue view") cat "$S/body"; exit 0;;\n'
        '  "issue create"|"issue edit")\n'
        '    echo "$1 $2" >> "$S/calls"\n'
        '    while [ $# -gt 0 ]; do [ "$1" = --body ] && printf "%s" "$2" > "$S/body"; shift; done\n'
        '    touch "$S/open";;\n'
        "esac\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    step = _unavailable_step()
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "STATE": str(tmp_path),
        "UNAVAILABLE": unavailable,
        "RUN_URL": "https://github.com/o/r/actions/runs/1",
        "LIMIT": str(step["env"]["LIMIT"]),
    }
    return [subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True).returncode for _ in range(nights)]


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs bash")
def test_the_run_fails_from_the_limit_th_unavailable_night_on(tmp_path: Path):
    limit = int(_unavailable_step()["env"]["LIMIT"])
    codes = _run_unavailable(tmp_path, limit + 1)
    assert codes == [0] * (limit - 1) + [1, 1]
    assert f"unavailable streak: {limit + 1}" in (tmp_path / "body").read_text(encoding="utf-8")
    calls = (tmp_path / "calls").read_text(encoding="utf-8").split("\n")
    assert calls[0] == "issue create" and set(calls[1:-1]) == {"issue edit"}  # one issue, updated


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs bash")
def test_the_unavailable_text_is_never_run_as_code(tmp_path: Path):
    marker = tmp_path / "pwned"
    _run_unavailable(tmp_path, 1, unavailable=f"x $(touch {marker}) `touch {marker}`")
    assert not marker.exists()


def test_a_night_that_fetches_the_specs_closes_the_unavailable_issue():
    step = next(s for s in _drift_steps() if s.get("name") == "Specs fetched again")
    assert "match" in step["if"] and "drift" in step["if"]
    assert "gh issue close" in step["run"] and "schema-drift-unavailable" in step["run"]


# ---------- scripts/release_pypi_check.py ----------


def _dist(tmp_path: Path, files: dict[str, bytes]) -> Path:
    d = tmp_path / "dist"
    d.mkdir()
    for name, data in files.items():
        (d / name).write_bytes(data)
    return d


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakePyPI:
    """Answers the JSON API with the given files, one answer per call (the last one repeats)."""

    def __init__(self, *answers: dict[str, str] | None):
        self.answers = list(answers)
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        files = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if files is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        return json.dumps(
            {"urls": [{"filename": n, "digests": {"sha256": h, "md5": "x"}} for n, h in files.items()]}
        ).encode()


WHL, SDIST = "e2er-1.2.3-py3-none-any.whl", "e2er-1.2.3.tar.gz"


def test_identical_files_pass(tmp_path: Path):
    d = _dist(tmp_path, {WHL: b"wheel", SDIST: b"sdist", "notes.txt": b"ignored"})
    pypi = FakePyPI({WHL: _sha(b"wheel"), SDIST: _sha(b"sdist")})
    assert rpc.check(d, "1.2.3", fetch=pypi) == []
    assert pypi.urls == ["https://pypi.org/pypi/e2er/1.2.3/json"]


def test_a_rebuilt_wheel_fails_at_once(tmp_path: Path):
    """skip-existing kept the first run's wheel on PyPI; this run's dist/ (on GitHub) differs."""
    d = _dist(tmp_path, {WHL: b"rebuilt", SDIST: b"sdist"})
    slept: list[float] = []
    problems = rpc.check(
        d, "1.2.3", wait=300, fetch=FakePyPI({WHL: _sha(b"first"), SDIST: _sha(b"sdist")}), sleep=slept.append
    )
    assert len(problems) == 1 and problems[0].startswith(WHL) and "PyPI" in problems[0]
    assert slept == []  # PyPI never replaces a file: no point waiting


def test_a_file_only_on_pypi_fails(tmp_path: Path):
    d = _dist(tmp_path, {WHL: b"wheel"})
    problems = rpc.check(d, "1.2.3", fetch=FakePyPI({WHL: _sha(b"wheel"), SDIST: _sha(b"sdist")}))
    assert problems == [f"{SDIST}: on PyPI but not in this run's dist/"]


def test_a_missing_file_is_asked_again_until_it_appears(tmp_path: Path):
    d = _dist(tmp_path, {WHL: b"wheel", SDIST: b"sdist"})
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    pypi = FakePyPI(None, {WHL: _sha(b"wheel")}, {WHL: _sha(b"wheel"), SDIST: _sha(b"sdist")})
    assert rpc.check(d, "1.2.3", wait=60, every=15, fetch=pypi, sleep=sleep, clock=lambda: now[0]) == []
    assert len(pypi.urls) == 3 and now[0] == 30


def test_a_file_that_never_appears_fails_after_the_wait(tmp_path: Path):
    d = _dist(tmp_path, {WHL: b"wheel"})
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    problems = rpc.check(d, "1.2.3", wait=60, every=15, fetch=FakePyPI(None), sleep=sleep, clock=lambda: now[0])
    assert problems == [f"{WHL}: in dist/ but not on PyPI"]
    assert now[0] <= 60


def test_an_empty_dist_fails(tmp_path: Path):
    assert rpc.check(_dist(tmp_path, {}), "1.2.3", fetch=FakePyPI({})) != []


def test_main_takes_the_tag_name_and_refuses_anything_else(tmp_path: Path, monkeypatch, capsys):
    d = _dist(tmp_path, {WHL: b"wheel"})
    monkeypatch.setattr(rpc, "_fetch", FakePyPI({WHL: _sha(b"wheel")}))
    assert rpc.main([str(d), "--version", "v1.2.3", "--wait", "0"]) == 0
    assert re.search(rf"ok  {re.escape(WHL)} [0-9a-f]{{64}}", capsys.readouterr().out)
    assert rpc.main([str(d), "--version", "v1.2.3; rm -rf /", "--wait", "0"]) == 2
