"""The deterministic steps of the field-map template, as checks that run as steps.

Each is ``(workspace, **settings) -> verdict``, the shape the runner records
for every check (``_run_check_step``). The computation lives in
``src/modules/fieldmap/workflow.py``, where ``e2er-fieldmap`` runs the same
functions.

- ``field_retrieve`` (reliability): retrieves every boundary of
  ``field_boundary.json`` from OpenAlex. Runs at every start, so a boundary the
  researcher edited is retrieved again (unchanged ones come from the files
  already retrieved, without a request).
- ``field_network`` (a gate a governance regime can shadow): builds the main
  boundary's citation network and fails when too many papers have no internal
  link or no references in OpenAlex.
- ``field_main_path``, ``field_robustness``, ``field_map`` (reliability): SPC,
  main paths and key routes; the same on every alternative boundary; the map,
  exports, reading list, tables and the results file.
- ``numbers`` and ``citations``: the number check and the citation check on
  the draft, run as steps of their own in a template without a review panel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ...modules.fieldmap import workflow as wf

Verdict = wf.Verdict


def field_retrieve(workspace: Path, *, max_papers: int = 5000, max_requests: int = 300) -> Verdict:
    return wf.retrieve_boundaries(Path(workspace), max_papers=max_papers, max_requests=max_requests)


def field_network(
    workspace: Path,
    *,
    max_isolated_share: float = 0.5,
    max_missing_refs_share: float = 0.4,
    min_papers: int = 100,
) -> Verdict:
    return wf.network_step(
        Path(workspace),
        max_isolated_share=float(max_isolated_share),
        max_missing_refs_share=float(max_missing_refs_share),
        min_papers=min_papers,
    )


def field_main_path(workspace: Path, *, key_routes: int = 10) -> Verdict:
    return wf.mainpath_step(Path(workspace), key_routes=key_routes)


def field_robustness(workspace: Path) -> Verdict:
    return wf.robustness_step(Path(workspace))


def field_map(workspace: Path) -> Verdict:
    return wf.map_step(Path(workspace))


DRAFT = "paper_draft.tex"


def draft_numbers(workspace: Path) -> Verdict:
    """The number check on the draft: every table cell must trace to a results file."""
    from .verify_numbers import verify_and_save

    ws = Path(workspace)
    draft = ws / DRAFT
    if not draft.is_file():
        return Verdict(passed=False, reasons=(f"{DRAFT} is missing",))
    report = verify_and_save(draft, ws)
    stats: dict[str, Any] = {
        "table_values": report.total_values_in_tables,
        "matched": report.matched,
        "prose_matched": report.prose_matched,
        "prose_unverifiable": report.prose_unverifiable,
    }
    if report.critical_mismatches:
        shown = "; ".join(
            f"{m.draft_value} vs {m.source_value} ({m.source_key}) at {m.table_context}"
            for m in report.critical_mismatches[:5]
        )
        return Verdict(
            passed=False,
            reasons=(f"{len(report.critical_mismatches)} table value(s) differ from the results files: {shown}",),
            stats=stats,
        )
    if not report.tables_conclusive:
        return Verdict(
            passed=False,
            reasons=(
                "the draft has no table the number check can read: include tables/field_map_summary.tex "
                "with \\input{tables/field_map_summary.tex}",
            ),
            stats=stats,
        )
    notes: tuple[str, ...] = ()
    if report.prose_mismatched:
        notes = (
            f"{report.prose_mismatched} number(s) in the text match no results value (see number_verification.json)",
        )
    return Verdict(passed=True, stats=stats, notes=notes)


def draft_citations(workspace: Path) -> Verdict:
    """The citation check on the draft: every key in the bibliography, and found in OpenAlex, S2 or Crossref."""
    from ..renderer.templates import assemble_refs_bib
    from .verify_citations import verify_and_save

    ws = Path(workspace)
    draft = ws / DRAFT
    if not draft.is_file():
        return Verdict(passed=False, reasons=(f"{DRAFT} is missing",))
    bib = assemble_refs_bib(ws)
    report = asyncio.run(verify_and_save(draft, ws, bib_path=bib))
    stats = {"cites": report.total_cites, "verified": report.verified, "missing_in_bib": report.missing_in_bib}
    if report.passed:
        return Verdict(passed=True, stats=stats)
    missing = ", ".join(c.cite_key for c in report.missing_checks[:5])
    unverif = ", ".join(c.cite_key for c in report.unverifiable_checks[:5])
    reasons = []
    if report.missing_in_bib:
        reasons.append(f"{report.missing_in_bib} cited key(s) missing from the bibliography: {missing}")
    if report.strict and report.unverifiable:
        reasons.append(f"{report.unverifiable} cite(s) found in no index (strict mode): {unverif}")
    return Verdict(passed=False, reasons=tuple(reasons or ["the citation check did not pass"]), stats=stats)


#: check name -> function, for the runner.
CHECKS = {
    "field_retrieve": field_retrieve,
    "field_network": field_network,
    "field_main_path": field_main_path,
    "field_robustness": field_robustness,
    "field_map": field_map,
    "numbers": draft_numbers,
    "citations": draft_citations,
}

#: What the researcher sees when one of them halts the run.
FILES = {
    "field_retrieve": ("field_boundary.json", "field_boundary_counts.md"),
    "field_network": ("field_boundary.json", "completeness_report.md", "completeness_report.json"),
    "field_main_path": ("completeness_report.md",),
    "field_robustness": ("field_boundary.json",),
    "field_map": ("field_lanes.json",),
    "numbers": ("paper_draft.tex", "number_verification.json", "field_map_results.json"),
    "citations": ("paper_draft.tex", "citation_integrity.json", "literature.bib"),
}
