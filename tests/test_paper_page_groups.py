"""Artifacts grouped by the phase that produced them, with an honest verdict.

The paper page listed every file in one alphabetical run: 42 files, no
indication of which step produced them or whether it went well, and — worst —
no way at all to see that a specialist had failed to write something, because a
file that was never written simply is not in a list of files.

The first version of the grouping then produced two false failures: it marked
Self-attack and polish red at 0/6 on a single_pass run, which skips both phases
by design, and Design red at 4/5 because theory_specialist is not dispatched for
an empirical paper. Those are pinned below, because a UI that cries wolf is the
same defect as a gate that does.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.api.app import _artifact_groups, _reading_list


def _workspace(tmp_path: Path, *, complete: bool = True) -> tuple[Path, list[str]]:
    ws = tmp_path / "ws"
    (ws / "replication").mkdir(parents=True)
    written = {
        "paper_plan.md": "plan",
        "literature_review.md": "lit",
        "identification_strategy.md": "ident",
        "identification_spec.json": json.dumps({"primary": {}}),
        "data_dictionary.json": json.dumps({}),
        "data_summary.md": "data",
        "summary_statistics.json": json.dumps({}),
        "figure_spec.json": json.dumps({}),
        "econometric_spec.md": "spec",
        "estimation_results.json": json.dumps({"main": {}}),
        "paper_draft.tex": "\\documentclass{article}",
        "abstract.tex": "abstract",
        "table_spec.json": json.dumps({"tables": []}),
        "scratch_probe.py": "# scratch",
    }
    if complete:
        written["paper_draft.pdf"] = "%PDF-1.4"
    for rel, body in written.items():
        (ws / rel).write_text(body, encoding="utf-8")
    (ws / "replication" / "estimation.py").write_text("# repl", encoding="utf-8")

    arts = sorted(str(f.relative_to(ws)) for f in ws.rglob("*") if f.is_file())
    return ws, arts


def test_artifacts_are_attributed_to_their_phase(tmp_path: Path):
    ws, arts = _workspace(tmp_path)
    groups = {g["name"]: g for g in _artifact_groups(ws, arts, "single_pass", "empirical")}

    design = groups["Design"]
    paths = {f["p"] for f in design["files"]}
    assert "paper_plan.md" in paths
    assert "identification_spec.json" in paths

    est = groups["Estimation"]
    assert "estimation_results.json" in {f["p"] for f in est["files"]}


def test_a_phase_never_dispatched_is_not_a_failure(tmp_path: Path):
    """single_pass skips self-attack and polish. Red there would be a lie."""
    ws, arts = _workspace(tmp_path)
    groups = {g["name"]: g for g in _artifact_groups(ws, arts, "single_pass", "empirical")}

    phase = groups["Self-attack and polish"]
    assert phase["status"] == "none"
    assert "not run" in phase["note"]


def test_the_theory_specialist_is_not_expected_of_an_empirical_paper(tmp_path: Path):
    ws, arts = _workspace(tmp_path)
    groups = {g["name"]: g for g in _artifact_groups(ws, arts, "single_pass", "empirical")}

    assert groups["Design"]["status"] == "pass"
    assert "model_spec.md" not in {f["p"] for f in groups["Design"]["files"]}


def test_a_missing_declared_artifact_is_shown_and_fails_its_phase(tmp_path: Path):
    """The whole point: absence is visible.

    A flat file list cannot show that the drafter never wrote its output.
    """
    ws, arts = _workspace(tmp_path)
    (ws / "estimation_results.json").unlink()
    arts = [a for a in arts if a != "estimation_results.json"]

    groups = {g["name"]: g for g in _artifact_groups(ws, arts, "single_pass", "empirical")}
    est = groups["Estimation"]

    assert est["status"] == "fail"
    missing = [f for f in est["files"] if f["status"] == "missing"]
    assert [f["p"] for f in missing] == ["estimation_results.json"]


def test_an_empty_artifact_fails_too(tmp_path: Path):
    """A zero-byte file satisfies "exists" and nothing else."""
    ws, arts = _workspace(tmp_path)
    (ws / "estimation_results.json").write_text("", encoding="utf-8")

    groups = {g["name"]: g for g in _artifact_groups(ws, arts, "single_pass", "empirical")}
    est = groups["Estimation"]
    assert est["status"] == "fail"
    assert any(f["note"] == "written but empty" for f in est["files"])


def test_gate_reports_carry_their_own_verdict(tmp_path: Path):
    ws, arts = _workspace(tmp_path)
    (ws / "number_verification.json").write_text(
        json.dumps({"matched": 12, "mismatches": [{"severity": "critical"}]}), encoding="utf-8"
    )
    arts.append("number_verification.json")

    groups = {g["name"]: g for g in _artifact_groups(ws, arts, "single_pass", "empirical")}
    gates = groups["Gates"]
    assert gates["status"] == "fail"
    assert any("critical" in f["note"] for f in gates["files"])


def test_the_paper_is_offered_for_reading(tmp_path: Path):
    """The compiled PDF was in the workspace and unreachable from the page."""
    _, arts = _workspace(tmp_path)
    reading = _reading_list(arts)

    assert reading, "nothing offered to read"
    assert reading[0]["path"] == "paper_draft.pdf"
    assert reading[0]["primary"] is True


def test_reading_list_skips_what_was_not_produced(tmp_path: Path):
    _, arts = _workspace(tmp_path, complete=False)
    paths = {r["path"] for r in _reading_list(arts)}
    assert "paper_draft.pdf" not in paths
    assert "paper_draft.tex" in paths
