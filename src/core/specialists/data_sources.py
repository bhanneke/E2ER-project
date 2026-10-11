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

Available: the connector kit's keyless sources (yfinance, the GMD, USGS, …),
FRED with FRED_API_KEY, Allium with ALLIUM_API_KEY, and the data files of this study: the files staged into its
``data/`` folder when it started (the files chosen on New study or with
``e2er run --data``, else every data file of the data folder). The data folder
itself is not read again: a file added there later is not part of this study.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...modules.local_corpus import DATA_EXTENSIONS


def _connectors() -> dict[str, tuple[str, str] | None]:
    """Connectors e2er has: source name -> (the setting that holds its key, its variable), None when keyless.

    The connector kit's sources (modules/data/sources/): the keyless ones first, then those that
    need a key, each in catalogue order; then Allium.
    """
    from ...modules.data.sources import all_sources

    kit = sorted(all_sources(), key=lambda s: bool(s.key and not s.key.optional))
    out: dict[str, tuple[str, str] | None] = {
        s.name: (s.key.setting, s.key.env) if s.key and not s.key.optional else None for s in kit
    }
    out["allium"] = ("allium_api_key", "ALLIUM_API_KEY")
    return out


def _aliases() -> dict[str, str]:
    """Other names for a connector, written as _norm writes them (lower case, "_" for spaces and dashes)."""
    from ...modules.data.sources import all_sources

    return {alias: s.name for s in all_sources() for alias in s.aliases}


#: The connectors when this module was imported (``_connectors()`` is the live list).
CONNECTORS: dict[str, tuple[str, str] | None] = _connectors()
#: A table from the study's own files.
LOCAL_SOURCES = frozenset(
    {"local", "file", "data", "data_folder", "researcher", "researcher_supplied", "supplied", "byod", "upload"}
)
#: The data files a study can read (the one list in modules/local_corpus.py).
_TABULAR = DATA_EXTENSIONS


@dataclass(frozen=True)
class Sources:
    connectors: dict[str, bool]  # name -> usable now
    files: tuple[str, ...]  # data files in the study's data folder(s), by their path inside it
    tables: frozenset[str]  # tables already in data.db (the researcher's own data)


def _data_dirs(workspace: Path, settings: Any) -> list[Path]:
    """The study's own data folder: what was staged for it at the start (never the live data folder)."""
    return [Path(workspace) / "data"]


def available_sources(workspace: Path, settings: Any = None) -> Sources:
    """The sources this study can load from now."""
    from .contract_check import table_row_counts

    if settings is None:
        from ...config import get_settings

        settings = get_settings()
    from ...modules.data.sources import get as source_of

    connectors = {}
    for name, key in _connectors().items():
        src = source_of(name)
        connectors[name] = src.available(settings) if src else key is None or bool(getattr(settings, key[0], None))
    files: list[str] = []
    for d in _data_dirs(workspace, settings):
        if d.is_dir():
            # Files in subfolders too (data/raw/x.csv), by their path inside the data folder.
            for p in sorted(d.rglob("*")):
                rel = p.relative_to(d)
                if p.is_file() and p.suffix.lower() in _TABULAR and not any(x.startswith(".") for x in rel.parts):
                    files.append(rel.as_posix())
    return Sources(connectors, tuple(dict.fromkeys(files)), frozenset(table_row_counts(workspace)))


def _norm(source: Any) -> str:
    """A source as named in the data dictionary, in one spelling: "Yahoo-Finance" and "yahoo finance" are yfinance."""
    s = "_".join(str(source or "").strip().lower().replace("-", " ").replace("_", " ").split())
    return _aliases().get(s, s)


def _has_file(wanted: str, files: tuple[str, ...]) -> bool:
    """Is the named file in the data folder? By its path there (``raw/x.csv`` or ``data/raw/x.csv``) or its name."""
    w = wanted.replace("\\", "/").strip().lstrip("./")
    if w.startswith("data/"):
        w = w[len("data/") :]
    return any(f == w or f.endswith("/" + w) for f in files) or Path(w).name in {Path(f).name for f in files}


def why_unavailable(entry: dict[str, Any], sources: Sources) -> str | None:
    """Why a declared table cannot be loaded (None when it can)."""
    name = str(entry.get("name") or "")
    if name in sources.tables:
        return None  # already in data.db
    source = _norm(entry.get("source"))
    if not source:
        return "declares no source"
    known = _connectors()
    if source in known:
        if sources.connectors.get(source):
            return None
        key = known[source]
        return f"{source} needs {key[1]}, which is not set" if key else f"{source} is not available"
    if source in LOCAL_SOURCES:
        wanted = str(entry.get("file") or "").strip()
        # The named file, or else a file named like the table (fomc_dates.csv for fomc_dates).
        if wanted and _has_file(wanted, sources.files):
            return None
        if not wanted and any(Path(f).stem == name for f in sources.files):
            return None
        if not sources.files:
            return "no data files were chosen for this study"
        return f"no file {wanted!r} among the study's data files ({', '.join(sources.files)})"
    return (
        f"e2er has no connector for {entry.get('source')!s}; "
        "add the data as a file to the study or use an available source"
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
    for name, key in _connectors().items():
        if s.connectors[name]:
            lines.append(f"- `{name}`" + (f" (its key {key[1]} is set)" if key else " (no key needed)"))
        else:
            lines.append(f"- not available: `{name}` (needs {key[1]}, which is not set)" if key else "")
    if s.files:
        lines.append(
            "- `file`: the researcher chose these data files for this study (in its `data/` folder): "
            + ", ".join(f"`{f}`" for f in s.files)
            + '; declare such a table with `"source": "file", "file": "<name>"`.'
        )
    else:
        lines.append("- no data files: the researcher chose no data files for this study.")
    if s.tables:
        lines.append("- already in data.db (do not redeclare): " + ", ".join(sorted(s.tables)))
    lines.append(
        "Sources such as CRSP, Compustat, WRDS, call reports or Fama-French factors are not available unless "
        "their data are among the study's data files. If the question needs data that no available source has, "
        "say so in data_dictionary.json (`unavailable`) instead of declaring the table."
    )
    return "\n".join(line for line in lines if line)
