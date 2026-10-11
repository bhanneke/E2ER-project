"""The connector kit: one definition per source, everything else derived from it.

Hermetic (respx, recorded fixtures; no live calls). Pins:
  - every definition is valid and wired in everywhere: e2er-data subcommands,
    the planning catalogue, the data architect's sources and aliases, the
    standalone check's loading commands, the labels, the skill files, the
    specialists that read them, the README table;
  - a source whose data a study may not pass on gets its data_terms entry and
    a get_data.py reload derived from its definition;
  - a keyed source without its key says how to get one, and is not offered;
  - the polite client: User-Agent, retry after 429 with Retry-After, the
    request budget, errors that name the URL and status;
  - the adapters: REST JSON paging (page, offset, next link), TAP/ADQL, CSV
    and ZIP download cached by version and re-hashed, SDMX-CSV;
  - recorded fixtures: record once, replay offline, an unrecorded request fails.
"""

from __future__ import annotations

import ast
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from src.modules.data import cli
from src.modules.data.sources import (
    Arg,
    Fetched,
    FetchError,
    Key,
    Operation,
    Polite,
    Restricted,
    Source,
    adapters,
    all_sources,
    get,
    names,
    register,
    unregister,
)
from src.modules.data.sources.docs import END, START, readme_block, skill_stub
from src.modules.data.sources.http import PoliteClient, use_cassette, user_agent
from src.modules.data.sources.runtime import KitFetcher, reload_args, run_operation

REPO = Path(__file__).resolve().parents[3]
PID = "kit-test"


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


def _settings(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(fred_api_key=None, allium_api_key=None, **kw)


# ── a fake source, built the way a new one is ────────────────────────────────

API = "https://api.example.org/v1"


async def _fetch_obs(ctx: Any, params: dict[str, Any]) -> Fetched:
    rows, urls = await adapters.rest_json_pages(
        ctx.http, f"{API}/obs", {"series": params["series"]}, items="results", paging="next", next_link="next"
    )
    return Fetched(rows=rows, series=f"series {params['series']}", query=urls[0], version="v3")


def _fake(**kw: Any) -> Source:
    base = dict(
        name="fakestat",
        label="Fake Statistics Office",
        dataset="Fake Statistics Office open data",
        website="https://example.org",
        terms_url="https://example.org/terms",
        terms_summary="Free for research; the data may not be republished.",
        licence="Example terms (https://example.org/terms): research use only; do not republish.",
        citation="Fake Statistics Office (2026). Open data. https://example.org",
        citation_by="source",
        bibtex="@misc{FakeStat2026,\n  title = {Open data},\n  year = {2026}\n}",
        cite_key="FakeStat2026",
        use="Fake observations for tests.",
        coverage="Fake observations",
        operations=(
            Operation(
                "obs",
                "Observations of one series.",
                args=(
                    Arg("series", "Series code.", required=True),
                    Arg("countries", "ISO3 codes.", type="list"),
                    Arg("annual", "Annual values only.", type="flag"),
                ),
                fetch=_fetch_obs,
            ),
        ),
        redistribution=False,
        restricted=Restricted(short="FSO", zenodo_licence=None, no_zenodo_why="the terms forbid republishing"),
        aliases=("fake_statistics_office",),
        skill="data/fakestat",
    )
    base.update(kw)
    return Source(**base)  # type: ignore[arg-type]


@pytest.fixture
def fake() -> Any:
    source = _fake()
    register(source)
    yield source
    unregister(source.name)


# ── the registry and what is derived from it ─────────────────────────────────


def test_every_definition_is_valid_and_named_once() -> None:
    sources = all_sources()
    assert [s.name for s in sources][:4] == ["yfinance", "fred", "gmd", "usgs"]
    assert len(set(names())) == len(sources)
    for s in sources:
        assert s.validate() == [], s.name


def test_every_source_has_its_skill_file_read_by_the_data_specialists() -> None:
    from src.core.specialists.registry import SPECIALIST_SKILLS

    for s in all_sources():
        assert (REPO / "skills" / "files" / f"{s.skill}.md").is_file(), s.skill
        assert s.skill in SPECIALIST_SKILLS["data_architect"] and s.skill in SPECIALIST_SKILLS["data_analyst"]


def test_every_source_is_a_subcommand_with_its_operations() -> None:
    parser = cli._build_parser()
    dispatch = cli._dispatch()
    for s in all_sources():
        assert set(dispatch[s.name]) == {op.name for op in s.operations}
        for op in s.operations:
            required = [x for a in op.args if a.required for x in (f"--{a.name}", "v")]
            ns = parser.parse_args([s.name, op.name, *required])
            assert ns.source == s.name and ns.command == op.name
            if op.loads:
                assert hasattr(ns, "table") and hasattr(ns, "save_to")
            else:
                assert not hasattr(ns, "table")


def test_the_data_architect_may_declare_every_source_by_name_or_alias(tmp_path: Path) -> None:
    from src.core.specialists import data_sources as ds

    connectors = ds._connectors()
    for s in all_sources():
        assert s.name in connectors
        for alias in s.aliases:
            assert ds._norm(alias) == s.name
    assert ds._norm("USGS Earthquakes") == "usgs" and ds._norm("ComCat") == "usgs"
    block = ds.sources_block(tmp_path, _settings())
    assert "- `usgs` (no key needed)" in block


def test_the_standalone_check_treats_every_source_as_loading_data() -> None:
    from src.core.specialists import standalone_check as sc

    for s in all_sources():
        call = ast.parse(f'subprocess.run([E2ER, "{s.name}", "x"])').body[0].value  # type: ignore[attr-defined]
        assert sc._argv_of(call)[:2] == ["e2er-data", s.name]


def test_labels_name_every_source_and_its_doctor_check() -> None:
    from src.core import labels

    for s in all_sources():
        assert labels.data_connector(s.name) == labels.DATA_CONNECTORS[s.name]
        if s.doctor:
            assert s.doctor.check in labels.CHECKS
    assert labels.CHECKS["data.usgs.events"] == "USGS Earthquake Catalog"
    assert labels.check_detail("data.usgs.events", "ConnectError: x").startswith(
        "USGS Earthquake Catalog could not be reached"
    )


def test_the_readme_lists_every_source() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    block = readme[readme.index(START) : readme.index(END) + len(END)]
    assert block == readme_block(all_sources()), "run scripts/gen_sources.py"
    for s in all_sources():
        assert f"| {s.label}" in block


def test_a_skill_stub_is_written_from_the_definition(fake: Source) -> None:
    stub = skill_stub(fake)
    assert stub.startswith("# Fake Statistics Office via `e2er-data fakestat`")
    assert "e2er-data fakestat obs --series <series>" in stub
    assert "https://example.org/terms" in stub and "may not pass these data on" in stub
    assert "`FakeStat2026`" in stub and "- `--countries`: ISO3 codes." in stub


# ── a new source end to end ──────────────────────────────────────────────────


def _mock_obs(router: respx.MockRouter) -> None:
    router.get(f"{API}/obs", params={"series": "GDP"}).mock(
        return_value=httpx.Response(200, json={"results": [{"year": 2020, "v": 1.5}], "next": f"{API}/obs?page=2"})
    )
    router.get(f"{API}/obs", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json={"results": [{"year": 2021, "v": None}], "next": None})
    )


