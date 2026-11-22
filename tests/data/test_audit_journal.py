"""The wrappers' audit rows reach the run database through a journal in the workspace.

Tester report 2026-11-02: under Codex on Windows every file edit failed because e2er
gave Codex the run database's folder as an extra writable folder (openai/codex#30009),
only so the wrappers could write their audit rows there. Inside a call the wrappers
now append to ``<workspace>/.e2er-audit-journal-<call>.jsonl``; e2er checks each line,
writes the rows with its own SQL and removes the journal. A real SQLite run database;
no network, no CLI.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from src.db import client as _client
from src.modules.data import audit, audit_journal
from src.modules.data.audit_journal import JournalImporter, new_journal_path

_REAL_EXECUTE = _client.execute
_REAL_FETCH_ONE = _client.fetch_one
_REAL_FETCH_ALL = _client.fetch_all
KEY = audit_journal.new_journal_key()


def _seal(line: str) -> str:
    """A journal line as the wrapper writes it: sealed with the call's key."""
    try:
        row = json.loads(line)
    except ValueError:
        return line
    if not isinstance(row, dict):
        return line
    row["mac"] = audit_journal.line_mac(row, KEY)
    return json.dumps(row)


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "run" / "papers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.delenv(audit_journal.ENV, raising=False)
    monkeypatch.delenv(audit_journal.ENV_KEY, raising=False)
    monkeypatch.setattr("src.db.client.execute", _REAL_EXECUTE)
    monkeypatch.setattr("src.db.client.fetch_one", _REAL_FETCH_ONE)
    monkeypatch.setattr("src.db.client.fetch_all", _REAL_FETCH_ALL)
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False
    yield path
    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


def _paper() -> str:
    pid = str(uuid.uuid4())
    asyncio.run(
        _client.execute(
            "INSERT INTO papers (id, title, research_question, status) VALUES (%(id)s, 't', 'q', 'designing')",
            {"id": pid},
        )
    )
    return pid


def _rows(db: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db) as c:
        return c.execute(sql).fetchall()


FEAS_SQL = "SELECT a FROM chain.trades WHERE block_time > '2024-01-01' LIMIT 10"


async def _wrapper_writes(paper_id: str) -> tuple[str, str, str]:
    """What `e2er-data allium feasibility` and `production` record (data/tools.py), in the wrapper process."""
    feas = await audit.log_query(paper_id, "data_analyst", FEAS_SQL, "feasibility",
                                 ["a"], "daily", estimated_rows=10)  # fmt: skip
    await audit.mark_approved(feas, approved_by="auto_feasibility")
    await audit.mark_executed(feas, 7)
    prod = await audit.log_query(paper_id, "data_analyst", "SELECT a FROM chain.trades", "production", ["a"], "daily")
    request = await audit.create_approval_request(prod, paper_id)
    return feas, prod, request


def test_wrapper_rows_go_through_the_journal_into_the_run_database(db, tmp_path, monkeypatch):
    pid = _paper()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    journal = new_journal_path(workspace)
    before = db.read_bytes()

    # The wrapper side: E2ER_AUDIT_JOURNAL set (as run_env sets it), the run database is not written.
    monkeypatch.setenv(audit_journal.ENV, str(journal))
    monkeypatch.setenv(audit_journal.ENV_KEY, KEY)
    feas, prod, request = asyncio.run(_wrapper_writes(pid))
    assert db.read_bytes() == before, "a wrapper inside a call never writes the run database"
    lines = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines()]
    assert [x["op"] for x in lines] == ["query", "approved", "executed", "query", "approval_request"]
    assert all(audit_journal.sealed(x, KEY) for x in lines), "every line carries the call's seal"
    # The feasibility-first guardrail knows the sealed feasibility query is on its way into the database.
    assert audit_journal.journal_has_pending_feasibility(pid, "chain.trades")
    assert not audit_journal.journal_has_pending_feasibility(pid, "other.table")

    # The e2er side: import, then the journal is gone.
    monkeypatch.delenv(audit_journal.ENV)
    monkeypatch.delenv(audit_journal.ENV_KEY)
    importer = JournalImporter(journal, pid, KEY)
    asyncio.run(importer.finish())
    assert not journal.exists()
    assert importer.imported == 5 and importer.skipped == 0
    records = dict(
        (r[0], r[1:])
        for r in _rows(
            db,
            "SELECT id, query_type, validation_status, approved_by, actual_rows, paper_id, "
            "fields_requested, estimated_rows FROM data_query_records",
        )  # fmt: skip
    )
    # Marked as reported by the wrapper: e2er checked the line, it did not see the query run.
    assert records[feas] == ("feasibility", "approved", audit_journal.JOURNAL_APPROVAL, 7, pid, '["a"]', 10)
    assert records[prod] == ("production", "pending", None, None, pid, '["a"]', None)
    assert _rows(db, "SELECT id, query_record_id, paper_id, status FROM data_approval_requests") == [
        (request, prod, pid, "pending")
    ]
    # The same audit exports as before (replication package).
    exported = asyncio.run(audit.export_audit_log(pid))
    assert {r["id"] for r in exported} == {feas, prod}


