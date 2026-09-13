"""Deterministic table renderer — src/core/renderer/tables.py."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.renderer.tables import ensure_input_stubs, render_tables

# Inline fixtures shaped like a real Welch-Goyal estimation_results.json
# (the workspace fixtures are gitignored, so tests must be self-contained).
EST = {
    "dp_full": {
        "specification": "Predictive OLS, full",
        "n_observations": 424,
        "coefficients": {"dp": {"estimate": 0.013577742717, "se": 0.008308296660, "p_value": 0.1022}},
        "diagnostics": {"r_squared": 0.0076874},
        "forecast_evaluation": {"oos_r_squared": 0.006304086, "clark_west_stat": 1.1139},
    },
    "tbl_post2008": {
        "specification": "Predictive OLS, post-2008",
        "n_observations": 203,
        "coefficients": {
            # p < 0.01 → ***
            "tbl": {"estimate": -0.00074969, "se": 0.0017551, "p_value": 0.004}
        },
        "diagnostics": {"r_squared": 0.0014},
        "forecast_evaluation": {"oos_r_squared": -0.0072, "clark_west_stat": -0.265},
    },
    "combination_full": {
        "specification": "Equal-weighted combination",
        "n_observations": None,  # legitimately undefined
        "coefficients": {},  # empty by design
        "diagnostics": {},
        "forecast_evaluation": {"oos_r_squared": -0.00448, "clark_west_stat": -0.181},
    },
}
ROB = {
    "dp_full_ct_restricted": {
        "specification": "dp: CT-restricted",
        "coefficients": {},
        "diagnostics": {},
        "forecast_evaluation": {"oos_r_squared": 0.0073909, "clark_west_stat": 1.243},
    }
}


def _ws(tmp_path: Path, spec: dict) -> Path:
    (tmp_path / "estimation_results.json").write_text(json.dumps(EST), encoding="utf-8")
    (tmp_path / "robustness_results.json").write_text(json.dumps(ROB), encoding="utf-8")
    (tmp_path / "table_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return tmp_path


def _spec(columns, rows, **kw):
    table = {"filename": "main.tex", "label": "tab:main", "caption": "C", "columns": columns, "rows": rows, **kw}
    return {"tables": [table]}


# ── Core rendering ──────────────────────────────────────────────────────────


def test_renders_real_values_with_se_and_stars(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "dp_full", "header": "dp"}, {"spec_key": "tbl_post2008", "header": "tbl"}],
            [
                {"type": "coefficient", "var": "*", "label": "$\\hat\\beta$"},
                {"type": "stat", "field": "oos_r_squared", "label": "OOS $R^2$", "decimals": 4},
                {"type": "stat", "field": "n_observations", "label": "N", "decimals": 0},
            ],
        ),
    )
    report = render_tables(ws)
    assert report.rendered == ["main.tex"]
    assert report.unresolved == []
    tex = (ws / "tables" / "main.tex").read_text()
    # dp_full primary coefficient 0.01358 → 0.014; no stars (p=0.10 not < .10)
    assert "0.014" in tex
    assert "(0.008)" in tex  # SE line
    # tbl_post2008 primary coef p=0.004 < .01 → ***
    assert "-0.001***" in tex
    # OOS R² (4 dp) and N as integer
    assert "0.0063" in tex and "424" in tex
    assert "\\input" not in tex  # the table is a self-contained \begin{table}


def test_significance_star_thresholds(tmp_path: Path):
    from src.core.renderer.tables import _stars

    assert _stars(0.009) == "***"
    assert _stars(0.03) == "**"
    assert _stars(0.08) == "*"
    assert _stars(0.5) == ""
    assert _stars(None) == ""


# ── Defensive cases (must NOT raise, must NOT silently mis-render) ──────────


def test_combination_empty_coefficients_render_dash_not_flagged(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "combination_full", "header": "Comb"}],
            [{"type": "coefficient", "var": "*", "label": "$\\hat\\beta$"}],
        ),
    )
    report = render_tables(ws)
    tex = (ws / "tables" / "main.tex").read_text()
    assert "---" in tex  # empty coefficients → em dash
    assert report.unresolved == []  # empty-by-design is NOT an unresolved ref


def test_null_stat_renders_dash_not_flagged(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "combination_full", "header": "Comb"}],
            [{"type": "stat", "field": "n_observations", "label": "N", "decimals": 0}],
        ),
    )
    report = render_tables(ws)
    tex = (ws / "tables" / "main.tex").read_text()
    assert "---" in tex  # n_observations is null → em dash
    assert report.unresolved == []  # present-but-null is not unresolved


def test_unresolved_spec_key_is_flagged(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "does_not_exist", "header": "X"}],
            [{"type": "stat", "field": "oos_r_squared", "label": "OOS"}],
        ),
    )
    report = render_tables(ws)
    kinds = {(u.kind, u.ref) for u in report.unresolved}
    assert ("spec_key", "does_not_exist") in kinds


def test_unresolved_field_and_coefficient_flagged(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "dp_full", "header": "dp"}],
            [
                {"type": "stat", "field": "no_such_field", "label": "?"},
                {"type": "coefficient", "var": "no_such_var", "label": "?"},
            ],
        ),
    )
    report = render_tables(ws)
    kinds = {(u.kind, u.ref) for u in report.unresolved}
    assert ("stat", "no_such_field") in kinds
    assert ("coefficient", "no_such_var") in kinds


def test_robustness_key_resolves(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "dp_full_ct_restricted", "header": "CT"}],
            [{"type": "stat", "field": "clark_west_stat", "label": "CW", "decimals": 3}],
        ),
    )
    report = render_tables(ws)
    assert report.unresolved == []
    assert "1.243" in (ws / "tables" / "main.tex").read_text()


# ── No spec / idempotency / bad input ──────────────────────────────────────


def test_no_table_spec_is_skipped(tmp_path: Path):
    report = render_tables(tmp_path)
    assert report.skipped_reason is not None
    assert report.rendered == []


def test_idempotent_render(tmp_path: Path):
    ws = _ws(
        tmp_path,
        _spec(
            [{"spec_key": "dp_full", "header": "dp"}],
            [{"type": "coefficient", "var": "dp", "label": "DP"}],
        ),
    )
    render_tables(ws)
    first = (ws / "tables" / "main.tex").read_bytes()
    render_tables(ws)
    assert (ws / "tables" / "main.tex").read_bytes() == first


def test_invalid_filename_rejected(tmp_path: Path):
    ws = _ws(tmp_path, {"tables": [{"filename": "../evil.tex", "columns": [], "rows": []}]})
    report = render_tables(ws)
    assert report.rendered == []
    assert report.errors


# ── ensure_input_stubs ─────────────────────────────────────────────────────


def test_stub_created_for_dangling_input(tmp_path: Path):
    (tmp_path / "paper_draft.tex").write_text("Text.\n\\input{tables/missing.tex}\n", encoding="utf-8")
    created = ensure_input_stubs(tmp_path)
    assert created == ["tables/missing.tex"]
    assert (tmp_path / "tables" / "missing.tex").is_file()


def test_stub_handles_extensionless_input(tmp_path: Path):
    (tmp_path / "paper_draft.tex").write_text("\\input{tables/foo}\n", encoding="utf-8")
    created = ensure_input_stubs(tmp_path)
    assert created == ["tables/foo.tex"]
    assert (tmp_path / "tables" / "foo.tex").is_file()


def test_stub_does_not_overwrite_existing(tmp_path: Path):
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "main.tex").write_text("REAL TABLE", encoding="utf-8")
    (tmp_path / "paper_draft.tex").write_text("\\input{tables/main.tex}\n", encoding="utf-8")
    assert ensure_input_stubs(tmp_path) == []
    assert (tables / "main.tex").read_text() == "REAL TABLE"


def test_stub_no_draft_returns_empty(tmp_path: Path):
    assert ensure_input_stubs(tmp_path) == []


# ── PR-2: deterministic key/var/field normalization (order-insensitive) ────


def _ws_keys(tmp_path: Path, est: dict, spec: dict) -> Path:
    (tmp_path / "estimation_results.json").write_text(json.dumps(est), encoding="utf-8")
    (tmp_path / "table_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return tmp_path


def test_spec_key_resolved_by_token_normalization(tmp_path: Path):
    """The validated bug: econ named specs `full_dp`, the drafter wrote
    `dp_full`. Token-set normalization resolves it; the table populates."""
    est = {
        "full_dp": {
            "n_observations": 424,
            "coefficients": {"dp": {"estimate": 0.0136, "p_value": 0.5}},
            "forecast_evaluation": {"oos_r_squared": 0.0063},
        }
    }
    spec = _spec(
        [{"spec_key": "dp_full", "header": "dp"}],
        [{"type": "stat", "field": "oos_r_squared", "label": "OOS", "decimals": 4}],
    )
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert report.unresolved == []
    assert [(n.requested, n.resolved) for n in report.normalized] == [("dp_full", "full_dp")]
    assert "0.0063" in (ws / "tables" / "main.tex").read_text()


def test_coefficient_var_resolved_by_token_normalization(tmp_path: Path):
    est = {"m1": {"coefficients": {"treat_post": {"estimate": -0.231, "se": 0.058, "p_value": 0.001}}}}
    spec = _spec(
        [{"spec_key": "m1", "header": "(1)"}], [{"type": "coefficient", "var": "post_treat", "label": "Effect"}]
    )
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert report.unresolved == []
    assert any(n.kind == "coefficient" and n.resolved == "treat_post" for n in report.normalized)
    assert "-0.231" in (ws / "tables" / "main.tex").read_text()


def test_genuinely_different_field_name_stays_unresolved(tmp_path: Path):
    """`cw_stat` vs the JSON's `clark_west_stat` are different token sets —
    normalization must NOT guess; it stays unresolved (the feedback case)."""
    est = {"m1": {"forecast_evaluation": {"clark_west_stat": 1.24}}}
    spec = _spec([{"spec_key": "m1", "header": "(1)"}], [{"type": "stat", "field": "cw_stat", "label": "CW"}])
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert report.normalized == []
    assert any(u.kind == "stat" and u.ref == "cw_stat" for u in report.unresolved)


def test_ambiguous_token_match_not_resolved(tmp_path: Path):
    """Two source keys share the target's token set → never guess."""
    est = {
        "full_dp": {"forecast_evaluation": {"oos_r_squared": 0.1}},
        "dp__full": {"forecast_evaluation": {"oos_r_squared": 0.2}},
    }
    spec = _spec([{"spec_key": "dp_full", "header": "x"}], [{"type": "stat", "field": "oos_r_squared", "label": "OOS"}])
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert any(u.kind == "spec_key" and u.ref == "dp_full" for u in report.unresolved)
    assert report.normalized == []


