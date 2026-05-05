"""Data module — Allium tool definitions and tool handler."""
from __future__ import annotations

import json
from typing import Any

from ...logging_config import get_logger
from ..llm.base import ToolHandler

logger = get_logger(__name__)

ALLIUM_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_allium",
        "description": (
            "Submit a SQL query to Allium blockchain data. "
            "FEASIBILITY queries (query_type='feasibility') run against a 1000-row sample "
            "and are auto-approved. "
            "PRODUCTION queries require human approval and will return a query_id to poll. "
            "All queries must: (1) list explicit fields — no SELECT *, "
            "(2) use only fields from data_dictionary.json, "
            "(3) include a time-bound WHERE clause, "
            "(4) justify transaction-level granularity if applicable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "The SQL query to execute"},
                "query_type": {
                    "type": "string",
                    "enum": ["feasibility", "production"],
                    "description": "feasibility=sample run (auto-approved), production=full run (human approval required)",
                },
                "fields_requested": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit list of column names selected — must match data_dictionary.json",
                },
                "estimated_rows": {
                    "type": "integer",
                    "description": "Your estimate of the result set size",
                },
                "aggregation_level": {
                    "type": "string",
                    "enum": ["transaction", "event", "daily", "weekly", "custom"],
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this query is needed and what it tests",
                },
                "primary_table": {
                    "type": "string",
                    "description": "Main table being queried (for feasibility-first check)",
                },
            },
            "required": ["sql", "query_type", "fields_requested", "aggregation_level"],
        },
    },
    {
        "name": "check_approval",
        "description": "Check whether a production query has been approved by the researcher.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query_id": {"type": "string", "description": "The query_id returned by query_allium"},
            },
            "required": ["query_id"],
        },
    },
    {
        "name": "list_allium_tables",
        "description": "List available Allium dataset schemas and tables.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class AlliumToolHandler(ToolHandler):
    """Intercepts Allium tool calls and routes through the guardrail layer."""

    def __init__(self, paper_id: str, specialist: str, dictionary: Any) -> None:
        self._paper_id = paper_id
        self._specialist = specialist
        self._dictionary = dictionary  # DataDictionary | None

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in {"query_allium", "check_approval", "list_allium_tables"}

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "list_allium_tables":
            return await self._list_tables()
        elif tool_name == "check_approval":
            return await self._check_approval(tool_input["query_id"])
        elif tool_name == "query_allium":
            return await self._query_allium(tool_input)
        return f"Unknown tool: {tool_name}"

    async def _list_tables(self) -> str:
        from .allium import AlliumProvider
        from ...config import get_settings

        settings = get_settings()
        if not settings.allium_api_key:
            return "Allium not configured. Set ALLIUM_API_KEY in .env."
        provider = AlliumProvider(settings.allium_api_key, settings.allium_api_base)
        tables = await provider.list_tables()
        return json.dumps([t.__dict__ for t in tables], indent=2, default=str)

    async def _check_approval(self, query_id: str) -> str:
        from .audit import get_approval_status

        status = await get_approval_status(query_id)
        if status == "approved":
            return f"Query {query_id} has been approved. You may now use the results."
        elif status == "rejected":
            return f"Query {query_id} was rejected by the researcher. Review the rejection note in the dashboard and revise."
        return f"Query {query_id} is pending approval. The researcher has been notified. Check back later."

    async def _query_allium(self, tool_input: dict[str, Any]) -> str:
        from .allium import AlliumProvider
        from .guardrails import QueryValidator
        from .audit import log_query, mark_approved, mark_executed, create_approval_request
        from ...config import get_settings

        settings = get_settings()
        if not settings.allium_api_key:
            return "Allium not configured. Set ALLIUM_API_KEY in .env."

        sql = tool_input["sql"]
        query_type = tool_input["query_type"]
        fields = tool_input.get("fields_requested", [])
        agg_level = tool_input["aggregation_level"]
        rationale = tool_input.get("rationale", "")
        primary_table = tool_input.get("primary_table", "")
        estimated_rows = tool_input.get("estimated_rows")

        # Validate against all 5 guardrails
        if self._dictionary:
            result = await QueryValidator.validate_all(
                sql=sql,
                query_type=query_type,
                fields_requested=fields,
                aggregation_level=agg_level,
                granularity_justification=rationale,
                dictionary=self._dictionary,
                paper_id=self._paper_id,
                primary_table=primary_table,
            )
            if not result.valid:
                return f"Query rejected by guardrails:\n{result.rejection_reason}"

        # Log the query
        query_id = await log_query(
            paper_id=self._paper_id,
            specialist=self._specialist,
            query_sql=sql,
            query_type=query_type,
            fields_requested=fields,
            aggregation_level=agg_level,
            estimated_rows=estimated_rows,
        )

        # Feasibility: enforce LIMIT 1000 and auto-approve
        if query_type == "feasibility":
            exec_sql = _enforce_limit(sql, 1000)
            await mark_approved(query_id, approved_by="auto_feasibility")
        else:
            # Production: create approval request, return pending
            await create_approval_request(query_id, self._paper_id)
            return (
                f"Production query submitted for researcher approval.\n"
                f"query_id: {query_id}\n"
                f"Use check_approval(query_id='{query_id}') to check status. "
                f"The researcher will review the query in the dashboard."
            )

        # Execute feasibility query
        provider = AlliumProvider(settings.allium_api_key, settings.allium_api_base)
        try:
            result = await provider.execute_raw(exec_sql)
            row_count = len(result.get("rows", []))
            await mark_executed(query_id, row_count)
            return (
                f"Feasibility query executed. {row_count} rows returned.\n"
                f"query_id: {query_id}\n"
                f"Sample result (first 3 rows):\n"
                f"{json.dumps(result.get('rows', [])[:3], indent=2, default=str)}\n\n"
                f"Columns: {result.get('columns', [])}"
            )
        except Exception as e:
            logger.error("Allium execution error: %s", e)
            return f"Query execution failed: {e}"


class DeferredAlliumToolHandler(AlliumToolHandler):
    """AlliumToolHandler that reads data_dictionary.json from workspace on each call.

    Unlike AlliumToolHandler (which takes a static dictionary at construction),
    this variant re-reads the file before every tool call so guardrail rule 2
    stays current as data_architect evolves the dictionary during the pipeline run.
    """

    def __init__(self, paper_id: str, specialist: str, workspace: "Path") -> None:
        from pathlib import Path as _Path
        super().__init__(paper_id, specialist, dictionary=None)
        self._workspace = _Path(workspace)

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        self._dictionary = self._read_dictionary()
        return await super().handle(tool_name, tool_input)

    def _read_dictionary(self):
        path = self._workspace / "data_dictionary.json"
        if not path.exists():
            return None
        try:
            from .dictionary import DataDictionary
            return DataDictionary.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None


def _enforce_limit(sql: str, limit: int) -> str:
    """Add or replace LIMIT clause in SQL."""
    import re

    sql = sql.rstrip().rstrip(";")
    if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        return re.sub(r"\bLIMIT\s+\d+", f"LIMIT {limit}", sql, flags=re.IGNORECASE)
    return f"{sql}\nLIMIT {limit}"
