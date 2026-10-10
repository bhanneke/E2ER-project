"""Helpers for the ``LOCAL_DATA_DIR`` corpus.

A researcher's reusable BYOD corpus — data files, ``.bib`` and PDFs — lives
in one (or several) local folder(s). These helpers parse the env var
(possibly comma-separated) and walk the folder(s), optionally recursing.

The corpus has three file kinds with different consumers:
  - data files (csv/tsv/jsonl/parquet/xlsx) → linked into
    ``workspace/<paper_id>/data/`` at paper creation (only the files chosen for
    the study, when a choice was made; see ``src/core/study_inputs.py``).
  - ``.bib`` → merged into the reference summary alongside
    ``LITERATURE_BIBTEX_FILE`` by ``LocalBibLibrary``.
  - PDFs → symlinked into ``workspace/<paper_id>/literature/`` so the
    ``read_reference`` tool can extract them by local path.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from ..logging_config import get_logger

logger = get_logger(__name__)

#: The data files e2er reads into a study, everywhere: the New study list, uploads, `e2er run --data`,
#: staging, the planning check and the import into data.db. One list, so a file offered is a file read.
DATA_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv", ".jsonl", ".parquet", ".xlsx"})
#: The same list as a researcher reads it.
DATA_EXTENSIONS_TEXT = ".csv, .tsv, .jsonl, .parquet or .xlsx"
BIB_EXTENSIONS: frozenset[str] = frozenset({".bib"})
PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


def not_a_data_file(name: str) -> str | None:
    """The plain sentence for a file e2er does not read as data (None when it does)."""
    if Path(name).suffix.lower() in DATA_EXTENSIONS:
        return None
    return f"{Path(name).name} is not a data file e2er can read. Use {DATA_EXTENSIONS_TEXT}."


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


#: The default folder for exported studies inside the data folder (config.resolved_output_root).
EXPORT_FOLDER = "e2er_papers"


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
            if not (path.is_file() and path.suffix.lower() in suffixes):
                continue
            # Exported studies land in <data>/e2er_papers by default; staging them
            # would feed earlier studies' files to the next one as "data".
            if EXPORT_FOLDER in path.relative_to(root).parts[:-1]:
                continue
            yield root, path


_copy_notice_shown = False


def link_or_copy(source: Path, target: Path) -> str:
    """Put ``source`` at ``target`` as a link, or as a copy where links are not allowed.

    Windows lets a program create links only with Developer Mode on (or as
    administrator). There the link fails, and the file used to be left out
    with a line in the log. Now it is copied, and the first copy says so in
    the terminal: a copy does not follow later edits of the original.
    Returns "linked" or "copied"; raises OSError when the copy fails too.
    """
    global _copy_notice_shown
    try:
        target.symlink_to(source.resolve())
        return "linked"
    except OSError as e:
        shutil.copy2(source, target)
        if not _copy_notice_shown:
            _copy_notice_shown = True
            msg = (
                f"could not link {source.name} into the study ({e}); copied it instead. "
                "Copies do not follow later edits of your files. On Windows, turning on Developer Mode "
                "(Settings > System > For developers) lets e2er link them."
            )
            logger.warning("%s", msg)
            print(f"e2er: {msg}", file=sys.stderr)
        return "copied"
