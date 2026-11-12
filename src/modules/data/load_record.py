"""The record of every external-data load: ``data_sources.json`` in the study's workspace.

Every connector that brings data into a study writes one entry per load here:
FRED, Yahoo Finance (yfinance), the Global Macro Database, Allium, a Zenodo
record (the replication template's package) and the researcher's own data
folder. Export ships the file as ``data/data_sources.json``; the dossier lists
its entries under ``data_sources`` and e2er.org shows them as the study's
"Data used".

An entry names what the page needs, in the same keys for every connector:

- ``connector``: the connector (``fred``, ``yfinance``, ``gmd``, ``allium``,
  ``zenodo``, ``data-folder``);
- ``dataset``: the source's name;
- ``version``: the release, where the source publishes releases (GMD, a Zenodo
  record's version), else absent; ``retrieved_at``: when the load ran (UTC);
- ``series``: what was loaded (series id, ticker, variables, query, file);
- ``table`` / ``saved_to``: where it went in the study;
- ``terms_summary``: the source's terms in one or two sentences; ``licence``:
  the terms as the connector states them in full; ``terms``: the address of the
  source's own terms;
- ``citation``: the citation; ``citation_by``: ``source`` when the source
  publishes the format, ``e2er`` when it publishes none and e2er suggests one;
- ``files``: ``{url, sha256}`` of every file read (or ``{path, sha256}`` for a
  local file), where the source serves files;
- ``request`` / ``query``: the load's parameters and the request as sent;
  ``rows``: how many rows the load returned;
- ``fingerprint`` (since 0.21): the data version of what the load returned, so
  a later reload can say whether the source now returns other data
  (``e2er reproduce``): ``{"form": "e2er-rows/1", "sha256", "rows", "columns"}``,
  see :func:`fingerprint_rows` for the canonical form. A load recorded before
  0.21 has none.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import shutil
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

DATA_SOURCES_FILE = "data_sources.json"


# A source's name, terms and citation are declared once, in its definition (sources/<name>.py).
from .sources.base import SourceInfo as SourceInfo  # noqa: E402


def _info(name: str) -> SourceInfo:
    """The SourceInfo of a source declared in the connector kit (sources/)."""
    from . import sources

    source = sources.get(name)
    if source is None:
        raise KeyError(f"no data source {name!r}")
    return source.info


def __getattr__(name: str) -> SourceInfo:
    # FRED and YFINANCE, from their definitions (read when first asked for: the definitions import this module).
    if name in ("FRED", "YFINANCE"):
        return _info(name.lower())
    raise AttributeError(name)


ALLIUM = SourceInfo(
    connector="allium",
    dataset="Allium",
    website="https://www.allium.so",
    terms_url="https://www.allium.so/terms-of-service",
    terms_summary="Allium's terms of service and the researcher's own agreement with Allium apply.",
    licence=(
        "Allium terms of service (https://www.allium.so/terms-of-service) and the agreement under which "
        "the researcher holds the API key."
    ),
    citation_by="e2er",
)

DATA_FOLDER = SourceInfo(
    connector="data-folder",
    dataset="The researcher's data folder",
    website="",
    terms_url="",
    terms_summary="Supplied by the researcher; e2er does not know the terms of these files.",
    licence="Supplied by the researcher; e2er does not know the terms of these files.",
    citation_by="",
)


#: The canonical form of a loaded table that ``fingerprint`` hashes (see fingerprint_rows).
FINGERPRINT_FORM = "e2er-rows/1"
_SAFE_INTEGER = 2**53


def _cell(value: Any) -> Any:
    """One value in the canonical form: JSON types only, a whole float as an integer, NaN and infinities as null."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value if abs(value) < _SAFE_INTEGER else str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer() and abs(value) < _SAFE_INTEGER:
            return int(value)
        return value
    if isinstance(value, dict):
        return {str(k): _cell(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_cell(v) for v in value]
    if hasattr(value, "item"):  # a numpy scalar
        try:
            return _cell(value.item())
        except (ValueError, AttributeError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def fingerprint_rows(rows: Any) -> dict[str, Any] | None:
    """The data version of a loaded table: a SHA-256 of its rows in a canonical form (``e2er-rows/1``).

    The canonical form, so the same data give the same hash whatever order or types the source used:

    1. the columns are the names of every row's keys, as text, sorted by Unicode code point;
    2. each row becomes a JSON array of its values in that column order, a missing key as null; a number
       whose value is whole (``3.0``) is written as an integer (``3``), other floats in Python's shortest
       round-trip form (``0.1``), NaN and infinities as null; dates as ISO text; nested objects with their
       keys sorted;
    3. each array is written as compact JSON (``json.dumps(..., ensure_ascii=False, sort_keys=True,
       separators=(",", ":"))``) and the lines are sorted by Unicode code point, so the order of the rows
       does not count;
    4. the hash is SHA-256 over the UTF-8 bytes of the column list (written the same way), a newline, and
       every sorted row line followed by a newline.

    Returns ``{"form", "sha256", "rows", "columns"}``, or None for rows that are not a list of objects.
    """
    if rows is None:
        return None
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict(orient="records")
    try:
        records = [r for r in rows if isinstance(r, dict)]
    except TypeError:
        return None
    columns = sorted({str(k) for r in records for k in r})

    def line(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    keyed = [{str(k): v for k, v in r.items()} for r in records]
    lines = sorted(line([_cell(r.get(c)) for c in columns]) for r in keyed)
    h = hashlib.sha256()
    h.update((line(columns) + "\n").encode("utf-8"))
    for text in lines:
        h.update((text + "\n").encode("utf-8"))
    return {"form": FINGERPRINT_FORM, "sha256": h.hexdigest(), "rows": len(records), "columns": columns}


def with_fingerprint(entry: dict[str, Any], rows: Any) -> dict[str, Any]:
    """``entry`` with the ``fingerprint`` of the rows the load returned (unchanged when there are none)."""
    try:
        found = fingerprint_rows(rows)
    except (TypeError, ValueError) as e:  # a cell JSON cannot write: the load is recorded without it
        logger.warning("the load's rows could not be fingerprinted: %s", e)
        return entry
    return {**entry, "fingerprint": found} if found and found["rows"] else entry


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _long_date(iso: str) -> str:
    """``2026-10-04T…`` → ``October 4, 2026`` (FRED's citation format)."""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
    except ValueError:
        return iso[:10]
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def base(info: SourceInfo) -> dict[str, Any]:
    """The keys every load of ``info`` carries."""
    out: dict[str, Any] = {"connector": info.connector, "dataset": info.dataset}
    if info.terms_summary:
        out["terms_summary"] = info.terms_summary
    if info.licence:
        out["licence"] = info.licence
    if info.terms_url:
        out["terms"] = info.terms_url
    return out


def fred_citation(series_id: str, retrieved_at: str, *, title: str = "", source: str = "") -> str:
    """The citation on a FRED series' Cite tab: source, title [ID], retrieved from FRED, …; series URL, date."""
    head = ", ".join(x for x in (source.strip(), title.strip()) if x)
    head = f"{head} [{series_id}]" if head else f"[{series_id}]"
    return (
        f"{head}, retrieved from FRED, Federal Reserve Bank of St. Louis; "
        f"https://fred.stlouisfed.org/series/{series_id}, {_long_date(retrieved_at)}."
    )


def fred_load(
    series_id: str, retrieved_at: str, *, title: str = "", source: str = "", last_updated: str = ""
) -> dict[str, Any]:
    out = base(_info("fred"))
    out.update(
        {
            "series": series_id,
            "link": f"https://fred.stlouisfed.org/series/{series_id}",
            "retrieved_at": retrieved_at,
            "citation": fred_citation(series_id, retrieved_at, title=title, source=source),
            "citation_by": _info("fred").citation_by,
        }
    )
    if title:
        out["title"] = title
    if last_updated:
        # FRED revises series; the vintage read is the one current at retrieval.
        out["last_updated"] = last_updated
    return out


def yfinance_load(ticker: str, retrieved_at: str, *, what: str = "daily prices") -> dict[str, Any]:
    out = base(_info("yfinance"))
    out.update(
        {
            "series": f"{ticker} {what}",
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "retrieved_at": retrieved_at,
            "citation": (
                f"Yahoo Finance, {ticker} {what}, retrieved through yfinance on {retrieved_at[:10]}, "
                f"https://finance.yahoo.com/quote/{ticker}."
            ),
            "citation_by": _info("yfinance").citation_by,
        }
    )
    return out


def allium_load(series: str, retrieved_at: str, *, query: str | None = None) -> dict[str, Any]:
    out = base(ALLIUM)
    out.update(
        {
            "series": series,
            "link": ALLIUM.website,
            "retrieved_at": retrieved_at,
            "citation": f"Allium, {series}, retrieved {retrieved_at[:10]}, https://www.allium.so.",
            "citation_by": ALLIUM.citation_by,
        }
    )
    if query:
        out["query"] = query
    return out


def zenodo_load(fetched: dict[str, Any], retrieved_at: str) -> dict[str, Any]:
    """A Zenodo record fetched as a study's input (``FetchedRecord.as_dict()``)."""
    record_id = str(fetched.get("record_id") or "")
    doi = str(fetched.get("doi") or "")
    url = str(fetched.get("url") or f"https://zenodo.org/records/{record_id}")
    creators = [c for c in fetched.get("creators") or [] if c]
    year = str(fetched.get("publication_date") or "")[:4]
    version = str(fetched.get("version") or "")
    licence = str(fetched.get("licence") or "")
    title = str(fetched.get("title") or f"Zenodo record {record_id}")
    # Zenodo's own citation style: creators (year). title (version). Zenodo. DOI link.
    cite = "; ".join(creators) + (f" ({year})" if year else "") + f". {title}"
    cite += f" ({version})" if version else ""
    cite += ". Zenodo." + (f" https://doi.org/{doi}" if doi else f" {url}")
    out: dict[str, Any] = {
        "connector": "zenodo",
        "dataset": title,
        "terms_summary": (
            f"Published on Zenodo under the licence {licence}." if licence else "The record names no licence."
        ),
        "licence": licence or "none named",
        "terms": url,
        "series": ", ".join(str(f.get("key") or f.get("path")) for f in fetched.get("files") or []),
        "link": f"https://doi.org/{doi}" if doi else url,
        "retrieved_at": retrieved_at,
        "citation": cite,
        "citation_by": "source",
        "files": [
            {"url": f"https://zenodo.org/records/{record_id}/files/{f.get('key')}", "sha256": f["sha256"]}
            for f in fetched.get("files") or []
            if f.get("sha256") and f.get("key")
        ],
    }
    if version:
        out["version"] = version
    if doi:
        out["doi"] = doi
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def data_folder_load(rel: str, path: Path, retrieved_at: str) -> dict[str, Any]:
    """A file from the researcher's data folder, as the run imported it."""
    out = base(DATA_FOLDER)
    out.update({"series": rel, "saved_to": f"data/{rel}", "retrieved_at": retrieved_at})
    try:
        out["files"] = [{"path": f"data/{rel}", "sha256": sha256_file(path)}]
    except OSError as e:
        logger.warning("data folder: %s could not be fingerprinted: %s", rel, e)
    return out


def _key(entry: dict[str, Any]) -> tuple[Any, ...]:
    """What one load is: a table, else a saved file, else the source and what was read."""
    if entry.get("table"):
        return ("table", entry["table"])
    if entry.get("saved_to"):
        return ("file", entry["saved_to"])
    return ("source", entry.get("connector"), entry.get("series"), entry.get("query"))


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    """An exclusive lock on ``.<name>.lock`` beside the file while the block runs (parallel loads of a study)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    from ...core.file_lock import exclusive

    with open(path.with_name(f".{path.name}.lock"), "a+b") as fh, exclusive(fh):
        yield


def _read_loads(path: Path) -> list[Any]:
    """The loads already recorded: the file, else its backup; a file that cannot be read is kept aside, never wiped."""
    if not path.is_file():
        return []
    for attempt in range(3):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("loads"), list):
                return list(loaded["loads"])
            break
        except (OSError, ValueError):
            time.sleep(0.05 * (attempt + 1))  # a writer that does not lock may be halfway through
    aside = path.with_name(f".{path.name}.unreadable-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}")
    try:
        path.replace(aside)
    except OSError:
        pass
    backup = path.with_name(f".{path.name}.bak")
    try:
        loaded = json.loads(backup.read_text(encoding="utf-8"))
        loads = list(loaded["loads"]) if isinstance(loaded, dict) and isinstance(loaded.get("loads"), list) else []
    except (OSError, ValueError):
        loads = []
    logger.warning(
        "%s could not be read; it was kept as %s and the record continues from %s",
        path,
        aside.name,
        f"its backup ({len(loads)} loads)" if loads else "nothing",
    )
    return loads


def record_load(workspace: Path, record: dict[str, Any]) -> Path:
    """Write ``record`` into the study's ``data_sources.json`` (one entry per table or saved file).

    A later load into the same table (or the same saved file, or of the same
    series from the same source when nothing was saved) replaces the earlier
    entry; everything else is kept. Export ships the file as
    ``data/data_sources.json`` and the dossier lists its entries.

    Parallel loads of one study (specialists run side by side) each hold a lock
    on the file while they read and rewrite it, and the file is replaced whole
    (written next to it, then renamed), so no load is lost and no reader sees
    half a file. The previous version is kept as ``.data_sources.json.bak``. The side files start
    with a dot, so export leaves them out of the study folder.
    """
    path = Path(workspace) / DATA_SOURCES_FILE
    record = {k: v for k, v in record.items() if v is not None}
    key = _key(record)
    with _locked(path):
        loads = _read_loads(path)
        doc: dict[str, Any] = {
            "$comment": (
                "Written by e2er-data: one entry per external-source load, with the source version, "
                "the URL and SHA-256 of every file read."
            ),
            "loads": [a for a in loads if not (isinstance(a, dict) and _key(a) == key)] + [record],
        }
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if path.is_file():
            shutil.copyfile(path, path.with_name(f".{path.name}.bak"))
        os.replace(tmp, path)
    return path


def try_record(workspace: Path | None, record: dict[str, Any]) -> str | None:
    """``record_load`` that never raises: returns the error text, or None when recorded."""
    if workspace is None:
        return "no workspace"
    try:
        record_load(workspace, record)
    except OSError as e:
        logger.warning("could not record the load in %s: %s", DATA_SOURCES_FILE, e)
        return f"{type(e).__name__}: {e}"
    return None
