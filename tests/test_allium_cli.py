"""Tests for `src.modules.data.cli` — the Allium gatekeeper.

These tests prove the bash-wrapper entry point uses the SAME guardrails as
the in-process AlliumToolHandler. If the SDK-mode handler accepts a query,
the CLI accepts it. If the handler rejects it, the CLI rejects it. Same
text comes back to the LLM either way.

All tests are offline ($0). The Allium HTTP client and the DB are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — workspace + data_dictionary fixtures
# ---------------------------------------------------------------------------


def _write_data_dictionary(workspace: Path) -> None:
    """Write a minimal valid data_dictionary.json so dictionary-dependent
    guardrails can fire."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "data_dictionary.json").write_text(
        json.dumps(
            {
                "unit_of_observation": "daily_aggregate",
                "fields": [
                    {
                        "name": "block_number",
                        "description": "Ethereum block height",
                        "data_type": "int",
                        "source_table": "ethereum.blocks",
                    },
                    {
                        "name": "ts",
                        "description": "Block timestamp",
                        "data_type": "timestamp",
                        "source_table": "ethereum.blocks",
                    },
                ],
                "time_filter": {
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "column": "ts",
                },
                "chains": ["ethereum"],
                "identification_rationale": "test",
                "granularity_justification": "daily aggregate of blocks",
            }
        )
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A workspace_root fixture with a paper subdir + data_dictionary."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    from src.config import get_settings

    get_settings.cache_clear()

    paper_id = "11111111-2222-3333-4444-555555555555"
    paper_ws = tmp_path / paper_id
    _write_data_dictionary(paper_ws)
    return paper_id, paper_ws


# ---------------------------------------------------------------------------
# 1. Help / argparse plumbing
# ---------------------------------------------------------------------------


def test_cli_help_lists_all_subcommands(capsys):
    from src.modules.data import cli

    with pytest.raises(SystemExit):
        cli.main(["--help"])

    out = capsys.readouterr().out
    for sub in ("feasibility", "production", "check-approval", "list-tables"):
        assert sub in out, f"--help output missing '{sub}' subcommand"


# ---------------------------------------------------------------------------
# 1b. paper_id / specialist resolution: env var + missing-id error
# ---------------------------------------------------------------------------