# --- nested-path descent -------------------------------------------------
# The 2026-08-20 canary: the numbers were all present, one level below the
# three flat locations `_resolve_stat` inspects, and the render halted on 13
# unresolved refs after the section_writer repair attempt failed to fix it.


def _nested_est() -> dict:
    """The shape the econometrics specialist actually produced."""
    return {
        "main": {
            "specification": "Threshold regime classification",
            "transition_probabilities_pre": {"p_LL": 0.76, "p_HH": 0.2978723404255319},
            "transition_probabilities_post": {"p_LL": 0.59, "p_HH": 0.4526315789473684},
            "treatment_effects": {
                "delta_p_HH": {"estimate": 0.1547592385, "se": 0.0874, "p_value": 0.0768},
                "delta_p_LL": {"estimate": -0.1733},
            },
        }
    }


def test_nested_stat_resolved_by_descent(tmp_path: Path):
    """`p_HH_pre` lives at `transition_probabilities_pre.p_HH` — the tokens of
    the request are a subset of the path's, uniquely at that depth."""
    spec = _spec(
        [{"spec_key": "main", "header": "(1)"}],
        [{"type": "stat", "field": "p_HH_pre", "label": "$p_{HH}$ pre", "decimals": 4}],
    )
    ws = _ws_keys(tmp_path, _nested_est(), spec)
    report = render_tables(ws)
    assert report.unresolved == []
    assert any(
        n.kind == "stat" and n.requested == "p_HH_pre" and "transition_probabilities_pre.p_HH" in n.resolved
        for n in report.normalized
    ), "the substitution must be recorded so the rendered number stays auditable"
    assert "0.2979" in (ws / "tables" / "main.tex").read_text()