def test_the_importer_follows_a_call_and_takes_only_complete_lines(db, tmp_path):
    pid = _paper()
    journal = new_journal_path(tmp_path)
    rid = str(uuid.uuid4())
    line = json.dumps({"op": "query", "id": rid, "paper_id": pid, "specialist": "s", "query_sql": "SELECT 1",
                       "query_type": "feasibility", "fields_requested": [], "aggregation_level": "daily",
                       "estimated_rows": None})  # fmt: skip
    line = _seal(line)
    importer = JournalImporter(journal, pid, KEY)
    journal.write_text(line[:20], encoding="utf-8")  # a wrapper is writing this line right now
    assert asyncio.run(importer.import_new()) == 0
    journal.write_text(line + "\n", encoding="utf-8")
    assert asyncio.run(importer.import_new()) == 1
    assert asyncio.run(importer.import_new()) == 0, "a line is imported once"
    asyncio.run(importer.finish())
    assert _rows(db, "SELECT id FROM data_query_records") == [(rid,)]


def test_malformed_and_forged_lines_are_skipped(db, tmp_path, caplog):
    pid = _paper()
    other = _paper()
    journal = new_journal_path(tmp_path)
    good = str(uuid.uuid4())
    prod = str(uuid.uuid4())

    def q(**kw):
        base = {"op": "query", "id": str(uuid.uuid4()), "paper_id": pid, "specialist": "s", "query_sql": "SELECT 1",
                "query_type": "production", "fields_requested": [], "aggregation_level": "daily",
                "estimated_rows": None}  # fmt: skip
        return json.dumps({**base, **kw})

    lines = [
        "not json at all",
        "[1, 2]",
        json.dumps({"op": "drop_table", "table": "papers"}),
        q(id=good),
        q(id=prod),
        q(paper_id=other),  # another paper's row
        q(id="'; DROP TABLE papers; --"),  # not a UUID
        q(query_type="admin"),
        q(extra_column="x"),
        q(estimated_rows="12"),
        q(fields_requested="a,b"),
        # A wrapper never approves a production query: that is the researcher's, in the dashboard.
        json.dumps({"op": "approved", "id": prod, "approved_by": "auto_feasibility"}),
        json.dumps({"op": "approved", "id": good, "approved_by": "researcher"}),
        json.dumps({"op": "executed", "id": str(uuid.uuid4()), "actual_rows": 3}),  # no such query
        json.dumps({"op": "executed", "id": good, "actual_rows": True}),
        json.dumps({"op": "approval_request", "id": str(uuid.uuid4()), "query_record_id": prod, "paper_id": other}),
        json.dumps({"op": "executed", "id": good, "actual_rows": 4}),
    ]
    journal.write_text("\n".join(_seal(x) for x in lines) + "\n", encoding="utf-8")
    importer = JournalImporter(journal, pid, KEY)
    asyncio.run(importer.finish())
    assert importer.imported == 3 and importer.skipped == len(lines) - 3
    assert not journal.exists()
    assert sorted(_rows(db, "SELECT id, paper_id, validation_status, actual_rows FROM data_query_records")) == sorted(
        [(good, pid, "pending", 4), (prod, pid, "pending", None)]
    )
    assert _rows(db, "SELECT COUNT(*) FROM data_approval_requests") == [(0,)]
    assert _rows(db, "SELECT COUNT(*) FROM papers") == [(2,)]
    assert "skipped" in caplog.text


def test_a_journal_is_read_up_to_its_cap(db, tmp_path, monkeypatch):
    pid = _paper()
    monkeypatch.setattr(audit_journal, "MAX_LINES", 3)
    journal = new_journal_path(tmp_path)
    rows = [
        json.dumps(
            {
                "op": "query",
                "id": str(uuid.uuid4()),
                "paper_id": pid,
                "specialist": "s",
                "query_sql": "x",
                "query_type": "feasibility",
                "fields_requested": [],
                "aggregation_level": "d",
                "estimated_rows": None,
            }
        )  # fmt: skip
        for _ in range(6)
    ]
    journal.write_text("\n".join(_seal(x) for x in rows) + "\n", encoding="utf-8")
    importer = JournalImporter(journal, pid, KEY)
    asyncio.run(importer.finish())
    assert importer.imported == 3
    assert _rows(db, "SELECT COUNT(*) FROM data_query_records") == [(3,)]


def test_the_wrapper_writes_only_a_journal_e2er_named(monkeypatch, tmp_path):
    monkeypatch.setenv(audit_journal.ENV, str(tmp_path / "papers.db"))
    with pytest.raises(RuntimeError, match="does not name an e2er audit journal"):
        audit_journal.append("query", id="x")