@respx.mock
def test_a_new_source_loads_records_and_cites(ws: Path, fake: Source, capsys: pytest.CaptureFixture[str]) -> None:
    _mock_obs(respx.mock)
    code = cli.main(["--paper-id", PID, "fakestat", "obs", "--series", "GDP", "--countries", "DEU,FRA", "--annual",
                     "--table", "gdp"])  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out
    assert out["items"] == [{"year": 2020, "v": 1.5}, {"year": 2021, "v": None}]
    assert out["recorded_in"] == ["data_sources.json", "data_dictionary.json"] and out["citation_added"] is True
    [load] = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert load["connector"] == "fakestat" and load["version"] == "v3" and load["cite_key"] == "FakeStat2026"
    assert load["request"] == {"command": "obs", "series": "GDP", "countries": ["DEU", "FRA"], "annual": True}
    assert load["query"] == f"{API}/obs?series=GDP"
    [entry] = json.loads((ws / "data_dictionary.json").read_text())["tables"]
    assert entry["source"] == "fakestat" and entry["version"] == "v3"
    assert "@misc{FakeStat2026," in (ws / "literature.bib").read_text()


def test_a_source_whose_data_may_not_be_passed_on_gets_terms_and_a_reload(fake: Source) -> None:
    from src.core import data_terms
    from src.core.export import reproduce_recipe as rr

    terms = data_terms.known()["fakestat"]
    assert terms.short == "FSO" and terms.zenodo_licence is None and terms.cite_key == "FakeStat2026"
    assert terms.plain == (fake.terms_summary,) and terms.terms_url == fake.terms_url
    assert data_terms.unknown_names(["fakestat"]) == []
    entry = {"connector": "fakestat", "request": {"command": "obs", "series": "GDP", "countries": ["DEU"],
                                                  "annual": True}}  # fmt: skip
    assert rr._reload_args(entry) == (
        ["fakestat", "obs", "--series", "GDP", "--countries", "DEU", "--annual"],
        "",
    )
    assert reload_args(fake, {"connector": "fakestat"}) is None
    assert "fakestat" in rr._restricted()


