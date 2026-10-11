"""WHO Global Health Observatory (GHO): health statistics by country, year and sex, through the GHO OData API.

- Service (keyless): https://ghoapi.azureedge.net/api/. ``Indicator`` lists
  every indicator (code and name; ``indicators`` reads the list and filters it
  here); ``<IndicatorCode>?$filter=…`` returns its values, one record per
  country (or region), period and breakdown (``Dim1``–``Dim3``: sex, age
  group, residence …), with the numeric value and its uncertainty interval.
- Terms ("Terms and conditions of use for WHO data compilations,
  aggregations, evaluations and analyses", ``TERMS_URL``, checked 2026-10-11),
  which cover "the data that it collects and publishes on its web site
  www.who.int": use, reproduction and distribution "for public health
  purposes"; "Any other alteration or modification of the Datasets
  (including abbreviations, additions, or deletions) may be made only with
  the prior written authorization of WHO"; no sale or transfer outside that
  use. These are not an open licence (the CC BY 4.0 terms of data.who.int
  cover that portal's datasets, not the GHO API), so e2er treats GHO data as
  data a published study may not pass on: publishing asks the researcher to
  confirm the terms, and the replication package loads them again
  (get_data.py) instead of shipping them.
- Citation, in the format the terms ask for: "WHO, title of dataset, year,
  date of access, acknowledgement of the country or countries having provided
  the underlying data."
- The API is live (values updated 2026-10-01); WHO's GHO page announces a new
  data portal but no end date for the API.
- Version: the latest ``Date`` (when WHO last changed a value) among the
  records read.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Restricted, Source

API = "https://ghoapi.azureedge.net/api"
TERMS_URL = "https://www.who.int/about/policies/publishing/data-policy/terms-and-conditions"
_CODE = re.compile(r"^[A-Za-z0-9_.]+$")
_ISO3 = re.compile(r"^[A-Za-z]{3}$")
SEXES = {"female": "SEX_FMLE", "male": "SEX_MLE", "both": "SEX_BTSX"}


def _next(doc: Any) -> str | None:
    return doc.get("@odata.nextLink") if isinstance(doc, dict) else None


async def fetch_indicators(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import rest_json_pages

    words = str(params["query"]).lower().split()
    if not words:
        raise FetchError("--query is empty; give words of the indicator's name, e.g. 'life expectancy'")
    records, urls = await rest_json_pages(ctx.http, f"{API}/Indicator", items="value", paging="next", next_link=_next)
    hits = [
        {"code": r.get("IndicatorCode"), "name": r.get("IndicatorName")}
        for r in records
        if all(w in f"{r.get('IndicatorCode', '')} {r.get('IndicatorName', '')}".lower() for w in words)
    ]
    limit = int(params.get("limit") or 50)
    return Fetched(
        rows=hits[:limit],
        series=f"WHO GHO indicators matching {' '.join(words)!r}",
        query=urls[0],
        note=f"{len(hits)} indicators match; showing {min(len(hits), limit)}. Load one with: data --indicator <code>.",
    )


def _year(value: Any, what: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        raise FetchError(f"--{what} {value!r} is not a year (YYYY)") from None


async def fetch_data(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import rest_json_pages, sha256_bytes

    code = str(params["indicator"]).strip()
    if not _CODE.match(code):
        raise FetchError(f"--indicator {code!r} is not a GHO indicator code (e.g. WHOSIS_000001)")
    countries = [c.strip().upper() for c in params.get("countries") or []]
    bad = [c for c in countries if not _ISO3.match(c)]
    if bad:
        raise FetchError(f"--countries {', '.join(bad)}: give ISO3 codes, e.g. DEU,FRA")
    start, end = _year(params.get("start"), "start"), _year(params.get("end"), "end")
    if start and end and start > end:
        raise FetchError(f"--start {start} is after --end {end}")
    sex = params.get("sex")
    if sex and sex not in SEXES:
        raise FetchError(f"--sex {sex!r}: one of {', '.join(SEXES)}")
    clauses = []
    if countries:
        clauses.append("(" + " or ".join(f"SpatialDim eq '{c}'" for c in countries) + ")")
    if start:
        clauses.append(f"TimeDim ge {start}")
    if end:
        clauses.append(f"TimeDim le {end}")
    q = {"$filter": " and ".join(clauses)} if clauses else {}
    records, urls = await rest_json_pages(ctx.http, f"{API}/{code}", q, items="value", paging="next", next_link=_next)
    rows = []
    for r in records:
        dims = {r.get(f"Dim{i}Type"): r.get(f"Dim{i}") for i in (1, 2, 3) if r.get(f"Dim{i}Type")}
        if sex and dims.get("SEX") != SEXES[sex]:
            continue
        rows.append(
            {
                "indicator": r.get("IndicatorCode"),
                "spatial_type": r.get("SpatialDimType"),
                "location": r.get("SpatialDim"),
                "parent_location": r.get("ParentLocation"),
                "time_type": r.get("TimeDimType"),
                "year": r.get("TimeDim"),
                "period": r.get("TimeDimensionValue"),
                "dim1_type": r.get("Dim1Type"),
                "dim1": r.get("Dim1"),
                "dim2_type": r.get("Dim2Type"),
                "dim2": r.get("Dim2"),
                "dim3_type": r.get("Dim3Type"),
                "dim3": r.get("Dim3"),
                "value": r.get("NumericValue"),
                "low": r.get("Low"),
                "high": r.get("High"),
                "value_text": r.get("Value"),
                "comments": r.get("Comments"),
                "updated": r.get("Date"),
            }
        )
    rows.sort(key=lambda x: (str(x["location"]), str(x["period"]), str(x["dim1"]), str(x["dim2"]), str(x["dim3"])))
    name = code
    try:
        listing = await ctx.http.get_json(f"{API}/Indicator", {"$filter": f"IndicatorCode eq '{code}'"})
        name = (listing.get("value") or [{}])[0].get("IndicatorName") or code
    except FetchError:
        pass
    version = max((str(r["updated"]) for r in rows if r.get("updated")), default=None)

    content = json.dumps(records, sort_keys=True, ensure_ascii=False).encode("utf-8")
    where = ", ".join(countries) if countries else "all locations"
    span = f"{start or 'first'}–{end or 'latest'}"
    return Fetched(
        rows=rows,
        series=f"WHO GHO {code}: {name} ({where}, {span}{', ' + sex if sex else ''})",
        query=urls[0],
        version=version[:10] if version else None,
        # The API pages JSON; the hash is of the records read, serialized with sorted keys.
        files=[{"url": urls[0], "sha256": sha256_bytes(content), "pages": len(urls)}],
        link=f"https://www.who.int/data/gho/data/indicators/indicator-details/GHO/{code}",
        citation=_citation(name, code, countries),
        record={"indicator_code": code, "indicator_name": name},
        frequency="annual" if all(r.get("time_type") in (None, "YEAR") for r in rows) else None,
        note=(
            "One row per location, period and breakdown (dim1–dim3: e.g. SEX, AGEGROUP, RESIDENCEAREATYPE); "
            "value is numeric, low/high the uncertainty interval where WHO gives one. Totals and breakdowns are "
            "in the same table: filter on the dim columns before summing."
        ),
    )


def _citation(name: str, code: str, countries: list[str]) -> str:
    """WHO's format: WHO, title of dataset, year, date of access, the countries that provided the data."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    who = ", ".join(countries) if countries else "all WHO Member States reporting it"
    return (
        f"WHO, Global Health Observatory: {name} ({code}), {now.year}, accessed {now.strftime('%Y-%m-%d')}. "
        f"Underlying data provided by the countries concerned ({who})."
    )


