"""Literature module — BibTeX parsing and bibliography management."""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from .models import PaperMetadata

logger = get_logger(__name__)


def parse_bibtex_file(bib_path: Path) -> list[PaperMetadata]:
    """Parse a .bib file and return PaperMetadata for each entry.

    Uses bibtexparser v2's `parse_file` API. The v1 `bibtexparser.load(f, ...)`
    call no longer exists.
    """
    try:
        import bibtexparser

        library = bibtexparser.parse_file(str(bib_path))
        # v2 Entry → flat str dict, matching what _entry_to_metadata expects.
        papers = [_entry_to_metadata({k: v.value for k, v in entry.fields_dict.items()}) for entry in library.entries]
        logger.info("Parsed %d entries from %s", len(papers), bib_path)
        return papers
    except ImportError:
        logger.warning("bibtexparser not installed — cannot parse .bib file")
        return []
    except Exception as e:
        logger.warning("Failed to parse %s: %s", bib_path, e)
        return []


def merge_bibtex_with_literature(
    provided: list[PaperMetadata],
    fetched: list[PaperMetadata],
) -> list[PaperMetadata]:
    """Merge user-provided BibTeX entries with fetched literature.
    User-provided entries take precedence (they may have better metadata).
    """
    result = list(provided)
    seen_dois = {p.doi.lower() for p in provided if p.doi}

    for paper in fetched:
        key = paper.doi.lower() if paper.doi else ""
        if key and key in seen_dois:
            continue
        result.append(paper)
        if key:
            seen_dois.add(key)

    return result


def papers_to_bibtex(papers: list[PaperMetadata]) -> str:
    """Render a list of PaperMetadata to a complete .bib file string."""
    return "\n\n".join(p.to_bibtex() for p in papers)


def _entry_to_metadata(entry: dict) -> PaperMetadata:
    raw_year = entry.get("year", "")
    try:
        year = int(raw_year)
    except (ValueError, TypeError):
        year = None

    authors_raw = entry.get("author", "")
    authors = [a.strip() for a in authors_raw.split(" and ")] if authors_raw else []

    return PaperMetadata(
        title=entry.get("title", "").strip("{}"),
        authors=authors,
        year=year,
        doi=entry.get("doi", ""),
        abstract=entry.get("abstract", ""),
        journal=entry.get("journal", entry.get("booktitle", "")),
        url=entry.get("url", ""),
        source="bibtex",
        raw=entry,
    )
