"""Hand the pipeline what the field already found, instead of a reading list.

``acquire_literature`` writes ``literature.bib``: thirty entries establishing
that thirty papers exist. A drafter given that can cite plausibly and nothing
more — it has read the metadata and is guessing at the content, which is how a
related-work section ends up describing papers nobody read.

If a corpus has been built, the same run can have something better: the claims
those papers actually make, each with the sentence it came from. This module is
the bridge. It reads, and never writes to the corpus — a paper run is not the
place to silently spend a model call per reference, so contributing back is
``e2er corpus add``, which the person chose to run.

Degrades to nothing. No corpus, an empty one, or no matching claims all produce
zero files and the pipeline behaves exactly as it did before.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ...logging_config import get_logger
from .corpus import ClaimHit, PaperRow, connect, corpus_path, get_papers, search_claims
from .models import PaperMetadata

logger = get_logger(__name__)

EVIDENCE_FILENAME = "corpus_evidence.md"

#: Claims pulled per query. Enough to be worth reading, small enough that the
#: file stays inside a prompt alongside everything else the drafter is given.
DEFAULT_PER_QUERY = 25

#: Order fields the way a reader wants them, not alphabetically.
_FIELD_ORDER = (
    "key_findings",
    "research_question",
    "hypotheses",
    "theoretical_framework",
    "methodology",
    "sample",
    "data_sources",
    "limitations",
    "implications",
)

_FIELD_LABELS = {
    "key_findings": "Findings",
    "research_question": "Research questions",
    "hypotheses": "Hypotheses",
    "theoretical_framework": "Theoretical framing",
    "methodology": "Methods",
    "sample": "Samples",
    "data_sources": "Data",
    "limitations": "Limitations the authors concede",
    "implications": "Implications",
}


@dataclass
class CorpusEvidence:
    """Verified claims from the corpus that bear on this paper's question."""

    hits: list[ClaimHit] = field(default_factory=list)
    papers: dict[str, PaperRow] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.hits)

    def as_metadata(self) -> list[PaperMetadata]:
        """The cited papers, in the shape ``literature.bib`` is written from."""
        return [
            PaperMetadata(
                title=p.title,
                authors=list(p.authors),
                year=p.year,
                doi=p.doi,
                source=p.source or "corpus",
            )
            for p in self.papers.values()
        ]


def gather(
    queries: list[str],
    *,
    db: str | Path | None = None,
    per_query: int = DEFAULT_PER_QUERY,
    conn: sqlite3.Connection | None = None,
) -> CorpusEvidence:
    """Find corpus claims bearing on these queries. Never raises.

    A missing or unreadable corpus is the normal case for a first-time user and
    must cost nothing — not a warning the person has to learn to ignore, and
    certainly not a failed run.
    """
    wanted = [q.strip() for q in queries if q and q.strip()]
    if not wanted:
        return CorpusEvidence()

    if conn is not None:
        return _gather(conn, wanted, per_query)

    path = corpus_path(db)
    if not path.is_file():
        logger.debug("no corpus at %s — pipeline continues without it", path)
        return CorpusEvidence()

    try:
        with connect(path) as opened:
            return _gather(opened, wanted, per_query)
    except sqlite3.Error as e:
        logger.warning("corpus at %s unreadable (%s) — continuing without it", path, e)
        return CorpusEvidence()


def _gather(conn: sqlite3.Connection, queries: list[str], per_query: int) -> CorpusEvidence:
    hits: list[ClaimHit] = []
    seen: set[tuple[str, str]] = set()

    for query in queries:
        for hit in search_claims(conn, query, limit=per_query):
            ident = (hit.key, hit.quote)
            if ident in seen:
                continue
            seen.add(ident)
            hits.append(hit)

    papers = get_papers(conn, sorted({h.key for h in hits}))
    return CorpusEvidence(hits=hits, papers=papers, queries=queries)


def _one_line(text: str) -> str:
    """Flatten a quote onto one line for display.

    Quotes are verbatim spans of PDF text and routinely contain newlines mid
    sentence. Emitted as-is, the second line of a quote loses its `>` prefix and
    the blockquote silently breaks apart — the quote stops looking like a quote,
    which is the one thing this file is for. Verification normalises whitespace
    on both sides anyway, so a flattened quote still matches its source.
    """
    return " ".join((text or "").split())


def render_markdown(evidence: CorpusEvidence) -> str:
    """Group the claims by paper, then by field, with every quote attached.

    By paper rather than by field because a reader building on this needs to
    know which claims come from the same study — two findings from one paper are
    one piece of evidence, and a section grouped by field hides that.
    """
    if not evidence.ok:
        return ""

    by_paper: dict[str, list[ClaimHit]] = {}
    for hit in evidence.hits:
        by_paper.setdefault(hit.key, []).append(hit)

    def sort_key(item: tuple[str, list[ClaimHit]]) -> tuple[int, str]:
        paper = evidence.papers.get(item[0])
        return (-(paper.year or 0) if paper else 0, paper.title if paper else item[0])

    lines = [
        "# Evidence from the corpus",
        "",
        "Claims extracted from papers in the local corpus, each with the verbatim",
        "sentence it came from. Every quote below was located in the source text;",
        "claims whose quotes could not be found were discarded before storage.",
        "",
        "Cite these papers from `literature.bib`. Quote them as written here — the",
        "quotes are exact, and the citation gate checks what you cite.",
        "",
        f"Matched on: {'; '.join(evidence.queries)}",
        "",
        f"{len(evidence.hits)} claim(s) from {len(by_paper)} paper(s).",
        "",
    ]

    for key, claims in sorted(by_paper.items(), key=sort_key):
        paper = evidence.papers.get(key)
        title = paper.title if paper else key
        year = paper.year if paper else None
        authors = ", ".join(paper.authors[:3]) if paper and paper.authors else ""
        if paper and paper.authors and len(paper.authors) > 3:
            authors += " et al."

        lines.append(f"## {title}")
        byline = " · ".join(x for x in [authors, str(year) if year else "", paper.doi if paper else ""] if x)
        if byline:
            lines.append(f"*{byline}*")
        lines.append("")

        ordered = sorted(
            claims,
            key=lambda c: _FIELD_ORDER.index(c.field) if c.field in _FIELD_ORDER else len(_FIELD_ORDER),
        )
        current = ""
        for claim in ordered:
            if claim.field != current:
                if current:
                    lines.append("")  # a heading run-on to the previous bullet reads as one block
                current = claim.field
                lines.append(f"**{_FIELD_LABELS.get(current, current)}**")
                lines.append("")
            lines.append(f"- {_one_line(claim.text)}")
            locator = f" — {claim.locator}" if claim.locator else ""
            lines.append(f'  > "{_one_line(claim.quote)}"{locator}')
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_evidence(workspace: Path, evidence: CorpusEvidence) -> Path | None:
    """Write the evidence file into the paper's literature/ folder.

    Returns the path, or None when there was nothing to write — an empty file
    would read like a corpus that was consulted and had nothing to say, which is
    not distinguishable by a reader from one that was never built.
    """
    if not evidence.ok:
        return None

    target = Path(workspace) / "literature" / EVIDENCE_FILENAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(evidence), encoding="utf-8")
    except OSError as e:
        logger.warning("could not write %s: %s", target, e)
        return None

    logger.info(
        "corpus evidence: %d claim(s) from %d paper(s) written to %s",
        len(evidence.hits),
        len(evidence.papers),
        target.name,
    )
    return target
