"""Which data sources a study can use now, and the data architect's check against them.

The live E2E-01 runs (2026-10-04, Sonnet and Haiku) with an empty data folder
and no FRED key: the data architect declared tables from CRSP, a bank
call-report table, Fama-French factors and FRED series. Nothing could load
them, and only the data analyst noticed, after the planning was paid for. Now
the architect is told exactly which sources are available, and a table from
any other source is a contract violation at planning time that names the
table, its source and why it is unavailable. After the last attempt the run
stops for the researcher, who can add data files or keys, or instruct the
architect to use other sources.

Available: yfinance and GMD (no key), FRED with FRED_API_KEY, Allium with
ALLIUM_API_KEY, and files in the study's data folder (``data/`` in the
workspace, or LOCAL_DATA_DIR).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Connectors e2er has: source name -> (the setting that holds its key, its variable), None when keyless.
CONNECTORS: dict[str, tuple[str, str] | None] = {
    "yfinance": None,
    "gmd": None,
    "fred": ("fred_api_key", "FRED_API_KEY"),
    "allium": ("allium_api_key", "ALLIUM_API_KEY"),
}
_ALIASES = {
    "yahoo": "yfinance",
    "yahoo_finance": "yfinance",
    "yahoo finance": "yfinance",
    "global_macro_database": "gmd",
    "global macro database": "gmd",
}
#: A table from the study's own files.
LOCAL_SOURCES = frozenset(
    {"local", "file", "data", "data_folder", "researcher", "researcher_supplied", "supplied", "byod", "upload"}
)
_TABULAR = frozenset({".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json", ".jsonl", ".txt"})


@dataclass(frozen=True)
class Sources:
    connectors: dict[str, bool]  # name -> usable now
    files: tuple[str, ...]  # data files in the study's data folder(s), by name
    tables: frozenset[str]  # tables already in data.db (the researcher's own data)


def _data_dirs(workspace: Path, settings: Any) -> list[Path]:
    dirs = [Path(workspace) / "data"]
    for part in str(getattr(settings, "local_data_dir", "") or "").split(","):
        if part.strip():
            dirs.append(Path(part.strip()).expanduser())
    return dirs


def available_sources(workspace: Path, settings: Any = None) -> Sources:
    """The sources this study can load from now."""
    from .contract_check import table_row_counts

    if settings is None:
        from ...config import get_settings

        settings = get_settings()
    connectors = {name: key is None or bool(getattr(settings, key[0], None)) for name, key in CONNECTORS.items()}
    files: list[str] = []
    for d in _data_dirs(workspace, settings):
        if d.is_dir():
            files += [p.name for p in sorted(d.iterdir()) if p.is_file() and p.suffix.lower() in _TABULAR]
    return Sources(connectors, tuple(dict.fromkeys(files)), frozenset(table_row_counts(workspace)))


def _norm(source: Any) -> str:
    s = str(source or "").strip().lower()
    s = _ALIASES.get(s, s)
    return s.replace("-", "_").replace(" ", "_")


def why_unavailable(entry: dict[str, Any], sources: Sources) -> str | None:
    """Why a declared table cannot be loaded (None when it can)."""
    name = str(entry.get("name") or "")
    if name in sources.tables:
        return None  # already in data.db
    source = _norm(entry.get("source"))
    if not source:
        return "declares no source"
    if source in CONNECTORS:
        if sources.connectors.get(source):
            return None
        key = CONNECTORS[source]
        return f"{source} needs {key[1]}, which is not set" if key else f"{source} is not available"
    if source in LOCAL_SOURCES:
        wanted = str(entry.get("file") or "").strip()
        # The named file, or else a file named like the table (fomc_dates.csv for fomc_dates).
        if wanted and Path(wanted).name in sources.files:
            return None
        if not wanted and any(Path(f).stem == name for f in sources.files):
            return None
        if not sources.files:
            return "the study's data folder (data/ or LOCAL_DATA_DIR) holds no data files"
        return f"no file {wanted!r} in the study's data folder (files there: {', '.join(sources.files)})"
    return (
        f"e2er has no connector for {entry.get('source')!s}; "
        "add the data as a file in the study's data folder or use an available source"
    )


def check_declared_sources(workspace: Path, settings: Any = None) -> list[Any]:
    """The data architect's contract: every declared table comes from a source available now."""
    from .contract_check import DATA_DICTIONARY_FILE, ContractCheck

    try:
        data = json.loads((Path(workspace) / DATA_DICTIONARY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("tables") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    sources = available_sources(workspace, settings)
    problems = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue  # a bare name: a table the researcher supplied, or older dictionaries
        why = why_unavailable(entry, sources)
        if why:
            problems.append(f"table {entry.get('name')!s} (source {entry.get('source')!s}): {why}")
    if not problems:
        return [ContractCheck(DATA_DICTIONARY_FILE, True)]
    return [
        ContractCheck(
            DATA_DICTIONARY_FILE,
            False,
            "declares tables from sources that are not available: "
            + "; ".join(problems)
            + ". "
            + sources_line(sources),
        )
    ]


def sources_line(sources: Sources) -> str:
    """One line naming the sources that are available, for a violation message."""
    usable = [n for n, ok in sources.connectors.items() if ok]
    files = f"; data files: {', '.join(sources.files)}" if sources.files else "; no data files"
    return f"Available now: {', '.join(usable)}{files}."


def sources_block(workspace: Path, settings: Any = None) -> str:
    """The prompt section for the data architect: exactly the sources available, and which need a key."""
    s = available_sources(workspace, settings)
    lines = [
        "## Data sources available to this study",
        "Declare tables only from these sources (the `source` of each table in data_dictionary.json). "
        "A table from any other source is rejected by the contract check.",
    ]
    for name, key in CONNECTORS.items():
        if s.connectors[name]:
            lines.append(f"- `{name}`" + (f" (its key {key[1]} is set)" if key else " (no key needed)"))
        else:
            lines.append(f"- not available: `{name}` (needs {key[1]}, which is not set)" if key else "")
    if s.files:
        lines.append(
            "- `file`: the study's data folder holds "
            + ", ".join(f"`{f}`" for f in s.files)
            + '; declare such a table with `"source": "file", "file": "<name>"`.'
        )
    else:
        lines.append("- no data files: the study's data folder (data/ or LOCAL_DATA_DIR) is empty.")
    if s.tables:
        lines.append("- already in data.db (do not redeclare): " + ", ".join(sorted(s.tables)))
    lines.append(
        "Sources such as CRSP, Compustat, WRDS, call reports or Fama-French factors are not available unless "
        "their data are files in the data folder. If the question needs data that no available source has, "
        "say so in data_dictionary.json (`unavailable`) instead of declaring the table."
    )
    return "\n".join(line for line in lines if line)
