"""Acquire, extract, verify, store — the loop behind every way papers enter the corpus.

Lived in ``cli_corpus.py`` until the pipeline needed it too. A paper run has to
read the PDFs staged in its own ``literature/`` folder, and a library module
importing from the CLI to do that would be backwards, so the loop moved here and
the CLI became one of its two callers.

Nothing here prints. Callers pass ``on_event`` if they want progress; the CLI
does, the pipeline logs instead. Nothing here raises for one bad paper either —
acquiring literature fails constantly and in boring ways, and a refresh of a
hundred papers must not end on the fourth.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from . import corpus
from .models import PaperMetadata

logger = get_logger(__name__)

#: How many search hits a single `add --search` or `refresh` considers per
#: topic. Deliberately modest: each one is a download and a model call.
DEFAULT_LIMIT = 10

#: Progress callback: (event, label, detail). `event` is one of
#: skip | stored | no_text | no_claims.
OnEvent = Callable[[str, str, str], None]


@dataclass
class IngestReport:
    """What a batch did. Every paper lands in exactly one bucket."""

    considered: int = 0
    skipped: int = 0
    stored: int = 0
    no_text: int = 0
    no_claims: int = 0
    keys: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "skipped": self.skipped,
            "stored": self.stored,
            "no_text": self.no_text,
            "no_claims": self.no_claims,
            "keys": self.keys,
            "failures": self.failures,
        }


async def ingest_papers(
    conn: sqlite3.Connection,
    papers: list[PaperMetadata],
    *,
    model: str = "",
    skip_known: bool = True,
    on_event: OnEvent | None = None,
) -> IngestReport:
    """Put each paper through the whole path, and report what happened to it."""
    from ...config import get_settings
    from ..llm.registry import get_backend
    from .extract import extract_review
    from .fulltext import fetch_full_text

    settings = get_settings()
    backend = get_backend(settings)
    # Which model produced the claims is not decoration: the fabrication rate is
    # a property of a model, and a corpus that records "unknown" cannot report
    # one. default_model_for resolves against the backend actually in use.
    resolved_model = model or settings.default_model_for(settings.llm_backend) or settings.llm_backend

    report = IngestReport(considered=len(papers))

    def emit(event: str, label: str, detail: str = "") -> None:
        if on_event is not None:
            on_event(event, label, detail)

    for paper in papers:
        label = (paper.title or paper.doi or "untitled")[:70]

        if skip_known and corpus.is_covered(conn, doi=paper.doi, title=paper.title, year=paper.year):
            report.skipped += 1
            emit("skip", label, "already covered")
            continue

        text = await fetch_full_text(paper)
        if not text.ok:
            report.no_text += 1
            report.failures.append({"paper": label, "stage": "fulltext", "error": text.error})
            emit("no_text", label, text.error)
            continue

        result = await extract_review(text.text, paper, backend, model=resolved_model)
        if not result.ok:
            report.no_claims += 1
            reason = result.error or f"0 of {result.proposed} claims verified"
            report.failures.append({"paper": label, "stage": "extract", "error": reason})
            emit("no_claims", label, reason)
            continue

        result.review.access_license = paper.raw.get("license", "") if isinstance(paper.raw, dict) else ""
        outcome = corpus.add_review(conn, result.review, extraction=result.to_dict())
        report.keys.append(outcome.key)
        report.stored += 1

        rate = result.first_pass_rejection_rate
        emit(
            "stored",
            label,
            f"{outcome.claims} claims kept, {result.dropped} dropped "
            f"({'—' if rate is None else f'{rate:.1%}'} of first-pass rejected) [{text.origin}]"
            + ("" if outcome.added else " (replaced)"),
        )

    return report


# ── turning a target into papers (`e2er library add`, the Library page) ─────


def paper_from_pdf(path: Path) -> PaperMetadata:
    """Read a local PDF's own metadata rather than guessing from its filename.

    `extract_pdf_metadata` pulls title, authors, DOI and year out of the
    document — from DocInfo, falling back to the first page. Using `path.stem`
    instead, as this did, meant a paper was titled "1-s2.0-S0378426619301..."
    with no DOI and no authors: unciteable, and impossible to deduplicate
    against the same paper arriving from the web.
    """
    from .local_pdf_meta import extract_pdf_metadata

    meta = extract_pdf_metadata(path)
    meta.pdf_path = str(path)
    meta.source = meta.source or "byod_pdf"
    return meta


def papers_from_folder(folder: Path, *, recursive: bool) -> list[PaperMetadata]:
    """Every PDF in a folder, with its own metadata."""
    from ..local_corpus import PDF_EXTENSIONS, iter_corpus_files

    papers = [paper_from_pdf(pdf) for _root, pdf in iter_corpus_files([folder], PDF_EXTENSIONS, recursive=recursive)]
    logger.info("corpus: %d PDF(s) found under %s", len(papers), folder)
    return papers


async def papers_for_target(target: str, *, limit: int | None, search: bool) -> list[PaperMetadata]:
    """Turn a DOI, a file path, or a query into papers to extract from."""
    from ...config import get_settings
    from .registry import doi_fetch_sources, search_sources

    settings = get_settings()

    path = Path(target).expanduser()

    # A folder of PDFs — the researcher's own library, or a paper's staged
    # `literature/` folder. This is the primary case, not a convenience: papers
    # you already have are always readable, whereas roughly two in five web hits
    # are behind a paywall or resolve to a landing page.
    if path.is_dir():
        # No default cap here. Truncating a folder to ten would silently ignore
        # most of a researcher's library and look like the tool losing papers;
        # an explicit --limit still applies, for trying a big folder out first.
        in_folder = papers_from_folder(path, recursive=True)
        return in_folder[:limit] if limit else in_folder

    if path.is_file() and path.suffix.lower() == ".pdf":
        return [paper_from_pdf(path)]

    if not search and ("/" in target and target.lower().startswith(("10.", "doi:", "http"))):
        doi = corpus.normalize_doi(target)
        for source in doi_fetch_sources(settings):
            try:
                found = await source.fetch(doi)
            except Exception as e:
                logger.debug("DOI fetch via %s failed: %s", getattr(source, "name", source), e)
                continue
            if found is not None:
                return [found]
        return []

    # Ask every source, then interleave round-robin so each one contributes to
    # the limit.
    #
    # Taking the first provider's hits until the limit fills sounds reasonable
    # and is not: on a real run, five OpenAlex records filled it, every one of
    # their "open access" URLs was a publisher landing page, and arXiv — which
    # serves actual PDFs — was never reached. Zero papers stored from a query
    # with plenty of readable matches.
    #
    # Ranking by "has a pdf_url" does not fix it either, because the landing
    # pages have one too. Interleaving is provider-agnostic: it preserves each
    # source's own ordering and only refuses to let one of them monopolise the
    # budget.
    # A web search is unbounded, so it always needs a cap.
    capped = limit or DEFAULT_LIMIT
    per_source: list[list[PaperMetadata]] = []
    for source in search_sources(settings):
        try:
            result = await source.search(target, capped)
        except Exception as e:
            logger.warning("literature search via %s failed: %s", getattr(source, "name", source), e)
            continue
        per_source.append(list(result.papers))

    papers: list[PaperMetadata] = []
    seen: set[str] = set()
    for rank in range(capped):
        for bucket in per_source:
            if rank >= len(bucket):
                continue
            paper = bucket[rank]
            ident = corpus.normalize_doi(paper.doi) or paper.title.lower()
            if not ident or ident in seen:
                continue
            seen.add(ident)
            papers.append(paper)
    return papers[:capped]
