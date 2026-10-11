"""NOAA NCEI Climate Data Online: daily weather-station records (GHCN-Daily), with a free token.

- Service: https://www.ncei.noaa.gov/cdo-web/api/v2/ (Climate Data Online web
  services v2). "An access token is required to use the API, and each token
  will be limited to five requests per second and 10,000 requests per day"
  (https://www.ncdc.noaa.gov/cdo-web/webservices/v2, checked 2026-10-11).
  The token goes in a ``token`` header, never in the URL, so it is not
  recorded. A ``/data`` request returns at most 1,000 results and daily data
  at most one year; e2er pages through the results and splits a longer period
  into years.
- e2er serves the daily summaries (dataset ``GHCND``, Global Historical
  Climatology Network - Daily) and the station list, so the citation is that
  dataset's.
- Terms: the dataset's page
  (https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00861)
  gives the citation as its use constraint and a liability disclaimer; it
  states no licence and no limit on passing the data on; "In most cases,
  electronic downloads of the data are free." A study may pass the data on.
- Citation (the same page): Menne et al. (2012), GHCN-Daily, Version 3,
  doi:10.7289/V5D21VHZ, with the subset used and the access date, and the
  overview article Menne et al. (2012), J. Atmos. Oceanic Technol. 29,
  897–910, doi:10.1175/JTECH-D-11-00103.1.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Key, Operation, Polite, Source

SERVICE = "https://www.ncei.noaa.gov/cdo-web/api/v2"
PAGE = 1000
#: The longest period one load covers (each year is at least one request; the token allows 10,000 a day).
MAX_YEARS = 30

DATASET_CITATION = (
    "Menne, M. J., Durre, I., Korzeniewski, B., McNeill, S., Thomas, K., Yin, X., Anthony, S., Ray, R., Vose, "
    "R. S., Gleason, B. E., and Houston, T. G. (2012): Global Historical Climatology Network - Daily "
    "(GHCN-Daily), Version 3. NOAA National Climatic Data Center. doi:10.7289/V5D21VHZ"
)
ARTICLE = (
    "Menne, M. J., Durre, I., Vose, R. S., Gleason, B. E., and Houston, T. G. (2012): An Overview of the Global "
    "Historical Climatology Network-Daily Database. J. Atmos. Oceanic Technol., 29, 897-910. "
    "doi:10.1175/JTECH-D-11-00103.1"
)
CITATION = DATASET_CITATION + " [subset used; access date]. And: " + ARTICLE
CITE_KEY = "GHCND_Menne2012"
#: From the DOIs' metadata (DataCite, Crossref), with e2er's keys.
BIBTEX = """@misc{GHCND_Menne2012,
  author    = {Menne, Matthew J. and Durre, Imke and Korzeniewski, Bryant and McNeill, Shelley and
               Thomas, Kristy and Yin, Xungang and Anthony, Steven and Ray, Ron and Vose, Russell S. and
               Gleason, Byron E. and Houston, Tamara G.},
  title     = {Global Historical Climatology Network - Daily ({GHCN-Daily}), Version 3},
  publisher = {NOAA National Centers for Environmental Information},
  year      = {2012},
  doi       = {10.7289/V5D21VHZ}
}

@article{Menne2012_GHCND_overview,
  author    = {Menne, Matthew J. and Durre, Imke and Vose, Russell S. and Gleason, Byron E. and Houston, Tamara G.},
  title     = {An Overview of the Global Historical Climatology Network-Daily Database},
  journal   = {Journal of Atmospheric and Oceanic Technology},
  volume    = {29},
  number    = {7},
  pages     = {897--910},
  year      = {2012},
  publisher = {American Meteorological Society},
  doi       = {10.1175/JTECH-D-11-00103.1}
}"""


def _day(value: Any, what: str) -> date:
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise FetchError(f"--{what} {value!r} is not a day (YYYY-MM-DD)") from None


def _station(s: str) -> str:
    s = s.strip()
    return s if ":" in s else f"GHCND:{s}"


def _headers(ctx: Context) -> dict[str, str]:
    if not ctx.key:
        raise FetchError("NOAA_TOKEN not configured. " + (SOURCE.key.how_to_get if SOURCE.key else ""))
    return {"token": ctx.key}


async def _pages(
    ctx: Context, url: str, q: dict[str, Any], files: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """All results of a CDO list, page after page (offset is 1-based); ``files`` gets each page's URL and SHA-256."""
    import json

    from .adapters import sha256_bytes

    out: list[dict[str, Any]] = []
    offset = 1
    while True:
        resp = await ctx.http.get(url, {**q, "limit": PAGE, "offset": offset}, headers=_headers(ctx))
        try:
            doc = json.loads(resp.content) if resp.content.strip() else {}
        except ValueError:
            doc = None
        if not isinstance(doc, dict):
            raise FetchError(f"{ctx.http.requests[-1]}: the answer is not a CDO result list")
        if files is not None:
            files.append({"url": ctx.http.requests[-1], "sha256": sha256_bytes(resp.content)})
        rows = doc.get("results") or []
        out += [r for r in rows if isinstance(r, dict)]
        count = ((doc.get("metadata") or {}).get("resultset") or {}).get("count")
        if not rows or (isinstance(count, int) and len(out) >= count) or len(rows) < PAGE:
            return out
        offset += len(rows)


