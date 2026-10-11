"""NASA Exoplanet Archive (`e2er-data exoplanets`): planets and ADQL queries through the archive's TAP service.

Hermetic. The main path replays responses recorded live once from the TAP
service (tests/data/fixtures/exoplanets_*.json; record again with
``E2ER_RECORD_FIXTURES=1``); failures are mocked with respx. Pins:
  - `exoplanets planets --table` loads one row per planet from pscomppars,
    records the ADQL, the TAP URL, the table DOI, the SHA-256 of the CSV read,
    the terms (acknowledgement, no licence stated) and the citation, and adds
    the archive's BibTeX entries once;
  - `--catalogue ps` keeps one solution per planet (default_flag = 1);
  - `query` runs one ADQL SELECT; anything else is refused before a request;
  - a refused query reports the archive's message; a result above the row
    cap stops the load instead of cutting the table; data.db is untouched;
  - fetch_data records the same load; the doctor check is one cheap request;
  - the data may be published: no terms gate.
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
from src.modules.data.sources.exoplanets import CITE_KEY, SERVICE
from src.modules.data.sources.http import use_cassette

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PLANETS = FIXTURES / "exoplanets_planets.json"
PID = "exo-test"
ARGS = [
    "exoplanets",
    "planets",
    "--since",
    "2024",
    "--until",
    "2024",
    "--method",
    "Imaging",
    "--columns",
    "pl_name,hostname,pl_orbsmax,pl_bmasse,disc_year",
]


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


def _recorded(path: Path, needle: str) -> bytes:
    doc = json.loads(path.read_text(encoding="utf-8"))
    [entry] = [e for e in doc["interactions"] if needle in e["url"]]
    return entry["text"].encode("utf-8")


def test_planets_load_a_table_and_record_adql_doi_hash_terms_and_citation(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with use_cassette(PLANETS):
        code, out = _run([*ARGS, "--table", "imaged", "--save-to", "imaged.csv"], capsys)
    assert code == 0, out
    assert out["error"] is None and out["row_count"] > 0
    assert out["saved_table"] == "imaged" and out["saved_table_rows"] == out["row_count"]
    assert out["citation_added"] is True and out["cite_key"] == CITE_KEY
    assert all(r["disc_year"] == 2024 for r in out["items"])
    names = [r["pl_name"] for r in out["items"]]
    assert names == sorted(names) and len(set(names)) == len(names)
    assert "Earth radii" in out["note"] and "pl_orbper days" in out["note"]

    with sqlite3.connect(ws / "data.db") as db:
        assert db.execute("SELECT COUNT(*) FROM imaged").fetchone()[0] == out["row_count"]
    assert (ws / "data" / "imaged.csv").is_file()

    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "exoplanets" and load["table"] == "imaged"
    assert load["terms"] == "https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html"
    assert "states no licence" in load["terms_summary"]
    assert "No licence stated" in load["licence"] and "Exoplanet Exploration Program" in load["licence"]
    assert load["citation_by"] == "source" and "10.3847/PSJ/ade3c2" in load["citation"]
    assert load["adql"] == (
        "select pl_name, hostname, pl_orbsmax, pl_bmasse, disc_year from pscomppars where disc_year >= 2024 "
        "and disc_year <= 2024 and discoverymethod = 'Imaging' order by pl_name"
    )
    assert load["query"].startswith(f"{SERVICE}/sync?") and "MAXREC=100001" in load["query"]
    assert load["table_doi"] == "10.26133/NEA13"
    [f] = load["files"]
    assert f["sha256"] == hashlib.sha256(_recorded(PLANETS, "/TAP/sync")).hexdigest()

    [entry] = json.loads((ws / "data_dictionary.json").read_text())["tables"]
    assert entry["source"] == "exoplanets" and entry["cite_key"] == CITE_KEY

    bib = (ws / "literature.bib").read_text()
    for key in (CITE_KEY, "NEA_PSCompPars", "NEA_PS"):
        assert bib.count(f"{{{key},") == 1
    with use_cassette(PLANETS):
        code, out = _run([*ARGS, "--table", "imaged2"], capsys)
    assert code == 0 and out["citation_added"] is False
    assert (ws / "literature.bib").read_text().count(f"{{{CITE_KEY},") == 1


@respx.mock
def test_the_ps_table_keeps_one_solution_per_planet(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    route = respx.get(f"{SERVICE}/sync").mock(
        return_value=httpx.Response(200, text='pl_name,pl_rade\n"A b",1.0\n', headers={"content-type": "text/csv"})
    )
    code, out = _run(["exoplanets", "planets", "--catalogue", "ps", "--columns", "pl_name,pl_rade"], capsys)
    assert code == 0, out
    query = route.calls[0].request.url.params["QUERY"]
    assert query == "select pl_name, pl_rade from ps where default_flag = 1 order by pl_name"
    code, out = _run(["exoplanets", "planets", "--catalogue", "ps", "--all-solutions", "--columns", "pl_name"], capsys)
    assert "default_flag" not in route.calls[1].request.url.params["QUERY"]


@respx.mock
def test_query_runs_one_adql_select(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    route = respx.get(f"{SERVICE}/sync").mock(
        return_value=httpx.Response(200, text="n\n6445\n", headers={"content-type": "text/csv"})
    )
    code, out = _run(
        ["exoplanets", "query", "--adql", "select count(*) as n from pscomppars", "--table", "count"], capsys
    )
    assert code == 0, out
    assert out["items"] == [{"n": 6445}]
    assert route.calls[0].request.url.params["MAXREC"] == "100001"
    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["adql"] == "select count(*) as n from pscomppars" and load["table_doi"] == "10.26133/NEA13"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["query", "--adql", "delete from ps"], "one ADQL SELECT"),
        (["query", "--adql", "select 1 from ps; select 2 from ps"], "one query"),
        (["planets", "--columns", "pl_name,1bad"], "not column names"),
        (["planets", "--where", "pl_rade < 2; drop"], "one ADQL condition"),
        (["planets", "--max-rows", "0"], "--max-rows"),
    ],
)
def test_a_bad_request_exits_non_zero_without_a_request(
    ws: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        code, out = _run(["exoplanets", *argv, "--table", "t"], capsys)
        assert not router.calls
    assert code == 4 and message in out["error"]
    assert not (ws / "data.db").exists()


@respx.mock
def test_a_refused_query_reports_the_archive_message(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    votable = (
        '<?xml version="1.0"?><VOTABLE version="1.4"><RESOURCE type="results">'
        '<INFO name="QUERY_STATUS" value="ERROR">ORA-00904: "NOSUCH": invalid identifier</INFO>'
        "</RESOURCE></VOTABLE>"
    )
    respx.get(f"{SERVICE}/sync").mock(return_value=httpx.Response(200, text=votable))
    code, out = _run(["exoplanets", "query", "--adql", "select nosuch from ps", "--table", "t"], capsys)
    assert code == 4 and 'ORA-00904: "NOSUCH": invalid identifier' in out["error"]
    assert not (ws / "data.db").exists() and not (ws / "data_sources.json").exists()


@respx.mock
def test_a_result_above_the_cap_stops_instead_of_cutting_the_table(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = "pl_name\n" + "".join(f"P{i}\n" for i in range(4))
    respx.get(f"{SERVICE}/sync").mock(return_value=httpx.Response(200, text=rows))
    code, out = _run(["exoplanets", "planets", "--columns", "pl_name", "--max-rows", "3", "--table", "t"], capsys)
    assert code == 4 and "more than 3 rows" in out["error"] and "would be cut" in out["error"]
    assert not (ws / "data.db").exists()


async def test_fetch_data_records_the_same_load(ws: Path) -> None:
    from src.modules.data.discovery_tools import SeriesDataToolHandler

    handler = SeriesDataToolHandler(ws)
    with use_cassette(PLANETS):
        out = json.loads(
            await handler.handle(
                "fetch_data",
                {
                    "provider": "exoplanets",
                    "method": "planets",
                    "params": {
                        "since": 2024,
                        "until": 2024,
                        "method": "Imaging",
                        "columns": "pl_name,hostname,pl_orbsmax,pl_bmasse,disc_year",
                    },
                    "materialize": True,
                    "table": "imaged",
                },
            )
        )
    assert out["error"] is None and out["items"] and out["recorded_in"] == ["data_sources.json"]
    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "exoplanets" and load["table"] == "imaged" and load["files"]


async def test_the_doctor_check_is_one_cheap_request() -> None:
    from src.doctor import PASS
    from src.modules.data.sources.runtime import doctor_check

    source = get("exoplanets")
    assert source is not None
    with use_cassette(FIXTURES / "exoplanets_doctor.json") as cassette:
        check = await doctor_check(source, None)
    assert check.name == "data.exoplanets.planets" and check.status == PASS
    assert "rows from NASA Exoplanet Archive" in check.detail and len(cassette.entries) == 1


def test_exoplanet_data_may_be_published() -> None:
    from src.core import data_terms

    source = get("exoplanets")
    assert source is not None and source.redistribution and source.key is None
    assert "exoplanets" not in data_terms.known()
