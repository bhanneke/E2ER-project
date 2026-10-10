"""Specialist dispatcher — runs work orders, supports parallel execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, ToolHandler
from ...modules.llm.plan_limit import PlanLimitReachedError
from ..governance import DEFAULT_REGIME
from ..specialists.base import run_specialist
from ..specialists.contracts import Contribution, WorkOrder

logger = get_logger(__name__)

# Attempts per work order, counting the first. Shared with the runner's
# sequential path, which imports it as `_MAX_SPECIALIST_ATTEMPTS` — one budget,
# one number, whichever path a specialist happens to be dispatched from.
#
# The parallel path used to have no retry at all, and that asymmetry killed the
# 2026-08-20 canary. `data_architect` returned a zero-tool-call turn, the
# contract check correctly flipped it to a failure, and because the batch held
# exactly one work order (concurrency 1) "1/1 specialists failed" was also
# "every specialist failed". Three seconds from one flaky turn to a dead run.
#
# The retry is not a blind re-roll. `run_specialist` persists the violation
# (`write_contract_feedback`) and the next attempt consumes it into its prompt
# (`read_contract_feedback`), so attempt 2 is told exactly what attempt 1 got
# wrong. That coaching machinery was built for this and, until now, only the
# sequential path could reach it.
MAX_SPECIALIST_ATTEMPTS = 3

#: Called with each work order that succeeded, as it succeeds. The runner sets it
#: in the initial phase, so a pause (the spending limit, say) in the middle of a
#: dispatch keeps a record of what is done and the resume runs only the rest.
specialist_done: ContextVar[Callable[[WorkOrder], None] | None] = ContextVar("specialist_done", default=None)

_EDITABLE = (".md", ".tex", ".json", ".txt", ".bib")


class ContractFailureError(RuntimeError):
    """Specialists whose last attempt still failed its output contract: the run stops for the researcher.

    Raised by the dispatcher instead of failing the run when every specialist
    that failed did produce output, but output that does not meet its contract
    (a crash, a timeout or an unavailable backend still fails the run as
    before). ``failures`` holds, per specialist, its work order, every attempt
    with its violations, and the files involved; ``contributions`` the whole
    dispatch so far (the specialists that succeeded keep their output) and
    ``remaining`` the work orders of later groups that did not run.
    """

    def __init__(
        self,
        failures: list[dict[str, Any]],
        contributions: list[Contribution] | None = None,
        remaining: list[WorkOrder] | None = None,
    ) -> None:
        self.failures = failures
        self.contributions = list(contributions or [])
        self.remaining = list(remaining or [])
        names = ", ".join(f["specialist"] for f in failures)
        super().__init__(f"output contract not met after {MAX_SPECIALIST_ATTEMPTS} attempts: {names}")


def contract_failed(c: Contribution) -> bool:
    """The specialist ran and wrote output, but the output failed its contract (not a crash)."""
    return not c.success and bool(c.contract_violations)


def _files_involved(specialist: str, violations: list[str]) -> list[str]:
    """The specialist's own output files and the files its violations name, as the researcher can edit them."""
    from ..pipeline.components import sidecars_for
    from .registry import SPECIALIST_ARTIFACTS

    names = [SPECIALIST_ARTIFACTS.get(specialist, ""), *sidecars_for(specialist)]
    names += [v.split(":", 1)[0].strip() for v in violations if ":" in v]
    return [n for n in dict.fromkeys(names) if n and "/" not in n and not n.startswith(".") and n.endswith(_EDITABLE)]


def failure_record(wo: WorkOrder, c: Contribution) -> dict[str, Any]:
    """What the researcher sees of one specialist that failed its contract (see ContractFailureError)."""
    attempts = c.attempts or [{"attempt": 1, "error": c.error, "violations": list(c.contract_violations)}]
    seen = [v for a in attempts for v in a.get("violations") or []]
    return {
        "specialist": wo.specialist,
        "order": wo.model_dump(include={"paper_id", "specialist", "focus", "parallel_group", "context_tier", "extra"}),
        "attempts": attempts,
        "files": _files_involved(wo.specialist, seen),
    }


