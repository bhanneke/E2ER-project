"""Our World in Data: the data behind an OWID chart, with each indicator's sources and their licences.

- Service (keyless): the chart data API. ``/grapher/<slug>.csv`` returns a
  chart's data (``csvType=full``: every entity and year;
  ``useColumnShortNames=true``: column names a program can use),
  ``/grapher/<slug>.metadata.json`` the chart's and each column's metadata
  (title, unit, ``citationShort``/``citationLong``, ``fullMetadata``), and the
  indicator API (``api.ourworldindata.org/v1/indicators/<id>.metadata.json``)
  the indicator's origins: who produced the data and under which licence, and
  ``nonRedistributable``.
- Search: ``/api/search?q=…&type=charts`` (keyless; documented at
  https://docs.owid.io/projects/etl/api/search-api/).
- Terms (FAQ, https://ourworldindata.org/faqs, checked 2026-10-11): "Data
  produced by us falls under our permissive CC BY license"; "Most of the data
  on Our World in Data comes from third-party providers (such as the WHO, UN,
  and World Bank) and is subject to the license terms of those providers."
  Every load therefore records each origin's licence from the indicator API,
  says which are not open licences, and refuses a chart whose indicators OWID
  marks as not redistributable.
- Citation: "you must credit both Our World in Data and the underlying
  third-party data provider"; each indicator's ``citationLong`` does both
  ("… – processed by Our World in Data" / "with major processing by Our World
  in Data"), and the load's citation joins them.
- Version: each indicator's ``lastUpdated`` date.
"""

from __future__ import annotations

import io
import re
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

SITE = "https://ourworldindata.org"
GRAPHER = f"{SITE}/grapher"
#: The most indicator metadata documents one load reads (one request each).
MAX_COLUMNS = 25
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

TERMS_URL = "https://ourworldindata.org/faqs"
_OPEN = re.compile(r"^(CC[ -]?BY|CC0|public domain|ODbL|ODC|Open Government|OGL|PDDL|Etalab|dl-de)", re.I)


def _slug(value: str) -> str:
    v = str(value).strip()
    m = re.match(r"^(?:https?://ourworldindata\.org)?/?(?:grapher/)?([a-z0-9-]+)(?:[?#.].*)?$", v)
    slug = m.group(1) if m else v
    if not _SLUG.match(slug):
        raise FetchError(f"--chart {value!r}: give the chart's slug, e.g. life-expectancy (from its URL)")
    return slug


def _licence_name(lic: Any) -> tuple[str | None, str | None]:
    if isinstance(lic, dict):
        return lic.get("name"), lic.get("url")
    if isinstance(lic, str):
        return lic, None
    return None, None


