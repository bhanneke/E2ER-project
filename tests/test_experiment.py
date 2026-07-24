"""Governance experiment driver (WS-F).

Harvesting metrics from a bundle + events, YAML config loading, and a full
RQ × 3-regime × N=1 dry run (stubbed server) producing a well-formed
results.csv + summary.md.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.core.experiment import (
    ExperimentConfig,
    _gate_event_stats,
    harvest_run,
    load_config,
    run_experiment,
)


def test_harvest_run_computes_fabrication(tmp_path: Path):
    b = tmp_path / "b"
    (b / "results").mkdir(parents=True)
    (b / "reviews").mkdir(parents=True)
    (b / "results" / "number_verification.json").write_text(
        json.dumps({"mismatches": [{"severity": "critical"}, {"severity": "critical"}, {"severity": "major"}]})
    )
    (b / "reviews" / "citation_integrity.json").write_text(
        json.dumps({"missing_in_bib": 1, "unverifiable": 2, "total_cites": 10})
    )
    events = [
        {"event_type": "gate_shadow", "payload": {"passed": False}},
        {"event_type": "gate_shadow", "payload": {"passed": True}},
    ]
    row = harvest_run(
        rq_idx=0,
        regime="off",
        backend="cc",
        repeat=1,
        paper_id="p1",
        status="completed",
        bundle_path=str(b),
        events=events,
    )
    assert row["critical_mismatches"] == 2  # only the criticals, not the major
    assert row["missing_in_bib"] == 1 and row["unverifiable"] == 2
    assert row["fabrication_count"] == 5  # 2 + 1 + 2
    assert row["shadow_gate_failures"] == 1
    assert row["completed"] == 1


def test_harvest_run_no_bundle_is_zero():
    row = harvest_run(
        rq_idx=0,
        regime="full",
        backend="cc",
        repeat=1,
        paper_id="p",
        status="failed",
        bundle_path=None,
        events=[],
    )
    assert row["fabrication_count"] == 0 and row["completed"] == 0


def test_gate_event_stats_handles_string_and_dict_payloads():
    events = [
        {"event_type": "gate_shadow", "payload": '{"passed": false}'},
        {"event_type": "gate_enforced", "payload": {"passed": False}},
        {"event_type": "gate_shadow", "payload": '{"passed": true}'},  # passed → not a failure
    ]
    assert _gate_event_stats(events) == (1, 1)


def test_load_config(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("name: t\nresearch_questions:\n  - Q1\nregimes: [off, full]\nrepeats: 2\n")
    c = load_config(p)
    assert c.name == "t"
    assert c.research_questions == ["Q1"]
    assert c.regimes == ["off", "full"]
    assert c.repeats == 2


# ── full dry run (stubbed server) ────────────────────────────────────────────


def _dry_run(tmp_path: Path):
    fab = {"off": 3, "contracts": 1, "full": 0}
    pid_regime: dict[str, str] = {}
    counter = {"n": 0}

    def submit_fn(*, rq, regime, backend, methodology, mode, max_cost, label):
        counter["n"] += 1
        pid = f"p{counter['n']}"
        pid_regime[pid] = regime
        return pid

    def poll_fn(paper_id, monitor_seconds):
        return "completed"

    def export_fn(paper_id, dest: Path):
        regime = pid_regime[paper_id]
        (dest / "results").mkdir(parents=True, exist_ok=True)
        (dest / "reviews").mkdir(parents=True, exist_ok=True)
        (dest / "results" / "number_verification.json").write_text(
            json.dumps({"mismatches": [{"severity": "critical"}] * fab[regime]})
        )
        (dest / "reviews" / "citation_integrity.json").write_text(
            json.dumps({"missing_in_bib": 0, "unverifiable": 0, "total_cites": 5})
        )
        return dest

    def events_fn(paper_id):
        regime = pid_regime[paper_id]
        if not fab[regime]:
            return []
        et = "gate_shadow" if regime != "full" else "gate_enforced"
        return [{"event_type": et, "payload": json.dumps({"gate": "numbers", "passed": False, "regime": regime})}]

    config = ExperimentConfig(
        name="pilot",
        research_questions=["Does X affect Y?"],
        regimes=["off", "contracts", "full"],
        repeats=1,
        backends=["claude_code"],
    )
    rows = run_experiment(
        config, tmp_path, submit_fn=submit_fn, poll_fn=poll_fn, export_fn=export_fn, events_fn=events_fn
    )
    return rows


def test_dry_run_writes_well_formed_results_csv(tmp_path: Path):
    rows = _dry_run(tmp_path)
    assert len(rows) == 3

    with (tmp_path / "results.csv").open(encoding="utf-8") as f:
        parsed = list(csv.DictReader(f))
    assert [r["regime"] for r in parsed] == ["off", "contracts", "full"]

    off = next(r for r in parsed if r["regime"] == "off")
    assert int(off["fabrication_count"]) == 3
    assert int(off["shadow_gate_failures"]) == 1
    assert int(off["completed"]) == 1

    full = next(r for r in parsed if r["regime"] == "full")
    assert int(full["fabrication_count"]) == 0
    assert int(full["shadow_gate_failures"]) == 0


def test_dry_run_writes_summary_with_per_regime_means(tmp_path: Path):
    _dry_run(tmp_path)
    summary = (tmp_path / "summary.md").read_text()
    assert "Per-regime means" in summary
    assert "| off |" in summary and "| full |" in summary
    # fabrication is measured in the shadow regimes, not zeroed out.
    assert "shadow" in summary.lower()


def test_run_experiment_records_submit_failure(tmp_path: Path):
    def submit_fn(**kw):
        return None

    config = ExperimentConfig(name="t", research_questions=["Q"], regimes=["off"], repeats=1, backends=["cc"])
    rows = run_experiment(
        config,
        tmp_path,
        submit_fn=submit_fn,
        poll_fn=lambda pid, s: "completed",
        export_fn=lambda pid, dest: dest,
        events_fn=lambda pid: [],
    )
    assert rows[0]["status"] == "submit_failed"
    assert rows[0]["completed"] == 0