async def fetch_daily(ctx: Context, params: dict[str, Any]) -> Fetched:
    stations = [_station(s) for s in params.get("stations") or []]
    if not stations:
        raise FetchError("--stations is empty; e.g. USW00094728 (find stations with `noaa stations`)")
    start, end = _day(params["start"], "start"), _day(params["end"], "end")
    if start > end:
        raise FetchError(f"--start {start} is after --end {end}")
    if (end - start).days > 366 * MAX_YEARS:
        raise FetchError(f"the period is longer than {MAX_YEARS} years; split it into several loads")
    q: dict[str, Any] = {"datasetid": "GHCND", "units": "metric", "stationid": stations}
    if params.get("datatypes"):
        q["datatypeid"] = [d.strip().upper() for d in params["datatypes"]]
    rows: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    first = len(ctx.http.requests)
    a = start
    while a <= end:  # the service takes at most one year of daily data per request
        b = min(end, date(a.year, 12, 31))
        rows += await _pages(ctx, f"{SERVICE}/data", {**q, "startdate": a.isoformat(), "enddate": b.isoformat()}, files)
        a = b + timedelta(days=1)
    if not rows:
        raise FetchError("NOAA returned no observations for these stations, types and period")
    out = [
        {
            "date": str(r.get("date", ""))[:10],
            "station": r.get("station"),
            "datatype": r.get("datatype"),
            "value": r.get("value"),
            "attributes": r.get("attributes"),
        }
        for r in rows
    ]
    out.sort(key=lambda r: (r["station"] or "", r["date"], r["datatype"] or ""))
    when = datetime.now(UTC).strftime("%Y-%m-%d")
    types = ", ".join(q.get("datatypeid") or ["all types"])
    subset = f"stations {', '.join(stations)}, {types}, {start}–{end}"
    return Fetched(
        rows=out,
        series=f"GHCN-Daily {subset}",
        query=ctx.http.requests[first],
        files=files,
        link="https://www.ncei.noaa.gov/cdo-web/",
        citation=f"{DATASET_CITATION} [{subset}; accessed {when}]. And: {ARTICLE}",
        record={"units": "metric (CDO scaling: °C, mm, km/h)", "requests": len(ctx.http.requests) - first},
        frequency="daily",
        note=(
            "Long format: one row per station, day and data type (TMAX, TMIN, PRCP, SNOW, …); values in metric "
            "units (temperatures °C, precipitation mm). attributes are GHCN-Daily flags (measurement, quality, "
            "source): a quality flag marks a value that failed a check."
        ),
    )


async def fetch_stations(ctx: Context, params: dict[str, Any]) -> Fetched:
    q: dict[str, Any] = {"datasetid": "GHCND"}
    if params.get("bbox"):
        parts = str(params["bbox"]).split(",")
        try:
            west, south, east, north = (float(x) for x in parts)
        except ValueError:
            raise FetchError("--bbox: give west,south,east,north in degrees, e.g. -74.3,40.5,-73.7,40.9") from None
        q["extent"] = f"{south},{west},{north},{east}"
    if params.get("location"):
        q["locationid"] = params["location"]
    if params.get("datatypes"):
        q["datatypeid"] = [d.strip().upper() for d in params["datatypes"]]
    if "extent" not in q and "locationid" not in q:
        raise FetchError("give --bbox or --location (e.g. FIPS:36 for New York State) to list stations")
    rows = await _pages(ctx, f"{SERVICE}/stations", q)
    keep = ("id", "name", "latitude", "longitude", "elevation", "mindate", "maxdate", "datacoverage")
    return Fetched(
        rows=[{k: r.get(k) for k in keep} for r in rows],
        series="GHCN-Daily stations",
        query=ctx.http.requests[-1],
    )


