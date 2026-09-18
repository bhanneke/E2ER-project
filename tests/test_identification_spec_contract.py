"""Identified-spec contract: the econometrics headline must implement the
DECLARED identification (fixed effects / controls / clustering from
identification_spec.json), and contract violations must reach the retry
prompt instead of failing blind.

Regression target: post-M5 econometrics rigor was high-variance run-to-run —
one run estimated the strategy's clean TWFE (identification score 8), the
next reported a weaker spec (score 5) under identical steering. The prose
steering shifts odds; this contract pins the outcome."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.specialists.contract_check import (
    check_matches_declared_spec,
    check_specialist_artifacts,
    read_contract_feedback,
    write_contract_feedback,
)

_RESULTS = "estimation_results.json"


def _write_spec(ws: Path, primary: dict) -> None:
    (ws / "identification_spec.json").write_text(json.dumps({"primary": primary}), encoding="utf-8")


def _write_results(ws: Path, main: dict | None, **extra_specs: dict) -> None:
    payload: dict = {}
    if main is not None:
        payload["main"] = main
    payload.update(extra_specs)
    (ws / _RESULTS).write_text(json.dumps(payload), encoding="utf-8")


def _coeffs(*names: str) -> dict:
    return {n: {"estimate": 0.1, "se": 0.02, "t_stat": 5.0, "p_value": 0.001} for n in names}


# ── Backward compatibility: absent / undemanding specs pass ──────────────────


def test_no_spec_file_passes(tmp_path: Path):
    _write_results(tmp_path, {"coefficients": _coeffs("treat")})
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


def test_spec_declaring_nothing_checkable_passes(tmp_path: Path):
    _write_spec(tmp_path, {"estimator": "ols", "fixed_effects": [], "controls": [], "cluster_level": "none"})
    _write_results(tmp_path, {"coefficients": _coeffs("treat")})
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


def test_unparseable_spec_degrades_to_ok(tmp_path: Path):
    (tmp_path / "identification_spec.json").write_text("{not json", encoding="utf-8")
    _write_results(tmp_path, {"coefficients": _coeffs("treat")})
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


# ── Enforcement ──────────────────────────────────────────────────────────────


def test_compliant_echo_passes(tmp_path: Path):
    _write_spec(
        tmp_path,
        {"fixed_effects": ["collection", "month"], "controls": ["log_volume"], "cluster_level": "collection"},
    )
    _write_results(
        tmp_path,
        {
            "coefficients": _coeffs("treat", "log_volume"),
            "fixed_effects": ["collection", "month"],
            "controls": ["log_volume"],
            "cluster_level": "collection",
            "n_clusters": 512,
        },
    )
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


def test_missing_fe_echo_fails_with_actionable_reason(tmp_path: Path):
    _write_spec(tmp_path, {"fixed_effects": ["collection", "month"]})
    _write_results(
        tmp_path,
        {"coefficients": _coeffs("treat"), "fixed_effects": ["month"]},
    )
    check = check_matches_declared_spec(tmp_path, _RESULTS)
    assert not check.ok
    assert "collection" in check.reason
    assert "identification_spec.json" in check.reason


def test_raw_gap_under_other_key_fails_main_requirement(tmp_path: Path):
    """The 'silently substitute a raw gap' failure mode: results exist but the
    headline is not under `main` implementing the declared design."""
    _write_spec(tmp_path, {"fixed_effects": ["unit", "time"], "cluster_level": "unit"})
    _write_results(tmp_path, None, raw_gap={"coefficients": _coeffs("const", "treat")})
    check = check_matches_declared_spec(tmp_path, _RESULTS)
    assert not check.ok
    assert "'main'" in check.reason


def test_fe_matching_is_normalized_not_fuzzy(tmp_path: Path):
    _write_spec(tmp_path, {"fixed_effects": ["Collection", "month"]})
    # "collection_id" must NOT satisfy "Collection"; exact-after-normalization only.
    _write_results(
        tmp_path,
        {"coefficients": _coeffs("treat"), "fixed_effects": ["collection_id", "month"]},
    )
    assert not check_matches_declared_spec(tmp_path, _RESULTS).ok
    # Case/punctuation differences DO match.
    _write_results(
        tmp_path,
        {"coefficients": _coeffs("treat"), "fixed_effects": ["collection", "Month"]},
    )
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


def test_controls_satisfied_via_coefficient_keys(tmp_path: Path):
    _write_spec(tmp_path, {"controls": ["log_volume"]})
    _write_results(tmp_path, {"coefficients": _coeffs("treat", "log_volume")})
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


def test_missing_control_fails(tmp_path: Path):
    _write_spec(tmp_path, {"controls": ["log_volume", "collection_age"]})
    _write_results(tmp_path, {"coefficients": _coeffs("treat", "log_volume")})
    check = check_matches_declared_spec(tmp_path, _RESULTS)
    assert not check.ok
    assert "collection_age" in check.reason


def test_declared_clustering_requires_echo_and_count(tmp_path: Path):
    _write_spec(tmp_path, {"cluster_level": "collection"})
    # No cluster echo at all → fail.
    _write_results(tmp_path, {"coefficients": _coeffs("treat")})
    assert not check_matches_declared_spec(tmp_path, _RESULTS).ok
    # Echoed level but missing n_clusters → fail.
    _write_results(tmp_path, {"coefficients": _coeffs("treat"), "cluster_level": "collection"})
    check = check_matches_declared_spec(tmp_path, _RESULTS)
    assert not check.ok
    assert "n_clusters" in check.reason
    # Full echo → pass.
    _write_results(
        tmp_path,
        {"coefficients": _coeffs("treat"), "cluster_level": "collection", "n_clusters": 512},
    )
    assert check_matches_declared_spec(tmp_path, _RESULTS).ok


# ── Wiring: check_specialist_artifacts ordering ──────────────────────────────


def test_wired_for_econometrics_after_regression_floor(tmp_path: Path):
    _write_spec(tmp_path, {"fixed_effects": ["unit"]})
    _write_results(tmp_path, {"coefficients": _coeffs("treat")})  # no FE echo
    failures = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert any("identified-spec contract" in c.reason for c in failures)


def test_not_layered_on_descriptive_only_failure(tmp_path: Path):
    """When the regression floor already failed (descriptive-only output), the
    spec contract must NOT pile a second failure into the feedback."""
    _write_spec(tmp_path, {"fixed_effects": ["unit"]})
    (tmp_path / _RESULTS).write_text(json.dumps({"raw_gap": {"note": "descriptives only"}}), encoding="utf-8")
    failures = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert any("no estimated regression" in c.reason for c in failures)
    assert not any("identified-spec contract" in c.reason for c in failures)


def test_identification_strategist_sidecar_required(tmp_path: Path):
    (tmp_path / "identification_strategy.md").write_text("# Strategy\n" + "prose " * 40, encoding="utf-8")
    failures = [c for c in check_specialist_artifacts(tmp_path, "identification_strategist") if not c.ok]
    assert any(c.artifact == "identification_spec.json" for c in failures)
    _write_spec(tmp_path, {"estimator": "ols", "fixed_effects": [], "controls": [], "cluster_level": "none"})
    failures = [c for c in check_specialist_artifacts(tmp_path, "identification_strategist") if not c.ok]
    assert not failures


# ── Contract-violation feedback reaches the retry ────────────────────────────


def test_feedback_roundtrip_and_consume_once(tmp_path: Path):
    write_contract_feedback(tmp_path, "econometrics_specialist", "estimation_results.json: no FE echo")
    fb = read_contract_feedback(tmp_path, "econometrics_specialist")
    assert fb is not None
    assert "OUTPUT-CONTRACT VIOLATION" in fb
    assert "no FE echo" in fb
    # Consumed: a later (post-success) attempt must not see stale feedback.
    assert read_contract_feedback(tmp_path, "econometrics_specialist") is None


def test_feedback_is_per_specialist(tmp_path: Path):
    write_contract_feedback(tmp_path, "econometrics_specialist", "econ problem")
    assert read_contract_feedback(tmp_path, "data_analyst") is None
    assert read_contract_feedback(tmp_path, "econometrics_specialist") is not None


def test_feedback_missing_returns_none(tmp_path: Path):
    assert read_contract_feedback(tmp_path, "econometrics_specialist") is None