def _tolerant() -> set[str]:
    from .registry import POLISH_SPECIALISTS, REVIEWER_SPECIALISTS

    return set(REVIEWER_SPECIALISTS) | set(POLISH_SPECIALISTS)


def order_by_dependencies(work_orders: list[WorkOrder]) -> tuple[list[WorkOrder], list[str]]:
    """Regroup a dispatch so no specialist runs before, or beside, one whose output it reads.

    ``registry.SPECIALIST_NEEDS`` names what each specialist reads. A work
    order planned in the same group as a producer, or before it, moves to the
    group after the producer's; every later group moves along, so the order of
    the rest stays as planned. Returns the orders and a line per move for the
    log. A dependency on a specialist that is not in this dispatch is not a
    constraint (its output is there from earlier, or the contract check says so).
    """
    from .registry import SPECIALIST_NEEDS

    if len(work_orders) < 2:
        return work_orders, []
    group = [w.parallel_group for w in work_orders]
    names = [w.specialist for w in work_orders]

    def producers(i: int) -> list[int]:
        needs = set(SPECIALIST_NEEDS.get(names[i], ()))
        return [j for j in range(len(work_orders)) if j != i and names[j] in needs and names[j] != names[i]]

    # A consumer planned before its producer joins the producer's group first.
    for _ in range(len(work_orders)):
        changed = False
        for i in range(len(work_orders)):
            later = [group[j] for j in producers(i) if group[j] > group[i]]
            if later:
                group[i] = max(later)
                changed = True
        if not changed:
            break
    # Then each group splits into as many as its dependencies need.
    new = [0] * len(work_orders)
    level = 0
    for g in sorted(set(group)):
        pending = [i for i in range(len(work_orders)) if group[i] == g]
        while pending:
            here = set(pending)
            ready = [i for i in pending if not any(j in here for j in producers(i))]
            if not ready:  # a cycle: run them as planned
                ready = pending
            for i in ready:
                new[i] = level
            pending = [i for i in pending if i not in ready]
            level += 1
    order = sorted(range(len(work_orders)), key=lambda i: (new[i], i))
    out = [work_orders[i].model_copy(update={"parallel_group": new[i]}) for i in order]
    moves = []
    for i in order:
        planned = work_orders[i].parallel_group
        early = sorted({names[j] for j in producers(i) if work_orders[j].parallel_group >= planned})
        if early:
            moves.append(f"{names[i]} waits for {', '.join(early)} (planned in the same or a later group)")
    return out, moves


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
    from ..pipeline.components import sidecars_for
    from ..strategist.context import (
        build_review_context,
        build_tier0_context,
        build_tier1_context,
        build_tier2_context,
    )
    from .registry import REVIEWER_SPECIALISTS, SPECIALIST_ARTIFACTS

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
        # The registry's sidecars plus any the active template adds
        # (`[sidecars]`; see core/pipeline/components.py).
        sidecars = sidecars_for(work_order.specialist)
        # Files the researcher edited are not requested again (a send-back).
        keep = set(work_order.extra.get("keep_files") or [])
        sidecars = [f for f in sidecars if f not in keep]
        if sidecars:
            updates["sidecar_artifacts"] = list(sidecars)

    return work_order.model_copy(update=updates) if updates else work_order


def _file_sha256(path: Path) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        return None


