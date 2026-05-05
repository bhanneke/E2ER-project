"""Specialist dispatcher — runs work orders, supports parallel execution."""
from __future__ import annotations

import asyncio
from pathlib import Path

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, ToolHandler
from ..specialists.base import run_specialist
from ..specialists.contracts import Contribution, WorkOrder

logger = get_logger(__name__)


def _inject_context(work_order: WorkOrder, workspace: Path) -> WorkOrder:
    """Populate work_order.context from workspace artifacts based on context_tier."""
    if work_order.context:
        return work_order  # already populated (e.g. in tests)
    from ..strategist.context import build_tier0_context, build_tier1_context, build_tier2_context
    builders = {0: build_tier0_context, 1: build_tier1_context, 2: build_tier2_context}
    builder = builders.get(work_order.context_tier, build_tier1_context)
    context = builder(workspace, work_order.paper_id)
    return work_order.model_copy(update={"context": context})


async def execute_work_order(
    work_order: WorkOrder,
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
) -> Contribution:
    """Execute a single work order."""
    work_order = _inject_context(work_order, workspace)
    logger.info("Dispatching %s for paper %s", work_order.specialist, work_order.paper_id)
    try:
        return await run_specialist(
            work_order=work_order,
            backend=backend,
            workspace=workspace,
            model=model,
            extra_tools=extra_tools,
            extra_handlers=extra_handlers,
            backend_name=backend_name,
        )
    except Exception as e:
        logger.error("Specialist %s failed: %s", work_order.specialist, e)
        return Contribution(
            paper_id=work_order.paper_id,
            specialist=work_order.specialist,
            output="",
            success=False,
            error=str(e),
        )


async def execute_parallel(
    work_orders: list[WorkOrder],
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
) -> list[Contribution]:
    """Execute multiple work orders concurrently, bounded by max_concurrent_specialists."""
    from ...config import get_settings
    logger.info("Parallel dispatch: %d specialists", len(work_orders))
    sem = asyncio.Semaphore(get_settings().max_concurrent_specialists)

    async def _bounded(wo: WorkOrder) -> Contribution:
        async with sem:
            return await execute_work_order(
                wo, backend, workspace, model,
                extra_tools, extra_handlers, backend_name,
            )

    return await asyncio.gather(*(_bounded(wo) for wo in work_orders))


async def execute_with_dependencies(
    work_orders: list[WorkOrder],
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
) -> list[Contribution]:
    """Execute work orders grouped by parallel_group — groups run sequentially,
    within each group specialists run in parallel.
    """
    from itertools import groupby

    sorted_orders = sorted(work_orders, key=lambda w: w.parallel_group)
    all_contributions: list[Contribution] = []

    for group_id, group_iter in groupby(sorted_orders, key=lambda w: w.parallel_group):
        group = list(group_iter)
        logger.info("Executing parallel group %d (%d specialists)", group_id, len(group))
        contributions = await execute_parallel(
            group, backend, workspace, model,
            extra_tools, extra_handlers, backend_name,
        )
        all_contributions.extend(contributions)

    return all_contributions