def test_a_keyed_source_without_its_key_says_how_to_get_one(
    ws: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FAKE_KEY", raising=False)
    keyed = _fake(
        name="fakekeyed",
        key=Key(setting="fake_key", env="FAKE_KEY", how_to_get="Get one at https://example.org/key."),
        redistribution=True,
        restricted=None,
        aliases=(),
    )
    register(keyed)
    try:
        from src.core.specialists import data_sources as ds
        from src.modules.data.registry import series_fetchers

        assert "fakekeyed" not in [f.name for f in series_fetchers(_settings())]
        assert ds._connectors()["fakekeyed"] == ("fake_key", "FAKE_KEY")
        assert "not available: `fakekeyed` (needs FAKE_KEY" in ds.sources_block(ws, _settings())
        code = cli.main(["--paper-id", PID, "fakekeyed", "obs", "--series", "GDP"])
        out = json.loads(capsys.readouterr().out)
        assert code == 4 and out["error"] == "FAKE_KEY not configured. Get one at https://example.org/key."
        monkeypatch.setenv("FAKE_KEY", "secret")
        assert "fakekeyed" in [f.name for f in series_fetchers(_settings())]
    finally:
        unregister("fakekeyed")


async def test_the_planning_card_and_fetch_data_come_from_the_definition(fake: Source) -> None:
    fetcher = KitFetcher(fake, _settings())
    card = fetcher.card()
    assert card["name"] == "fakestat" and card["requires"] == "(none)" and "obs" in card["methods"]
    assert "series (str, required)" in card["methods"]["obs"]
    assert "unknown method" in (await fetcher.fetch("nope", {}))["error"]
    with pytest.raises(KeyError):
        await fetcher.fetch("obs", {})


async def test_a_connector_bug_is_an_error_envelope_not_an_exception(fake: Source) -> None:
    async def boom(ctx: Any, params: dict[str, Any]) -> Fetched:
        raise ZeroDivisionError("oops")

    broken = _fake(operations=(Operation("obs", "x", fetch=boom),))
    env = await run_operation(broken, broken.operations[0], {}, _settings())
    assert env["error"] == "ZeroDivisionError: oops" and env["items"] == []


def test_an_invalid_definition_is_refused() -> None:
    with pytest.raises(ValueError, match="redistribution=False needs `restricted`"):
        register(_fake(name="bad", restricted=None))
    with pytest.raises(ValueError, match="exactly one of fetch"):
        register(_fake(name="bad2", operations=(Operation("x", "x"),)))
    assert get("bad") is None


# ── the polite client ────────────────────────────────────────────────────────


@respx.mock
async def test_the_client_names_e2er_retries_429_and_reports_the_status() -> None:
    route = respx.get("https://x.org/a").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={"ok": 1})]
    )
    respx.get("https://x.org/b").mock(return_value=httpx.Response(404, text="no such series"))
    async with PoliteClient("t", Polite(retries=1)) as http:
        assert await http.get_json("https://x.org/a") == {"ok": 1}
        with pytest.raises(FetchError, match=r"https://x.org/b: HTTP 404: no such series"):
            await http.get("https://x.org/b")
    assert route.call_count == 2
    assert route.calls[0].request.headers["User-Agent"] == user_agent() and "e2er/" in user_agent()


@respx.mock
async def test_the_client_stops_a_runaway_operation() -> None:
    respx.get("https://x.org/p").mock(
        return_value=httpx.Response(200, json={"r": [{"a": 1}], "next": "https://x.org/p"})
    )
    async with PoliteClient("t", Polite(max_requests=3)) as http:
        with pytest.raises(FetchError, match="more than 3 requests"):
            await adapters.rest_json_pages(http, "https://x.org/p", items="r", paging="next")


# ── adapters ─────────────────────────────────────────────────────────────────


@respx.mock
async def test_rest_json_pages_by_page_number_and_offset() -> None:
    pages = {1: [{"i": 1}, {"i": 2}], 2: [{"i": 3}]}
    respx.get("https://x.org/pg").mock(
        side_effect=lambda r: httpx.Response(200, json={"data": {"items": pages.get(int(r.url.params["page"]), [])}})
    )
    async with PoliteClient("t") as http:
        rows, urls = await adapters.rest_json_pages(
            http, "https://x.org/pg", items="data.items", paging="page", page_size=2
        )
    assert [r["i"] for r in rows] == [1, 2, 3] and len(urls) == 2 and "per_page=2" in urls[0]

    data = [{"i": i} for i in range(5)]
    respx.get("https://x.org/off").mock(
        side_effect=lambda r: httpx.Response(200, json=data[int(r.url.params["offset"]) :][:2])
    )
    async with PoliteClient("t") as http:
        rows, _ = await adapters.rest_json_pages(
            http, "https://x.org/off", paging="offset", size_param="limit", page_size=2
        )
    assert [r["i"] for r in rows] == [0, 1, 2, 3, 4]


