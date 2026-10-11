"""Eurostat GISCO boundaries: NUTS regions and countries as GeoJSON, one row per unit.

- Service: the GISCO distribution API (https://gisco-services.ec.europa.eu/distribution/v2/),
  keyless. NUTS files: ``nuts/geojson/NUTS_RG_{scale}_{year}_{crs}_LEVL_{level}.geojson``
  (years 2003 to 2024, scales 01M, 03M, 10M, 20M, 60M, CRS 4326, 3035, 3857);
  countries: ``countries/geojson/CNTR_RG_{scale}_{year}_{crs}.geojson``.
  Checked 2026-10-11 (NUTS_RG_20M_2021_4326_LEVL_2.geojson: 334 regions,
  718,581 bytes).
- Terms (https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units,
  checked 2026-10-11): "The Commission agrees to grant the non-exclusive and
  non-transferable right to use and process the Eurostat/GISCO geographical
  data downloaded from this page (the 'data'). The permission to use the data
  is granted on condition that: the data will not be used for commercial
  purposes the source will be acknowledged. A copyright notice, as specified
  below, must be visible on any printed or electronic publication using the
  data downloaded from this page." For NUTS the notice is "© EuroGeographics
  for the administrative boundaries", in the legend of the map and in the
  introductory page of the publication. The administrative units page
  (countries) has the same wording. Nothing grants passing the files on, so a
  published study does not ship them: ``get_data.py`` loads them again.
- Citation: GISCO publishes none for the files; e2er cites the dataset by its
  page and the required copyright notice.

Each row is one unit with its id, names and codes and its geometry as GeoJSON
text (``geometry``), so a study keeps its boundaries in ``data.db`` beside its
data and the map renderer and the spatial checks read them from there.
"""

from __future__ import annotations

import json
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Restricted, Source

SERVICE = "https://gisco-services.ec.europa.eu/distribution/v2"
NUTS_YEARS = ("2003", "2006", "2010", "2013", "2016", "2021", "2024")
COUNTRY_YEARS = ("2001", "2006", "2010", "2013", "2016", "2020", "2024")
SCALES = ("01M", "03M", "10M", "20M", "60M")
CRS = ("4326", "3035", "3857")
NOTICE = "© EuroGeographics for the administrative boundaries"
TERMS_URL = "https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units"
CITE_KEY = "Eurostat_GISCO_NUTS"
CITATION = (
    "Eurostat, GISCO. Territorial units for statistics (NUTS), boundaries. European Commission. "
    "https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics. " + NOTICE + "."
)
BIBTEX = """@misc{Eurostat_GISCO_NUTS,
  author       = {{Eurostat}},
  title        = {{GISCO}: Territorial units for statistics ({NUTS}), boundaries},
  publisher    = {European Commission},
  howpublished = {\\url{https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics}},
  note         = {\\textcopyright{} EuroGeographics for the administrative boundaries}
}"""

_NUTS_KEEP = ("NUTS_ID", "LEVL_CODE", "CNTR_CODE", "NAME_LATN", "NUTS_NAME", "MOUNT_TYPE", "URBN_TYPE", "COAST_TYPE")
_CNTR_KEEP = ("CNTR_ID", "CNTR_NAME", "NAME_ENGL", "ISO3_CODE", "EU_STAT", "EFTA_STAT", "CC_STAT")


def _choice(value: Any, allowed: tuple[str, ...], what: str) -> str:
    s = str(value).strip().upper() if what == "scale" else str(value).strip()
    if s not in allowed:
        raise FetchError(f"--{what} {value!r}: GISCO publishes {', '.join(allowed)}")
    return s


def _rows(doc: Any, keep: tuple[str, ...], countries: list[str] | None, country_key: str) -> list[dict[str, Any]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("features"), list):
        raise FetchError("GISCO answered with something other than a GeoJSON FeatureCollection")
    wanted = {c.upper() for c in countries} if countries else None
    out = []
    for f in doc["features"]:
        props = f.get("properties") or {}
        if wanted and str(props.get(country_key) or "").upper() not in wanted:
            continue
        row = {k.lower(): props.get(k) for k in keep}
        row["geometry"] = json.dumps(f.get("geometry"), separators=(",", ":"))
        out.append(row)
    return out


