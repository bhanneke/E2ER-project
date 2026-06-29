"""Structured export: artifact→folder mapping, versioned slug, README, best-effort."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.export.structured import export_paper, resolve_versioned_slug, slugify


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws-uuid"
    ws.mkdir()
    (ws / "manifest.json").write_text(
        json.dumps({"title": "Routing Around Royalties", "research_question": "Did aggregators erode royalties?"})
    )
    (ws / "paper_draft.tex").write_text("\\documentclass{article}\\begin{document}hi\\end{document}")
    (ws / "abstract.tex").write_text("We study royalties.")
    (ws / "literature.bib").write_text("@article{x2024, title={X}}")
    (ws / "run_estimation.py").write_text("import pandas as pd")
    (ws / "_explore.py").write_text("# probe")
    (ws / "run_estimation.log").write_text("ran ok")
    (ws / "data.db").write_bytes(b"SQLite format 3\x00")
    (ws / "data_summary.md").write_text("rows: 2.1M")
    (ws / "estimation_results.json").write_text(
        json.dumps({"main": {"coefficients": {"aggregator_routed": {"estimate": -0.0087, "p_value": 0.43}}}})
    )
    (ws / "identification_strategy.md").write_text("DiD around Oct 2022")
    (ws / "review_mechanism.md").write_text("# Referee\nContribution: 4/10")
    (ws / "review_aggregation.json").write_text(
        json.dumps({"verdict": "MECHANISM_FAIL", "weighted_avg": 4.0, "rationale": "proxy too weak"})
    )
    (ws / ".pipeline_state.json").write_text("{}")  # internal — must not be exported
    return ws


def test_slugify():
    assert slugify("Routing Around Royalties!") == "routing-around-royalties"
    assert slugify("   ") == "paper"


def test_versioned_slug_increments(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    s1 = resolve_versioned_slug(root, "My Paper", "20260627")
    assert s1 == "my-paper-20260627-01"
    (root / s1).mkdir()
    assert resolve_versioned_slug(root, "My Paper", "20260627") == "my-paper-20260627-02"


def test_export_builds_structured_tree(tmp_path: Path):
    ws = _workspace(tmp_path)
    out = export_paper(ws, tmp_path / "out", date_str="20260627")

    assert out.name == "routing-around-royalties-20260627-01"
    assert (out / "paper" / "paper.tex").is_file()  # renamed from paper_draft.tex
    assert (out / "paper" / "abstract.tex").is_file()
    assert (out / "paper" / "refs.bib").is_file()  # renamed from literature.bib
    assert (out / "code" / "run_estimation.py").is_file()
    assert (out / "code" / "scratch" / "_explore.py").is_file()
    assert (out / "code" / "scratch" / "run_estimation.log").is_file()
    assert (out / "data" / "data.db").is_file()
    assert (out / "results" / "estimation_results.json").is_file()
    assert (out / "design" / "identification_strategy.md").is_file()
    assert (out / "reviews" / "review_mechanism.md").is_file()
    assert (out / "reviews" / "review_aggregation.json").is_file()
    assert (out / "README.md").is_file()


def test_readme_has_verdict_and_coef(tmp_path: Path):
    ws = _workspace(tmp_path)
    out = export_paper(ws, tmp_path / "out", date_str="20260627")
    readme = (out / "README.md").read_text()
    assert "Routing Around Royalties" in readme
    assert "MECHANISM_FAIL" in readme
    assert "aggregator_routed" in readme  # headline estimate table


def test_internal_files_not_exported(tmp_path: Path):
    ws = _workspace(tmp_path)
    out = export_paper(ws, tmp_path / "out", date_str="20260627")
    # .pipeline_state.json (dotfile) and manifest.json must not leak into misc/
    assert not (out / "misc" / ".pipeline_state.json").exists()
    assert not (out / "misc" / "manifest.json").exists()


def test_best_effort_on_missing_artifacts(tmp_path: Path):
    ws = tmp_path / "sparse"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"title": "Sparse"}))
    (ws / "review_aggregation.json").write_text(json.dumps({"verdict": "REJECTED"}))
    # No paper/code/data at all — export must still succeed (rejected-run case).
    out = export_paper(ws, tmp_path / "out", date_str="20260627")
    assert out.is_dir()
    assert (out / "README.md").is_file()
    assert (out / "reviews" / "review_aggregation.json").is_file()
