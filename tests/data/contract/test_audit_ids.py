"""Regression: audit inserts generate app-side UUIDs.

SQLite's schema has no id default, so relying on a DB default left `id` NULL
and broke the approval-request join (pending queries never surfaced). These
assert the inserts carry a real uuid in the params and return it.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from src.modules.data import audit


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, TypeError):
        return False


async def test_log_query_generates_id():
    with patch("src.db.client.execute", new=AsyncMock()) as ex:
        rid = await audit.log_query(
            paper_id="p1",
            specialist="data_analyst",
            query_sql="SELECT a FROM x WHERE block_time > '2024-01-01'",
            query_type="feasibility",
            fields_requested=["a"],
            aggregation_level="daily",
        )
    assert _is_uuid(rid)
    sql, params = ex.await_args.args
    assert "id" in params and params["id"] == rid
    assert "(id," in sql.replace(" ", "").replace("\n", "")  # id is in the column list


async def test_create_approval_request_generates_id():
    with patch("src.db.client.execute", new=AsyncMock()) as ex:
        aid = await audit.create_approval_request("query-1", "p1")
    assert _is_uuid(aid)
    _sql, params = ex.await_args.args
    assert params["id"] == aid
