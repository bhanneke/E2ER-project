"""Tests for the data audit trail module."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import AsyncMock, patch


async def test_log_query_returns_id():
    row = {"id": "query-uuid-1"}
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row):
        from src.modules.data.audit import log_query

        query_id = await log_query(
            paper_id="paper-uuid",
            specialist="data_analyst",
            query_sql="SELECT block_date, tx_hash FROM uniswap.pools WHERE block_date >= '2024-01-01'",
            query_type="feasibility",
            fields_requested=["block_date", "tx_hash"],
            aggregation_level="transaction",
            estimated_rows=1000,
        )
    assert query_id == "query-uuid-1"


async def test_log_query_no_row_returns_empty():
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        from src.modules.data.audit import log_query

        query_id = await log_query(
            paper_id="p",
            specialist="s",
            query_sql="SELECT x FROM t WHERE dt >= '2024-01-01'",
            query_type="feasibility",
            fields_requested=["x"],
            aggregation_level="daily",
        )
    assert query_id == ""


async def test_mark_approved_calls_update():
    with patch("src.db.client.execute", new_callable=AsyncMock) as mock_exec:
        from src.modules.data.audit import mark_approved

        await mark_approved("query-uuid-1", approved_by="researcher")

    mock_exec.assert_called_once()
    sql = mock_exec.call_args[0][0]
    assert "approved" in sql.lower()


async def test_mark_executed_records_row_count():
    with patch("src.db.client.execute", new_callable=AsyncMock) as mock_exec:
        from src.modules.data.audit import mark_executed

        await mark_executed("query-uuid-1", actual_rows=95432)

    mock_exec.assert_called_once()
    params = mock_exec.call_args[0][1]
    assert params["rows"] == 95432


async def test_create_approval_request_returns_id():
    row = {"id": "approval-uuid-1"}
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row):
        from src.modules.data.audit import create_approval_request

        approval_id = await create_approval_request("query-uuid-1", "paper-uuid")
    assert approval_id == "approval-uuid-1"


async def test_get_approval_status_pending():
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"status": "pending"}):
        from src.modules.data.audit import get_approval_status

        status = await get_approval_status("query-uuid")
    assert status == "pending"


async def test_get_approval_status_approved():
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"status": "approved"}):
        from src.modules.data.audit import get_approval_status

        status = await get_approval_status("query-uuid")
    assert status == "approved"


async def test_get_approval_status_missing_returns_pending():
    with patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=None):
        from src.modules.data.audit import get_approval_status

        status = await get_approval_status("nonexistent")
    assert status == "pending"


async def test_export_audit_log_returns_records():
    rows = [
        {
            "id": "q1",
            "query_type": "feasibility",
            "query_sql": "SELECT x FROM t WHERE dt >= '2024-01-01'",
            "fields_requested": '["x"]',
            "aggregation_level": "daily",
            "estimated_rows": 1000,
            "actual_rows": 987,
            "validation_status": "approved",
            "approved_by": "researcher",
            "approved_at": None,
            "executed_at": None,
            "created_at": None,
        }
    ]
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=rows):
        from src.modules.data.audit import export_audit_log

        result = await export_audit_log("paper-uuid")
    assert len(result) == 1
    assert result[0]["query_type"] == "feasibility"


async def test_write_audit_csv_creates_file(tmp_path: Path):
    rows = [
        {
            "id": "q1",
            "query_type": "production",
            "query_sql": "SELECT x FROM t WHERE dt >= '2024-01-01'",
            "fields_requested": '["x"]',
            "aggregation_level": "daily",
            "estimated_rows": 10000,
            "actual_rows": 9876,
            "validation_status": "approved",
            "approved_by": "researcher",
            "approved_at": "2026-01-01",
            "executed_at": "2026-01-01",
            "created_at": "2026-01-01",
        }
    ]
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=rows):
        from src.modules.data.audit import write_audit_csv

        out = tmp_path / "replication" / "audit_log.csv"
        count = await write_audit_csv("paper-uuid", out)

    assert count == 1
    assert out.exists()
    rows_read = list(csv.DictReader(out.open()))
    assert len(rows_read) == 1
    assert rows_read[0]["query_type"] == "production"
    assert rows_read[0]["actual_rows"] == "9876"


async def test_write_audit_csv_empty(tmp_path: Path):
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=[]):
        from src.modules.data.audit import write_audit_csv

        out = tmp_path / "audit_log.csv"
        count = await write_audit_csv("paper-uuid", out)

    assert count == 0
    assert out.exists()
    rows_read = list(csv.DictReader(out.open()))
    assert rows_read == []


async def test_write_data_queries_sql_creates_file(tmp_path: Path):
    rows = [
        {
            "id": "q1",
            "query_type": "production",
            "query_sql": "SELECT date, amount FROM swaps WHERE date >= '2024-01-01'",
            "fields_requested": '["date", "amount"]',
            "aggregation_level": "daily",
            "estimated_rows": 5000,
            "actual_rows": 4800,
            "validation_status": "approved",
            "approved_by": "researcher",
            "approved_at": "2026-01-01",
            "executed_at": "2026-01-01",
            "created_at": "2026-01-01",
        }
    ]
    with patch("src.db.client.fetch_all", new_callable=AsyncMock, return_value=rows):
        from src.modules.data.audit import write_data_queries_sql

        out = tmp_path / "data_queries.sql"
        count = await write_data_queries_sql("paper-uuid", out)

    assert count == 1
    assert out.exists()
    content = out.read_text()
    assert "SELECT date, amount FROM swaps" in content
    assert "paper_id: paper-uuid" in content