async def fetch_chart(ctx: Context, params: dict[str, Any]) -> Fetched:
    import pandas as pd

    from .adapters import sha256_bytes

    slug = _slug(params["chart"])
    q = {"v": 1, "csvType": "full", "useColumnShortNames": "true"}
    meta = await ctx.http.get_json(f"{GRAPHER}/{slug}.metadata.json", q)
    columns: dict[str, Any] = meta.get("columns") or {}
    if not columns:
        raise FetchError(f"{ctx.http.requests[-1]}: the chart has no data columns")
    wanted = params.get("columns")
    if wanted:
        unknown = [c for c in wanted if c not in columns]
        if unknown:
            raise FetchError(f"--columns {', '.join(unknown)}: the chart has {', '.join(columns)}")
        columns = {k: v for k, v in columns.items() if k in wanted}
    if len(columns) > MAX_COLUMNS:
        raise FetchError(f"the chart has {len(columns)} columns; pick at most {MAX_COLUMNS} with --columns")

    indicators: dict[str, Any] = {}
    blocked = []
    for name, col in columns.items():
        info: dict[str, Any] = {
            "title": col.get("titleShort") or col.get("titleLong"),
            "unit": col.get("unit") or None,
            "last_updated": col.get("lastUpdated"),
            "citation": col.get("citationLong") or col.get("citationShort"),
            "owid_variable_id": col.get("owidVariableId"),
        }
        full_url = col.get("fullMetadata")
        if full_url:
            full = await ctx.http.get_json(full_url)
            if full.get("nonRedistributable"):
                blocked.append(name)
            origins = []
            seen = set()
            for o in full.get("origins") or []:
                lic, lic_url = _licence_name(o.get("license"))
                key = (o.get("producer"), o.get("title"), lic)
                if key in seen:
                    continue
                seen.add(key)
                origins.append(
                    {
                        "producer": o.get("producer"),
                        "title": o.get("title"),
                        "licence": lic,
                        "licence_url": lic_url,
                        "citation": o.get("citationFull"),
                    }
                )
            info["origins"] = origins
            info["non_redistributable"] = bool(full.get("nonRedistributable"))
            info["dataset_version"] = full.get("datasetVersion")
        indicators[name] = info
    if blocked:
        raise FetchError(
            f"OWID marks {', '.join(blocked)} of chart {slug} as not redistributable (the data's producer does not "
            "allow it); e2er does not load it. Get the data from its producer under their terms."
        )

    content = await ctx.http.get_bytes(f"{GRAPHER}/{slug}.csv", q)
    csv_url = ctx.http.requests[-1]
    try:
        df = pd.read_csv(io.BytesIO(content))
    except ValueError as e:
        raise FetchError(f"{csv_url}: the answer is not CSV ({e})") from None
    keep = [c for c in df.columns if c in ("entity", "code", "year", "day") or c in columns]
    df = df[keep]
    if params.get("entities"):
        want = {e.lower() for e in params["entities"]}
        keep_rows = df["entity"].str.lower().isin(want)
        if "code" in df.columns:
            keep_rows |= df["code"].fillna("").astype(str).str.lower().isin(want)
        df = df[keep_rows]
        if df.empty:
            raise FetchError(f"--entities {', '.join(params['entities'])}: none is in chart {slug}")
    if params.get("start") is not None and "year" in df.columns:
        df = df[df["year"] >= int(params["start"])]
    if params.get("end") is not None and "year" in df.columns:
        df = df[df["year"] <= int(params["end"])]
    df = df.reset_index(drop=True)

    licences = sorted({o["licence"] for i in indicators.values() for o in i.get("origins", []) if o.get("licence")})
    not_open = sorted(
        {
            f"{o.get('producer')}: {o['licence']}"
            for i in indicators.values()
            for o in i.get("origins", [])
            if o.get("licence") and not _OPEN.match(o["licence"])
        }
    )
    citations = [i["citation"] for i in indicators.values() if i.get("citation")]
    chart = meta.get("chart") or {}
    updated = sorted({i["last_updated"] for i in indicators.values() if i.get("last_updated")})
    note = (
        "One row per entity (country or region) and year (or day), one column per indicator. "
        f"The data's producers license them as: {', '.join(licences) or 'not stated'}; each origin's licence is "
        "recorded. Cite the producers as well as OWID (citation in the load record)."
    )
    if not_open:
        note += (
            " Not an open licence: " + "; ".join(not_open) + ". Check those terms before the study passes the data on."
        )
    return Fetched(
        rows=df,
        series=f"OWID chart {slug}: {chart.get('title') or slug}"
        + (f" ({', '.join(params['entities'])})" if params.get("entities") else ""),
        query=csv_url,
        version=updated[-1] if updated else None,
        files=[{"url": csv_url, "sha256": sha256_bytes(content)}],
        link=f"{GRAPHER}/{slug}",
        citation=(" ".join(citations) + f" Retrieved {_today()} from {GRAPHER}/{slug}") if citations else None,
        record={
            "chart": slug,
            "chart_title": chart.get("title"),
            "indicators": indicators,
            "origin_licences": licences,
            "origins_not_open": not_open,
        },
        frequency="daily" if "day" in df.columns else "annual",
        note=note,
    )


def _today() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


async def fetch_search(ctx: Context, params: dict[str, Any]) -> Fetched:
    query = str(params["query"]).strip()
    if not query:
        raise FetchError("--query is empty; give words, e.g. 'life expectancy'")
    limit = int(params.get("limit") or 20)
    if not 1 <= limit <= 100:
        raise FetchError(f"--limit {limit}: between 1 and 100")
    doc = await ctx.http.get_json(f"{SITE}/api/search", {"q": query, "type": "charts", "hitsPerPage": limit})
    rows = [
        {
            "slug": r.get("slug"),
            "title": r.get("title"),
            "variant": r.get("variantName") or None,
            "subtitle": r.get("subtitle") or None,
            "entities": len(r.get("availableEntities") or []),
            "updated": r.get("updatedAt"),
            "url": r.get("url"),
        }
        for r in (doc.get("results") or [])
        if isinstance(r, dict) and r.get("slug")
    ]
    return Fetched(
        rows=rows,
        series=f"OWID charts matching {query!r}",
        query=ctx.http.requests[-1],
        note=f"{doc.get('nbHits', len(rows))} charts match; showing {len(rows)}. Load one with: chart --chart <slug>.",
    )


