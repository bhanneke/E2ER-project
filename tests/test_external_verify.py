"""Cross-pipeline citation audit (WS-G).

The registry chain (verify_citations.verify) is mocked — these tests pin the
synthesize-from-bib logic, the text-with-cites path, aggregation, the summary
(incl. the sharing note), and the on-disk outputs.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.core.external_verify import (
    aggregate_reports,
    audit_papers,
    render_summary,
    synthesize_cites_tex,
    verify_paper,
)
from src.core.pipeline.verify_citations import CitationIntegrityReport


def _bib(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "refs.bib"
    p.write_text(text, encoding="utf-8")
    return p


def test_synthesize_cites_every_bib_key(tmp_path: Path):
    bib = _bib(
        tmp_path,
        "@article{smith2021, title={A}, author={Smith}, year={2021}}\n"
        "@book{jones2020, title={B}, author={Jones}, year={2020}}\n",
    )
    tex = synthesize_cites_tex(bib)
    assert "\\cite{smith2021}" in tex
    assert "\\cite{jones2020}" in tex


async def test_verify_paper_synthesizes_when_no_text(tmp_path: Path, monkeypatch):
    captured: dict = {}

    async def fake_verify(draft, bib_path=None, **kw):
        captured["draft"] = Path(draft)
        return CitationIntegrityReport(total_cites=2, verified=2, unverifiable=0)

    monkeypatch.setattr("src.core.pipeline.verify_citations.verify", fake_verify)
    bib = _bib(tmp_path, "@article{smith2021, title={A}, year={2021}}\n@book{jones2020, title={B}, year={2020}}\n")
    with tempfile.TemporaryDirectory() as td:
        await verify_paper(str(bib), None, Path(td))
        content = captured["draft"].read_text()
    assert "\\cite{smith2021}" in content and "\\cite{jones2020}" in content


async def test_verify_paper_uses_text_with_real_cites(tmp_path: Path, monkeypatch):
    captured: dict = {}

    async def fake_verify(draft, bib_path=None, **kw):
        captured["draft"] = Path(draft)
        return CitationIntegrityReport()

    monkeypatch.setattr("src.core.pipeline.verify_citations.verify", fake_verify)
    bib = _bib(tmp_path, "@article{x, title={A}}\n")
    tex = tmp_path / "paper.tex"
    tex.write_text("Body text with \\cite{x}.", encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        await verify_paper(str(bib), str(tex), Path(td))
    assert captured["draft"] == tex  # used the real text, did not synthesize


def test_aggregate_reports():
    r1 = CitationIntegrityReport(total_cites=4, verified=3, unverifiable=1)
    r2 = CitationIntegrityReport(total_cites=6, verified=3, unverifiable=3)
    agg = aggregate_reports([("p1", r1), ("p2", r2)])
    assert agg["n_papers"] == 2
    assert agg["total_references"] == 10
    assert agg["verified"] == 6
    assert agg["verified_pct"] == 60.0
    assert agg["per_paper"][0]["verified_pct"] == 75.0


def test_render_summary_has_sharing_note_and_pct():
    agg = aggregate_reports([("p1", CitationIntegrityReport(total_cites=4, verified=3, unverifiable=1))])
    s = render_summary(agg)
    assert "Cross-pipeline citation audit" in s
    assert "before any external" in s.lower()  # the sharing constraint
    assert "75.0%" in s


async def test_audit_papers_writes_outputs(tmp_path: Path, monkeypatch):
    async def fake_verify(draft, bib_path=None, **kw):
        return CitationIntegrityReport(total_cites=2, verified=2, unverifiable=0)

    monkeypatch.setattr("src.core.pipeline.verify_citations.verify", fake_verify)
    bib = _bib(tmp_path, "@article{a, title={A}, year={2021}}\n")
    out = tmp_path / "out"
    agg = await audit_papers([("paperA", str(bib), None)], out)
    assert agg["total_references"] == 2 and agg["verified_pct"] == 100.0
    assert (out / "paperA.citation_integrity.json").is_file()
    assert (out / "summary.md").is_file()
    assert json.loads((out / "aggregate.json").read_text())["n_papers"] == 1