async def _load(ctx: Context, url: str, version: str) -> tuple[Any, dict[str, Any]]:
    from .adapters import download_file

    path, meta = await download_file(ctx.http, url, "gisco", version=version)
    try:
        return json.loads(path.read_text(encoding="utf-8")), meta
    except (OSError, ValueError) as e:
        raise FetchError(f"{url}: not a readable GeoJSON file ({e})") from None


async def fetch_nuts(ctx: Context, params: dict[str, Any]) -> Fetched:
    level = params.get("level")
    if level not in (0, 1, 2, 3):
        raise FetchError("--level must be 0, 1, 2 or 3")
    year = _choice(params.get("year") or "2021", NUTS_YEARS, "year")
    scale = _choice(params.get("scale") or "20M", SCALES, "scale")
    crs = _choice(params.get("crs") or "4326", CRS, "crs")
    if year == "2003" and scale == "60M":
        raise FetchError("NUTS 2003 has no 60M scale; use 20M")
    name = f"NUTS_RG_{scale}_{year}_{crs}_LEVL_{level}.geojson"
    url = f"{SERVICE}/nuts/geojson/{name}"
    doc, meta = await _load(ctx, url, f"nuts-{year}")
    rows = _rows(doc, _NUTS_KEEP, params.get("countries"), "CNTR_CODE")
    if not rows:
        raise FetchError(f"{name} holds no region of {', '.join(params.get('countries') or [])}")
    where = f" in {', '.join(params['countries'])}" if params.get("countries") else ""
    return Fetched(
        rows=rows,
        series=f"NUTS {level} regions{where}, NUTS {year}, 1:{scale[:-1].lstrip('0')} million, EPSG:{crs}",
        query=url,
        version=f"NUTS {year}",
        files=[{"url": meta["url"], "sha256": meta["sha256"]}],
        link="https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics",
        record={"nuts_year": year, "level": level, "scale": scale, "crs": f"EPSG:{crs}", "attribution": NOTICE},
        note=(
            f"One row per region: nuts_id, levl_code, cntr_code, name_latn, nuts_name, mount_type, urbn_type, "
            f"coast_type and geometry (GeoJSON, EPSG:{crs}). Join the data on nuts_id with the same NUTS version "
            f"({year}); codes change between versions. Every map must carry: {NOTICE}. Not for commercial use."
        ),
        frequency="static",
    )


async def fetch_countries(ctx: Context, params: dict[str, Any]) -> Fetched:
    year = _choice(params.get("year") or "2024", COUNTRY_YEARS, "year")
    scale = _choice(params.get("scale") or "20M", SCALES, "scale")
    crs = _choice(params.get("crs") or "4326", CRS, "crs")
    name = f"CNTR_RG_{scale}_{year}_{crs}.geojson"
    url = f"{SERVICE}/countries/geojson/{name}"
    doc, meta = await _load(ctx, url, f"countries-{year}")
    rows = _rows(doc, _CNTR_KEEP, params.get("countries"), "CNTR_ID")
    return Fetched(
        rows=rows,
        series=f"countries, GISCO {year}, 1:{scale[:-1].lstrip('0')} million, EPSG:{crs}",
        query=url,
        version=f"countries {year}",
        files=[{"url": meta["url"], "sha256": meta["sha256"]}],
        link="https://ec.europa.eu/eurostat/web/gisco/geodata/administrative-units/countries",
        record={"year": year, "scale": scale, "crs": f"EPSG:{crs}", "attribution": NOTICE},
        note=f"One row per country: cntr_id, cntr_name, name_engl, iso3_code, … and geometry. Maps carry: {NOTICE}.",
        frequency="static",
    )


