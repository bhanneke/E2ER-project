"""USGS Earthquake Catalog: earthquakes worldwide from the ANSS ComCat, through the FDSN event web service.

The first source built on the kit alone: a definition and one fetch function.

- Service: https://earthquake.usgs.gov/fdsnws/event/1/ (keyless). ``query``
  returns events as CSV, ``count`` the number a query would return. The
  service answers at most 20,000 events per query (HTTP 400 beyond), so a
  larger request is split into time windows by their counts.
- Terms (https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits,
  checked 2026-10-11): "USGS-authored or produced data and information are
  considered to be in the U.S. Public Domain", and USGS asks "that proper
  credit be given". A study may pass the data on.
- Citation: the catalogue's DOI record (10.5066/F7MS3QZH, DataCite):
  U.S. Geological Survey (2017), Advanced National Seismic System (ANSS)
  Comprehensive Catalog.
- The catalogue has no releases; events are revised as they are reviewed.
  Each load records the query URL, the service version, the SHA-256 of every
  CSV read and when it ran.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

SERVICE = "https://earthquake.usgs.gov/fdsnws/event/1"
#: The service's own limit on the events of one query.
MAX_EVENTS = 20000
#: The most windows one load is split into (each costs a count and a query).
MAX_WINDOWS = 40

CITE_KEY = "USGS_ComCat"
CITATION = (
    "U.S. Geological Survey. (2017). Advanced National Seismic System (ANSS) Comprehensive Catalog. "
    "U.S. Geological Survey. https://doi.org/10.5066/F7MS3QZH"
)
#: From the DOI's metadata (https://doi.org/10.5066/F7MS3QZH, application/x-bibtex), with e2er's key.
BIBTEX = """@misc{USGS_ComCat,
  doi       = {10.5066/F7MS3QZH},
  url       = {https://doi.org/10.5066/F7MS3QZH},
  author    = {{U.S. Geological Survey}},
  title     = {Advanced National Seismic System (ANSS) Comprehensive Catalog},
  publisher = {U.S. Geological Survey},
  year      = {2017}
}"""

_BBOX = ("minlatitude", "minlongitude", "maxlatitude", "maxlongitude")


def _when(value: str, what: str) -> datetime:
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise FetchError(f"--{what} {value!r} is not a date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)") from None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _query(params: dict[str, Any]) -> dict[str, Any]:
    q: dict[str, Any] = {"minmagnitude": params.get("min_magnitude"), "maxmagnitude": params.get("max_magnitude")}
    bbox = params.get("bbox")
    if bbox:
        parts = bbox if isinstance(bbox, list) else str(bbox).split(",")
        try:
            west, south, east, north = (float(x) for x in parts)
        except ValueError:
            raise FetchError(f"--bbox {bbox!r}: give west,south,east,north in degrees, e.g. -125,32,-114,42") from None
        if not (-90 <= south < north <= 90) or not (-360 <= west <= 360 and -360 <= east <= 360):
            raise FetchError(f"--bbox {bbox!r}: south must be below north, latitudes within ±90")
        q.update(dict(zip(_BBOX, (south, west, north, east), strict=True)))
    if params.get("event_type"):
        q["eventtype"] = params["event_type"]
    return q


async def _count(ctx: Context, q: dict[str, Any], start: datetime, end: datetime) -> int:
    doc = await ctx.http.get_json(
        f"{SERVICE}/count", {**q, "format": "geojson", "starttime": _iso(start), "endtime": _iso(end)}
    )
    try:
        return int(doc["count"])
    except (KeyError, TypeError, ValueError):
        raise FetchError(f"{ctx.http.requests[-1]}: the count answer has no count") from None


async def _windows(ctx: Context, q: dict[str, Any], start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Time windows whose events each fit in one query, split in halves by their counts."""
    todo, done = [(start, end)], []
    while todo:
        a, b = todo.pop(0)
        n = await _count(ctx, q, a, b)
        if n <= MAX_EVENTS:
            if n:
                done.append((a, b))
            continue
        if len(done) + len(todo) + 2 > MAX_WINDOWS or (b - a).total_seconds() < 3600:
            raise FetchError(
                f"{n} events between {_iso(a)} and {_iso(b)}: more than e2er loads in one go "
                f"({MAX_WINDOWS} windows of at most {MAX_EVENTS}); raise --min-magnitude or shorten the period"
            )
        mid = a + (b - a) / 2
        todo[:0] = [(a, mid), (mid, b)]
    return sorted(done)


async def fetch_events(ctx: Context, params: dict[str, Any]) -> Fetched:
    import pandas as pd

    from .adapters import sha256_bytes

    start = _when(params["start"], "start")
    end = _when(params["end"], "end") if params.get("end") else datetime.now(UTC)
    if start >= end:
        raise FetchError(f"--start {params['start']} is not before --end {params.get('end') or 'now'}")
    q = _query(params)
    version = (await ctx.http.get_text(f"{SERVICE}/version")).strip()
    frames, files = [], []
    for a, b in await _windows(ctx, q, start, end):
        content = await ctx.http.get_bytes(
            f"{SERVICE}/query",
            {**q, "format": "csv", "orderby": "time-asc", "starttime": _iso(a), "endtime": _iso(b)},
        )
        files.append({"url": ctx.http.requests[-1], "sha256": sha256_bytes(content)})
        if content.strip():
            frames.append(pd.read_csv(io.BytesIO(content)))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        # A window boundary is shared by two windows: an event exactly on it appears once.
        df = df.drop_duplicates(subset=["id"]).sort_values("time").reset_index(drop=True)
    mag = params.get("min_magnitude")
    where = f" in {params['bbox']}" if params.get("bbox") else " worldwide"
    series = (
        f"earthquakes{f' of magnitude {mag} and above' if mag is not None else ''}{where}, "
        f"{_iso(start)[:10]} to {_iso(end)[:10]}"
    )
    import httpx

    whole = {**q, "format": "csv", "orderby": "time-asc", "starttime": _iso(start), "endtime": _iso(end)}
    first = str(httpx.URL(f"{SERVICE}/query", params={k: v for k, v in whole.items() if v is not None}))
    return Fetched(
        rows=df,
        series=series,
        query=first,
        files=files,
        link="https://earthquake.usgs.gov/earthquakes/search/",
        record={"service_version": version, "windows": len(files)},
        frequency="event",
        note=(
            "One row per event (ComCat's CSV columns: time, latitude, longitude, depth, mag, magType, …, id). "
            "The catalogue revises events as they are reviewed; the load records when it ran."
        ),
    )


SOURCE = Source(
    name="usgs",
    label="USGS Earthquake Catalog",
    dataset="ANSS Comprehensive Earthquake Catalog (ComCat), U.S. Geological Survey",
    website="https://earthquake.usgs.gov/earthquakes/search/",
    terms_url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    terms_summary=(
        "USGS-authored or produced data are in the U.S. public domain; USGS asks that proper credit be given."
    ),
    licence=(
        "U.S. public domain (https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits): "
        '"USGS-authored or produced data and information are considered to be in the U.S. Public Domain." '
        'USGS asks "that proper credit be given". Cite the catalogue: ' + CITATION
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Earthquakes worldwide from the ANSS Comprehensive Catalog (ComCat): time, location, depth, "
        "magnitude and type of every event, from 1900 (complete for small events in recent decades). "
        "Good for frequency–magnitude, aftershock and regional seismicity studies. Public domain."
    ),
    coverage="Earthquakes worldwide (ANSS ComCat): time, place, depth, magnitude. Public domain.",
    help="USGS Earthquake Catalog (ANSS ComCat): earthquakes worldwide. No key.",
    operations=(
        Operation(
            "events",
            "Earthquakes in a period, e.g. --start 2024-01-01 --end 2024-02-01 --min-magnitude 4.5 "
            "--bbox -125,32,-114,42.",
            args=(
                Arg("start", "First day (YYYY-MM-DD, or a UTC time YYYY-MM-DDTHH:MM:SS).", required=True),
                Arg("end", "End (exclusive), same format. Default: now."),
                Arg("min-magnitude", "Smallest magnitude, e.g. 2.5.", type=float),
                Arg("max-magnitude", "Largest magnitude.", type=float),
                Arg("bbox", "Region: west,south,east,north in degrees, e.g. -125,32,-114,42. Default: worldwide."),
                Arg("event-type", "Only this event type, e.g. earthquake (default: every type in the catalogue)."),
            ),
            fetch=fetch_events,
            card=(
                "Earthquakes in a period → one row per event. Params: start (YYYY-MM-DD, required), end, "
                "min_magnitude, max_magnitude, bbox ('west,south,east,north'), event_type."
            ),
        ),
    ),
    polite=Polite(min_interval=0.5, max_requests=2 * MAX_WINDOWS + 5),
    aliases=("usgs_earthquakes", "comcat", "anss_comcat", "usgs_earthquake_catalog"),
    skill="data/usgs",
    doctor=Doctor(
        "data.usgs.events",
        operation="events",
        params={"start": "2024-01-01", "end": "2024-01-02", "min_magnitude": 5},
    ),
)
