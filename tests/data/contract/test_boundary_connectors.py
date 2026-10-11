"""Boundaries for maps and spatial weights: Eurostat GISCO (NUTS, countries) and Natural Earth.

Hermetic: the GeoJSON files are mocked with respx (small FeatureCollections
shaped like the real ones: GISCO's NUTS_ID, LEVL_CODE, CNTR_CODE, NAME_LATN,
...; Natural Earth's ADM0_A3, ISO_A3_EH, ISO_A3, NAME, ...). Pins:
  - `gisco nuts --table` loads one row per region with its geometry as GeoJSON
    text, records the file's URL and SHA-256, the NUTS version, the CRS and the
    EuroGeographics notice, and filters by country;
  - GISCO's terms do not allow passing the files on: the source is restricted
    (publishing asks, get_data.py loads them again), Natural Earth's are public domain;
  - Natural Earth's countries are pinned to a release and keep both ISO3 codes;
  - an unknown NUTS version or scale is refused before any request.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx

from src.modules.data import cli
from src.modules.data.sources import get
from src.modules.data.sources.gisco import NOTICE, SERVICE
from src.modules.data.sources.naturalearth import BASE, RELEASE

PID = "boundaries-test"


def _square(x: float, y: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]}


NUTS = {
    "type": "FeatureCollection",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
    "features": [
        {
            "type": "Feature",
            "properties": {
                "NUTS_ID": nid,
                "LEVL_CODE": 2,
                "CNTR_CODE": nid[:2],
                "NAME_LATN": name,
                "NUTS_NAME": name,
                "MOUNT_TYPE": 0,
                "URBN_TYPE": 1,
                "COAST_TYPE": 3,
            },
            "geometry": _square(x, 50),
        }
        for nid, name, x in (("DE11", "Stuttgart", 9), ("DE12", "Karlsruhe", 8), ("FR10", "Ile-de-France", 2))
    ],
}
NE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "ADM0_A3": a3,
                "ISO_A3_EH": eh,
                "ISO_A3": iso,
                "NAME": n,
                "NAME_LONG": n,
                "CONTINENT": "Europe",
                "REGION_UN": "Europe",
                "SUBREGION": "Western Europe",
                "POP_EST": 1,
            },
            "geometry": _square(x, 46),
        }
        for a3, eh, iso, n, x in (("FRA", "FRA", "-99", "France", 2), ("DEU", "DEU", "DEU", "Germany", 10))
    ],
}


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.modules.data.sources.http.PACING", False)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("E2ER_CACHE_DIR", str(tmp_path / "cache"))
    w = tmp_path / "ws" / PID
    w.mkdir(parents=True)
    return w


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = cli.main(["--paper-id", PID, *argv])
    return code, json.loads(capsys.readouterr().out)


@respx.mock
def test_nuts_regions_load_with_geometry_hash_version_and_notice(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = json.dumps(NUTS).encode()
    url = f"{SERVICE}/nuts/geojson/NUTS_RG_20M_2021_4326_LEVL_2.geojson"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=body))
    code, out = _run(["gisco", "nuts", "--level", "2", "--countries", "DE", "--table", "nuts2"], capsys)
    assert code == 0, out
    assert route.called and out["row_count"] == 2
    with sqlite3.connect(ws / "data.db") as db:
        rows = db.execute("SELECT nuts_id, cntr_code, geometry FROM nuts2 ORDER BY nuts_id").fetchall()
    assert [r[0] for r in rows] == ["DE11", "DE12"]
    assert json.loads(rows[0][2])["type"] == "Polygon"

    loads = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))["loads"]
    [load] = [x for x in loads if x["connector"] == "gisco"]
    assert load["version"] == "NUTS 2021" and load["crs"] == "EPSG:4326" and load["attribution"] == NOTICE
    assert load["files"] == [{"url": url, "sha256": hashlib.sha256(body).hexdigest()}]
    assert "non-commercial" in load["terms_summary"].lower()

    # A second load of the same file comes from the cache (one request).
    code, _ = _run(["gisco", "nuts", "--level", "2", "--table", "nuts2_all"], capsys)
    assert code == 0 and route.call_count == 1


def test_an_unknown_nuts_version_or_scale_is_refused_before_any_request(ws: Path, capsys) -> None:
    with respx.mock(assert_all_called=False) as mock:
        code, out = _run(["gisco", "nuts", "--level", "2", "--year", "2019", "--table", "x"], capsys)
        assert code != 0 and "2021" in out["error"]
        code, out = _run(["gisco", "nuts", "--level", "2", "--scale", "05M", "--table", "x"], capsys)
        assert code != 0 and "20M" in out["error"]
        assert not mock.calls
    assert not (ws / "data.db").exists() or "x" not in {
        r[0] for r in sqlite3.connect(ws / "data.db").execute("SELECT name FROM sqlite_master")
    }


def test_gisco_terms_keep_the_files_out_of_a_published_study_and_natural_earth_is_public_domain() -> None:
    from src.core.data_terms import known

    gisco, ne = get("gisco"), get("naturalearth")
    assert gisco is not None and ne is not None
    assert gisco.redistribution is False and gisco.restricted is not None
    assert gisco.restricted.zenodo_licence is None and NOTICE in gisco.licence
    assert "gisco" in known() and "naturalearth" not in known()
    assert ne.redistribution is True and "public domain" in ne.licence.lower()


@respx.mock
def test_natural_earth_countries_are_pinned_to_a_release_and_keep_both_iso3_codes(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"{BASE}/{RELEASE}/geojson/ne_110m_admin_0_countries.geojson"
    respx.get(url).mock(return_value=httpx.Response(200, content=json.dumps(NE).encode()))
    code, out = _run(["naturalearth", "countries", "--table", "world"], capsys)
    assert code == 0, out
    with sqlite3.connect(ws / "data.db") as db:
        rows = dict(db.execute("SELECT name, iso_a3_eh FROM world").fetchall())
        iso = dict(db.execute("SELECT name, iso_a3 FROM world").fetchall())
    assert rows == {"France": "FRA", "Germany": "DEU"} and iso["France"] == "-99"
    load = json.loads((ws / "data_sources.json").read_text(encoding="utf-8"))["loads"][-1]
    assert load["version"] == RELEASE and load["connector"] == "naturalearth"
