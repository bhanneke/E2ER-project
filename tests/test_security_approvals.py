"""A production query's approval is the researcher's, not a row a model wrote (security review 2026-10-23)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import app
from src.modules.data import approval_seal as seal
from src.modules.data.audit import get_approval_status_with_note

from .platform_help import owner_only

QID = "3c9d2b1e-7a4f-4e8b-9d6c-1f2a3b4c5d6e"
SQL = "SELECT block_time, amount FROM dex.trades WHERE block_time >= '2026-01-01'"


def _db(status: str, sql: str = SQL):
    async def fetch_one(query, params=None):
        if "data_approval_requests" in query:
            return {"status": status, "note": ""}
        if "data_query_records" in query:
            return {"query_sql": sql}
        return None

    return patch("src.db.client.fetch_one", side_effect=fetch_one)


def test_an_approved_row_without_the_dashboards_seal_stays_pending():
    with _db("approved"):
        assert asyncio.run(get_approval_status_with_note(QID)) == ("pending", "")


def test_the_dashboards_approval_counts_and_only_for_the_same_sql(as_approver):
    with patch("src.db.client.execute"), _db("approved"):
        r = TestClient(app).post(f"/api/queries/{QID}/approve", json={"approved": True, "note": "ok"})
        assert r.status_code == 200
        assert asyncio.run(get_approval_status_with_note(QID))[0] == "approved"
    with _db("approved", sql=SQL + " OR 1=1"):
        assert asyncio.run(get_approval_status_with_note(QID))[0] == "pending"
    assert owner_only(seal.key_file())


def test_a_forged_seal_file_without_the_key_does_not_count():
    seal.seals_dir().mkdir(parents=True, exist_ok=True)
    (seal.seals_dir() / f"{QID}.json").write_text('{"status": "approved", "mac": "00"}', encoding="utf-8", newline="\n")
    with _db("approved"):
        assert asyncio.run(get_approval_status_with_note(QID))[0] == "pending"


def test_a_rejection_needs_no_seal():
    with _db("rejected"):
        assert asyncio.run(get_approval_status_with_note(QID))[0] == "rejected"


def test_a_query_id_that_is_a_path_is_refused():
    r = TestClient(app).post("/api/queries/..%2F..%2Fx/approve", json={"approved": True, "note": ""})
    assert r.status_code == 404


def test_the_session_token_alone_cannot_approve(monkeypatch):
    """Review of 2026-11-21: a script that read ~/.e2er/session-<port>.json approved a production query."""
    import hashlib

    monkeypatch.setenv("E2ER_APPROVER_SHA256", hashlib.sha256(b"the-real-key").hexdigest())
    with patch("src.db.client.execute") as ex, _db("pending"):
        r = TestClient(app).post(f"/api/queries/{QID}/approve", json={"approved": True, "note": ""})
        assert r.status_code == 403
        assert "browser e2er opened" in r.json()["detail"]
        ex.assert_not_called()
        assert not (seal.seals_dir() / f"{QID}.json").exists() or not seal.is_sealed(QID, "approved", SQL)
        # Refusing needs no more than the session.
        assert TestClient(app).post(f"/api/queries/{QID}/approve", json={"approved": False}).status_code == 200


def test_a_made_up_cookie_or_key_does_not_approve(monkeypatch):
    import hashlib

    monkeypatch.setenv("E2ER_APPROVER_SHA256", hashlib.sha256(b"the-real-key").hexdigest())
    c = TestClient(app)
    c.cookies.set("e2er_approver_80", "guess")
    with patch("src.db.client.execute"), _db("pending"):
        assert c.post(f"/api/queries/{QID}/approve", json={"approved": True}).status_code == 403
    assert c.post("/api/session/approver", json={"key": "guess"}).status_code == 403


def test_without_an_approver_key_nobody_approves(monkeypatch):
    """A server started without the hash (an old launcher) refuses every approval rather than trusting the token."""
    monkeypatch.delenv("E2ER_APPROVER_SHA256", raising=False)
    c = TestClient(app)
    c.cookies.set("e2er_approver_80", "")
    with patch("src.db.client.execute"), _db("pending"):
        assert c.post(f"/api/queries/{QID}/approve", json={"approved": True}).status_code == 403


def test_the_launch_key_buys_the_approver_cookie(monkeypatch):
    import hashlib

    monkeypatch.setenv("E2ER_APPROVER_SHA256", hashlib.sha256(b"the-real-key").hexdigest())
    c = TestClient(app)
    r = c.post("/api/session/approver", json={"key": "the-real-key"})
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    with patch("src.db.client.execute"), _db("approved"):
        assert c.post(f"/api/queries/{QID}/approve", json={"approved": True}).status_code == 200