CITATION = (
    "WHO, Global Health Observatory data repository, [year], [date of access], acknowledgement of the "
    "country or countries having provided the underlying data."
)
CITE_KEY = "WHO_GHO"
BIBTEX = """@misc{WHO_GHO,
  author       = {{World Health Organization}},
  title        = {Global Health Observatory data repository},
  howpublished = {GHO OData API, \\url{https://ghoapi.azureedge.net/api/}},
  url          = {https://www.who.int/data/gho}
}"""

SOURCE = Source(
    name="who_gho",
    label="WHO Global Health Observatory",
    dataset="Global Health Observatory (GHO) data repository, World Health Organization",
    website="https://www.who.int/data/gho",
    terms_url=TERMS_URL,
    terms_summary=(
        "WHO grants use, reproduction and distribution for public health purposes; other changes to the data "
        "need WHO's written authorization, and the data may not be sold. Not an open licence: a published study "
        "reloads the data instead of shipping them."
    ),
    terms_plain=(
        "WHO allows use, reproduction and distribution of its datasets for public health purposes.",
        "Changes beyond matching a publication's style need WHO's prior written authorization.",
        "The data may not be sold, transferred outside that use, or used to promote a commercial enterprise.",
        "Attribution: WHO, title of dataset, year, date of access, and the countries that provided the data.",
    ),
    licence=(
        f"WHO, Terms and conditions of use for WHO data compilations, aggregations, evaluations and analyses "
        f'({TERMS_URL}): "Licensed Use. Subject to these Terms and Conditions, WHO grants to you the '
        "royalty-free, worldwide, non-exclusive right to use, reproduce, extract, download, copy, distribute, "
        "display or include the Datasets and data contained therein in other products for public health "
        'purposes." "Any other alteration or modification of the Datasets (including abbreviations, additions, '
        'or deletions) may be made only with the prior written authorization of WHO." "You will not sell or '
        "otherwise transfer the Datasets and/or data contained therein to any third party, except within the "
        'Licensed Use." Attribution "in the following format: WHO, title of dataset, year, date of access, '
        'acknowledgement of the country or countries having provided the underlying data."'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Health statistics of WHO's 194 member states by year (and sex, age group, residence where WHO breaks "
        "them down): life expectancy, mortality by cause, immunization, infectious diseases (HIV, TB, malaria), "
        "risk factors (tobacco, alcohol, obesity), health workforce and spending, about 2,000 indicators. "
        "Find an indicator with `indicators`, load it with `data`."
    ),
    coverage="WHO health statistics by country, year, sex and age (about 2,000 indicators).",
    help="WHO Global Health Observatory: health statistics by country and year. No key.",
    operations=(
        Operation(
            "indicators",
            "Find indicators by words of their name or code, e.g. --query 'life expectancy'.",
            args=(
                Arg("query", "Words that must all appear in the indicator's name or code.", required=True),
                Arg("limit", "Most indicators to list (default 50).", type=int),
            ),
            fetch=fetch_indicators,
            loads=False,
            card="List GHO indicators whose name contains words → code, name. Params: query (required), limit.",
        ),
        Operation(
            "data",
            "Values of one indicator, e.g. --indicator WHOSIS_000001 --countries DEU,FRA --start 2000 --sex both.",
            args=(
                Arg("indicator", "GHO indicator code, e.g. WHOSIS_000001.", required=True),
                Arg(
                    "countries", "ISO3 codes, comma-separated (default: every location, regions included).", type="list"
                ),
                Arg("start", "First year."),
                Arg("end", "Last year."),
                Arg("sex", "Only one sex: female, male or both (the total).", choices=tuple(SEXES)),
            ),
            fetch=fetch_data,
            card="Values of a GHO indicator → one row per location, period and breakdown. Params: indicator "
            "(required), countries (list of ISO3), start, end (years), sex (female/male/both).",
        ),
    ),
    redistribution=False,
    restricted=Restricted(
        short="WHO GHO",
        name="WHO Global Health Observatory",
        zenodo_licence=None,
        no_zenodo_why=(
            "WHO's terms allow use for public health purposes only and no modification without WHO's written "
            "authorization, and a Zenodo deposit republishes the data for anyone to reuse"
        ),
        limit="allow use for public health purposes only and no changes without WHO's written authorization",
        limit_finish="allow use for public health purposes only and no changes without WHO's written authorization",
        confirm="under WHO's terms (public health purposes, no changes without WHO's authorization)",
        warn="WHO's terms allow use for public health purposes only; the data may not be sold.",
    ),
    polite=Polite(min_interval=1.0, max_requests=60),
    aliases=("who", "gho", "global_health_observatory", "who_global_health_observatory"),
    skill="data/who_gho",
    doctor=Doctor(
        "data.who_gho.data",
        operation="data",
        params={"indicator": "WHOSIS_000001", "countries": "DEU", "start": 2019, "end": 2019},
    ),
)
