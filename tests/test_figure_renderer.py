"""Deterministic figure rendering from figure_spec.json → PDF files."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.renderer.figures import ensure_figure_placeholders, render_figures


def _spec(tmp_path: Path, figures: list[dict]) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "figure_spec.json").write_text(json.dumps({"figures": figures}))
    return ws


def _is_pdf(p: Path) -> bool:
    return p.is_file() and p.read_bytes()[:4] == b"%PDF"


def test_renders_all_three_figure_types(tmp_path: Path):
    ws = _spec(
        tmp_path,
        [
            {
                "filename": "fig_coef.pdf",
                "figure_type": "coefficient",
                "coefficients": [
                    {"name": "Effective rate", "estimate": -1.35, "ci_lower": -1.49, "ci_upper": -1.21},
                    {"name": "Pays any", "estimate": -15.7, "ci_lower": -17.7, "ci_upper": -13.8},
                ],
                "reference_line": 0,
                "x_label": "pp",
            },
            {
                "filename": "fig_event.pdf",
                "figure_type": "event_study",
                "periods": [-1, 0, 1],
                "estimates": [0.05, -1.5, -1.44],
                "ci_lower": [-0.13, -1.65, -1.66],
                "ci_upper": [0.24, -1.35, -1.22],
                "treatment_period": 0,
                "x_label": "q",
                "y_label": "pp",
            },
            {
                "filename": "fig_bar.pdf",
                "figure_type": "bar",
                "categories": ["Direct", "Gem/Genie", "Blur", "Routed"],
                "values": [15.56, 18.78, 28.06, 23.93],
                "y_label": "% zero royalty",
            },
        ],
    )
    report = render_figures(ws)
    assert set(report.rendered) == {"fig_coef.pdf", "fig_event.pdf", "fig_bar.pdf"}
    assert not report.skipped and not report.errors
    for name in ("fig_coef.pdf", "fig_event.pdf", "fig_bar.pdf"):
        assert _is_pdf(ws / name)
    # idempotent
    report2 = render_figures(ws)
    assert set(report2.rendered) == set(report.rendered)


def test_unknown_type_is_skipped_not_fatal(tmp_path: Path):
    ws = _spec(tmp_path, [{"filename": "x.pdf", "figure_type": "heatmap"}])
    report = render_figures(ws)
    assert report.rendered == []
    assert any("heatmap" in s for s in report.skipped)


def test_missing_data_skipped_not_fatal(tmp_path: Path):
    ws = _spec(tmp_path, [{"filename": "bad.pdf", "figure_type": "bar", "categories": ["a"], "values": "nope"}])
    report = render_figures(ws)
    assert "bad.pdf" not in report.rendered
    assert any("bad.pdf" in s for s in report.skipped)


def test_invalid_filename_reported(tmp_path: Path):
    bad = [{"filename": "sub/dir.pdf", "figure_type": "bar"}, {"filename": "x.png", "figure_type": "bar"}]
    ws = _spec(tmp_path, bad)
    report = render_figures(ws)
    assert len(report.errors) == 2
    assert report.rendered == []


def test_no_spec_returns_skipped_reason(tmp_path: Path):
    ws = tmp_path / "empty"
    ws.mkdir()
    report = render_figures(ws)
    assert report.skipped_reason and "no figure_spec.json" in report.skipped_reason


def test_placeholder_for_missing_referenced_figure(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "paper_draft.tex").write_text(
        r"\includegraphics[width=0.7\textwidth]{fig_present.pdf}" "\n" r"\includegraphics{fig_missing.pdf}"
    )
    # one figure already exists; the other must be stubbed
    (ws / "fig_present.pdf").write_bytes(b"%PDF-1.4 real")
    created = ensure_figure_placeholders(ws)
    assert created == ["fig_missing.pdf"]
    assert _is_pdf(ws / "fig_missing.pdf")
    assert (ws / "fig_present.pdf").read_bytes() == b"%PDF-1.4 real"  # untouched