def test_nested_estimate_object_renders_point_estimate(tmp_path: Path):
    """A matched estimate-shaped object contributes its `estimate`, not a dict."""
    spec = _spec(
        [{"spec_key": "main", "header": "(1)"}],
        [{"type": "stat", "field": "delta_p_HH", "label": "$\\Delta p$", "decimals": 3}],
    )
    ws = _ws_keys(tmp_path, _nested_est(), spec)
    report = render_tables(ws)
    assert report.unresolved == []
    assert "0.155" in (ws / "tables" / "main.tex").read_text()


def test_nested_sibling_with_different_tokens_does_not_collide(tmp_path: Path):
    """`delta_p_LL` must not satisfy a request for `delta_p_HH`."""
    spec = _spec(
        [{"spec_key": "main", "header": "(1)"}],
        [{"type": "stat", "field": "delta_p_XX", "label": "bogus"}],
    )
    ws = _ws_keys(tmp_path, _nested_est(), spec)
    report = render_tables(ws)
    assert any(u.kind == "stat" and u.ref == "delta_p_XX" for u in report.unresolved)


def test_nested_conflicting_values_refused(tmp_path: Path):
    """Two equally-shallow matches holding DIFFERENT numbers is a real
    ambiguity — the renderer must flag it, never pick one."""
    est = {
        "main": {
            "transition_probabilities_pre": {"p_HH": 0.30},
            "bootstrap_probabilities_pre": {"p_HH": 0.91},
        }
    }
    spec = _spec([{"spec_key": "main", "header": "(1)"}], [{"type": "stat", "field": "p_HH_pre", "label": "p"}])
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert any(u.kind == "stat" and u.ref == "p_HH_pre" for u in report.unresolved)
    assert report.normalized == []


