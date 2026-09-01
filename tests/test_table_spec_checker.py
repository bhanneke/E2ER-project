"""Tests for the table_spec checker (`e2er-check-tables`).

The canary-#6 fixture below is the real thing: the `comparison` object is
exactly the five keys `estimation_results.json` carried in paper 8d3d9ce6, and
the spec asks it for the same stat rows the pre/post columns use. That run died
with ten unresolved references and a repair pass that made it worse. The test
that matters is not "the checker returns non-zero" — it is that the checker
prints the five keys that DO exist, because that is the line that ends the
guessing loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.renderer.check_tables import (
    EXIT_CANNOT_CHECK,
    EXIT_OK,
    EXIT_UNRESOLVED,
    check,
    main,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "scripts" / "e2er-check-tables"


# ── fixtures ─────────────────────────────────────────────────────────────────


def _write(ws: Path, name: str, obj) -> None:
    (ws / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")


#: Canary #6's estimation output, trimmed to the fields the spec touches.
CANARY6_ESTIMATION = {
    "pre_etf": {
        "specification": "Regime persistence - pre-ETF",
        "n_observations": 354,
        "p11_persist_high_vol": 0.9333333333333333,
        "expected_duration_high_vol": 15.000000000000004,
        "pct_high_vol_days": 4.237288135593221,
    },
    "post_etf": {
        "specification": "Regime persistence - post-ETF",
        "n_observations": 959,
        "p11_persist_high_vol": 0.9148936170212766,
        "expected_duration_high_vol": 11.749999999999998,
        "pct_high_vol_days": 9.801876955161626,
    },
    # The five keys that actually exist. Every "same rows as the other columns"
    # request against this object is unresolvable by lookup.
    "comparison": {
        "delta_p11": -0.018439716312056764,
        "pct_change_p11": -1.9756838905775105,
        "delta_duration": -3.2500000000000053,
        "pct_change_duration": -21.666666666666696,
        "persistence_declined": True,
    },
}

CANARY6_SPEC = {
    "tables": [
        {
            "filename": "summary_stats.tex",
            "caption": "Regime persistence around the spot-ETF approval",
            "label": "tab:summary",
            "columns": [
                {"spec_key": "pre_etf", "header": "Pre-ETF"},
                {"spec_key": "post_etf", "header": "Post-ETF"},
                {"spec_key": "comparison", "header": "Change"},
            ],
            "rows": [
                {"type": "stat", "label": "Observations", "field": "n_observations", "decimals": 0},
                {"type": "stat", "label": "P(stay high-vol)", "field": "p11_persist_high_vol"},
                {"type": "stat", "label": "Expected duration", "field": "expected_duration_high_vol"},
            ],
        }
    ]
}


@pytest.fixture
def canary6(tmp_path: Path) -> Path:
    _write(tmp_path, "estimation_results.json", CANARY6_ESTIMATION)
    _write(tmp_path, "table_spec.json", CANARY6_SPEC)
    return tmp_path


# ── the canary-#6 case ───────────────────────────────────────────────────────


def test_canary6_spec_is_reported_unresolved(canary6: Path):
    code, text = check(canary6)
    assert code == EXIT_UNRESOLVED
    assert "summary_stats.tex" in text


def test_canary6_report_names_the_offending_column(canary6: Path):
    _, text = check(canary6)
    assert "'comparison'" in text


def test_canary6_report_lists_the_keys_that_do_exist(canary6: Path):
    """The line that would have ended the repair loop."""
    _, text = check(canary6)
    for key in ("delta_p11", "pct_change_p11", "delta_duration", "pct_change_duration", "persistence_declined"):
        assert key in text, f"the report must show the author that {key} exists"


def test_canary6_report_explains_that_the_renderer_does_not_compute(canary6: Path):
    _, text = check(canary6)
    assert "never" in text and "computes" in text


def test_canary6_only_the_comparison_column_is_unresolved(canary6: Path):
    """pre_etf and post_etf carry all three fields, so they must not be flagged
    — a checker that blames resolvable columns sends the author to the wrong file."""
    _, text = check(canary6)
    body = text.split("The renderer LOOKS UP")[0]
    assert "'pre_etf'" not in body
    assert "'post_etf'" not in body


# ── the passing case ─────────────────────────────────────────────────────────


def test_fully_resolvable_spec_exits_ok(tmp_path: Path):
    _write(tmp_path, "estimation_results.json", CANARY6_ESTIMATION)
    spec = json.loads(json.dumps(CANARY6_SPEC))
    spec["tables"][0]["columns"] = [
        {"spec_key": "pre_etf", "header": "Pre-ETF"},
        {"spec_key": "post_etf", "header": "Post-ETF"},
    ]
    _write(tmp_path, "table_spec.json", spec)

    code, text = check(tmp_path)
    assert code == EXIT_OK
    assert text.startswith("OK")
    assert "summary_stats.tex" in text


def test_repaired_comparison_column_exits_ok(canary6: Path):
    """The fix the checker is steering toward: ask the comparison object for
    keys it actually has."""
    spec = json.loads(json.dumps(CANARY6_SPEC))
    spec["tables"][0]["columns"] = [{"spec_key": "comparison", "header": "Change"}]
    spec["tables"][0]["rows"] = [
        {"type": "stat", "label": "Delta P(stay)", "field": "delta_p11"},
        {"type": "stat", "label": "Delta duration", "field": "delta_duration"},
    ]
    _write(canary6, "table_spec.json", spec)

    code, _ = check(canary6)
    assert code == EXIT_OK


# ── other unresolved kinds ───────────────────────────────────────────────────


def test_unknown_spec_key_lists_the_available_ones(tmp_path: Path):
    _write(tmp_path, "estimation_results.json", CANARY6_ESTIMATION)
    spec = json.loads(json.dumps(CANARY6_SPEC))
    spec["tables"][0]["columns"] = [{"spec_key": "during_etf", "header": "During"}]
    _write(tmp_path, "table_spec.json", spec)

    code, text = check(tmp_path)
    assert code == EXIT_UNRESOLVED
    assert "during_etf" in text
    assert "available spec keys" in text
    assert "pre_etf" in text and "comparison" in text


def test_unknown_coefficient_lists_that_specs_coefficients(tmp_path: Path):
    _write(
        tmp_path,
        "estimation_results.json",
        {
            "main": {
                "specification": "OLS baseline",
                "coefficients": {
                    "post_etf": {"estimate": 0.12, "se": 0.03, "p_value": 0.001},
                    "log_volume": {"estimate": -0.4, "se": 0.1, "p_value": 0.02},
                },
            }
        },
    )
    _write(
        tmp_path,
        "table_spec.json",
        {
            "tables": [
                {
                    "filename": "main.tex",
                    "columns": [{"spec_key": "main", "header": "(1)"}],
                    "rows": [{"type": "coefficient", "label": "Treatment", "var": "etf_dummy"}],
                }
            ]
        },
    )

    code, text = check(tmp_path)
    assert code == EXIT_UNRESOLVED
    assert "etf_dummy" in text
    # The coefficient branch keys off the spec's `specification` label, not its
    # spec_key — the checker must still find and list the real coefficients.
    assert "post_etf" in text and "log_volume" in text


def test_stat_row_with_no_field_is_named_as_its_own_defect(tmp_path: Path):
    """Canary #6's main.tex carried four rows with `"field": ""` — malformed
    rows the repair pass emitted and nothing rejects. Reporting them as a
    missing field named "(empty)" tells the author nothing."""
    _write(tmp_path, "estimation_results.json", CANARY6_ESTIMATION)
    _write(
        tmp_path,
        "table_spec.json",
        {
            "tables": [
                {
                    "filename": "main.tex",
                    "columns": [{"spec_key": "pre_etf", "header": "Pre"}],
                    "rows": [
                        {"type": "stat", "label": "Orphan", "field": ""},
                        {"type": "stat", "label": "Another", "field": ""},
                    ],
                }
            ]
        },
    )

    code, text = check(tmp_path)
    assert code == EXIT_UNRESOLVED
    assert "2 stat row(s) declare no 'field' at all" in text
    assert "(empty)" not in text


# ── degenerate inputs ────────────────────────────────────────────────────────


def test_missing_spec_cannot_be_checked(tmp_path: Path):
    code, text = check(tmp_path)
    assert code == EXIT_CANNOT_CHECK
    assert "could not be checked" in text


def test_unparseable_spec_cannot_be_checked(tmp_path: Path):
    (tmp_path / "table_spec.json").write_text("{not json", encoding="utf-8")
    code, text = check(tmp_path)
    assert code == EXIT_CANNOT_CHECK
    assert "could not be checked" in text


def test_spec_without_tables_list_cannot_be_checked(tmp_path: Path):
    _write(tmp_path, "table_spec.json", {"note": "no tables here"})
    code, text = check(tmp_path)
    assert code == EXIT_CANNOT_CHECK


def test_spec_with_no_sidecars_at_all_is_unresolved_not_ok(tmp_path: Path):
    """No estimation JSON means nothing resolves. It must not read as a pass."""
    _write(tmp_path, "table_spec.json", CANARY6_SPEC)
    code, _ = check(tmp_path)
    assert code != EXIT_OK


def test_check_never_raises_on_a_hostile_spec(tmp_path: Path):
    _write(tmp_path, "estimation_results.json", CANARY6_ESTIMATION)
    _write(
        tmp_path,
        "table_spec.json",
        {"tables": [{"filename": "../escape.tex", "columns": "not-a-list", "rows": 7}, "not-an-object"]},
    )
    code, text = check(tmp_path)
    assert code in (EXIT_OK, EXIT_UNRESOLVED)
    assert isinstance(text, str)


# ── entry point ──────────────────────────────────────────────────────────────


def test_main_rejects_extra_arguments(canary6: Path):
    assert main([str(canary6), "--and-something-else"]) == EXIT_CANNOT_CHECK


def test_main_returns_the_check_exit_code(canary6: Path):
    assert main([str(canary6)]) == EXIT_UNRESOLVED


# ── the real wrapper script ──────────────────────────────────────────────────


@pytest.mark.skipif(not WRAPPER.exists(), reason="wrapper not present")
def test_wrapper_rejects_arguments(tmp_path: Path):
    proc = subprocess.run(
        [str(WRAPPER), "table_spec.json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2
    assert "takes no arguments" in proc.stderr


@pytest.mark.skipif(not WRAPPER.exists(), reason="wrapper not present")
def test_wrapper_checks_the_directory_it_was_called_from(canary6: Path):
    """End-to-end: cwd is the workspace, and the wrapper must resolve the
    project root from its own path rather than from cwd."""
    env = dict(os.environ, E2ER_PYTHON=sys.executable)
    proc = subprocess.run(
        [str(WRAPPER)],
        cwd=canary6,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == EXIT_UNRESOLVED, proc.stderr
    assert "comparison" in proc.stdout
    assert "delta_p11" in proc.stdout
