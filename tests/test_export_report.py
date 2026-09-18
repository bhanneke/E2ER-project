"""report.html — the file you can send someone.

Seeing what a run produced used to require installing Python, installing E2ER
and starting a server, which put the results of a verification tool behind a
developer toolchain. A co-author or a referee could not look without becoming a
user first.

Self-containment is the entire premise and the thing most easily lost: one
stylesheet from a CDN, one webfont, one fetch, and the promise that this opens
from a folder on a plane is gone. These tests fail on any of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.core.export.report import render_report, write_report

EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*['"]https?://""")


def _bundle(tmp_path: Path, *, with_reports: bool = True) -> Path:
    b = tmp_path / "bundle"
    (b / "paper").mkdir(parents=True)
    (b / "results").mkdir()
    (b / "reviews").mkdir()

    (b / "paper" / "paper.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (b / "paper" / "abstract.tex").write_text(
        "\\begin{abstract}We find no detectable change.\\end{abstract}", encoding="utf-8"
    )
    (b / "provenance.json").write_text(
        json.dumps(
            {
                "files": {"paper/paper.tex": {"sha256": "x"}},
                "edges": [{"type": "table_cell"}, {"type": "citation"}, {"type": "citation"}],
                "run": {"backend": "claude_code", "governance": "full"},
            }
        ),
        encoding="utf-8",
    )
    if with_reports:
        (b / "results" / "table_render_report.json").write_text(
            json.dumps({"rendered": ["main.tex"], "unresolved": [], "errors": []}), encoding="utf-8"
        )
        (b / "results" / "number_verification.json").write_text(
            json.dumps({"matched": 42, "mismatches": []}), encoding="utf-8"
        )
        (b / "reviews" / "citation_integrity.json").write_text(
            json.dumps({"passed": True, "verified": 9, "total_cites": 9, "missing_in_bib": 0}),
            encoding="utf-8",
        )
    return b


def test_report_is_written_and_names_the_paper(tmp_path: Path):
    b = _bundle(tmp_path)
    out = write_report(b, {"title": "Spot ETFs and comovement", "research_question": "Did it change?"})
    assert out is not None and out.is_file()

    html = out.read_text(encoding="utf-8")
    assert "Spot ETFs and comovement" in html
    assert "Did it change?" in html


def test_it_is_self_contained(tmp_path: Path):
    """No CDN, no webfont, no script, no fetch. It has to open offline."""
    b = _bundle(tmp_path)
    html = render_report(b, {"title": "T"})

    assert not EXTERNAL.search(html), "report pulls an external resource"
    assert "<script" not in html, "report ships script"
    assert "fetch(" not in html and "XMLHttpRequest" not in html


def test_every_link_resolves_inside_the_bundle(tmp_path: Path):
    """A dead link in a shareable report is the same defect as a bundle that
    cannot compile: it fails for the reader and not for the author."""
    b = _bundle(tmp_path)
    write_report(b, {"title": "T"})
    html = (b / "report.html").read_text(encoding="utf-8")

    links = {m for m in re.findall(r"href='([^']+)'", html) if not m.startswith(("http", "#"))}
    broken = sorted(x for x in links if not (b / x).exists())
    assert not broken, f"report links to files that are not in the bundle: {broken}"


def test_it_reports_the_runs_own_verdicts(tmp_path: Path):
    b = _bundle(tmp_path)
    html = render_report(b, {"title": "T"})

    assert "42 table cells trace" in html
    assert "9 of 9 verified" in html
    assert "385" not in html  # not inventing numbers
    assert "3</td>" in html or "derivation edges" in html


def test_a_bundle_without_gate_reports_still_renders(tmp_path: Path):
    """Degrade, never crash: a partial bundle is exactly when someone needs to
    look at it."""
    b = _bundle(tmp_path, with_reports=False)
    html = render_report(b, {"title": "T"})

    assert "no gate reports" in html
    assert "<html" in html


def test_the_abstract_is_shown_without_latex_wrappers(tmp_path: Path):
    b = _bundle(tmp_path)
    html = render_report(b, {"title": "T"})

    assert "We find no detectable change." in html
    assert "\\begin{abstract}" not in html


def test_write_report_never_raises(tmp_path: Path):
    """An export that dies writing a convenience file is worse than one without
    it."""
    missing = tmp_path / "nope"
    assert write_report(missing, {"title": "T"}) is None
