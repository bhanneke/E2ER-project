"""Data module — Allium HTTP API provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

_TIMEOUT = 120.0
_MAX_RETRIES = 3


@dataclass
class TableInfo:
    schema: str
    table: str
    description: str = ""
    row_count_estimate: int | None = None


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    query_id: str = ""


class AlliumProvider:
    """Allium blockchain data HTTP API client."""

    def __init__(self, api_key: str, base_url: str = "https://api.allium.so/api/v1") -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

    async def list_tables(self) -> list[TableInfo]:
        """List available Allium tables."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.get(f"{self._base}/schemas", headers=self._headers)
                if resp.status_code == 200:
                    data = resp.json()
                    tables = []
                    for item in data.get("schemas", []):
                        tables.append(
                            TableInfo(
                                schema=item.get("schema", ""),
                                table=item.get("table", ""),
                                description=item.get("description", ""),
                            )
                        )
                    return tables
            except Exception as e:
                logger.warning("list_tables failed: %s", e)
        return []

    async def execute_raw(self, sql: str) -> dict[str, Any]:
        """Execute SQL and return raw response dict."""
        last_error = ""
        for attempt in range(_MAX_RETRIES):
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                try:
                    resp = await client.post(
                        f"{self._base}/explorer/query/run",
                        headers=self._headers,
                        json={"query": sql},
                    )
                    if resp.status_code == 200:
                        return resp.json()
                    if resp.status_code >= 500:
                        last_error = f"HTTP {resp.status_code}"
                        continue
                    return {
                        "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                        "rows": [],
                        "columns": [],
                    }
                except httpx.TimeoutException:
                    last_error = "timeout"
                except httpx.HTTPError as e:
                    last_error = str(e)
                    break
        raise RuntimeError(f"Allium query failed after {_MAX_RETRIES} attempts: {last_error}")

    async def execute(self, sql: str) -> QueryResult:
        raw = await self.execute_raw(sql)
        columns = raw.get("columns", [])
        rows = raw.get("rows", [])
        if isinstance(rows, list) and rows and not isinstance(rows[0], dict):
            rows = [dict(zip(columns, row)) for row in rows]
        return QueryResult(columns=columns, rows=rows, row_count=len(rows))