SOURCE = Source(
    name="noaa",
    label="NOAA Climate Data Online",
    dataset="Global Historical Climatology Network - Daily (GHCN-Daily), NOAA NCEI Climate Data Online",
    website="https://www.ncei.noaa.gov/cdo-web/",
    terms_url="https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00861",
    terms_summary=(
        "Free with a free token; NOAA states no licence and asks for the GHCN-Daily citation with the subset "
        "used and the access date, and the overview article."
    ),
    terms_plain=(
        "Free; the API needs a free token (five requests a second, 10,000 a day).",
        "NOAA states no licence and no limit on passing the data on.",
        "Cite GHCN-Daily (doi:10.7289/V5D21VHZ) with the subset used and the access date, and Menne et al. (2012).",
    ),
    licence=(
        "No licence stated. The dataset page "
        "(https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00861) gives as use "
        f'constraint: "Cite as: {DATASET_CITATION.split(" doi:")[0]} [indicate subset used]. ... [access date]. '
        'Publications citing this dataset should also cite the following article: ..." and "In most cases, '
        'electronic downloads of the data are free." The web service '
        '(https://www.ncdc.noaa.gov/cdo-web/webservices/v2): "An access token is required to use the API".'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Daily weather-station records worldwide (NOAA GHCN-Daily, via Climate Data Online): maximum and minimum "
        "temperature, precipitation, snowfall, snow depth per station and day, from the 1800s for some "
        "stations. Good for station-level climate trends and extremes, and weather controls tied to a place. "
        "Needs a free NOAA token (NOAA_TOKEN)."
    ),
    coverage="Daily weather-station records worldwide (GHCN-Daily): temperature, precipitation, snow.",
    help="NOAA Climate Data Online: daily weather-station records (GHCN-Daily). Free token: NOAA_TOKEN.",
    key=Key(
        setting="noaa_token",
        env="NOAA_TOKEN",
        how_to_get=(
            "Get a free token by email at https://www.ncdc.noaa.gov/cdo-web/token and set NOAA_TOKEN "
            "(five requests a second, 10,000 a day)."
        ),
    ),
    operations=(
        Operation(
            "stations",
            "List GHCN-Daily stations in a region, e.g. --bbox -74.3,40.5,-73.7,40.9 --datatypes TMAX.",
            args=(
                Arg("bbox", "Region: west,south,east,north in degrees."),
                Arg("location", "A CDO location id instead, e.g. FIPS:36 (New York State) or CITY:US360019."),
                Arg("datatypes", "Only stations with these data types, e.g. TMAX,PRCP.", type="list"),
            ),
            fetch=fetch_stations,
            loads=False,
            card="GHCN-Daily stations → id, name, position, first/last date. Params: bbox or location, datatypes.",
        ),
        Operation(
            "daily",
            "Daily observations of stations, e.g. --stations USW00094728 --datatypes TMAX,TMIN,PRCP "
            "--start 2020-01-01 --end 2024-12-31.",
            args=(
                Arg(
                    "stations", "Comma-separated GHCN-Daily station ids, e.g. USW00094728.", type="list", required=True
                ),
                Arg("datatypes", "Comma-separated data types, e.g. TMAX,TMIN,PRCP (default: all).", type="list"),
                Arg("start", "First day (YYYY-MM-DD).", required=True),
                Arg("end", "Last day (YYYY-MM-DD, included).", required=True),
            ),
            fetch=fetch_daily,
            card=(
                "Daily station observations → one row per station, day and data type (metric units). Params: "
                "stations (list, required), datatypes (list), start, end (YYYY-MM-DD, required)."
            ),
        ),
    ),
    # Five requests a second per token; e2er stays well below.
    polite=Polite(min_interval=0.25, retries=3, timeout=120.0, max_requests=400),
    aliases=("noaa_cdo", "ghcnd", "ghcn_daily", "noaa_ncei", "climate_data_online"),
    skill="data/noaa",
    doctor=Doctor(
        "data.noaa.daily",
        operation="daily",
        params={"stations": "USW00094728", "datatypes": "TMAX", "start": "2024-01-01", "end": "2024-01-02"},
    ),
)
