"""Literature module — shared data models."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: ``PaperMetadata.source`` values that mean the researcher brought the paper (their PDFs, .bib,
#: Zotero, the Library or an upload). Anything else was found by a web search.
RESEARCHER_SOURCES = frozenset({"bibtex", "byod_pdf", "zotero_local", "zotero", "library", "corpus", "upload"})

#: The field in literature.bib (and refs.bib) that says where an entry came from: ``researcher`` or ``web``.
#: BibTeX ignores fields it does not know, so the tag travels with the entry into the export and the dossier.
SOURCE_FIELD = "e2er_source"

#: A key BibTeX accepts as it is: no spaces, commas, braces, quotes or the characters TeX treats specially.
_VALID_KEY = re.compile(r"^[A-Za-z0-9_:.+/-]+$")


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
    # The key the researcher's own .bib gives the entry. Kept as it is, so the paper cites the
    # researcher's keys; empty for everything else, which gets the derived key below.
    cite_key: str = ""

    @property
    def origin(self) -> str:
        """``researcher`` (the researcher's own papers) or ``web`` (a web search found it)."""
        if (self.raw or {}).get("e2er_origin") in {"researcher", "web"}:
            return str(self.raw["e2er_origin"])
        return "researcher" if self.source in RESEARCHER_SOURCES else "web"

    @property
    def bibtex_key(self) -> str:
        if self.cite_key and _VALID_KEY.match(self.cite_key):
            return self.cite_key
        # Alphanumeric only: BibTeX keys can't contain '.', spaces, etc.
        # A no-year item used to yield "…n.d.…" and a punctuated surname/word
        # produced keys the \cite{} could never resolve against.
        last = (self.authors[0].split()[-1] if self.authors else "unknown").lower()
        # "Pérez-Orive" → "perezorive", not "prezorive".
        last = unicodedata.normalize("NFKD", last).encode("ascii", "ignore").decode()
        year = str(self.year) if self.year else "nd"
        word = self.title.split()[0].lower() if self.title else "paper"
        key = re.sub(r"[^a-z0-9]", "", f"{last}{year}{word}")
        return key or "ref"

    def to_bibtex(self) -> str:
        from ...core.bibliography import tex_escape  # & in "S&P 500" or "Banking & Finance" stops LaTeX

        own = self.source == "bibtex"  # an entry of the researcher's .bib: its type and fields are kept
        raw = self.raw or {}
        etype = str(raw.get("ENTRYTYPE") or "article") if own else "article"
        if not re.fullmatch(r"[A-Za-z]+", etype):
            etype = "article"
        authors_str = " and ".join(self.authors) if self.authors else "Unknown"
        # The researcher's own title and authors stay as written (their braces and escapes included).
        title = str(raw["title"]) if own and raw.get("title") else tex_escape(self.title)
        author = str(raw["author"]) if own and raw.get("author") else tex_escape(authors_str)
        lines = [
            f"@{etype}{{{self.bibtex_key},",
            f"  title = {{{title}}},",
            f"  author = {{{author}}},",
        ]
        if self.year:
            lines.append(f"  year = {{{self.year}}},")
        if self.journal and (not own or "journal" in raw):
            lines.append(f"  journal = {{{tex_escape(self.journal)}}},")
        if self.doi:
            lines.append(f"  doi = {{{self.doi}}},")
        if self.url:
            lines.append(f"  url = {{{self.url}}},")
        if own:
            # The fields the ones above do not cover (booktitle, volume, pages, publisher, …), as written.
            done = {"title", "author", "year", "journal", "doi", "url", "abstract", "file", SOURCE_FIELD}
            for name, value in raw.items():
                low = str(name).lower()
                # e2er's own markers (e2er_*, the file a paper came from) are not fields of the entry.
                internal = low.startswith("e2er_") or low in {"source_pdf", "zotero_key", "library_key", "filename"}
                if low in done or internal or name in {"ENTRYTYPE", "ID"} or not str(value).strip():
                    continue
                if re.fullmatch(r"[a-z][a-z0-9_-]*", low):
                    lines.append(f"  {low} = {{{value}}},")
        lines.append(f"  {SOURCE_FIELD} = {{{self.origin}}},")
        lines.append("}")
        return "\n".join(lines)


@dataclass
class SearchResult:
    papers: list[PaperMetadata]
    source: str
    query: str
    total_found: int = 0
