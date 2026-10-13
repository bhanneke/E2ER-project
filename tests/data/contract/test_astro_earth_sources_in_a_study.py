"""The NASA Exoplanet Archive, ESA Gaia and NASA POWER inside a study, end to end (hermetic, recorded fixtures).

A data analyst's `e2er-data … --table` command loads the rows into the
study's data.db; the study's "Data used" (the run page's panel and the finish
page, ``inputs_view``) names the source and the table; the dashboard has the
source's name and doctor check; the data architect may declare it; the
standalone check counts its commands as loading data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.modules.data import cli
from src.modules.data.sources.http import use_cassette

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PID = "astro-earth-study"

CASES = [
    (
        "exoplanets",
        "NASA Exoplanet Archive",
        "imaged",
        "exoplanets_planets.json",
        ["planets", "--since", "2024", "--until", "2024", "--method", "Imaging",
         "--columns", "pl_name,hostname,pl_orbsmax,pl_bmasse,disc_year"],
    ),
    (
        "gaia",
        "ESA Gaia Archive",
        "pleiades",
        "gaia_cone_pleiades.json",
        ["cone", "--ra", "56.75", "--dec", "24.12", "--radius", "0.5", "--max-mag", "11"],
    ),
    (
        "nasa_power",
        "NASA POWER",
        "frankfurt",
        "nasa_power_point_daily.json",
        ["point", "--lat", "50.11", "--lon", "8.68", "--parameters", "T2M,PRECTOTCORR",
         "--start", "2024-01-01", "--end", "2024-01-07"],
    ),
]  # fmt: skip


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


@pytest.mark.parametrize(("name", "label", "table", "fixture", "argv"), CASES, ids=[c[0] for c in CASES])
def test_a_data_analyst_load_reaches_data_db_and_data_used(
    ws: Path, capsys: pytest.CaptureFixture[str], name: str, label: str, table: str, fixture: str, argv: list[str]
) -> None:
    from src.api.inputs import inputs_view

    with use_cassette(FIXTURES / fixture):
        code = cli.main(["--paper-id", PID, "--specialist", "data_analyst", name, *argv, "--table", table])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out
    with sqlite3.connect(ws / "data.db") as db:
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == out["row_count"] > 0

    view = inputs_view(ws)
    [row] = view["tables"]
    assert row["table"] == table and row["rows"] == out["row_count"]
    assert row["source"].startswith(label + " (")
    [load] = view["loads"]
    assert load["source"] == label and load["what"] and len(load["sha256"]) == 64
    assert view["prepared"]  # the source's BibTeX entry is in the study's bibliography


@pytest.mark.parametrize("name", [c[0] for c in CASES])
def test_the_source_is_named_declared_and_counted_as_loading(name: str, tmp_path: Path) -> None:
    from src.core import labels
    from src.core.specialists import data_sources as ds
    from src.core.specialists.standalone_check import _loading_sources
    from src.modules.data.sources import get

    source = get(name)
    assert source is not None and source.doctor is not None
    assert labels.data_connector(name) == source.label
    assert labels.CHECKS[source.doctor.check] == source.label
    settings = SimpleNamespace(fred_api_key=None, allium_api_key=None)
    assert f"- `{name}` (no key needed)" in ds.sources_block(tmp_path, settings)
    assert all(ds._norm(a) == name for a in source.aliases)
    assert name in _loading_sources()
    assert (Path(__file__).resolve().parents[3] / "skills" / "files" / f"{source.skill}.md").is_file()