def _skills(specialist: str) -> list[str]:
    try:
        from ...skills.loader import loaded_skill_names

        return loaded_skill_names(specialist)
    except Exception:  # noqa: BLE001 — a record of skills must never stop a dispatch
        return []


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
    # What this step reads and writes, recorded with the step so the dossier can
    # say which skills ran and what each step wrote (not what a later step or a
    # later checkout left behind).
    declared = list(dict.fromkeys(n for n in [work_order.output_file, *work_order.sidecar_artifacts] if n))
    before = {n: _file_sha256(workspace / n) for n in declared}
    await log_event(
        work_order.paper_id,
        "specialist_start",
        specialist=work_order.specialist,
        payload={"skills": _skills(work_order.specialist), "outputs": declared},
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
        outputs = []
        for n in declared:
            after = _file_sha256(workspace / n)
            if after is not None:
                outputs.append({"file": n, "sha256": after, "changed": after != before.get(n)})
        await log_event(
            work_order.paper_id,
            "specialist_end",
            specialist=work_order.specialist,
            payload={"success": contribution.success, "outputs": outputs},
        )
        done = specialist_done.get()
        if contribution.success and done is not None:
            done(work_order)
        return contribution
    except asyncio.CancelledError:
        # Cancellation must propagate, not be swallowed as a specialist failure.
        raise
    except PlanLimitReachedError as limit:
        # The subscription plan's usage limit: not this specialist's failure. No
        # attempt is counted; the run pauses and Resume runs this work order again.
        limit.specialist = limit.specialist or work_order.specialist
        logger.warning("Specialist %s paused: %s", work_order.specialist, limit)
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


async def run_with_attempts(
    wo: WorkOrder,
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
    governance: str = DEFAULT_REGIME,
    *,
    sem: asyncio.Semaphore | None = None,
    retry_crashes: bool = True,
) -> Contribution:
    """One work order, retried until it succeeds or exhausts MAX_SPECIALIST_ATTEMPTS.

    The semaphore is acquired per attempt rather than held across the whole
    retry chain, so a specialist working through its retries doesn't also
    squat a concurrency slot its peers could be using. Every attempt is kept
    on the returned contribution (``attempts``). With ``retry_crashes=False``
    only a contract violation is retried; a crash returns at once.
    """
    from ...modules.tracking.usage import check_budget_by_paper_id
    from .contract_check import has_contract_feedback

    contribution: Contribution | None = None
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, MAX_SPECIALIST_ATTEMPTS + 1):
        if contribution is not None:
            # Retries cost real money, and a parallel batch runs entirely
            # between the runner's phase-boundary budget checks — re-check
            # rather than let a retrying batch spend past the cap.
            await check_budget_by_paper_id(wo.paper_id)
            logger.warning(
                "%s: attempt %d/%d failed (%s) — retrying %s",
                wo.specialist,
                attempt - 1,
                MAX_SPECIALIST_ATTEMPTS,
                (contribution.error or "no error recorded")[:200],
                (
                    "with the contract violation fed back into the prompt"
                    if has_contract_feedback(workspace, wo.specialist)
                    else "(no contract feedback to feed back — blind retry)"
                ),
            )
        if sem is not None:
            async with sem:
                contribution = await execute_work_order(
                    wo, backend, workspace, model, extra_tools, extra_handlers, backend_name, governance
                )
        else:
            contribution = await execute_work_order(
                wo, backend, workspace, model, extra_tools, extra_handlers, backend_name, governance
            )
        attempts.append(
            {
                "attempt": attempt,
                "error": (contribution.error or "")[:2000],
                "violations": list(contribution.contract_violations),
            }
        )
        if contribution.success:
            if attempt > 1:
                logger.info("%s: recovered on attempt %d/%d", wo.specialist, attempt, MAX_SPECIALIST_ATTEMPTS)
            return contribution.model_copy(update={"attempts": attempts})
        if not retry_crashes and not contract_failed(contribution):
            return contribution.model_copy(update={"attempts": attempts})

    assert contribution is not None  # the loop runs at least once
    logger.error(
        "%s: exhausted %d attempts — %s",
        wo.specialist,
        MAX_SPECIALIST_ATTEMPTS,
        (contribution.error or "no error recorded")[:200],
    )
    return contribution.model_copy(update={"attempts": attempts})


