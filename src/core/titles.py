"""A paper's title as a researcher reads it, and whether the title is a title at all.

Titles come from PDFs, .bib files, Zotero and the Library, and many are not
fit to show. The 2026-10-10 live run's New study listed, among Björn's Library:
"C:\\Working Papers\\10449.wpd" (the typesetting file's name), "J Evol Econ
(2013) 23:925–953" (the page header), "PII: S1573-4412(84)02014-6",
"Credible, Optimal Auctions via Public Broadcast Tarun Chitra ∗ Matheus V. X.
Ferreira † …" (the authors and their footnote marks), and .bib titles with
their braces ("{Federal Reserve}").

:func:`clean` removes what is markup (braces, LaTeX commands, footnote marks
and the author names they follow, "Accepted Version" banners). :func:`unusable`
says when what is left is not a title (a file name, a journal citation or page
header, an identifier). :func:`display_title` then takes the title of the
paper's DOI record (OpenAlex, kept in ``~/.e2er/title_cache.json``) when there
is a DOI, and says "(title not readable)" when there is none.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

#: Footnote marks authors put after their names (and some PDFs after the title).
_MARKS = "∗†‡§¶⋆★✝"
_MARK_RE = re.compile(rf"\s*[{_MARKS}]")
_LATEX_CMD = re.compile(r"\\(?:emph|textit|textbf|textsc|texttt|mathrm|text)\{([^{}]*)\}")
_LATEX_ACCENT = re.compile(r"\{?\\[`'^\"~=.uvHtcdbk]\s*\{?([A-Za-z])\}?\}?")
_LATEX_ESCAPED = re.compile(r"\\([&%$#_])")
_BANNERS = re.compile(
    r"\s+(?:Article\s+Accepted\s+Version|Accepted\s+Version|Published\s+Version|Author\s+Accepted\s+Manuscript|"
    r"Working\s+Paper\s+Series|Discussion\s+Paper|Preprint)\b.*$",
    re.IGNORECASE,
)
_TRAILING_DATE = re.compile(
    r"[\s,;:–-]+(?:this\s+(?:version|draft)[:\s]*)?(?:\d{1,2}\s+)?"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+\d{1,2},?)?\s+\d{4}\s*$",
    re.IGNORECASE,
)
#: A person's name at the end of a cut title: "… Market Makers Jun Aoyagi" (First [M.] Last).
_TRAILING_NAME = re.compile(r"\s+[A-Z][a-z'’-]+(?:\s+(?:[A-Z]\.\s*)+)?\s+[A-Z][A-Za-z'’-]+$")

_FILE_NAME = re.compile(r"(?:^[A-Za-z]:[\\/]?|\\|\.(?:wpd|dvi|indd|pdf|docx?|tex|ps|rtf|qxd)\b)", re.IGNORECASE)
_NOT_A_TITLE = [
    re.compile(r"^\s*(?:PII|DOI|ISSN|ISBN|arXiv)\s*:", re.IGNORECASE),
    re.compile(r"^\s*Cite\s+(?:as|this)", re.IGNORECASE),
    re.compile(r"\(\d{4}\)\s*\d+\s*[:(]"),  # J Evol Econ (2013) 23:925–953 · Electronic Markets (2024) 34:42
    re.compile(r"\bVolume\s+\d+\s*,\s*Issue\b|\bISSN\s+\d{4}", re.IGNORECASE),
    re.compile(r"^\s*Munich Personal RePEc Archive\s*$", re.IGNORECASE),
]

#: Shown for a paper without a readable title and without a DOI to look one up by.
NOT_READABLE = "(title not readable)"


def clean(raw: str) -> str:
    """The title without markup: braces, LaTeX, footnote marks with the author names before them, banners, dates."""
    t = " ".join(str(raw or "").replace("\xa0", " ").split())
    t = _LATEX_CMD.sub(r"\1", t)
    t = _LATEX_ACCENT.sub(r"\1", t)
    t = _LATEX_ESCAPED.sub(r"\1", t)
    t = t.replace("{", "").replace("}", "").replace("\\", "")
    m = _MARK_RE.search(t)
    if m:
        # Everything from the first footnote mark on is the authors and their notes; the name just
        # before the mark is the first author's.
        head = t[: m.start()].rstrip(" ,;")
        trimmed = _TRAILING_NAME.sub("", head)
        t = trimmed if len(trimmed.split()) >= 3 else head
    t = _BANNERS.sub("", t)
    t = _TRAILING_DATE.sub("", t)
    return " ".join(t.split()).strip(" ,;:-–")


def unusable(title: str) -> bool:
    """Is this not a title: a file name, a journal citation or page header, an identifier, nothing?"""
    t = clean(title)
    if len(re.findall(r"[A-Za-z]", t)) < 6:
        return True
    if _FILE_NAME.search(t):
        return True
    return any(p.search(t) for p in _NOT_A_TITLE)


def _cache_file() -> Path:
    from ..home import state_dir

    return state_dir() / "title_cache.json"


def _read_cache() -> dict[str, str]:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(cache: dict[str, str]) -> None:
    try:
        f = _cache_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass


def title_by_doi(doi: str) -> str:
    """The title of the DOI's record (OpenAlex, else Crossref), cached; "" when it cannot be found."""
    key = doi.strip().lower()
    if not key:
        return ""
    cache = _read_cache()
    if key in cache:
        return cache[key]
    import asyncio

    from ..modules.literature import crossref, openalex

    try:
        asyncio.get_running_loop()
        return ""  # inside the server's event loop: only what is cached (New study's list fills the cache)
    except RuntimeError:
        pass

    async def look() -> str:
        for fetch in (openalex.fetch_by_doi, crossref.fetch_by_doi):
            try:
                hit = await asyncio.wait_for(fetch(key), timeout=8)
            except Exception:  # noqa: BLE001 — offline, rate-limited: no title
                continue
            if hit is not None and hit.title:
                return clean(hit.title)
        return ""

    found = asyncio.run(look())
    if found:
        cache[key] = found
        _write_cache(cache)
    return found


def display_title(raw: str, doi: str = "", *, lookup: bool = True) -> str:
    """The title to show: cleaned; from the DOI record when the paper's own is not a title or still has author
    footnotes in it; "(title not readable)" when neither gives one."""
    t = clean(raw)
    dirty = unusable(raw) or bool(_MARK_RE.search(str(raw or "")))
    if dirty and doi and lookup:
        better = title_by_doi(doi)
        if better and not unusable(better):
            return better
    if unusable(raw):
        return NOT_READABLE
    return t
