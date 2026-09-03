"""Provenance manifest (WS-P4.1).

provenance.json content-addresses every bundle file and reconstructs a
derivation graph from the gate reports. It is the backbone `e2er verify`
re-checks offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.export.provenance import (
    PROVENANCE_FILE,
    _source_key_file,
    build_provenance,
    inventory,
    write_provenance,
)

MANIFEST = {
    "paper_id": "p1",
    "title": "T",
    "backend": "claude_code",
    "model": "sonnet",
    "governance": "off",
}


def _bundle(tmp_path: Path) -> Path:
    """A synthetic export bundle with the report files the edge derivation reads."""
    b = tmp_path / "bundle"
    (b / "paper").mkdir(parents=True)
    (b / "paper" / "paper.tex").write_text("\\cite{smith2021}")
    (b / "results" / "figures").mkdir(parents=True)
    (b / "results" / "estimation_results.json").write_text(
        json.dumps({"main": {"coefficients": {"treat": {"estimate": 0.042}}}})
    )
    (b / "results" / "number_verification.json").write_text(
        json.dumps(
            {
                "matched": 1,
                # source_key uses verify_numbers' real convention: the source
                # FILENAME is the flatten prefix (pinned by
                # test_source_key_convention_matches_verify_numbers below).
                "matched_cells": [
                    {
                        "draft_value": "0.042",
                        "source_key": "estimation_results.json.main.coefficients.treat.estimate",
                        "table_context": "T1",
                    }
                ],
            }
        )
    )
    (b / "results" / "figure_spec.json").write_text(json.dumps({"figures": []}))
    (b / "results" / "figures" / "fig1.pdf").write_bytes(b"%PDF")
    (b / "reviews").mkdir()
    (b / "reviews" / "citation_integrity.json").write_text(
        json.dumps(
            {
                "checks": [
                    {"cite_key": "smith2021", "status": "verified_doi", "verifier": "openalex", "matched_doi": "10.1/x"}
                ]
            }
        )
    )
    (b / "code" / "scratch").mkdir(parents=True)
    (b / "code" / "run_estimation.py").write_text("import pandas")
    (b / "code" / "scratch" / "run_estimation.log").write_text("ok")
    (b / "data").mkdir()
    (b / "data" / "data.db").write_bytes(b"SQLite format 3\x00")
    (b / "replication").mkdir()
    (b / "replication" / "data_queries.sql").write_text("SELECT 1;")
    return b


# ── inventory ────────────────────────────────────────────────────────────────


def test_inventory_hashes_every_file(tmp_path: Path):
    b = _bundle(tmp_path)
    files = inventory(b)
    assert "paper/paper.tex" in files
    assert "data/data.db" in files
    assert "results/figures/fig1.pdf" in files
    for meta in files.values():
        assert len(meta["sha256"]) == 64
        assert meta["bytes"] >= 0


def test_inventory_excludes_provenance_itself(tmp_path: Path):
    b = _bundle(tmp_path)
    (b / PROVENANCE_FILE).write_text("{}")
    assert PROVENANCE_FILE not in inventory(b)


def test_inventory_is_deterministic(tmp_path: Path):
    b = _bundle(tmp_path)
    assert inventory(b) == inventory(b)


# ── edges ────────────────────────────────────────────────────────────────────


def test_edges_cover_every_applicable_type(tmp_path: Path):
    b = _bundle(tmp_path)
    prov = build_provenance(b, MANIFEST, exported_at="20260627")
    kinds = {e["type"] for e in prov["edges"]}
    assert kinds == {"table_cell", "citation", "figure", "estimation", "data"}


def test_table_cell_edge_attributes_source_file(tmp_path: Path):
    b = _bundle(tmp_path)
    prov = build_provenance(b, MANIFEST, exported_at="20260627")
    cell = next(e for e in prov["edges"] if e["type"] == "table_cell")
    assert cell["cell_value"] == "0.042"
    assert cell["source_key"] == "estimation_results.json.main.coefficients.treat.estimate"
    assert cell["source"] == "results/estimation_results.json"


def test_source_key_convention_matches_verify_numbers(tmp_path: Path):
    """Pin the contract between the two modules: provenance resolves a cell's
    source by matching the filename PREFIX in the key, so the key format
    verify_numbers actually writes must stay prefixed. (An earlier version
    re-flattened without the prefix and nulled every cell's source.)"""
    from src.core.pipeline.verify_numbers import verify as verify_numbers

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"coefficients": {"treat": {"estimate": 0.042}}}}))
    tex = ws / "paper.tex"
    tex.write_text("\\begin{tabular}{c}\n0.042 \\\\\n\\end{tabular}\n")

    report = verify_numbers(tex, ws)
    assert report.matched_cells, "fixture should match at least one cell"
    key = report.matched_cells[0].source_key
    assert key.startswith("estimation_results.json.")

    # And that real key must resolve through provenance's lookup.
    b = _bundle(tmp_path)
    assert _source_key_file(b, key) == "results/estimation_results.json"


def test_citation_edge_carries_registry_and_doi(tmp_path: Path):
    b = _bundle(tmp_path)
    prov = build_provenance(b, MANIFEST, exported_at="20260627")
    cite = next(e for e in prov["edges"] if e["type"] == "citation")
    assert cite["key"] == "smith2021"
    assert cite["registry"] == "openalex"
    assert cite["external_id"] == "doi:10.1/x"


def test_run_metadata_from_manifest(tmp_path: Path):
    b = _bundle(tmp_path)
    prov = build_provenance(b, MANIFEST, exported_at="20260627")
    assert prov["schema"] == "e2er-provenance/1"
    assert prov["run"]["governance"] == "off"
    assert prov["run"]["backend"] == "claude_code"
    assert prov["run"]["exported_at"] == "20260627"


def test_degrades_gracefully_without_reports(tmp_path: Path):
    b = tmp_path / "empty"
    (b / "paper").mkdir(parents=True)
    (b / "paper" / "paper.tex").write_text("x")
    prov = build_provenance(b, {"paper_id": "p"}, exported_at="20260627")
    assert prov["edges"] == []
    assert "paper/paper.tex" in prov["files"]
    assert prov["run"]["governance"] == "full"  # default when manifest lacks it


# ── write + schema conformance ───────────────────────────────────────────────


def test_write_provenance_round_trips_and_validates(tmp_path: Path):
    b = _bundle(tmp_path)
    path = write_provenance(b, MANIFEST, exported_at="20260627")
    assert path.name == PROVENANCE_FILE
    doc = json.loads(path.read_text())
    assert doc["run"]["e2er_version"]  # non-empty (real version or "unknown")

    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "schemas" / "provenance.schema.json").read_text()
    )
    jsonschema.validate(doc, schema)  # raises on non-conformance


# ── verify_numbers records matched cells (the P4.1 extension) ─────────────────


def test_verify_numbers_records_matched_cells():
    from src.core.pipeline.verify_numbers import VerificationReport

    r = VerificationReport()
    assert r.matched_cells == []  # additive field, defaults empty
    assert "matched_cells" in r.to_dict()
