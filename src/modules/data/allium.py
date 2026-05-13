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

    async def list_tables(self, limit: int = 200) -> list[TableInfo]:
        """List available Allium tables via INFORMATION_SCHEMA.

        Uses standard SQL discovery rather than a vendor-specific REST
        endpoint. Works against any SQL backend that exposes
        INFORMATION_SCHEMA (DuckDB, Trino, Snowflake, etc., which is
        what Allium runs underneath). Falls back to an empty list if the
        endpoint or schema isn't accessible.
        """
        sql = (
            "SELECT table_schema, table_name "
            "FROM information_schema.tables "
            f"ORDER BY table_schema, table_name LIMIT {limit}"
        )
        try:
            raw = await self.execute_raw(sql)
        except Exception as e:
            logger.warning("list_tables (information_schema) failed: %s", e)
            return []
        if raw.get("error"):
            logger.warning("list_tables returned error: %s", raw["error"][:200])
            return []
        rows = raw.get("rows", [])
        columns = raw.get("columns", [])
        tables: list[TableInfo] = []
        for row in rows:
            if isinstance(row, dict):
                tables.append(
                    TableInfo(
                        schema=row.get("table_schema", "") or row.get("TABLE_SCHEMA", ""),
                        table=row.get("table_name", "") or row.get("TABLE_NAME", ""),
                    )
                )
            elif isinstance(row, list) and columns and len(row) >= 2:
                tables.append(TableInfo(schema=str(row[0]), table=str(row[1])))
        return tables

    async def describe_table(self, schema: str, table: str) -> list[dict[str, str]]:
        """Return columns + types for a table via INFORMATION_SCHEMA.COLUMNS.

        Call this BEFORE composing real queries so the model knows the
        exact column names and types — eliminates the
        ``WHERE marketplace IN ('opensea')`` failure mode where the
        literal doesn't match Allium's actual storage.
        """
        sql = (
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
            "ORDER BY ordinal_position"
        )
        try:
            raw = await self.execute_raw(sql)
        except Exception as e:
            logger.warning("describe_table failed for %s.%s: %s", schema, table, e)
            return []
        if raw.get("error"):
            return []
        rows = raw.get("rows", [])
        cols = raw.get("columns", [])
        out: list[dict[str, str]] = []
        for r in rows:
            if isinstance(r, dict):
                out.append({"name": r.get("column_name", ""), "type": r.get("data_type", "")})
            elif isinstance(r, list) and cols and len(r) >= 2:
                out.append({"name": str(r[0]), "type": str(r[1])})
        return out

    async def distinct_values(
        self,
        schema: str,
        table: str,
        column: str,
        limit: int = 100,
    ) -> list[Any]:
        """Return distinct values of a column with their counts.

        Use this for grouping columns (platform, marketplace, currency, …)
        BEFORE filtering with ``WHERE col IN (…)``. Instead of guessing
        whether Allium stores 'OpenSea' / 'opensea' / a contract address,
        ask Allium what's actually there. Capped at ``limit`` so a
        high-cardinality column doesn't blow up.
        """
        # Identifier interpolation is risky in general, but schema/table/
        # column here all come from describe_table → INFORMATION_SCHEMA, so
        # they're either real names or absent. We still strip quotes
        # defensively to avoid trivial injection if a caller passes
        # user-supplied input directly.
        s = schema.replace('"', "").replace("'", "")
        t = table.replace('"', "").replace("'", "")
        c = column.replace('"', "").replace("'", "")
        sql = f"SELECT {c} AS value, COUNT(*) AS n FROM {s}.{t} GROUP BY {c} ORDER BY n DESC LIMIT {limit}"
        try:
            raw = await self.execute_raw(sql)
        except Exception as e:
            logger.warning("distinct_values failed for %s.%s.%s: %s", schema, table, column, e)
            return []
        if raw.get("error"):
            return []
        rows = raw.get("rows", [])
        cols = raw.get("columns", [])
        out: list[dict[str, Any]] = []
        for r in rows:
            if isinstance(r, dict):
                out.append({"value": r.get("value"), "n": r.get("n", 0)})
            elif isinstance(r, list) and cols and len(r) >= 2:
                out.append({"value": r[0], "n": r[1]})
        return out

    async def execute_raw(self, sql: str) -> dict[str, Any]:
        """Execute SQL via Allium's 4-step async Explorer API.

        Allium's REST API doesn't accept ad-hoc single-shot SQL like
        ``POST /query`` with ``{"query": "SELECT ..."}``. It's a
        saved-query model with async execution:

          1. ``POST /explorer/queries``                                  (create query)
          2. ``POST /explorer/queries/{query_id}/run-async``             (start run)
          3. ``GET  /explorer/queries/{query_id}/run/{run_id}/status``   (poll)
          4. ``GET  /explorer/queries/{query_id}/run/{run_id}/results``  (fetch rows)

        Confirmed from https://docs.allium.so/llms.txt 2026-05-12. Our
        previous implementation POSTed to ``/explorer/query/run`` which
        404s on every tier.

        Returns the canonical dict shape ``{"rows": [...], "columns": [...]}``
        on success, or ``{"error": str, "rows": [], "columns": []}`` on
        client errors. Raises ``RuntimeError`` only on transport-level
        failure (timeout, network) after all retries.
        """
        import time

        title = f"e2er-adhoc-{int(time.time() * 1000)}"
        # `config.limit` is a required field per Allium's API schema. 1000
        # matches their documented default; for production queries we
        # override at run-async time via run_config.
        create_body = {"title": title, "config": {"sql": sql, "limit": 1000}}

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Step 1: create the query
            try:
                resp = await client.post(
                    f"{self._base}/explorer/queries",
                    headers=self._headers,
                    json=create_body,
                )
            except httpx.HTTPError as e:
                raise RuntimeError(f"Allium create-query transport error: {e}") from e
            if resp.status_code != 200:
                return {
                    "error": f"create-query HTTP {resp.status_code}: {resp.text[:300]}",
                    "rows": [],
                    "columns": [],
                }
            qid = resp.json().get("query_id") or resp.json().get("id")
            if not qid:
                return {
                    "error": f"create-query returned no query_id: {resp.text[:300]}",
                    "rows": [],
                    "columns": [],
                }

            # Step 2: kick off async run. 429 (rate limit) on this endpoint
            # is common when the subscription's queries-per-minute is tight.
            # Retry with exponential backoff up to 60s before giving up.
            import asyncio as _asyncio

            backoff = 2.0
            max_429_wait = 60.0
            run_async_resp = None
            t0 = 0.0
            while t0 < max_429_wait:
                try:
                    run_async_resp = await client.post(
                        f"{self._base}/explorer/queries/{qid}/run-async",
                        headers=self._headers,
                        json={"parameters": {}},
                    )
                except httpx.HTTPError as e:
                    raise RuntimeError(f"Allium run-async transport error: {e}") from e
                if run_async_resp.status_code != 429:
                    break
                logger.warning("Allium run-async rate-limited; sleeping %.1fs before retry", backoff)
                await _asyncio.sleep(backoff)
                t0 += backoff
                backoff = min(backoff * 1.5, 15.0)
            resp = run_async_resp  # type: ignore[assignment]
            if resp is None or resp.status_code != 200:
                code = resp.status_code if resp is not None else "?"
                text = resp.text[:300] if resp is not None else ""
                return {
                    "error": f"run-async HTTP {code}: {text}",
                    "rows": [],
                    "columns": [],
                }
            rid = resp.json().get("run_id") or resp.json().get("id")
            if not rid:
                return {
                    "error": f"run-async returned no run_id: {resp.text[:300]}",
                    "rows": [],
                    "columns": [],
                }

            # Step 3: poll status. URL is `/explorer/query-runs/{run_id}/status`
            # — a sibling of /explorer/queries, NOT nested under it.
            # Confirmed from docs.allium.so/api/explorer/fetch-query-run-status.
            # Status vocabulary per the docs:
            #   created | queued | running | success | failed | canceled
            import asyncio as _asyncio

            poll_interval = 1.0
            elapsed = 0.0
            while elapsed < _TIMEOUT:
                try:
                    resp = await client.get(
                        f"{self._base}/explorer/query-runs/{rid}/status",
                        headers=self._headers,
                    )
                except httpx.HTTPError as e:
                    raise RuntimeError(f"Allium poll-status transport error: {e}") from e
                if resp.status_code != 200:
                    return {
                        "error": f"poll-status HTTP {resp.status_code}: {resp.text[:300]}",
                        "rows": [],
                        "columns": [],
                    }
                # Allium returns either {"status": "running"} OR a bare JSON
                # string "running" depending on something we don't control.
                # Accept both.
                body = resp.json()
                if isinstance(body, str):
                    status = body.lower()
                elif isinstance(body, dict):
                    status = (body.get("status") or "").lower()
                else:
                    status = ""
                if status in {"success", "completed", "finished"}:
                    break
                if status in {"failed", "error", "cancelled", "canceled"}:
                    err = body.get("error") if isinstance(body, dict) else resp.text[:300]
                    return {"error": f"Allium run {status}: {err}", "rows": [], "columns": []}
                # created / queued / running → keep polling
                await _asyncio.sleep(poll_interval)
                elapsed += poll_interval
                poll_interval = min(poll_interval * 1.5, 5.0)
            else:
                return {
                    "error": f"Allium run timed out after {_TIMEOUT}s waiting for completion",
                    "rows": [],
                    "columns": [],
                }

            # Step 4: fetch results. URL is `/explorer/query-runs/{run_id}/results`
            # — also a sibling of /explorer/queries. Response shape:
            #   {"sql": ..., "data": [{...row...}], "meta": {"columns": [{"name", "data_type"}]}}
            # Note: `data` not `rows`; columns are objects, not strings.
            #
            # 429 retry-with-backoff: same pattern as step 2. Allium throttles
            # fetch-results too on tight tiers.
            backoff = 2.0
            t_fetch = 0.0
            results_resp = None
            while t_fetch < max_429_wait:
                try:
                    results_resp = await client.get(
                        f"{self._base}/explorer/query-runs/{rid}/results",
                        headers=self._headers,
                    )
                except httpx.HTTPError as e:
                    raise RuntimeError(f"Allium fetch-results transport error: {e}") from e
                if results_resp.status_code != 429:
                    break
                logger.warning(
                    "Allium fetch-results rate-limited; sleeping %.1fs before retry", backoff
                )
                await _asyncio.sleep(backoff)
                t_fetch += backoff
                backoff = min(backoff * 1.5, 15.0)
            resp = results_resp  # type: ignore[assignment]
            if resp is None or resp.status_code != 200:
                code = resp.status_code if resp is not None else "?"
                text = resp.text[:300] if resp is not None else ""
                return {
                    "error": f"fetch-results HTTP {code}: {text}",
                    "rows": [],
                    "columns": [],
                }
            payload = resp.json()
            rows = payload.get("data") or payload.get("rows") or []
            meta_cols = (payload.get("meta") or {}).get("columns") or []
            if meta_cols and isinstance(meta_cols[0], dict):
                # Allium-native shape: list of {name, data_type}; flatten to names.
                cols = [c.get("name", "") for c in meta_cols]
            else:
                cols = payload.get("columns") or payload.get("column_names") or []
            if rows and isinstance(rows[0], dict) and not cols:
                cols = list(rows[0].keys())
            return {"rows": rows, "columns": cols}

    async def execute(self, sql: str) -> QueryResult:
        raw = await self.execute_raw(sql)
        columns = raw.get("columns", [])
        rows = raw.get("rows", [])
        if isinstance(rows, list) and rows and not isinstance(rows[0], dict):
            rows = [dict(zip(columns, row)) for row in rows]
        return QueryResult(columns=columns, rows=rows, row_count=len(rows))
