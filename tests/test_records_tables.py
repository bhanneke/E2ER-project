"""Tables and figures for results that are not regression columns (0.16.0).

A ``records`` table has entries of the results as rows: variables, bins,
categories, forecast periods, spatial statistics, terms. Code fills every cell
by lookup, as for the regression layout; what does not resolve is reported.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.renderer.check_tables import check
from src.core.renderer.figures import render_figures
from src.core.renderer.tables import render_tables

RESULTS = {
    "result_kind": "timeseries",
    "forecasts": {
        "f": {
            "model": "m",
            "points": [
                {"period": "2025-01", "forecast": 1.94, "lower": -0.8, "upper": 4.6},
                {"period": "2025-02", "forecast": 2.7, "lower": -0.4, "upper": 5.8},
            ],
        }
    },
    "out_of_sample": {"arima_test": {"model": "m", "rmse": 1.41, "mae": 1.12, "n_test": 36}},
}


def _spec(ws: Path, *tables: dict) -> None:
    (ws / "table_spec.json").write_text(json.dumps({"tables": list(tables)}), encoding="utf-8")


def test_rows_are_entries_of_a_list_named_by_their_key_field(tmp_path: Path):
    (tmp_path / "estimation_results.json").write_text(json.dumps(RESULTS))
    _spec(
        tmp_path,
        {
            "filename": "fc.tex",
            "label": "tab:fc",
            "caption": "Forecasts",
            "layout": "records",
            "path": "forecasts.f.points",
            "key_field": "period",
            "row_header": "Month",
            "columns": [
                {"field": "forecast", "header": "Forecast", "decimals": 2},
                {"field": "lower", "header": "Lower", "decimals": 1},
                {"field": "upper", "header": "Upper", "decimals": 1},
            ],
        },
    )
    report = render_tables(tmp_path)
    assert report.rendered == ["fc.tex"] and not report.unresolved
    tex = (tmp_path / "tables" / "fc.tex").read_text(encoding="utf-8")
    assert "Month & Forecast & Lower & Upper \\\\" in tex
    assert "2025-01 & 1.94 & -0.8 & 4.6 \\\\" in tex and "2025-02 & 2.70 & -0.4 & 5.8 \\\\" in tex


def test_rows_of_an_object_with_labels_text_cells_and_a_chosen_order(tmp_path: Path):
    stats = {
        "statistics": {
            "radius_earth": {"n": 60, "mean": 3.8088, "unit": "R_E"},
            "period_days": {"n": 60, "mean": 46.1622},
        }
    }
    (tmp_path / "summary_statistics.json").write_text(json.dumps(stats))
    _spec(
        tmp_path,
        {
            "filename": "s.tex",
            "layout": "records",
            "source": "summary_statistics.json",
            "path": "statistics",
            "rows": ["period_days", "radius_earth"],
            "row_labels": {"radius_earth": "Radius ($R_\\oplus$)"},
            "columns": [{"field": "n", "decimals": 0}, {"field": "mean", "decimals": 2}, {"field": "unit"}],
        },
    )
    report = render_tables(tmp_path)
    tex = (tmp_path / "tables" / "s.tex").read_text(encoding="utf-8")
    assert tex.index("period\\_days & 60 & 46.16 & --- \\\\") < tex.index(
        "Radius ($R_\\oplus$) & 60 & 3.81 & R\\_E \\\\"
    )
    assert [(u.kind, u.ref, u.column) for u in report.unresolved] == [("field", "unit", "period_days")]


def test_what_does_not_resolve_is_reported_with_what_to_do(tmp_path: Path):
    (tmp_path / "estimation_results.json").write_text(json.dumps(RESULTS))
    _spec(
        tmp_path,
        {"filename": "a.tex", "layout": "records", "path": "forecasts.g.points", "columns": [{"field": "forecast"}]},
        {
            "filename": "b.tex",
            "layout": "records",
            "path": "out_of_sample",
            "rows": ["arima_test", "naive_test"],
            "columns": [{"field": "rmse"}],
        },
        {"filename": "c.tex", "layout": "records", "source": "../secrets.json", "path": "x", "columns": []},
    )
    code, text = check(tmp_path)
    assert code == 1
    assert "path not found" in text and "forecasts.g.points" in text
    assert "rows not found under 'out_of_sample': naive_test" in text
    assert "source not readable by a records table: ../secrets.json" in text


def test_the_regression_layout_is_unchanged_beside_records_tables(tmp_path: Path):
    res = {
        "main": {
            "coefficients": {"x": {"estimate": 0.5, "se": 0.1, "p_value": 0.001}},
            "diagnostics": {"n_observations": 100},
        }
    }
    (tmp_path / "estimation_results.json").write_text(json.dumps(res))
    _spec(
        tmp_path,
        {
            "filename": "m.tex",
            "columns": [{"spec_key": "main", "header": "(1)"}],
            "rows": [
                {"type": "coefficient", "var": "x", "label": "$x$"},
                {"type": "stat", "field": "n_observations", "label": "$N$", "decimals": 0},
            ],
        },
    )
    assert not render_tables(tmp_path).unresolved
    tex = (tmp_path / "tables" / "m.tex").read_text(encoding="utf-8")
    assert "$x$ & 0.500*** \\\\" in tex and " & (0.100) \\\\" in tex and "$N$ & 100 \\\\" in tex


def test_scatter_and_histogram_figures_render(tmp_path: Path):
    spec = {
        "figures": [
            {
                "filename": "fig_s.pdf",
                "figure_type": "scatter",
                "x": [1, 10, 100],
                "y": [1.2, 2.5, 11.0],
                "groups": ["a", "a", "b"],
                "log_x": True,
            },
            {
                "filename": "fig_h.pdf",
                "figure_type": "histogram",
                "bins": [{"lower": 0.5, "upper": 1.0, "count": 3}, {"lower": 1.0, "upper": 2.0, "count": 5}],
            },
            {"filename": "fig_bad.pdf", "figure_type": "histogram", "bins": [{"lower": 1}]},
        ]
    }
    (tmp_path / "figure_spec.json").write_text(json.dumps(spec))
    report = render_figures(tmp_path)
    assert report.rendered == ["fig_s.pdf", "fig_h.pdf"]
    assert (tmp_path / "fig_s.pdf").read_bytes()[:4] == b"%PDF" and (tmp_path / "fig_h.pdf").is_file()
    assert report.skipped and report.skipped[0].startswith("fig_bad.pdf")


def test_e2er_verify_adds_a_results_contract_check_only_for_a_kind_other_than_regression(tmp_path: Path):
    from src.cli_verify import _check_results_contract

    (tmp_path / "estimation_results.json").write_text(json.dumps({"main": {"coefficients": {}}}))
    assert _check_results_contract(tmp_path) is None
    (tmp_path / "estimation_results.json").write_text(json.dumps(RESULTS))
    c = _check_results_contract(tmp_path)
    assert c is not None and c.status == "FAIL" and c.detail.startswith("timeseries: ")
