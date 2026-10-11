"""Eurostat: official statistics of the EU, its member states and regions (NUTS), through Eurostat's dissemination API.

- Service (keyless): the table of contents
  (``/catalogue/toc/txt``) lists every dataset with its code, title, last
  update and period; ``datasets`` searches it. The statistics API
  (``/statistics/1.0/data/<code>``, JSON-stat 2.0) returns a dataset filtered
  by dimension (``unit=MIO_EUR``, ``geo=DE1``), by NUTS level
  (``geoLevel=nuts2``) and by period (``sinceTimePeriod``,
  ``untilTimePeriod``); ``data`` reads it into one row per observation with
  every dimension's code and label, and ``dimensions`` lists the codes a
  dataset uses (from its latest period).
- Terms (copyright notice, https://ec.europa.eu/eurostat/en/help/copyright-notice,
  checked 2026-10-11): reuse "for commercial or non-commercial purposes is
  authorised provided the source is acknowledged"; data of sources other than
  Eurostat and data for countries outside the EU, EFTA and the candidate
  countries "may not be reused for commercial purposes, but non-commercial
  reuse is possible without restriction". A study may pass the data on.
- Citation, as the notice asks: "Source: [digital object identifier (DOI)
  number of the Eurostat dataset], [access date]"; a filtered extract is a
  customised version: "Source: [Eurostat dataset datacode link], [access
  date]". Each load cites both (the DOI from the dataset's own annotation).
- Version: Eurostat keeps no past versions ("there is no versioning or
  documentation of past versions of the data", API introduction); each load
  records the dataset's ``updated`` time stamp, the query and the SHA-256 of
  the answer, so the study's extract is the record.
- Limits: the API answers up to 500,000 cells at once (more is answered
  asynchronously or refused); Eurostat asks scripts for one request at a time
  and no parallel requests.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

BASE = "https://ec.europa.eu/eurostat/api/dissemination"
STATS = f"{BASE}/statistics/1.0/data"
TOC = f"{BASE}/catalogue/toc/txt"
#: The most observations one load reads (beyond: filter by dimension, region level or period).
MAX_ROWS = 500_000
GEO_LEVELS = ("aggregate", "country", "nuts1", "nuts2", "nuts3", "city")

TERMS_URL = "https://ec.europa.eu/eurostat/en/help/copyright-notice"
_DOI = re.compile(r"https?://doi\.org/10\.2908/[A-Za-z0-9_$.\-]+")


def _code(value: str, what: str) -> str:
    v = str(value).strip()
    if not v or not v.replace("_", "").replace("-", "").replace("$", "").isalnum():
        raise FetchError(f"--{what} {value!r} is not a Eurostat code (e.g. nama_10r_2gdp)")
    return v


def _estat_error(content: bytes, url: str) -> None:
    """The API answers an error as ``{"error": [{"status": …, "label": …}]}``."""
    try:
        doc = json.loads(content)
    except ValueError:
        return
    if isinstance(doc, dict) and doc.get("error"):
        errs = doc["error"] if isinstance(doc["error"], list) else [doc["error"]]
        text = "; ".join(str(e.get("label") or e) for e in errs if isinstance(e, dict))
        raise FetchError(f"{url}: Eurostat refused the request: {text}")


async def _get(ctx: Context, url: str, params: dict[str, Any]) -> bytes:
    """GET, with Eurostat's error document (also sent with HTTP 4xx) as the message."""
    try:
        content = await ctx.http.get_bytes(url, params)
    except FetchError as e:
        msg = str(e)
        if '"error"' in msg and "label" in msg:
            label = msg.split('"label":', 1)[1].strip().strip('"}] ')
            raise FetchError(f"{ctx.http.requests[-1]}: Eurostat refused the request: {label}") from None
        raise
    _estat_error(content, ctx.http.requests[-1])
    return content