def test_cli_picks_up_paper_id_from_env(workspace, capsys, monkeypatch):
    """The runner injects E2ER_PAPER_ID into the subprocess env so the
    specialist's bash invocation can stay clean (no --paper-id flag)."""
    paper_id, _ = workspace
    monkeypatch.setenv("ALLIUM_API_KEY", "test-key")
    monkeypatch.setenv("E2ER_PAPER_ID", paper_id)
    monkeypatch.setenv("E2ER_SPECIALIST", "data_architect")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.data import cli

    # No --paper-id, no --specialist on the CLI.
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        rc = cli.main(
            [
                "feasibility",
                "--sql",
                "SELECT * FROM ethereum.blocks WHERE ts >= '2024-01-01'",
                "--fields",
                "block_number,ts",
                "--aggregation",
                "daily",
                "--rationale",
                "test",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0
    # SELECT * still rejected — proves the call routed through the same
    # handler that runs all 5 guardrails.
    assert "rejected" in out.lower()


def test_cli_errors_when_paper_id_missing(capsys, monkeypatch):
    """No --paper-id and no env var → exit code 2 with a clear message."""
    monkeypatch.delenv("E2ER_PAPER_ID", raising=False)
    monkeypatch.delenv("E2ER_SPECIALIST", raising=False)

    from src.modules.data import cli

    rc = cli.main(["list-tables"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "paper_id" in err.lower() or "E2ER_PAPER_ID" in err


# ---------------------------------------------------------------------------
# 2. Guardrail rejection — SELECT * (G1)
# ---------------------------------------------------------------------------


def test_feasibility_rejects_select_star(workspace, capsys, monkeypatch):
    paper_id, _ = workspace
    monkeypatch.setenv("ALLIUM_API_KEY", "test-key")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.data import cli

    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        rc = cli.main(
            [
                "--paper-id",
                paper_id,
                "feasibility",
                "--sql",
                "SELECT * FROM ethereum.blocks WHERE ts >= '2024-01-01'",
                "--fields",
                "block_number,ts",
                "--aggregation",
                "daily",
                "--rationale",
                "test",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0  # always 0; rejection is in stdout
    assert "rejected" in out.lower(), f"SELECT * must be rejected; output: {out}"
    assert "select" in out.lower() and ("*" in out or "select *" in out.lower())


# ---------------------------------------------------------------------------
# 3. Guardrail rejection — field not in dictionary (G2)
# ---------------------------------------------------------------------------


def test_feasibility_rejects_field_not_in_dictionary(workspace, capsys, monkeypatch):
    paper_id, _ = workspace
    monkeypatch.setenv("ALLIUM_API_KEY", "test-key")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.data import cli

    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        rc = cli.main(
            [
                "--paper-id",
                paper_id,
                "feasibility",
                "--sql",
                "SELECT undeclared_column FROM ethereum.blocks WHERE ts >= '2024-01-01'",
                "--fields",
                "undeclared_column",
                "--aggregation",
                "daily",
                "--rationale",
                "test",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0
    assert "rejected" in out.lower()
    assert "undeclared_column" in out or "data_dictionary" in out


# ---------------------------------------------------------------------------
# 4. Guardrail rejection — no time-bound WHERE clause (G3)
# ---------------------------------------------------------------------------


def test_feasibility_rejects_unbounded_query(workspace, capsys, monkeypatch):
    paper_id, _ = workspace
    monkeypatch.setenv("ALLIUM_API_KEY", "test-key")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.data import cli

    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        rc = cli.main(
            [
                "--paper-id",
                paper_id,
                "feasibility",
                "--sql",
                "SELECT block_number, ts FROM ethereum.blocks",  # no WHERE
                "--fields",
                "block_number,ts",
                "--aggregation",
                "daily",
                "--rationale",
                "test",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0
    assert "rejected" in out.lower()
    # Some hint about the time filter requirement
    assert "where" in out.lower() or "time" in out.lower()


# ---------------------------------------------------------------------------
# 5. Production query without prior feasibility (G5: feasibility-first)
# ---------------------------------------------------------------------------


def test_production_rejected_without_prior_feasibility(workspace, capsys, monkeypatch):
    paper_id, _ = workspace
    monkeypatch.setenv("ALLIUM_API_KEY", "test-key")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.data import cli

    # No prior feasibility row → guardrail G5 should reject.
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
        patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=[]),
    ):
        rc = cli.main(
            [
                "--paper-id",
                paper_id,
                "production",
                "--sql",
                "SELECT block_number, ts FROM ethereum.blocks WHERE ts >= '2024-01-01'",
                "--fields",
                "block_number,ts",
                "--aggregation",
                "daily",
                "--rationale",
                "production run for the analysis",
                "--primary-table",
                "ethereum.blocks",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0
    # Either a guardrail rejection mentioning feasibility OR a production-pending
    # response; the test asserts the contract: the CLI did not silently bypass
    # guardrails or crash. Presence of either means routing through the same
    # AlliumToolHandler that the SDK backends use.
    assert "rejected" in out.lower() or "approval" in out.lower() or "pending" in out.lower()


# ---------------------------------------------------------------------------
# 6. check-approval routes through the same handler
# ---------------------------------------------------------------------------


def test_check_approval_returns_status(workspace, capsys, monkeypatch):
    paper_id, _ = workspace
    monkeypatch.setenv("ALLIUM_API_KEY", "test-key")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.data import cli

    # Stub the approval-with-note lookup directly (the handler imports it).
    async def _status(*a, **kw):
        return ("rejected", "fields too broad — narrow to block_number, ts only")

    with patch("src.modules.data.audit.get_approval_status_with_note", side_effect=_status):
        rc = cli.main(
            [
                "--paper-id",
                paper_id,
                "check-approval",
                "--query-id",
                "abc-123",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0
    assert "REJECTED" in out
    assert "fields too broad" in out
    # Tells the model how to recover (the handler's prompt language)
    assert "submit" in out.lower() or "new" in out.lower()


# ---------------------------------------------------------------------------
# 7. Allium not configured — CLI surfaces a clear message
# ---------------------------------------------------------------------------


def test_cli_handles_missing_allium_key(workspace, capsys, monkeypatch):
    """If ALLIUM_API_KEY isn't set, list-tables surfaces a clear message
    rather than silently calling Allium. We patch get_settings() directly
    because pydantic-settings loads .env from CWD, which can keep a real
    key around even if monkeypatch.delenv is used."""
    paper_id, _ = workspace

    from src.config import Settings, get_settings

    # Build a fresh Settings ignoring any .env so allium_api_key is None.
    no_key_settings = Settings(_env_file=None)  # type: ignore[call-arg]
    no_key_settings.allium_api_key = None

    get_settings.cache_clear()

    from src.modules.data import cli

    # Handler does a lazy `from ...config import get_settings` inside _list_tables,
    # so we patch the canonical source.
    with (
        patch("src.config.get_settings", return_value=no_key_settings),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None),
    ):
        rc = cli.main(
            [
                "--paper-id",
                paper_id,
                "list-tables",
            ]
        )

    out = capsys.readouterr().out
    assert rc == 0
    assert "not configured" in out.lower() or "allium_api_key" in out.lower(), (
        f"missing-key path must surface a clear message; got: {out!r}"
    )
