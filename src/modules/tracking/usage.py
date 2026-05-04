"""Token and cost usage recording."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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


async def get_paper_usage(paper_id: str) -> list[dict[str, Any]]:
    """Get all usage records for a paper."""
    from ...db.client import fetch_all

    return await fetch_all(
        "SELECT * FROM llm_usage WHERE paper_id = %(id)s ORDER BY created_at",
        {"id": paper_id},
    )


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
