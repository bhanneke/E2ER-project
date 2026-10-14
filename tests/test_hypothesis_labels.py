"""Pre-registered hypotheses keep their labels apart from their statements (2026-10-13 demo).

The school-fee demo's plan declared "- **H1 (average effect)**: Abolition raises
gross primary enrolment"; the machine-readable block read "average effect
Abolition raises gross primary enrolment".
"""

from __future__ import annotations

import pytest

from src.core.pipeline.preregistration import extract_hypotheses


@pytest.mark.parametrize(
    "line",
    [
        "- **H1 (average effect)**: Abolition raises gross primary enrolment.",
        "- **H1 (average effect):** Abolition raises gross primary enrolment.",
        "**H1 — average effect:** Abolition raises gross primary enrolment.",
        "- **H1: average effect:** Abolition raises gross primary enrolment.",
    ],
)
def test_label_and_statement_are_kept_apart(line: str):
    (h,) = extract_hypotheses(line + "\n")
    assert h["id"] == "H1"
    assert h["label"] == "average effect"
    assert h["statement"] == "average effect: Abolition raises gross primary enrolment."


def test_a_heading_without_a_label_is_its_statement():
    (h,) = extract_hypotheses("### H2: Surprise Sensitivity Test\n")
    assert h == {"id": "H2", "statement": "Surprise Sensitivity Test"}


def test_a_plain_statement_has_no_label():
    (h,) = extract_hypotheses("**H3.** Volume rises after a cut.\n")
    assert h == {"id": "H3", "statement": "Volume rises after a cut."}
