"""The fabrication metric must not report 0 for checks that never ran.

Every test here fails against the pre-2026-08-04 harvester, which counted only
table-cell `mismatches[].severity == "critical"` and read a skipped citation
check as a clean one. The first pilot run (paper ab95fcba) recorded
fabrication_count=0 while its own report said prose_mismatched=166.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.experiment import ExperimentConfig, harvest_run, run_experiment, write_summary


def _write(root: Path, rel: str, payload: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _harvest(**kw):
    base = {
        "rq_idx": 0,
        "regime": "off",
        "backend": "claude_code",
        "repeat": 1,
        "paper_id": "p1",
        "status": "completed",
        "bundle_path": None,
        "events": [],
    }
    base.update(kw)
    return harvest_run(**base)


def test_prose_mismatches_count_as_fabrication(tmp_path: Path) -> None:
    """The exact shape of pilot run ab95fcba: no table cells, 166 bad prose numbers."""
    _write(
        tmp_path,
        "results/number_verification.json",
        {
            "passed": True,
            "total_values_in_tables": 0,
            "matched": 0,
            "mismatched": 0,
            "coverage": 1.0,
            "mismatches": [],
            "prose_total": 278,
            "prose_matched": 112,
            "prose_mismatched": 166,
        },
    )
    row = _harvest(bundle_path=str(tmp_path))
    assert row["prose_mismatched"] == 166
    assert row["fabrication_count"] == 166, "prose mismatches must not be invisible to the metric"


def test_skipped_citation_check_is_not_a_clean_one(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "reviews/citation_integrity.json",
        {
            "passed": True,
            "total_cites": 0,
            "verified": 0,
            "unverifiable": 0,
            "missing_in_bib": 0,
            "skipped_reason": "no bibliography source found",
        },
    )
    row = _harvest(bundle_path=str(tmp_path))
    assert "citations" in row["checks_skipped"]


def test_run_with_every_check_skipped_is_not_measured(tmp_path: Path) -> None:
    empty = {"passed": True, "total_values_in_tables": 0, "prose_total": 0}
    _write(tmp_path, "results/number_verification.json", empty)
    _write(tmp_path, "reviews/citation_integrity.json", {"passed": True, "total_cites": 0})
    row = _harvest(bundle_path=str(tmp_path))
    assert row["measured"] == 0
    assert row["fabrication_count"] == 0  # a zero, but flagged as not evidence


def test_a_real_check_marks_the_run_measured(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "results/number_verification.json",
        {"total_values_in_tables": 12, "prose_total": 30, "prose_mismatched": 2, "mismatches": []},
    )
    row = _harvest(bundle_path=str(tmp_path))
    assert row["measured"] == 1
    assert row["fabrication_count"] == 2


def test_rejected_run_is_harvested_from_its_workspace(tmp_path: Path) -> None:
    """A `rejected` run is never exported, but its workspace holds the reports.

    Without the workspace fallback these runs contribute a structural zero —
    biasing the experiment toward the null it is meant to test.
    """
    ws = tmp_path / "workspaces" / "abc"
    ws.mkdir(parents=True)
    (ws / "number_verification.json").write_text(
        json.dumps({"total_values_in_tables": 0, "prose_total": 278, "prose_mismatched": 166, "mismatches": []}),
        encoding="utf-8",
    )
    row = _harvest(status="rejected", bundle_path=None, workspace_path=str(ws))
    assert row["fabrication_count"] == 166
    assert row["measured"] == 1


def test_missing_reports_yield_an_unmeasured_row() -> None:
    row = _harvest(bundle_path=None, workspace_path=None)
    assert row["measured"] == 0
    assert row["checks_skipped"] == "numbers,citations"


def test_summary_excludes_unmeasured_runs_from_means(tmp_path: Path) -> None:
    cfg = ExperimentConfig(name="t", research_questions=["q"], regimes=["off"], repeats=2)
    rows = [
        _harvest(repeat=1, bundle_path=None, workspace_path=None),  # unmeasured 0
        _harvest(
            repeat=2,
            bundle_path=str(
                (
                    lambda p: (
                        _write(
                            p,
                            "results/number_verification.json",
                            {"total_values_in_tables": 4, "prose_total": 10, "prose_mismatched": 8, "mismatches": []},
                        ),
                        p,
                    )[1]
                )(tmp_path / "b")
            ),
        ),
    ]
    write_summary(tmp_path, rows, cfg)
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    # Mean over measured runs only = 8.00, not the 4.00 you'd get by averaging in the skipped 0.
    assert "8.00" in text
    assert "not measurable" in text


def test_workspace_fn_is_used_for_non_completed_runs(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "number_verification.json").write_text(
        json.dumps({"total_values_in_tables": 1, "prose_total": 5, "prose_mismatched": 3, "mismatches": []}),
        encoding="utf-8",
    )
    cfg = ExperimentConfig(name="t", research_questions=["q"], regimes=["off"], repeats=1, backends=["claude_code"])
    rows = run_experiment(
        cfg,
        tmp_path / "out",
        submit_fn=lambda **kw: "pid-1",
        poll_fn=lambda pid, secs: "rejected",
        export_fn=lambda pid, dest: None,
        events_fn=lambda pid: [],
        workspace_fn=lambda pid: str(ws),
    )
    assert rows[0]["fabrication_count"] == 3
    assert rows[0]["measured"] == 1
