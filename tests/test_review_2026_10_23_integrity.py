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


# ── 4. a package's declarations are not taken on its word ────────────────────


def test_a_package_that_declares_a_results_file_left_out_without_support_fails(tmp_path: Path, monkeypatch, capsys):
    """The reviewer's repro: a .e2er whose manifest declares results/estimation_results.json left out (under
    terms no record of the study's names) verified with the file missing."""
    import zipfile

    from src.cli_verify import verify
    from src.core.export import package as pkg
    from tests.test_package import _export

    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    folder = _export(tmp_path)
    packed = pkg.build(folder, tmp_path / "s.e2er")
    forged = tmp_path / "forged.e2er"
    rel = "results/estimation_results.json"
    with zipfile.ZipFile(packed.path) as src, zipfile.ZipFile(forged, "w") as dst:
        for info in src.infolist():
            name = info.filename
            if name.endswith(rel):
                continue
            data = src.read(info)
            if name.endswith(pkg.MANIFEST):
                doc = json.loads(data)
                doc["contents"] = [c for c in doc["contents"] if c["path"] != rel]
                doc.setdefault("left_out", []).append(
                    {"path": rel, "kind": "terms", "source": "gaia", "reason": "under Gaia's terms"}
                )
                doc["fingerprint"] = pkg.fingerprint(doc["contents"])
                data = json.dumps(doc).encode()
            dst.writestr(info, data)
    capsys.readouterr()
    code = verify(str(forged))
    out = capsys.readouterr().out + capsys.readouterr().err
    assert code == 1 and "[FAIL] integrity" in out, out
    assert "declared left out by e2er-package.json" in out and "estimation_results.json" in out


# ── 5. reproduce checks the folder first ─────────────────────────────────────


def _exported_study(tmp_path: Path) -> Path:
    from src.core.export.provenance import write_provenance
    from tests.test_reproduce import _study

    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    write_provenance(folder, {"paper_id": "p5", "governance": "full"}, exported_at="20261023")
    return folder


def test_reproduce_runs_the_study_as_exported(tmp_path: Path, capsys):
    from src.cli_reproduce import reproduce

    folder = _exported_study(tmp_path)
    assert reproduce(str(folder), yes=True, sandbox=False) == 0
    out = capsys.readouterr().out
    assert "Reproduced: every compared value is identical" in out and "no provenance.json" not in out


def test_reproduce_refuses_an_edited_recipe(tmp_path: Path, capsys):
    """The reviewer's repro: reproduce.json edited after export (another step, another compared file) ran and
    reported "Reproduced"."""
    from src.cli_reproduce import reproduce

    folder = _exported_study(tmp_path)
    recipe = json.loads((folder / "reproduce.json").read_text())
    recipe["steps"][0]["about"] = "something else"
    (folder / "reproduce.json").write_text(json.dumps(recipe))
    assert reproduce(str(folder), yes=True, sandbox=False) == 2
    out = capsys.readouterr().out
    assert "not the study as exported" in out and "reproduce.json" in out and "Reproduced" not in out


def test_reproduce_refuses_an_unlisted_recipe_and_edited_results(tmp_path: Path, capsys):
    from src.cli_reproduce import reproduce

    folder = _exported_study(tmp_path)
    prov = json.loads((folder / "provenance.json").read_text())
    del prov["files"]["reproduce.json"]
    (folder / "provenance.json").write_text(json.dumps(prov))
    assert reproduce(str(folder), yes=True, sandbox=False) == 2
    assert "unlisted (reproduce.json)" in capsys.readouterr().out


def test_reproduce_of_a_folder_without_provenance_says_so(tmp_path: Path, capsys):
    from src.cli_reproduce import reproduce
    from tests.test_reproduce import _study

    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    assert reproduce(str(folder), yes=True, sandbox=False) == 0
    out = capsys.readouterr().out
    assert "no provenance.json, so nothing ties its files" in out and "Reproduced:" in out


# ── 6. reproduce renders the tables from the rerun's outputs only ────────────


def _tables_study(tmp_path: Path) -> tuple[Path, Path]:
    from src.core.renderer.tables import render_tables

    folder, run_dir = tmp_path / "study", tmp_path / "run"
    (folder / "results").mkdir(parents=True)
    (folder / "paper" / "tables").mkdir(parents=True)
    run_dir.mkdir()
    cols = [{"field": "v", "header": "V", "decimals": 2}]
    tables = [
        {"filename": "est.tex", "layout": "records", "source": "estimation_results.json", "path": "rows",
         "columns": cols},
        {"filename": "sum.tex", "layout": "records", "source": "summary_statistics.json", "path": "rows",
         "columns": cols},
    ]  # fmt: skip
    (folder / "results" / "table_spec.json").write_text(json.dumps({"tables": tables}))
    (folder / "results" / "estimation_results.json").write_text(json.dumps({"rows": {"a": {"v": 1.25}}}))
    (folder / "results" / "summary_statistics.json").write_text(json.dumps({"rows": {"a": {"v": 7.5}}}))
    scratch = tmp_path / "scratch"
    shutil.copytree(folder / "results", scratch)
    render_tables(scratch)
    for name in ("est.tex", "sum.tex"):
        shutil.copy2(scratch / "tables" / name, folder / "paper" / "tables" / name)
    (run_dir / "estimation_results.json").write_text(json.dumps({"rows": {"a": {"v": 1.25}}}))
    return folder, run_dir


def test_a_table_whose_results_were_not_rerun_is_not_compared(tmp_path: Path):
    """The reviewer's repro: the published summary_statistics.json was copied in, so its table "rendered the same"
    although the rerun never wrote it."""
    from src.core import reproduce as rp

    folder, run_dir = _tables_study(tmp_path)
    compare = [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}]
    out = rp.compare_tables(folder, run_dir, compare)
    assert out is not None
    assert out["identical"] == ["est.tex"] and out["not_compared"] == ["sum.tex"] and out["rendered"] == 1
    fc = rp.compare_json(folder / "results" / "estimation_results.json", run_dir / "estimation_results.json", "e", "e")
    text, code = rp.verdict([fc], out, [])
    assert code == 0 and "1 table(s) not compared" in text and "sum.tex" in text


# ── 8. a whole number is not a rounded one ───────────────────────────────────


def test_a_whole_number_float_must_match_exactly():
    """The reviewer's repro: 1234.0 published, 1234.4 rerun read as "the same at the published precision"."""
    from src.core import reproduce as rp

    assert rp.compare_value(1234.0, 1234.4)[0] != rp.AT_PRECISION
    assert rp.compare_value(4321.0, 4321.0)[0] == rp.IDENTICAL
    assert rp.compare_value(1234.5678, 1234.56781)[0] == rp.AT_PRECISION
