"""Mechanical review aggregation — 3-rule system for publication decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReviewScore:
    reviewer: str
    score: float  # 1-10
    recommendation: str  # accept, major_revision, minor_revision, reject
    comments: str = ""
    weight: float = 1.0
    # Where the score was read from: "file" (the reviewer wrote its artifact) or
    # "transcript" (the file was absent and the score was salvaged from the
    # reviewer's reply text). A salvaged score still counts toward the verdict,
    # but it means no review FILE exists — so the deep-revision round has no
    # referee report to work from and the export bundle ships without one.
    # Recording it makes a degraded panel visible in the artifact instead of
    # only in a log line.
    source: str = "file"


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
    from ...logging_config import get_logger
    from ..specialists.registry import REVIEWER_SPECIALISTS

    expected = len(REVIEWER_SPECIALISTS)
    if len(scores) < expected:
        get_logger(__name__).warning(
            "Partial review aggregation: only %d/%d reviewer scores present "
            "(missing: %s). Verdict computed on partial data — treat with caution.",
            len(scores),
            expected,
            sorted(set(REVIEWER_SPECIALISTS) - {s.reviewer for s in scores}),
        )

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
    # Rule 1b — the mechanism gate must actually run. If mechanism_reviewer is
    # an expected reviewer but produced no parseable score, do NOT let the
    # paper be ACCEPTED on the remaining reviewers' average — that silently
    # skips the load-bearing gate. Require another review round.
    if "mechanism_reviewer" in REVIEWER_SPECIALISTS and not mech_scores:
        total_w = sum(s.weight for s in scores) or 1.0
        avg = sum(s.score * s.weight for s in scores) / total_w
        return AggregationResult(
            verdict="MAJOR_REVISION",
            weighted_avg=avg,
            rule_triggered="Rule 1: mechanism review missing",
            scores=scores,
            rationale=(
                "No parseable mechanism_reviewer score — the mechanism gate could "
                "not run. The paper cannot be accepted without it; re-running the "
                "review/revision round."
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
    """Extract a structured score from a reviewer's text output.

    Reviewers vary their format in practice. Observed in the May 2026 run:
      • "**OVERALL SCORE: 6.2/10**"                      (literature_reviewer)
      • "**Weighted overall score:** 5.6/10"             (mechanism_reviewer)
      • "## DIMENSION SCORES\n- Contribution: 6.5/10\n   ..."  (mechanism, no overall)
      • No explicit score, just dimension breakdown      (technical, writing,
                                                          identification)

    The old `(?:score|rating)[:\\s]+(\\d+)` regex caught only the first
    pattern because `:**` between the colon and the digit isn't whitespace.
    The new logic tries patterns in priority order — overall first, then
    dimension average, then any bare N/10 mention — so reviews are scored
    deterministically regardless of which template the model used.

    Returns None when no number on a 0-10 scale can be found at all.
    """
    import re

    score: float | None = None

    # P1 — explicit overall/weighted overall score line. The `[^\d\n]{0,15}?`
    # between the keyword and the digit absorbs markdown bold, colons,
    # asterisks, and short interstitial whitespace. Capped to one line so we
    # don't span paragraphs.
    m = re.search(
        r"(?:overall|weighted(?:\s+overall)?)\s+score[^\d\n]{0,15}?(\d+(?:\.\d+)?)\s*/\s*10",
        raw_output,
        re.IGNORECASE,
    )
    if m:
        score = float(m.group(1))

    # P2 — any "score ... N/10" mention (less specific; e.g. a reviewer who
    # just writes "Score: 7.5/10" without "Overall").
    if score is None:
        m = re.search(
            r"\bscore\b[^\d\n]{0,15}?(\d+(?:\.\d+)?)\s*/\s*10",
            raw_output,
            re.IGNORECASE,
        )
        if m:
            score = float(m.group(1))

    # P3 — DIMENSION SCORES section: average whatever numbers appear there.
    # The mechanism_reviewer style — list dimensions without an overall.
    if score is None:
        section = re.search(r"DIMENSION\s+SCORES.*?(?=\n##|\Z)", raw_output, re.IGNORECASE | re.DOTALL)
        if section:
            vals = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*/\s*10", section.group(0))]
            vals = [v for v in vals if 0 <= v <= 10]
            if vals:
                score = sum(vals) / len(vals)

    # P4 — last-resort: first "N/10" mention anywhere in the first 4 KB.
    if score is None:
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*10\b", raw_output[:4000])
        if m:
            v = float(m.group(1))
            if 0 <= v <= 10:
                score = v

    if score is None:
        return None

    return ReviewScore(
        reviewer=reviewer,
        score=min(10.0, max(0.0, score)),
        recommendation=parse_recommendation(raw_output),
        comments=raw_output[:500],
    )


# accept | minor revision | major revision | reject, tolerating the separators
# reviewers actually use ("Major Revision", "major-revision", "major_revision").
_REC_ALTERNATIVES = r"accept|minor[\s_-]*revision|major[\s_-]*revision|reject"


def parse_recommendation(raw_output: str) -> str:
    """The reviewer's stated recommendation.

    Prefers the mandatory closing line the reviewer prompt calls
    "parser-enforced"::

        RECOMMENDATION: Major Revision

    Canary #5 (2026-08-26) is why this is anchored. The previous version ran an
    unanchored substring search over the whole review body and took the FIRST
    hit, so `accept` matched inside "unacceptable" and `reject` inside
    "rejected". All six reviewers stated "Major Revision"; five were recorded as
    something else — three `accept` (from "unacceptable", "acceptable",
    "Acceptable") and two `reject` (from "rejected"). Only `technical_reviewer`
    came out right, and only because its prose happened to reach the real line
    before either word appeared.

    The fallback scan uses WORD BOUNDARIES and takes the LAST match rather than
    the first: `\\baccept\\b` cannot match "acceptable", and the recommendation
    is stated at the end, after any prose that discusses accepting or rejecting.

    Defaults to ``major_revision`` when nothing parses — the neutral verdict,
    neither waving a paper through nor failing it on a parse miss.
    """
    for pattern, flags in (
        # The mandatory closing line. Tolerates markdown around the label and
        # the value: "**RECOMMENDATION:** Reject", "## RECOMMENDATION: Accept".
        (rf"^[\s*#>\-]*RECOMMENDATION[\s*:\-]*({_REC_ALTERNATIVES})", re.IGNORECASE | re.MULTILINE),
        (rf"\b({_REC_ALTERNATIVES})\b", re.IGNORECASE),
    ):
        matches = re.findall(pattern, raw_output, flags)
        if matches:
            return re.sub(r"[\s_-]+", "_", matches[-1].strip().lower())
    return "major_revision"
