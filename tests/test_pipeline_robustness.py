"""Robustness regressions from the 2026-05 code review (Lane A)."""

from __future__ import annotations

import json

from src.core.specialists.registry import REVIEWER_SPECIALISTS
from src.core.strategist.context import build_tier0_context
from src.core.strategist.review_aggregator import ReviewScore, aggregate_reviews
from src.core.strategist.runner import _coerce_paper_status
from src.core.strategist.state import PaperStatus


def _score(reviewer: str, score: float) -> ReviewScore:
    return ReviewScore(reviewer=reviewer, score=score, recommendation="accept")


# ── #6: a missing mechanism score must not allow ACCEPT ──────────────────────


def test_missing_mechanism_score_blocks_accept():
    # Every non-mechanism reviewer scores high, but mechanism_reviewer produced
    # no parseable score. Previously this silently accepted on the average;
    # now the mechanism gate's absence forces a revision round.
    scores = [_score(r, 9.0) for r in REVIEWER_SPECIALISTS if r != "mechanism_reviewer"]
    result = aggregate_reviews(scores)
    assert result.verdict == "MAJOR_REVISION"
    assert "mechanism" in result.rule_triggered.lower()


def test_present_mechanism_high_still_accepts():
    scores = [_score(r, 9.0) for r in REVIEWER_SPECIALISTS]
    assert aggregate_reviews(scores).verdict == "ACCEPT"


# ── #7: resume must tolerate a bad/legacy persisted status ───────────────────


def test_coerce_status_valid():
    assert _coerce_paper_status("completed", PaperStatus.IN_PROGRESS) == PaperStatus.COMPLETED


def test_coerce_status_garbage_falls_back():
    assert _coerce_paper_status("not_a_real_status", PaperStatus.COMPLETED) == PaperStatus.COMPLETED


def test_coerce_status_none_falls_back():
    assert _coerce_paper_status(None, PaperStatus.IN_PROGRESS) == PaperStatus.IN_PROGRESS


# ── null-vs-missing trap in the tier-0 context builder ───────────────────────


def test_tier0_context_handles_null_fields(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"title": "T", "datasets": None, "research_question": None}))
    out = build_tier0_context(tmp_path, "p1")  # must not raise on explicit nulls
    assert "Paper: T" in out
