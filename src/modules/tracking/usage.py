"""Token and cost usage recording."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..llm.base import TokenUsage
from .costs import compute_cost


@dataclass
class UsageRecord:
    paper_id: str
    specialist: str
    backend: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal
    work_order_id: str | None = None
    timestamp: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


async def save_usage(
    paper_id: str,
    specialist: str,
    backend: str,
    model: str,
    usage: TokenUsage,
    work_order_id: str | None = None,
) -> None:
    """Save a usage record to the database."""
    from ...db.client import execute

    cost = compute_cost(model, usage)
    await execute(
        """
        INSERT INTO llm_usage
            (paper_id, specialist, work_order_id, backend, model,
             input_tokens, output_tokens, cache_read_tokens,
             cache_write_tokens, cost_usd)
        VALUES (%(paper_id)s, %(specialist)s, %(work_order_id)s, %(backend)s,
                %(model)s, %(input_tokens)s, %(output_tokens)s,
                %(cache_read_tokens)s, %(cache_write_tokens)s, %(cost_usd)s)
        """,
        {
            "paper_id": paper_id,
            "specialist": specialist,
            "work_order_id": work_order_id,
            "backend": backend,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "cost_usd": str(cost),
        },
    )


async def check_budget(paper_id: str, max_cost_usd: float) -> None:
    """Raise BudgetExceeded if cumulative cost has hit the per-paper cap.

    Called at phase boundaries by the pipeline runner. Read-only; reuses the
    same llm_usage rows that compute_cost has already populated.
    """
    from ...core.strategist.state import BudgetExceeded
    from ...db.client import fetch_one

    try:
        row = await fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0)::float AS spent FROM llm_usage WHERE paper_id = %(id)s",
            {"id": paper_id},
        )
    except Exception:
        # DB unavailable — skip the check rather than crash.
        return
    spent = float((row or {}).get("spent", 0.0))
    if spent >= max_cost_usd:
        raise BudgetExceeded(spent=spent, cap=max_cost_usd)


async def get_paper_usage(paper_id: str) -> dict[str, Any]:
    """Get aggregated usage totals and per-specialist breakdown for a paper."""
    from ...db.client import fetch_one, fetch_all

    totals = await fetch_one(
        """
        SELECT
            COUNT(*)::int AS specialist_calls,
            COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
            COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0)::bigint AS cache_read_tokens,
            COALESCE(SUM(cost_usd), 0)::numeric AS total_cost_usd
        FROM llm_usage WHERE paper_id = %(id)s
        """,
        {"id": paper_id},
    )
    breakdown = await fetch_all(
        "SELECT specialist, SUM(cost_usd)::numeric AS cost_usd, SUM(input_tokens+output_tokens)::bigint AS tokens FROM llm_usage WHERE paper_id = %(id)s GROUP BY specialist ORDER BY cost_usd DESC",
        {"id": paper_id},
    )
    return {"totals": totals or {}, "by_specialist": breakdown}


async def get_usage_summary() -> dict[str, Any]:
    """Aggregate usage across all papers."""
    from ...db.client import fetch_one

    row = await fetch_one(
        """
        SELECT
            COUNT(DISTINCT paper_id) AS n_papers,
            SUM(input_tokens) AS total_input_tokens,
            SUM(output_tokens) AS total_output_tokens,
            SUM(cache_read_tokens) AS total_cache_read_tokens,
            SUM(cost_usd) AS total_cost_usd
        FROM llm_usage
        """
    )
    return row or {}
