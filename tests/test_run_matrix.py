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


# ── 2026-10: template, review pauses, demonstration, a model per backend ──────


def _capture_submit(monkeypatch, calls):
    monkeypatch.setattr(m, "_ensure_api_up", lambda *a, **k: (True, None))

    def fake_submit(rq, methodology, mode, max_cost, **kw):
        calls.append(kw)
        return {"paper_id": f"pid-{len(calls)}"}

    monkeypatch.setattr(m, "_submit_paper", fake_submit)
    monkeypatch.setattr(m, "_poll_status", lambda paper_id, total_seconds: "completed")
    monkeypatch.setattr(m, "_export_bundle", lambda paper_id, dest_root: Path(dest_root) / "bundle")


def test_matrix_passes_template_review_pauses_demonstration_and_models(tmp_path: Path, monkeypatch):
    calls: list[dict] = []
    _capture_submit(monkeypatch, calls)
    rc = m.run_matrix(
        "RQ",
        ["claude_code", "codex"],
        repeats=1,
        out=str(tmp_path),
        template="event-study-finance",
        review_stages=["initial"],
        demonstration=True,
        models={"claude_code": "sonnet", "codex": "gpt-x"},
    )
    assert rc == 0
    assert [c["model"] for c in calls] == ["sonnet", "gpt-x"]
    for c in calls:
        assert c["template"] == "event-study-finance"
        assert c["review_stages"] == ["initial"]
        assert c["demonstration"] is True
    matrix = json.loads((tmp_path / "matrix.json").read_text())
    assert matrix["template"] == "event-study-finance" and matrix["demonstration"] is True
    assert matrix["models"] == {"claude_code": "sonnet", "codex": "gpt-x"}
    assert [r["model"] for r in matrix["runs"]] == ["sonnet", "gpt-x"]


def test_matrix_without_models_records_each_backends_configured_model(tmp_path: Path, monkeypatch):
    from src.config import get_settings

    monkeypatch.setenv("CODEX_MODEL", "gpt-configured")
    get_settings.cache_clear()
    try:
        calls: list[dict] = []
        _capture_submit(monkeypatch, calls)
        m.run_matrix("RQ", ["codex"], repeats=1, out=str(tmp_path))
    finally:
        get_settings.cache_clear()
    assert calls[0]["model"] is None  # the backend's own setting applies
    matrix = json.loads((tmp_path / "matrix.json").read_text())
    assert matrix["runs"][0]["model"] == "gpt-configured"


def test_parse_models():
    assert m.parse_models("claude_code=sonnet, codex=gpt-x", ["claude_code", "codex"]) == {
        "claude_code": "sonnet",
        "codex": "gpt-x",
    }
    assert m.parse_models(None, ["codex"]) == {}
    import pytest

    for bad in ("codex", "codex=", "nope=x", "gemini=x"):
        with pytest.raises(m.MatrixArgError):
            m.parse_models(bad, ["claude_code", "codex"])


def test_unknown_backend_is_refused(tmp_path: Path, monkeypatch):
    calls: list[dict] = []
    _capture_submit(monkeypatch, calls)
    assert m.run_matrix("RQ", ["claude", "codex"], repeats=1, out=str(tmp_path)) == 2
    assert not calls


def test_default_backends_are_the_ready_ones(monkeypatch):
    from types import SimpleNamespace

    rows = [
        SimpleNamespace(name="claude_code", kind="cli", ready=True),
        SimpleNamespace(name="codex", kind="cli", ready=False),
        SimpleNamespace(name="gemini", kind="cli", ready=True),
        SimpleNamespace(name="anthropic", kind="api", ready=True),
    ]
    monkeypatch.setattr("src.doctor.detect_backends", lambda settings=None: rows)
    assert m.available_backends(settings=object()) == ["claude_code", "gemini"]
    for r in rows:
        if r.kind == "cli":
            r.ready = False
    assert m.available_backends(settings=object()) == ["anthropic"]


def test_no_ready_backend_says_so(tmp_path: Path, monkeypatch, capsys):
    assert m.run_matrix("RQ", [], repeats=1, out=str(tmp_path)) == 2
    assert "e2er doctor" in capsys.readouterr().err


def test_compare_names_the_model_from_the_matrix_when_the_bundle_lacks_it(tmp_path: Path):
    from src.core.compare import _resolve_records

    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    (tmp_path / "matrix.json").write_text(
        json.dumps(
            {
                "research_question": "RQ",
                "runs": [
                    {
                        "backend": "claude_code",
                        "model": "sonnet",
                        "repeat": 1,
                        "status": "completed",
                        "bundle_path": str(tmp_path / "a"),
                    },
                    {
                        "backend": "codex",
                        "model": "gpt-x",
                        "repeat": 1,
                        "status": "completed",
                        "bundle_path": str(tmp_path / "b"),
                    },
                ],
            }
        )
    )
    records, rq, _ = _resolve_records([str(tmp_path / "matrix.json")])
    assert [r["model"] for r in records] == ["sonnet", "gpt-x"]
