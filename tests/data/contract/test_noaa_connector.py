"""NOAA Climate Data Online (`e2er-data noaa`): GHCN-Daily station records, with a free token.

Hermetic (respx; no live call: the token is personal). Pins:
  - without NOAA_TOKEN the source is not offered, a load and the doctor say
    how to get a free token, and nothing is requested;
  - `daily` sends the token in a header (never in the URL or the record),
    pages through 1,000-result pages, splits a period by calendar year, and
    records every page's URL and SHA-256, the subset in the citation and the
    GHCN-Daily BibTeX entries;
  - `stations` lists stations in a region and loads nothing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from src.modules.data import cli
from src.modules.data.sources import get
from src.modules.data.sources.noaa import CITE_KEY, PAGE, SERVICE

PID = "noaa-test"
TOKEN = "secret-test-token"


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


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("NOAA_TOKEN", TOKEN)
    return TOKEN


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = cli.main(["--paper-id", PID, *argv])
    return code, json.loads(capsys.readouterr().out)


def _obs(day: str, dtype: str, value: float) -> dict:
    return {"date": f"{day}T00:00:00", "datatype": dtype, "station": "GHCND:USW00094728", "attributes": ",,W,2400",
            "value": value}  # fmt: skip


def test_without_a_token_the_source_says_how_to_get_one(
    ws: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.core.specialists import data_sources as ds

    monkeypatch.delenv("NOAA_TOKEN", raising=False)
    source = get("noaa")
    assert source is not None and source.key is not None and not source.key.optional
    assert not source.available(SimpleNamespace())
    with respx.mock(assert_all_called=False) as router:
        code, out = _run(["noaa", "daily", "--stations", "USW00094728", "--start", "2024-01-01", "--end",
                          "2024-01-02", "--table", "t"], capsys)  # fmt: skip
        assert not router.calls
    assert code == 4 and "NOAA_TOKEN not configured" in out["error"] and "cdo-web/token" in out["error"]
    block = ds.sources_block(ws, SimpleNamespace(fred_api_key=None, allium_api_key=None))
    assert "- `noaa` (no key needed)" not in block


async def test_the_doctor_skips_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.doctor import SKIP
    from src.modules.data.sources.runtime import doctor_check

    monkeypatch.delenv("NOAA_TOKEN", raising=False)
    source = get("noaa")
    assert source is not None
    check = await doctor_check(source, SimpleNamespace())
    assert check.status == SKIP and "NOAA_TOKEN" in check.detail


@respx.mock
def test_daily_pages_splits_by_year_and_records_without_the_token(
    ws: Path, capsys: pytest.CaptureFixture[str], token: str
) -> None:
    def data(request: httpx.Request) -> httpx.Response:
        assert request.headers["token"] == token and token not in str(request.url)
        p = request.url.params
        assert p.get_list("stationid") == ["GHCND:USW00094728"] and p["units"] == "metric"
        if p["startdate"] == "2023-12-30":
            assert p["enddate"] == "2023-12-31"
            if p["offset"] == "1":  # a full first page, then the rest
                rows = [_obs("2023-12-30", "TMAX", 5.0)] * (PAGE - 1) + [_obs("2023-12-31", "TMAX", 6.0)]
                return httpx.Response(200, json={"metadata": {"resultset": {"count": PAGE + 1}}, "results": rows})
            assert p["offset"] == str(PAGE + 1)
            return httpx.Response(200, json={"results": [_obs("2023-12-31", "TMIN", -1.0)]})
        assert (p["startdate"], p["enddate"]) == ("2024-01-01", "2024-01-02")
        return httpx.Response(200, json={"metadata": {"resultset": {"count": 1}},
                                         "results": [_obs("2024-01-01", "TMAX", 7.5)]})  # fmt: skip

    respx.get(f"{SERVICE}/data").mock(side_effect=data)
    code, out = _run(["noaa", "daily", "--stations", "USW00094728", "--datatypes", "tmax,tmin",
                      "--start", "2023-12-30", "--end", "2024-01-02", "--table", "nyc"], capsys)  # fmt: skip
    assert code == 0, out
    assert out["row_count"] == PAGE + 2
    assert out["items"][-1] == {"date": "2024-01-01", "station": "GHCND:USW00094728", "datatype": "TMAX",
                                "value": 7.5, "attributes": ",,W,2400"}  # fmt: skip
    with sqlite3.connect(ws / "data.db") as db:
        assert db.execute("SELECT COUNT(*) FROM nyc").fetchone()[0] == PAGE + 2

    text = (ws / "data_sources.json").read_text()
    assert token not in text
    [load] = json.loads(text)["loads"]
    assert load["connector"] == "noaa" and len(load["files"]) == 3 and load["requests"] == 3
    assert all(len(f["sha256"]) == 64 for f in load["files"])
    assert "USW00094728" in load["citation"] and "TMAX, TMIN" in load["citation"] and "accessed" in load["citation"]
    assert "10.7289/V5D21VHZ" in load["citation"] and "10.1175/JTECH-D-11-00103.1" in load["citation"]
    bib = (ws / "literature.bib").read_text()
    assert bib.count(f"{{{CITE_KEY},") == 1 and "{Menne2012_GHCND_overview," in bib


@respx.mock
def test_stations_list_a_region_and_load_nothing(ws: Path, capsys: pytest.CaptureFixture[str], token: str) -> None:
    station = {"id": "GHCND:USW00094728", "name": "NY CITY CENTRAL PARK, NY US", "latitude": 40.77898,
               "longitude": -73.96925, "elevation": 42.7, "mindate": "1869-01-01", "maxdate": "2026-10-09",
               "datacoverage": 1, "elevationUnit": "METERS"}  # fmt: skip
    route = respx.get(f"{SERVICE}/stations").mock(
        return_value=httpx.Response(200, json={"metadata": {"resultset": {"count": 1}}, "results": [station]})
    )
    code, out = _run(["noaa", "stations", "--bbox", "-74.3,40.5,-73.7,40.9", "--datatypes", "TMAX"], capsys)
    assert code == 0, out
    assert out["items"][0]["id"] == "GHCND:USW00094728" and "elevationUnit" not in out["items"][0]
    assert route.calls[0].request.url.params["extent"] == "40.5,-74.3,40.9,-73.7"
    assert not (ws / "data_sources.json").exists()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["daily", "--stations", "X", "--start", "2024-02-01", "--end", "2024-01-01"], "is after"),
        (["daily", "--stations", "X", "--start", "1900-01-01", "--end", "2024-01-01"], "longer than 30 years"),
        (["daily", "--stations", "X", "--start", "yesterday", "--end", "2024-01-01"], "is not a day"),
    ],
)
def test_a_bad_request_exits_non_zero_without_a_request(
    ws: Path, capsys: pytest.CaptureFixture[str], token: str, argv: list[str], message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        code, out = _run(["noaa", *argv, "--table", "t"], capsys)
        assert not router.calls
    assert code == 4 and message in out["error"]
