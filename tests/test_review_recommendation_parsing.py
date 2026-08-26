"""Reviewer recommendations must come from the stated line (canary #5, 2026-08-26).

All six reviewers wrote `RECOMMENDATION: Major Revision`. The parser recorded
five of them as something else, because it substring-searched the whole review
body and took the first hit: `accept` matched inside "unacceptable", `reject`
inside "rejected". The prompt calls that closing line "parser-enforced"; the
parser never looked at it.

The prose fragments below are copied from the real review files of paper
ad29d86e-bba5-4ee0-a78f-d49598d783d9.
"""

from __future__ import annotations

import pytest

from src.core.strategist.review_aggregator import parse_recommendation, parse_review_output

# (reviewer, prose that hijacked the old parser) — verbatim from canary #5.
CANARY5_REVIEWS = [
    ("data_reviewer", 'The null hypothesis of "no change" has already been rejected for volatility levels.'),
    ("identification_reviewer", "Ethereum also applied for spot ETF approval (rejected in January 2024)."),
    ("literature_reviewer", 'Contains placeholder text ("results are pending"), which is unacceptable.'),
    ("mechanism_reviewer", "While this might be acceptable in a working paper, a complete manuscript needs more."),
    ("writing_reviewer", "- **Acceptable**: The agent (the parameter) is the grammatical subject."),
    ("technical_reviewer", "Ambiguities must be resolved before publication."),
]


def _review(prose: str, stated: str = "Major Revision", score: str = "5.5") -> str:
    return f"# Review\n\n{prose}\n\nOVERALL SCORE: {score}/10\nRECOMMENDATION: {stated}\n"


@pytest.mark.parametrize(("reviewer", "prose"), CANARY5_REVIEWS)
def test_canary5_reviews_all_parse_as_major_revision(reviewer, prose):
    """Every one of these stated Major Revision. Five used to parse otherwise."""
    assert parse_recommendation(_review(prose)) == "major_revision"


@pytest.mark.parametrize(("reviewer", "prose"), CANARY5_REVIEWS)
def test_the_score_object_carries_the_stated_recommendation(reviewer, prose):
    score = parse_review_output(reviewer, _review(prose))
    assert score is not None
    assert score.recommendation == "major_revision"


def test_unacceptable_does_not_read_as_accept():
    """The single most damaging substring: three of five errors came from it."""
    assert parse_recommendation("This is unacceptable.\n\nRECOMMENDATION: Reject\n") == "reject"


def test_rejected_does_not_read_as_reject():
    assert parse_recommendation("The ETF was rejected in 2024.\n\nRECOMMENDATION: Accept\n") == "accept"


@pytest.mark.parametrize(
    "stated",
    ["Accept", "Minor Revision", "Major Revision", "Reject", "minor-revision", "major_revision", "REJECT"],
)
def test_every_permitted_value_round_trips(stated):
    expected = stated.strip().lower().replace(" ", "_").replace("-", "_")
    assert parse_recommendation(_review("Prose.", stated=stated)) == expected


@pytest.mark.parametrize(
    "line",
    [
        "RECOMMENDATION: Reject",
        "**RECOMMENDATION:** Reject",
        "**RECOMMENDATION**: Reject",
        "## RECOMMENDATION: Reject",
        "RECOMMENDATION - Reject",
        "recommendation: reject",
    ],
)
def test_markdown_around_the_label_is_tolerated(line):
    """Reviewers bold and head this line in practice; the value is what matters."""
    assert parse_recommendation(f"Prose.\n\n{line}\n") == "reject"


def test_the_last_stated_line_wins():
    """A review that discusses its recommendation before stating it must not be
    scored on the discussion."""
    text = "RECOMMENDATION: Accept would be premature.\n\nRECOMMENDATION: Major Revision\n"
    assert parse_recommendation(text) == "major_revision"


def test_a_review_with_no_closing_line_falls_back_to_word_boundaries():
    """Older reviews and salvaged transcripts may lack the line entirely."""
    assert parse_recommendation("I recommend that the editor reject this paper.") == "reject"


def test_the_fallback_still_refuses_substring_matches():
    """No closing line AND no bare keyword — 'unacceptable' must not become an
    accept. Defaults to the neutral verdict instead."""
    text = "The framing is unacceptable and the results are rejected out of hand."
    assert parse_recommendation(text) == "major_revision"


def test_nothing_parseable_defaults_to_major_revision():
    """Never `accept` on a parse miss — a parse failure must not wave a paper
    through."""
    assert parse_recommendation("No verdict stated anywhere in this text.") == "major_revision"