def test_nested_agreeing_duplicates_resolve(tmp_path: Path):
    """The canary's real shape: `p_HH_pre` matches both the transition block
    and `logistic_regression.implied_p_HH_pre`, holding the same number. The
    ambiguity is nominal, so it resolves — and records both paths."""
    est = {
        "main": {
            "transition_probabilities_pre": {"p_HH": 0.2978723404255319},
            "logistic_regression": {"implied_p_HH_pre": 0.2978723404255319},
        }
    }
    spec = _spec(
        [{"spec_key": "main", "header": "(1)"}],
        [{"type": "stat", "field": "p_HH_pre", "label": "p", "decimals": 4}],
    )
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert report.unresolved == []
    resolved = [n.resolved for n in report.normalized if n.requested == "p_HH_pre"]
    assert resolved and "==" in resolved[0], "both corroborating paths must be recorded"
    assert "0.2979" in (ws / "tables" / "main.tex").read_text()


def test_nested_descent_skips_coefficients_block(tmp_path: Path):
    """Coefficients have their own row type; a `stat` row must not reach in."""
    est = {"main": {"coefficients": {"treat_post": {"estimate": -0.231, "se": 0.058}}}}
    spec = _spec([{"spec_key": "main", "header": "(1)"}], [{"type": "stat", "field": "treat_post", "label": "T"}])
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert any(u.kind == "stat" and u.ref == "treat_post" for u in report.unresolved)


def test_shallower_match_wins_over_deeper(tmp_path: Path):
    """Depth breaks ties before uniqueness is tested, so a nested duplicate
    deeper in the tree cannot make a clean shallow match ambiguous."""
    est = {
        "main": {
            "block_pre": {"gamma": 1.5},
            "sensitivity": {"block_pre": {"gamma": 9.9}},
        }
    }
    spec = _spec(
        [{"spec_key": "main", "header": "(1)"}],
        [{"type": "stat", "field": "gamma_pre", "label": "g", "decimals": 1}],
    )
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert report.unresolved == []
    assert "1.5" in (ws / "tables" / "main.tex").read_text()


def test_absent_scalar_still_halts(tmp_path: Path):
    """Cause B of the canary: the robustness columns never carried `N`. That
    is a missing number, not a naming problem, and must stay a hard failure —
    descent must not paper over it by borrowing from another column."""
    est = {"main": {"n_pre_treatment": 192}}
    rob = {"rv5_measure": {"specification": "5-day RV", "delta_p_HH": 0.018}}
    (tmp_path / "robustness_results.json").write_text(json.dumps(rob), encoding="utf-8")
    spec = _spec(
        [{"spec_key": "rv5_measure", "header": "(2)"}],
        [{"type": "stat", "field": "n_pre_treatment", "label": "N pre", "decimals": 0}],
    )
    ws = _ws_keys(tmp_path, est, spec)
    report = render_tables(ws)
    assert any(u.kind == "stat" and u.ref == "n_pre_treatment" for u in report.unresolved)
