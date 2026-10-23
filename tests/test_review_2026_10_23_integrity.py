"""The integrity findings of the code review of 2026-10-23: verify and reproduce check what they claim.

Each test is the reviewer's reproduction turned into a regression test.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.cli_verify import FAIL, SKIP, _check_numbers, _check_tables, _reconstruct_workspace, _run_checks

LEFT = {"path": "results/summary_statistics.json", "kind": "terms", "source": "gaia", "reason": "Gaia's terms"}

TWO_SOURCES_TEX = (
    "\\documentclass{article}\\begin{document}\n"
    "See \\cite{smith2021}.\n"
    "\\begin{tabular}{lc}\n"
    "Treatment & 12.5 \\\\\n"
    "Observations & 4321 \\\\\n"
    "\\end{tabular}\n"
    "\\end{document}\n"
)


def _two_sources(tmp_path: Path, estimation: dict | None = None) -> Path:
    """An exported study whose table has a cell from the estimation and one from the summary statistics."""
    from src.core.export.structured import export_paper
    from tests.results_script import write_results_script

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"title": "Two", "paper_id": "p2", "governance": "full"}))
    (ws / "paper_draft.tex").write_text(TWO_SOURCES_TEX)
    (ws / "literature.bib").write_text("@article{smith2021, title={X}, doi={10.1/x}, year={2021}}\n")
    est = estimation or {"main": {"coefficients": {"treat": {"estimate": 12.5}}}}
    (ws / "estimation_results.json").write_text(json.dumps(est))
    (ws / "summary_statistics.json").write_text(json.dumps({"n_obs": 4321}))
    write_results_script(ws)
    from src.core.pipeline.verify_numbers import verify_and_save

    verify_and_save(ws / "paper_draft.tex", ws)  # the run's number check: the cells' sources (provenance edges)
    return export_paper(ws, tmp_path / "out", date_str="20261023")


def _numbers(bundle: Path, left: dict) -> object:
    ws = bundle.parent / "verify-ws"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir()
    _reconstruct_workspace(bundle, ws)
    return _check_numbers(bundle, ws, left)


# ── 3. a left-out results file masks only its own cells ──────────────────────


def test_a_cell_of_a_left_out_file_is_skipped(tmp_path: Path):
    bundle = _two_sources(tmp_path)
    (bundle / "results" / "summary_statistics.json").unlink()
    c = _numbers(bundle, {LEFT["path"]: LEFT})
    assert c.status == SKIP and "summary_statistics.json" in c.detail


def test_a_fabricated_cell_with_a_left_out_file_fails(tmp_path: Path):
    """The reviewer's repro: any results JSON left out turned every numbers failure into a skip."""
    bundle = _two_sources(tmp_path)
    (bundle / "results" / "summary_statistics.json").unlink()
    tex = bundle / "paper" / "paper.tex"
    tex.write_text(tex.read_text().replace("12.5", "20.0"))
    c = _numbers(bundle, {LEFT["path"]: LEFT})
    assert c.status == FAIL and "20.0" in c.detail and "4321" not in c.detail
    checks = {x.name: x for x in _run_checks(bundle, False, {LEFT["path"]: LEFT})}
    assert checks["numbers"].status == FAIL


def test_inconsistent_statistics_fail_whatever_is_left_out(tmp_path: Path):
    bad = {"main": {"coefficients": {"treat": {"estimate": 12.5, "se": 1.0, "t_stat": 3.0, "p_value": 0.01}}}}
    bundle = _two_sources(tmp_path, bad)
    (bundle / "results" / "summary_statistics.json").unlink()
    c = _numbers(bundle, {LEFT["path"]: LEFT})
    assert c.status == FAIL and "p-value/t" in c.detail
    checks = {x.name: x for x in _run_checks(bundle, False, {LEFT["path"]: LEFT})}
    assert checks["numbers"].status == FAIL and "p-value/t" in checks["numbers"].detail


def _tables_ws(tmp_path: Path) -> tuple[Path, Path]:
    from src.core.renderer.tables import render_tables

    bundle, ws = tmp_path / "b", tmp_path / "ws"
    (bundle / "paper" / "tables").mkdir(parents=True)
    ws.mkdir()
    (ws / "estimation_results.json").write_text(json.dumps({"rows": {"a": {"v": 1.25}}}))
    (ws / "summary_statistics.json").write_text(json.dumps({"rows": {"a": {"v": 7.5}}}))
    cols = [{"field": "v", "header": "V", "decimals": 2}]
    tables = [
        {"filename": "est.tex", "layout": "records", "source": "estimation_results.json", "path": "rows",
         "columns": cols},
        {"filename": "sum.tex", "layout": "records", "source": "summary_statistics.json", "path": "rows",
         "columns": cols},
    ]  # fmt: skip
    (ws / "table_spec.json").write_text(json.dumps({"tables": tables}))
    render_tables(ws)
    for name in ("est.tex", "sum.tex"):
        shutil.copy2(ws / "tables" / name, bundle / "paper" / "tables" / name)
    shutil.rmtree(ws / "tables")
    (ws / "summary_statistics.json").unlink()  # left out
    return bundle, ws


def test_a_table_of_a_left_out_file_is_skipped_and_any_other_that_differs_fails(tmp_path: Path):
    bundle, ws = _tables_ws(tmp_path)
    left = {LEFT["path"]: LEFT}
    c = _check_tables(bundle, ws, left)
    assert c.status == SKIP and "summary_statistics.json" in c.detail
    shipped = bundle / "paper" / "tables" / "est.tex"
    shipped.write_text(shipped.read_text().replace("1.25", "9.99"))  # a fabricated cell in another table
    shutil.rmtree(ws / "tables")
    c = _check_tables(bundle, ws, left)
    assert c.status == FAIL and "est.tex" in c.detail and "sum.tex" not in c.detail
