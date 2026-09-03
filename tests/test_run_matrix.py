"""`e2er run-matrix` — same RQ across k backends × n repeats (WS-P3.2).

Orchestration only (submit → poll → export → matrix.json); the network + the
pipeline are mocked. Verifies the right per-backend submissions are made and a
well-formed matrix.json is written.
"""

from __future__ import annotations

import json
from pathlib import Path

import src.cli_run_matrix as m


def _patch_pipeline(monkeypatch, submit_calls, *, poll="completed", submit_ok=True):
    monkeypatch.setattr(m, "_ensure_api_up", lambda *a, **k: (True, None))

    def fake_submit(rq, methodology, mode, max_cost, **kw):
        submit_calls.append({"rq": rq, "backend": kw.get("backend"), "title_suffix": kw.get("title_suffix")})
        if not submit_ok:
            return None
        return {"paper_id": f"pid-{len(submit_calls)}", "workspace": "ws"}

    monkeypatch.setattr(m, "_submit_paper", fake_submit)
    monkeypatch.setattr(m, "_poll_status", lambda paper_id, total_seconds: poll)
    monkeypatch.setattr(m, "_export_bundle", lambda paper_id, dest_root: Path(dest_root) / "bundle-01")


def test_matrix_submits_each_backend_and_repeat(tmp_path: Path, monkeypatch):
    calls: list[dict] = []
    _patch_pipeline(monkeypatch, calls)

    rc = m.run_matrix("Does X affect Y?", ["claude_code", "codex"], repeats=2, out=str(tmp_path))
    assert rc == 0

    # 2 backends × 2 repeats = 4 submissions, backend-major order.
    assert [c["backend"] for c in calls] == ["claude_code", "claude_code", "codex", "codex"]
    # Titles are labeled per backend/repeat.
    assert calls[0]["title_suffix"] == " [claude_code/rep-1]"
    assert calls[1]["title_suffix"] == " [claude_code/rep-2]"
    assert calls[3]["title_suffix"] == " [codex/rep-2]"


def test_matrix_json_is_well_formed(tmp_path: Path, monkeypatch):
    calls: list[dict] = []
    _patch_pipeline(monkeypatch, calls)

    m.run_matrix("Does X affect Y?", ["claude_code", "codex"], repeats=2, governance="off", out=str(tmp_path))
    matrix = json.loads((tmp_path / "matrix.json").read_text())

    assert matrix["research_question"] == "Does X affect Y?"
    assert matrix["backends"] == ["claude_code", "codex"]
    assert matrix["repeats"] == 2
    assert matrix["governance"] == "off"
    assert len(matrix["runs"]) == 4
    r0 = matrix["runs"][0]
    assert r0["backend"] == "claude_code" and r0["repeat"] == 1
    assert r0["status"] == "completed"
    assert r0["paper_id"] == "pid-1"
    assert r0["bundle_path"].endswith("claude_code-1/bundle-01")


def test_matrix_records_failed_submit(tmp_path: Path, monkeypatch):
    calls: list[dict] = []
    _patch_pipeline(monkeypatch, calls, submit_ok=False)

    m.run_matrix("RQ", ["claude_code"], repeats=1, out=str(tmp_path))
    runs = json.loads((tmp_path / "matrix.json").read_text())["runs"]
    assert runs[0]["status"] == "submit_failed"
    assert runs[0]["paper_id"] is None
    assert runs[0]["bundle_path"] is None


def test_matrix_records_non_completed_status(tmp_path: Path, monkeypatch):
    calls: list[dict] = []
    _patch_pipeline(monkeypatch, calls, poll="failed")

    m.run_matrix("RQ", ["codex"], repeats=1, out=str(tmp_path))
    runs = json.loads((tmp_path / "matrix.json").read_text())["runs"]
    assert runs[0]["status"] == "failed"
    assert runs[0]["bundle_path"] is None  # no export for a non-completed run


def test_matrix_validates_inputs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(m, "_ensure_api_up", lambda *a, **k: (True, None))
    assert m.run_matrix("RQ", [], repeats=2, out=str(tmp_path)) == 2
    assert m.run_matrix("RQ", ["codex"], repeats=0, out=str(tmp_path)) == 2
