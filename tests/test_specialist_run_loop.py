"""The write→run→fix loop (ROBUSTNESS_REVIEW.md, recommendation 4).

E2ER v1 gave the estimation and analysis stages `Bash(python3:*)`, so a
specialist ran its own script, read the traceback, and fixed it inside one
session. v3 removed code execution entirely and had the orchestrator run the
script afterwards, which is better for provenance and much worse for
reliability: the model writes blind and one crash costs a whole dispatch.

These tests pin the compromise: script-writing specialists get a GUARDED
runner (`e2er-run`), not arbitrary shell, and everyone else gets nothing new.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.core.specialists.base import _SCRIPT_WRITING_SPECIALISTS, _build_system_prompt
from src.core.specialists.post_execution import EXECUTION_CONVENTIONS
from src.modules.llm.claude_code import _DEFAULT_ALLOWED_TOOLS, allowed_tools_for

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "e2er-run"


# ── who gets the runner ──────────────────────────────────────────────────────


def test_script_writers_get_the_runner():
    for specialist in _SCRIPT_WRITING_SPECIALISTS:
        assert "Bash(e2er-run:*)" in allowed_tools_for(specialist)


@pytest.mark.parametrize("specialist", ["paper_drafter", "section_writer", "referee_1", None])
def test_everyone_else_gets_the_default_set(specialist):
    assert allowed_tools_for(specialist) == _DEFAULT_ALLOWED_TOOLS


def test_no_raw_bash_anywhere():
    """The whole point of a wrapper is that `Bash(python3:*)` never appears —
    v1 was contained by Docker and an egress firewall; v3 is not."""
    for specialist in list(_SCRIPT_WRITING_SPECIALISTS) + ["paper_drafter", None]:
        tools = allowed_tools_for(specialist)
        assert "Bash" not in tools
        assert not any(t.startswith("Bash(python") or t.startswith("Bash(bash") for t in tools)


def test_runner_set_matches_the_execution_conventions():
    """A specialist that writes a script must be able to run it, and a
    specialist that cannot write one has no use for the runner."""
    assert _SCRIPT_WRITING_SPECIALISTS == frozenset(EXECUTION_CONVENTIONS)


def test_script_writers_are_told_to_run_it():
    prompt = _build_system_prompt("econometrics_specialist", skills_text="")
    assert "e2er-run" in prompt
    assert "tz-aware" in prompt  # the crash that motivated this


def test_other_specialists_are_not():
    assert "e2er-run" not in _build_system_prompt("paper_drafter", skills_text="")


# ── the wrapper's guards ─────────────────────────────────────────────────────


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(WRAPPER), *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=False)


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "ok.py").write_text("print('ran')\n")
    (tmp_path / "bad.py").write_text("raise ValueError('boom')\n")
    (tmp_path / "notpy.txt").write_text("x\n")
    return tmp_path


def test_runs_a_script_and_returns_its_output(sandbox: Path):
    r = _run(sandbox, "ok.py")
    assert r.returncode == 0
    assert "ran" in r.stdout


def test_surfaces_the_traceback_so_the_model_can_fix_it(sandbox: Path):
    r = _run(sandbox, "bad.py")
    assert r.returncode == 1
    assert "ValueError: boom" in r.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("/etc/passwd",),  # absolute path
        ("../ok.py",),  # traversal
        ("notpy.txt",),  # not python
        ("missing.py",),  # no such file
        ("ok.py", "--sneaky"),  # arguments could smuggle behaviour
        (),  # nothing at all
    ],
)
def test_guards_reject(sandbox: Path, args):
    assert _run(sandbox, *args).returncode == 2
