"""Studies: repeated runs of one question grouped as versions, and archiving.

A researcher's dashboard listed 40 "studies" since May, most of them repeated
runs of the same question. These tests pin the grouping (what counts as the
same study), the backfill for databases made by an older e2er, the counts the
list shows, and the archive rules: hide, never delete, never touch a run that
is still going or can still be resumed.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import local_session as ls
from src.db import client as _client
from src.db import studies as st

_REAL_EXECUTE = _client.execute
_REAL_FETCH_ONE = _client.fetch_one
_REAL_FETCH_ALL = _client.fetch_all

Q = "Does the equity premium remain unpredictable out-of-sample?"
TOKEN = "study-test-token-0123456789"
BASE = "http://127.0.0.1:8290"


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    """A real SQLite database in a temp folder (the autouse mocks restored to the real client)."""
    path = tmp_path / "papers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
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


def _run(coro):
    return asyncio.run(coro)


async def _add(
    rq: str = Q,
    *,
    status: str = "failed",
    title: str | None = None,
    pipeline: str = "empirical",
    created: str = "2026-06-01 10:00:00",
    key: bool = False,
) -> str:
    pid = str(uuid.uuid4())
    await _client.execute(
        "INSERT INTO papers (id, title, research_question, status, pipeline, created_at, updated_at, study_key) "
        "VALUES (%(id)s, %(t)s, %(rq)s, %(s)s, %(p)s, %(c)s, %(c)s, %(k)s)",
        {
            "id": pid,
            "t": title or rq[:40],
            "rq": rq,
            "s": status,
            "p": pipeline,
            "c": created,
            "k": st.study_key(rq, pipeline) if key else None,
        },
    )
    return pid


def _archived(db: Path) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT id FROM papers WHERE archived_at IS NOT NULL")}


# ── the grouping key ─────────────────────────────────────────────────────────


def test_normalisation_ignores_spacing_case_and_trailing_punctuation():
    a = st.study_key("  Does the equity premium   remain\nunpredictable?  ", "empirical")
    b = st.study_key("does the EQUITY premium remain unpredictable", "empirical")
    c = st.study_key("Does the equity premium remain unpredictable?!.", "empirical")
    assert a == b == c
    assert st.normalise_question("  A  b?\t") == "a b"


def test_a_different_question_is_a_different_study():
    assert st.study_key("Does X raise Y?", "empirical") != st.study_key("Does X lower Y?", "empirical")
    # Punctuation inside the question is content, not noise.
    assert st.study_key("Did NFT (e.g. Blur) trades pay less?", "empirical") != st.study_key(
        "Did NFT trades pay less?", "empirical"
    )


def test_the_template_separates_studies():
    assert st.study_key(Q, "empirical") != st.study_key(Q, "event-study-finance")
    assert st.study_key(Q, None) == st.study_key(Q, "empirical")


def test_a_row_without_a_question_groups_by_its_title():
    assert st.study_key(None, "empirical", "My title") == st.study_key("my title.", "empirical")


# ── backfill on a database from an older e2er ────────────────────────────────


_OLD_SCHEMA = """
CREATE TABLE papers (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, research_question TEXT,
    status TEXT NOT NULL DEFAULT 'idea', mode TEXT NOT NULL DEFAULT 'iterative',
    workspace TEXT, github_repo TEXT, last_error TEXT, max_cost_usd REAL DEFAULT 25.0,
    methodology TEXT NOT NULL DEFAULT 'empirical', model TEXT, backend TEXT,
    governance TEXT NOT NULL DEFAULT 'full', review_stages TEXT,
    pipeline TEXT NOT NULL DEFAULT 'empirical',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER papers_updated_at AFTER UPDATE ON papers FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN UPDATE papers SET updated_at = datetime('now') WHERE id = NEW.id; END;
"""


def test_backfill_on_a_database_without_the_columns(db: Path):
    with sqlite3.connect(db) as c:
        c.executescript(_OLD_SCHEMA)
        for i, rq in enumerate([Q, Q.upper() + "  ", "Another question"]):
            c.execute(
                "INSERT INTO papers (id, title, research_question, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'failed', ?, ?)",
                (str(uuid.uuid4()), f"t{i}", rq, f"2026-05-0{i + 1} 10:00:00", f"2026-05-0{i + 1} 11:00:00"),
            )

    studies, archived = _run(st.list_studies())

    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(papers)")}
        assert {"study_key", "study_override", "archived_at", "run_owner", "heartbeat_at"} <= cols
        assert c.execute("SELECT COUNT(*) FROM papers WHERE study_key IS NULL").fetchone()[0] == 0
        # The backfill is bookkeeping: it must not move the dates the list sorts by.
        dates = sorted(r[0] for r in c.execute("SELECT updated_at FROM papers"))
    assert dates == ["2026-05-01 11:00:00", "2026-05-02 11:00:00", "2026-05-03 11:00:00"]
    assert sorted(len(s.attempts) for s in studies) == [1, 2]
    assert archived == 0
    assert _run(st.ensure_study_keys()) == 0  # idempotent


def test_bootstrap_twice_is_harmless(db: Path):
    _run(st.list_studies())
    _client._sqlite_bootstrapped = False
    _run(st.list_studies())  # re-adds nothing, keeps the trigger


def test_a_status_change_still_moves_updated_at(db: Path):
    """The trigger skips bookkeeping columns only; real changes still count as activity."""
    pid = _run(_add())
    _run(_client.execute("UPDATE papers SET status = 'completed' WHERE id = %(id)s", {"id": pid}))
    with sqlite3.connect(db) as c:
        updated = c.execute("SELECT updated_at FROM papers WHERE id = ?", (pid,)).fetchone()[0]
    assert updated != "2026-06-01 10:00:00"


# ── the list: grouping, versions, counts ─────────────────────────────────────


def _seed_pilot(db: Path) -> dict[str, str]:
    async def go():
        ids = {}
        ids["v1"] = await _add(Q, status="rejected", title="Pilot 1", created="2026-06-01 10:00:00")
        ids["v2"] = await _add(Q + "  ", status="failed", title="Pilot 2", created="2026-06-02 10:00:00")
        ids["v3"] = await _add(Q.lower(), status="completed", title="Pilot 3", created="2026-06-03 10:00:00")
        ids["v4"] = await _add(Q, status="cancelled", title="Pilot 4", created="2026-06-04 10:00:00", key=True)
        ids["other"] = await _add("Another question?", status="completed", created="2026-07-01 10:00:00")
        ids["tpl"] = await _add(Q, status="paused", pipeline="event-study-finance", created="2026-05-01 10:00:00")
        return ids

    return _run(go())


def test_list_groups_attempts_and_counts_them(db: Path):
    ids = _seed_pilot(db)
    studies, archived = _run(st.list_studies())

    assert len(studies) == 3
    pilot = next(s for s in studies if len(s.attempts) == 4)
    assert [a["id"] for a in pilot.attempts] == [ids["v1"], ids["v2"], ids["v3"], ids["v4"]]
    assert [a["version"] for a in pilot.attempts] == [1, 2, 3, 4]
    assert pilot.title == "Pilot 4"  # the latest attempt names the study
    d = pilot.as_dict()
    assert d["attempts"] == 4
    assert d["summary"] == "1 completed · 1 rejected · 1 failed · 1 cancelled"
    assert d["latest_status"] == "cancelled"
    # Most recent activity first.
    assert [len(s.attempts) for s in studies] == [1, 4, 1]
    assert archived == 0


def test_search_matches_question_title_and_key(db: Path):
    _seed_pilot(db)
    assert len(_run(st.list_studies("another"))[0]) == 1
    assert len(_run(st.list_studies("pilot 2"))[0]) == 1
    key = _run(st.list_studies("another"))[0][0].key
    assert [s.key for s in _run(st.list_studies(key))[0]] == [key]
    assert _run(st.list_studies("no such thing"))[0] == []


def test_move_to_another_study_split_off_and_back(db: Path):
    ids = _seed_pilot(db)
    studies, _ = _run(st.list_studies())
    other = next(s for s in studies if s.title.startswith("Another"))

    # Split v2 off into a study of its own.
    new_key = _run(st.move_attempt(ids["v2"], "new"))
    studies, _ = _run(st.list_studies())
    assert len(studies) == 4
    solo = next(s for s in studies if s.key == new_key)
    assert [a["id"] for a in solo.attempts] == [ids["v2"]] and solo.attempts[0]["moved"]
    pilot = next(s for s in studies if len(s.attempts) == 3)
    assert [a["version"] for a in pilot.attempts] == [1, 2, 3]

    # Move it into another study, by that study's key …
    assert _run(st.move_attempt(ids["v2"][:8], other.key)) == other.key
    assert len(next(s for s in _run(st.list_studies())[0] if s.key == other.key).attempts) == 2

    # … and back next to v1, by naming an attempt there: the override is cleared.
    _run(st.move_attempt(ids["v2"], ids["v1"]))
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT study_override FROM papers WHERE id = ?", (ids["v2"],)).fetchone()[0] is None
    assert len(_run(st.list_studies())[0]) == 3


def test_move_to_an_unknown_study_is_refused(db: Path):
    ids = _seed_pilot(db)
    with pytest.raises(st.StudyError):
        _run(st.move_attempt(ids["v1"], "0000000000"))


# ── archiving ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["paused", "designing", "in_progress", "revision", "idea", "data_approval"])
def test_archive_refuses_running_and_paused_attempts(db: Path, status: str):
    pid = _run(_add(status=status))
    with pytest.raises(st.StudyError) as e:
        _run(st.archive_attempt(pid))
    msg = str(e.value)
    assert "v1" in msg
    assert ("paused" in msg) if status == "paused" else ("running" in msg or "approval" in msg)
    assert "only takes attempts that have ended" in msg
    assert _archived(db) == set()


def test_archive_study_refuses_when_one_attempt_is_paused(db: Path):
    a = _run(_add(status="failed", created="2026-06-01 10:00:00"))
    _run(_add(status="paused", created="2026-06-02 10:00:00"))
    with pytest.raises(st.StudyError) as e:
        _run(st.archive_study(a))
    assert str(e.value).startswith("Nothing was archived: v2 (")
    assert "is paused and can still be resumed" in str(e.value)
    assert _archived(db) == set()


def test_archive_and_unarchive_a_study(db: Path):
    ids = _seed_pilot(db)
    study, n = _run(st.archive_study(ids["v3"]))
    assert n == 4
    studies, archived = _run(st.list_studies())
    assert archived == 4 and len(studies) == 2
    # Shown again with the archived switch, versions unchanged.
    everything, _ = _run(st.list_studies(show_archived=True))
    assert len(everything) == 3
    _, back = _run(st.unarchive_study(study.key))
    assert back == 4 and _archived(db) == set()


def test_archive_one_attempt_keeps_the_row_and_the_version_numbers(db: Path):
    ids = _seed_pilot(db)
    _run(st.archive_attempt(ids["v2"]))
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 6  # nothing deleted
    pilot = next(s for s in _run(st.list_studies())[0] if len(s.attempts) == 4)
    assert [a["version"] for a in pilot.visible] == [1, 3, 4]
    assert pilot.as_dict()["attempts"] == 3 and pilot.as_dict()["archived"] == 1
    _run(st.unarchive_attempt(ids["v2"]))
    assert _archived(db) == set()


def test_bulk_archive_dry_run_changes_nothing_and_apply_takes_only_confirmed_ids(db: Path):
    ids = _seed_pilot(db)
    preview = _run(st.failed_candidates())
    assert {a["id"] for a in preview} == {ids["v2"], ids["v4"]}
    assert _archived(db) == set()

    # Something fails after the count was shown: it is not swept in.
    late = _run(_add("Late question", status="failed", created="2026-08-01 10:00:00"))
    done = _run(st.archive_failed([a["id"] for a in preview]))
    assert {a["id"] for a in done} == {ids["v2"], ids["v4"]}
    assert _archived(db) == {ids["v2"], ids["v4"]}
    assert late not in _archived(db)


def test_archiving_does_not_touch_files(db: Path, tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "paper.tex").write_text("x")
    pid = _run(_add())
    _run(_client.execute("UPDATE papers SET workspace = %(w)s WHERE id = %(id)s", {"w": str(ws), "id": pid}))
    _run(st.archive_attempt(pid))
    assert (ws / "paper.tex").read_text() == "x"


# ── the command line ─────────────────────────────────────────────────────────


def test_cli_list_and_attempts(db: Path, capsys):
    from src import cli_studies

    ids = _seed_pilot(db)
    _run(st.archive_attempt(ids["v2"]))
    assert cli_studies.list_studies() == 0
    out = capsys.readouterr().out
    assert out.startswith("3 studies · 5 attempts (1 archived not shown; --archived shows them)")
    assert "3 attempts · 1 archived · latest: cancelled" in out
    assert "v1" not in out

    cli_studies.list_studies(attempts=True, archived=True)
    out = capsys.readouterr().out
    assert "4 attempts" in out
    assert f"v2   {ids['v2'][:8]}  failed" in out and "[archived]" in out


def test_cli_archive_failed_is_a_dry_run_without_yes(db: Path, capsys):
    from src import cli_studies

    ids = _seed_pilot(db)
    assert cli_studies.archive(failed=True) == 0
    out = capsys.readouterr().out
    assert "Would archive 2 failed or cancelled attempts" in out and "dry run" in out
    assert _archived(db) == set()

    assert cli_studies.archive(failed=True, yes=True) == 0
    assert "Archived 2 attempts" in capsys.readouterr().out
    assert _archived(db) == {ids["v2"], ids["v4"]}


def test_cli_archive_refusal_and_unarchive(db: Path, capsys):
    from src import cli_studies

    ids = _seed_pilot(db)
    assert cli_studies.archive(ids["tpl"][:8]) == 1
    assert "paused" in capsys.readouterr().err
    assert cli_studies.archive(ids["v1"][:8]) == 0
    assert cli_studies.unarchive(ids["v1"]) == 0
    assert _archived(db) == set()
    assert cli_studies.archive(study=ids["v3"]) == 0
    assert "Archived 4 attempts" in capsys.readouterr().out
    assert cli_studies.unarchive(study=ids["v3"]) == 0
    assert cli_studies.archive("ffffffff") == 1


# ── the dashboard and its guard ──────────────────────────────────────────────


def _http(*, cookie: bool) -> TestClient:
    from src.api.app import app

    c = TestClient(app, base_url=BASE, client=("127.0.0.1", 50000))
    if cookie:
        c.cookies.set("e2er_session_8290", TOKEN)
    return c


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/studies"),
        ("GET", "/api/archive/failed"),
        ("POST", "/api/archive/failed"),
        ("POST", "/api/papers/{id}/archive"),
        ("POST", "/api/papers/{id}/unarchive"),
        ("POST", "/api/papers/{id}/move"),
        ("POST", "/api/studies/{key}/archive"),
        ("POST", "/api/studies/{key}/unarchive"),
    ],
)
def test_the_endpoints_need_the_session(db: Path, monkeypatch, method: str, path: str):
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    pid = _run(_add())
    url = path.format(id=pid, key=st.study_key(Q, "empirical"))
    body = {"ids": [pid]} if "failed" in path else {"study": "new"}
    r = _http(cookie=False).request(method, url, json=body if method == "POST" else None)
    assert r.status_code == 403
    assert _archived(db) == set()


def test_dashboard_archive_flow(db: Path, monkeypatch):
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    ids = _seed_pilot(db)
    c = _http(cookie=True)

    page = c.get("/").text
    assert "4 attempts" in page and "Archive failed and cancelled attempts" in page
    assert page.count('href="/studies/') == 3

    preview = c.get("/api/archive/failed").json()
    assert preview["count"] == 2
    r = c.post("/api/archive/failed", json={"ids": [a["id"] for a in preview["attempts"]]})
    assert r.json()["archived"] == 2

    page = c.get("/").text
    assert "Show archived (2)" in page and "2 archived" in page
    shown = c.get("/?archived=1").text
    assert "Unarchive" in shown

    refused = c.post(f"/api/papers/{ids['tpl']}/archive")
    assert refused.status_code == 409 and "paused" in refused.json()["detail"]

    key = st.study_key(Q, "empirical")
    study = c.get(f"/studies/{key}").text
    assert "Move to study…" in study and "v3" in study and "v2" not in study.split("<tbody>")[1]
    assert "v2" in c.get(f"/studies/{key}?archived=1").text
    assert c.get("/studies/zzzz").status_code == 404

    assert c.post(f"/api/studies/{key}/unarchive").json()["unarchived"] == 2
    moved = c.post(f"/api/papers/{ids['v1']}/move", json={"study": "new"}).json()
    assert moved["study"] != key

    paper = c.get(f"/papers/{ids['v3']}").text
    assert "v2 of 3" in paper  # v1 was split off, so v3 is now the second of three


# ── cancelling a paused attempt ──────────────────────────────────────────────


def _events(db: Path, pid: str) -> list[tuple[str, str]]:
    with sqlite3.connect(db) as c:
        return list(c.execute("SELECT event_type, payload FROM pipeline_events WHERE paper_id = ?", (pid,)))


def test_cancel_a_paused_attempt_records_who_and_when_and_keeps_files(db: Path, tmp_path: Path):
    import json

    ws = tmp_path / "ws-paused"
    ws.mkdir()
    (ws / "event_design.json").write_text("{}")
    (ws / ".pipeline_state.json").write_text(
        json.dumps({"paper_id": "x", "mode": "single_pass", "pending_review_stage": "g"})
    )
    pid = _run(_add(status="paused"))
    _run(_client.execute("UPDATE papers SET workspace = %(w)s WHERE id = %(id)s", {"w": str(ws), "id": pid}))

    done = _run(st.cancel_attempt(pid[:8], via="command line"))

    assert done["status"] == "cancelled"
    with sqlite3.connect(db) as c:
        status, err = c.execute("SELECT status, last_error FROM papers WHERE id = ?", (pid,)).fetchone()
    assert status == "cancelled" and err == "Cancelled by the researcher."
    (etype, payload), *_ = _events(db, pid)
    ev = json.loads(payload)
    assert etype == "researcher_action"
    assert ev["action"] == "cancel" and ev["remark"] == "cancelled by the researcher"
    assert ev["by"] == "researcher" and ev["via"] == "command line" and ev["at"].endswith("Z")
    assert ev["previous_status"] == "paused" and ev["step"] == "g"
    assert (ws / "event_design.json").exists()  # the workspace is kept

    # Now it archives like any cancelled attempt.
    _run(st.archive_attempt(pid))
    assert _archived(db) == {pid}


def test_the_dossier_lists_the_cancellation(db: Path):
    from src.core.dossier import researcher_step

    pid = _run(_add(status="paused"))
    _run(st.cancel_attempt(pid))
    import json

    (_etype, payload), *_ = _events(db, pid)
    step = researcher_step(json.loads(payload), "2026-09-29 10:00:00")
    assert step["type"] == "researcher" and step["action"] == "cancel"
    assert step["remark"] == "cancelled by the researcher"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "rejected", "designing", "in_progress"])
def test_cancel_refuses_attempts_that_are_not_paused(db: Path, status: str):
    pid = _run(_add(status=status))
    with pytest.raises(st.StudyError) as e:
        _run(st.cancel_attempt(pid))
    assert ("already" in str(e.value)) if status in st.ARCHIVABLE else ("still running" in str(e.value))
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT status FROM papers WHERE id = ?", (pid,)).fetchone()[0] == status
    assert _events(db, pid) == []


def test_cancel_refuses_an_attempt_another_live_process_owns(db: Path):
    import json
    import os

    from src.core import run_owner

    pid = _run(_add(status="paused"))
    other = {**run_owner.this_owner(8280), "instance": "the-other-server", "pid": os.getppid(), "started": None}
    _run(_client.execute("UPDATE papers SET run_owner = %(o)s WHERE id = %(id)s", {"o": json.dumps(other), "id": pid}))
    with pytest.raises(st.StudyError) as e:
        _run(st.cancel_attempt(pid))
    assert "another e2er process" in str(e.value) and "port 8280" in str(e.value)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT status FROM papers WHERE id = ?", (pid,)).fetchone()[0] == "paused"

    # A dead owner does not block it.
    dead = {**other, "pid": 2**22 + 7}
    _run(_client.execute("UPDATE papers SET run_owner = %(o)s WHERE id = %(id)s", {"o": json.dumps(dead), "id": pid}))
    assert _run(st.cancel_attempt(pid))["status"] == "cancelled"


def test_cli_cancel_a_paused_attempt(db: Path, capsys, monkeypatch):
    from src import cli_status

    pid = _run(_add(status="paused"))
    monkeypatch.setattr("builtins.input", lambda _p: "n")
    assert cli_status.cancel(pid[:8]) == 0
    assert "Nothing was cancelled" in capsys.readouterr().out
    assert cli_status.cancel(pid[:8], yes=True) == 0
    assert "Cancelled v1" in capsys.readouterr().out
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT status FROM papers WHERE id = ?", (pid,)).fetchone()[0] == "cancelled"


def test_dashboard_cancel_attempt(db: Path, monkeypatch):
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    pid = _run(_add(status="paused"))
    assert _http(cookie=False).post(f"/api/papers/{pid}/cancel-attempt").status_code == 403
    c = _http(cookie=True)
    key = st.study_key(Q, "empirical")
    assert "Cancel attempt" in c.get(f"/studies/{key}").text
    assert "cancel-attempt" in c.get(f"/htmx/papers/{pid}/live").text
    r = c.post(f"/api/papers/{pid}/cancel-attempt")
    assert r.status_code == 200 and "files are kept" in r.json()["message"]
    again = c.post(f"/api/papers/{pid}/cancel-attempt")
    assert again.status_code == 409 and "already cancelled" in again.json()["detail"]
    assert "cancel-attempt" not in c.get(f"/htmx/papers/{pid}/live").text


def test_cli_list_on_an_empty_database_ends_its_line(db: Path, capsys):
    from src import cli_studies

    assert cli_studies.list_studies() == 0
    assert capsys.readouterr().out == "No studies yet.\n"
