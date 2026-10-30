"""tests/parts.py: the suite in parts for the release workflow's parallel jobs; every test in exactly one."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.parts import assign, from_junit, load_durations, parse_part

ROOT = Path(__file__).resolve().parents[1]


def test_every_file_is_in_exactly_one_part():
    files = {f"tests/test_{i}.py": (i % 7) + 1 for i in range(50)}
    durations = {f"tests/test_{i}.py": float(i) for i in range(0, 50, 3)}
    parts = assign(files, 4, durations)
    flat = [f for p in parts for f in p]
    assert sorted(flat) == sorted(files) and len(flat) == len(set(flat))


def test_the_parts_are_about_even():
    files = {f"t{i}.py": 1 for i in range(40)}
    durations = {f"t{i}.py": 100.0 if i < 4 else 1.0 for i in range(40)}
    parts = assign(files, 4, durations)
    loads = [sum(durations[f] for f in p) for p in parts]
    assert max(loads) - min(loads) <= 1.0  # one slow file each, the rest spread


def test_the_recorded_durations_name_existing_files():
    durations = load_durations()
    assert durations, "tests/test_durations.json is missing or empty"
    missing = [f for f in durations if not (ROOT / f).is_file()]
    assert len(missing) <= len(durations) // 10, missing  # stale entries are harmless, but not many


@pytest.mark.parametrize("bad", ["", "2", "0/4", "5/4", "a/b"])
def test_parse_part_refuses(bad: str):
    with pytest.raises(ValueError):
        parse_part(bad)


def test_from_junit(tmp_path: Path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite name="pytest">'
        '<testcase classname="tests.test_a" name="t1" time="1.5"/>'
        '<testcase classname="tests.test_a.TestX" name="t2" time="0.5"/>'
        '<testcase classname="tests.pipeline.test_b" name="t3" time="2"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
        newline="\n",
    )
    assert from_junit(xml) == {"tests/pipeline/test_b.py": 2.0, "tests/test_a.py": 2.0}


def _collected(env_part: str | None, files: list[str]) -> set[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("E2ER_TEST_PART", "PYTEST_ADDOPTS")}
    if env_part:
        env["E2ER_TEST_PART"] = env_part
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
        cwd=ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    return {ln for ln in out.splitlines() if "::" in ln}


def test_the_parts_together_are_the_whole_suite():
    files = ["tests/test_release_facts.py", "tests/test_release_script.py", "tests/test_test_parts.py"]
    whole = _collected(None, files)
    parts = [_collected(f"{k}/2", files) for k in (1, 2)]
    assert parts[0] | parts[1] == whole and not parts[0] & parts[1] and all(parts)
