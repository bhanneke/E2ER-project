"""Token and cost usage recording."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
            self.timestamp = datetime.now(UTC)


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


async def check_budget(
    paper_id: str,
    max_cost_usd: float,
    in_memory_spent: float = 0.0,
) -> None:
    """Raise BudgetExceededError when cumulative cost has hit the per-paper cap.

    Called at phase boundaries by the pipeline runner.

    Two cost sources are combined:
      1. ``llm_usage`` table (durable, populated by ``save_usage``).
      2. ``in_memory_spent`` — the runner's running total of specialist
         + strategist costs since startup. This makes the cap robust when
         the database is unavailable (otherwise spent=0 and the cap never
         trips). The greater of the two values is treated as authoritative
         to avoid double-counting when both sources see the same call.
    """
    from ...core.strategist.state import BudgetExceededError
    from ...db.client import fetch_one

    db_spent = 0.0
    try:
        row = await fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0)::float AS spent FROM llm_usage WHERE paper_id = %(id)s",
            {"id": paper_id},
        )
        db_spent = float((row or {}).get("spent", 0.0))
    except Exception:
        # DB unavailable — fall back to in-memory tracking only.
        db_spent = 0.0

    spent = max(db_spent, float(in_memory_spent))
    if spent >= max_cost_usd:
        raise BudgetExceededError(spent=spent, cap=max_cost_usd)


async def check_budget_by_paper_id(paper_id: str) -> None:
    """Fetch the cap from the papers table and run the budget check.

    Used by code paths (like the dispatcher) that don't have the cap on
    hand. Falls back to default_max_cost_usd when no row exists or the
    DB is unavailable. No-op on lookup failure rather than blocking work.
    """
    from ...config import get_settings
    from ...db.client import fetch_one

    cap = get_settings().default_max_cost_usd
    try:
        row = await fetch_one(
            "SELECT max_cost_usd FROM papers WHERE id = %(id)s",
            {"id": paper_id},
        )
        if row and row.get("max_cost_usd") is not None:
            cap = float(row["max_cost_usd"])
    except Exception:
        # DB unavailable — use default cap. Better to over-trip than to skip the check.
        pass

    await check_budget(paper_id, cap, in_memory_spent=0.0)


async def get_paper_usage(paper_id: str) -> dict[str, Any]:
    """Get aggregated usage totals and per-specialist breakdown for a paper."""
    from ...db.client import fetch_all, fetch_one

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
        "SELECT specialist, SUM(cost_usd)::numeric AS cost_usd, "
        "SUM(input_tokens+output_tokens)::bigint AS tokens "
        "FROM llm_usage WHERE paper_id = %(id)s "
        "GROUP BY specialist ORDER BY cost_usd DESC",
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
