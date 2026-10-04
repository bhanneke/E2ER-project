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
  local file), where the source serves files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

DATA_SOURCES_FILE = "data_sources.json"


@dataclass(frozen=True)
class SourceInfo:
    """What e2er records about a source on every load: its name, terms and citation."""

    connector: str
    dataset: str
    website: str
    terms_url: str
    #: The terms in one or two sentences, for a study page.
    terms_summary: str
    #: The terms in full, as the connector states them.
    licence: str
    #: ``source``: the source publishes the citation format; ``e2er``: it publishes none.
    citation_by: str


FRED = SourceInfo(
    connector="fred",
    dataset="FRED, Federal Reserve Bank of St. Louis",
    website="https://fred.stlouisfed.org",
    terms_url="https://fred.stlouisfed.org/legal/",
    terms_summary=(
        "FRED's terms of use apply. Each series page states its copyright status: public domain (citation "
        "requested), copyrighted with citation required, or copyrighted with the owner's permission needed "
        "for any use beyond personal use."
    ),
    licence=(
        "FRED legal notices, information and terms of use (https://fred.stlouisfed.org/legal/). Copyright status "
        "is stated beneath each series on FRED: Public Domain: Citation Requested; Copyrighted: Citation Required; "
        "Copyrighted: Pre-approval Required. Before using data series owned by third parties for anything other "
        "than your own personal use, you must contact the data owner to obtain permission. Cite each series "
        "with the suggested citation on its Cite tab."
    ),
    citation_by="source",
)

YFINANCE = SourceInfo(
    connector="yfinance",
    dataset="Yahoo Finance (through yfinance)",
    website="https://finance.yahoo.com",
    terms_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    terms_summary=(
        "Yahoo's terms of use apply. The yfinance project notes that Yahoo's finance data are intended "
        "for personal use only; yfinance is not affiliated with Yahoo."
    ),
    licence=(
        "Yahoo terms of service (https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html). The data are "
        "read through yfinance, which is not affiliated with Yahoo; its documentation refers users to "
        "Yahoo's terms for their rights to use the data and notes that the data are intended for personal use only."
    ),
    citation_by="e2er",
)

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
    out = base(FRED)
    out.update(
        {
            "series": series_id,
            "link": f"https://fred.stlouisfed.org/series/{series_id}",
            "retrieved_at": retrieved_at,
            "citation": fred_citation(series_id, retrieved_at, title=title, source=source),
            "citation_by": FRED.citation_by,
        }
    )
    if title:
        out["title"] = title
    if last_updated:
        # FRED revises series; the vintage read is the one current at retrieval.
        out["last_updated"] = last_updated
    return out


def yfinance_load(ticker: str, retrieved_at: str, *, what: str = "daily prices") -> dict[str, Any]:
    out = base(YFINANCE)
    out.update(
        {
            "series": f"{ticker} {what}",
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "retrieved_at": retrieved_at,
            "citation": (
                f"Yahoo Finance, {ticker} {what}, retrieved through yfinance on {retrieved_at[:10]}, "
                f"https://finance.yahoo.com/quote/{ticker}."
            ),
            "citation_by": YFINANCE.citation_by,
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


def record_load(workspace: Path, record: dict[str, Any]) -> Path:
    """Write ``record`` into the study's ``data_sources.json`` (one entry per table or saved file).

    A later load into the same table (or the same saved file, or of the same
    series from the same source when nothing was saved) replaces the earlier
    entry; everything else is kept. Export ships the file as
    ``data/data_sources.json`` and the dossier lists its entries.
    """
    path = Path(workspace) / DATA_SOURCES_FILE
    loads: list[Any] = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("loads"), list):
                loads = loaded["loads"]
        except (OSError, ValueError):
            logger.warning("%s is unreadable; starting it again", path)
    doc: dict[str, Any] = {
        "$comment": (
            "Written by e2er-data: one entry per external-source load, with the source version, "
            "the URL and SHA-256 of every file read."
        ),
        "loads": loads,
    }
    record = {k: v for k, v in record.items() if v is not None}
    key = _key(record)
    doc["loads"] = [a for a in doc["loads"] if not (isinstance(a, dict) and _key(a) == key)] + [record]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
