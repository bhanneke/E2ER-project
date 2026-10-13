"""ESA Gaia (`e2er-data gaia`): cone searches and ADQL queries on Gaia DR3 through the Gaia archive's TAP service.

Hermetic. The main path replays responses recorded live once from the
archive (tests/data/fixtures/gaia_*.json; record again with
``E2ER_RECORD_FIXTURES=1``); failures are mocked with respx. Pins:
  - `gaia cone --table` loads one row per source with its distance from the
    centre, records the ADQL, the release (DR3), the SHA-256 of the CSV read,
    the CC BY-NC 3.0 IGO terms and the citation of both Gaia papers, which go
    into literature.bib once;
  - the anonymous quota (50,000 rows) is never exceeded and a cone with more
    stars stops with advice instead of cutting the table;
  - a refused query (HTTP 400 with an error VOTable) reports the archive's
    message; bad coordinates and non-SELECT queries are refused before a
    request; data.db is untouched;
  - Gaia data are under terms: publishing asks for --accept-data-terms gaia, a
    Zenodo deposit takes a non-commercial licence, get_data.py reloads them;
  - the doctor check is one cheap request.
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
from src.modules.data.sources.gaia import ANON_MAX_ROWS, CITE_KEY, SERVICE
from src.modules.data.sources.http import use_cassette

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONE = FIXTURES / "gaia_cone_pleiades.json"
PID = "gaia-test"
ARGS = ["gaia", "cone", "--ra", "56.75", "--dec", "24.12", "--radius", "0.5", "--max-mag", "11"]


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


def test_a_cone_loads_a_table_and_records_adql_release_hash_terms_and_citation(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with use_cassette(CONE):
        code, out = _run([*ARGS, "--table", "pleiades"], capsys)
    assert code == 0, out
    assert out["error"] is None and out["row_count"] > 0 and out["version"] == "DR3"
    assert out["citation_added"] is True and out["cite_key"] == CITE_KEY
    rows = out["items"]
    assert all(r["phot_g_mean_mag"] < 11 and r["dist_deg"] <= 0.5 for r in rows)
    assert [r["source_id"] for r in rows] == sorted(r["source_id"] for r in rows)
    assert {"parallax", "pmra", "bp_rp", "ruwe"} <= set(rows[0])
    assert "parallax and parallax_error mas" in out["note"]

    with sqlite3.connect(ws / "data.db") as db:
        assert db.execute("SELECT COUNT(*) FROM pleiades").fetchone()[0] == out["row_count"]

    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "gaia" and load["version"] == "DR3"
    assert load["terms"] == "https://www.cosmos.esa.int/web/gaia-users/license"
    assert "CC BY-NC 3.0 IGO" in load["terms_summary"] and "commercial use" in load["licence"]
    assert "10.1051/0004-6361/202243940" in load["citation"] and "10.1051/0004-6361/201629272" in load["citation"]
    assert "CIRCLE('ICRS', 56.75, 24.12, 0.5)" in load["adql"] and "phot_g_mean_mag < 11.0" in load["adql"]
    assert load["query"].startswith(f"{SERVICE}/sync?") and f"MAXREC={ANON_MAX_ROWS}" in load["query"]
    doc = json.loads(CONE.read_text(encoding="utf-8"))
    [csv] = [e["text"] for e in doc["interactions"] if "/sync" in e["url"]]
    assert load["files"][0]["sha256"] == hashlib.sha256(csv.encode("utf-8")).hexdigest()
    assert load["request"]["ra"] == 56.75 and load["request"]["radius"] == 0.5

    bib = (ws / "literature.bib").read_text()
    assert bib.count("{GaiaDR3_Vallenari2023,") == 1 and bib.count("{GaiaMission_Prusti2016,") == 1


@respx.mock
def test_a_crowded_cone_stops_with_advice_instead_of_cutting_the_table(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def full(request: httpx.Request) -> httpx.Response:
        cap = int(request.url.params["MAXREC"])
        assert cap <= ANON_MAX_ROWS  # never more than the archive's anonymous quota
        return httpx.Response(200, text="source_id\n" + "".join(f"{i}\n" for i in range(cap)))

    respx.get(f"{SERVICE}/sync").mock(side_effect=full)
    code, out = _run(["gaia", "cone", "--ra", "266.4", "--dec", "-29.0", "--radius", "1", "--table", "bulge"], capsys)
    assert code == 4 and "set --max-mag" in out["error"]
    assert not (ws / "data.db").exists() and not (ws / "data_sources.json").exists()


@respx.mock
def test_a_refused_query_reports_the_archive_message(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    votable = (
        '<VOTABLE version="1.2"><RESOURCE type="results"><INFO name="QUERY_STATUS" value="ERROR">\n'
        "Cannot parse query 'SELECT nosuch FROM gaiadr3.gaia_source': 1 unresolved identifiers: nosuch !\n"
        '</INFO><INFO name="HttpErrorCode" value="400"/></RESOURCE></VOTABLE>'
    )
    respx.get(f"{SERVICE}/sync").mock(return_value=httpx.Response(400, text=votable))
    code, out = _run(["gaia", "query", "--adql", "SELECT nosuch FROM gaiadr3.gaia_source", "--table", "t"], capsys)
    assert code == 4 and "the TAP service refused the query" in out["error"]
    assert "1 unresolved identifiers: nosuch" in out["error"]
    assert not (ws / "data.db").exists()


@respx.mock
def test_a_query_records_the_release_it_names(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{SERVICE}/sync").mock(return_value=httpx.Response(200, text="source_id,parallax\n1,250.0\n"))
    code, out = _run(
        ["gaia", "query", "--adql", "SELECT TOP 5 source_id, parallax FROM gaiadr2.gaia_source", "--table", "t"],
        capsys,
    )
    assert code == 0 and out["version"] == "DR2"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["cone", "--ra", "400", "--dec", "0", "--radius", "1"], "0–360"),
        (["cone", "--ra", "10", "--dec", "-95", "--radius", "1"], "±90"),
        (["cone", "--ra", "10", "--dec", "0", "--radius", "30"], "at most 5.0"),
        (["cone", "--ra", "10", "--dec", "0", "--radius", "1", "--columns", "ra,x y"], "not column names"),
        (["cone", "--ra", "10", "--dec", "0", "--radius", "1", "--max-rows", "60000"], "anonymous limit"),
        (["query", "--adql", "DROP TABLE x"], "one ADQL SELECT"),
    ],
)
def test_a_bad_request_exits_non_zero_without_a_request(
    ws: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        code, out = _run(["gaia", *argv, "--table", "t"], capsys)
        assert not router.calls
    assert code == 4 and message in out["error"]
    assert not (ws / "data.db").exists()


def test_gaia_data_are_under_non_commercial_terms_and_reloaded() -> None:
    from src.core import data_terms
    from src.core.export import reproduce_recipe as rr

    terms = data_terms.known()["gaia"]
    assert terms.short == "Gaia" and terms.zenodo_licence == "other-nc" and terms.cite_key == CITE_KEY
    assert "non-commercial" in terms.limit and "CC BY-NC 3.0 IGO" in terms.confirm
    assert any("commercial use needs ESA's authorisation" in line for line in terms.plain)
    entry = {
        "connector": "gaia",
        "request": {"command": "cone", "ra": 56.75, "dec": 24.12, "radius": 0.5, "max_mag": 11.0},
    }
    assert rr._reload_args(entry) == (
        ["gaia", "cone", "--ra", "56.75", "--dec", "24.12", "--radius", "0.5", "--max-mag", "11.0"],
        "",
    )
    assert "gaia" in rr._restricted()


async def test_the_doctor_check_is_one_cheap_request() -> None:
    from src.doctor import PASS
    from src.modules.data.sources.runtime import doctor_check

    source = get("gaia")
    assert source is not None
    with use_cassette(FIXTURES / "gaia_doctor.json") as cassette:
        check = await doctor_check(source, None)
    assert check.name == "data.gaia.cone" and check.status == PASS
    assert "rows from ESA Gaia Archive" in check.detail and len(cassette.entries) == 1
