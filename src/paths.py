"""Forgiving path input, and what a folder holds.

A researcher pastes paths the way the desktop hands them over: dragged from
Finder (``/Users/me/My\\ Library.bib``), copied with quotes (``'/Users/me/x'``),
or copied together with the terminal prompt in front of it (``❯ /Users/me/x``).
Every prompt and flag that takes a path runs the answer through
:func:`clean_path_input` first, so none of these fails as "not found".

:func:`inspect_literature` and :func:`inspect_data` say what a file or folder
holds. The terminal setup and the browser setup both use them, so the two
cannot disagree about what counts as a library.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

#: Prompt glyphs a terminal puts in front of a line. Copying a line from the
#: terminal copies these along with the path.
PROMPT_GLYPHS = ("❯", "›", "»", "➜", "→", "$", "%", ">", "#")

#: Glyphs that are never the first character of a real path, so they are
#: stripped even when no space follows (``❯/Users/me``).
_ALWAYS_STRIP = ("❯", "›", "»", "➜", "→")

_QUOTES = {'"': '"', "'": "'", "“": "”", "‘": "’"}

#: Data files e2er imports from a data folder (as the doctor counts them).
DATA_EXTS = frozenset({".csv", ".tsv", ".jsonl", ".parquet", ".xlsx", ".xls", ".json", ".txt"})

#: Stop counting after this many files, so pointing at a huge folder stays fast.
_WALK_LIMIT = 50_000


def clean_path_input(raw: str | None) -> str:
    """The path a person meant, from what they pasted.

    Strips surrounding whitespace, a leading terminal prompt glyph, surrounding
    quotes, the backslash escapes a drag-and-drop adds (``My\\ Library``), a
    ``file://`` prefix, and expands ``~``. Returns ``""`` for empty input. The
    path is not required to exist.
    """
    if raw is None:
        return ""
    s = raw.strip()
    # A prompt glyph, possibly several ("$ ❯ path"), each followed by space.
    changed = True
    while s and changed:
        changed = False
        for g in PROMPT_GLYPHS:
            if s.startswith(g):
                rest = s[len(g) :]
                if g in _ALWAYS_STRIP or (rest[:1].isspace()):
                    s = rest.strip()
                    changed = True
                    break
    # Surrounding quotes.
    if len(s) >= 2 and s[0] in _QUOTES and s.endswith(_QUOTES[s[0]]):
        s = s[1:-1].strip()
    # file:// URLs (dragged from some apps).
    if s.startswith("file://"):
        s = unquote(s[len("file://") :])
        if s.startswith("localhost/"):
            s = s[len("localhost") :]
    # Backslash escapes from drag-and-drop in a POSIX terminal. On Windows the
    # backslash is the separator and must stay.
    if os.name != "nt" and "\\" in s:
        s = re.sub(r"\\(.)", r"\1", s)
    if s.startswith("~"):
        s = os.path.expanduser(s)
    return s


def to_path(raw: str | None) -> Path | None:
    """:func:`clean_path_input`, as a Path; None for empty input."""
    s = clean_path_input(raw)
    return Path(s) if s else None


def _walk_files(root: Path, limit: int = _WALK_LIMIT) -> Iterator[Path]:
    """Files under ``root``: hidden ones and symlinked folders are skipped."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            n += 1
            if n > limit:
                return
            yield Path(dirpath) / name