def test_a_wrapper_reads_the_run_database_read_only(db, tmp_path, monkeypatch):
    pid = _paper()
    monkeypatch.setenv(audit_journal.ENV, str(new_journal_path(tmp_path)))
    _client._sqlite_bootstrapped = False
    assert asyncio.run(_client.fetch_one("SELECT id FROM papers WHERE id = %(id)s", {"id": pid})) == {"id": pid}
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        asyncio.run(_client.execute("DELETE FROM papers", {}))


def _feasibility_lines(pid: str, sql: str = FEAS_SQL) -> list[str]:
    rid = str(uuid.uuid4())
    return [
        json.dumps(
            {
                "op": "query",
                "id": rid,
                "paper_id": pid,
                "specialist": "s",
                "query_sql": sql,
                "query_type": "feasibility",
                "fields_requested": ["a"],
                "aggregation_level": "daily",
                "estimated_rows": None,
            }
        ),  # fmt: skip
        json.dumps({"op": "approved", "id": rid, "approved_by": "auto_feasibility"}),
    ]


def test_lines_without_the_calls_seal_are_skipped(db, tmp_path):
    """Review 2026-11-22: lines the model wrote with its file tools were imported like the wrapper's."""
    pid = _paper()
    journal = new_journal_path(tmp_path)
    forged = _feasibility_lines(pid)
    wrong_key = audit_journal.new_journal_key()
    other = [json.dumps({**json.loads(x), "mac": audit_journal.line_mac(json.loads(x), wrong_key)}) for x in forged]
    journal.write_text("\n".join(forged + other) + "\n", encoding="utf-8")
    importer = JournalImporter(journal, pid, KEY)
    asyncio.run(importer.finish())
    assert importer.imported == 0 and importer.skipped == 4
    assert _rows(db, "SELECT COUNT(*) FROM data_query_records") == [(0,)]


def test_a_feasibility_query_that_fails_the_guardrails_is_not_approved(db, tmp_path):
    pid = _paper()
    journal = new_journal_path(tmp_path)
    journal.write_text("\n".join(_seal(x) for x in _feasibility_lines(pid, "SELECT * FROM chain.trades")) + "\n")
    importer = JournalImporter(journal, pid, KEY)
    asyncio.run(importer.finish())
    assert importer.imported == 1 and importer.skipped == 1
    assert _rows(db, "SELECT validation_status FROM data_query_records") == [("pending",)]


def test_the_guardrail_does_not_trust_journal_lines(db, tmp_path, monkeypatch):
    """A forged feasibility query in the journal never lets a production query through (finding 6)."""
    from src.modules.data.guardrails import QueryValidator

    pid = _paper()
    journal = new_journal_path(tmp_path)
    monkeypatch.setenv(audit_journal.ENV, str(journal))
    monkeypatch.setenv(audit_journal.ENV_KEY, KEY)
    monkeypatch.setattr(audit_journal, "IMPORT_WAIT", 0.6)
    _client._sqlite_bootstrapped = False

    # Unsealed (the model's file tools): not even waited for.
    journal.write_text("\n".join(_feasibility_lines(pid)) + "\n", encoding="utf-8")
    assert not audit_journal.journal_has_pending_feasibility(pid, "chain.trades")
    result = asyncio.run(QueryValidator.validate_feasibility_first("production", pid, "chain.trades"))
    assert not result.valid

    # Sealed but never imported (no e2er importing it): the guardrail waits, then refuses.
    journal.write_text("\n".join(_seal(x) for x in _feasibility_lines(pid)) + "\n", encoding="utf-8")
    assert audit_journal.journal_has_pending_feasibility(pid, "chain.trades")
    result = asyncio.run(QueryValidator.validate_feasibility_first("production", pid, "chain.trades"))
    assert not result.valid


def test_the_guardrail_passes_once_e2er_imported_the_feasibility_query(db, tmp_path, monkeypatch):
    from src.modules.data.guardrails import QueryValidator

    pid = _paper()
    journal = new_journal_path(tmp_path)
    journal.write_text("\n".join(_seal(x) for x in _feasibility_lines(pid)) + "\n", encoding="utf-8")
    asyncio.run(JournalImporter(journal, pid, KEY).finish())
    result = asyncio.run(QueryValidator.validate_feasibility_first("production", pid, "chain.trades"))
    assert result.valid, result.rejection_reason


def test_an_ai_written_script_never_gets_the_journal_key():
    from src.core.child_env import script_env

    env = script_env(
        home=Path("/nonexistent-home"),
        source={audit_journal.ENV_KEY: KEY, audit_journal.ENV: "/w/.e2er-audit-journal-0123456789abcdef.jsonl"},
    )
    assert audit_journal.ENV_KEY not in env