@respx.mock
async def test_tap_query_returns_rows_and_reports_a_refused_query() -> None:
    tap = "https://exoplanetarchive.ipac.caltech.edu/TAP"
    respx.get(f"{tap}/sync", params={"QUERY": "select pl_name from ps"}).mock(
        return_value=httpx.Response(200, text="pl_name\nKepler-22 b\n")
    )
    respx.get(f"{tap}/sync", params={"QUERY": "select nope from ps"}).mock(
        return_value=httpx.Response(
            200,
            text='<VOTABLE><RESOURCE type="results"><INFO name="QUERY_STATUS" value="ERROR">'
            "column nope does not exist</INFO></RESOURCE></VOTABLE>",
        )
    )
    async with PoliteClient("t") as http:
        df, url = await adapters.tap_query(http, tap, "select   pl_name\n from ps")
        assert list(df["pl_name"]) == ["Kepler-22 b"] and "LANG=ADQL" in url and "FORMAT=csv" in url
        with pytest.raises(FetchError, match="column nope does not exist"):
            await adapters.tap_query(http, tap, "select nope from ps")


@respx.mock
async def test_a_versioned_download_is_cached_rehashed_and_read_from_a_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("E2ER_CACHE_DIR", str(tmp_path / "cache"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data.csv", "a,b\n1,2\n")
        z.writestr("README.txt", "x")
    route = respx.get("https://x.org/files/data.zip").mock(return_value=httpx.Response(200, content=buf.getvalue()))
    async with PoliteClient("t") as http:
        path, meta = await adapters.download_file(http, "https://x.org/files/data.zip", "zz", version="2026_09")
        assert meta["from_cache"] is False and meta["sha256"] == adapters.sha256_bytes(buf.getvalue())
        _, again = await adapters.download_file(http, "https://x.org/files/data.zip", "zz", version="2026_09")
        assert again["from_cache"] is True and route.call_count == 1
        path.write_bytes(b"corrupted")
        _, fixed = await adapters.download_file(http, "https://x.org/files/data.zip", "zz", version="2026_09")
        assert fixed["from_cache"] is False and route.call_count == 2
    assert path == tmp_path / "cache" / "zz" / "2026_09" / "data.zip"
    with pytest.raises(FetchError, match="holds 2 tables"):
        adapters.read_table(path)
    assert adapters.read_table(path, member="data.csv").to_dict("records") == [{"a": 1, "b": 2}]


@respx.mock
async def test_sdmx_data_reads_sdmx_csv() -> None:
    base = "https://sdmx.example.org/rest"
    route = respx.get(f"{base}/data/PRC_HICP/M.DE.CP00").mock(
        return_value=httpx.Response(200, text="DATAFLOW,FREQ,TIME_PERIOD,OBS_VALUE\nX,M,2024-01,2.1\n")
    )
    async with PoliteClient("t") as http:
        df, url = await adapters.sdmx_data(http, base, "PRC_HICP", "M.DE.CP00", start="2024-01")
    assert df["OBS_VALUE"].tolist() == [2.1] and "startPeriod=2024-01" in url
    assert route.calls[0].request.headers["Accept"] == adapters.SDMX_CSV


# ── recorded fixtures ────────────────────────────────────────────────────────


async def test_a_cassette_records_once_and_replays_offline(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    with respx.mock:  # stands in for the live service while recording
        respx.get("https://x.org/v").mock(return_value=httpx.Response(200, text="a,b\n1,2\n"))
        with use_cassette(path, record=True):
            async with PoliteClient("t") as http:
                assert await http.get_text("https://x.org/v", {"z": 1, "a": 2}) == "a,b\n1,2\n"
    doc = json.loads(path.read_text())
    assert doc["interactions"][0]["url"] == "https://x.org/v?a=2&z=1"
    with use_cassette(path):  # no respx, no network
        async with PoliteClient("t") as http:
            assert await http.get_text("https://x.org/v", {"a": 2, "z": 1}) == "a,b\n1,2\n"
            with pytest.raises(AssertionError, match="has no response for GET https://x.org/other"):
                await http.get("https://x.org/other")


def test_a_missing_cassette_says_how_to_record_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="E2ER_RECORD_FIXTURES=1"):
        with use_cassette(tmp_path / "none.json", record=False):
            pass
