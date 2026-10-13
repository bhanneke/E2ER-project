"""World Bank Open Data: development indicators by country and year, through the Indicators API (v2).

- Service: https://api.worldbank.org/v2/ (keyless; "API keys and other
  authentication methods are no longer necessary to access the API",
  https://datahelpdesk.worldbank.org/knowledgebase/articles/889392). ``indicator``
  lists a database's indicators (the API has no text search, so ``indicators``
  reads the list of one database and filters it here);
  ``country/<codes>/indicator/<id>`` returns the values, page after page;
  ``sources/<id>/series/<id>/metadata`` the indicator's metadata, with its
  licence (``License_Type``, ``License_URL``) and its data source.
- Terms (Terms of Use for Datasets,
  https://www.worldbank.org/ext/en/legal/terms-conditions/datasets, checked
  2026-10-11): "Unless specifically labeled otherwise, these Datasets are
  provided to you under a Creative Commons Attribution 4.0 International
  License (CC BY 4.0)", with attribution "in the following format: The World
  Bank: Dataset name: Data source (if known)". Third-party data may carry other
  terms: "Where applicable, these conditions are included in the dataset or
  indicator metadata." Every load therefore records each indicator's licence
  from its metadata and says so when one is not CC BY 4.0.
- Citation: the attribution format the terms ask for, per load (database and
  the indicators' data sources); the BibTeX entry is e2er's (the World Bank
  publishes none for the API).
- Version: the database's ``lastupdated`` date as the API reports it.
"""

from __future__ import annotations

from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

API = "https://api.worldbank.org/v2"
TERMS_URL = "https://www.worldbank.org/ext/en/legal/terms-conditions/datasets"
WDI = "2"
#: The most indicators one load reads (each costs a metadata request and one or more pages).
MAX_INDICATORS = 20
PAGE = 20000

CITE_KEY = "WorldBank_OpenData"
CITATION = (
    "The World Bank: World Development Indicators. World Bank Open Data, https://data.worldbank.org. "
    "Licence: CC BY 4.0."
)
BIBTEX = """@misc{WorldBank_OpenData,
  author       = {{The World Bank}},
  title        = {World Bank Open Data},
  howpublished = {Indicators API v2, \\url{https://api.worldbank.org/v2/}},
  url          = {https://data.worldbank.org},
  note         = {Licence: CC BY 4.0 unless an indicator's metadata states otherwise}
}"""
CC_BY = ("CC BY-4.0", "CC BY 4.0", "CC-BY-4.0", "CC BY")


def _wb_error(doc: Any, url: str) -> None:
    """The API answers a bad request with HTTP 200 and ``[{"message": [...]}]``."""
    if isinstance(doc, list) and doc and isinstance(doc[0], dict) and doc[0].get("message"):
        msgs = doc[0]["message"]
        text = "; ".join(f"{m.get('key', '')}: {m.get('value', '')}".strip(": ") for m in msgs if isinstance(m, dict))
        raise FetchError(f"{url}: the World Bank API refused the request ({text or msgs})")


def _codes(values: list[str] | None, what: str) -> list[str]:
    out = []
    for v in values or []:
        v = v.strip()
        if not v.replace(".", "").replace("_", "").isalnum():
            raise FetchError(f"--{what} {v!r} is not a code (e.g. NY.GDP.PCAP.CD, DEU)")
        out.append(v)
    return out


