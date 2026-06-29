"""The ``query_data`` tool — read-only SQL over the paper's ``data.db``.

The per-paper data warehouse (``src/db/paper_data_db.py``) holds the
researcher's imported BYOD files plus any external series the agent has
materialized. This tool lets data/econometrics specialists query it with real
SQL — aggregations, joins, filters — rather than loading whole files into the
model context.

Safety: queries run through ``read_only_query``, which validates the statement
and opens the DB ``mode=ro`` + ``PRAGMA query_only=ON``. Each executed query is
recorded best-effort to ``data_query_records`` (audit trail for the replication
package).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ...db.paper_data_db import MAX_RESULT_ROWS, DataQueryError, read_only_query
from ...logging_config import get_logger
from ..llm.base import ToolHandler

logger = get_logger(__name__)

QUERY_DATA_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_data",
        "description": (
            "Run a read-only SQL SELECT against this paper's local data warehouse (data.db). "
            "It holds the researcher's imported data files and any external series you have "
            "materialized — the AVAILABLE TABLES (names, columns, row counts, samples) are listed "
            "in your context under 'Local Data Warehouse'. Use real SQL: aggregate, join, filter, "
            "window. Returns column headers + rows (capped at "
            f"{MAX_RESULT_ROWS}). One SELECT/WITH statement only; no writes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single read-only SQL SELECT (or WITH) statement.",
                },
            },
            "required": ["sql"],
        },
    },
]


def _format_result(result: dict[str, Any]) -> str:
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    payload: dict[str, Any] = {"columns": columns, "rows": rows, "row_count": result.get("row_count", len(rows))}
    if result.get("truncated"):
        payload["note"] = f"results truncated to {MAX_RESULT_ROWS} rows; refine with LIMIT/WHERE/aggregation"
    return json.dumps(payload, default=str)


class QueryDataToolHandler(ToolHandler):
    """Handles ``query_data`` for one paper run (bound to its workspace)."""

    _MAX_CALLS = 100

    def __init__(self, paper_id: str, workspace: Path) -> None:
        self._paper_id = paper_id
        self._workspace = Path(workspace)
        self._calls = 0

    def can_handle(self, tool_name: str) -> bool:
        return tool_name == "query_data"

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name != "query_data":
            return json.dumps({"error": f"unknown tool: {tool_name}"})
        if self._calls >= self._MAX_CALLS:
            return json.dumps(
                {"error": f"query_data budget exhausted ({self._MAX_CALLS} calls). Proceed with the data you have."}
            )
        self._calls += 1

        sql = (tool_input.get("sql") or "").strip()
        if not sql:
            return json.dumps({"error": "missing 'sql'"})
        try:
            result = await read_only_query(self._workspace, sql)
        except DataQueryError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:  # noqa: BLE001 — never crash the tool loop
            logger.warning("query_data unexpected error: %s", e)
            return json.dumps({"error": f"query failed: {e}"})

        await self._audit(sql, int(result.get("row_count", 0)))
        return _format_result(result)

    async def _audit(self, sql: str, actual_rows: int) -> None:
        """Record the executed query to data_query_records (best-effort).

        Logged as ``feasibility`` (the only non-approval query_type the schema
        CHECK allows) — local SQL is read-only and never needs approval.
        """
        try:
            from .audit import log_query, mark_executed

            specialist = os.environ.get("E2ER_SPECIALIST") or "data_specialist"
            record_id = await log_query(
                paper_id=self._paper_id,
                specialist=specialist,
                query_sql=sql,
                query_type="feasibility",
                fields_requested=[],
                aggregation_level="local_data_db",
            )
            await mark_executed(record_id, actual_rows)
        except Exception as e:  # noqa: BLE001 — audit must never break a query
            logger.debug("query_data audit skipped: %s", e)