def raise_contract_failure(work_orders: list[WorkOrder], contributions: list[Contribution]) -> None:
    """Raise ContractFailureError when every specialist that failed (reviewers, polish aside) failed its contract.

    A failure of another kind among them (a crash, a timeout, an unavailable
    backend) leaves the decision to the caller, which fails the run as before.
    """
    tolerant = _tolerant()
    failed = [(wo, c) for wo, c in zip(work_orders, contributions, strict=True) if not c.success]
    blocking = [(wo, c) for wo, c in failed if wo.specialist not in tolerant]
    if blocking and all(contract_failed(c) for _wo, c in blocking):
        raise ContractFailureError([failure_record(wo, c) for wo, c in blocking], contributions)


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

    Each work order gets up to MAX_SPECIALIST_ATTEMPTS attempts; a contract
    violation on one attempt is fed back into the next one's prompt. Only a work
    order that exhausts its budget counts as failed.

    Per-specialist failures are caught inside execute_work_order and surface as
    Contribution(success=False). This wrapper logs an aggregate failure summary.
    When the specialists that failed all failed their output contract on the
    last attempt, it raises ContractFailureError: the run stops for the researcher,
    and the specialists that succeeded keep their output. Otherwise it raises
    if every specialist in the batch failed (so callers fail fast rather than
    silently advancing to the next phase with no artifacts).
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

    async def _one(wo: WorkOrder) -> Contribution | PlanLimitReachedError:
        try:
            return await run_with_attempts(
                wo, backend, workspace, model, extra_tools, extra_handlers, backend_name, governance, sem=sem
            )
        except PlanLimitReachedError as limit:
            return limit

    # A plan's usage limit hit by one specialist does not stop the others: each
    # finishes (the ones that succeed keep their output, and in the initial phase
    # are recorded as done), then the batch raises the limit and the run pauses.
    # The others usually hit the same limit at their next call, so this costs
    # little, and nothing they finished is thrown away.
    outcomes = await asyncio.gather(*(_one(wo) for wo in work_orders))
    limits = [o for o in outcomes if isinstance(o, PlanLimitReachedError)]
    if limits:
        raise next((x for x in limits if x.resets), limits[0])
    contributions = [o for o in outcomes if isinstance(o, Contribution)]

    failed = [c for c in contributions if not c.success]
    if failed:
        logger.warning(
            "execute_parallel: %d/%d specialists failed after %d attempts each: %s",
            len(failed),
            len(contributions),
            MAX_SPECIALIST_ATTEMPTS,
            ", ".join(f"{c.specialist}({(c.error or '?')[:60]})" for c in failed),
        )

    # Output that keeps failing its contract stops the run for the researcher;
    # the specialists that succeeded keep theirs. Crashes still fail the run.
    raise_contract_failure(work_orders, list(contributions))

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

    A missing canonical artifact is a RELIABILITY failure: the specialist did
    not produce what it was asked to produce, and downstream specialists will
    starve. That is a broken run in any regime, so this guard always halts and
    is not switchable. Governance decides whether the paper's *claims* are
    verified, never whether the pipeline is allowed to be broken.
    """
    missing = find_missing_artifacts(contributions, workspace)
    if not missing:
        return

    details = _cascade_details(missing)
    enforced = True
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
                    "detail": details[:2000],
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
    between_groups: Callable[[set[str], list[WorkOrder]], Awaitable[None]] | None = None,
) -> list[Contribution]:
    """Execute work orders grouped by parallel_group — groups run sequentially,
    within each group specialists run in parallel.

    The groups are first checked against what each specialist reads
    (:func:`order_by_dependencies`): a specialist never runs beside, or before,
    one whose output it needs.

    ``between_groups(done, remaining)`` is awaited after each group with the
    specialists that have succeeded so far and the work orders still to run; a
    researcher step uses it to stop the run between two groups.
    """
    from itertools import groupby

    ordered, moves = order_by_dependencies(work_orders)
    for line in moves:
        logger.warning("Dispatch reordered: %s", line)
    sorted_orders = sorted(ordered, key=lambda w: w.parallel_group)
    all_contributions: list[Contribution] = []

    for group_id, group_iter in groupby(sorted_orders, key=lambda w: w.parallel_group):
        group = list(group_iter)
        logger.info("Executing parallel group %d (%d specialists)", group_id, len(group))
        try:
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
        except ContractFailureError as cf:
            cf.contributions = all_contributions + cf.contributions
            cf.remaining = [w for w in sorted_orders if w.parallel_group > group_id]
            raise
        all_contributions.extend(contributions)
        if between_groups is not None:
            done = {c.specialist for c in all_contributions if c.success}
            remaining = [w for w in sorted_orders if w.parallel_group > group_id]
            await between_groups(done, remaining)

    return all_contributions
