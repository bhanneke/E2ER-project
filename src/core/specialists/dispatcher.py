"""Specialist dispatcher — runs work orders, supports parallel execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, ToolHandler
from ..governance import DEFAULT_REGIME, enforces
from ..specialists.base import run_specialist
from ..specialists.contracts import Contribution, WorkOrder

logger = get_logger(__name__)


def _inject_context(work_order: WorkOrder, workspace: Path) -> WorkOrder:
    """Populate work_order.context and ensure output_file is set.

    Auto-fills output_file from SPECIALIST_ARTIFACTS when the strategist
    omitted it — without this, specialists freelance on filenames and
    write multiple uncanonical artifacts (a real failure mode on smaller
    models like Haiku).

    Routes pure-text reviewer specialists through build_review_context,
    which pre-loads the full paper draft + supporting docs into the
    prompt. This eliminates the read_file-per-doc tool tour that
    dominated review-phase token usage (each tool result re-sent on
    every subsequent turn → quadratic input growth).
    """
    from ..strategist.context import (
        build_review_context,
        build_tier0_context,
        build_tier1_context,
        build_tier2_context,
    )
    from .registry import REVIEWER_SPECIALISTS, SPECIALIST_ARTIFACTS, SPECIALIST_SIDECAR_ARTIFACTS

    updates: dict[str, object] = {}

    if not work_order.context:
        if work_order.specialist in REVIEWER_SPECIALISTS:
            # Reviewers are pure-text: pre-load full draft + supporting docs.
            updates["context"] = build_review_context(workspace, work_order.paper_id)
        else:
            builders = {0: build_tier0_context, 1: build_tier1_context, 2: build_tier2_context}
            builder = builders.get(work_order.context_tier, build_tier1_context)
            updates["context"] = builder(workspace, work_order.paper_id)

    if not work_order.output_file:
        canonical = SPECIALIST_ARTIFACTS.get(work_order.specialist)
        if canonical:
            updates["output_file"] = canonical

    # Auto-populate sidecar_artifacts from the registry when the strategist
    # / caller didn't set it. Without this, the multi-file output block in
    # _build_user_prompt would never fire and the JSON contract would
    # silently not be emitted — the exact failure mode the v0.5 live runs
    # surfaced.
    if not work_order.sidecar_artifacts:
        sidecars = SPECIALIST_SIDECAR_ARTIFACTS.get(work_order.specialist)
        if sidecars:
            updates["sidecar_artifacts"] = list(sidecars)

    return work_order.model_copy(update=updates) if updates else work_order


async def execute_work_order(
    work_order: WorkOrder,
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
    governance: str = DEFAULT_REGIME,
) -> Contribution:
    """Execute a single work order."""
    from ...db.events import log_event

    work_order = _inject_context(work_order, workspace)
    logger.info("Dispatching %s for paper %s", work_order.specialist, work_order.paper_id)
    await log_event(
        work_order.paper_id,
        "specialist_start",
        specialist=work_order.specialist,
    )
    try:
        contribution = await run_specialist(
            work_order=work_order,
            backend=backend,
            workspace=workspace,
            model=model,
            extra_tools=extra_tools,
            extra_handlers=extra_handlers,
            backend_name=backend_name,
            governance=governance,
        )
        await log_event(
            work_order.paper_id,
            "specialist_end",
            specialist=work_order.specialist,
            payload={"success": contribution.success},
        )
        return contribution
    except asyncio.CancelledError:
        # Cancellation must propagate, not be swallowed as a specialist failure.
        raise
    except Exception as e:
        logger.error("Specialist %s failed: %s", work_order.specialist, e)
        await log_event(
            work_order.paper_id,
            "specialist_failed",
            specialist=work_order.specialist,
            payload={"error": str(e)},
        )
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
    governance: str = DEFAULT_REGIME,
) -> list[Contribution]:
    """Execute multiple work orders concurrently, bounded by max_concurrent_specialists.

    Per-specialist failures are caught inside execute_work_order and surface as
    Contribution(success=False). This wrapper logs an aggregate failure summary
    and raises if every specialist in the batch failed (so callers fail fast
    rather than silently advancing to the next phase with no artifacts).
    """
    from ...config import get_settings

    if not work_orders:
        return []

    # Mid-phase budget check: parallel batches can spend several dollars between
    # the runner's phase-boundary checks. A pre-batch check protects against a
    # single phase blowing past the cap.
    from ...modules.tracking.usage import check_budget_by_paper_id

    await check_budget_by_paper_id(work_orders[0].paper_id)

    logger.info("Parallel dispatch: %d specialists", len(work_orders))
    sem = asyncio.Semaphore(get_settings().max_concurrent_specialists)

    async def _bounded(wo: WorkOrder) -> Contribution:
        async with sem:
            return await execute_work_order(
                wo,
                backend,
                workspace,
                model,
                extra_tools,
                extra_handlers,
                backend_name,
                governance,
            )

    contributions = await asyncio.gather(*(_bounded(wo) for wo in work_orders))

    failed = [c for c in contributions if not c.success]
    if failed:
        logger.warning(
            "execute_parallel: %d/%d specialists failed: %s",
            len(failed),
            len(contributions),
            ", ".join(f"{c.specialist}({(c.error or '?')[:60]})" for c in failed),
        )

    if failed and len(failed) == len(contributions):
        details = "; ".join(f"{c.specialist}: {c.error}" for c in failed)
        raise RuntimeError(f"All specialists failed in parallel batch: {details}")

    # Cascade detection: a specialist that "succeeded" but didn't write its
    # canonical artifact will starve downstream specialists.
    await guard_artifacts(contributions, workspace, governance)

    return contributions


def find_missing_artifacts(contributions: list[Contribution], workspace: Path) -> list[tuple[str, str, str]]:
    """Non-tolerant specialists that "succeeded" without writing their canonical
    artifact, as (specialist, artifact, error) triples.

    Reviewers and polish specialists are tolerant of partial failure (the
    aggregator handles gaps); everyone else writes a required upstream artifact.
    """
    from .registry import POLISH_SPECIALISTS, REVIEWER_SPECIALISTS, SPECIALIST_ARTIFACTS

    tolerant = set(REVIEWER_SPECIALISTS) | set(POLISH_SPECIALISTS)
    missing: list[tuple[str, str, str]] = []
    for c in contributions:
        if c.specialist in tolerant:
            continue
        artifact = SPECIALIST_ARTIFACTS.get(c.specialist)
        if not artifact:
            continue
        if not (workspace / artifact).exists():
            missing.append((c.specialist, artifact, c.error or "(no error)"))
    return missing


def _cascade_details(missing: list[tuple[str, str, str]]) -> str:
    return "; ".join(f"{spec} -> {artifact} missing ({err[:400]})" for spec, artifact, err in missing)


def assert_artifacts_written(contributions: list[Contribution], workspace: Path) -> None:
    """Raise if a non-tolerant specialist didn't write its canonical artifact.

    The unconditional (always-enforcing) form. Prefer :func:`guard_artifacts`
    on the live dispatch paths, which honours the governance regime.
    """
    missing = find_missing_artifacts(contributions, workspace)
    if missing:
        raise RuntimeError(
            f"Specialist(s) did not produce canonical artifact: {_cascade_details(missing)}. "
            "Halting before downstream cascade — see specialist_failed events for details."
        )


async def guard_artifacts(
    contributions: list[Contribution],
    workspace: Path,
    governance: str = DEFAULT_REGIME,
) -> None:
    """Cascade guard, governance-aware (WS-B).

    The check always runs and its verdict is always logged. Under a regime
    that enforces contracts it raises (halting the run before downstream
    specialists starve); under ``off`` it records a `gate_shadow` event and
    lets the run continue on the missing artifact — the ungoverned control.
    """
    missing = find_missing_artifacts(contributions, workspace)
    if not missing:
        return

    details = _cascade_details(missing)
    enforced = enforces(governance, "contracts")
    paper_id = contributions[0].paper_id if contributions else ""
    if paper_id:
        try:
            from ...db.events import log_event

            await log_event(
                paper_id,
                "gate_enforced" if enforced else "gate_shadow",
                stage="contracts",
                payload={
                    "gate": "contracts",
                    "passed": False,
                    "enforced": enforced,
                    "regime": governance,
                    "check": "missing_artifact",
                    "detail": details[:500],
                },
            )
        except Exception as e:  # noqa: BLE001 — measurement must never break a run
            logger.debug("Could not log cascade-guard event: %s", e)

    if enforced:
        raise RuntimeError(
            f"Specialist(s) did not produce canonical artifact: {details}. "
            "Halting before downstream cascade — see specialist_failed events for details."
        )
    logger.warning(
        "Cascade guard NOT enforced under governance=%s (shadow) — continuing without: %s",
        governance,
        details,
    )


async def execute_with_dependencies(
    work_orders: list[WorkOrder],
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
    governance: str = DEFAULT_REGIME,
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
            group,
            backend,
            workspace,
            model,
            extra_tools,
            extra_handlers,
            backend_name,
            governance,
        )
        all_contributions.extend(contributions)

    return all_contributions
