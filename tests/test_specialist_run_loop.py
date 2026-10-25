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
from src.modules.llm.claude_code import (
    _DEFAULT_ALLOWED_TOOLS,
    _LITERATURE_SPECIALISTS,
    _SPEC_WRITING_SPECIALISTS,
    allowed_tools_for,
)

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "e2er-run"


# ── who gets the runner ──────────────────────────────────────────────────────


def test_script_writers_get_the_runner():
    for specialist in _SCRIPT_WRITING_SPECIALISTS:
        assert "Bash(e2er-run:*)" in allowed_tools_for(specialist)


def test_spec_writers_get_the_checker():
    """paper_drafter authors table_spec.json and section_writer repairs it.
    Both wrote blind until `e2er-check-tables` — the same gap `e2er-run` closed
    for scripts, one artifact over."""
    for specialist in _SPEC_WRITING_SPECIALISTS:
        assert "Bash(e2er-check-tables:*)" in allowed_tools_for(specialist)


def test_literature_specialists_get_the_literature_bridge():
    """tool_loop ignores `tools`, so LITERATURE_TOOLS are unreachable on CLI
    backends. e2er-lit is the only path to a bibliography there."""
    for specialist in _LITERATURE_SPECIALISTS:
        assert "Bash(e2er-lit:*)" in allowed_tools_for(specialist)


def test_the_planners_can_look_up_sources_for_dates_and_metadata():
    for specialist in ("idea_developer", "identification_strategist", "data_architect"):
        assert "Bash(e2er-lit:*)" in allowed_tools_for(specialist)


def test_specialists_that_neither_find_nor_cite_literature_do_not_get_it():
    for specialist in ("econometrics_specialist", "data_analyst", "referee_1", None):
        assert "Bash(e2er-lit:*)" not in allowed_tools_for(specialist)


def test_the_two_grants_do_not_displace_each_other():
    assert "Bash(e2er-run:*)" in allowed_tools_for("econometrics_specialist")
    assert "Bash(e2er-check-tables:*)" not in allowed_tools_for("econometrics_specialist")
    assert "Bash(e2er-run:*)" not in allowed_tools_for("paper_drafter")


@pytest.mark.parametrize("specialist", ["referee_1", "abstract_writer", "polish_formula", None])
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


# ── one plain command per call (the 2026-10-25 live test) ───────────────────


@pytest.mark.parametrize(
    "specialist",
    sorted(_LITERATURE_SPECIALISTS | _SCRIPT_WRITING_SPECIALISTS | _SPEC_WRITING_SPECIALISTS | {"review_methods"}),
)
def test_every_cli_specialist_is_told_to_run_e2ers_commands_plainly(specialist):
    """The literature scanner wrapped its searches in `( ... 2>&1 | head; ... )`; Claude Code refused the line and
    the scanner wrote its review without a search. Every specialist on a CLI backend gets the rule."""
    prompt = _build_system_prompt(specialist, skills_text="", shell=True)
    assert "one plain command per call" in prompt
    for banned in ("subshell", "pipe `|`", "`&&`", "`2>&1`", "heredoc"):
        assert banned in prompt, banned
    assert "can't be checked before it runs" in prompt and "run the same e2er command again" in prompt
    assert "Read tool" in prompt
    shell = [t for t in allowed_tools_for(specialist) if t.startswith("Bash(") and t != "Bash(e2er-allium-query:*)"]
    granted = [t[5:-3] for t in shell]
    for name in granted:
        assert f"`{name}`" in prompt, name
    if "e2er-lit" not in granted:
        assert "e2er-lit" not in prompt, "no example of a command the specialist cannot run"


def test_the_sdk_backends_get_no_shell_rule():
    assert "one plain command per call" not in _build_system_prompt("literature_scanner", skills_text="")


async def test_run_specialist_passes_the_rule_to_a_cli_backend_only(monkeypatch, tmp_path):
    from src.core.specialists import base

    seen: dict[str, bool] = {}

    def spy(*args, **kwargs):
        seen["shell"] = kwargs.get("shell", False)
        raise RuntimeError("stop here")

    monkeypatch.setattr(base, "_build_system_prompt", spy)
    from src.core.specialists.contracts import WorkOrder

    order = WorkOrder(paper_id="p1", specialist="literature_scanner", focus="f", output_file="literature_review.md")
    for backend, expected in (("claude_code", True), ("codex", True), ("anthropic", False)):
        with pytest.raises(RuntimeError, match="stop here"):
            await base.run_specialist(order, None, tmp_path, "m", backend_name=backend)  # type: ignore[arg-type]
        assert seen["shell"] is expected, backend
