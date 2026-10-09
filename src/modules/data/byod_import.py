"""Import the researcher's staged data files into the paper's ``data.db``.

At paper creation the BYOD corpus is symlinked into ``workspace/<id>/data/``
(see ``api/app.py:_link_local_data_dir_into_workspace``). This module walks
those staged files and loads each tabular one into the per-paper SQLite data
warehouse (``src/db/paper_data_db.py``) as a queryable table, so specialists can
``query_data("SELECT … FROM trades …")`` instead of reading whole CSVs into
pandas memory.

Design contract (mirrors the symlinker): **best-effort, never fatal.** A bad or
unreadable file logs a warning and is skipped; paper creation always continues.
Large files are chunk-loaded and capped at ``settings.max_rows_per_paper``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ...db.paper_data_db import (
    _materialize_dataframe_sync,
    data_db_path,
    unique_table_name,
)
from ...logging_config import get_logger
from ..local_corpus import DATA_EXTENSIONS

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)

# Tabular extensions we import into data.db: the one list (local_corpus.DATA_EXTENSIONS).
_TABULAR_EXTENSIONS = DATA_EXTENSIONS

_CSV_CHUNK = 50_000


def _staged_data_files(workspace: Path) -> list[Path]:
    data_dir = Path(workspace) / "data"
    if not data_dir.is_dir():
        return []
    return sorted(p for p in data_dir.rglob("*") if p.is_file() and p.suffix.lower() in _TABULAR_EXTENSIONS)


def _sniff_delimiter(path: Path, default: str) -> str:
    """Sniff the column delimiter from a CSV's first line. Real-world exports
    use ';' (European locales) or '|' as often as ','. Restricted to common
    delimiters; falls back to ``default`` when detection is ambiguous."""
    import csv

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            sample = f.readline()
        if not sample:
            return default
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except (csv.Error, OSError):
        return default


def _estimate_csv_rows(path: Path, sample_lines: int = 2000) -> int:
    """Estimate total data rows from file size + average sampled line length.
    Cheap (reads only the head), so we can pick a sampling stride for a
    multi-GB file without a full counting pass."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    consumed = 0
    n = 0
    with path.open("rb") as f:
        header_len = len(f.readline())
        for _ in range(sample_lines):
            line = f.readline()
            if not line:
                break
            consumed += len(line)
            n += 1
    if n == 0:
        return 0
    avg = consumed / n
    return int(max(0, size - header_len) / avg) if avg > 0 else 0


