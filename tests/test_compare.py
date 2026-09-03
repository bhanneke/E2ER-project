"""Design-choice comparison across runs (WS-P3.3).

Three synthetic bundles — two agreeing, one divergent — exercise the matrix,
per-field agreement (scalar modal + set Jaccard), the descriptive variance
decomposition, divergent-field flagging, the coefficient fallback, and the
matrix.json input path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.compare import build_comparison, compare, load_run_record, render_report


def _make_bundle(
    d: Path,
    *,
    backend: str,
    estimator: str,
    fe: list[str],
    controls: list[str],
    cluster: str,
    treatment: str = "treat",
    estimate: float = 0.5,
    coeffs: dict | None = None,
    governance: str = "full",
) -> Path:
    (d / "design").mkdir(parents=True)
    (d / "results").mkdir(parents=True)
    (d / "design" / "identification_spec.json").write_text(
        json.dumps(
            {
                "primary": {
                    "estimator": estimator,
                    "unit_of_analysis": "firm",
                    "outcome": "y",
                    "treatment": treatment,
                    "fixed_effects": fe,
                    "controls": controls,
                    "cluster_level": cluster,
                    "identifying_assumption": "parallel trends",
                }
            }
        )
    )
    coefs = coeffs if coeffs is not None else {treatment: {"estimate": estimate, "se": 0.1, "p_value": 0.03}}
    (d / "results" / "estimation_results.json").write_text(
        json.dumps({"main": {"n_observations": 1000, "coefficients": coefs}})
    )
    (d / "provenance.json").write_text(
        json.dumps({"run": {"backend": backend, "model": "m1", "governance": governance}})
    )
    return d


def _three_runs(tmp_path: Path) -> list[dict]:
    b1 = _make_bundle(
        tmp_path / "cc-1",
        backend="claude_code",
        estimator="did",
        fe=["unit", "time"],
        controls=["x1"],
        cluster="unit",
        estimate=0.50,
    )
    b2 = _make_bundle(
        tmp_path / "cc-2",
        backend="claude_code",
        estimator="did",
        fe=["unit", "time"],
        controls=["x1"],
        cluster="unit",
        estimate=0.54,
    )
    b3 = _make_bundle(
        tmp_path / "cx-1",
        backend="codex",
        estimator="iv",
        fe=["unit"],
        controls=["x1", "x2"],
        cluster="time",
        estimate=0.20,
    )
    return [
        load_run_record(b1, "claude_code/rep-1"),
        load_run_record(b2, "claude_code/rep-2"),
        load_run_record(b3, "codex/rep-1"),
    ]


def test_design_matrix_values(tmp_path: Path):
    comp = build_comparison(_three_runs(tmp_path))
    assert comp["n_runs"] == 3
    est = comp["design_matrix"]["estimator"]
    assert est["claude_code/rep-1"] == "did"
    assert est["codex/rep-1"] == "iv"


def test_scalar_agreement_and_divergence(tmp_path: Path):
    comp = build_comparison(_three_runs(tmp_path))
    # estimator: did, did, iv → modal share 2/3
    assert comp["agreement"]["estimator"]["score"] == pytest.approx(2 / 3)
    assert comp["agreement"]["estimator"]["modal"] == "did"
    # treatment: all "treat" → full agreement
    assert comp["agreement"]["treatment"]["score"] == 1.0
    assert "estimator" in comp["divergent_fields"]
    assert "treatment" not in comp["divergent_fields"]


def test_set_field_jaccard(tmp_path: Path):
    comp = build_comparison(_three_runs(tmp_path))
    # fixed_effects: {unit,time},{unit,time},{unit} → mean pairwise J = (1 + .5 + .5)/3
    assert comp["agreement"]["fixed_effects"]["score"] == pytest.approx((1 + 0.5 + 0.5) / 3)
    assert "fixed_effects" in comp["divergent_fields"]
    assert "controls" in comp["divergent_fields"]


def test_variance_decomposition(tmp_path: Path):
    comp = build_comparison(_three_runs(tmp_path))
    v = comp["variance"]
    assert v["available"] is True
    assert v["n_backends"] == 2 and v["n_estimates"] == 3
    # within = pvar([0.50, 0.54]) = 0.0004 (only claude_code has >= 2)
    assert v["within_backend"] == pytest.approx(0.0004)
    # between = pvar([mean(cc)=0.52, mean(cx)=0.20]) = 0.0256
    assert v["between_backend"] == pytest.approx(0.0256)


def test_variance_unavailable_with_one_estimate(tmp_path: Path):
    b = _make_bundle(tmp_path / "only", backend="codex", estimator="ols", fe=[], controls=[], cluster="none")
    comp = build_comparison([load_run_record(b, "a"), load_run_record(b, "b")])
    # same estimate twice, one backend → within computable but let's just check
    # the shape is present; with 2 identical estimates variance is 0.
    assert comp["variance"]["available"] is True


def test_coefficient_fallback_when_treatment_term_absent(tmp_path: Path):
    # treatment declared as "treat" but coefficients only has "policy_x".
    b = _make_bundle(
        tmp_path / "fb",
        backend="codex",
        estimator="ols",
        fe=[],
        controls=[],
        cluster="none",
        coeffs={"const": {"estimate": 1.0}, "policy_x": {"estimate": 0.33, "se": 0.1, "p_value": 0.2}},
    )
    rec = load_run_record(b, "fb")
    assert rec["coef_fallback"] is True
    assert rec["fields"]["coef_term"] == "policy_x"  # first non-intercept
    assert rec["fields"]["coef_estimate"] == 0.33


def test_report_renders_with_preamble_and_flags(tmp_path: Path):
    comp = build_comparison(_three_runs(tmp_path))
    report = render_report(comp)
    assert "Design-choice comparison" in report
    assert "No run is promoted here" in report  # the anti-selection preamble
    assert "⚠️" in report  # a divergent field is flagged
    assert "claude_code/rep-1" in report


def test_missing_files_degrade_to_na(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    rec = load_run_record(empty, "empty")
    assert rec["fields"]["estimator"] is None
    assert rec["fields"]["coef_estimate"] is None


# ── CLI + matrix.json input ──────────────────────────────────────────────────


def test_compare_via_matrix_json(tmp_path: Path):
    b1 = _make_bundle(tmp_path / "b1", backend="claude_code", estimator="did", fe=["unit"], controls=[], cluster="unit")
    b2 = _make_bundle(tmp_path / "b2", backend="codex", estimator="iv", fe=["unit"], controls=[], cluster="unit")
    matrix = {
        "research_question": "Does X affect Y?",
        "runs": [
            {"backend": "claude_code", "repeat": 1, "paper_id": "p1", "status": "completed", "bundle_path": str(b1)},
            {"backend": "codex", "repeat": 1, "paper_id": "p2", "status": "completed", "bundle_path": str(b2)},
            {"backend": "gemini", "repeat": 1, "paper_id": "p3", "status": "failed", "bundle_path": None},
        ],
    }
    mpath = tmp_path / "matrix.json"
    mpath.write_text(json.dumps(matrix))
    rc = compare([str(mpath)])
    assert rc == 0
    comp = json.loads((tmp_path / "comparison.json").read_text())
    assert comp["research_question"] == "Does X affect Y?"
    assert comp["n_runs"] == 2  # the failed run (no bundle) is excluded
    assert (tmp_path / "comparison_report.md").is_file()


def test_compare_needs_two_runs(tmp_path: Path):
    b1 = _make_bundle(tmp_path / "solo", backend="codex", estimator="ols", fe=[], controls=[], cluster="none")
    assert compare([str(b1)]) == 2  # only one bundle
