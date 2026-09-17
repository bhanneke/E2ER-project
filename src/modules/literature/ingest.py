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
from typing import Any

from ...logging_config import get_logger
from . import corpus
from .models import PaperMetadata

logger = get_logger(__name__)

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
