"""Literature module — shared data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperMetadata:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str = ""
    abstract: str = ""
    journal: str = ""
    url: str = ""
    pdf_url: str = ""
    source: str = ""  # "openalex", "semantic_scholar", "arxiv", "bibtex"
    citations: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def bibtex_key(self) -> str:
        last = (self.authors[0].split()[-1] if self.authors else "unknown").lower()
        year = self.year or "n.d."
        word = self.title.split()[0].lower() if self.title else "paper"
        return f"{last}{year}{word}"

    def to_bibtex(self) -> str:
        authors_str = " and ".join(self.authors) if self.authors else "Unknown"
        lines = [
            f"@article{{{self.bibtex_key},",
            f'  title = {{{self.title}}},',
            f'  author = {{{authors_str}}},',
        ]
        if self.year:
            lines.append(f'  year = {{{self.year}}},')
        if self.journal:
            lines.append(f'  journal = {{{self.journal}}},')
        if self.doi:
            lines.append(f'  doi = {{{self.doi}}},')
        if self.url:
            lines.append(f'  url = {{{self.url}}},')
        lines.append("}")
        return "\n".join(lines)


@dataclass
class SearchResult:
    papers: list[PaperMetadata]
    source: str
    query: str
    total_found: int = 0
