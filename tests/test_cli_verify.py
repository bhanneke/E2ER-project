"""`e2er verify <bundle>` — offline bundle verification (WS-P4.2).

Builds a real bundle via export_paper, then checks that a clean bundle passes
and each tamper is caught. The offline path must never touch the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.cli_verify import FAIL, PASS, SKIP, _run_checks, verify

# Coefficient ≥ 1 so a tampered cell crosses verify_numbers' critical
# threshold (its relative-error denominator is clamped to max(1, source),
# so sub-1 values can only ever produce a non-gating "major" mismatch).
TABLE_TEX = (
    "\\documentclass{article}\\begin{document}\n"
    "See \\cite{smith2021}.\n"
    "\\begin{tabular}{lc}\n"
    "Treatment & 12.5 \\\\\n"
    "\\end{tabular}\n"
    "\\end{document}\n"
)


def _clean_bundle(tmp_path: Path) -> Path:
    """Export a bundle whose numbers trace, spec matches, and citation resolves."""
    from src.core.export.structured import export_paper

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"title": "Verify Me", "paper_id": "p1", "governance": "full"}))
    (ws / "paper_draft.tex").write_text(TABLE_TEX)
    (ws / "literature.bib").write_text("@article{smith2021, title={X}, doi={10.1/x}, year={2021}}\n")
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"coefficients": {"treat": {"estimate": 12.5}}}}))
    # A spec that declares nothing checkable (no FE/controls/clustering) → the
    # contract passes trivially, keeping this fixture's focus on tamper cases.
    (ws / "identification_spec.json").write_text(
        json.dumps({"primary": {"estimator": "ols", "outcome": "y", "treatment": "treat"}})
    )
    return export_paper(ws, tmp_path / "out", date_str="20260627")


def _status(bundle: Path, name: str) -> str:
    return next(c.status for c in _run_checks(bundle, online=False) if c.name == name)


# ── clean bundle passes ──────────────────────────────────────────────────────


def test_clean_bundle_passes_offline(tmp_path: Path):
    bundle = _clean_bundle(tmp_path)
    assert verify(str(bundle), online=False) == 0
    checks = {c.name: c.status for c in _run_checks(bundle, online=False)}
    assert checks["integrity"] == PASS
    assert checks["numbers"] == PASS
    assert checks["spec"] == PASS
    assert checks["citations"] == PASS


def test_non_directory_bundle_errors(tmp_path: Path):
    assert verify(str(tmp_path / "nope"), online=False) == 2


# ── tamper cases ─────────────────────────────────────────────────────────────


def test_tamper_edited_table_number_fails(tmp_path: Path):
    bundle = _clean_bundle(tmp_path)
    tex = bundle / "paper" / "paper.tex"
    # 12.5 → 20.0: close enough to be a critical mismatch, not an unrelated number.
    tex.write_text(tex.read_text().replace("12.5", "20.0"))
    assert verify(str(bundle), online=False) == 1
    assert _status(bundle, "numbers") == FAIL
    assert _status(bundle, "integrity") == FAIL  # the tex hash also changed


def test_tamper_edited_results_json_fails(tmp_path: Path):
    bundle = _clean_bundle(tmp_path)
    res = bundle / "results" / "estimation_results.json"
    res.write_text(res.read_text().replace("12.5", "20.0"))
    assert verify(str(bundle), online=False) == 1
    assert _status(bundle, "integrity") == FAIL


def test_tamper_deleted_bib_entry_fails(tmp_path: Path):
    bundle = _clean_bundle(tmp_path)
    (bundle / "paper" / "refs.bib").write_text("@article{other2020, title={Y}}\n")
    assert verify(str(bundle), online=False) == 1
    assert _status(bundle, "citations") == FAIL


def test_tamper_deleted_file_fails(tmp_path: Path):
    bundle = _clean_bundle(tmp_path)
    (bundle / "paper" / "refs.bib").unlink()
    assert verify(str(bundle), online=False) == 1
    assert _status(bundle, "integrity") == FAIL


# ── a skipped check is not a passed check ────────────────────────────────────


def _integrity_only_bundle(tmp_path: Path) -> Path:
    """A bundle with no paper.tex — export is best-effort, so this really is
    producible. Nothing but hashes can be checked."""
    from src.core.export.provenance import write_provenance

    b = tmp_path / "partial"
    (b / "results").mkdir(parents=True)
    (b / "results" / "notes.json").write_text("{}")
    write_provenance(b, {"paper_id": "p1", "governance": "off"}, exported_at="20260627")
    return b


def test_partial_bundle_is_not_reported_as_verified(tmp_path: Path, capsys):
    """The failure this guards: integrity PASS + every content check SKIP once
    printed '✅ Bundle verified — hashes, numbers, spec, and citations are
    internally consistent' and exited 0, having checked only hashes."""
    bundle = _integrity_only_bundle(tmp_path)
    assert _status(bundle, "integrity") == PASS
    for name in ("numbers", "spec", "citations"):
        assert _status(bundle, name) == SKIP

    code = verify(str(bundle), online=False)
    out = capsys.readouterr().out
    assert code == 1
    assert "NOT verified" in out
    assert "✅" not in out


def test_partial_verdict_names_the_skipped_checks(tmp_path: Path, capsys):
    """Citations verifiable but no results JSON → pass, but say plainly which
    checks did NOT run rather than implying the whole bundle was checked."""
    from src.core.export.provenance import write_provenance

    b = tmp_path / "cites-only"
    (b / "paper").mkdir(parents=True)
    (b / "paper" / "paper.tex").write_text("See \\cite{smith2021}.\n")
    (b / "paper" / "refs.bib").write_text("@article{smith2021, title={X}, year={2021}}\n")
    write_provenance(b, {"paper_id": "p1", "governance": "off"}, exported_at="20260627")

    checks = {c.name: c.status for c in _run_checks(b, online=False)}
    assert checks["citations"] == PASS
    assert checks["numbers"] == SKIP
    assert checks["spec"] == SKIP

    assert verify(str(b), online=False) == 0
    out = capsys.readouterr().out
    assert "1 content check(s) passed (citations)" in out
    assert "2 skipped (numbers, spec)" in out


# ── offline path never touches the network ───────────────────────────────────


def test_offline_never_calls_the_live_registry(tmp_path: Path, monkeypatch):
    bundle = _clean_bundle(tmp_path)

    async def _boom(*a, **k):
        raise AssertionError("offline verify must not call the live citation registry")

    monkeypatch.setattr("src.core.pipeline.verify_citations.verify", _boom)
    assert verify(str(bundle), online=False) == 0
