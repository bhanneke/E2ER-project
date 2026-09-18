"""Literature module — shared data models."""

from __future__ import annotations

import re
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
    source: str = ""  # "openalex", "semantic_scholar", "arxiv", "bibtex", "byod_pdf", "zotero_local"
    citations: int = 0
    # Workspace-relative path to a staged PDF (BYOD/Zotero discovery), readable
    # via the read_reference tool. Empty for web-sourced metadata.
    pdf_path: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def bibtex_key(self) -> str:
        # Alphanumeric only: BibTeX keys can't contain '.', spaces, etc.
        # A no-year item used to yield "…n.d.…" and a punctuated surname/word
        # produced keys the \cite{} could never resolve against.
        last = (self.authors[0].split()[-1] if self.authors else "unknown").lower()
        year = str(self.year) if self.year else "nd"
        word = self.title.split()[0].lower() if self.title else "paper"
        key = re.sub(r"[^a-z0-9]", "", f"{last}{year}{word}")
        return key or "ref"

    def to_bibtex(self) -> str:
        authors_str = " and ".join(self.authors) if self.authors else "Unknown"
        lines = [
            f"@article{{{self.bibtex_key},",
            f"  title = {{{self.title}}},",
            f"  author = {{{authors_str}}},",
        ]
        if self.year:
            lines.append(f"  year = {{{self.year}}},")
        if self.journal:
            lines.append(f"  journal = {{{self.journal}}},")
        if self.doi:
            lines.append(f"  doi = {{{self.doi}}},")
        if self.url:
            lines.append(f"  url = {{{self.url}}},")
        lines.append("}")
        return "\n".join(lines)


@dataclass
class SearchResult:
    papers: list[PaperMetadata]
    source: str
    query: str
    total_found: int = 0
