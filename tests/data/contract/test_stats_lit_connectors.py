"""World Bank, Eurostat, Our World in Data, WHO GHO, Project Gutenberg and GitHub on the connector kit.

Hermetic. The main paths replay responses recorded live once
(tests/data/fixtures/<source>_*.json; record again with
``E2ER_RECORD_FIXTURES=1``); listings whose answer is large (the World Bank's
and WHO's indicator lists, Eurostat's table of contents) and the failures are
mocked with respx. Pins, per source:
  - a load lands in data.db and is recorded (data_sources.json with terms,
    citation, query, version and SHA-256 of what was read; the data
    dictionary entry; the BibTeX entry in literature.bib);
  - what the terms require: the World Bank's and OWID's per-indicator licences
    are recorded; Eurostat's citation names the dataset's DOI and the
    customised extract; WHO GHO and GitHub data are reloaded, not shipped;
    Project Gutenberg texts are stored without the Project Gutenberg header,
    footer, licence and references, and come from PG's mirror, never from
    www.gutenberg.org; GitHub's token comes from GITHUB_TOKEN only;
  - refused requests and bad arguments exit non-zero and leave data.db alone.
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PID = "stats-lit-test"


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.modules.data.sources.http.PACING", False)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("E2ER_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    # The settings from the environment only: never a token from this machine's studies folder .env.
    from src import config

    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None))
    w = tmp_path / "ws" / PID
    w.mkdir(parents=True)
    return w


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = cli.main(["--paper-id", PID, *argv])
    return code, json.loads(capsys.readouterr().out)


def _load(ws: Path) -> dict:
    return json.loads((ws / "data_sources.json").read_text())["loads"][-1]


def _rows(ws: Path, table: str) -> int:
    with sqlite3.connect(ws / "data.db") as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _recorded(fixture: str, part: str) -> bytes:
    doc = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    [entry] = [e for e in doc["interactions"] if part in e["url"]]
    return entry["text"].encode("utf-8")


def _loaded_ok(ws: Path, out: dict, table: str, connector: str, cite_key: str) -> dict:
    assert out["error"] is None and out["row_count"] > 0, out
    assert out["saved_table"] == table and _rows(ws, table) == out["row_count"]
    assert out["recorded_in"] == ["data_sources.json", "data_dictionary.json"]
    load = _load(ws)
    assert load["connector"] == connector and load["table"] == table
    assert load["terms"] == get(connector).terms_url and load["citation"]
    [entry] = [t for t in json.loads((ws / "data_dictionary.json").read_text())["tables"] if t["name"] == table]
    assert entry["source"] == connector and entry["cite_key"] == cite_key
    assert f"{{{cite_key}," in (ws / "literature.bib").read_text()
    return load


# ── World Bank ───────────────────────────────────────────────────────────────


def test_worldbank_series_load_records_licences_version_and_hashes(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "worldbank_series.json"):
        code, out = _run(
            [
                "worldbank",
                "series",
                "--indicator",
                "NY.GDP.PCAP.CD,SP.POP.TOTL",
                "--countries",
                "DEU,FRA",
                "--start",
                "2020",
                "--end",
                "2022",
                "--table",
                "wb",
            ],
            capsys,
        )
    assert code == 0, out
    assert out["row_count"] == 12 and {r["iso3"] for r in out["items"]} == {"DEU", "FRA"}
    assert {r["year"] for r in out["items"]} == {2020, 2021, 2022}
    load = _loaded_ok(ws, out, "wb", "worldbank", "WorldBank_OpenData")
    assert load["version"] and load["frequency"] == "annual"
    assert load["indicator_licences"]["NY.GDP.PCAP.CD"]["licence"] == "CC BY-4.0"
    assert "World Development Indicators" in load["citation"] and "Licence: CC BY 4.0." in load["citation"]
    assert len(load["files"]) == 2
    assert (
        load["files"][0]["sha256"] == hashlib.sha256(_recorded("worldbank_series.json", "NY.GDP.PCAP.CD?")).hexdigest()
    )
    assert load["request"]["indicator"] == ["NY.GDP.PCAP.CD", "SP.POP.TOTL"]


@respx.mock
def test_worldbank_indicators_search_and_a_refused_request(ws: Path, capsys) -> None:
    respx.get("https://api.worldbank.org/v2/indicator").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"page": 1, "pages": 1, "total": 2},
                [
                    {"id": "NY.GDP.PCAP.CD", "name": "GDP per capita (current US$)", "source": {"value": "WDI"}},
                    {"id": "SP.POP.TOTL", "name": "Population, total", "source": {"value": "WDI"}},
                ],
            ],
        )
    )
    code, out = _run(["worldbank", "indicators", "--query", "gdp capita"], capsys)
    assert code == 0 and [r["indicator"] for r in out["items"]] == ["NY.GDP.PCAP.CD"]
    assert not (ws / "data_sources.json").exists()  # a listing is not recorded

    respx.get(url__regex=r"https://api\.worldbank\.org/v2/sources/2/series/NOPE/metadata.*").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "message": [
                        {"id": "120", "key": "Invalid value", "value": "The provided parameter value is not valid"}
                    ]
                }
            ],
        )
    )
    code, out = _run(["worldbank", "series", "--indicator", "NOPE", "--table", "x"], capsys)
    assert code == 4 and "refused the request" in out["error"] and "Invalid value" in out["error"]
    assert not (ws / "data.db").exists()


def test_worldbank_bad_arguments_make_no_request(ws: Path, capsys) -> None:
    with respx.mock(assert_all_called=False) as router:
        code, out = _run(["worldbank", "series", "--indicator", "X", "--start", "2020", "--end", "2010"], capsys)
        assert code == 4 and "is after" in out["error"] and not router.calls
        code, out = _run(["worldbank", "series", "--indicator", "a b"], capsys)
        assert code == 4 and "is not a code" in out["error"]


# ── Eurostat ─────────────────────────────────────────────────────────────────


def test_eurostat_data_by_nuts_region_records_doi_extract_and_hash(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "eurostat_data.json"):
        code, out = _run(
            [
                "eurostat",
                "data",
                "--dataset",
                "nama_10r_2gdp",
                "--filter",
                "unit=MIO_EUR,geo=DE1+DE2+FR10",
                "--start",
                "2021",
                "--end",
                "2022",
                "--table",
                "gdp_regions",
            ],
            capsys,
        )
    assert code == 0, out
    assert {r["geo"] for r in out["items"]} == {"DE1", "DE2", "FR10"} and out["row_count"] == 6
    row = out["items"][0]
    assert row["unit"] == "MIO_EUR" and row["geo_label"] and row["time"] in ("2021", "2022") and row["value"] > 0
    load = _loaded_ok(ws, out, "gdp_regions", "eurostat", "Eurostat_Database")
    assert load["doi"] == "https://doi.org/10.2908/NAMA_10R_2GDP"
    assert "Source: https://doi.org/10.2908/NAMA_10R_2GDP" in load["citation"]
    assert "Customised version: Source: https://ec.europa.eu/eurostat/api/" in load["citation"]
    assert load["version"] and load["frequency"] == "annual"
    [f] = load["files"]
    assert f["sha256"] == hashlib.sha256(_recorded("eurostat_data.json", "nama_10r_2gdp")).hexdigest()
    assert "geo=DE1&geo=DE2&geo=FR10" in load["query"]


@respx.mock
def test_eurostat_dataset_search_reads_the_table_of_contents(ws: Path, capsys) -> None:
    toc = (
        '"title"\t"code"\t"type"\t"last update of data"\t"last table structure change"\t"data start"\t'
        '"data end"\t"values"\n'
        '"Database by themes"\t"data"\t"folder"\t" "\t" "\t" "\t" "\t\n'
        '"    GDP at current market prices by NUTS 2 region"\t"nama_10r_2gdp"\t"dataset"\t"10.02.2026"\t'
        '"10.02.2026"\t"2000"\t"2024"\t75931\n'
        '"    Population on 1 January"\t"demo_pjan"\t"dataset"\t"01.03.2026"\t"01.03.2026"\t"1960"\t"2025"\t9\n'
    )
    route = respx.get("https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/txt").mock(
        return_value=httpx.Response(200, text=toc)
    )
    code, out = _run(["eurostat", "datasets", "--query", "gdp nuts"], capsys)
    assert code == 0 and [r["code"] for r in out["items"]] == ["nama_10r_2gdp"]
    assert out["items"][0]["title"].startswith("GDP") and out["items"][0]["values"] == 75931
    _run(["eurostat", "datasets", "--query", "population"], capsys)
    assert route.call_count == 1  # the day's table of contents is read once


@respx.mock
def test_eurostat_refusals_name_the_reason(ws: Path, capsys) -> None:
    base = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
    respx.get(f"{base}/nope_xx").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": [
                    {"status": 404, "id": 100, "label": "ERR_NOT_FOUND_4: NOPE_XX is not available for dissemination."}
                ]
            },
        )
    )
    respx.get(f"{base}/big_one").mock(
        return_value=httpx.Response(
            200,
            json={
                "warning": {
                    "status": 413,
                    "label": "ASYNCHRONOUS_RESPONSE. Your request will be treated asynchronously.",
                }
            },
        )
    )
    code, out = _run(["eurostat", "data", "--dataset", "nope_xx", "--table", "x"], capsys)
    assert code == 4 and "Eurostat refused the request" in out["error"] and "ERR_NOT_FOUND_4" in out["error"]
    code, out = _run(["eurostat", "data", "--dataset", "big_one", "--table", "x"], capsys)
    assert code == 4 and "only asynchronously" in out["error"] and "--filter" in out["error"]
    code, out = _run(
        [
            "eurostat",
            "data",
            "--dataset",
            "nama_10r_2gdp",
            "--filter",
            "geo=DE1",
            "--geo-level",
            "nuts2",
            "--table",
            "x",
        ],
        capsys,
    )
    assert code == 4 and "not both" in out["error"]
    assert not (ws / "data.db").exists()


def test_jsonstat_decoding_handles_gaps_and_flags() -> None:
    from src.modules.data.sources.eurostat import _decode

    doc = {
        "id": ["geo", "time"],
        "size": [2, 2],
        "value": {"0": 1.0, "3": 4.0},
        "status": {"1": "c"},
        "dimension": {
            "geo": {"category": {"index": {"AT": 0, "BE": 1}, "label": {"AT": "Austria", "BE": "Belgium"}}},
            "time": {"category": {"index": {"2020": 0, "2021": 1}}},
        },
    }
    assert _decode(doc) == [
        {"geo": "AT", "geo_label": "Austria", "time": "2020", "value": 1.0, "flag": None},
        {"geo": "AT", "geo_label": "Austria", "time": "2021", "value": None, "flag": "c"},
        {"geo": "BE", "geo_label": "Belgium", "time": "2021", "value": 4.0, "flag": None},
    ]


# ── Our World in Data ────────────────────────────────────────────────────────


def test_owid_chart_records_each_origin_licence_and_cites_producers(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "owid_chart.json"):
        code, out = _run(
            [
                "owid",
                "chart",
                "--chart",
                "literacy-rate-adults",
                "--entities",
                "DEU,India",
                "--start",
                "2000",
                "--table",
                "literacy",
            ],
            capsys,
        )
    assert code == 0, out
    assert {r["entity"] for r in out["items"]} <= {"Germany", "India"} and out["row_count"] > 0
    assert all(r["year"] >= 2000 for r in out["items"])
    load = _loaded_ok(ws, out, "literacy", "owid", "OWID")
    [(name, ind)] = load["indicators"].items()
    assert ind["origins"] and all(o["licence"] for o in ind["origins"])
    assert ind["non_redistributable"] is False and load["origin_licences"]
    assert "Our World in Data" in load["citation"] and "Retrieved" in load["citation"]
    assert load["link"] == "https://ourworldindata.org/grapher/literacy-rate-adults"
    [f] = load["files"]
    assert f["sha256"] == hashlib.sha256(_recorded("owid_chart.json", "literacy.csv")).hexdigest()
    assert name in out["items"][0]


def test_owid_search_lists_charts(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "owid_search.json"):
        code, out = _run(["owid", "search", "--query", "life expectancy", "--limit", "3"], capsys)
    assert code == 0 and out["items"][0]["slug"] == "life-expectancy" and len(out["items"]) == 3


@respx.mock
def test_owid_refuses_a_chart_marked_not_redistributable(ws: Path, capsys) -> None:
    respx.get("https://ourworldindata.org/grapher/closed.metadata.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "chart": {"title": "Closed"},
                "columns": {
                    "x": {
                        "titleShort": "X",
                        "fullMetadata": "https://api.ourworldindata.org/v1/indicators/1.metadata.json",
                    }
                },
            },
        )
    )
    respx.get("https://api.ourworldindata.org/v1/indicators/1.metadata.json").mock(
        return_value=httpx.Response(200, json={"nonRedistributable": True, "origins": []})
    )
    code, out = _run(["owid", "chart", "--chart", "closed", "--table", "x"], capsys)
    assert code == 4 and "not redistributable" in out["error"]
    assert not (ws / "data.db").exists()


# ── WHO Global Health Observatory ────────────────────────────────────────────


def test_who_gho_data_load_cites_who_and_is_reloaded_not_shipped(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "who_gho_data.json"):
        code, out = _run(
            [
                "who_gho",
                "data",
                "--indicator",
                "WHOSIS_000001",
                "--countries",
                "DEU,FRA",
                "--start",
                "2019",
                "--end",
                "2021",
                "--sex",
                "both",
                "--table",
                "life_exp",
            ],
            capsys,
        )
    assert code == 0, out
    assert out["row_count"] == 6 and {r["dim1"] for r in out["items"]} == {"SEX_BTSX"}
    assert all(r["low"] <= r["value"] <= r["high"] for r in out["items"])
    load = _loaded_ok(ws, out, "life_exp", "who_gho", "WHO_GHO")
    assert load["citation"].startswith("WHO, Global Health Observatory: Life expectancy at birth (years)")
    assert "(DEU, FRA)" in load["citation"] and load["version"]

    from src.core import data_terms
    from src.core.export import reproduce_recipe as rr

    terms = data_terms.known()["who_gho"]
    assert terms.zenodo_licence is None and "public health purposes" in terms.limit
    assert rr._reload_args(load)[0] == [
        "who_gho",
        "data",
        "--indicator",
        "WHOSIS_000001",
        "--countries",
        "DEU,FRA",
        "--start",
        "2019",
        "--end",
        "2021",
        "--sex",
        "both",
    ]


@respx.mock
def test_who_gho_indicator_search(ws: Path, capsys) -> None:
    respx.get("https://ghoapi.azureedge.net/api/Indicator").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"IndicatorCode": "WHOSIS_000001", "IndicatorName": "Life expectancy at birth (years)"},
                    {"IndicatorCode": "MDG_0000000001", "IndicatorName": "Infant mortality rate"},
                ]
            },
        )
    )
    code, out = _run(["who_gho", "indicators", "--query", "life expectancy"], capsys)
    assert code == 0 and out["items"] == [{"code": "WHOSIS_000001", "name": "Life expectancy at birth (years)"}]
    code, out = _run(["who_gho", "data", "--indicator", "WHOSIS_000001", "--countries", "Germany"], capsys)
    assert code == 4 and "ISO3" in out["error"]


# ── Project Gutenberg ────────────────────────────────────────────────────────


def test_gutenberg_text_is_stored_without_project_gutenberg_and_from_the_mirror(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "gutenberg_text.json") as cassette:
        code, out = _run(["gutenberg", "text", "--ids", "41", "--table", "texts"], capsys)
    assert code == 0, out
    hosts = {e["url"].split("/")[2] for e in cassette.entries}
    assert hosts == {"gutendex.com", "gutenberg.pglaf.org"}  # never www.gutenberg.org
    [row] = out["items"]
    assert row["id"] == 41 and row["title"].startswith("The Legend of Sleepy Hollow") and row["copyright"] is False
    assert "gutenberg" not in row["text"].lower() and row["words"] > 10000
    load = _loaded_ok(ws, out, "texts", "gutenberg", "ProjectGutenberg")
    info = load["stripped"]["41"]
    assert info["header_found"] and info["footer_found"] and info["characters_removed"] > 10000
    [f] = load["files"]
    assert f["url"] == "https://gutenberg.pglaf.org/cache/epub/41/pg41.txt"
    assert f["sha256"] == hashlib.sha256(_recorded("gutenberg_text.json", "pg41.txt")).hexdigest()
    assert "Urbana, Illinois: Project Gutenberg. Retrieved" in load["citation"]
    assert "www.gutenberg.org/ebooks/41." in load["citation"]


def test_gutenberg_books_catalogue(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "gutenberg_books.json"):
        code, out = _run(
            ["gutenberg", "books", "--search", "austen pride", "--languages", "en", "--limit", "3", "--table", "books"],
            capsys,
        )
    assert code == 0, out
    assert out["items"][0]["id"] == 1342 and out["items"][0]["authors"] == "Austen, Jane"
    _loaded_ok(ws, out, "books", "gutenberg", "ProjectGutenberg")


@respx.mock
def test_gutenberg_refuses_copyrighted_books_and_too_many(ws: Path, capsys) -> None:
    respx.get("https://gutendex.com/books/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": [{"id": 9, "title": "Recent", "authors": [], "copyright": True}],
            },
        )
    )
    code, out = _run(["gutenberg", "text", "--ids", "9", "--table", "t"], capsys)
    assert code == 4 and "still under copyright" in out["error"]
    code, out = _run(["gutenberg", "text", "--ids", ",".join(str(i) for i in range(1, 30))], capsys)
    assert code == 4 and "at most 20" in out["error"]
    assert not (ws / "data.db").exists()


def test_gutenberg_stripping() -> None:
    from src.modules.data.sources.gutenberg import strip_gutenberg

    raw = (
        "The Project Gutenberg eBook of X\r\nLicense blah\r\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK X ***\r\n\r\nChapter 1\r\nIt was a dark night.\r\n"
        "Transcribed for Project Gutenberg by someone.\r\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK X ***\r\nFull Project Gutenberg License\r\n"
    )
    text, info = strip_gutenberg(raw)
    assert text == "Chapter 1\nIt was a dark night.\n"
    assert info["header_found"] and info["footer_found"] and info["lines_naming_project_gutenberg_removed"] == 1


# ── GitHub ───────────────────────────────────────────────────────────────────


def test_github_search_repo_and_releases_load_metadata_only(ws: Path, capsys) -> None:
    with use_cassette(FIXTURES / "github_api.json"):
        code, out = _run(
            [
                "github",
                "repos",
                "--topic",
                "econometrics",
                "--language",
                "Python",
                "--min-stars",
                "50",
                "--sort",
                "stars",
                "--limit",
                "5",
                "--table",
                "repos",
            ],
            capsys,
        )
        assert code == 0, out
        assert len(out["items"]) == 5 and out["items"][0]["stars"] >= out["items"][-1]["stars"] >= 50
        load = _loaded_ok(ws, out, "repos", "github", "GitHub_RESTAPI")
        assert load["search"] == "topic:econometrics language:Python stars:>=50" and load["total_count"] >= 5

        code, out = _run(["github", "repo", "--repos", "statsmodels/statsmodels", "--table", "meta"], capsys)
        assert code == 0, out
        [row] = out["items"]
        assert row["full_name"] == "statsmodels/statsmodels" and row["contributors"] > 100
        assert row["languages"].startswith("Python:") and row["license"] == "BSD-3-Clause"
        assert not any("email" in k for k in row)

        code, out = _run(["github", "releases", "--repo", "statsmodels/statsmodels", "--table", "rel"], capsys)
        assert code == 0 and out["items"][0]["tag"]

    from src.core import data_terms

    assert "github" in data_terms.known() and data_terms.known()["github"].zenodo_licence is None


@respx.mock
def test_github_token_from_the_setting_only_and_rate_limit_advice(
    ws: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx.get("https://api.github.com/repos/a/b/releases").mock(
        return_value=httpx.Response(403, json={"message": "API rate limit exceeded for 1.2.3.4."})
    )
    code, out = _run(["github", "releases", "--repo", "a/b"], capsys)
    assert code == 4 and "rate limit is reached" in out["error"] and "set GITHUB_TOKEN" in out["error"]
    assert "Authorization" not in route.calls[0].request.headers

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")
    route.mock(return_value=httpx.Response(200, json=[]))
    code, out = _run(["github", "releases", "--repo", "a/b"], capsys)
    assert route.calls[-1].request.headers["Authorization"] == "Bearer ghp_secret123"
    assert code == 0 and "ghp_secret123" not in json.dumps(out)


def test_github_bad_repo_names(ws: Path, capsys) -> None:
    code, out = _run(["github", "repo", "--repos", "not-a-repo"], capsys)
    assert code == 4 and "owner/name" in out["error"]
    code, out = _run(["github", "repos", "--created-after", "2020"], capsys)
    assert code == 4 and "YYYY-MM-DD" in out["error"]


# ── every new source: doctor, planning catalogue, data architect ─────────────

NEW = ("worldbank", "eurostat", "owid", "who_gho", "gutenberg", "github")


def test_new_sources_are_offered_to_the_data_architect_and_the_planning_catalogue(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from src.core.specialists import data_sources as ds
    from src.modules.data.registry import series_fetchers

    settings = SimpleNamespace(fred_api_key=None, allium_api_key=None, github_token=None)
    block = ds.sources_block(tmp_path, settings)
    names = [f.name for f in series_fetchers(settings)]
    for n in NEW:
        assert f"`{n}`" in block and n in names
        assert get(n).doctor is not None
    assert ds._norm("World Bank") == "worldbank" and ds._norm("Our World in Data") == "owid"
    assert ds._norm("Project Gutenberg") == "gutenberg" and ds._norm("WHO") == "who_gho"


async def test_new_sources_doctor_checks_pass_on_recorded_answers() -> None:
    from src.doctor import PASS, source_checks

    with use_cassette(FIXTURES / "stats_lit_doctor.json"):
        checks = {c.name: c for c in await source_checks(None)}
    for n in NEW:
        check = checks[get(n).doctor.check]
        assert check.status == PASS, (n, check.detail)


# ── recorded fixtures: redirects and Link headers replay as they happened live ─


async def test_a_cassette_replays_redirects_and_link_headers(tmp_path: Path) -> None:
    from src.modules.data.sources import Polite
    from src.modules.data.sources.http import PoliteClient

    path = tmp_path / "rec.json"
    with respx.mock:
        respx.get("https://x.org/old").mock(return_value=httpx.Response(301, headers={"location": "https://x.org/new"}))
        respx.get("https://x.org/new").mock(
            return_value=httpx.Response(200, text="ok", headers={"link": '<https://x.org/new?page=7>; rel="last"'})
        )
        with use_cassette(path, record=True):
            async with PoliteClient("t", Polite()) as http:
                assert (await http.get("https://x.org/old")).text == "ok"
    with use_cassette(path):  # no network
        async with PoliteClient("t", Polite()) as http:
            resp = await http.get("https://x.org/old")
    assert resp.text == "ok" and resp.headers["link"] == '<https://x.org/new?page=7>; rel="last"'


def test_an_argument_named_like_e2er_datas_own_is_refused() -> None:
    from src.modules.data.sources import Arg, Operation, Source

    async def fetch(ctx, params):  # pragma: no cover
        raise AssertionError

    bad = Source(
        name="x",
        label="X",
        dataset="X",
        website="https://x.org",
        terms_url="https://x.org/t",
        terms_summary="t",
        licence="t",
        citation="c",
        citation_by="e2er",
        use="u",
        coverage="c",
        operations=(Operation("op", "h", args=(Arg("source", "s"),), fetch=fetch),),
    )
    assert any("e2er-data's own" in p for p in bad.validate())
