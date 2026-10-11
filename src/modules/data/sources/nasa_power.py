"""NASA POWER: daily, monthly and annual weather and solar parameters for any place on Earth.

- Service: https://power.larc.nasa.gov/api/temporal/ (keyless, JSON). The
  ``point`` endpoint returns up to 20 parameters for one latitude/longitude;
  the ``regional`` endpoint one parameter on its grid inside a box of 2
  to 10 degrees a side (docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/,
  checked 2026-10-11). The service answers HTTP 429 when asked too often and
  warns that an application repeatedly requesting the same location may be
  blocked; e2er spaces requests by two seconds and asks for each place once.
  Daily data run from 1981-01-01 to near real time; monthly and annual from
  1981 to the previous year.
- Terms: POWER's referencing guide (https://power.larc.nasa.gov/docs/referencing/)
  asks every publication to include POWER's reference and data reference
  ("service name, version number, and date accessed") and requests notice
  when data are passed to other researchers. It states no licence; NASA's
  Earth science data use guidance
  (https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance)
  says data from NASA-led missions without a marked restriction "are licensed
  as Creative Commons Zero (CC0)" and "there are no restrictions on the use of
  these data". POWER's values come from NASA's MERRA-2 reanalysis and CERES
  satellite radiation products (each response names them). A study may pass the data on.
- Each load records the API name and version (from the response), the
  community, the time standard, the units of every parameter, the request
  URL, the SHA-256 of the JSON read and when it ran; its citation names the
  version and the access date as POWER asks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

SERVICE = "https://power.larc.nasa.gov/api/temporal"
TEMPORAL = ("daily", "monthly", "annual")
COMMUNITIES = ("RE", "AG", "SB")
MAX_POINT_PARAMETERS = 20

REFERENCE = (
    "The data was obtained from National Aeronautics and Space Administration (NASA) Langley Research Center's "
    "Prediction Of Worldwide Energy Resources (POWER) project funded through the NASA Earth Science Division."
)
CITE_KEY = "NASA_POWER"
CITATION = (
    "NASA Langley Research Center (LaRC) POWER Project. Prediction Of Worldwide Energy Resources (POWER), "
    "https://power.larc.nasa.gov/. " + REFERENCE + " Data reference: the POWER API name, version and access date "
    "of the load (recorded with each load)."
)
#: POWER publishes reference sentences, no BibTeX and no DOI: e2er's entry built from them.
BIBTEX = """@misc{NASA_POWER,
  author       = {{NASA Langley Research Center (LaRC) POWER Project}},
  title        = {Prediction Of Worldwide Energy Resources ({POWER})},
  howpublished = {\\url{https://power.larc.nasa.gov/}},
  note         = {Funded through the NASA Earth Science Division. Cite the API version and access date
                  of each load (data\\_sources.json).}
}"""


def _day(value: str, what: str) -> str:
    text = str(value).strip().replace("-", "")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        raise FetchError(f"--{what} {value!r} is not a day (YYYY-MM-DD)") from None
    return text


def _year(value: str, what: str) -> str:
    text = str(value).strip()[:4]
    if not (text.isdigit() and 1981 <= int(text) <= 2100):
        raise FetchError(f"--{what} {value!r}: give a year from 1981 (YYYY or YYYY-MM-DD)")
    return text


def _period(params: dict[str, Any], temporal: str) -> tuple[str, str]:
    if temporal == "daily":
        start, end = _day(params["start"], "start"), _day(params["end"], "end")
    else:
        start, end = _year(params["start"], "start"), _year(params["end"], "end")
    if start > end:
        raise FetchError(f"--start {params['start']} is after --end {params['end']}")
    return start, end


def _parameters(params: dict[str, Any], most: int) -> list[str]:
    names = [p.upper() for p in params.get("parameters") or []]
    if not names:
        raise FetchError("--parameters is empty; e.g. T2M,PRECTOTCORR (see the skill file for the list)")
    if len(names) > most:
        raise FetchError(
            f"{len(names)} parameters: POWER serves at most {most} per request here"
            + ("; the regional endpoint takes one parameter per load" if most == 1 else "")
        )
    return names


def _common(params: dict[str, Any]) -> tuple[str, str]:
    temporal = (params.get("temporal") or "daily").lower()
    if temporal not in TEMPORAL:
        raise FetchError(f"--temporal must be one of {', '.join(TEMPORAL)}")
    community = (params.get("community") or "RE").upper()
    if community not in COMMUNITIES:
        raise FetchError(f"--community must be one of {', '.join(COMMUNITIES)}")
    return temporal, community


def _endpoint(temporal: str, spatial: str) -> str:
    return f"{SERVICE}/{'daily' if temporal == 'daily' else 'monthly'}/{spatial}"


async def _get(ctx: Context, url: str, q: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    import json

    resp = await ctx.http.get(url, q, ok_status=(422,))
    try:
        doc = json.loads(resp.content)
    except ValueError:
        raise FetchError(f"{ctx.http.requests[-1]}: the answer is not JSON") from None
    if resp.status_code == 422 or not isinstance(doc, dict) or ("properties" not in doc and "features" not in doc):
        msgs = doc.get("messages") if isinstance(doc, dict) else None
        detail = "; ".join(str(m) for m in msgs) if isinstance(msgs, list) and msgs else str(doc)[:300]
        raise FetchError(f"POWER refused the request: {detail}")
    return doc, resp.content


def _key_cells(temporal: str, key: str) -> dict[str, Any] | None:
    """The date cells of one value's key (YYYYMMDD daily, YYYYMM monthly; month 13 is the annual value)."""
    if temporal == "daily":
        return {"date": f"{key[:4]}-{key[4:6]}-{key[6:8]}"}
    year, month = int(key[:4]), int(key[4:6])
    if temporal == "annual":
        return {"year": year} if month == 13 else None
    return None if month == 13 else {"year": year, "month": month, "date": f"{year:04d}-{month:02d}"}


def _rows(temporal: str, values: dict[str, dict[str, Any]], fill: float, where: dict[str, Any]) -> list[dict]:
    rows: dict[str, dict[str, Any]] = {}
    for name, series in values.items():
        for key, value in (series or {}).items():
            cells = _key_cells(temporal, str(key))
            if cells is None:
                continue
            row = rows.setdefault(str(key), {**where, **cells})
            row[name] = None if value is None or value == fill else value
    return [rows[k] for k in sorted(rows)]


def _record(doc: dict[str, Any], community: str, temporal: str, names: list[str]) -> dict[str, Any]:
    header = doc.get("header") or {}
    api = header.get("api") or {}
    units = {n: (doc.get("parameters") or {}).get(n, {}).get("units") for n in names}
    longnames = {n: (doc.get("parameters") or {}).get(n, {}).get("longname") for n in names}
    return {
        "api": api.get("name"),
        "api_version": api.get("version"),
        "community": community,
        "temporal": temporal,
        "time_standard": header.get("time_standard"),
        "data_sources": header.get("sources"),
        "units": units,
        "parameter_names": longnames,
    }


def _citation(record: dict[str, Any]) -> str:
    when = datetime.now(UTC).strftime("%Y/%m/%d")
    version = str(record.get("api_version") or "").lstrip("v") or "unknown version"
    api = str(record.get("api") or "POWER API")
    return (
        CITATION.split(" Data reference:")[0]
        + f" Data reference: The data was obtained from the {api} version {version} on {when}."
    )


def _note(record: dict[str, Any]) -> str:
    units = ", ".join(f"{k} {v}" for k, v in (record.get("units") or {}).items())
    return (
        f"Units: {units}. Time standard: {record.get('time_standard')}. Missing values (POWER's fill value -999) "
        f"are empty. Values are grid-cell estimates from {_sources(record)}, not station measurements."
    )


_SOURCE_NAMES = {"MERRA2": "NASA's MERRA-2 reanalysis", "SYN1DEG": "CERES SYN1deg satellite radiation"}


def _sources(record: dict[str, Any]) -> str:
    names = [str(s) for s in record.get("data_sources") or []] or ["POWER"]
    return ", ".join(f"{s} ({_SOURCE_NAMES[s]})" if s in _SOURCE_NAMES else s for s in names)


async def fetch_point(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import sha256_bytes

    temporal, community = _common(params)
    lat, lon = float(params["lat"]), float(params["lon"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise FetchError("--lat must be within ±90 and --lon within ±180 degrees")
    names = _parameters(params, MAX_POINT_PARAMETERS)
    start, end = _period(params, temporal)
    q: dict[str, Any] = {
        "parameters": ",".join(names),
        "community": community,
        "latitude": lat,
        "longitude": lon,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    if temporal == "daily" and params.get("time_standard"):
        q["time-standard"] = str(params["time_standard"]).upper()
    doc, content = await _get(ctx, _endpoint(temporal, "point"), q)
    url = ctx.http.requests[-1]
    fill = (doc.get("header") or {}).get("fill_value", -999.0)
    coords = (doc.get("geometry") or {}).get("coordinates") or [lon, lat]
    where = {"lat": lat, "lon": lon}
    if len(coords) > 2:
        where["elevation_m"] = coords[2]
    rows = _rows(temporal, (doc.get("properties") or {}).get("parameter") or {}, fill, where)
    if not rows:
        raise FetchError(f"POWER returned no values for {start}–{end}; check the period (from 1981)")
    record = _record(doc, community, temporal, names)
    return Fetched(
        rows=rows,
        series=f"NASA POWER {temporal} {', '.join(names)} at lat {lat}, lon {lon}, {start}–{end}",
        query=url,
        version=record.get("api_version"),
        files=[{"url": url, "sha256": sha256_bytes(content)}],
        link="https://power.larc.nasa.gov/data-access-viewer/",
        citation=_citation(record),
        record=record,
        note=_note(record),
        frequency=temporal,
    )


async def fetch_regional(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import sha256_bytes

    temporal, community = _common(params)
    names = _parameters(params, 1)
    raw = params.get("bbox")
    parts = raw if isinstance(raw, list) else str(raw or "").split(",")
    try:
        west, south, east, north = (float(x) for x in parts)
    except ValueError:
        raise FetchError(f"--bbox {raw!r}: give west,south,east,north in degrees, e.g. 5,47,15,55") from None
    for span, what in ((north - south, "latitude"), (east - west, "longitude")):
        if not 2 <= span <= 10:
            raise FetchError(
                f"--bbox spans {span:g} degrees of {what}; POWER's regional endpoint needs 2 to 10 "
                "(use `point` for one place, several loads for a larger area)"
            )
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise FetchError(f"--bbox {raw!r}: south below north within ±90, west below east within ±180")
    start, end = _period(params, temporal)
    q = {
        "parameters": names[0],
        "community": community,
        "latitude-min": south,
        "latitude-max": north,
        "longitude-min": west,
        "longitude-max": east,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    doc, content = await _get(ctx, _endpoint(temporal, "regional"), q)
    url = ctx.http.requests[-1]
    fill = (doc.get("header") or {}).get("fill_value", -999.0)
    rows: list[dict[str, Any]] = []
    for feature in doc.get("features") or []:
        coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
        where = {"lat": coords[1], "lon": coords[0]}
        rows += _rows(temporal, (feature.get("properties") or {}).get("parameter") or {}, fill, where)
    if not rows:
        raise FetchError(f"POWER returned no values for {start}–{end} in {raw}")
    record = _record(doc, community, temporal, names)
    record["grid_cells"] = len(doc.get("features") or [])
    return Fetched(
        rows=rows,
        series=f"NASA POWER {temporal} {names[0]} on the grid in {west},{south},{east},{north}, {start}–{end}",
        query=url,
        version=record.get("api_version"),
        files=[{"url": url, "sha256": sha256_bytes(content)}],
        link="https://power.larc.nasa.gov/data-access-viewer/",
        citation=_citation(record),
        record=record,
        note=_note(record),
        frequency=temporal,
    )


async def fetch_parameters(ctx: Context, params: dict[str, Any]) -> Fetched:
    temporal, community = _common(params)
    doc = await ctx.http.get_json(
        f"{SERVICE.rsplit('/temporal', 1)[0]}/system/manager/parameters",
        {"community": community, "temporal": "daily" if temporal == "daily" else "monthly"},
    )
    if not isinstance(doc, dict) or not doc:
        raise FetchError(f"{ctx.http.requests[-1]}: no parameter list in the answer")
    want = str(params.get("search") or "").lower()
    rows = [
        {
            "parameter": name,
            "name": (meta or {}).get("name"),
            "units": (meta or {}).get("units"),
            "type": (meta or {}).get("type"),
            "definition": (meta or {}).get("definition"),
        }
        for name, meta in sorted(doc.items())
        if not want or want in f"{name} {(meta or {}).get('name', '')} {(meta or {}).get('definition', '')}".lower()
    ]
    return Fetched(rows=rows, series=f"POWER parameters ({community}, {temporal})", query=ctx.http.requests[-1])


_COMMON_ARGS = (
    Arg("start", "First day (daily: YYYY-MM-DD) or year (monthly, annual: YYYY).", required=True),
    Arg("end", "Last day or year, same format (included).", required=True),
    Arg("temporal", "daily (default), monthly or annual.", choices=TEMPORAL),
    Arg(
        "community",
        "RE (renewable energy, default), AG (agroclimatology) or SB (sustainable buildings); "
        "sets the units of some parameters (solar radiation: kWh/m²/day for RE/SB, MJ/m²/day for AG).",
        choices=COMMUNITIES,
    ),
)

SOURCE = Source(
    name="nasa_power",
    label="NASA POWER",
    dataset="NASA Prediction Of Worldwide Energy Resources (POWER), NASA Langley Research Center",
    website="https://power.larc.nasa.gov/",
    terms_url="https://power.larc.nasa.gov/docs/referencing/",
    terms_summary=(
        "Free and keyless; NASA data without a marked restriction are CC0. POWER asks publications to give its "
        "reference with the API version and access date, and asks to be told when data are passed to others."
    ),
    terms_plain=(
        "Free and keyless; POWER states no licence, NASA's Earth science data guidance makes NASA mission data CC0.",
        "Cite POWER's reference and its data reference (API name, version, access date: recorded with each load).",
        "POWER asks to be told (larc-power-project@mail.nasa.gov) about publications and when data are passed on.",
    ),
    licence=(
        "No licence stated by POWER; NASA's Earth science data use guidance "
        '(https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance): "Unless '
        "the content is marked with a use restriction or license, data provided from a NASA-led mission are "
        "licensed as Creative Commons Zero (CC0). While there are no restrictions on the use of these data, data "
        "users are very strongly urged to cite the data used in their work products.\" POWER's referencing guide "
        '(https://power.larc.nasa.gov/docs/referencing/): "When POWER data products are used in a publication '
        "include both POWER's Reference and POWER's Data Reference in any work product or publication\" and "
        '"the Project requests notification if POWER data is transmitted to other researchers."'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Daily, monthly or annual weather and solar parameters for any point on Earth since 1981 (NASA POWER, "
        "from the MERRA-2 reanalysis and CERES satellite products): temperature (T2M, T2M_MAX, T2M_MIN), "
        "precipitation (PRECTOTCORR), humidity, wind, surface pressure, solar radiation "
        "(ALLSKY_SFC_SW_DWN). Good for climate trends, weather controls in panels, agriculture and energy "
        "studies; a 2–10 degree region for one parameter. Keyless."
    ),
    coverage="Weather and solar parameters for any point or region, daily/monthly/annual since 1981. Keyless.",
    help="NASA POWER: daily/monthly/annual weather and solar parameters for any place since 1981. No key.",
    operations=(
        Operation(
            "parameters",
            "List POWER's parameters with units and definitions, e.g. --search precipitation.",
            args=(
                Arg("search", "Only parameters whose code, name or definition contains this text."),
                Arg("temporal", "daily (default), monthly or annual.", choices=TEMPORAL),
                Arg("community", "RE (default), AG or SB: the units differ by community.", choices=COMMUNITIES),
            ),
            fetch=fetch_parameters,
            loads=False,
            card="POWER's parameter list → code, name, units, definition. Params: search, temporal, community.",
        ),
        Operation(
            "point",
            "Up to 20 parameters at one place, e.g. --lat 50.11 --lon 8.68 --parameters T2M,PRECTOTCORR "
            "--start 2000-01-01 --end 2024-12-31.",
            args=(
                Arg("lat", "Latitude, degrees (−90 to 90).", type=float, required=True),
                Arg("lon", "Longitude, degrees (−180 to 180).", type=float, required=True),
                Arg(
                    "parameters",
                    "Comma-separated POWER parameters, e.g. T2M,PRECTOTCORR (at most 20).",
                    type="list",
                    required=True,
                ),
                *_COMMON_ARGS,
                Arg(
                    "time-standard",
                    "Daily only: LST (local solar time, POWER's default) or UTC.",
                    choices=("LST", "UTC"),
                ),
            ),
            fetch=fetch_point,
            card=(
                "Weather/solar parameters at one place → one row per day (daily), month (monthly) or year "
                "(annual), one column per parameter. Params: lat, lon, parameters (list, ≤20), start, end "
                "(days for daily, years otherwise; all required), temporal ('daily'|'monthly'|'annual'), "
                "community ('RE'|'AG'|'SB'), time_standard."
            ),
        ),
        Operation(
            "regional",
            "One parameter on POWER's grid in a region of 2–10 degrees a side, e.g. --bbox 5,47,15,55 "
            "--parameters T2M --temporal monthly --start 2000 --end 2024.",
            args=(
                Arg("bbox", "Region: west,south,east,north in degrees, each side 2 to 10 degrees.", required=True),
                Arg("parameters", "One POWER parameter, e.g. T2M.", type="list", required=True),
                *_COMMON_ARGS,
            ),
            fetch=fetch_regional,
            card=(
                "One parameter on the grid in a region → one row per grid cell and day/month/year. Params: "
                "bbox ('west,south,east,north', 2–10 degrees a side), parameters (one), start, end, temporal, "
                "community."
            ),
        ),
    ),
    # POWER answers 429 when asked too often and may block repeated requests for one place.
    polite=Polite(min_interval=2.0, retries=3, timeout=180.0, max_requests=5),
    aliases=("power", "nasa_power_api", "power_larc", "nasa_larc_power"),
    skill="data/nasa_power",
    doctor=Doctor(
        "data.nasa_power.point",
        operation="point",
        params={"lat": 50.11, "lon": 8.68, "parameters": "T2M", "start": "2024-01-01", "end": "2024-01-02"},
    ),
)
