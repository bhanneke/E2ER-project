"""Tests for the mechanical 3-rule review aggregation."""
import pytest

from src.core.strategist.review_aggregator import (
    aggregate_reviews,
    ReviewScore,
)


def _score(reviewer: str, score: float) -> ReviewScore:
    return ReviewScore(reviewer=reviewer, score=score, recommendation="major_revision")


def test_mechanism_fail_triggers_rule1():
    scores = [
        _score("mechanism_reviewer", 4.0),
        _score("technical_reviewer", 8.0),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "MECHANISM_FAIL"
    assert "Rule 1" in result.rule_triggered


def test_hard_reject_triggers_rule2():
    scores = [
        _score("mechanism_reviewer", 6.0),
        _score("technical_reviewer", 3.5),  # below 4
        _score("writing_reviewer", 7.0),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "HARD_REJECT"
    assert "Rule 2" in result.rule_triggered


def test_accept_via_weighted_average():
    scores = [
        _score("mechanism_reviewer", 8.5),
        _score("technical_reviewer", 9.0),
        _score("writing_reviewer", 8.0),
        _score("literature_reviewer", 7.5),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "ACCEPT"
    assert result.weighted_avg >= 8.0


def test_technical_reviewer_has_higher_weight():
    scores = [
        _score("mechanism_reviewer", 6.5),
        _score("technical_reviewer", 8.5),  # 1.5x weight pulls average up
    ]
    result = aggregate_reviews(scores)
    # technical gets 1.5x weight: (6.5*1 + 8.5*1.5) / 2.5 = 7.9
    assert result.weighted_avg > 7.5


def test_major_revision_range():
    scores = [
        _score("mechanism_reviewer", 6.0),
        _score("technical_reviewer", 5.5),
        _score("writing_reviewer", 6.0),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "MAJOR_REVISION"
