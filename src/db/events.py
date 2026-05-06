"""Append-only pipeline events log — one row per phase/specialist transition."""
from __future__ import annotations

import json
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)


async def log_event(
    paper_id: str,
    event_type: str,
    *,
    stage: str | None = None,
    specialist: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert a row into pipeline_events. DB failures are swallowed (logged at debug).

    event_type values used by the runner/dispatcher:
      phase_start, phase_end, specialist_start, specialist_end, specialist_failed
    """
    from .client import execute

    try:
        await execute(
            """
            INSERT INTO pipeline_events (paper_id, event_type, stage, specialist, payload)
            VALUES (%(p)s, %(t)s, %(st)s, %(sp)s, %(pl)s::jsonb)
            """,
            {
                "p": paper_id,
                "t": event_type,
                "st": stage,
                "sp": specialist,
                "pl": json.dumps(payload or {}),
            },
        )
    except Exception as e:
        logger.debug("Event log skipped (no DB?): %s", e)


async def fetch_events(paper_id: str, since: str | None = None) -> list[dict[str, Any]]:
    """Read events for a paper, optionally newer than an ISO-8601 timestamp."""
    from .client import fetch_all

    try:
        if since:
            rows = await fetch_all(
                """
                SELECT id, event_type, stage, specialist, payload, created_at
                FROM pipeline_events
                WHERE paper_id = %(p)s AND created_at > %(s)s::timestamptz
                ORDER BY created_at ASC
                """,
                {"p": paper_id, "s": since},
            )
        else:
            rows = await fetch_all(
                """
                SELECT id, event_type, stage, specialist, payload, created_at
                FROM pipeline_events
                WHERE paper_id = %(p)s
                ORDER BY created_at ASC
                """,
                {"p": paper_id},
            )
        return rows or []
    except Exception as e:
        logger.debug("Event fetch skipped (no DB?): %s", e)
        return []