CITATION = (
    "Our World in Data. https://ourworldindata.org (cite the data's producers too: "
    "'… – processed by Our World in Data')."
)
CITE_KEY = "OWID"
BIBTEX = """@misc{OWID,
  author       = {{Our World in Data}},
  title        = {Our World in Data},
  howpublished = {Chart data API, \\url{https://ourworldindata.org/grapher/}},
  url          = {https://ourworldindata.org},
  note         = {Cite the underlying data producers as well (each load records them)}
}"""

SOURCE = Source(
    name="owid",
    label="Our World in Data",
    dataset="Our World in Data, Global Change Data Lab",
    website=SITE,
    terms_url=TERMS_URL,
    terms_summary=(
        "OWID's own data are CC BY; most data on OWID come from third parties and carry their licences, which each "
        "load records per origin. Credit both OWID and the data's producers."
    ),
    terms_plain=(
        "Data produced by Our World in Data are licensed CC BY: use and pass them on, citing OWID.",
        "Most data come from third parties (WHO, UN, World Bank …) and are subject to their licences; each load "
        "records every origin's licence and names those that are not open.",
        "Charts OWID marks as not redistributable are not loaded.",
        "Cite both Our World in Data and the underlying data producers.",
    ),
    licence=(
        f'Our World in Data FAQ ({TERMS_URL}): "Some of the data on our site is produced by us — you can tell '
        "because it will say “Official data collated by Our World in Data”, “with major processing by Our World in "
        "Data”, or similar. Data produced by us falls under our permissive CC BY license; you have permission to "
        'use, reproduce, and distribute it, provided that you cite us." "Most of the data on Our World in Data '
        "comes from third-party providers (such as the WHO, UN, and World Bank) and is subject to the license terms "
        'of those providers. You should always check their license before reusing or republishing the data." '
        '"When reusing the data we have on our site (e.g., to do an analysis, make your own chart, or build on it '
        'in another way), you must credit both Our World in Data and the underlying third-party data provider."'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "The data behind any Our World in Data chart (about 5,000): health, demography, economy, energy, "
        "environment, education, poverty, by country and year, with each indicator's sources and their licences. "
        "Load a chart by its slug (the end of its URL, e.g. life-expectancy)."
    ),
    coverage="The data behind any Our World in Data chart, with each indicator's sources and licences.",
    help="Our World in Data: the data behind a chart, by country and year. No key.",
    operations=(
        Operation(
            "search",
            "Find charts by words, e.g. --query 'life expectancy'.",
            args=(
                Arg("query", "Words to search chart titles and descriptions for.", required=True),
                Arg("limit", "Most charts to list (default 20, at most 100).", type=int),
            ),
            fetch=fetch_search,
            loads=False,
            card="Find OWID charts by words → slug, title, updated. Params: query (required), limit.",
        ),
        Operation(
            "chart",
            "The data of one chart, e.g. --chart life-expectancy --entities DEU,FRA --start 1950.",
            args=(
                Arg("chart", "The chart's slug (from its URL), e.g. life-expectancy.", required=True),
                Arg(
                    "entities",
                    "Countries or regions (names or ISO3 codes), comma-separated (default: all).",
                    type="list",
                ),
                Arg("columns", "Only these indicator columns (short names, as `chart` lists them).", type="list"),
                Arg("start", "First year.", type=int),
                Arg("end", "Last year.", type=int),
            ),
            fetch=fetch_chart,
            card="The data of one OWID chart → one row per entity and year. Params: chart (slug, required), "
            "entities (list), columns (list), start, end (years).",
        ),
    ),
    polite=Polite(min_interval=1.0, max_requests=MAX_COLUMNS + 5),
    aliases=("our_world_in_data", "ourworldindata", "owid_grapher"),
    skill="data/owid",
    doctor=Doctor(
        "data.owid.chart",
        operation="chart",
        params={"chart": "nuclear-warhead-inventories", "columns": "retired"},
    ),
)