async def fetch_datasets(ctx: Context, params: dict[str, Any]) -> Fetched:
    import pandas as pd

    from .adapters import download_file

    words = str(params["query"]).lower().split()
    if not words:
        raise FetchError("--query is empty; give words of the dataset's title, e.g. 'gdp nuts 2'")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path, meta = await download_file(ctx.http, f"{TOC}?lang=en", "eurostat", version=f"toc_{today}", name="toc.txt")
    toc = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    toc.columns = [c.strip() for c in toc.columns]
    toc["title"] = toc["title"].str.strip()
    toc = toc[toc["type"].isin(["dataset", "table"])].drop_duplicates(subset=["code"])
    hay = (toc["code"] + " " + toc["title"]).str.lower()
    hit = toc[hay.apply(lambda h: all(w in h for w in words))]
    limit = int(params.get("limit") or 50)
    rows = [
        {
            "code": r["code"],
            "title": r["title"],
            "type": r["type"],
            "last_update": r.get("last update of data", "").strip() or None,
            "data_start": r.get("data start", "").strip() or None,
            "data_end": r.get("data end", "").strip() or None,
            "values": int(r["values"]) if str(r.get("values", "")).strip().isdigit() else None,
        }
        for _, r in hit.head(limit).iterrows()
    ]
    return Fetched(
        rows=rows,
        series=f"Eurostat datasets matching {' '.join(words)!r}",
        query=meta["url"],
        note=f"{len(hit)} datasets match; showing {len(rows)}. List a dataset's codes: dimensions --dataset <code>.",
    )


