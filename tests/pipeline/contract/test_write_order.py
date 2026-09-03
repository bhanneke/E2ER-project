"""The narrative artifact is written BEFORE the analysis script.

The 2026-08-12 canary (docs/USER_JOURNEY.md) failed twice at the same
place: `econometrics_specialist` wrote `run_estimation.py`,
`summary_statistics.json`, `figure_spec.json` and `robustness_results.json`
but never wrote `econometric_spec.md`, its declared artifact. One attempt was
cut off at the 1800s cap; the other finished on its own in 24 minutes, inside
the cap, and still didn't write it. So it is not a budget problem.

Two prompt defects explain it. The system prompt told every specialist "One
specialist = one artifact" and "produce exactly one final write_file at the
end" — false for a specialist whose work order carries sidecars and a script,
and it pushes the one narrative write to the very end of a turn budget that
gets consumed by debugging. And nothing said which file to write first.

These tests pin the ordering signal and the corrected discipline text. Model
behaviour is exercised by live runs, not here.
"""

from __future__ import annotations

import re
import uuid

from src.core.specialists.base import (
    _SCRIPT_WRITING_SPECIALISTS,
    _build_system_prompt,
    _build_user_prompt,
)
from src.core.specialists.contracts import WorkOrder
from src.core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SIDECAR_ARTIFACTS


def _system(specialist: str, **kw) -> str:
    return _build_system_prompt(specialist, skills_text="", **kw)


def _user(specialist: str, sidecars: list[str]) -> str:
    return _build_user_prompt(
        WorkOrder(
            paper_id=str(uuid.uuid4()),
            specialist=specialist,
            focus="test focus",
            output_file=SPECIALIST_ARTIFACTS[specialist],
            sidecar_artifacts=sidecars,
        )
    )


# ── the ordering signal ──────────────────────────────────────────────────────


def test_script_writers_are_told_to_write_the_artifact_before_the_script():
    for specialist in _SCRIPT_WRITING_SPECIALISTS:
        prompt = _system(specialist)
        assert "Write Order" in prompt, f"{specialist} has no write-order block"
        assert "BEFORE you write or run any script" in prompt


def test_the_write_order_block_names_the_actual_artifact():
    """A generic 'write your artifact first' is too vague to act on — the
    block must name the file the contract gate looks for."""
    for specialist in _SCRIPT_WRITING_SPECIALISTS:
        artifact = SPECIALIST_ARTIFACTS[specialist]
        block = _system(specialist).split("## Write Order", 1)[1]
        assert artifact in block, f"write-order block for {specialist} must name {artifact}"


def test_write_order_block_precedes_the_run_your_script_block():
    """Order on the page is the instruction: design first, then the loop."""
    prompt = _system("econometrics_specialist")
    assert prompt.index("## Write Order") < prompt.index("## RUN YOUR SCRIPT")


def test_non_script_specialists_get_no_write_order_block():
    for specialist in ("paper_drafter", "idea_developer", "technical_reviewer"):
        assert "Write Order" not in _system(specialist)


def test_script_writers_early_write_deadline_is_before_the_debugging_loop():
    """Mid-budget is too late for a specialist that spends its budget in
    write -> run -> fix: by turn 40 of 80 it is deep in debugging."""
    for specialist in _SCRIPT_WRITING_SPECIALISTS:
        m = re.search(r"within turn (\d+)", _system(specialist, max_turns=80))
        assert m, f"{specialist} prompt lost its early-write deadline"
        assert int(m.group(1)) <= 80 // 4, (
            f"{specialist} early-write deadline {m.group(1)} leaves the narrative "
            "artifact until after the debugging loop has started"
        )


# ── output discipline must match the work order ──────────────────────────────


def test_multi_artifact_specialists_are_not_told_one_artifact():
    """`econometrics_specialist` writes a spec, a results JSON and a script.
    Telling it 'One specialist = one artifact' contradicts its work order."""
    for specialist, sidecars in SPECIALIST_SIDECAR_ARTIFACTS.items():
        prompt = _system(specialist, sidecars=sidecars)
        assert "One specialist = one artifact" not in prompt
        assert "exactly one final write_file" not in prompt
        assert "ALL of them are required" in prompt


def test_single_artifact_specialists_keep_the_one_file_rule():
    """The rule is right for writers, reviewers and polish — don't lose it."""
    prompt = _system("technical_reviewer")
    assert "One specialist = one artifact" in prompt
    assert "ONE output file" in prompt


def test_system_prompt_sidecar_branch_is_driven_by_the_work_order():
    """Same specialist, no sidecars in the work order -> single-file rule."""
    assert "One specialist = one artifact" in _system("econometrics_specialist", sidecars=[])


# ── the work order repeats the ordering rule ─────────────────────────────────


def test_multi_file_work_order_puts_the_narrative_file_first():
    prompt = _user("econometrics_specialist", ["estimation_results.json"])
    assert "Write `./econometric_spec.md` FIRST" in prompt
    assert "before you write or run any script" in prompt
