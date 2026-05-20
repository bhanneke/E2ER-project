"""Unit tests for the v0.5 anti-hallucination gate.

Pins behaviour of src/core/pipeline/verify_numbers.py:
- _values_match tolerance / sign / integer-exact rules
- _extract_table_numbers parses LaTeX tabular environments correctly
- _flatten_json walks nested structures
- end-to-end verify() classifies mismatches by severity
- skip-reason paths (no draft, no source files, unparseable JSON)

Motivating live test: paper a6182f08 (v0.4.5) — drafter cited
"log realized variance falls by 0.41 ($t=-3.9$)" with no source
in the data_analyst's CSVs. The technical reviewer caught it but
only after 6 reviewers had already burned tokens. verify_numbers
catches it pre-review at $0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.pipeline.verify_numbers import (
    Mismatch,
    VerificationReport,
    _extract_table_numbers,
    _flatten_json,
    _parse_number,
    _values_match,
    verify,
    verify_and_save,
)

# ---------------------------------------------------------------------------
# _values_match — the core matching rule
# ---------------------------------------------------------------------------


class TestValuesMatch:
    def test_exact_decimal_match(self):
        assert _values_match(0.41, 0.41)

    def test_within_default_tolerance(self):
        # tolerance=0.005 of max(1, |0.41|)=1 → window is 0.005 absolute
        assert _values_match(0.41, 0.412)
        assert _values_match(0.41, 0.408)

    def test_outside_default_tolerance(self):
        # 0.41 vs 0.23 — clearly outside; scale=1, diff=0.18
        assert not _values_match(0.41, 0.23)

    def test_sign_mismatch_rejected(self):
        # Both nonzero, opposite sign → never match regardless of magnitude
        assert not _values_match(0.41, -0.41)
        assert not _values_match(-1.0, 1.0)

    def test_zero_is_sign_agnostic(self):
        # Zero on either side bypasses the sign check, falls through to
        # tolerance check. tolerance=0.005 of max(1, 0) = 0.005 absolute.
        assert _values_match(0.0, 0.001)
        assert _values_match(0.001, 0.0)
        assert not _values_match(0.0, 0.5)

    def test_large_integer_must_be_exact(self):
        # Source value 10000 is an exact integer >=10 → exact match required.
        assert _values_match(10000.0, 10000.0)
        assert not _values_match(10000.0, 10001.0)

    def test_small_integer_uses_tolerance(self):
        # Source 5 is integer but <10 → falls through to scaled tolerance.
        # scale = max(1, 5) = 5; window = 0.005 * 5 = 0.025
        assert _values_match(5.01, 5.0)
        assert not _values_match(5.1, 5.0)

    def test_large_magnitude_scales_tolerance(self):
        # Source 100.0 (not integer per Python — but 100.0 == int(100.0))
        # IS treated as integer >=10 → exact match required. Use 100.5 to
        # exercise the scaled-tolerance branch.
        # scale=100.5; window = 0.5025
        assert _values_match(100.5, 100.5)
        assert _values_match(100.5, 100.7)
        assert not _values_match(100.5, 102.0)


# ---------------------------------------------------------------------------
# _flatten_json
# ---------------------------------------------------------------------------


class TestFlattenJson:
    def test_flat_dict(self):
        assert _flatten_json({"a": 1, "b": 2.5}) == {"a": 1.0, "b": 2.5}

    def test_nested_dict(self):
        flat = _flatten_json({"outer": {"inner": 0.42}})
        assert flat == {"outer.inner": 0.42}

    def test_list_uses_bracket_index(self):
        flat = _flatten_json({"xs": [1, 2, 3]})
        assert flat == {"xs[0]": 1.0, "xs[1]": 2.0, "xs[2]": 3.0}

    def test_skips_strings_and_bools(self):
        # bool is a subclass of int — _flatten_json must reject it explicitly.
        flat = _flatten_json({"label": "main", "active": True, "value": 0.5})
        assert flat == {"value": 0.5}

    def test_skips_nan_and_inf(self):
        import math

        flat = _flatten_json({"a": math.nan, "b": math.inf, "c": 1.0})
        assert flat == {"c": 1.0}

    def test_prefix_applied(self):
        flat = _flatten_json({"a": 1.0}, prefix="src")
        assert flat == {"src.a": 1.0}


# ---------------------------------------------------------------------------
# _extract_table_numbers
# ---------------------------------------------------------------------------


class TestExtractTableNumbers:
    def test_finds_numbers_in_tabular(self):
        tex = r"""
