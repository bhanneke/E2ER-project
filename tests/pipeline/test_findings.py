"""v0.6 step 1: Finding dataclass + three collectors.

Pure-refactor tests — no runtime call sites use these yet. Step 3 of
v0.6 wires them into `_run_revision_phase`, step 4 into
`_run_self_attack_phase`, step 5 into the verify_numbers auto-patch
loop. Pinning the contract now lets the downstream wiring land in
isolated commits.

Coverage:
- Finding dataclass: shape, validation, frozen-ness.
- collect_self_attack_findings: severity floor, category → target.
- collect_verify_numbers_findings: severity mapping, table_context parsing.
- collect_review_findings: degraded form (score-only), reviewer →
  primary section map.
- combine_findings: severity-desc + source-priority sort.
"""

from __future__ import annotations

import pytest

from src.core.pipeline.verify_numbers import Mismatch, VerificationReport
from src.core.strategist.actions import SelfAttackFinding, SelfAttackReport
from src.core.strategist.findings import (
    Finding,
    collect_review_findings,
    collect_self_attack_findings,
    collect_verify_numbers_findings,
    combine_findings,
)
from src.core.strategist.review_aggregator import ReviewScore

# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


class TestFindingDataclass:
    def test_construction(self):
        f = Finding(
            source="self_attack",
            source_detail="self_attack",
            target="section:identification",
            severity=8,
            problem="Pre-trends are not visually inspected.",
            suggested_fix="Add Figure 2 with year fixed effects.",
        )
        assert f.severity == 8
        assert f.target == "section:identification"

    def test_severity_must_be_int(self):
        with pytest.raises(TypeError):
            Finding(
                source="review",
                source_detail="technical_reviewer",
                target="paper:full",
                severity=5.0,  # type: ignore[arg-type]
                problem="x",
                suggested_fix="y",
            )

    def test_severity_out_of_range(self):
        for bad in (0, -1, 11, 100):
            with pytest.raises(ValueError):
                Finding(
                    source="review",
                    source_detail="r",
                    target="paper:full",
                    severity=bad,
                    problem="x",
                    suggested_fix="y",
                )

    def test_empty_target_rejected(self):
        with pytest.raises(ValueError):
            Finding(
                source="review",
                source_detail="r",
                target="",
                severity=5,
                problem="x",
                suggested_fix="y",
            )

    def test_bare_word_target_rejected(self):
        """Targets without a canonical prefix are caught at construction
        time — the merger downstream can't act on `coefficients` (was
        it a section? a table? a variable name?)."""
        with pytest.raises(ValueError):
            Finding(
                source="review",
                source_detail="r",
                target="coefficients",
                severity=5,
                problem="x",
                suggested_fix="y",
            )

    def test_canonical_prefix_accepted(self):
        # All canonical prefixes pass.
        for target in (
            "section:identification",
            "table:tab:main",
            "references",
            "abstract",
            "paper:full",
        ):
            Finding(
                source="review",
                source_detail="r",
                target=target,
                severity=5,
                problem="x",
                suggested_fix="y",
            )

    def test_finding_is_frozen(self):
        """Findings must be immutable — they get passed across stages
        and any in-place edit would silently corrupt the audit trail."""
        f = Finding(
            source="review",
            source_detail="r",
            target="paper:full",
            severity=5,
            problem="x",
            suggested_fix="y",
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            f.severity = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# collect_self_attack_findings
# ---------------------------------------------------------------------------


def _self_attack_report(*findings: SelfAttackFinding) -> SelfAttackReport:
    severities = [f.severity for f in findings]
    return SelfAttackReport(
        findings=list(findings),
        overall_severity=max(severities) if severities else 0,
    )


class TestSelfAttackCollector:
    def test_maps_categories_to_section_targets(self):
        report = _self_attack_report(
            SelfAttackFinding(
                severity=8,
                category="identification",
                description="Pre-trends are not inspected.",
                suggested_fix="Add Figure 2.",
            ),
            SelfAttackFinding(
                severity=7,
                category="bibliography",
                description="Three key references missing.",
                suggested_fix="Add Lou (2019), Hasbrouck (2023), Lehar (2024).",
            ),
        )
        findings = collect_self_attack_findings(report)
        targets = {f.target for f in findings}
        assert "section:identification" in targets
        assert "references" in targets

    def test_severity_floor_drops_minor_findings(self):
        report = _self_attack_report(
            SelfAttackFinding(severity=8, category="identification", description="bad", suggested_fix=""),
            SelfAttackFinding(severity=3, category="numerics", description="cosmetic", suggested_fix=""),
            SelfAttackFinding(severity=1, category="bibliography", description="cosmetic", suggested_fix=""),
        )
        findings = collect_self_attack_findings(report, severity_floor=4)
        # Only the severity-8 finding survives.
        assert len(findings) == 1
        assert findings[0].severity == 8

    def test_unknown_category_falls_back_to_paper_full(self):
        # The SelfAttackFinding model restricts category, but a malformed
        # report (e.g. loaded from a corrupted JSON) might slip through.
        # Construct a minimal mock that bypasses pydantic validation.
        class _BadFinding:
            severity = 8
            category = "garbage_value"
            description = "x"
            suggested_fix = "y"

        class _BadReport:
            findings = [_BadFinding()]
            overall_severity = 8

        findings = collect_self_attack_findings(_BadReport())  # type: ignore[arg-type]
        assert len(findings) == 1
        assert findings[0].target == "paper:full"

    def test_source_fields_propagated(self):
        report = _self_attack_report(
            SelfAttackFinding(severity=8, category="mechanism", description="d", suggested_fix="f"),
        )
        findings = collect_self_attack_findings(report)
        assert findings[0].source == "self_attack"
        assert findings[0].source_detail == "self_attack"


# ---------------------------------------------------------------------------
# collect_verify_numbers_findings
# ---------------------------------------------------------------------------


def _verification_report(*mismatches: Mismatch) -> VerificationReport:
    r = VerificationReport()
    r.mismatches = list(mismatches)
    return r


class TestVerifyNumbersCollector:
    def test_critical_mismatch_emits_severity_9(self):
        report = _verification_report(
            Mismatch(
                draft_value="0.80",
                source_key="estimation_results.main.coef",
                source_value="0.50",
                table_context="tab:main, row 1, col 2",
                severity="critical",
            ),
        )
        findings = collect_verify_numbers_findings(report)
        assert len(findings) == 1
        assert findings[0].severity == 9
        assert findings[0].source == "verify_numbers"

    def test_major_mismatch_emits_severity_6(self):
        report = _verification_report(
            Mismatch(
                draft_value="0.42",
                source_key="x.coef",
                source_value="0.41",
                table_context="tab:secondary, row 1, col 1",
                severity="major",
            ),
        )
        findings = collect_verify_numbers_findings(report, severity_floor=6)
        assert len(findings) == 1
        assert findings[0].severity == 6

    def test_minor_mismatch_below_default_floor(self):
        report = _verification_report(
            Mismatch(
                draft_value="0.05",
                source_key="x.coef",
                source_value="0.06",
                table_context="tab:main, row 2, col 2",
                severity="minor",
            ),
        )
        findings = collect_verify_numbers_findings(report)
        # Default floor=6; minor (severity 3) is dropped.
        assert findings == []

    def test_target_extracted_from_latex_label(self):
        report = _verification_report(
            Mismatch(
                draft_value="0.80",
                source_key="x.coef",
                source_value="0.50",
                table_context="tab:liquidity, row 1, col 2",
                severity="critical",
            ),
        )
        findings = collect_verify_numbers_findings(report)
        assert findings[0].target == "table:tab:liquidity"

    def test_target_falls_back_to_table_number(self):
        """Unlabelled tables get 'table:Table_N' rather than dropping
        to 'paper:full' — preserves enough context for the merger
        to scope the patch."""
        report = _verification_report(
            Mismatch(
                draft_value="0.80",
                source_key="x.coef",
                source_value="0.50",
                table_context="Table 3, row 1, col 2",
                severity="critical",
            ),
        )
        findings = collect_verify_numbers_findings(report)
        assert findings[0].target == "table:Table_3"

    def test_problem_text_carries_actual_numbers(self):
        report = _verification_report(
            Mismatch(
                draft_value="0.80",
                source_key="estimation_results.main.coef",
                source_value="0.50",
                table_context="tab:main, row 1, col 2",
                severity="critical",
            ),
        )
        findings = collect_verify_numbers_findings(report)
        problem = findings[0].problem
        assert "0.80" in problem
        assert "0.50" in problem
        assert "estimation_results.main.coef" in problem

    def test_suggested_fix_carries_actionable_replacement(self):
        report = _verification_report(
            Mismatch(
                draft_value="0.80",
                source_key="x",
                source_value="0.50",
                table_context="tab:main, row 1, col 2",
                severity="critical",
            ),
        )
        findings = collect_verify_numbers_findings(report)
        fix = findings[0].suggested_fix
        assert "Replace" in fix
        assert "0.80" in fix and "0.50" in fix


# ---------------------------------------------------------------------------
# collect_review_findings
# ---------------------------------------------------------------------------


class TestReviewCollector:
    def test_low_score_emits_finding(self):
        scores = [
            ReviewScore(
                reviewer="identification_reviewer",
                score=3.0,
                recommendation="Major Revision",
                comments="Pre-trends are not shown.",
            ),
        ]
        findings = collect_review_findings(scores)
        assert len(findings) == 1
        assert findings[0].source == "review"
        assert findings[0].source_detail == "identification_reviewer"
        assert findings[0].target == "section:identification"

    def test_high_score_does_not_emit_finding(self):
        scores = [
            ReviewScore(
                reviewer="technical_reviewer",
                score=8.0,
                recommendation="Accept",
                comments="Looks good.",
            ),
        ]
        assert collect_review_findings(scores) == []

    def test_score_to_severity_mapping(self):
        # Low score → high severity, mapped via round(11 - score).
        scores = [
            ReviewScore(reviewer="technical_reviewer", score=1.0, recommendation="Reject", comments=""),
            ReviewScore(reviewer="mechanism_reviewer", score=5.0, recommendation="Major Revision", comments=""),
        ]
        findings = collect_review_findings(scores, score_floor=10.0)
        severities = {f.source_detail: f.severity for f in findings}
        assert severities["technical_reviewer"] == 10
        assert severities["mechanism_reviewer"] == 6

    def test_writing_reviewer_targets_paper_full(self):
        """writing_reviewer is the catch-all reviewer with no specific
        section assignment — must fall back to paper:full."""
        scores = [
            ReviewScore(reviewer="writing_reviewer", score=3.0, recommendation="Reject", comments=""),
        ]
        findings = collect_review_findings(scores)
        assert findings[0].target == "paper:full"

    def test_unknown_reviewer_falls_back_to_paper_full(self):
        scores = [
            ReviewScore(reviewer="phantom_reviewer", score=3.0, recommendation="Reject", comments=""),
        ]
        findings = collect_review_findings(scores)
        assert findings[0].target == "paper:full"

    def test_empty_comments_get_pointer_text(self):
        """When a reviewer score is bad but comments are empty, the
        suggested_fix must still point the operator somewhere actionable
        — defaults to 'see the reviewer's full report'."""
        scores = [
            ReviewScore(reviewer="data_reviewer", score=3.0, recommendation="Reject", comments=""),
        ]
        findings = collect_review_findings(scores)
        assert "full report" in findings[0].suggested_fix.lower()


# ---------------------------------------------------------------------------
# combine_findings
# ---------------------------------------------------------------------------


class TestCombineFindings:
    def _f(self, source: str, severity: int) -> Finding:
        return Finding(
            source=source,  # type: ignore[arg-type]
            source_detail=source,
            target="paper:full",
            severity=severity,
            problem="x",
            suggested_fix="y",
        )

    def test_sorted_by_severity_desc(self):
        combined = combine_findings(
            [self._f("review", 3)],
            [self._f("self_attack", 8)],
            [self._f("verify_numbers", 6)],
        )
        assert [f.severity for f in combined] == [8, 6, 3]

    def test_ties_broken_by_source_priority(self):
        """When two findings have the same severity, verify_numbers
        wins over self_attack wins over review. Numerical mismatches
        are the most mechanical to fix — patch them first."""
        combined = combine_findings(
            [self._f("review", 6)],
            [self._f("self_attack", 6)],
            [self._f("verify_numbers", 6)],
        )
        # All severity 6 — order should be verify_numbers, self_attack, review.
        assert [f.source for f in combined] == [
            "verify_numbers",
            "self_attack",
            "review",
        ]

    def test_empty_inputs(self):
        assert combine_findings() == []
        assert combine_findings([], [], []) == []

    def test_preserves_all_findings(self):
        combined = combine_findings(
            [self._f("review", 3), self._f("review", 5)],
            [self._f("self_attack", 8)],
        )
        assert len(combined) == 3