def bib_entry_count(path: Path) -> int:
    """Number of entries in a BibTeX file (lines starting with ``@``, minus @comment/@string/@preamble)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    n = 0
    for line in text.splitlines():
        stripped = line.lstrip().lower()
        if stripped.startswith("@") and not stripped.startswith(("@comment", "@string", "@preamble")):
            n += 1
    return n


@dataclass
class Literature:
    """What a literature path holds, and the settings it becomes.

    ``kind`` is one of ``bib`` (a .bib file), ``zotero_export`` (a folder with a
    .bib and a ``files/`` folder of attachments), ``zotero_library`` (a Zotero
    data folder with ``zotero.sqlite``), ``pdf_folder`` (a folder of PDFs, maybe
    with one .bib), ``many_bibs`` (a folder with several .bib files and no PDFs),
    ``empty`` (a folder with neither), ``not_bib`` (a file that is not .bib),
    or ``missing``.
    """

    path: str
    kind: str
    bib: str = ""
    bibs: list[str] = field(default_factory=list)
    n_references: int = 0
    n_pdfs: int = 0
    message: str = ""

    @property
    def usable(self) -> bool:
        return self.kind in {"bib", "zotero_export", "zotero_library", "pdf_folder"}

    def settings(self) -> dict[str, str]:
        """The .env keys this literature sets (LITERATURE_BIBTEX_FILE / LITERATURE_DIR)."""
        out: dict[str, str] = {}
        if self.bib:
            out["LITERATURE_BIBTEX_FILE"] = self.bib
        if self.kind in {"zotero_export", "zotero_library", "pdf_folder"}:
            out["LITERATURE_DIR"] = self.path
        return out

    def summary(self) -> str:
        parts = []
        if self.bib:
            parts.append(f"{self.n_references} reference{'s' if self.n_references != 1 else ''}")
        if self.n_pdfs:
            parts.append(f"{self.n_pdfs} PDF{'s' if self.n_pdfs != 1 else ''}")
        return ", ".join(parts)


def inspect_literature(raw: str | Path) -> Literature:
    """Say what a file or folder the researcher chose as their literature holds."""
    s = clean_path_input(str(raw)) if not isinstance(raw, Path) else str(raw)
    p = Path(s)
    if not s or not p.exists():
        return Literature(s, "missing", message=f"Nothing found at {s or '(empty)'}.")
    if p.is_file():
        if p.suffix.lower() == ".bib":
            n = bib_entry_count(p)
            return Literature(
                str(p), "bib", bib=str(p), bibs=[str(p)], n_references=n, message=f"A BibTeX file with {n} references."
            )
        return Literature(
            str(p),
            "not_bib",
            message=f"That is a {p.suffix or 'file without an extension'} file. "
            "Expected a .bib file, a Zotero export folder or a folder of PDFs.",
        )
    # A folder.
    if (p / "zotero.sqlite").is_file():
        n_pdf = (
            sum(1 for f in _walk_files(p / "storage") if f.suffix.lower() == ".pdf") if (p / "storage").is_dir() else 0
        )
        return Literature(str(p), "zotero_library", n_pdfs=n_pdf, message=f"A Zotero library with {n_pdf} PDFs.")
    bibs = sorted(
        str(f) for f in p.iterdir() if f.is_file() and f.suffix.lower() == ".bib" and not f.name.startswith(".")
    )
    n_pdf = sum(1 for f in _walk_files(p) if f.suffix.lower() == ".pdf")
    if len(bibs) == 1:
        bib = bibs[0]
        n = bib_entry_count(Path(bib))
        if (p / "files").is_dir():
            return Literature(
                str(p),
                "zotero_export",
                bib=bib,
                bibs=bibs,
                n_references=n,
                n_pdfs=n_pdf,
                message=f"A Zotero export: {Path(bib).name} with {n} references and {n_pdf} PDFs.",
            )
        return Literature(
            str(p),
            "pdf_folder",
            bib=bib,
            bibs=bibs,
            n_references=n,
            n_pdfs=n_pdf,
            message=f"A folder with {Path(bib).name} ({n} references) and {n_pdf} PDFs.",
        )
    if len(bibs) > 1 and not n_pdf:
        names = ", ".join(Path(b).name for b in bibs[:5])
        return Literature(
            str(p),
            "many_bibs",
            bibs=bibs,
            message=f"That folder has {len(bibs)} .bib files ({names}). Pick one of them.",
        )
    if n_pdf:
        extra = f" and {len(bibs)} .bib files" if bibs else ""
        return Literature(str(p), "pdf_folder", bibs=bibs, n_pdfs=n_pdf, message=f"A folder of {n_pdf} PDFs{extra}.")
    return Literature(str(p), "empty", message="That folder has no .bib file and no PDFs.")


@dataclass
class DataFolder:
    path: str
    ok: bool
    files: list[str] = field(default_factory=list)
    message: str = ""


def inspect_data(raw: str | Path, limit: int = 200) -> DataFolder:
    """The data files a folder holds (top level, as e2er stages them)."""
    s = clean_path_input(str(raw)) if not isinstance(raw, Path) else str(raw)
    p = Path(s)
    if not s or not p.exists():
        return DataFolder(s, False, message=f"Nothing found at {s or '(empty)'}.")
    if not p.is_dir():
        return DataFolder(str(p), False, message="That is a file. Choose the folder that holds your data files.")
    files = sorted(
        f.name
        for f in p.iterdir()
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in DATA_EXTS | {".bib"}
    )
    if not files:
        return DataFolder(
            str(p), True, [], "No data files here yet (csv, tsv, xlsx, parquet, json, txt). You can add them later."
        )
    return DataFolder(str(p), True, files[:limit], f"{len(files)} data file{'s' if len(files) != 1 else ''}.")


@dataclass
class BibAnswer:
    """The outcome of resolving a typed answer to "where is your .bib file?"."""

    bib: str = ""  # the .bib to use, when one was found without asking
    ask: str = ""  # a yes/no question to confirm a candidate (``candidate`` holds it)
    candidate: str = ""
    literature: Literature | None = None  # set when the answer is a whole library (folder of PDFs, Zotero)
    error: str = ""


def resolve_bib_answer(raw: str) -> BibAnswer:
    """Turn what someone typed at a .bib prompt into a .bib, a question, or an explanation.

    A folder with exactly one .bib (or a Zotero export folder) is accepted with a
    confirmation; a folder of PDFs is accepted as a library of its own.
    """
    s = clean_path_input(raw)
    if not s:
        return BibAnswer()
    lit = inspect_literature(Path(s))
    if lit.kind == "bib":
        return BibAnswer(bib=lit.bib, literature=lit)
    if lit.kind in {"zotero_export", "pdf_folder"} and lit.bib:
        return BibAnswer(
            ask=f"That is a folder. It contains {Path(lit.bib).name} — use it?", candidate=lit.bib, literature=lit
        )
    if lit.kind in {"pdf_folder", "zotero_library"}:
        return BibAnswer(ask=f"That is a folder: {lit.message} Use it as your literature?", literature=lit)
    if lit.kind == "missing":
        hint = ""
        if raw.strip() != s:
            hint = f" (read as {s})"
        return BibAnswer(error=f"Expected a .bib file or a folder. Nothing exists at {s}{hint}.")
    return BibAnswer(error=f"Expected a .bib file or a folder that contains one. {lit.message}")
