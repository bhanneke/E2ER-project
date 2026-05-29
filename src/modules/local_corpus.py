"""Helpers for the ``LOCAL_DATA_DIR`` corpus.

A researcher's reusable BYOD corpus — data files, ``.bib`` and PDFs — lives
in one (or several) local folder(s). These helpers parse the env var
(possibly comma-separated) and walk the folder(s), optionally recursing.

The corpus has three file kinds with different consumers:
  - data files (csv/tsv/jsonl/parquet/xlsx/txt) → symlinked into
    ``workspace/<paper_id>/data/`` at paper creation.
  - ``.bib`` → merged into the reference summary alongside
    ``LITERATURE_BIBTEX_FILE`` by ``LocalBibLibrary``.
  - PDFs → symlinked into ``workspace/<paper_id>/literature/`` so the
    ``read_reference`` tool can extract them by local path.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

DATA_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv", ".jsonl", ".parquet", ".xlsx", ".txt"})
BIB_EXTENSIONS: frozenset[str] = frozenset({".bib"})
PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


def parse_corpus_roots(setting: str | None) -> list[Path]:
    """Parse the LOCAL_DATA_DIR value (comma-separated paths allowed) into
    the list of existing directories, with ``~`` expanded. Missing entries
    are silently dropped — misconfig must not break paper creation."""
    if not setting:
        return []
    roots: list[Path] = []
    for raw in setting.split(","):
        candidate = Path(raw.strip()).expanduser()
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def iter_corpus_files(
    roots: Iterable[Path],
    suffixes: frozenset[str],
    recursive: bool,
) -> Iterator[tuple[Path, Path]]:
    """Yield ``(root, file)`` pairs for every file under any root whose
    suffix is in ``suffixes`` (case-insensitive). When ``recursive`` is
    False, only top-level files are visited; this matches v0.8's behaviour
    so existing setups don't change."""
    for root in roots:
        walker = root.rglob("*") if recursive else root.iterdir()
        for path in walker:
            if path.is_file() and path.suffix.lower() in suffixes:
                yield root, path