def _systematic_sample(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    """Cap an in-memory frame to <= max_rows by keeping every k-th row (order
    preserved, full span) rather than the first N — so a time-ordered file isn't
    truncated to its earliest period."""
    if len(df) <= max_rows:
        return df
    stride = max(1, -(-len(df) // max_rows))  # ceil
    idx = list(range(0, len(df), stride))[:max_rows]
    return df.take(idx)


#: The package pandas needs to read each file type, for the error a researcher sees.
_READERS = {".parquet": "pyarrow", ".xlsx": "openpyxl"}


class MissingReaderError(RuntimeError):
    """A data file whose reader package is not installed."""


def _require_reader(path: Path) -> None:
    """Fail with a plain instruction when the package that reads this file type is missing."""
    import importlib.util

    package = _READERS.get(path.suffix.lower())
    if package and importlib.util.find_spec(package) is None:
        raise MissingReaderError(
            f"{path.name} was not loaded: reading {path.suffix.lower()} files needs the {package} package, "
            f"which is not installed. Install it with `pip install {package}` (or reinstall e2er, which "
            "includes it) and start the study again."
        )


def _load_flat_dataframe(path: Path, max_rows: int) -> pd.DataFrame:
    """Read a non-CSV tabular file fully, systematic-sampled to the cap.
    CSV/TSV use the chunked path."""
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(path)
    elif suffix == ".jsonl":
        df = pd.read_json(path, lines=True)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"not a flat-loadable file: {path}")
    return _systematic_sample(df, max_rows)


def _import_one_file_sync(
    db_path: Path,
    rel_label: str,
    path: Path,
    existing: set[str],
    max_rows: int,
) -> list[dict[str, Any]]:
    """Import a single file into data.db. Returns one record per table created."""
    import pandas as pd

    suffix = path.suffix.lower()
    results: list[dict[str, Any]] = []
    _require_reader(path)

    if suffix == ".xlsx":
        # One table per sheet; suffix the sheet name when there's more than one.
        sheets = pd.read_excel(path, sheet_name=None)
        multi = len(sheets) > 1
        for sheet_name, df in sheets.items():
            df = _systematic_sample(df, max_rows)
            label = f"{Path(rel_label).with_suffix('')}_{sheet_name}" if multi else rel_label
            table = unique_table_name(label, existing)
            rows = _materialize_dataframe_sync(db_path, table, df, if_exists="replace")
            results.append({"table": table, "source": rel_label, "rows": rows, "columns": list(df.columns)})
        return results

    if suffix in {".csv", ".tsv"}:
        sep = "\t" if suffix == ".tsv" else _sniff_delimiter(path, ",")
        table = unique_table_name(rel_label, existing)
        # Systematic sampling so a row cap on a time-ordered file still spans the
        # whole period. head(N) once restricted a 16 GB NFT file to its earliest
        # ~200k rows (all 2021, before aggregators existed) → the model built a
        # bogus proxy and the paper was rejected. Stride from a cheap size-based
        # estimate; stride==1 (file fits) keeps the old read-everything behaviour.
        # ceil, not round: for files 1-1.5x the cap, round() gives stride 1 and
        # the kept>=max_rows break silently reintroduces the head(N) bias.
        estimate = _estimate_csv_rows(path)
        stride = max(1, -(-estimate // max_rows)) if estimate > max_rows else 1
        kept = 0
        seen = 0
        first = True
        columns: list[str] = []
        for chunk in pd.read_csv(path, sep=sep, chunksize=_CSV_CHUNK):
            if kept >= max_rows:
                break
            if stride > 1:
                # keep rows whose GLOBAL index is a multiple of stride (order kept)
                positions = [i for i in range(len(chunk)) if (seen + i) % stride == 0]
                seen += len(chunk)
                if not positions:
                    continue
                chunk = chunk.iloc[positions]
            else:
                seen += len(chunk)
            if kept + len(chunk) > max_rows:
                chunk = chunk.head(max_rows - kept)
            mode: Literal["replace", "append"] = "replace" if first else "append"
            _materialize_dataframe_sync(db_path, table, chunk, if_exists=mode)
            columns = list(chunk.columns)
            kept += len(chunk)
            first = False
        total = kept
        if first:  # empty file → still create an empty table so the catalog shows it
            empty = pd.read_csv(path, sep=sep, nrows=0)
            _materialize_dataframe_sync(db_path, table, empty, if_exists="replace")
            columns = list(empty.columns)
        results.append({"table": table, "source": rel_label, "rows": total, "columns": columns})
        return results

    # parquet / jsonl
    df = _load_flat_dataframe(path, max_rows)
    table = unique_table_name(rel_label, existing)
    rows = _materialize_dataframe_sync(db_path, table, df, if_exists="replace")
    results.append({"table": table, "source": rel_label, "rows": rows, "columns": list(df.columns)})
    return results


def _uploaded_names(workspace: Path) -> set[str]:
    """The data files added on New study for this study alone (study_inputs.json)."""
    import json

    try:
        record = json.loads((Path(workspace) / "study_inputs.json").read_text(encoding="utf-8"))
        files = (record.get("data") or {}).get("files") or []
        return {str(f.get("name")) for f in files if isinstance(f, dict) and f.get("origin") == "upload"}
    except (OSError, ValueError, AttributeError):
        return set()


def _import_corpus_sync(workspace: Path, max_rows: int) -> list[dict[str, Any]]:
    files = _staged_data_files(workspace)
    if not files:
        return []
    uploaded = _uploaded_names(workspace)
    data_dir = Path(workspace) / "data"
    db_path = data_db_path(workspace)
    existing: set[str] = set()
    imported: list[dict[str, Any]] = []
    for path in files:
        rel_label = path.relative_to(data_dir).as_posix()
        try:
            tables = _import_one_file_sync(db_path, rel_label, path, existing, max_rows)
        except MissingReaderError as e:
            # Loud: a missing reader is a setup problem the researcher can fix,
            # not a bad file. Logged as an error and printed to the terminal.
            logger.error("%s", e)
            print(f"e2er: {e}", file=sys.stderr)
            continue
        except Exception as e:  # noqa: BLE001 — best-effort: one bad file must not fail paper creation
            logger.warning("BYOD import skipped %s: %s (paper creation continues)", rel_label, e)
            continue
        imported.extend(tables)
        _record_file(workspace, rel_label, path, tables, uploaded=rel_label in uploaded)
    return imported


def _record_file(workspace: Path, rel: str, path: Path, tables: list[dict[str, Any]], uploaded: bool = False) -> None:
    """Record the researcher's file in data_sources.json: its name, SHA-256 and the tables it became."""
    from .load_record import data_folder_load, now_utc, try_record

    entry = data_folder_load(rel, path, now_utc())
    if uploaded:
        entry["dataset"] = "Added by the researcher for this study"
    entry["tables"] = [t["table"] for t in tables]
    entry["rows"] = sum(int(t.get("rows") or 0) for t in tables)
    try_record(workspace, entry)


async def import_corpus_into_data_db(workspace: Path, max_rows: int) -> list[dict[str, Any]]:
    """Import all staged tabular files in ``workspace/data/`` into ``data.db``.

    Returns a list of ``{table, source, rows, columns}`` records (one per table
    created). Never raises — failures are logged and skipped.
    """
    try:
        imported = await asyncio.to_thread(_import_corpus_sync, workspace, max_rows)
    except Exception as e:  # noqa: BLE001 — defensive outer guard
        logger.warning("BYOD import failed for %s: %s (paper creation continues)", workspace, e)
        return []
    if imported:
        logger.info(
            "BYOD import: %d table(s) into %s (%s)",
            len(imported),
            data_db_path(workspace).name,
            ", ".join(f"{r['table']}={r['rows']}" for r in imported),
        )
    return imported
