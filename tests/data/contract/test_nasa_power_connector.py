"""NASA POWER (`e2er-data nasa_power`): daily, monthly and annual weather and solar parameters.

Hermetic. The main paths replay responses recorded live once from the POWER
API (tests/data/fixtures/nasa_power_*.json; record again with
``E2ER_RECORD_FIXTURES=1``); failures are mocked with respx. Pins:
  - `point` daily loads one row per day with one column per parameter, the
    fill value as empty; the record holds the API version, community, time
    standard, units, data sources, the request URL and the SHA-256 of the
    JSON read; the citation names the API, version and access date as POWER
    asks; the BibTeX entry goes into literature.bib once;
  - monthly rows drop POWER's month 13 (the annual value); annual rows keep
    only it;
  - `regional` returns one row per grid cell and month;
  - POWER's limits (20 parameters at a point, one in a region, 2–10 degree
    boxes) are checked before a request; a refusal (HTTP 422) reports POWER's
    message; data.db is untouched;
  - `parameters` lists codes with units and loads nothing;
  - the data may be published; the doctor check is one cheap request.
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
from src.modules.data.sources.http import use_cassette
from src.modules.data.sources.nasa_power import CITE_KEY, SERVICE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PID = "power-test"
POINT = ["nasa_power", "point", "--lat", "50.11", "--lon", "8.68"]


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


def test_a_daily_point_loads_a_table_and_records_version_units_hash_and_citation(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = FIXTURES / "nasa_power_point_daily.json"
    argv = [*POINT, "--parameters", "T2M,PRECTOTCORR", "--start", "2024-01-01", "--end", "2024-01-07"]
    with use_cassette(fixture):
        code, out = _run([*argv, "--table", "ffm"], capsys)
    assert code == 0, out
    assert out["row_count"] == 7 and out["citation_added"] is True and out["cite_key"] == CITE_KEY
    first = out["items"][0]
    assert first["date"] == "2024-01-01" and first["lat"] == 50.11 and first["lon"] == 8.68
    assert isinstance(first["T2M"], float) and isinstance(first["PRECTOTCORR"], float)
    assert [r["date"] for r in out["items"]] == [f"2024-01-0{d}" for d in range(1, 8)]
    assert "T2M C" in out["note"] and "PRECTOTCORR mm/day" in out["note"] and "MERRA-2" in out["note"]

    with sqlite3.connect(ws / "data.db") as db:
        assert db.execute("SELECT COUNT(*) FROM ffm").fetchone()[0] == 7

    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "nasa_power" and load["frequency"] == "daily"
    assert load["api"] == "POWER Daily API" and load["version"] == load["api_version"]
    assert load["version"].startswith("v2.")
    assert load["community"] == "RE" and load["time_standard"] == "LST" and "MERRA2" in load["data_sources"]
    assert load["units"] == {"T2M": "C", "PRECTOTCORR": "mm/day"}
    assert load["query"].startswith(f"{SERVICE}/daily/point?") and "start=20240101" in load["query"]
    doc = json.loads(fixture.read_text(encoding="utf-8"))
    [body] = [e["text"] for e in doc["interactions"]]
    assert load["files"][0]["sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert "Prediction Of Worldwide Energy Resources (POWER) project" in load["citation"]
    assert f"POWER Daily API version {load['version'].lstrip('v')} on " in load["citation"]
    assert "Creative Commons Zero" in load["licence"] and "notification" in load["licence"]

    [entry] = json.loads((ws / "data_dictionary.json").read_text())["tables"]
    assert entry["source"] == "nasa_power" and entry["frequency"] == "daily" and entry["version"] == load["version"]
    assert (ws / "literature.bib").read_text().count("@misc{NASA_POWER,") == 1


def test_monthly_drops_the_annual_value_and_annual_keeps_only_it(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = FIXTURES / "nasa_power_point_monthly.json"
    with use_cassette(fixture):
        code, monthly = _run([*POINT, "--parameters", "T2M", "--temporal", "monthly", "--start", "2023",
                              "--end", "2023", "--table", "m"], capsys)  # fmt: skip
        assert code == 0, monthly
        code, annual = _run([*POINT, "--parameters", "T2M", "--temporal", "annual", "--start", "2023",
                             "--end", "2023", "--table", "a"], capsys)  # fmt: skip
    assert code == 0, annual
    assert [(r["year"], r["month"]) for r in monthly["items"]] == [(2023, m) for m in range(1, 13)]
    assert monthly["items"][0]["date"] == "2023-01"
    [year] = annual["items"]
    assert year["year"] == 2023 and "month" not in year and isinstance(year["T2M"], float)
    loads = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert [ld["frequency"] for ld in loads] == ["monthly", "annual"]


def test_a_region_loads_one_row_per_grid_cell_and_month(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with use_cassette(FIXTURES / "nasa_power_regional.json"):
        code, out = _run(["nasa_power", "regional", "--bbox", "8,50,10,52", "--parameters", "T2M",
                          "--temporal", "monthly", "--start", "2023", "--end", "2023", "--table", "grid"],
                         capsys)  # fmt: skip
    assert code == 0, out
    cells = {(r["lat"], r["lon"]) for r in out["items"]}
    assert len(cells) > 1 and out["row_count"] == 12 * len(cells)
    assert all(50 <= lat <= 52 and 8 <= lon <= 10 for lat, lon in cells)
    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["grid_cells"] == len(cells) and "latitude-min=50" in load["query"]


@respx.mock
def test_the_fill_value_is_empty(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = {
        "geometry": {"coordinates": [8.68, 50.11, 171.6]},
        "properties": {"parameter": {"T2M": {"20240101": 5.0, "20240102": -999.0}}},
        "header": {"api": {"name": "POWER Daily API", "version": "v2.10.0"}, "fill_value": -999.0,
                   "time_standard": "LST", "sources": ["MERRA2"]},
        "parameters": {"T2M": {"units": "C", "longname": "Temperature at 2 Meters"}},
    }  # fmt: skip
    respx.get(f"{SERVICE}/daily/point").mock(return_value=httpx.Response(200, json=doc))
    code, out = _run([*POINT, "--parameters", "T2M", "--start", "2024-01-01", "--end", "2024-01-02"], capsys)
    assert code == 0, out
    assert [r["T2M"] for r in out["items"]] == [5.0, None]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ([*POINT, "--parameters", ",".join(f"P{i}" for i in range(21)), "--start", "2024-01-01", "--end",
          "2024-01-02"], "at most 20"),
        ([*POINT, "--parameters", "T2M", "--start", "2024-13-01", "--end", "2024-12-31"], "is not a day"),
        ([*POINT, "--parameters", "T2M", "--start", "2024-02-01", "--end", "2024-01-01"], "is after"),
        ([*POINT, "--parameters", "T2M", "--temporal", "monthly", "--start", "1970", "--end", "1980"],
         "from 1981"),
        (["nasa_power", "point", "--lat", "95", "--lon", "0", "--parameters", "T2M", "--start", "2024-01-01",
          "--end", "2024-01-02"], "±90"),
        (["nasa_power", "regional", "--bbox", "8,50,9,52", "--parameters", "T2M", "--start", "2024-01-01",
          "--end", "2024-01-02"], "2 to 10"),
        (["nasa_power", "regional", "--bbox", "0,40,20,52", "--parameters", "T2M", "--start", "2024-01-01",
          "--end", "2024-01-02"], "2 to 10"),
        (["nasa_power", "regional", "--bbox", "8,50,10,52", "--parameters", "T2M,PS", "--start", "2024-01-01",
          "--end", "2024-01-02"], "one parameter per load"),
    ],
)  # fmt: skip
def test_a_bad_request_exits_non_zero_without_a_request(
    ws: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        code, out = _run([*argv, "--table", "t"], capsys)
        assert not router.calls
    assert code == 4 and message in out["error"]
    assert not (ws / "data.db").exists()


@respx.mock
def test_a_refusal_reports_powers_message(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = {
        "header": "The POWER Daily API failed to complete your request; please review the errors below.",
        "messages": ["One of your parameters is incorrect: FOO."],
    }
    respx.get(f"{SERVICE}/daily/point").mock(return_value=httpx.Response(422, json=body))
    code, out = _run([*POINT, "--parameters", "FOO", "--start", "2024-01-01", "--end", "2024-01-02", "--table", "t"],
                     capsys)  # fmt: skip
    assert code == 4 and out["error"] == "POWER refused the request: One of your parameters is incorrect: FOO."
    assert not (ws / "data.db").exists() and not (ws / "data_sources.json").exists()


@respx.mock
def test_parameters_lists_codes_with_units_and_loads_nothing(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalogue = {
        "T2M": {"name": "Temperature at 2 Meters", "units": "C", "type": "METEOROLOGY", "definition": "Air temp."},
        "PRECTOTCORR": {"name": "Precipitation Corrected", "units": "mm/day", "type": "METEOROLOGY",
                        "definition": "Bias corrected total precipitation."},
    }  # fmt: skip
    route = respx.get("https://power.larc.nasa.gov/api/system/manager/parameters").mock(
        return_value=httpx.Response(200, json=catalogue)
    )
    code, out = _run(["nasa_power", "parameters", "--search", "precip"], capsys)
    assert code == 0, out
    assert out["items"] == [
        {
            "parameter": "PRECTOTCORR",
            "name": "Precipitation Corrected",
            "units": "mm/day",
            "type": "METEOROLOGY",
            "definition": "Bias corrected total precipitation.",
        }
    ]
    assert route.calls[0].request.url.params["community"] == "RE"
    assert not (ws / "data_sources.json").exists() and not (ws / "data.db").exists()


async def test_the_doctor_check_is_one_cheap_request() -> None:
    from src.doctor import PASS
    from src.modules.data.sources.runtime import doctor_check

    source = get("nasa_power")
    assert source is not None
    with use_cassette(FIXTURES / "nasa_power_doctor.json") as cassette:
        check = await doctor_check(source, None)
    assert check.name == "data.nasa_power.point" and check.status == PASS
    assert "rows from NASA POWER" in check.detail and len(cassette.entries) == 1


def test_power_data_may_be_published() -> None:
    from src.core import data_terms

    source = get("nasa_power")
    assert source is not None and source.redistribution and source.key is None
    assert "nasa_power" not in data_terms.known()
