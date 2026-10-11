"""Generic adapters: the four ways most open-data services serve tables.

Each adapter takes the kit's :class:`~.http.PoliteClient` and returns rows (a
pandas DataFrame or a list of records) and what the load record needs (the
query as sent, the file's SHA-256), so a new source's fetch function is a few
lines:

- :func:`rest_json_pages` — a REST API returning JSON, page after page
  (page numbers, offset/limit, or a "next" link);
- :func:`tap_query` — an IVOA TAP service (astronomy archives: NASA Exoplanet
  Archive, ESA Gaia, SDSS) queried with ADQL, synchronously, as CSV;
- :func:`download_file` + :func:`read_table` — a CSV, TSV or ZIP file,
  cached by version under ``~/.e2er/cache/<source>/<version>/`` and re-hashed
  (SHA-256) on every use;
- :func:`sdmx_data` — an SDMX 2.1 REST service (Eurostat, OECD, IMF, ECB, the
  ILO, UN SDG) read as SDMX-CSV.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import FetchError
from .http import PoliteClient


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_dir(source: str) -> Path:
    """``$E2ER_CACHE_DIR/<source>`` when set, else ``~/.e2er/cache/<source>``."""
    root = os.environ.get("E2ER_CACHE_DIR")
    return (Path(root) if root else Path.home() / ".e2er" / "cache") / source


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dig(doc: Any, path: str) -> Any:
    """``doc["a"]["b"]`` for ``path="a.b"``; ``""`` is the document itself."""
    for part in [p for p in path.split(".") if p]:
        if isinstance(doc, dict):
            doc = doc.get(part)
        elif isinstance(doc, list) and part.isdigit():
            doc = doc[int(part)] if int(part) < len(doc) else None
        else:
            return None
    return doc


# ── REST JSON with paging ────────────────────────────────────────────────────


async def rest_json_pages(
    http: PoliteClient,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    items: str = "",
    paging: str = "none",
    page_param: str = "page",
    first_page: int = 1,
    size_param: str = "per_page",
    page_size: int | None = None,
    offset_param: str = "offset",
    next_link: str | Callable[[Any], str | None] = "next",
    total: str = "",
    max_items: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """All records of a paged JSON API, and the URLs requested.

    ``items`` is the path of the record list in each page (``"results"``,
    ``"data.items"``; ``""`` when the page is the list). ``paging``:

    - ``"none"``: one request;
    - ``"page"``: ``page_param`` = 1, 2, … (``size_param`` = ``page_size``)
      until a page has fewer than ``page_size`` records, or none;
    - ``"offset"``: ``offset_param`` = 0, n, 2n, … the same way;
    - ``"next"``: follow the URL at ``next_link`` (a path in the page, or a
      function of the page) until there is none.

    ``total`` (a path) stops when that many records have arrived;
    ``max_items`` stops after that many. The client's ``max_requests`` bounds
    the number of pages.
    """
    params = dict(params or {})
    out: list[dict[str, Any]] = []
    start = len(http.requests)
    if page_size and paging in ("page", "offset"):
        params[size_param] = page_size
    page, offset = first_page, 0
    next_url: str | None = url
    while next_url:
        call = dict(params)
        if paging == "page":
            call[page_param] = page
        elif paging == "offset":
            call[offset_param] = offset
        doc = await http.get_json(next_url, call if next_url == url or paging != "next" else None)
        rows = _dig(doc, items)
        if rows is None:
            raise FetchError(f"{http.requests[-1]}: the response has no {items or 'list'} of records")
        if not isinstance(rows, list):
            rows = [rows]
        out.extend(r for r in rows if isinstance(r, dict))
        if max_items is not None and len(out) >= max_items:
            out = out[:max_items]
            break
        want = _dig(doc, total) if total else None
        if isinstance(want, int) and len(out) >= want:
            break
        if paging == "none" or not rows:
            break
        if paging == "next":
            link = next_link(doc) if callable(next_link) else _dig(doc, next_link)
            next_url = str(link) if link else None
            continue
        if page_size and len(rows) < page_size:
            break
        page += 1
        offset += len(rows)
    return out, http.requests[start:]


# ── TAP / ADQL (astronomy archives) ──────────────────────────────────────────


async def tap_query(http: PoliteClient, service: str, adql: str, *, max_rows: int | None = None) -> tuple[Any, str]:
    """Rows of an ADQL query on a TAP service (synchronous, CSV), and the URL requested.

    ``service`` is the TAP base (``https://exoplanetarchive.ipac.caltech.edu/TAP``);
    the query goes to ``<service>/sync``. A TAP error (a VOTable with
    ``QUERY_STATUS="ERROR"``) becomes a FetchError with the service's message.
    """
    df, url, _ = await _tap(http, service, adql, max_rows)
    return df, url


async def _tap(http: PoliteClient, service: str, adql: str, max_rows: int | None) -> tuple[Any, str, bytes]:
    """``tap_query``, plus the CSV as read (for its SHA-256)."""
    import pandas as pd

    params: dict[str, Any] = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": " ".join(adql.split())}
    if max_rows is not None:
        params["MAXREC"] = max_rows
    # A TAP service may answer a refused query with HTTP 400 and an error VOTable (Gaia): read its message.
    resp = await http.get(service.rstrip("/") + "/sync", params, ok_status=(400,))
    text = resp.text
    if "<VOTABLE" in text[:500].upper() or 'QUERY_STATUS" VALUE="ERROR' in text.upper():
        import re

        msg = re.search(r"<INFO[^>]*ERROR[^>]*>(.*?)</INFO>", text, re.S | re.I)
        import html

        raise FetchError(
            "the TAP service refused the query: " + " ".join(html.unescape(msg.group(1) if msg else text[:300]).split())
        )
    if resp.status_code // 100 != 2:
        raise FetchError(f"{http.requests[-1]}: HTTP {resp.status_code}: {' '.join(text[:300].split())}")
    try:
        df = pd.read_csv(io.StringIO(text)) if text.strip() else pd.DataFrame()
    except ValueError as e:
        raise FetchError(f"{http.requests[-1]}: the answer is not CSV ({e})") from None
    return df, http.requests[-1], resp.content


def adql_select_only(adql: str) -> str:
    """The query, one line, when it is a single ADQL SELECT; else a FetchError (a TAP service is read-only anyway)."""
    q = " ".join(str(adql).split()).rstrip(";").strip()
    if not q.lower().startswith(("select ", "with ")):
        raise FetchError("--adql must be one ADQL SELECT query, e.g. SELECT TOP 10 * FROM ps")
    if ";" in q:
        raise FetchError("--adql must be one query (no ';')")
    return q


async def tap_capped(http: PoliteClient, service: str, adql: str, cap: int) -> tuple[Any, str, str]:
    """``tap_query`` with a row cap that never cuts a table silently; also the SHA-256 of the CSV read.

    The service is asked for ``cap + 1`` rows (``MAXREC``); more than ``cap``
    rows back means the result would be cut, and the load stops with a
    FetchError instead of saving a partial table.
    """
    df, url, content = await _tap(http, service, adql, cap + 1)
    if len(df) > cap:
        raise FetchError(
            f"the query returns more than {cap:,} rows, the cap of this load; the table would be cut. "
            "Narrow the query (fewer columns do not help: add conditions, a smaller region, a brighter limit) "
            "or raise --max-rows if the source allows it"
        )
    return df, url, sha256_bytes(content)


# ── CSV / ZIP download, versioned and hashed ─────────────────────────────────


async def download_file(
    http: PoliteClient, url: str, source: str, *, version: str | None = None, name: str | None = None
) -> tuple[Path, dict[str, Any]]:
    """The file at ``url`` on disk, and its record ``{url, sha256, bytes, retrieved_at, from_cache}``.

    With a ``version`` the file is kept under ``<cache>/<source>/<version>/``
    and reused while its SHA-256 matches the one recorded when it was
    downloaded (a changed file is downloaded again). Without one it is
    downloaded every time (into ``<cache>/<source>/latest/``).
    """
    name = name or Path(url.split("?", 1)[0]).name or "download"
    target = cache_dir(source) / (version or "latest") / name
    meta_path = target.with_name(target.name + ".json")
    if version and target.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        if meta.get("sha256") and sha256_file(target) == meta["sha256"]:
            return target, {**meta, "from_cache": True}
    content = await http.get_bytes(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(content)
    tmp.replace(target)
    meta = {"url": http.requests[-1], "sha256": sha256_bytes(content), "bytes": len(content), "retrieved_at": now_utc()}
    if version:
        meta["version"] = version
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return target, {**meta, "from_cache": False}


def read_table(path: Path, *, member: str | None = None, **read_csv: Any) -> Any:
    """A CSV/TSV file, or one member of a ZIP file, as a DataFrame.

    For a ZIP, ``member`` names the file inside (default: the only .csv/.tsv
    in it); ``read_csv`` keywords go to ``pandas.read_csv`` (``sep`` is
    inferred from a .tsv name).
    """
    import pandas as pd

    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".csv", ".tsv", ".txt"))]
            if member is None:
                if len(names) != 1:
                    raise FetchError(f"{path.name} holds {len(names)} tables ({', '.join(names)}); name one")
                member = names[0]
            if member not in z.namelist():
                raise FetchError(f"{path.name} has no {member}; it holds {', '.join(z.namelist())}")
            data = z.read(member)
        if member.lower().endswith(".tsv"):
            read_csv.setdefault("sep", "\t")
        return pd.read_csv(io.BytesIO(data), **read_csv)
    if path.suffix.lower() == ".tsv":
        read_csv.setdefault("sep", "\t")
    return pd.read_csv(path, **read_csv)


# ── SDMX (official statistics) ───────────────────────────────────────────────

SDMX_CSV = "application/vnd.sdmx.data+csv;version=1.0.0"


async def sdmx_data(
    http: PoliteClient,
    base: str,
    flow: str,
    key: str = "all",
    *,
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    accept: str = SDMX_CSV,
) -> tuple[Any, str]:
    """An SDMX 2.1 data query (``<base>/data/<flow>/<key>``) as a DataFrame, and the URL requested.

    ``key`` is the dot-separated series key (``M.DE.CP00`` or ``all``);
    ``start``/``end`` are ``startPeriod``/``endPeriod``. The service is asked
    for SDMX-CSV (``accept``); services that want a ``format`` parameter
    instead (Eurostat: ``format=SDMX-CSV``) get it through ``params``.
    """
    import pandas as pd

    query = {"startPeriod": start, "endPeriod": end, **(params or {})}
    resp = await http.get(f"{base.rstrip('/')}/data/{flow}/{key}", query, headers={"Accept": accept})
    text = resp.text
    if not text.strip():
        return pd.DataFrame(), http.requests[-1]
    try:
        df = pd.read_csv(io.StringIO(text))
    except ValueError as e:
        raise FetchError(f"{http.requests[-1]}: the answer is not SDMX-CSV ({e})") from None
    if "OBS_VALUE" not in df.columns:
        raise FetchError(f"{http.requests[-1]}: the answer has no OBS_VALUE column (columns: {', '.join(df.columns)})")
    return df, http.requests[-1]