\begin{table}
\caption{Main results}
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
log RV & -0.41 & 0.10 \\
\bottomrule
\end{tabular}
\end{table}
"""
        nums = _extract_table_numbers(tex)
        values = {n for n, _ in nums}
        # All three table numbers picked up
        assert "-0.41" in values
        assert "0.10" in values

    def test_ignores_zero(self):
        tex = r"""
\begin{tabular}{lc}
A & 0 \\
B & 0.0 \\
C & 1.0 \\
\end{tabular}
"""
        nums = _extract_table_numbers(tex)
        # 0 and 0.0 are filtered (parsed == 0); 1.0 stays.
        values = {n for n, _ in nums}
        assert "1.0" in values
        assert "0" not in values
        assert "0.0" not in values

    def test_ignores_text_outside_tabular(self):
        tex = "In Section 2 we discuss the value 0.99 in detail.\nNo table here."
        nums = _extract_table_numbers(tex)
        assert nums == []

    def test_captures_table_label_in_context(self):
        tex = r"""
\label{tab:liquidity}
\begin{tabular}{lc}
x & 0.42 \\
\end{tabular}
"""
        nums = _extract_table_numbers(tex)
        assert nums
        # context string carries the label
        assert any("tab:liquidity" in ctx for _, ctx in nums)


# ---------------------------------------------------------------------------
# _parse_number
# ---------------------------------------------------------------------------


class TestParseNumber:
    def test_plain(self):
        assert _parse_number("0.41") == pytest.approx(0.41)

    def test_strips_commas(self):
        assert _parse_number("1,234") == 1234.0

    def test_negative(self):
        assert _parse_number("-1.23") == pytest.approx(-1.23)

    def test_unparseable_returns_none(self):
        assert _parse_number("not a number") is None


# ---------------------------------------------------------------------------
# verify() — end-to-end on a synthetic workspace
# ---------------------------------------------------------------------------


def _write_draft(ws: Path, tabular_rows: str) -> Path:
    """Write a minimal paper_draft.tex with a single table."""
    draft = ws / "paper_draft.tex"
    draft.write_text(
        r"""
\documentclass{article}
\begin{document}
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
"""
        + tabular_rows
        + r"""
