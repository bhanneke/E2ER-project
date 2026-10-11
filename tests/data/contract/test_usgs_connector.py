"""USGS Earthquake Catalog: the first source built on the connector kit alone.

Hermetic. The main path replays responses recorded live once from the FDSN
event service (tests/data/fixtures/usgs_events_2024_01.json; record again
with ``E2ER_RECORD_FIXTURES=1``); the window split and the failures are mocked
with respx. Pins:
  - `usgs events --table` loads one row per event, records the query, the
    service version, the SHA-256 of the CSV read, the terms and the citation
    (data_sources.json and the data dictionary entry), and adds the USGS
    BibTeX entry once;
  - fetch_data (the API backends) records the same load;
  - a period with more than 20,000 events is split into windows by their
    counts, an event on a window boundary appears once;
  - a bad region, a refused request and too many events exit non-zero and
    leave data.db untouched;
  - the data may be published: no terms gate, no get_data.py reload.
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
from src.modules.data.sources.usgs import CITE_KEY, SERVICE

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "usgs_events_2024_01.json"
PID = "usgs-test"
ARGS = ["usgs", "events", "--start", "2024-01-01", "--end", "2024-01-08", "--min-magnitude", "5"]


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


def _recorded_csv() -> bytes:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    [csv] = [e for e in doc["interactions"] if "/query?" in e["url"]]
    return csv["text"].encode("utf-8")


def test_events_load_a_table_and_record_query_version_hash_terms_and_citation(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with use_cassette(FIXTURE):
        code, out = _run([*ARGS, "--table", "quakes", "--save-to", "quakes.csv"], capsys)
    assert code == 0, out
    assert out["error"] is None and out["row_count"] > 0
    assert out["saved_table"] == "quakes" and out["saved_table_rows"] == out["row_count"]
    assert out["recorded_in"] == ["data_sources.json", "data_dictionary.json"]
    assert out["citation_added"] is True and out["cite_key"] == CITE_KEY
    times = [r["time"] for r in out["items"]]
    assert times == sorted(times) and all(r["mag"] >= 5 for r in out["items"])

    with sqlite3.connect(ws / "data.db") as db:
        assert db.execute("SELECT COUNT(*) FROM quakes").fetchone()[0] == out["row_count"]
    assert (ws / "data" / "quakes.csv").is_file()

    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "usgs" and load["table"] == "quakes"
    assert load["terms"].startswith("https://www.usgs.gov/") and "public domain" in load["terms_summary"]
    assert load["citation_by"] == "source" and "10.5066/F7MS3QZH" in load["citation"]
    assert load["query"].startswith(f"{SERVICE}/query?") and "minmagnitude=5" in load["query"]
    assert load["service_version"] and load["windows"] == 1
    assert load["request"] == {"command": "events", "start": "2024-01-01", "end": "2024-01-08", "min_magnitude": 5.0}
    [f] = load["files"]
    assert f["sha256"] == hashlib.sha256(_recorded_csv()).hexdigest()

    [entry] = json.loads((ws / "data_dictionary.json").read_text())["tables"]
    assert entry["source"] == "usgs" and entry["frequency"] == "event" and entry["cite_key"] == CITE_KEY
    assert entry["source_files"] == [{"url": f["url"], "sha256": f["sha256"]}]

    bib = (ws / "literature.bib").read_text()
    assert bib.count("@misc{USGS_ComCat,") == 1
    # A second load does not add the entry again.
    with use_cassette(FIXTURE):
        code, out = _run([*ARGS, "--table", "quakes2"], capsys)
    assert code == 0 and out["citation_added"] is False
    assert (ws / "literature.bib").read_text().count("@misc{USGS_ComCat,") == 1


async def test_fetch_data_records_the_same_load(ws: Path) -> None:
    from src.modules.data.discovery_tools import SeriesDataToolHandler

    handler = SeriesDataToolHandler(ws)
    with use_cassette(FIXTURE):
        out = json.loads(
            await handler.handle(
                "fetch_data",
                {
                    "provider": "usgs",
                    "method": "events",
                    "params": {"start": "2024-01-01", "end": "2024-01-08", "min_magnitude": 5},
                    "materialize": True,
                    "table": "quakes",
                },
            )
        )
    assert out["error"] is None and out["items"] and out["recorded_in"] == ["data_sources.json"]
    assert "_load_record" not in out
    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "usgs" and load["table"] == "quakes" and load["files"]


def _csv(*rows: tuple[str, float, str]) -> str:
    head = "time,latitude,longitude,depth,mag,magType,id\n"
    return head + "".join(f"{t},1.0,2.0,10.0,{m},mb,{i}\n" for t, m, i in rows)


@respx.mock
def test_a_period_over_the_service_limit_is_split_by_counts(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{SERVICE}/version").mock(return_value=httpx.Response(200, text="2.8.1"))

    def count(request: httpx.Request) -> httpx.Response:
        start = request.url.params["starttime"]
        whole = start.startswith("2020-01-01") and request.url.params["endtime"].startswith("2022-01-01")
        return httpx.Response(200, json={"count": 30000 if whole else 15000, "maxAllowed": 20000})

    def query(request: httpx.Request) -> httpx.Response:
        if request.url.params["starttime"].startswith("2020-01-01"):  # the second window starts mid-period
            body = _csv(("2020-05-01T00:00:00Z", 5.1, "a"), ("2021-01-01T00:00:00Z", 5.2, "edge"))
        else:
            body = _csv(("2021-01-01T00:00:00Z", 5.2, "edge"), ("2021-06-01T00:00:00Z", 6.0, "b"))
        return httpx.Response(200, text=body, headers={"content-type": "text/csv"})

    respx.get(f"{SERVICE}/count").mock(side_effect=count)
    respx.get(f"{SERVICE}/query").mock(side_effect=query)
    code, out = _run(["usgs", "events", "--start", "2020-01-01", "--end", "2022-01-01", "--table", "q"], capsys)
    assert code == 0, out
    assert [r["id"] for r in out["items"]] == ["a", "edge", "b"]
    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["windows"] == 2 and len(load["files"]) == 2


@respx.mock
def test_too_many_events_stop_with_advice(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{SERVICE}/version").mock(return_value=httpx.Response(200, text="2.8.1"))
    respx.get(f"{SERVICE}/count").mock(return_value=httpx.Response(200, json={"count": 900000}))
    code, out = _run(["usgs", "events", "--start", "1990-01-01", "--end", "2025-01-01", "--table", "q"], capsys)
    assert code == 4 and "raise --min-magnitude or shorten the period" in out["error"]
    assert not (ws / "data.db").exists() and not (ws / "data_sources.json").exists()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--bbox", "1,2,3"], "west,south,east,north"),
        (["--bbox", "0,50,10,40"], "south must be below north"),
        (["--end", "2023-01-01"], "is not before"),
        (["--end", "yesterday"], "is not a date"),
    ],
)
def test_a_bad_request_exits_non_zero_without_a_request(
    ws: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        code, out = _run(["usgs", "events", "--start", "2024-01-01", *extra, "--table", "q"], capsys)
        assert not router.calls or all("/version" in str(c.request.url) for c in router.calls)
    assert code == 4 and message in out["error"]
    assert not (ws / "data.db").exists()


@respx.mock
def test_a_refused_request_names_the_url_and_status(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{SERVICE}/version").mock(return_value=httpx.Response(200, text="2.8.1"))
    respx.get(f"{SERVICE}/count").mock(return_value=httpx.Response(400, text="Bad Request: minmagnitude"))
    code, out = _run(["usgs", "events", "--start", "2024-01-01", "--end", "2024-02-01"], capsys)
    assert code == 4 and "HTTP 400" in out["error"] and f"{SERVICE}/count" in out["error"]


def test_usgs_data_may_be_published() -> None:
    from src.core import data_terms

    source = get("usgs")
    assert source is not None and source.redistribution
    assert "usgs" not in data_terms.known()


async def test_the_doctor_check_is_one_cheap_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.doctor import PASS, source_checks

    with use_cassette(Path(__file__).resolve().parents[1] / "fixtures" / "usgs_doctor.json"):
        [check] = await source_checks(None)
    assert check.name == "data.usgs.events" and check.status == PASS and "rows from USGS" in check.detail


def test_a_region_west_of_greenwich_is_read_as_a_value() -> None:
    """argparse takes "-125,…" for an option; e2er-data joins it to --bbox."""
    argv = ["usgs", "events", "--start", "2024-01-01", "--bbox", "-125,32,-114,42"]
    ns = cli._build_parser().parse_args(cli._join_negative_values(argv))
    assert ns.bbox == "-125,32,-114,42"
    assert cli._join_negative_values(["fred", "series", "--series-id", "DGS2"]) == [
        "fred",
        "series",
        "--series-id",
        "DGS2",
    ]
