"""Mechanical review aggregation — 3-rule system for publication decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ReviewScore:
    reviewer: str
    score: float  # 1-10
    recommendation: str  # accept, major_revision, minor_revision, reject
    comments: str = ""
    weight: float = 1.0


@dataclass
class AggregationResult:
    verdict: str  # "ACCEPT", "MAJOR_REVISION", "MINOR_REVISION", "MECHANISM_FAIL", "HARD_REJECT"
    weighted_avg: float
    rule_triggered: str  # which rule determined the outcome
    scores: list[ReviewScore]
    rationale: str


_WEIGHTS: dict[str, float] = {
    "mechanism_reviewer": 1.0,
    "technical_reviewer": 1.5,
    "literature_reviewer": 1.0,
    "writing_reviewer": 0.75,
    "data_reviewer": 1.25,
    "identification_reviewer": 1.5,
}

_RECOMMENDATION_FLOOR = {
    "accept": 8.0,
    "minor_revision": 6.5,
    "major_revision": 5.0,
    "reject": 0.0,
}


def aggregate_reviews(scores: list[ReviewScore]) -> AggregationResult:
    """Apply 3-rule mechanical aggregation to produce a final verdict.

    Rule 1: If mechanism_reviewer < 5 → MECHANISM_FAIL (hard gate).
    Rule 2: If any reviewer < 4 → HARD_REJECT.
    Rule 3: Weighted average — technical_reviewer has 1.5x weight.
    """
    for s in scores:
        s.weight = _WEIGHTS.get(s.reviewer, 1.0)

    # Rule 1 — mechanism gate
    mech_scores = [s for s in scores if s.reviewer == "mechanism_reviewer"]
    if mech_scores and mech_scores[0].score < 5:
        return AggregationResult(
            verdict="MECHANISM_FAIL",
            weighted_avg=mech_scores[0].score,
            rule_triggered="Rule 1: mechanism_reviewer < 5",
            scores=scores,
            rationale=(
                f"Mechanism reviewer scored {mech_scores[0].score:.1f}/10. "
                "The paper's core mechanism is not sufficiently convincing. "
                "Fundamental revision required before review can continue."
            ),
        )

    # Rule 2 — any reviewer hard floor
    hard_fail = [s for s in scores if s.score < 4]
    if hard_fail:
        worst = min(hard_fail, key=lambda s: s.score)
        return AggregationResult(
            verdict="HARD_REJECT",
            weighted_avg=worst.score,
            rule_triggered=f"Rule 2: {worst.reviewer} scored {worst.score:.1f} (< 4)",
            scores=scores,
            rationale=(
                f"{worst.reviewer} gave a score of {worst.score:.1f}/10. "
                "A score below 4 from any reviewer triggers immediate rejection. "
                f"Issue: {worst.comments[:200]}"
            ),
        )

    # Rule 3 — weighted average
    total_weight = sum(s.weight for s in scores)
    weighted_avg = sum(s.score * s.weight for s in scores) / total_weight if total_weight > 0 else 0.0

    verdict = _score_to_verdict(weighted_avg)
    return AggregationResult(
        verdict=verdict,
        weighted_avg=weighted_avg,
        rule_triggered="Rule 3: weighted average",
        scores=scores,
        rationale=(
            f"Weighted average score: {weighted_avg:.2f}/10. "
            f"Verdict: {verdict}. "
            f"Breakdown: {', '.join(f'{s.reviewer}={s.score:.1f}' for s in scores)}"
        ),
    )


def _score_to_verdict(avg: float) -> str:
    if avg >= 8.0:
        return "ACCEPT"
    if avg >= 6.5:
        return "MINOR_REVISION"
    if avg >= 5.0:
        return "MAJOR_REVISION"
    return "HARD_REJECT"


def parse_review_output(reviewer: str, raw_output: str) -> ReviewScore | None:
    """Extract structured score from a reviewer's text output."""
    import re

    score_match = re.search(r"(?:score|rating)[:\s]+(\d+(?:\.\d+)?)\s*(?:/\s*10)?", raw_output, re.IGNORECASE)
    rec_match = re.search(
        r"(accept|minor.revision|major.revision|reject)",
        raw_output,
        re.IGNORECASE,
    )

    if not score_match:
        return None

    score = float(score_match.group(1))
    recommendation = rec_match.group(1).lower().replace(" ", "_") if rec_match else "major_revision"

    return ReviewScore(
        reviewer=reviewer,
        score=min(10.0, max(0.0, score)),
        recommendation=recommendation,
        comments=raw_output[:500],
    )