def _year(value: Any, what: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        y = int(str(value)[:4])
    except ValueError:
        raise FetchError(f"--{what} {value!r} is not a year (YYYY)") from None
    if not 1900 <= y <= 2100:
        raise FetchError(f"--{what} {value!r} is not a year between 1900 and 2100")
    return y


async def fetch_indicators(ctx: Context, params: dict[str, Any]) -> Fetched:
    query = str(params["query"]).strip().lower()
    if not query:
        raise FetchError("--query is empty; give words of the indicator's name, e.g. 'gdp per capita'")
    source = str(params.get("database") or WDI)
    url = f"{API}/indicator"
    doc = await ctx.http.get_json(url, {"format": "json", "per_page": PAGE, "source": source})
    _wb_error(doc, ctx.http.requests[-1])
    records = doc[1] if isinstance(doc, list) and len(doc) > 1 and isinstance(doc[1], list) else []
    words = query.split()
    rows = []
    for r in records:
        hay = f"{r.get('id', '')} {r.get('name', '')}".lower()
        if all(w in hay for w in words):
            rows.append(
                {
                    "indicator": r.get("id"),
                    "name": r.get("name"),
                    "database": (r.get("source") or {}).get("value"),
                    "unit": r.get("unit") or None,
                    "data_source": r.get("sourceOrganization") or None,
                    "description": (r.get("sourceNote") or "")[:400] or None,
                }
            )
    limit = int(params.get("limit") or 50)
    return Fetched(
        rows=rows[:limit],
        series=f"World Bank indicators matching {query!r} (database {source})",
        query=ctx.http.requests[-1],
        note=f"{len(rows)} indicators match; showing {min(len(rows), limit)}. Load one with: series --indicator <id>.",
    )


def _meta(doc: Any) -> dict[str, str]:
    """``{metatype id: value}`` of one series' metadata document."""
    try:
        variable = doc["source"][0]["concept"][0]["variable"][0]
        return {m["id"]: m.get("value", "") for m in variable.get("metatype", [])}
    except (KeyError, IndexError, TypeError):
        return {}


async def fetch_series(ctx: Context, params: dict[str, Any]) -> Fetched:
    import json

    from .adapters import sha256_bytes

    indicators = _codes(params["indicator"], "indicator")
    if not indicators:
        raise FetchError("--indicator is empty; give one or more indicator codes, e.g. NY.GDP.PCAP.CD")
    if len(indicators) > MAX_INDICATORS:
        raise FetchError(f"{len(indicators)} indicators: load at most {MAX_INDICATORS} at a time")
    countries = _codes(params.get("countries"), "countries") or ["all"]
    start, end = _year(params.get("start"), "start"), _year(params.get("end"), "end")
    if start and end and start > end:
        raise FetchError(f"--start {start} is after --end {end}")
    source = str(params.get("database") or WDI)
    date = f"{start or 1960}:{end or 2100}" if (start or end) else None

    rows: list[dict[str, Any]] = []
    files, licences, data_sources, queries = [], {}, {}, []
    version = None
    db_name = ""
    for ind in indicators:
        meta_doc = await ctx.http.get_json(f"{API}/sources/{source}/series/{ind}/metadata", {"format": "json"})
        _wb_error(meta_doc, ctx.http.requests[-1])
        meta = _meta(meta_doc)
        try:
            db_name = db_name or str(meta_doc["source"][0]["name"])
        except (KeyError, IndexError, TypeError):
            pass
        licences[ind] = {"licence": meta.get("License_Type") or None, "licence_url": meta.get("License_URL") or None}
        if meta.get("Source"):
            data_sources[ind] = " ".join(meta["Source"].split())
        url = f"{API}/country/{';'.join(countries)}/indicator/{ind}"
        q = {"format": "json", "per_page": PAGE, "source": source, "date": date}
        doc_rows: list[Any] = []
        page, pages = 1, 1
        while page <= pages:
            content = await ctx.http.get_bytes(url, {**q, "page": page})
            if page == 1:
                queries.append(ctx.http.requests[-1])
            files.append({"url": ctx.http.requests[-1], "sha256": sha256_bytes(content)})
            try:
                doc = json.loads(content)
            except ValueError:
                raise FetchError(f"{ctx.http.requests[-1]}: the answer is not JSON") from None
            _wb_error(doc, ctx.http.requests[-1])
            header = doc[0] if isinstance(doc, list) and doc and isinstance(doc[0], dict) else {}
            doc_rows.extend(doc[1] if isinstance(doc, list) and len(doc) > 1 and isinstance(doc[1], list) else [])
            version = header.get("lastupdated") or version
            pages = int(header.get("pages") or 1)
            page += 1
        for r in doc_rows:
            if not isinstance(r, dict):
                continue
            rows.append(
                {
                    "indicator": (r.get("indicator") or {}).get("id"),
                    "indicator_name": (r.get("indicator") or {}).get("value"),
                    "country": (r.get("country") or {}).get("value"),
                    "iso3": r.get("countryiso3code") or None,
                    "year": int(r["date"]) if str(r.get("date", "")).isdigit() else r.get("date"),
                    "value": r.get("value"),
                    "obs_status": r.get("obs_status") or None,
                    "unit": r.get("unit") or None,
                }
            )
    rows.sort(key=lambda r: (r["indicator"] or "", r["iso3"] or r["country"] or "", str(r["year"])))
    other = {k: v["licence"] for k, v in licences.items() if v["licence"] and v["licence"] not in CC_BY}
    unknown = [k for k, v in licences.items() if not v["licence"]]
    note = "One row per country (or aggregate) and year; value is null where the World Bank has no figure."
    if other:
        note += (
            " Not CC BY 4.0 by its metadata: "
            + ", ".join(f"{k} ({v})" for k, v in other.items())
            + "; check those terms before publishing the data."
        )
    if unknown:
        note += f" No licence in the metadata of {', '.join(unknown)}: the World Bank's dataset terms apply."
    db_name = db_name or ("World Development Indicators" if source == WDI else f"World Bank database {source}")
    srcs = sorted(set(data_sources.values()))
    citation = (
        f"The World Bank: {db_name}"
        + (f": {'; '.join(srcs)}" if srcs else "")
        + (
            ". World Bank Open Data, https://data.worldbank.org"
            + (f" (last updated {version})" if version else "")
            + ". Licence: "
            + ("CC BY 4.0." if not other else "see the indicators' metadata.")
        )
    )
    span = f"{start or 'first'}–{end or 'latest'}"
    dates = {str(r["year"]) for r in rows}
    frequency = "quarterly" if any("Q" in d for d in dates) else "monthly" if any("M" in d for d in dates) else "annual"
    return Fetched(
        rows=rows,
        series=f"World Bank {', '.join(indicators)} for {', '.join(countries)}, {span}",
        query=queries[0] if len(queries) == 1 else " ; ".join(queries),
        version=version,
        files=files,
        link=f"https://data.worldbank.org/indicator/{indicators[0]}",
        citation=citation,
        record={"database": source, "indicator_licences": licences, "indicator_sources": data_sources},
        frequency=frequency,
        note=note,
    )


SOURCE = Source(
    name="worldbank",
    label="World Bank Open Data",
    dataset="World Bank Open Data (Indicators API v2), The World Bank",
    website="https://data.worldbank.org",
    terms_url=TERMS_URL,
    terms_summary=(
        'CC BY 4.0 unless an indicator is labelled otherwise; attribute as "The World Bank: Dataset name: Data '
        'source". Some third-party indicators carry other terms, stated in their metadata (each load records them).'
    ),
    terms_plain=(
        "The World Bank's datasets are licensed CC BY 4.0 unless labelled otherwise.",
        "Attribution: The World Bank: Dataset name: Data source (if known).",
        "Some third-party indicators may not be redistributed or carry other terms; their metadata says so, "
        "and each load records every indicator's licence.",
    ),
    licence=(
        f"CC BY 4.0 with the World Bank's additional terms ({TERMS_URL}): \"Unless specifically labeled "
        "otherwise, these Datasets are provided to you under a Creative Commons Attribution 4.0 International "
        'License (CC BY 4.0)". "You agree to provide attribution to The World Bank and its data providers in '
        'the following format: The World Bank: Dataset name: Data source (if known)." "Some datasets and '
        "indicators are provided by third parties, and may not be redistributed or reused without the consent "
        "of the original data provider, or may be subject to terms and conditions that are different from those "
        'described above. Where applicable, these conditions are included in the dataset or indicator metadata."'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Development indicators by country and year from World Bank Open Data (World Development Indicators "
        "by default; about 1,500 series): GDP, population, health, education, poverty, trade, energy, environment, "
        "1960 to the latest year, about 217 economies and regional aggregates. Search with `indicators`, load "
        "with `series`. CC BY 4.0; each load records every indicator's licence from its metadata."
    ),
    coverage="Development indicators by country and year (WDI and other World Bank databases). CC BY 4.0.",
    help="World Bank Open Data (Indicators API v2): indicators by country and year. No key.",
    operations=(
        Operation(
            "indicators",
            "Find indicators by words of their name or code, e.g. --query 'gdp per capita'.",
            args=(
                Arg("query", "Words that must all appear in the indicator's name or code.", required=True),
                Arg("database", "World Bank database id (default 2: World Development Indicators)."),
                Arg("limit", "Most indicators to list (default 50).", type=int),
            ),
            fetch=fetch_indicators,
            loads=False,
            card="List indicators whose name contains words → id, name, unit, data source. Params: query (required), "
            "database (id, default 2 = WDI), limit.",
        ),
        Operation(
            "series",
            "Values of indicators by country and year, e.g. --indicator NY.GDP.PCAP.CD --countries DEU,FRA "
            "--start 2000 --end 2023.",
            args=(
                Arg(
                    "indicator",
                    "Indicator codes, comma-separated (at most 20), e.g. NY.GDP.PCAP.CD,SP.POP.TOTL.",
                    type="list",
                    required=True,
                ),
                Arg(
                    "countries",
                    "ISO3 (or ISO2) country or aggregate codes, comma-separated (default: all).",
                    type="list",
                ),
                Arg("start", "First year (YYYY)."),
                Arg("end", "Last year (YYYY)."),
                Arg("database", "World Bank database id (default 2: World Development Indicators)."),
            ),
            fetch=fetch_series,
            card="Indicators by country and year → one row per indicator, country, year. Params: indicator (list, "
            "required), countries (list of ISO3; default all), start, end (years), database (default 2 = WDI).",
        ),
    ),
    polite=Polite(min_interval=0.5, max_requests=2 * MAX_INDICATORS + 40),
    aliases=("world_bank", "wdi", "world_development_indicators", "world_bank_open_data", "wb"),
    skill="data/worldbank",
    doctor=Doctor(
        "data.worldbank.series",
        operation="series",
        params={"indicator": "NY.GDP.PCAP.CD", "countries": "DEU", "start": 2020, "end": 2020},
    ),
)
