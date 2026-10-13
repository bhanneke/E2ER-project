"""Natural Earth: country boundaries of the world, public domain, one row per country.

- Files: the GeoJSON files of the Natural Earth vector data in its GitHub
  repository, pinned to a release tag
  (https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_admin_0_countries.geojson;
  177 countries at 1:110 million, checked 2026-10-11). Scales 110m, 50m, 10m.
- Terms (https://www.naturalearthdata.com/about/terms-of-use/, checked
  2026-10-11): "All versions of Natural Earth raster + vector map data found
  on this website are in the public domain. You may use the maps in any
  manner, including modifying the content and design, electronic
  dissemination, and offset printing. ... No permission is needed to use
  Natural Earth. Crediting the authors is unnecessary." Suggested credit:
  "Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com."
- Country codes: join on ``iso_a3_eh`` or ``adm0_a3``, never on ``iso_a3``
  alone (it is -99 for France, Norway, Kosovo, Northern Cyprus and Somaliland).
"""

from __future__ import annotations

import json
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

RELEASE = "v5.1.2"
BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
SCALES = ("110m", "50m", "10m")
CREDIT = "Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com."
CITE_KEY = "NaturalEarth"
CITATION = f"Natural Earth (release {RELEASE}). Admin 0 – Countries. https://www.naturalearthdata.com/. {CREDIT}"
BIBTEX = """@misc{NaturalEarth,
  author       = {{Natural Earth}},
  title        = {Natural Earth: Admin 0 -- Countries},
  howpublished = {\\url{https://www.naturalearthdata.com/}},
  note         = {Public domain. Made with Natural Earth}
}"""
_KEEP = ("ADM0_A3", "ISO_A3_EH", "ISO_A3", "NAME", "NAME_LONG", "CONTINENT", "REGION_UN", "SUBREGION", "POP_EST")


async def fetch_countries(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import download_file

    scale = str(params.get("scale") or "110m").lower()
    if scale not in SCALES:
        raise FetchError(f"--scale {scale!r}: Natural Earth publishes {', '.join(SCALES)}")
    url = f"{BASE}/{RELEASE}/geojson/ne_{scale}_admin_0_countries.geojson"
    path, meta = await download_file(ctx.http, url, "naturalearth", version=RELEASE)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FetchError(f"{url}: not a readable GeoJSON file ({e})") from None
    wanted = {c.upper() for c in params.get("countries") or []}
    rows = []
    for f in doc.get("features") or []:
        props = f.get("properties") or {}
        if (
            wanted
            and str(props.get("ADM0_A3") or "").upper() not in wanted
            and str(props.get("ISO_A3_EH") or "").upper() not in wanted
        ):
            continue
        row = {k.lower(): props.get(k) for k in _KEEP}
        row["geometry"] = json.dumps(f.get("geometry"), separators=(",", ":"))
        rows.append(row)
    return Fetched(
        rows=rows,
        series=f"countries of the world, Natural Earth {RELEASE}, 1:{scale[:-1]} million, EPSG:4326",
        query=url,
        version=RELEASE,
        files=[{"url": meta["url"], "sha256": meta["sha256"]}],
        link="https://www.naturalearthdata.com/downloads/",
        record={"scale": scale, "crs": "EPSG:4326", "attribution": CREDIT},
        note=(
            "One row per country: adm0_a3, iso_a3_eh, iso_a3, name, name_long, continent, region_un, subregion, "
            "pop_est and geometry (GeoJSON, EPSG:4326). Join ISO3 codes on iso_a3_eh or adm0_a3 (iso_a3 is -99 "
            "for France and Norway). Public domain."
        ),
        frequency="static",
    )


SOURCE = Source(
    name="naturalearth",
    label="Natural Earth",
    dataset="Natural Earth vector data: Admin 0 – Countries",
    website="https://www.naturalearthdata.com/",
    terms_url="https://www.naturalearthdata.com/about/terms-of-use/",
    terms_summary="Public domain; no permission is needed and crediting the authors is unnecessary.",
    licence=(
        'Public domain (https://www.naturalearthdata.com/about/terms-of-use/): "All versions of Natural Earth '
        "raster + vector map data found on this website are in the public domain. You may use the maps in any "
        "manner, including modifying the content and design, electronic dissemination, and offset printing. "
        '... No permission is needed to use Natural Earth. Crediting the authors is unnecessary." '
        f"Suggested credit: {CREDIT}"
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Country boundaries of the world (Natural Earth, release " + RELEASE + ", 1:110m, 1:50m, 1:10m) as "
        "GeoJSON geometries in data.db, to map country data (World Bank, WHO, OWID) by ISO3 code. Public domain."
    ),
    coverage="Country boundaries of the world at 1:110m, 1:50m, 1:10m. Public domain.",
    help="Natural Earth: country boundaries of the world (GeoJSON), public domain. No key.",
    operations=(
        Operation(
            "countries",
            "Country boundaries, e.g. --scale 110m (--countries FRA,DEU to keep some).",
            args=(
                Arg("scale", "110m (coarse, default), 50m or 10m (detailed, large).", default="110m"),
                Arg("countries", "Only these ISO3 codes (adm0_a3 or iso_a3_eh), e.g. FRA,DEU.", type="list"),
            ),
            fetch=fetch_countries,
            card="Country boundaries → one row per country with geometry (GeoJSON). Params: scale (110m), countries.",
        ),
    ),
    polite=Polite(min_interval=1.0, max_requests=2, timeout=120.0),
    aliases=("natural_earth", "ne_countries"),
    skill="data/naturalearth",
    doctor=Doctor("data.naturalearth.countries", operation="countries", params={"scale": "110m"}),
)
