"""Export copies the study's data folder, keeps hidden folders out, and says when an output was too large.

Review of 2026-10-23:
* files under workspace/data/ (e2er-data --save-to files, the researcher's own files) were copied only by
  the recipe, and only when a script named them: a systematic review, a field map or a run whose recipe
  failed shipped data_sources.json naming files the folder lacked;
* export checked only a file's own name, so sandbox/run/.cache/x.json was exported and listed, and pack
  (which drops every path with a hidden folder) then lacked a listed file;
* a reproduction output over 200 MB was dropped with a log line only, and verify failed with no reason in
  the folder.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.core.export import structured
from src.core.export.structured import export_paper


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "data" / "raw").mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": "p1", "title": "A review", "pipeline": "systematic-review"}),
        encoding="utf-8",
        newline="\n",
    )
    (ws / "data" / "fred_gdp.csv").write_text("date,gdp\n2020,1\n", encoding="utf-8", newline="\n")
    (ws / "data" / "raw" / "mine.csv").write_text("a\n1\n", encoding="utf-8", newline="\n")
    (ws / "data" / "gaia.csv").write_text("source_id\n1\n", encoding="utf-8", newline="\n")
    (ws / "data" / ".hidden.csv").write_text("x\n", encoding="utf-8", newline="\n")
    (ws / "data" / "notes.csv~").write_text("x\n", encoding="utf-8", newline="\n")
    loads = [
        {"connector": "fred", "series": "GDP", "saved_to": "data/fred_gdp.csv"},
        {"connector": "gaia", "series": "q", "saved_to": "data/gaia.csv"},
        {"connector": "data-folder", "series": "mine", "files": [{"path": "data/raw/mine.csv"}]},
    ]
    (ws / "data_sources.json").write_text(json.dumps({"loads": loads}), encoding="utf-8", newline="\n")
    return ws


def test_the_data_folder_is_exported_without_restricted_hidden_or_leftover_files(tmp_path: Path):
    out = export_paper(_workspace(tmp_path), tmp_path / "exports", date_str="20261023")
    assert (out / "data" / "fred_gdp.csv").is_file()
    assert (out / "data" / "raw" / "mine.csv").is_file()
    assert not (out / "data" / "gaia.csv").exists(), "a source whose terms keep its rows out"
    assert not (out / "data" / ".hidden.csv").exists() and not (out / "data" / "notes.csv~").exists()
    prov = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert "data/fred_gdp.csv" in prov["files"] and "data/raw/mine.csv" in prov["files"]


def test_a_link_out_of_the_workspace_is_copied_only_when_the_run_recorded_it(tmp_path: Path):
    ws = _workspace(tmp_path)
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("secret\n", encoding="utf-8", newline="\n")
    (ws / "data" / "linked.csv").symlink_to(outside)
    out = export_paper(ws, tmp_path / "exports", date_str="20261023")
    assert not (out / "data" / "linked.csv").exists()
    doc = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(outside.read_bytes()).hexdigest()
    doc["loads"].append({"connector": "data-folder", "files": [{"path": "data/linked.csv", "sha256": sha}]})
    (ws / "data_sources.json").write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    out2 = export_paper(ws, tmp_path / "exports", date_str="20261023")
    assert (out2 / "data" / "linked.csv").read_text(encoding="utf-8") == "secret\n"


def _reproduction_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "rws"
    run = ws / "sandbox" / "run"
    (run / ".cache").mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": "p2", "title": "A replication"}), encoding="utf-8", newline="\n"
    )
    (run / "results.json").write_text('{"b": 1}', encoding="utf-8", newline="\n")
    (run / "big.csv").write_text("x\n" * 1000, encoding="utf-8", newline="\n")
    (run / ".cache" / "x.json").write_text("{}", encoding="utf-8", newline="\n")
    outputs = [{"path": p, "written_by_run": True} for p in ("results.json", "big.csv", ".cache/x.json")]
    (ws / "sandbox_log.json").write_text(
        json.dumps({"run_dir": "sandbox/run", "outputs": outputs}), encoding="utf-8", newline="\n"
    )
    (ws / "reproduction_report.json").write_text(json.dumps({"results": []}), encoding="utf-8", newline="\n")
    return ws


def test_a_file_in_a_hidden_folder_is_not_exported(tmp_path: Path):
    out = export_paper(_reproduction_workspace(tmp_path), tmp_path / "exports", date_str="20261023")
    assert (out / "sandbox" / "run" / "results.json").is_file()
    assert not (out / "sandbox" / "run" / ".cache").exists()
    assert not any(".cache" in k for k in json.loads((out / "provenance.json").read_text(encoding="utf-8"))["files"])


def test_a_reproduction_output_too_large_is_recorded_as_left_out(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(structured, "MAX_OUTPUT_BYTES", 500)
    out = export_paper(_reproduction_workspace(tmp_path), tmp_path / "exports", date_str="20261023")
    assert not (out / "sandbox" / "run" / "big.csv").exists()
    [item] = json.loads((out / "provenance.json").read_text(encoding="utf-8"))["run"]["left_out"]
    assert item["path"] == "sandbox/run/big.csv" and item["kind"] == "size" and item["bytes"] == 2000
    assert "`sandbox/run/big.csv`" in (out / "README.md").read_text(encoding="utf-8")