\bottomrule
\end{tabular}
\end{document}
"""
    )
    return draft


class TestVerifyEndToEnd:
    def test_no_draft_skips(self, tmp_path: Path):
        report = verify(tmp_path / "missing.tex", tmp_path)
        assert report.skipped_reason and "not found" in report.skipped_reason
        # Skip is treated as pass — operator decides whether to gate on it.
        assert not report.critical_mismatches

    def test_no_source_files_skips(self, tmp_path: Path):
        _write_draft(tmp_path, "x & 0.42 & 0.01 \\\\")
        report = verify(tmp_path / "paper_draft.tex", tmp_path)
        assert report.skipped_reason and "no source JSON" in report.skipped_reason
        assert not report.critical_mismatches

    def test_unparseable_json_skips_that_file(self, tmp_path: Path):
        _write_draft(tmp_path, "x & 0.42 & 0.01 \\\\")
        (tmp_path / "summary_statistics.json").write_text("{not valid json")
        # No other source files exist → after the unparseable one is dropped,
        # there are no values left, so the skip path fires.
        report = verify(tmp_path / "paper_draft.tex", tmp_path)
        assert report.skipped_reason and "empty or unparseable" in report.skipped_reason

    def test_exact_match_passes(self, tmp_path: Path):
        _write_draft(tmp_path, "x & 0.42 & 0.01 \\\\")
        (tmp_path / "summary_statistics.json").write_text(json.dumps({"x": {"coef": 0.42, "se": 0.01}}))
        report = verify(tmp_path / "paper_draft.tex", tmp_path)
        assert report.passed
        assert report.matched == 2
        assert report.mismatched == 0
        assert not report.critical_mismatches

    def test_critical_mismatch_caught(self, tmp_path: Path):
        # Drafter claims -0.41 but source says -0.23. Relative error
        # (0.41 - 0.23) / 0.23 = 78% → critical (>10% threshold).
        _write_draft(tmp_path, "log RV & -0.41 & 0.10 \\\\")
        (tmp_path / "estimation_results.json").write_text(json.dumps({"log_rv": {"coef": -0.23, "se": 0.10}}))
        report = verify(tmp_path / "paper_draft.tex", tmp_path)
        assert not report.passed
        assert any(m.severity == "critical" for m in report.mismatches)
        # SE matched exactly → at least one matched value
        assert report.matched >= 1

    def test_major_mismatch_close_but_not_within_tolerance(self, tmp_path: Path):
        # 0.41 vs 0.42 — same sign, dist=0.01. Within 50% of |draft|=0.41.
        # Relative error = 0.01/0.42 ≈ 2.4% → major, not critical.
        _write_draft(tmp_path, "x & 0.41 & 0.01 \\\\")
        (tmp_path / "summary_statistics.json").write_text(json.dumps({"x": {"coef": 0.42, "se": 0.01}}))
        report = verify(tmp_path / "paper_draft.tex", tmp_path)
        # Draft 0.41 vs source 0.42: diff=0.01, tolerance=0.005*max(1,0.42)=0.005
        # → doesn't match, falls to closest-value branch as 'major'.
        majors = [m for m in report.mismatches if m.severity == "major"]
        assert majors, f"expected at least one major mismatch, got {report.mismatches}"
        assert not report.critical_mismatches  # the headline gate doesn't fire

    def test_unverifiable_number_does_not_fail(self, tmp_path: Path):
        # 5.00 in draft has no remotely-close source value (closest is 0.42,
        # which is >50% of |draft|=5.0 away). Counted as unverifiable, not
        # as a mismatch.
        _write_draft(tmp_path, "derived & 5.00 & 0.01 \\\\")
        (tmp_path / "summary_statistics.json").write_text(json.dumps({"x": {"coef": 0.42, "se": 0.01}}))
        report = verify(tmp_path / "paper_draft.tex", tmp_path)
        assert report.unverifiable >= 1
        # Unverifiable values do not contribute to mismatched counts and
        # the report still passes (no critical/major).
        assert not report.critical_mismatches


# ---------------------------------------------------------------------------
# verify_and_save persists the report
# ---------------------------------------------------------------------------


def test_verify_and_save_writes_number_verification_json(tmp_path: Path):
    _write_draft(tmp_path, "x & 0.42 & 0.01 \\\\")
    (tmp_path / "summary_statistics.json").write_text(json.dumps({"x": {"coef": 0.42, "se": 0.01}}))
    report = verify_and_save(tmp_path / "paper_draft.tex", tmp_path)
    assert report.passed
    out = tmp_path / "number_verification.json"
    assert out.exists(), "verify_and_save must persist the report"
    data = json.loads(out.read_text())
    assert data["passed"] is True
    assert data["matched"] >= 2


def test_verify_and_save_persists_even_on_skip(tmp_path: Path):
    """The dashboard reads number_verification.json regardless of outcome —
    skipped runs must still emit a report file so the UI can show
    'verification skipped: <reason>' instead of 404."""
    _write_draft(tmp_path, "x & 0.42 & 0.01 \\\\")
    # No source JSON files → skipped path.
    report = verify_and_save(tmp_path / "paper_draft.tex", tmp_path)
    assert report.skipped_reason
    out = tmp_path / "number_verification.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["skipped_reason"]


# ---------------------------------------------------------------------------
# Mismatch / VerificationReport dataclasses
# ---------------------------------------------------------------------------


def test_critical_mismatches_property_filters_severity():
    report = VerificationReport()
    report.mismatches = [
        Mismatch("0.41", "log_rv.coef", "-0.23", "Table 1, row 1, col 2", "critical"),
        Mismatch("0.10", "log_rv.se", "0.08", "Table 1, row 1, col 3", "major"),
        Mismatch("0.05", "x.coef", "0.06", "Table 1, row 2, col 2", "minor"),
    ]
    crits = report.critical_mismatches
    assert len(crits) == 1
    assert crits[0].severity == "critical"
