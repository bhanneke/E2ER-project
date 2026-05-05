"""Data module — audit log for all Allium queries."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID


async def log_query(
    paper_id: str,
    specialist: str,
    query_sql: str,
    query_type: str,
    fields_requested: list[str],
    aggregation_level: str,
    estimated_rows: int | None = None,
    validation_warnings: list[str] | None = None,
) -> str:
    """Create a data_query_record and return its ID."""
    import json

    from ...db.client import fetch_one

    row = await fetch_one(
        """
        INSERT INTO data_query_records
            (paper_id, specialist, query_sql, query_type, fields_requested,
             aggregation_level, estimated_rows, validation_status)
        VALUES (%(paper_id)s, %(specialist)s, %(sql)s, %(qtype)s,
                %(fields)s, %(agg)s, %(est_rows)s, 'pending')
        RETURNING id
        """,
        {
            "paper_id": paper_id,
            "specialist": specialist,
            "sql": query_sql,
            "qtype": query_type,
            "fields": json.dumps(fields_requested),
            "agg": aggregation_level,
            "est_rows": estimated_rows,
        },
    )
    return str(row["id"]) if row else ""


async def mark_approved(query_id: str, approved_by: str = "auto") -> None:
    from ...db.client import execute

    await execute(
        """
        UPDATE data_query_records
        SET validation_status = 'approved', approved_by = %(by)s, approved_at = NOW()
        WHERE id = %(id)s
        """,
        {"id": query_id, "by": approved_by},
    )


async def mark_executed(query_id: str, actual_rows: int) -> None:
    from ...db.client import execute

    await execute(
        "UPDATE data_query_records SET executed_at = NOW(), actual_rows = %(rows)s WHERE id = %(id)s",
        {"id": query_id, "rows": actual_rows},
    )


async def create_approval_request(query_record_id: str, paper_id: str) -> str:
    from ...db.client import fetch_one

    row = await fetch_one(
        """
        INSERT INTO data_approval_requests (query_record_id, paper_id)
        VALUES (%(qid)s, %(pid)s)
        RETURNING id
        """,
        {"qid": query_record_id, "pid": paper_id},
    )
    return str(row["id"]) if row else ""


async def get_approval_status(query_id: str) -> str:
    """Returns 'pending', 'approved', or 'rejected'."""
    from ...db.client import fetch_one

    row = await fetch_one(
        "SELECT status FROM data_approval_requests WHERE query_record_id = %(qid)s ORDER BY created_at DESC LIMIT 1",
        {"qid": query_id},
    )
    return row["status"] if row else "pending"


async def export_audit_log(paper_id: str) -> list[dict[str, Any]]:
    """Export full query audit for the replication package."""
    from ...db.client import fetch_all

    return await fetch_all(
        """
        SELECT
            dqr.id, dqr.query_type, dqr.query_sql,
            dqr.fields_requested, dqr.aggregation_level,
            dqr.estimated_rows, dqr.actual_rows,
            dqr.validation_status, dqr.approved_by, dqr.approved_at,
            dqr.executed_at, dqr.created_at
        FROM data_query_records dqr
        WHERE dqr.paper_id = %(pid)s
        ORDER BY dqr.created_at
        """,
        {"pid": paper_id},
    )


async def write_audit_csv(paper_id: str, output_path: "Path") -> int:
    """Write audit_log.csv to the replication package directory. Returns row count."""
    import csv
    from pathlib import Path as _Path

    rows = await export_audit_log(paper_id)
    output_path = _Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "id", "query_type", "query_sql", "fields_requested", "aggregation_level",
        "estimated_rows", "actual_rows", "validation_status", "approved_by",
        "approved_at", "executed_at", "created_at",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return len(rows)


async def write_data_queries_sql(paper_id: str, output_path: "Path") -> int:
    """Write data_queries.sql with all production queries used. Returns query count."""
    from pathlib import Path as _Path

    rows = await export_audit_log(paper_id)
    production = [r for r in rows if r.get("query_type") == "production"]

    output_path = _Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "-- E2ER v3 data queries for replication",
        f"-- paper_id: {paper_id}",
        f"-- generated: {datetime.now(UTC).isoformat()}",
        "",
    ]
    for i, row in enumerate(production, 1):
        lines.append(f"-- Query {i}: {row.get('query_type', '')} ({row.get('aggregation_level', '')})")
        lines.append(f"-- Fields: {row.get('fields_requested', '')}")
        lines.append(f"-- Status: {row.get('validation_status', '')} | Approved by: {row.get('approved_by', '')}")
        lines.append(row.get("query_sql", "").strip())
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return len(production)
