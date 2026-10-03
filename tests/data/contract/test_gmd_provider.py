"""Global Macro Database connector: listings, loads, records, failures.

Hermetic: every GMD file is mocked with respx; no network. Pins:
  - versions newest first; variables with units and definitions; countries
  - `series --table` loads a table with values, records the release, the
    URL and the SHA-256 of the file read (data_sources.json and the
    data dictionary entry, with the licence), and adds the GMD citation
  - the newest release is the default; the release used is always recorded
  - an unknown variable or country names the valid ones and exits non-zero
  - a failed download exits non-zero and leaves data.db untouched
  - the cache is keyed by release and re-hashed on use
  - export ships data_sources.json and the dossier lists the release and hash
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from src.modules.data import cli
from src.modules.data.gmd_provider import BASES, CITE_KEY, GMDProvider

S3, GH = BASES
PID = "gmd-test"

VERSIONS = "versions,version_package\n2026_03,2.0.0\n2026_09,2.0.0\n2026_06,2.0.0\n"
VARLIST = "variables,units,definition\nrGDP,millions of LC,Real Gross Domestic Product.\ninfl,in %,Inflation rate.\n"
PANEL = (
    "countryname,ISO3,id,year,rGDP,infl,forecast_rGDP,forecast_infl\n"
    "Germany,DEU,DEU,1999,2560000.0,,0,0\n"
    "Germany,DEU,DEU,2000,2601382.5,1.39,0,0\n"
    "Germany,DEU,DEU,2001,2647274.5,1.90,0,0\n"
    "Germany,DEU,DEU,2026,,,1,1\n"
    "United States,USA,USA,2000,13717681.0,3.37,0,0\n"
    "United States,USA,USA,2001,13853000.0,2.83,0,0\n"
    "France,FRA,FRA,2000,2000000.0,1.7,0,0\n"
)
PANEL_06 = PANEL.replace("2601382.5", "2600000.0")


def _countrylist() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"countryname": ["Germany", "United States"], "ISO3": ["DEU", "USA"]}).to_stata(buf, write_index=False)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("E2ER_CACHE_DIR", str(tmp_path / "cache"))
    ws = tmp_path / "ws" / PID
    ws.mkdir(parents=True)
    return ws


def _mock_helpers(router: respx.MockRouter) -> None:
    router.get(f"{S3}/helpers/versions.csv").mock(return_value=httpx.Response(200, text=VERSIONS))
    router.get(f"{S3}/helpers/varlist.csv").mock(return_value=httpx.Response(200, text=VARLIST))
    router.get(f"{S3}/helpers/countrylist.dta").mock(return_value=httpx.Response(200, content=_countrylist()))


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = cli.main(["--paper-id", PID, "gmd", *argv])
    out = capsys.readouterr().out
    return code, json.loads(out)


# ── listings ─────────────────────────────────────────────────────────────────


@respx.mock
def test_versions_are_listed_newest_first(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_helpers(respx.mock)
    code, out = _run(["versions"], capsys)
    assert code == 0
    assert [i["version"] for i in out["items"]] == ["2026_09", "2026_06", "2026_03"]
    assert out["latest"] == "2026_09"
    assert out["source_file"]["sha256"] == hashlib.sha256(VERSIONS.encode()).hexdigest()


@respx.mock
def test_variables_carry_units_and_definitions(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_helpers(respx.mock)
    code, out = _run(["variables"], capsys)
    assert code == 0
    assert out["items"][0] == {
        "variable": "rGDP",
        "units": "millions of LC",
        "definition": "Real Gross Domestic Product.",
    }
    assert len(out["items"]) == 2


@respx.mock
def test_countries_are_listed_by_iso3(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_helpers(respx.mock)
    code, out = _run(["countries"], capsys)
    assert code == 0
    assert out["items"] == [
        {"ISO3": "DEU", "countryname": "Germany"},
        {"ISO3": "USA", "countryname": "United States"},
    ]


@respx.mock
def test_helper_files_fall_back_to_github(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{S3}/helpers/versions.csv").mock(return_value=httpx.Response(403))
    respx.get(f"{GH}/helpers/versions.csv").mock(return_value=httpx.Response(200, text=VERSIONS))
    code, out = _run(["versions"], capsys)
    assert code == 0 and out["source_file"]["url"] == f"{GH}/helpers/versions.csv"


# ── series loads ─────────────────────────────────────────────────────────────


@respx.mock
def test_series_loads_a_table_and_records_release_url_hash_licence_and_citation(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_helpers(respx.mock)
    panel = respx.get(f"{S3}/distribute/GMD_2026_09.csv").mock(return_value=httpx.Response(200, text=PANEL))
    (env / "data_dictionary.json").write_text(
        json.dumps({"tables": [{"name": "gmd_macro", "source": "gmd", "role": "macro controls"}]})
    )
    (env / "literature.bib").write_text("@article{smith2020,\n  title = {A},\n  year = {2020}\n}\n")

    code, out = _run(
        [
            "series",
            "--variables",
            "rGDP,infl",
            "--countries",
            "USA,DEU",
            "--start",
            "2000",
            "--end",
            "2030",
            "--table",
            "gmd_macro",
        ],
        capsys,
    )
    assert code == 0, out
    assert out["version"] == "2026_09" and out["saved_table_rows"] == 4
    sha = hashlib.sha256(PANEL.encode()).hexdigest()

    con = sqlite3.connect(env / "data.db")
    rows = con.execute("SELECT ISO3, year, rGDP, infl, forecast_rGDP FROM gmd_macro ORDER BY ISO3, year").fetchall()
    con.close()
    # 1999 is before --start; DEU 2026 has no value of either variable and is dropped; FRA was not asked for.
    assert rows == [
        ("DEU", 2000, 2601382.5, 1.39, 0),
        ("DEU", 2001, 2647274.5, 1.90, 0),
        ("USA", 2000, 13717681.0, 3.37, 0),
        ("USA", 2001, 13853000.0, 2.83, 0),
    ]

    [load] = json.loads((env / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "gmd" and load["version"] == "2026_09"
    assert load["version_chosen"] == "latest release in helpers/versions.csv"
    assert load["files"][0]["url"] == f"{S3}/distribute/GMD_2026_09.csv"
    assert load["files"][0]["sha256"] == sha
    assert load["table"] == "gmd_macro" and load["variables"] == ["rGDP", "infl"]
    assert load["versions_file"]["url"] == f"{S3}/helpers/versions.csv"

    [entry] = json.loads((env / "data_dictionary.json").read_text())["tables"]
    assert entry["role"] == "macro controls"  # what the data architect wrote is kept
    assert entry["version"] == "2026_09" and entry["source_files"] == [{"url": load["files"][0]["url"], "sha256": sha}]
    assert "free for academic use" in entry["licence"] and entry["cite_key"] == CITE_KEY

    bib = (env / "literature.bib").read_text()
    assert "@article{smith2020," in bib and "@techreport{GMD2025," in bib
    assert "doi         = {10.3386/w33714}" in bib
    assert out["citation_added"] is True

    # A second load uses the cache (no new download), re-hashes it, and adds no second citation.
    code, out = _run(["series", "--variables", "rGDP", "--countries", "USA", "--table", "gmd_macro"], capsys)
    assert code == 0 and panel.call_count == 1
    assert out["provenance"]["files"][0]["from_cache"] is True and out["provenance"]["files"][0]["sha256"] == sha
    assert out["citation_added"] is False and bib == (env / "literature.bib").read_text()
    assert len(json.loads((env / "data_sources.json").read_text())["loads"]) == 1  # same table: replaced


@respx.mock
def test_a_requested_release_is_used_and_recorded(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_helpers(respx.mock)
    respx.get(f"{S3}/distribute/GMD_2026_06.csv").mock(return_value=httpx.Response(200, text=PANEL_06))
    code, out = _run(
        [
            "series",
            "--variables",
            "rGDP",
            "--countries",
            "DEU",
            "--version",
            "2026_06",
            "--start",
            "2000",
            "--end",
            "2000",
            "--table",
            "deu",
        ],
        capsys,
    )
    assert code == 0
    assert out["items"][0]["rGDP"] == 2600000.0
    [load] = json.loads((env / "data_sources.json").read_text())["loads"]
    assert load["version"] == "2026_06" and load["version_chosen"] == "requested"
    assert load["files"][0]["sha256"] == hashlib.sha256(PANEL_06.encode()).hexdigest()


@respx.mock
def test_unknown_release_lists_the_releases(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_helpers(respx.mock)
    code, out = _run(["series", "--variables", "rGDP", "--version", "2019_01", "--table", "x"], capsys)
    assert code == 4
    assert "2019_01" in out["error"] and "2026_09, 2026_06, 2026_03" in out["error"]
    assert not (env / "data.db").exists()


@respx.mock
def test_unknown_variable_names_the_valid_ones_and_changes_nothing(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_helpers(respx.mock)
    respx.get(f"{S3}/distribute/GMD_2026_09.csv").mock(return_value=httpx.Response(200, text=PANEL))
    code, out = _run(["series", "--variables", "rGDP,GDPX", "--table", "gmd_macro"], capsys)
    assert code == 4
    assert "unknown GMD variable(s) GDPX" in out["error"] and "valid variables: rGDP, infl" in out["error"]
    assert "was not created or changed" in out["table_error"]
    assert not (env / "data.db").exists() and not (env / "data_sources.json").exists()
    assert not (env / "literature.bib").exists()


@respx.mock
def test_unknown_country_names_the_valid_ones(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_helpers(respx.mock)
    respx.get(f"{S3}/distribute/GMD_2026_09.csv").mock(return_value=httpx.Response(200, text=PANEL))
    code, out = _run(["series", "--variables", "rGDP", "--countries", "USA,XYZ"], capsys)
    assert code == 4
    assert "unknown ISO3 code(s) XYZ" in out["error"] and "valid codes: DEU, FRA, USA" in out["error"]


@respx.mock
def test_failed_download_exits_non_zero_and_leaves_data_db_untouched(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    con = sqlite3.connect(env / "data.db")
    con.execute("CREATE TABLE gmd_macro (ISO3 TEXT, year INT, rGDP REAL)")
    con.execute("INSERT INTO gmd_macro VALUES ('USA', 2000, 1.0)")
    con.commit()
    con.close()
    before = (env / "data.db").read_bytes()

    _mock_helpers(respx.mock)
    respx.get(f"{S3}/distribute/GMD_2026_09.csv").mock(return_value=httpx.Response(503))
    code, out = _run(["series", "--variables", "rGDP", "--table", "gmd_macro"], capsys)
    assert code == 4
    assert "HTTP 503" in out["error"] and out["version"] == "2026_09"
    assert (env / "data.db").read_bytes() == before
    assert not list((env.parent.parent / "cache").rglob("*.csv"))  # no partial file is cached


@respx.mock
def test_unreachable_release_list_fails_loudly(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{S3}/helpers/versions.csv").mock(side_effect=httpx.ConnectError("offline"))
    respx.get(f"{GH}/helpers/versions.csv").mock(side_effect=httpx.ConnectError("offline"))
    code, out = _run(["series", "--variables", "rGDP", "--table", "gmd_macro"], capsys)
    assert code == 4 and "could not read the list of GMD releases" in out["error"]
    assert not (env / "data.db").exists()


@respx.mock
def test_a_corrupted_cache_is_downloaded_again(tmp_path: Path) -> None:
    import asyncio

    _mock_helpers(respx.mock)
    route = respx.get(f"{S3}/distribute/GMD_2026_09.csv").mock(return_value=httpx.Response(200, text=PANEL))
    p = GMDProvider(cache_dir=tmp_path)
    asyncio.run(p.series(["rGDP"]))
    (tmp_path / "2026_09" / "GMD_2026_09.csv").write_text(PANEL.replace("2601382.5", "9"))
    out = asyncio.run(p.series(["rGDP"], countries=["DEU"], start=2000, end=2000))
    assert route.call_count == 2 and out["items"][0]["rGDP"] == 2601382.5


# ── export and dossier ───────────────────────────────────────────────────────


def test_dossier_lists_the_release_and_file_hash(tmp_path: Path) -> None:
    from src.core.dossier import _data_sources

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data_sources.json").write_text(
        json.dumps(
            {
                "loads": [
                    {
                        "connector": "gmd",
                        "dataset": "Global Macro Database",
                        "version": "2026_09",
                        "table": "gmd_macro",
                        "cite_key": "GMD2025",
                        "licence": "long text not copied",
                        "files": [{"url": "https://x/GMD_2026_09.csv", "sha256": "a" * 64, "bytes": 3}],
                    }
                ]
            }
        )
    )
    assert _data_sources(tmp_path) == [
        {
            "connector": "gmd",
            "dataset": "Global Macro Database",
            "version": "2026_09",
            "table": "gmd_macro",
            "cite_key": "GMD2025",
            "files": [{"url": "https://x/GMD_2026_09.csv", "sha256": "a" * 64}],
        }
    ]
    assert _data_sources(tmp_path / "nothing") == []


def test_export_ships_data_sources_json() -> None:
    from src.core.export.structured import EXPORT_MAP

    assert ("data_sources.json", None) in EXPORT_MAP["data"]


def test_gmd_is_in_the_catalog_without_a_key() -> None:
    from types import SimpleNamespace

    from src.modules.data.registry import data_catalog

    cards = {c["name"]: c for c in data_catalog(SimpleNamespace(fred_api_key=None, allium_api_key=None))}  # type: ignore[arg-type]
    assert cards["gmd"]["requires"] == "(none)" and "series" in cards["gmd"]["methods"]
