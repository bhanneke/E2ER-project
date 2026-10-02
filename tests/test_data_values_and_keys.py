"""Findings 4-6 from the live FOMC event study (2026-09-29).

4. The data analyst loaded a `dgs2` table of 2,765 dates and no values, and
   the data contract passed because it counted rows only.
5. The study's `.env` held the FRED key with a space in front of it; FRED
   answered HTTP 400 and the analyst wrote NULLs.
6. The econometrics specialist wrote its own t distribution (p = 0.208 for
   t = -2.00 with 19 df); the runtime had no scipy to import.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.specialists.contract_check import check_declared_tables, empty_columns

PID = "12345678-1234-1234-1234-123456789abc"
ROOT = Path(__file__).resolve().parents[1]
FRED_KEY = "e5f0123456789abcdef0123456789abc"


# ── 4. declared tables hold values ──────────────────────────────────────────


def _table(ws: Path, name: str, n: int, filled: int, *, extra: str = "") -> None:
    con = sqlite3.connect(ws / "data.db")
    con.execute(f'CREATE TABLE "{name}" (date TIMESTAMP, value REAL{extra})')
    rows = [(f"2020-01-{i % 28 + 1:02d}", 1.0 if i < filled else None) for i in range(n)]
    if extra:
        con.executemany(f'INSERT INTO "{name}" VALUES (?, ?, NULL)', rows)
    else:
        con.executemany(f'INSERT INTO "{name}" VALUES (?, ?)', rows)
    con.commit()
    con.close()


def _dictionary(ws: Path, tables: list[dict]) -> None:
    (ws / "data_dictionary.json").write_text(json.dumps({"tables": tables}))


def test_a_table_of_dates_without_values_fails_the_data_contract(tmp_path: Path):
    _dictionary(tmp_path, [{"name": "dgs2", "source": "fred", "series": "DGS2"}])
    _table(tmp_path, "dgs2", 2765, 0)
    (tmp_path / "data_summary.md").write_text("dgs2: 2,765 rows\n")
    [check] = check_declared_tables(tmp_path)
    assert not check.ok and check.artifact == "data.db"
    assert "dgs2.value: 0 of 2765 non-null (needs 90%)" in check.reason
    assert check.kind == "reliability"


def test_a_series_with_holidays_passes_and_a_declared_share_is_honoured(tmp_path: Path):
    _dictionary(
        tmp_path,
        [
            {"name": "dgs2", "source": "fred"},  # FRED marks holidays "." -> NULL: 96% filled
            {"name": "sparse", "source": "fred", "min_non_null": 0.5},
            {"name": "cols", "source": "fred", "columns": [{"name": "value", "min_non_null": 0.2}, "date"]},
        ],
    )
    _table(tmp_path, "dgs2", 100, 96)
    _table(tmp_path, "sparse", 100, 60)
    _table(tmp_path, "cols", 100, 30, extra=", note TEXT")  # note is not declared, so not checked
    assert empty_columns(tmp_path, ["dgs2", "sparse", "cols"]) == []
    _dictionary(tmp_path, [{"name": "sparse", "source": "fred"}])
    assert empty_columns(tmp_path, ["sparse"]) == ["sparse.value: 60 of 100 non-null (needs 90%)"]


def test_researcher_tables_are_checked_only_where_columns_are_declared(tmp_path: Path):
    _table(tmp_path, "events", 31, 0)
    _dictionary(tmp_path, [{"name": "events", "source": "researcher-supplied"}])
    assert empty_columns(tmp_path, ["events"]) == []
    _dictionary(tmp_path, [{"name": "events", "source": "researcher-supplied", "columns": ["value", "missing"]}])
    assert empty_columns(tmp_path, ["events"]) == [
        "events.value: 0 of 31 non-null (needs 90%)",
        "events.missing: declared in the data dictionary but not a column of the table",
    ]


# ── 5. keys with whitespace ─────────────────────────────────────────────────


def test_settings_strip_keys_from_the_environment_and_env_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from src.config import Settings

    monkeypatch.setenv("FRED_API_KEY", f" {FRED_KEY}\n")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-x")
    assert Settings(_env_file=None).fred_api_key == FRED_KEY
    monkeypatch.delenv("FRED_API_KEY")
    env = tmp_path / ".env"
    env.write_text(f"FRED_API_KEY=' {FRED_KEY}'\nGITHUB_TOKEN=\" ghp_x \"\n")
    s = Settings(_env_file=str(env))
    assert s.fred_api_key == FRED_KEY and s.github_token == "ghp_x"


def test_the_setup_page_strips_a_key_it_keeps(tmp_path: Path):
    from src.api.setup import SaveSetup, build_env

    body, _ = build_env(
        SaveSetup(backend="claude_code", keys={"ALLIUM_API_KEY": "  al-key \t"}),
        {"FRED_API_KEY": f" {FRED_KEY}", "ZENODO_TOKEN": " zt ", "OTHER": " keep me "},
        tmp_path,
    )
    assert f"FRED_API_KEY={FRED_KEY}\n" in body
    assert "ALLIUM_API_KEY=al-key\n" in body
    assert "ZENODO_TOKEN=zt\n" in body
    assert "OTHER=' keep me '" in body  # not a key: left as it was


def _fred_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict) -> tuple[int, Path]:
    from src.modules.data import cli
    from src.modules.data.fred_provider import FredProvider

    async def fake_get(self, path, params):
        assert self._api_key == FRED_KEY  # sent without the space
        return raw

    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(fred_api_key=f" {FRED_KEY}"))
    monkeypatch.setattr(FredProvider, "_get", fake_get)
    monkeypatch.setattr("src.modules.data.fred_provider._pace_request", _no_wait)
    (tmp_path / PID).mkdir(exist_ok=True)
    code = cli.main(["--paper-id", PID, "fred", "series", "--series-id", "DGS2", "--table", "dgs2"])
    return code, tmp_path / PID / "data.db"


async def _no_wait() -> None:
    return None


def test_a_connector_error_fails_the_table_load_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    err = {"_error": "HTTP 400: Bad Request. The value for variable api_key is not a 32 character alpha-numeric"}
    code, db = _fred_cli(tmp_path, monkeypatch, err)
    out = capsys.readouterr()
    assert code == 4
    assert "table 'dgs2' was not created or changed" in json.loads(out.out)["table_error"]
    assert "HTTP 400" in out.err
    assert not db.exists()


def test_a_load_that_returns_dates_without_values_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    dots = {"observations": [{"date": f"2020-01-0{i}", "value": "."} for i in range(1, 6)]}
    code, db = _fred_cli(tmp_path, monkeypatch, dots)
    assert code == 4 and "empty values" in capsys.readouterr().err
    assert not db.exists()


def test_a_good_load_still_writes_the_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    obs = {"observations": [{"date": "2020-01-02", "value": "1.58"}, {"date": "2020-01-03", "value": "."}]}
    code, db = _fred_cli(tmp_path, monkeypatch, obs)
    assert code == 0
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(value), COUNT(*) FROM dgs2").fetchone() == (1, 2)
    con.close()


def test_the_table_writer_refuses_an_error_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from src.modules.data import cli

    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / PID).mkdir()
    result = {"items": [{"date": "2020-01-02", "value": 1.0}], "error": "partial failure"}
    cli._maybe_save_table(result, argparse.Namespace(table="dgs2", paper_id=PID))
    assert "saved_table" not in result and "partial failure" in result["table_error"]
    assert not (tmp_path / PID / "data.db").exists()


@pytest.mark.parametrize(
    ("key", "status", "detail"),
    [
        (FRED_KEY, "PASS", "format of a FRED key"),
        (FRED_KEY.upper(), "FAIL", "not only lower-case letters and digits"),
        (FRED_KEY[:-1], "FAIL", "31 characters"),
        (None, "SKIP", "not set"),
    ],
)
def test_doctor_checks_the_fred_key_format(key, status, detail, monkeypatch: pytest.MonkeyPatch):
    from src.doctor import fred_key_check

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    c = fred_key_check(SimpleNamespace(fred_api_key=key))
    assert c.name == "data.fred.key" and c.status == status and detail in c.detail


def test_doctor_says_when_the_key_had_whitespace(monkeypatch: pytest.MonkeyPatch):
    from src.doctor import fred_check, fred_key_check

    monkeypatch.setenv("FRED_API_KEY", f" {FRED_KEY}")
    c = fred_key_check(SimpleNamespace(fred_api_key=FRED_KEY))
    assert c.status == "PASS" and "e2er strips them" in c.detail
    import asyncio

    skipped = asyncio.run(fred_check(SimpleNamespace(fred_api_key="not-a-key")))
    assert skipped.status == "SKIP" and "wrong format" in skipped.detail


# ── 6. statistics come from a library ───────────────────────────────────────


def test_the_runtime_has_scipy_and_statsmodels():
    """The runner executes run_estimation.py with e2er's interpreter; both must import there."""
    import tomllib

    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert any(d.startswith("scipy") for d in deps) and any(d.startswith("statsmodels") for d in deps)


def test_the_econometrics_skills_forbid_hand_written_distributions():
    schema = (ROOT / "skills/files/econometrics/estimation-results-schema.md").read_text()
    assert "scipy.stats" in schema and "Never write your own" in schema
    assert "`hypothesis`" in schema and "exclusions" in schema
    assert "scipy.stats" in (ROOT / "skills/files/econometrics/event-study.md").read_text()


@pytest.mark.parametrize("df", [1, 2, 3, 5, 9, 19, 30, 120, 1000, 50000])
@pytest.mark.parametrize("t", [0.01, 0.5, 1.0, 1.6, 2.0, 2.6, 4.0, 8.0])
def test_our_t_distribution_agrees_with_scipy(t: float, df: int):
    stats = pytest.importorskip("scipy.stats")
    from src.core.pipeline.statistics import t_two_sided_p

    assert t_two_sided_p(t, df) == pytest.approx(2 * stats.t.sf(t, df), rel=1e-9, abs=1e-14)
