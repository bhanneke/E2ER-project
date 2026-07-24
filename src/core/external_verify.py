"""Cross-pipeline citation verification (WS-G).

Run E2ER's citation-integrity chain (OpenAlex → Semantic Scholar → Crossref)
over papers produced by OTHER pipelines — e.g. the public papers from Project
APE — to report how many of their references actually resolve to real works.
Citations-first and nearly format-agnostic: all it needs per paper is a
reference list (`.bib`) and, optionally, the `\\cite`-bearing text.

This is offered as infrastructure, not a gotcha. Any results MUST be shared
with the pipeline's authors (e.g. the APE team) before external / submission
use — this module only produces the reports; the researcher handles sharing.

Reuses `verify_citations.verify()` unchanged. When the text has real `\\cite`
commands they are used as-is; otherwise a synthetic tex citing every bib key
is generated, so the whole reference list is verified.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .pipeline.verify_citations import CitationIntegrityReport

SHARING_NOTE = (
    "Offered as infrastructure, not a gotcha. Share these results with the "
    "pipeline's authors before any external or submission use."
)


def synthesize_cites_tex(bib_path: Path) -> str:
    """A minimal LaTeX doc that \\cites every key in the bib — so verifying it
    verifies the entire reference list."""
    from .pipeline.verify_citations import load_bib

    keys = list(load_bib(Path(bib_path)).keys())
    body = " ".join(f"\\cite{{{k}}}" for k in keys)
    return f"\\documentclass{{article}}\\begin{{document}}\n{body}\n\\end{{document}}\n"


async def verify_paper(bib_path: str | Path, text_path: str | Path | None, tmp_dir: Path) -> CitationIntegrityReport:
    """Verify one external paper's references. Uses `text_path` directly if it
    has \\cite commands; otherwise synthesizes a tex citing the whole bib."""
    from .pipeline.verify_citations import parse_cite_keys
    from .pipeline.verify_citations import verify as verify_citations

    bib_path = Path(bib_path)
    draft: Path | None = None
    if text_path and Path(text_path).is_file():
        text = Path(text_path).read_text(encoding="utf-8", errors="replace")
        if parse_cite_keys(text):
            draft = Path(text_path)
    if draft is None:
        draft = tmp_dir / "synthetic.tex"
        draft.write_text(synthesize_cites_tex(bib_path), encoding="utf-8")
    return await verify_citations(draft, bib_path=bib_path)


def _report_row(name: str, report: CitationIntegrityReport) -> dict[str, Any]:
    total = report.total_cites
    return {
        "paper": name,
        "references": total,
        "verified": report.verified,
        "unverifiable": report.unverifiable,
        "missing_in_bib": report.missing_in_bib,
        "verified_pct": round(100.0 * report.verified / total, 1) if total else None,
    }


def aggregate_reports(named_reports: list[tuple[str, CitationIntegrityReport]]) -> dict[str, Any]:
    per_paper = [_report_row(name, r) for name, r in named_reports]
    total_refs = sum(r["references"] for r in per_paper)
    total_verified = sum(r["verified"] for r in per_paper)
    total_unverifiable = sum(r["unverifiable"] for r in per_paper)
    return {
        "schema": "e2er-external-citation-audit/1",
        "note": SHARING_NOTE,
        "n_papers": len(per_paper),
        "total_references": total_refs,
        "verified": total_verified,
        "unverifiable": total_unverifiable,
        "verified_pct": round(100.0 * total_verified / total_refs, 1) if total_refs else None,
        "per_paper": per_paper,
    }


def render_summary(aggregate: dict[str, Any]) -> str:
    pct = aggregate["verified_pct"]
    pct_s = "n/a" if pct is None else f"{pct}%"
    lines = [
        "# Cross-pipeline citation audit",
        "",
        f"> {aggregate['note']}",
        "",
        f"**{aggregate['n_papers']} paper(s), {aggregate['total_references']} references — "
        f"{aggregate['verified']} verified ({pct_s}), {aggregate['unverifiable']} unverifiable.**",
        "",
        "Verified = the reference resolves to a real work in OpenAlex / Semantic "
        "Scholar / Crossref (by DOI or title). Unverifiable = no registry match "
        "(legitimately includes some preprints, posters, working papers).",
        "",
        "| paper | references | verified | unverifiable | verified % |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in aggregate["per_paper"]:
        vp = "n/a" if r["verified_pct"] is None else f"{r['verified_pct']}%"
        lines.append(f"| {r['paper']} | {r['references']} | {r['verified']} | {r['unverifiable']} | {vp} |")
    lines.append("")
    return "\n".join(lines)


async def audit_papers(papers: list[tuple[str, str, str | None]], out_dir: Path) -> dict[str, Any]:
    """papers = [(name, bib_path, text_path_or_None)]. Writes per-paper reports
    + summary.md + aggregate.json into out_dir; returns the aggregate."""
    out_dir.mkdir(parents=True, exist_ok=True)
    named: list[tuple[str, CitationIntegrityReport]] = []
    with tempfile.TemporaryDirectory() as td:
        for name, bib, text in papers:
            report = await verify_paper(bib, text, Path(td))
            (out_dir / f"{name}.citation_integrity.json").write_text(
                json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
            )
            named.append((name, report))
    aggregate = aggregate_reports(named)
    (out_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_summary(aggregate), encoding="utf-8")
    return aggregate
