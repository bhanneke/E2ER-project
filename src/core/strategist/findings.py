"""Structured `Finding` objects for the targeted-revision pipeline (v0.6).

Pre-v0.6, the three sources of revision input (`verify_numbers`,
`self_attack`, `review`) each spoke a different shape, and the
`revisor` specialist received only the review aggregator's
free-text rationale. That made it impossible to scope revisions —
the revisor saw "the panel said the identification section is
weak" and rewrote the whole paper.

v0.6 introduces a single `Finding` dataclass that all three
collectors emit. The downstream `patch_revisor` (step 2 of v0.6)
will receive a list of these and emit only the edits that target
the named sections / tables / references. The verify_numbers
collector closes the loop so a critical mismatch can drive an
automated patch instead of REJECT.

This module is pure refactor: the dataclass and collectors exist
but no runtime call sites use them yet. Step 3 wires them into
`_run_revision_phase`; step 4 wires them into
`_run_self_attack_phase`; step 5 closes the verify_numbers
auto-patch loop.

Target schema (consumed by the merger to enforce scope):

- `section:<name>` — e.g. `section:identification`,
  `section:results`, `section:introduction`.
- `table:<label>` — the LaTeX `\\label{}` of the affected
  `tabular`, e.g. `table:tab:main`.
- `references` — the bibliography / `references.bib`.
- `abstract` — the abstract block.
- `paper:full` — fallback when the finding pertains to the whole
  paper and no narrower target is known. The merger treats this
  as a wide scope and a v0.6 invariant test pins that
  `patch_revisor` refuses to act on `paper:full` findings without
  operator override — they have to be narrowed first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..pipeline.verify_numbers import VerificationReport
    from .actions import SelfAttackReport
    from .review_aggregator import ReviewScore


FindingSource = Literal["self_attack", "verify_numbers", "review"]


@dataclass(frozen=True)
class Finding:
    """A single, scoped revision target.

    Same shape across all sources so `patch_revisor` consumes one
    list. The `source` and `source_detail` fields preserve enough
    provenance for the operator to trace any patch back to the
    finding that motivated it.
    """

    source: FindingSource
    source_detail: str  # "technical_reviewer" | "self_attack" | "verify_numbers"
    target: str  # "section:identification" | "table:tab:main" | "references" | "abstract" | "paper:full"
    severity: int  # 1-10; >=7 critical, 4-6 major, 1-3 minor (cosmetic)
    problem: str  # one-sentence specific description
    suggested_fix: str  # one-sentence concrete suggestion

    def __post_init__(self) -> None:
        # Frozen dataclass — must use object.__setattr__ in __post_init__
        # if normalisation is needed. Validate severity here without
        # mutating; integer-only contract.
        if not isinstance(self.severity, int):
            raise TypeError(f"Finding.severity must be int (got {type(self.severity).__name__})")
        if not 1 <= self.severity <= 10:
            raise ValueError(f"Finding.severity must be in 1..10 (got {self.severity})")
        if not self.target:
            raise ValueError("Finding.target must be non-empty")
        # Canonical-prefix sanity check. Empty-string targets and bare
        # words are easy mistakes the merger can't recover from —
        # catch at construction.
        if ":" not in self.target and self.target not in {"references", "abstract"}:
            raise ValueError(
                f"Finding.target must be one of references / abstract / <prefix>:<name>; got {self.target!r}"
            )


# ---------------------------------------------------------------------------
# Self-attack collector
# ---------------------------------------------------------------------------

# Self-attack categories map onto section / reference targets. Anything not
# listed here falls back to `paper:full` (the merger will refuse to act on
# those without an explicit operator override).
_SELF_ATTACK_CATEGORY_TARGETS: dict[str, str] = {
    "identification": "section:identification",
    "mechanism": "section:mechanism",
    "numerics": "section:results",
    "institutions": "section:institutional_context",
    "equilibrium": "section:model",
    "bibliography": "references",
    "framing": "section:introduction",
    "novelty": "section:contribution",
}


def collect_self_attack_findings(
    report: SelfAttackReport,
    severity_floor: int = 4,
) -> list[Finding]:
    """Map a `SelfAttackReport` → list of `Finding`.

    Args:
        report: parsed self-attack output.
        severity_floor: drop findings with severity below this. Default
            4 corresponds to "more than cosmetic"; minor polish work
            isn't a revision target — the polish stack handles it.

    Returns:
        One `Finding` per qualifying self-attack finding, target
        mapped from the finding's `category`.
    """
    out: list[Finding] = []
    for f in report.findings:
        if f.severity < severity_floor:
            continue
        target = _SELF_ATTACK_CATEGORY_TARGETS.get(f.category, "paper:full")
        out.append(
            Finding(
                source="self_attack",
                source_detail="self_attack",
                target=target,
                severity=f.severity,
                problem=f.description,
                suggested_fix=f.suggested_fix or "",
            )
        )
    return out


# ---------------------------------------------------------------------------
# verify_numbers collector
# ---------------------------------------------------------------------------

# Severity mapping for verify_numbers mismatch classes. The
# verify_numbers gate uses string labels; the Finding contract uses
# integers. critical → 9 (just below catastrophic 10); major → 6
# (qualifies for patch); minor → 3 (typically below patch threshold,
# kept for completeness).
_MISMATCH_SEVERITY: dict[str, int] = {
    "critical": 9,
    "major": 6,
    "minor": 3,
}

# Parse "Table 1, row 2, col 3" or "tab:main, row 2, col 3 (caption...)"
# from Mismatch.table_context. Prefers the LaTeX \label{tab:...} form
# when present; falls back to "Table N" for unlabelled tables.
_TABLE_LABEL_RE = re.compile(r"(tab:[A-Za-z0-9_:-]+)")
_TABLE_NUMBER_RE = re.compile(r"Table (\d+)")


def _table_target_from_context(table_context: str) -> str:
    """Extract a `table:<label>` target from a Mismatch's table_context.

    Falls back to `paper:full` only if the context is unparseable —
    which would be a verify_numbers bug, not a caller error.
    """
    m = _TABLE_LABEL_RE.search(table_context)
    if m:
        return f"table:{m.group(1)}"
    m = _TABLE_NUMBER_RE.search(table_context)
    if m:
        return f"table:Table_{m.group(1)}"
    return "paper:full"


def collect_verify_numbers_findings(
    report: VerificationReport,
    severity_floor: int = 6,
) -> list[Finding]:
    """Map a `VerificationReport`'s mismatches → list of `Finding`.

    Args:
        report: parsed verify_numbers output.
        severity_floor: drop findings below this integer severity.
            Default 6 = include `critical` and `major` mismatches,
            drop `minor` ones (those are typically rounding-tolerable
            and shouldn't drive a revision pass).

    Returns:
        One `Finding` per qualifying Mismatch, target derived from
        the mismatch's `table_context`.
    """
    out: list[Finding] = []
    for m in report.mismatches:
        severity = _MISMATCH_SEVERITY.get(m.severity, 3)
        if severity < severity_floor:
            continue
        target = _table_target_from_context(m.table_context)
        problem = (
            f"Table cites {m.draft_value!r} but the closest source value "
            f"({m.source_key}) is {m.source_value} — relative error exceeds the "
            f"{m.severity}-mismatch threshold."
        )
        suggested_fix = (
            f"Replace {m.draft_value!r} in {m.table_context} with "
            f"{m.source_value} (or update the source JSON if the table is "
            f"correct and the source is stale)."
        )
        out.append(
            Finding(
                source="verify_numbers",
                source_detail="verify_numbers",
                target=target,
                severity=severity,
                problem=problem,
                suggested_fix=suggested_fix,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Review collector (degraded for v0.6 step 1; richer once reviewer
# closing format is extended in step 2)
# ---------------------------------------------------------------------------

# Threshold below which a reviewer score becomes a Finding worth
# patching. Scores 7+ are not actionable revision targets — they
# indicate the section is acceptable.
_REVIEW_SCORE_FINDING_FLOOR = 6.0

# Map reviewer specialist name → primary section it reviews. Used to
# pick a `target` for the degraded-form review Finding. When the
# reviewer prompt is extended (step 2) with a structured FINDINGS
# JSON block, those structured targets win; this map is the fallback.
_REVIEWER_PRIMARY_TARGET: dict[str, str] = {
    "mechanism_reviewer": "section:mechanism",
    "technical_reviewer": "section:results",
    "identification_reviewer": "section:identification",
    "literature_reviewer": "section:literature",
    "data_reviewer": "section:data",
    "writing_reviewer": "paper:full",
}


def _review_severity_from_score(score: float) -> int:
    """Convert a 0-10 reviewer score into a 1-10 Finding severity.

    Low scores correspond to high severity (more revision needed):
        score 1 → severity 10
        score 5 → severity 6
        score 7 → severity 4 (below the default revision floor)

    Clamped to 1..10.
    """
    raw = round(11 - score)
    return max(1, min(10, int(raw)))


def collect_review_findings(
    scores: list[ReviewScore],
    score_floor: float = _REVIEW_SCORE_FINDING_FLOOR,
) -> list[Finding]:
    """Map review aggregator output → list of `Finding`.

    v0.6 step 1: degraded form. Emits one Finding per reviewer
    whose score is below ``score_floor``; the target is the primary
    section that reviewer covers (per `_REVIEWER_PRIMARY_TARGET`).
    The recommendation text becomes the `problem` field; the
    reviewer's comments become the `suggested_fix`.

    Step 2 of v0.6 extends the reviewer closing format with a
    `FINDINGS:` JSON block listing specific section / table targets;
    when that lands this function gains a richer code path. The
    degraded form here lets the rest of v0.6 land first.
    """
    out: list[Finding] = []
    for s in scores:
        if s.score >= score_floor:
            continue
        target = _REVIEWER_PRIMARY_TARGET.get(s.reviewer, "paper:full")
        problem = (
            f"{s.reviewer} scored this paper {s.score:.1f}/10 "
            f"(recommendation: {s.recommendation}). "
            f"Below the {score_floor:.1f} threshold for the revision phase."
        )
        suggested_fix = (
            s.comments.strip() if s.comments.strip() else "See the reviewer's full report for specific issues."
        )
        out.append(
            Finding(
                source="review",
                source_detail=s.reviewer,
                target=target,
                severity=_review_severity_from_score(s.score),
                problem=problem,
                suggested_fix=suggested_fix,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Convenience: combine all three into one prioritised list
# ---------------------------------------------------------------------------


def combine_findings(*finding_lists: list[Finding]) -> list[Finding]:
    """Combine findings from multiple collectors, sorted by severity desc.

    Higher-severity findings first so a budget-constrained
    `patch_revisor` addresses the most consequential issues first.
    Ties broken by source order: verify_numbers > self_attack >
    review (numerical mismatches are the most mechanical to fix
    and have the strongest correctness signal).
    """
    _source_priority = {"verify_numbers": 0, "self_attack": 1, "review": 2}
    all_findings = [f for lst in finding_lists for f in lst]
    return sorted(
        all_findings,
        key=lambda f: (-f.severity, _source_priority.get(f.source, 99)),
    )
