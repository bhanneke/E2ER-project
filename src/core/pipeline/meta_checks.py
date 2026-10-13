"""The deterministic steps of the systematic-review template, as checks that run as steps.

Each is ``(workspace, **settings) -> verdict`` (``_run_check_step`` in the
runner). The work is in ``src/modules/metaanalysis/workflow.py``.

- ``meta_search`` (reliability): every search of ``review_protocol.json`` on
  OpenAlex (and Crossref when named), recorded and deduplicated. Runs at every
  start, so an edited protocol is searched again; unchanged searches are read
  from the cache without a request.
- ``meta_screening`` (a gate): every record decided, every exclusion with a
  criterion of the protocol and a reason; writes the sample the researcher reads.
- ``meta_fulltext`` (reliability): open-access full texts, page by page, or
  the reason there is none.
- ``meta_extraction`` (a gate): every extracted number read back from the
  passage it cites; full-text exclusions with reasons; risk of bias for every
  included study.
- ``meta_synthesis`` (a gate): e2er's ``run_estimation.py`` written and run;
  the results held to the meta-analysis contract (too few studies: narrative
  synthesis, no pooled estimate); forest, funnel and PRISMA figures; tables.
"""

from __future__ import annotations

from pathlib import Path

from ...modules.metaanalysis import workflow as wf

Verdict = wf.Verdict


def meta_search(workspace: Path, *, max_records: int = 600, max_requests: int = 40, max_crossref: int = 100) -> Verdict:
    return wf.search_step(
        Path(workspace), max_records=max_records, max_requests=max_requests, max_crossref=max_crossref
    )


def meta_screening(workspace: Path, *, sample_size: int = 20) -> Verdict:
    return wf.screening_step(Path(workspace), sample_size=sample_size)


def meta_fulltext(workspace: Path, *, max_downloads: int = 150) -> Verdict:
    return wf.fulltext_step(Path(workspace), max_downloads=max_downloads)


def meta_extraction(workspace: Path) -> Verdict:
    return wf.extraction_step(Path(workspace))


def meta_synthesis(workspace: Path) -> Verdict:
    return wf.synthesis_step(Path(workspace))


#: check name -> function, for the runner.
CHECKS = {
    "meta_search": meta_search,
    "meta_screening": meta_screening,
    "meta_fulltext": meta_fulltext,
    "meta_extraction": meta_extraction,
    "meta_synthesis": meta_synthesis,
}

#: What the researcher sees when one of them halts the run.
FILES = {
    "meta_search": ("review_protocol.json", "search_counts.md"),
    "meta_screening": ("screening.json", "records.csv", "review_protocol.json"),
    "meta_fulltext": ("fulltext_log.json",),
    "meta_extraction": ("extraction.json", "extraction_check.md", "fulltext_log.json"),
    "meta_synthesis": ("meta_studies.csv", "estimation_results.json", "review_protocol.json"),
}
