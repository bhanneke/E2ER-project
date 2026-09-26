"""Choosing which pipeline a paper runs.

Pipelines became files so that the process could be changed without changing
E2ER. That is only true if a user can pick one, and until now the choice existed
only as a constructor default nobody could reach: every paper ran `empirical`
because nothing offered anything else.

Two things carry the weight here. The choice has to be validated against the
files on disk rather than a list in the code, or adding a pipeline would mean
editing E2ER. And it has to be *stored*, because resume re-reads the row: a
paper that started under one DAG must not finish under another.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import _pipeline_choices, app
from src.core.pipeline import spec

SECOND_PIPELINE = """
name = "theory"
description = "A formal model, argued and attacked. No data."
methodologies = ["theoretical"]
finalize = ["compile"]

[[steps]]
name = "framing"
kind = "strategist"

[[steps]]
name = "contracts"
kind = "gate"
check = "contracts"
"""


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def two_pipelines(tmp_path: Path, monkeypatch) -> Path:
    """A project-local pipelines dir, plus the builtin one."""
    local = tmp_path / "pipelines"
    local.mkdir()
    (local / "theory.toml").write_text(SECOND_PIPELINE)
    builtin = Path(__file__).resolve().parents[1] / "pipelines"
    monkeypatch.setattr(spec, "search_paths", lambda project=None: [local, builtin])
    return local


# ---------------------------------------------------------------------------
# The choice comes from disk
# ---------------------------------------------------------------------------


def test_the_form_offers_every_pipeline_on_disk(client, two_pipelines):
    r = client.get("/papers/new")

    assert r.status_code == 200
    assert 'value="empirical"' in r.text
    assert 'value="theory"' in r.text, "a pipeline dropped into ./pipelines must appear by itself"


def test_each_choice_carries_its_own_description(client, two_pipelines):
    """The name alone does not tell anyone what the pipeline does."""
    r = client.get("/papers/new")

    assert "A formal model, argued and attacked" in r.text


def test_a_pipeline_that_does_not_parse_is_listed_not_hidden(tmp_path, monkeypatch):
    """A typo in a TOML file must not present as "my pipeline vanished"."""
    local = tmp_path / "pipelines"
    local.mkdir()
    (local / "broken.toml").write_text("name = = broken")
    monkeypatch.setattr(spec, "search_paths", lambda project=None: [local])

    names = [c["name"] for c in _pipeline_choices()]

    assert "broken" in names
    assert "did not parse" in next(c["description"] for c in _pipeline_choices() if c["name"] == "broken")


def test_listing_pipelines_survives_a_broken_one(client, tmp_path, monkeypatch):
    local = tmp_path / "pipelines"
    local.mkdir()
    (local / "broken.toml").write_text("this is not toml = = =")
    monkeypatch.setattr(spec, "search_paths", lambda project=None: [local])

    assert client.get("/papers/new").status_code == 200


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_an_unknown_pipeline_is_refused_at_submit(client, two_pipelines):
    """Not at run time.

    find_spec raises inside the runner. A background task that dies on its first
    line leaves a paper row at 'idea' with nothing on screen to explain it, so
    the check has to happen while someone is still waiting for a response.
    """
    r = client.post(
        "/api/papers",
        json={"title": "T", "research_question": "Q?", "pipeline": "no-such-pipeline"},
    )

    assert r.status_code == 422
    assert "no-such-pipeline" in r.text
    assert "empirical" in r.text, "say what there is, not just what there isn't"


def test_the_default_pipeline_is_accepted_without_being_named(client):
    """Every existing caller omits `pipeline`; none of them may break."""
    from src.api.app import CreatePaperRequest

    assert CreatePaperRequest(title="T", research_question="Q?").pipeline == "empirical"


# ---------------------------------------------------------------------------
# It has to be stored
# ---------------------------------------------------------------------------


def test_the_chosen_pipeline_is_written_to_the_papers_row(client, two_pipelines, monkeypatch):
    """Resume reads the row, so creating has to write it.

    If the pipeline were re-chosen at resume time, a theory paper resumed after
    a crash would continue under the empirical DAG — skipping or repeating
    stages depending on which steps the two happen to share. The column exists
    for this and nothing else.
    """
    inserts: list[tuple[str, dict]] = []

    async def record(sql, params=None):
        if "INSERT INTO papers" in sql:
            inserts.append((sql, params or {}))

    async def fake_prepare(*a, **kw):
        return None

    monkeypatch.setattr("src.db.client.execute", record)
    monkeypatch.setattr("src.api.app._prepare_and_run", fake_prepare)

    client.post(
        "/api/papers",
        json={
            "title": "T",
            "research_question": "Q?",
            "pipeline": "theory",
            "mode": "single_pass",
            "max_cost_usd": 1,
        },
    )

    assert inserts, "the paper must be persisted"
    sql, params = inserts[0]
    assert "pipeline" in sql, "the INSERT has to name the column"
    assert params.get("pipeline") == "theory", "and bind the chosen value, not the default"


def test_an_existing_sqlite_database_gains_the_column(tmp_path, monkeypatch):
    """CREATE TABLE IF NOT EXISTS never alters a table that already exists.

    Every DB created before this change has a papers table without `pipeline`,
    and the INSERT names that column — so without the backfill, the first paper
    created after upgrading fails to persist on every existing install.
    """
    import asyncio
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()

    import aiosqlite

    from src.db.client import _ensure_sqlite_columns

    async def upgrade():
        async with aiosqlite.connect(str(db)) as c:
            await _ensure_sqlite_columns(c, "papers", {"pipeline": "TEXT NOT NULL DEFAULT 'empirical'"})
            await c.commit()

    asyncio.run(upgrade())

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(papers)")}
    conn.close()

    assert "pipeline" in cols


def test_the_backfill_list_includes_pipeline():
    """The upgrade above only happens if the column is on the list."""
    import inspect

    from src.db import client as dbc

    assert '"pipeline"' in inspect.getsource(dbc._ensure_sqlite_schema)


def test_the_postgres_migration_is_additive():
    """Migration 014 must not rewrite an earlier one."""
    sqldir = Path(__file__).resolve().parents[1] / "sql"
    migration = sqldir / "014_papers_pipeline.sql"

    assert migration.exists()
    assert "ALTER TABLE papers" in migration.read_text()
    assert "ADD COLUMN pipeline" in migration.read_text()


def test_the_pipeline_column_is_not_constrained_to_a_fixed_list():
    """A CHECK constraint would mean writing a pipeline required a migration.

    papers.methodology has one, correctly — those three values are hardcoded in
    the prompts. Pipelines are user files, so the legal set is open.
    """
    sqldir = Path(__file__).resolve().parents[1] / "sql"
    text = (sqldir / "014_papers_pipeline.sql").read_text()

    assert "CHECK" not in text.upper().replace("-- ", "").split("ALTER TABLE")[-1].upper()


def test_the_runner_is_constructed_with_the_chosen_pipeline(tmp_path, monkeypatch):
    """The last link in the chain.

    Everything above this is plumbing that only matters if the name actually
    reaches PipelineRunner, which is what turns it into a different DAG.
    """
    import asyncio

    seen: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, **kw):
            seen.update(kw)

        async def run(self):
            return None

    monkeypatch.setattr("src.core.strategist.runner.PipelineRunner", FakeRunner)
    # The backend is built before the (fake) runner; it only checks that a key
    # is configured, and nothing is ever sent with it.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    from src.config import get_settings

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    from src.api.app import _run_pipeline

    asyncio.run(
        _run_pipeline(
            "pid",
            tmp_path,
            "single_pass",
            1.0,
            "theoretical",
            None,
            None,
            None,
            None,
            pipeline="theory",
        )
    )

    assert seen.get("pipeline") == "theory"
    get_settings.cache_clear()  # later tests must not see the dummy key


def test_resume_reads_the_pipeline_from_the_row():
    import inspect

    from src.api import app as appmod

    src = inspect.getsource(appmod.resume_paper)
    assert 'row.get("pipeline")' in src, "resume must not re-choose the pipeline"
    assert "pipeline=pipeline" in src, "and must pass what it read"


# ---------------------------------------------------------------------------
# End to end through the form
# ---------------------------------------------------------------------------


def test_the_form_sends_the_pipeline_on_to_the_runner(client, two_pipelines, monkeypatch):
    seen: dict[str, str] = {}

    async def fake_prepare(paper_id, workspace, settings, mode, cap, *a, **kw):
        seen["pipeline"] = kw.get("pipeline", "")

    monkeypatch.setattr("src.api.app._prepare_and_run", fake_prepare)

    r = client.post(
        "/papers",
        data={
            "title": "T",
            "research_question": "Q?",
            "pipeline": "theory",
            "mode": "single_pass",
            # Within the first-run guardrail's $1 floor: on a fresh DB no
            # (model, methodology, mode) tuple has ever completed, so a default
            # $25 cap is refused. Not what this test is about.
            "max_cost_usd": "1",
        },
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)
    assert seen["pipeline"] == "theory", "the form's choice must reach the background task"