def _decode(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """JSON-stat 2.0 → one record per observation, with each dimension's code and label."""
    ids: list[str] = doc.get("id") or []
    sizes: list[int] = doc.get("size") or []
    values = doc.get("value") or {}
    status = doc.get("status") or {}
    dims = doc.get("dimension") or {}
    cats: list[list[tuple[str, str]]] = []
    for d in ids:
        cat = (dims.get(d) or {}).get("category") or {}
        index = cat.get("index") or {}
        labels = cat.get("label") or {}
        order = sorted(index, key=lambda k: index[k]) if isinstance(index, dict) else list(index)
        cats.append([(code, labels.get(code, code)) for code in order])
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    if isinstance(status, list):
        status = {str(i): s for i, s in enumerate(status) if s}
    keys = sorted({int(k) for k in values} | {int(k) for k in status})
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    out = []
    for flat in keys:
        rec: dict[str, Any] = {}
        rest = flat
        for d, stride, cat in zip(ids, strides, cats, strict=True):
            pos, rest = divmod(rest, stride)
            code, label = cat[pos]
            if d == "time":
                rec["time"] = code
            else:
                rec[d] = code
                rec[f"{d}_label"] = label
        rec["value"] = values.get(str(flat))
        rec["flag"] = status.get(str(flat)) or None
        out.append(rec)
    return out


def _filters(raw: list[str] | None) -> list[tuple[str, str]]:
    """``["unit=MIO_EUR", "geo=DE1+DE2"]`` → ``[("unit", "MIO_EUR"), ("geo", "DE1"), ("geo", "DE2")]``."""
    out = []
    for item in raw or []:
        if "=" not in item:
            raise FetchError(f"--filter {item!r}: give dimension=code, e.g. unit=MIO_EUR or geo=DE1+DE2")
        dim, codes = (x.strip() for x in item.split("=", 1))
        if not dim.replace("_", "").isalnum() or not codes:
            raise FetchError(f"--filter {item!r}: give dimension=code, e.g. unit=MIO_EUR or geo=DE1+DE2")
        out += [(dim.lower(), c.strip()) for c in codes.split("+") if c.strip()]
    return out


async def fetch_data(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import sha256_bytes

    code = _code(params["dataset"], "dataset")
    filters = _filters(params.get("filter"))
    level = params.get("geo_level")
    if level and level not in GEO_LEVELS:
        raise FetchError(f"--geo-level {level!r}: one of {', '.join(GEO_LEVELS)}")
    if level and any(d == "geo" for d, _ in filters):
        raise FetchError("give either --geo-level or a geo filter, not both (Eurostat accepts one)")
    query: dict[str, Any] = {"lang": "en"}
    for dim, value in filters:
        query.setdefault(dim, []).append(value)
    query.update({"geoLevel": level, "sinceTimePeriod": params.get("start"), "untilTimePeriod": params.get("end")})
    url = f"{STATS}/{code}"
    content = await _get(ctx, url, query)
    doc = json.loads(content)
    if isinstance(doc, dict) and doc.get("warning"):
        label = str((doc["warning"] or {}).get("label") if isinstance(doc["warning"], dict) else doc["warning"])
        raise FetchError(
            f"{ctx.http.requests[-1]}: Eurostat answers this request only asynchronously ({label}); it is too large: "
            "filter by dimension (--filter), region level (--geo-level) or period (--start/--end)"
        )
    n = len(doc.get("value") or {})
    if n > MAX_ROWS:
        raise FetchError(
            f"{n} observations: more than e2er loads at once ({MAX_ROWS}); filter by dimension "
            "(--filter), region level (--geo-level) or period (--start/--end)"
        )
    rows = _decode(doc)
    label = doc.get("label") or code
    where = ", ".join(f"{d}={c}" for d, c in filters) + (f", {level}" if level else "")
    span = f"{params.get('start') or 'first'}–{params.get('end') or 'latest'}"
    freq = {"A": "annual", "Q": "quarterly", "M": "monthly", "D": "daily", "S": "half-yearly"}
    codes = {str(r.get("freq")) for r in rows}
    updated = doc.get("updated")
    found = _DOI.search(content.decode("utf-8", errors="replace"))
    doi = found.group(0).replace("http://", "https://") if found else None
    return Fetched(
        rows=rows,
        series=f"Eurostat {code}: {label}" + (f" ({where})" if where else "") + f", {span}",
        query=ctx.http.requests[-1],
        version=updated,
        files=[{"url": ctx.http.requests[-1], "sha256": sha256_bytes(content)}],
        link=f"https://ec.europa.eu/eurostat/databrowser/view/{code}/default/table?lang=en",
        citation=_citation(
            code,
            label,
            doi,
            ctx.http.requests[-1] if (filters or level or params.get("start") or params.get("end")) else None,
        ),
        record={"dataset_code": code, "dataset_title": label, "doi": doi},
        frequency=freq.get(next(iter(codes))) if len(codes) == 1 else None,
        note=(
            "One row per observation: each dimension's code and label, time, value and Eurostat's flag "
            "(p provisional, e estimated, b break in series, c confidential, u low reliability, …)."
        ),
    )


async def fetch_dimensions(ctx: Context, params: dict[str, Any]) -> Fetched:
    code = _code(params["dataset"], "dataset")
    content = await _get(ctx, f"{STATS}/{code}", {"lang": "en", "lastTimePeriod": 1})
    doc = json.loads(content)
    rows = []
    for d in doc.get("id") or []:
        dim = (doc.get("dimension") or {}).get(d) or {}
        cat = dim.get("category") or {}
        index = cat.get("index") or {}
        for c in sorted(index, key=lambda k: index[k]) if isinstance(index, dict) else list(index):
            rows.append(
                {
                    "dimension": d,
                    "dimension_label": dim.get("label"),
                    "code": c,
                    "label": (cat.get("label") or {}).get(c, c),
                }
            )
    return Fetched(
        rows=rows,
        series=f"codes of Eurostat {code} (its latest period)",
        query=ctx.http.requests[-1],
        note="The codes present in the latest period; earlier periods may have others (e.g. older NUTS versions).",
    )


def _citation(code: str, title: str, doi: str | None, extract: str | None) -> str:
    """Eurostat's format: "Source: [DOI], [access date]"; a filtered extract also "Source: [datacode link], [date]"."""
    d = datetime.now(UTC).strftime("%Y-%m-%d")
    link = f"https://ec.europa.eu/eurostat/databrowser/view/{code}/default/table?lang=en"
    out = f"Eurostat, {title} ({code}). Source: {doi or link}, {d}."
    if extract:
        out += f" Customised version: Source: {extract}, {d}."
    return out


CITATION = "Eurostat. Source: Eurostat database, https://ec.europa.eu/eurostat/data/database, [access date]."
CITE_KEY = "Eurostat_Database"
BIBTEX = """@misc{Eurostat_Database,
  author       = {{Eurostat}},
  title        = {Eurostat Database},
  howpublished = {Eurostat dissemination API, \\url{https://ec.europa.eu/eurostat/api/dissemination/}},
  url          = {https://ec.europa.eu/eurostat/data/database},
  note         = {Source: Eurostat}
}"""

SOURCE = Source(
    name="eurostat",
    label="Eurostat",
    dataset="Eurostat database (dissemination API), European Commission",
    website="https://ec.europa.eu/eurostat/data/database",
    terms_url=TERMS_URL,
    terms_summary=(
        "Reuse for commercial or non-commercial purposes is authorised provided the source is acknowledged; "
        "data of non-Eurostat sources and of countries outside the EU, EFTA and candidate countries may be reused "
        "non-commercially only. Modified data must say so."
    ),
    terms_plain=(
        "Free reuse, commercial or not, provided the source (Eurostat) is acknowledged.",
        "Data that belong to other sources, and data for countries outside the EU, EFTA and the candidate "
        "countries (e.g. the USA, Japan, China), may be reused non-commercially only.",
        "Changed data must be marked as changed, with a disclaimer that Eurostat is not responsible.",
        "Eurostat keeps no past versions: the study's extract (recorded with its SHA-256) is the record.",
    ),
    licence=(
        f'Eurostat copyright notice ({TERMS_URL}): "Reuse of statistical data, metadata, publications, and other '
        "dissemination tools published on this website for commercial or non-commercial purposes is authorised "
        "provided the source is acknowledged. The reuse policy of the European Commission is implemented by the "
        'Decision of 12 December 2011." "The following Eurostat data and documents may not be reused for '
        "commercial purposes, but non-commercial reuse is possible without restriction: Data identified as "
        "belonging to sources other than Eurostat. […] Data for countries other than: Member States of the "
        "European Union (EU); Member States of the European Free Trade Association (EFTA); official EU acceding "
        'and candidate countries." "When reuse involves translations of publications or modifications to the '
        "data or text, this must be stated clearly to the end user of the information. A disclaimer regarding the "
        'non-responsibility of Eurostat shall be included."'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Official EU statistics by country and region (NUTS 0–3): national and regional accounts, prices (HICP), "
        "labour market, population, health, education, energy, environment, trade, tourism; thousands of datasets. "
        "Find a dataset with `datasets`, list its codes with `dimensions`, load with `data` (filters by dimension, "
        "NUTS level and period)."
    ),
    coverage="Official EU statistics by country and NUTS region (thousands of datasets).",
    help="Eurostat: official EU statistics by country and NUTS region. No key.",
    operations=(
        Operation(
            "datasets",
            "Find datasets by words of their title or code, e.g. --query 'gdp nuts 2'.",
            args=(
                Arg("query", "Words that must all appear in the dataset's title or code.", required=True),
                Arg("limit", "Most datasets to list (default 50).", type=int),
            ),
            fetch=fetch_datasets,
            loads=False,
            card="List datasets whose title contains words → code, title, last update, period. Params: query "
            "(required), limit.",
        ),
        Operation(
            "dimensions",
            "The dimensions of a dataset and the codes it uses, e.g. --dataset nama_10r_2gdp.",
            args=(Arg("dataset", "Dataset code, e.g. nama_10r_2gdp.", required=True),),
            fetch=fetch_dimensions,
            loads=False,
            card="A dataset's dimensions and codes (from its latest period). Params: dataset (required).",
        ),
        Operation(
            "data",
            "Observations of a dataset, e.g. --dataset nama_10r_2gdp --filter unit=MIO_EUR --geo-level nuts2 "
            "--start 2015.",
            args=(
                Arg("dataset", "Dataset code, e.g. nama_10r_2gdp.", required=True),
                Arg(
                    "filter",
                    "dimension=code pairs, comma-separated; several codes with +, e.g. unit=MIO_EUR,geo=DE1+DE2.",
                    type="list",
                ),
                Arg("geo-level", "Regions of one level instead of a geo filter.", choices=GEO_LEVELS),
                Arg("start", "First period (e.g. 2015, 2015-Q1, 2015-01)."),
                Arg("end", "Last period."),
            ),
            fetch=fetch_data,
            card="Observations of a dataset → one row per observation (dimension codes and labels, time, value, "
            "flag). Params: dataset (required), filter (list of 'dim=code+code'), geo_level (nuts0..nuts3, "
            "country, aggregate, city), start, end.",
        ),
    ),
    polite=Polite(min_interval=1.0, max_requests=10, timeout=180.0),
    aliases=("estat", "eurostat_database", "european_statistics"),
    skill="data/eurostat",
    doctor=Doctor(
        "data.eurostat.data",
        operation="data",
        params={"dataset": "nama_10r_2gdp", "filter": "unit=MIO_EUR,geo=DE1", "start": "2022", "end": "2022"},
    ),
)
