"""tests/replay/uv.py: the replay tests' reproduce step is skipped without uv locally and fails on CI."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.replay import uv

ROOT = Path(__file__).resolve().parents[1]


def test_without_uv_skips_locally(monkeypatch):
    monkeypatch.delenv(uv.REQUIRE_ENV, raising=False)
    monkeypatch.setattr(uv.shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception):
        uv.reproduce_env()


def test_without_uv_fails_on_ci(monkeypatch):
    monkeypatch.setenv(uv.REQUIRE_ENV, "1")
    monkeypatch.setattr(uv.shutil, "which", lambda name: None)
    with pytest.raises(pytest.fail.Exception, match="E2ER_REQUIRE_UV"):
        uv.reproduce_env()


def test_on_ci_reproduce_runs_online(monkeypatch):
    monkeypatch.setenv(uv.REQUIRE_ENV, "1")
    monkeypatch.setattr(uv.shutil, "which", lambda name: "/usr/bin/uv")
    assert "UV_OFFLINE" not in uv.reproduce_env()


def test_a_failed_install_skips_locally_and_fails_on_ci(monkeypatch):
    out = "error: could not install the requirements: no network"
    monkeypatch.delenv(uv.REQUIRE_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception):
        uv.check_installed(out)
    monkeypatch.setenv(uv.REQUIRE_ENV, "1")
    with pytest.raises(pytest.fail.Exception):
        uv.check_installed(out)
    uv.check_installed("Reproduced: 3 of 3 steps")  # a run that installed passes through


@pytest.mark.parametrize("workflow", ["tests.yml", "release.yml"])
def test_ci_installs_uv_and_requires_it(workflow: str):
    """Both test jobs install uv (pinned to a commit) and set the flag on the pytest step."""
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    assert re.search(r"uses: astral-sh/setup-uv@[0-9a-f]{40}\s+# v\d", text), workflow
    run_tests = text.split("- name: Run tests", 1)[1].split("- name:", 1)[0]
    assert 'E2ER_REQUIRE_UV: "1"' in run_tests, workflow
    setup = text.index("astral-sh/setup-uv@")
    assert setup < text.index("- name: Run tests"), workflow


def test_every_replay_test_uses_the_helper():
    """No replay test skips the reproduce step on its own (that is what hid it on CI)."""
    seen: list[str] = []
    for p in sorted(ROOT.glob("tests/test_*_replay.py")):
        text = p.read_text(encoding="utf-8")
        if not re.search(r"\buv\b", text):
            continue  # its reproduce step installs nothing
        assert "uv.reproduce_env()" in text and "uv.check_installed(" in text, p.name
        assert 'pytest.skip("uv is not installed' not in text, p.name
        seen.append(p.name)
    assert len(seen) == 4, seen
