"""Lane A — turn-budget signal in specialist system prompt.

Pins the fix for run #16's failure mode: data_analyst hit max_turns
without writing data_summary.md because the prompt didn't tell it to
write early. The fix is a "Turn Budget" section near the top of the
system prompt that tells the model to write a first version of the
canonical artifact within the first half of its turn budget.

These tests assert the prompt contains the budget signal and the
early-write deadline. The actual model behaviour is exercised by live
runs.
"""

from __future__ import annotations

import re

from src.core.specialists.base import _build_system_prompt


def test_prompt_includes_turn_count():
    """The model must know its turn cap so it can pace tool calls."""
    prompt = _build_system_prompt("data_analyst", skills_text="", has_allium=False, max_turns=80)
    assert "80" in prompt, "system prompt must surface the max_turns budget to the model"
    assert "Turn Budget" in prompt or "turn budget" in prompt.lower()


def test_prompt_includes_early_write_deadline():
    """The model must be told to write the artifact at least by mid-budget.

    The exact figure isn't pinned (it's derived from max_turns), but it
    must appear in a sentence that mentions write_file / canonical
    artifact, otherwise the signal is too vague.
    """
    prompt = _build_system_prompt("data_analyst", skills_text="", has_allium=False, max_turns=80)
    # Find a sentence that mentions writing the artifact within a turn count
    m = re.search(r"within turn (\d+)", prompt, re.IGNORECASE)
    assert m, f"prompt should contain an 'within turn N' early-write deadline; prompt was:\n{prompt[:500]}"
    deadline = int(m.group(1))
    # Deadline should be in the first half of the budget (run #16 hit at 41,
    # so anything > 40 is too late on an 80-turn budget).
    assert deadline <= 80 // 2, (
        f"early-write deadline {deadline} is too far into the budget — needs to be in the first half"
    )


def test_prompt_scales_with_lower_max_turns():
    """If max_turns is small (e.g. 20), the deadline must scale accordingly."""
    prompt = _build_system_prompt("paper_drafter", skills_text="", has_allium=False, max_turns=20)
    assert "20" in prompt
    m = re.search(r"within turn (\d+)", prompt, re.IGNORECASE)
    assert m
    deadline = int(m.group(1))
    assert deadline <= 20, "deadline must not exceed the budget"
    # Minimum deadline is 10 (we don't tell models "write by turn 1")
    assert deadline >= 10 or deadline == 20 // 2


def test_prompt_warns_against_saving_write_for_last_turn():
    """The most common failure mode (run #16) is saving write_file for the end.

    The prompt must explicitly warn against it.
    """
    prompt = _build_system_prompt("data_analyst", skills_text="", has_allium=False, max_turns=80)
    p = prompt.lower()
    assert ("last turn" in p) or ("end of" in p and "write" in p), (
        "prompt should warn against saving write_file for the last turn"
    )
