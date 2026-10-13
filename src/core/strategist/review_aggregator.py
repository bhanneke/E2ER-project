"""e2er's internal quality review: the panel's reviewer scores combined into one score.

Each reviewer specialist scores the draft from one angle (data,
identification, literature, mechanism, technical, writing; outside economics
also methods and domain plausibility) on a scale of 0 to 10. The panel is the
template's (its `aggregate` step; six reviewers by default). The combined
score is their weighted average (``_WEIGHTS``, or the template's
``review_weights``). The result's
``verdict`` is an internal code that picks the revision round the runner runs
(runner._run_revision_phase); it is never shown. Readers see the score:

* mechanism score below 5 → the analysis is redone and the draft scored once
  more (``MECHANISM_FAIL``, at most one such round; the rules then apply to the new score);
* mechanism score missing → one revision round that edits the text;
* any reviewer below 4, or a combined score below 5 → no revision round;
* combined score from 5 to below 6.5 → one revision round that edits the text;
* combined score 6.5 or more → no revision round.

Whatever the score, a run that finishes its steps is completed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReviewScore:
    reviewer: str
    score: float  # 1-10
    recommendation: str  # the reviewer's closing line, as an internal code; never shown
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
    # Internal code for the revision path, never shown: "ACCEPT" and
    # "MINOR_REVISION" (no round), "MAJOR_REVISION" (text revision round),
    # "MECHANISM_FAIL" (analysis redone), "HARD_REJECT" (no round).
    verdict: str
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
    # The discipline-neutral reviewers (0.16.0); a template's `review_weights` may set its own.
    "methods_reviewer": 1.5,
    "plausibility_reviewer": 1.25,
}

_RECOMMENDATION_FLOOR = {
    "accept": 8.0,
    "minor_revision": 6.5,
    "major_revision": 5.0,
    "reject": 0.0,
}


def aggregate_reviews(
    scores: list[ReviewScore],
    *,
    panel: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> AggregationResult:
    """Apply 3-rule mechanical aggregation to produce a final verdict.

    Rule 1: If mechanism_reviewer < 5 → MECHANISM_FAIL (hard gate).
    Rule 2: If any reviewer < 4 → HARD_REJECT.
    Rule 3: Weighted average — technical_reviewer has 1.5x weight.

    ``panel`` is the template's reviewers and ``weights`` its ``review_weights``,
    which take the place of the default weight of each reviewer they name; by
    default those of the running template, else e2er's six reviewers and their
    weights. Rule 1 applies only to a panel with a mechanism reviewer.
    """
    from ...logging_config import get_logger
    from ..pipeline.components import active
    from ..specialists.registry import REVIEWER_SPECIALISTS

    spec = active()
    if panel is None:
        panel = spec.panel() if spec is not None else list(REVIEWER_SPECIALISTS)
    if weights is None and spec is not None:
        weights = dict(spec.review_weights)
    expected = len(panel)
    if len(scores) < expected:
        get_logger(__name__).warning(
            "Partial review aggregation: only %d/%d reviewer scores present "
            "(missing: %s). Combined score computed on partial data — treat with caution.",
            len(scores),
            expected,
            sorted(set(panel) - {s.reviewer for s in scores}),
        )

    template_weights = weights or {}
    for s in scores:
        s.weight = template_weights.get(s.reviewer, _WEIGHTS.get(s.reviewer, 1.0))

    # Rule 1 — mechanism gate
    mech_scores = [s for s in scores if s.reviewer == "mechanism_reviewer"]
    if mech_scores and mech_scores[0].score < 5:
        return AggregationResult(
            verdict="MECHANISM_FAIL",
            weighted_avg=mech_scores[0].score,
            rule_triggered="Rule 1: mechanism_reviewer < 5",
            scores=scores,
            rationale=(
                f"Mechanism reviewer scored {mech_scores[0].score:.1f} of 10 (below 5): "
                "the analysis is redone and the draft scored again."
            ),
        )
    # Rule 1b — the mechanism gate must actually run. If mechanism_reviewer is
    # an expected reviewer but produced no parseable score, do NOT let the
    # paper be ACCEPTED on the remaining reviewers' average — that silently
    # skips the load-bearing gate. Require another review round.
    if "mechanism_reviewer" in panel and not mech_scores:
        total_w = sum(s.weight for s in scores) or 1.0
        avg = sum(s.score * s.weight for s in scores) / total_w
        return AggregationResult(
            verdict="MAJOR_REVISION",
            weighted_avg=avg,
            rule_triggered="Rule 1: mechanism review missing",
            scores=scores,
            rationale=(
                "No mechanism_reviewer score could be read, so the mechanism score "
                f"is missing. Combined score of the other reviewers: {avg:.2f} of 10; "
                "one revision round runs."
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
                f"{worst.reviewer} scored {worst.score:.1f} of 10 (below 4); "
                "no revision round runs. "
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
            f"Weighted average score: {weighted_avg:.2f} of 10. "
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