SOURCE = Source(
    name="gisco",
    label="Eurostat GISCO boundaries",
    dataset="GISCO geographical data (NUTS regions, countries), Eurostat",
    website="https://ec.europa.eu/eurostat/web/gisco",
    terms_url=TERMS_URL,
    terms_summary=(
        "Use and processing for non-commercial purposes, with the source acknowledged and the notice "
        f"'{NOTICE}' on every map and publication; the files may not be passed on."
    ),
    terms_plain=(
        "Non-commercial use only.",
        f"Every map and publication using the boundaries carries: {NOTICE}.",
        "The boundary files are not passed on: a published study loads them again.",
    ),
    licence=(
        f'GISCO download terms ({TERMS_URL}): "The Commission agrees to grant the non-exclusive and '
        "non-transferable right to use and process the Eurostat/GISCO geographical data downloaded from this "
        "page (the 'data'). The permission to use the data is granted on condition that: the data will not be "
        "used for commercial purposes the source will be acknowledged. A copyright notice, as specified below, "
        f'must be visible on any printed or electronic publication using the data downloaded from this page." '
        f"Notice: {NOTICE}."
    ),
    citation=CITATION,
    citation_by="e2er",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Boundaries of the EU's statistical regions (NUTS 0 to 3, versions 2003 to 2024) and of countries, as "
        "GeoJSON geometries in data.db, to map regional data (Eurostat's NUTS tables) and to build spatial "
        "weights. Non-commercial use; maps carry the EuroGeographics notice."
    ),
    coverage="NUTS 0–3 regions (2003–2024) and countries: boundaries as GeoJSON. Non-commercial use.",
    help="Eurostat GISCO: NUTS region and country boundaries (GeoJSON). No key.",
    operations=(
        Operation(
            "nuts",
            "NUTS regions of one level, e.g. --level 2 --year 2021 --scale 20M --crs 4326.",
            args=(
                Arg("level", "NUTS level: 0 (countries), 1, 2 or 3.", type=int, required=True),
                Arg("year", "NUTS version: " + ", ".join(NUTS_YEARS) + ". Default 2021.", default="2021"),
                Arg("scale", "Generalisation: 01M (detailed) to 60M (coarse). Default 20M.", default="20M"),
                Arg("crs", "EPSG code: 4326 (lon/lat, default), 3035 (ETRS89-LAEA metres), 3857.", default="4326"),
                Arg("countries", "Only these country codes, e.g. DE,FR,IT (EL for Greece). Default: all.", type="list"),
            ),
            fetch=fetch_nuts,
            card=(
                "NUTS boundaries → one row per region with geometry (GeoJSON text). Params: level (0-3, required), "
                "year (2021), scale (20M), crs (4326), countries."
            ),
        ),
        Operation(
            "countries",
            "Country boundaries, e.g. --year 2024 --scale 20M.",
            args=(
                Arg("year", "Version: " + ", ".join(COUNTRY_YEARS) + ". Default 2024.", default="2024"),
                Arg("scale", "Generalisation: 01M to 60M. Default 20M.", default="20M"),
                Arg("crs", "EPSG code: 4326 (default), 3035, 3857.", default="4326"),
                Arg("countries", "Only these GISCO country ids, e.g. DE,FR. Default: all.", type="list"),
            ),
            fetch=fetch_countries,
            card="Country boundaries → one row per country with geometry. Params: year (2024), scale, crs, countries.",
        ),
    ),
    redistribution=False,
    restricted=Restricted(
        short="GISCO",
        name="Eurostat GISCO boundaries",
        zenodo_licence=None,
        no_zenodo_why="the GISCO terms grant a non-transferable right to use the boundaries, not to pass them on",
        limit=(
            "allow non-commercial use with the EuroGeographics notice, and do not allow passing the boundary files on"
        ),
        limit_finish="do not allow passing the boundary files on",
        warn="Maps drawn from the boundaries carry: " + NOTICE + ".",
    ),
    polite=Polite(min_interval=1.0, max_requests=4, timeout=120.0),
    aliases=("eurostat_gisco", "nuts_boundaries", "gisco_nuts"),
    skill="data/gisco",
    doctor=Doctor("data.gisco.nuts", operation="nuts", params={"level": 0, "year": "2021", "scale": "60M"}),
)
