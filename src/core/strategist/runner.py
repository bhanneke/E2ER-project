"""Pipeline runner — orchestrates the full paper pipeline with V3 extensions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, ToolHandler
from ..governance import DEFAULT_REGIME, KIND_RELIABILITY
from ..governance import enforces as governance_enforces
from ..pipeline.spec import RESEARCHER_KINDS, SEQUENCE_CHECKS, find_spec
from ..specialists.contracts import Contribution, WorkOrder
from ..specialists.dispatcher import (
    MAX_SPECIALIST_ATTEMPTS,
    ContractFailureError,
    execute_parallel,
    execute_with_dependencies,
)
from ..specialists.registry import POLISH_SPECIALISTS, REVIEWER_SPECIALISTS, SPECIALIST_ARTIFACTS
from ..strategist.actions import StrategistDecision
from ..strategist.engine import StrategistEngine
from ..strategist.review_aggregator import aggregate_reviews, parse_review_output
from ..strategist.state import (
    BudgetExceededError,
    CircuitBreakerError,
    GateHaltError,
    HumanReviewRequestedError,
    PaperStatus,
    StepFailedError,
)

logger = get_logger(__name__)


def _coerce_paper_status(value: str | None, fallback: PaperStatus) -> PaperStatus:
    """Build a PaperStatus from a persisted string, tolerating bad/legacy
    values. ``state.last_status`` is a free ``str`` field (could be hand-edited
    or from an older schema); a raw ``PaperStatus(value)`` ValueError on resume
    would crash an otherwise-complete paper into FAILED."""
    try:
        return PaperStatus(value) if value else fallback
    except ValueError:
        logger.warning("Resume: unrecognized persisted status %r — falling back to %s", value, fallback.value)
        return fallback


_MAX_ITERATIONS = 6
_MAX_PIVOTS = 1
# Maximum consecutive failures for a single non-tolerant specialist before
# the circuit breaker halts the run. Set from runs #14 / #18 experience:
# - data_analyst failed 3 times in a row when Allium was unrecoverable
# - retrying past the third attempt never recovered the data layer
# 3 is the cheapest threshold that doesn't false-trip on transient errors
# (one bad attempt + one retry + one confirmation that it's not transient).
#
# Defined in the dispatcher so the sequential path (here) and the parallel
# path (execute_parallel) share ONE budget. They used to disagree: this
# constant was local, so parallel batches got no retry at all.
_MAX_SPECIALIST_ATTEMPTS = MAX_SPECIALIST_ATTEMPTS
# v0.6 step 5: budget for the verify_numbers auto-patch loop. When the
# pre-review gate finds critical mismatches, the runner dispatches
# patch_revisor with the mismatch findings, re-runs verify_numbers, and
# only transitions to REJECTED if the second pass STILL has criticals.
# 1 attempt is the right cost/benefit point: one patch fixes the common
# "drafter rounded wrong" / "drafter typo'd a sign" case at the cost of
# one specialist call; > 1 attempts means the drafter+patch pair can't
# converge and operator intervention is needed.
_VERIFY_NUMBERS_AUTO_PATCH_BUDGET = 1

# Deep revision: when reviewers reject the paper's RESEARCH (not its wording) —
# MAJOR_REVISION or MECHANISM_FAIL — re-dispatch the research specialists
# (data_analyst + econometrics_specialist) and the writer with the referee
# reports as guidance, then re-render, re-draft, and re-review. patch_revisor
# only edits prose; it cannot recompute an out-of-sample test or re-source a
# dataset, so the substantive referee findings used to die in a terminal
# REJECTED. This loop lets the pipeline respond to a referee like a researcher
# does. Bounded to 1 round: each round is ~a dozen specialist calls + a full
# re-review; one round is the right cost/benefit point and guarantees
# termination.
_MAX_DEEP_REVISIONS = 1

# Repair attempts for table_spec.json before the render halt fires. One attempt
# was demonstrably too few: the 2026-08-20 canary went from 12 unresolved
# references to 4 in a single section_writer pass and then halted with the
# remainder fixable. Each attempt costs one specialist call, and the loop stops
# early the moment an attempt fails to reduce the count — a reference that is
# genuinely ambiguous (`ar1` where the JSON holds `ar1_pre` and `ar1_post`) will
# not become resolvable by asking a second time, so the budget is only spent
# while it is buying progress.
_MAX_TABLE_SPEC_REPAIRS = 3

#: The specialist whose work a design check must precede. A gate with `after`
#: runs as soon as its specialists are done, and in any case before a group that
#: contains this one, so a plan that leaves out one of those specialists cannot
#: slip the estimation past the check.
_ESTIMATION_SPECIALIST = "econometrics_specialist"

#: Checks that can sit inside the dispatch (gate steps with `after`): the design
#: file they read, and the specialist that writes it (sent back on `retry`).
_DESIGN_CHECKS: dict[str, tuple[str, str]] = {
    "event_window": ("event_design.json", "identification_strategist"),
}


@dataclass(frozen=True)
class _StepEffects:
    """What a phase persists, beyond running.

    Implementation detail of each phase, deliberately not in the pipeline file:
    a researcher writing a process should not have to know that the iterative
    phase is the one that owns the pivot counter.
    """

    handler: str = ""
    captures_status: bool = False
    updates_contributions: bool = False
    updates_iteration: bool = False
    forces_in_progress: bool = False


_STEP_EFFECTS: dict[str, _StepEffects] = {
    # status becomes IN_PROGRESS after initial whether or not it ran, which is
    # why this is a flag rather than a line after the loop.
    "initial": _StepEffects(updates_contributions=True, forces_in_progress=True),
    "iterative": _StepEffects(captures_status=True, updates_contributions=True, updates_iteration=True),
    "estimation_gate": _StepEffects(handler="_enforce_estimation_gate"),
    "self_attack": _StepEffects(captures_status=True),
    "polish": _StepEffects(captures_status=True),
    "review": _StepEffects(captures_status=True),
    "replication": _StepEffects(updates_contributions=True),
}


class PipelineRunner:
    """Top-level orchestrator for a single paper."""

    def __init__(
        self,
        paper_id: str,
        workspace: Path,
        backend: LLMBackend,
        model: str,
        mode: str = "iterative",
        extra_tools: list[dict] | None = None,
        extra_handlers: list[ToolHandler] | None = None,
        backend_name: str = "anthropic",
        max_cost_usd: float | None = None,
        methodology: str = "empirical",
        governance: str = DEFAULT_REGIME,
        review_stages: list[str] | None = None,
        pipeline: str = "empirical",
    ) -> None:
        self._paper_id = paper_id
        self._workspace = workspace
        self._backend = backend
        self._model = model
        self._mode = mode
        # The process this run follows. Resolved at construction so a bad
        # pipeline name fails before any model is called, not forty minutes in.
        self._spec = find_spec(pipeline)
        # Governance regime (experiment treatment): off | contracts | full.
        # Selects which gates BLOCK; non-blocking gates still compute + log.
        self._governance = governance
        # Human-in-the-loop: stages after which the run pauses for the
        # researcher to inspect/edit the workspace before continuing.
        self._review_stages = set(review_stages or [])
        # Researcher steps and gates with `after = [...]` act inside the
        # strategist's dispatch, right after those specialists; the rest are
        # ordinary steps.
        self._triggers = [s for s in self._spec.steps if (s.kind in RESEARCHER_KINDS or s.kind == "gate") and s.after]
        self._state: Any = None
        self._in_initial = False
        # Methodology drives phase routing (data_reviewer + replication_packager
        # are skipped for theoretical papers — pre-v0.5 they ran wastefully).
        self._methodology = methodology
        self._extra_tools = extra_tools or []
        self._extra_handlers = extra_handlers or []
        self._backend_name = backend_name
        self._strategist = StrategistEngine(
            backend,
            workspace,
            paper_id,
            mode,
            model=model,
            backend_name=backend_name,
        )
        self._contributions: list[Contribution] = []
        self._iteration = 0
        self._pivot_count = 0
        if max_cost_usd is None:
            from ...config import get_settings

            max_cost_usd = get_settings().default_max_cost_usd
        self._max_cost_usd = max_cost_usd

        # Circuit breaker: count consecutive failures per specialist within
        # this run. Tolerant specialists (reviewers, polish) are exempt —
        # they're allowed to fail without halting downstream work. Hitting
        # ``_MAX_SPECIALIST_ATTEMPTS`` on a non-tolerant specialist raises
        # CircuitBreakerError and the run halts with status=PAUSED.
        self._failure_counts: dict[str, int] = {}
        self._last_specialist_errors: dict[str, str] = {}
        # Deep-revision rounds spent this run (re-do-the-research loop).
        self._deep_revision_count: int = 0
        # What the number check's automatic correction did this time, for the stop.
        self._number_patch_outcome: str = ""

    def _in_memory_spent(self) -> float:
        """Sum of all specialist contribution costs + strategist usage cost.

        Used as a fallback when the llm_usage DB table is unavailable so the
        cost cap still trips. Authoritative on whichever side is larger.
        """
        from ...modules.tracking.costs import compute_cost

        spec_cost = sum(c.cost_usd or 0.0 for c in self._contributions)
        # Pass backend so flat-rate CLI backends produce $0 here too —
        # otherwise the in-memory fallback estimate trips the budget
        # cap even with the DB-side cost stored as 0 (M4 finding #1).
        strat_cost = float(compute_cost(self._model, self._strategist.total_usage, backend=self._backend_name))
        return spec_cost + strat_cost

    async def _run_spec_step(
        self,
        step: Any,
        _phase: Any,
        state: Any,
        prior_contributions: int,
        status: PaperStatus,
    ) -> PaperStatus:
        """Execute one step of the spec, with the bookkeeping that phase needs.

        The sequence is data; this is not. Each phase persists different things
        — iteration counts, contribution counts, a completion marker — and
        revision needs the running status passed in and logs its own events
        because it cannot go through `_phase`. Flattening that into the spec
        would put implementation detail in a file researchers are meant to
        write, so it stays here, keyed by step name.
        """
        name = step.name
        self._current_step = name
        if step.kind in RESEARCHER_KINDS:
            if state.is_approved(name):
                if step.kind == "preregister":
                    await self._freeze_preregistration(name)
                state.mark_complete(name)
                state.save(self._workspace)
                return status
            await self._stop_for_researcher(step, state)
        effects = _STEP_EFFECTS.get(name, _StepEffects())

        if name == "revision":
            # Bypasses _phase: it takes the current status as an argument.
            from ...db.events import log_event
            from ...modules.tracking.usage import check_budget

            await check_budget(self._paper_id, self._max_cost_usd, self._in_memory_spent())
            await log_event(self._paper_id, "phase_start", stage="revision")
            status = await self._run_revision_phase(status)
            if status in (PaperStatus.FAILED, PaperStatus.REJECTED):
                raise StepFailedError(status, "", "revision")
            await log_event(self._paper_id, "phase_end", stage="revision")
            state.last_status = status.value
            state.contributions_count = prior_contributions + len(self._contributions)
            state.mark_complete("revision")
            state.save(self._workspace)
            if self._should_pause_for_review("revision", state):
                state.pending_review_stage = "revision"
                state.save(self._workspace)
                raise HumanReviewRequestedError("revision")
            return status

        handler = getattr(self, effects.handler or f"_run_{name}_phase", None)
        if handler is None:
            # A step this runner has no phase of its own for: a template's fixed
            # set of specialists, or a check that runs as a step of its own.
            if step.kind == "specialists":

                async def handler() -> None:
                    await self._run_specialists_step(step)

            elif step.kind == "gate" and step.check in SEQUENCE_CHECKS:

                async def handler() -> None:
                    await self._run_check_step(step, state)

            else:
                raise RuntimeError(f"step {name!r} ({step.kind}) has no phase in this runner")
        result = await _phase(name, handler)

        if effects.captures_status and isinstance(result, PaperStatus):
            status = result
        if effects.updates_iteration:
            state.iteration = self._iteration
            state.pivot_count = self._pivot_count
        if effects.updates_contributions:
            state.contributions_count = prior_contributions + len(self._contributions)
        if step.resumable:
            state.mark_complete(name)
            state.save(self._workspace)
        if effects.forces_in_progress:
            status = PaperStatus.IN_PROGRESS
        return status

    async def run(self) -> dict[str, Any]:
        """Run the full pipeline from idea to completion, with checkpoint/resume support."""
        from ...db.events import log_event
        from ...modules.tracking.usage import check_budget
        from ..pipeline.state import PipelineState

        # Initialise outside try/except so the except branch can reference state
        # if setup itself fails. Without this, a crash in load() or _update_status()
        # propagates silently from the background task with no event log.
        # Stamp WHICH CODE is about to run, before anything can fail. Lands in
        # the paper's event stream, so it travels with the run into the export
        # bundle and the experiment harvest — the only place an after-the-fact
        # reader can check the result against the code that produced it.
        from ..run_identity import identity_summary, run_identity

        logger.info("Run identity for paper %s: %s", self._paper_id, identity_summary())
        await log_event(self._paper_id, "run_identity", payload=run_identity())
        # Which model and which CLI version answered the calls — the process
        # identity above only knows the process-wide default backend.
        try:
            # identity() may run `<cli> --version`; keep it off the event loop.
            backend_identity = {"backend": self._backend_name, **(await asyncio.to_thread(self._backend.identity))}
            backend_identity["backend"] = self._backend_name or backend_identity.get("backend")
            await log_event(self._paper_id, "backend_identity", payload=backend_identity)
        except Exception as e:  # noqa: BLE001 — a missing stamp must not stop the run
            logger.debug("backend identity not recorded: %s", e)
        # The template's own skills and sidecar files (`[skills]`, `[sidecars]`)
        # apply to every specialist this run dispatches.
        from ..pipeline.components import activate, deactivate

        template_token = activate(self._spec)
        if self._spec.skills or self._spec.sidecars:
            await log_event(
                self._paper_id,
                "template_components",
                payload={
                    "template": self._spec.name,
                    "skills": {k: list(v) for k, v in self._spec.skills.items()},
                    "sidecars": {k: list(v) for k, v in self._spec.sidecars.items()},
                },
            )

        state: PipelineState | None = None
        try:
            state = PipelineState.load(self._workspace, self._paper_id, self._mode)
            self._iteration = state.iteration
            self._pivot_count = state.pivot_count
            prior_contributions = state.contributions_count
            self._state = state

            status = PaperStatus.DESIGNING
            await self._update_status(status)
        except Exception as e:
            logger.error("Pipeline setup failed for paper %s: %s", self._paper_id, e)
            await log_event(self._paper_id, "failed", payload={"error": f"setup: {type(e).__name__}: {e}"})
            await self._update_status(PaperStatus.FAILED, error=f"setup error: {e}")
            deactivate(template_token)
            return {"status": "failed", "error": f"setup: {type(e).__name__}: {e}"}

        async def _phase(name: str, fn) -> Any:
            """Run a phase with budget check, event logging, and state persistence."""
            await check_budget(self._paper_id, self._max_cost_usd, self._in_memory_spent())
            await log_event(self._paper_id, "phase_start", stage=name)
            result = await fn()
            if result in (PaperStatus.FAILED, PaperStatus.REJECTED):
                # A phase that ends the run raises StepFailedError with its
                # reason; a bare status here would let the next step run.
                raise StepFailedError(result, "", name)
            await log_event(self._paper_id, "phase_end", stage=name)
            # Human-in-the-loop checkpoint: pause AFTER this stage's work is
            # done (and persisted) but before the next, if the researcher asked
            # to review here and hasn't already approved it on a prior resume.
            if self._should_pause_for_review(name, state):
                state.mark_complete(name)
                state.pending_review_stage = name
                if isinstance(getattr(state, "metadata", None), dict):
                    state.metadata["review"] = {"kind": "review_at", "files": []}
                state.save(self._workspace)
                raise HumanReviewRequestedError(name)
            return result

        try:
            # The sequence, the mode conditions and the resume rules come from
            # the pipeline spec (pipelines/empirical.toml by default). The phase
            # bodies do not: each still has its own bookkeeping, described in
            # _STEP_EFFECTS. Sequence as data, work as code.
            #
            # tests/test_pipeline_sequence.py pins what this must produce, and
            # tests/test_pipeline_spec.py pins that the spec predicts the same
            # thing. If either goes red, this changed behaviour rather than
            # relocating it.
            await self._settle_researcher_decisions(state)
            for step in self._spec.steps:
                if not step.applies_to(self._mode):
                    continue
                if step.after and (step.kind in RESEARCHER_KINDS or step.kind == "gate"):
                    continue  # acts inside the dispatch (see _between_groups)
                # resumable=false is how the estimation gate stays unskippable:
                # it runs even when something claims the stage is done.
                if step.resumable and state.is_complete(step.name):
                    continue
                if state.is_complete("initial"):
                    # A gate meant for inside the initial dispatch that never ran
                    # there (its specialists were not dispatched) runs now,
                    # before anything later builds on the unchecked design.
                    await self._run_open_gates(state, [])
                status = await self._run_spec_step(step, _phase, state, prior_contributions, status)

            # Closes #6: when run() is called on a paper whose state.json
            # already has every stage marked complete (a resume on an
            # already-finished paper), no phase body executes and the DB
            # row would stay at `designing` (the state run() set on entry).
            # Mirror state.last_status — typically `completed` — back to
            # the DB so the dashboard reflects reality.
            if state.last_status in ("", PaperStatus.IN_PROGRESS.value) and self._spec.step("revision") is None:
                # A template without a revision step (e.g. `replication`, whose
                # product is a report and a dossier, not a reviewed paper) is
                # complete when its last step is done. The loop only gets here
                # when no step stopped the run. `in_progress` is the state
                # file's default, not a status any step set: testing for an
                # empty value instead left a run whose last step was an
                # approved researcher step at `in_progress` for good.
                state.last_status = PaperStatus.COMPLETED.value
                state.save(self._workspace)
            if state.last_status:
                final_status = _coerce_paper_status(state.last_status, status)
                if final_status in (PaperStatus.FAILED, PaperStatus.REJECTED):
                    # A run whose state says it ended there (an older run, every
                    # step done): stop with the reason, never a bare status.
                    raise StepFailedError(final_status, str(state.metadata.get("last_error") or ""), "")
                await self._update_status(final_status)
                status = final_status

            total_contributions = prior_contributions + len(self._contributions)
            return {"status": status.value, "contributions": total_contributions}

        except asyncio.CancelledError:
            # User cancelled. Save state, mark CANCELLED, then re-raise so the
            # task is genuinely cancelled.
            state.save(self._workspace)
            logger.warning("Pipeline cancelled for paper %s", self._paper_id)
            await log_event(self._paper_id, "cancelled")
            await self._update_status(PaperStatus.CANCELLED, error="cancelled by user")
            raise
        except CircuitBreakerError as cb:
            # A non-tolerant specialist failed _MAX_SPECIALIST_ATTEMPTS times
            # in a row. Save state, mark PAUSED, return cleanly. The operator
            # can inspect events + workspace, fix the underlying issue, and
            # POST /api/papers/{id}/resume.
            if state is not None:
                state.save(self._workspace)
            logger.warning(
                "Pipeline paused (circuit breaker) for paper %s: %s after %d attempts",
                self._paper_id,
                cb.specialist,
                cb.attempts,
            )
            await log_event(
                self._paper_id,
                "circuit_breaker_tripped",
                payload={
                    "specialist": cb.specialist,
                    "attempts": cb.attempts,
                    "last_error": (cb.last_error or "")[:2000],
                },
            )
            await self._best_effort_finalize()
            await self._update_status(
                PaperStatus.PAUSED,
                error=f"Circuit breaker: {cb.specialist} failed {cb.attempts} times. "
                "Fix the underlying issue, then POST /api/papers/{id}/resume.",
            )
            return {
                "status": "paused",
                "reason": "circuit_breaker",
                "specialist": cb.specialist,
                "attempts": cb.attempts,
            }
        except BudgetExceededError as be:
            # Distinct from a crash (FAILED). Budget exhaustion preserves
            # the workspace + state.json; resuming via /api/papers/{id}/resume
            # after raising --max-cost picks up at the first incomplete phase.
            state.save(self._workspace)
            logger.warning(
                "Pipeline paused (budget) for paper %s: spent $%.2f, cap $%.2f",
                self._paper_id,
                be.spent,
                be.cap,
            )
            error_msg = f"BudgetExceededError: spent ${be.spent:.2f}, cap ${be.cap:.2f}"
            await log_event(
                self._paper_id,
                "paused_budget",
                payload={"spent": be.spent, "cap": be.cap},
            )
            await self._update_status(PaperStatus.PAUSED, error=error_msg)
            return {"status": "paused", "reason": "budget_exhausted", "spent": be.spent, "cap": be.cap}
        except StepFailedError as sf:
            # A step ended the run. Nothing after it runs; the step is not
            # marked done, so `e2er resume` runs it again; the reason is the
            # paper's last_error.
            state.last_status = sf.status.value
            state.metadata["last_error"] = sf.reason
            state.save(self._workspace)
            logger.error("Pipeline %s for paper %s: %s", sf.status.value, self._paper_id, sf.reason)
            await log_event(
                self._paper_id,
                "failed" if sf.status == PaperStatus.FAILED else "stopped",
                stage=sf.stage or None,
                payload={"error": sf.reason},
            )
            await self._update_status(sf.status, error=sf.reason)
            return {"status": sf.status.value, "error": sf.reason}
        except ContractFailureError as cf:
            # Output that kept failing its contract: the run stops for the
            # researcher instead of failing (crashes still fail, below).
            return await self._stop_for_contract(cf, state)
        except GateHaltError as gh:
            # A design check failed before estimation. The run stops for the
            # researcher at the check; it runs again on resume.
            state.save(self._workspace)
            logger.warning("Pipeline halted by %s for paper %s: %s", gh.stage, self._paper_id, "; ".join(gh.reasons))
            await log_event(self._paper_id, "gate_halted", stage=gh.stage, payload={"reasons": gh.reasons})
            deviation = state.metadata.get("review", {}).get("kind") == "deviation"
            if state.metadata.get("review", {}).get("kind") == "numbers":
                await self._update_status(PaperStatus.PAUSED, error=self._number_check_status_text(gh.reasons))
                return {"status": "paused", "reason": "number_check", "stage": gh.stage, "reasons": gh.reasons}
            await self._update_status(
                PaperStatus.PAUSED,
                error=(
                    (
                        "Halted: the pre-registered plan changed after the freeze: "
                        f"{'; '.join(gh.reasons[:-1])[:1500]}. "
                        "Approve the deviation (e2er review --approve; recorded in the dossier), edit the file back "
                        "(e2er review --edit) or send back the step that changed it."
                    )
                    if deviation
                    else (
                        f"Halted by the check '{gh.stage}': {'; '.join(gh.reasons)[:1500]}. "
                        "Fix what it names (e2er review --edit) or send its specialist back, then resume; "
                        "the check runs again."
                    )
                ),
            )
            return {"status": "paused", "reason": "gate_halted", "stage": gh.stage, "reasons": gh.reasons}
        except HumanReviewRequestedError as hr:
            # Clean, resumable pause at a researcher-chosen checkpoint. State
            # (incl. the completed stage + pending_review_stage) was saved in
            # _phase before the raise; resume approves it and continues.
            state.save(self._workspace)
            logger.info("Pipeline paused for human review after stage '%s' (paper %s)", hr.stage, self._paper_id)
            await log_event(self._paper_id, "awaiting_review", stage=hr.stage, payload={"stage": hr.stage})
            await self._update_status(
                PaperStatus.PAUSED,
                error=(
                    f"Paused for human review after stage '{hr.stage}'. Inspect the workspace, "
                    f"edit artifacts if needed, then resume (POST /api/papers/{{id}}/resume or `e2er resume`)."
                ),
            )
            return {"status": "paused", "reason": "awaiting_review", "stage": hr.stage}
        except Exception as e:
            state.save(self._workspace)  # preserve progress on failure
            logger.error("Pipeline failed for paper %s: %s", self._paper_id, e)
            error_msg = f"{type(e).__name__}: {e}"
            await log_event(self._paper_id, "failed", payload={"error": error_msg})
            await self._update_status(PaperStatus.FAILED, error=error_msg)
            return {"status": "failed", "error": error_msg}
        finally:
            # Best-effort finalization — runs on completion, failure, AND
            # cancellation. Lets a partially-completed paper still get its
            # LaTeX compiled, audit log exported, and git push attempted.
            # Each step swallows its own exceptions so finalize never raises.
            await self._best_effort_finalize()
            deactivate(template_token)

    async def _best_effort_finalize(self) -> None:
        """Run compile + audit-export + GitHub push, swallowing all errors.

        This guarantees that even when the pipeline aborts mid-flight (cost
        cap, OpenRouter 402, all-specialists-failed, user cancellation),
        the partial artifacts on disk are still:
          1. Compiled to PDF if a paper_draft.tex exists
          2. Augmented with replication/audit_log.csv from the DB query
             history (independent of whether replication_packager ran)
          3. Pushed to GitHub if configured
        """
        try:
            await self._run_compile_phase()
        except Exception as e:
            logger.warning("Finalize: compile skipped: %s", e)
        try:
            await self._export_audit_log_only()
        except Exception as e:
            logger.warning("Finalize: audit export skipped: %s", e)
        try:
            await self._run_github_push_phase()
        except Exception as e:
            logger.warning("Finalize: github push skipped: %s", e)
        try:
            await self._run_export_phase()
        except Exception as e:
            logger.warning("Finalize: structured export skipped: %s", e)

    async def _run_export_phase(self) -> None:
        """Assemble the clean, structured project folder from the workspace.

        Runs at terminal status (completed/rejected/failed) so the user always
        gets a navigable folder — even a rejected paper yields its reviews +
        draft. Best-effort; gated on EXPORT_ENABLED.
        """
        from datetime import datetime

        from ...config import get_settings
        from ..export.structured import export_paper

        settings = get_settings()
        if not settings.export_enabled:
            return
        date_str = datetime.now().strftime("%Y%m%d")
        dest_root = settings.resolved_output_root()
        out = await asyncio.to_thread(
            export_paper, self._workspace, dest_root, date_str=date_str, template=self._spec.name
        )
        logger.info("Structured export for paper %s → %s", self._paper_id, out)

    async def _export_audit_log_only(self) -> None:
        """Write replication/audit_log.csv + data_queries.sql from the DB.

        Standalone version of the audit-export step that's normally embedded
        in _run_replication_phase. Runs even when the replication_packager
        specialist didn't get to execute, so reviewers always have the
        provenance trail of which queries ran (or were rejected).
        """
        from ...modules.data.audit import write_audit_csv, write_data_queries_sql

        replication_dir = self._workspace / "replication"
        replication_dir.mkdir(exist_ok=True)
        audit_csv = replication_dir / "audit_log.csv"
        queries_sql = replication_dir / "data_queries.sql"
        # Only re-export if not already present (avoid clobbering a real run)
        if not audit_csv.exists():
            await write_audit_csv(self._paper_id, audit_csv)
        if not queries_sql.exists():
            await write_data_queries_sql(self._paper_id, queries_sql)

    async def _run_initial_phase(self) -> None:
        from ..specialists.dispatcher import specialist_done

        self._in_initial = True
        token = specialist_done.set(self._record_initial_done)
        try:
            await self._initial_phase_body()
            state = getattr(self, "_state", None)
            if state is not None and isinstance(getattr(state, "metadata", None), dict):
                # The phase is done: nothing of it is left to resume.
                state.metadata.pop("initial_orders", None)
                state.metadata.pop("initial_done", None)
        finally:
            specialist_done.reset(token)
            self._in_initial = False

    @staticmethod
    def _order_key(wo: WorkOrder) -> str:
        return f"{wo.specialist}\n{wo.focus}"

    def _record_initial_done(self, wo: WorkOrder) -> None:
        """A work order of the initial phase succeeded: record it, so a resume does not run it again."""
        state = getattr(self, "_state", None)
        if state is None or not isinstance(getattr(state, "metadata", None), dict):
            return
        done = state.metadata.setdefault("initial_done", [])
        key = self._order_key(wo)
        if key not in done:
            done.append(key)
            state.save(self._workspace)

    def _save_initial_orders(self, orders: list[WorkOrder]) -> None:
        """Keep the initial phase's work orders until it ends, for a resume after a pause."""
        state = getattr(self, "_state", None)
        if state is None or not isinstance(getattr(state, "metadata", None), dict):
            return
        state.metadata["initial_orders"] = [wo.model_dump() for wo in orders]
        state.save(self._workspace)

    def _initial_orders_left(self, state: Any) -> list[WorkOrder]:
        """The saved initial-phase work orders whose output is not there yet.

        A work order is done when it succeeded (recorded as it succeeded) and
        its specialist's declared output exists and passes its contract
        check; everything else runs again.
        """
        from ..specialists.contract_check import check_specialist_artifacts

        orders = [WorkOrder(**d) for d in state.metadata.get("initial_orders") or []]
        done = set(state.metadata.get("initial_done") or [])
        # Output the researcher approved as it is, although it failed its contract.
        accepted = set(state.metadata.get("contract_accepted_orders") or [])
        left = []
        for wo in orders:
            key = self._order_key(wo)
            complete = key in done and (
                key in accepted or all(c.ok for c in check_specialist_artifacts(self._workspace, wo.specialist))
            )
            if not complete:
                left.append(wo)
        return left

    async def _initial_phase_body(self) -> None:
        """Run the initial design + data collection specialists.

        The pipeline is useless if the strategist failed to plan the initial
        phase (e.g. produced prose instead of JSON). Raise so the run is
        marked FAILED rather than silently advancing to a review phase with
        no draft to review.
        """
        # Resuming after a researcher step inside this phase: continue with the
        # work orders that had not run yet, instead of planning afresh.
        state = getattr(self, "_state", None)
        if state is not None and "pending_orders" in (getattr(state, "metadata", None) or {}):
            pending = [WorkOrder(**d) for d in state.metadata.pop("pending_orders")]
            self._save_initial_orders(pending)
            # A second researcher step after the same specialists (e.g. the
            # pre-registration after the design review) stops before anything runs.
            await self._between_groups(set(), pending)
            if pending:
                self._contributions.extend(await self._execute_orders(pending))
            return
        if state is not None and (getattr(state, "metadata", None) or {}).get("initial_orders"):
            # Resuming after a pause inside this phase (the spending limit, a
            # circuit breaker, a crash): the work orders already planned, minus
            # those whose output is there and complete. Nothing is planned or
            # paid for twice.
            left = self._initial_orders_left(state)
            logger.info(
                "Resuming the initial phase of paper %s: %d of %d work orders left (%s)",
                self._paper_id,
                len(left),
                len(state.metadata["initial_orders"]),
                ", ".join(wo.specialist for wo in left) or "none",
            )
            if left:
                await self._between_groups(set(), left)
                self._contributions.extend(await self._execute_orders(left))
            return

        decision = await self._strategist.decide("designing", iteration=0)
        if decision.action == "fail":
            raise RuntimeError(f"Strategist could not plan the initial phase: {decision.rationale}")
        if not decision.work_orders:
            raise RuntimeError(
                "Strategist returned no work orders for the initial phase — cannot "
                "proceed without specialist assignments."
            )
        self._save_initial_orders(self._to_contract_orders(decision.work_orders))
        contributions = await self._dispatch(decision)
        if not contributions:
            raise RuntimeError("Initial phase produced no contributions.")
        self._contributions.extend(contributions)

    async def _run_iterative_phase(self) -> PaperStatus:
        """Iterative improvement loop with ceiling detection."""
        for iteration in range(1, _MAX_ITERATIONS + 1):
            self._iteration = iteration
            logger.info("Iteration %d for paper %s", iteration, self._paper_id)

            decision = await self._strategist.decide("in_progress", iteration=iteration)
            if decision.action == "complete":
                return PaperStatus.IN_PROGRESS
            if decision.action == "fail":
                raise RuntimeError(f"Strategist declared failure: {decision.rationale}")

            contributions = await self._dispatch(decision)
            self._contributions.extend(contributions)

            # Ceiling detection after first iteration
            if iteration >= 1:
                ceiling = await self._strategist.ceiling_check(iteration, self._pivot_count)
                logger.info("Ceiling check: %s (iter=%d)", ceiling.verdict, iteration)

                if ceiling.verdict == "proceed_to_review":
                    break
                if ceiling.verdict == "pivot" and self._pivot_count < _MAX_PIVOTS:
                    self._pivot_count += 1
                    pivot_contributions = await execute_parallel(
                        self._to_contract_orders(ceiling.suggested_pivots),
                        self._backend,
                        self._workspace,
                        self._model,
                        self._extra_tools,
                        self._extra_handlers,
                        self._backend_name,
                        self._governance,
                    )
                    self._contributions.extend(pivot_contributions)
                    break  # one pivot per paper
                if ceiling.verdict == "continue":
                    # Explicitly fall through to the next iteration. On the final
                    # iteration this lets the for-loop exit naturally — but we log
                    # so it doesn't look like the ceiling check was satisfied.
                    if iteration == _MAX_ITERATIONS:
                        logger.warning(
                            "Ceiling check returned 'continue' on final iteration %d; "
                            "exiting iterative phase without quality-ceiling confirmation",
                            iteration,
                        )
                    continue
                # Any other verdict is unrecognised — log and proceed defensively.
                logger.warning(
                    "Unrecognised ceiling decision '%s' at iter=%d; treating as proceed_to_review",
                    ceiling.verdict,
                    iteration,
                )
                break

        return PaperStatus.CEILING_CHECK

    def _governance_enforces(self, gate: str) -> bool:
        """True iff `gate` should BLOCK under the active regime.

        The matrix itself lives in :mod:`src.core.governance` because the
        specialist layer (output contracts, cascade guard) consults the same
        table — when it didn't, `off` and `contracts` behaved identically.
        """
        return governance_enforces(getattr(self, "_governance", DEFAULT_REGIME), gate)

    def _should_pause_for_review(self, stage: str, state: Any) -> bool:
        """True iff the run should pause after `stage` for human review — i.e.
        the researcher requested a checkpoint here and hasn't approved it yet."""
        return stage in self._review_stages and not state.is_approved(stage)

    # ── the researcher step ────────────────────────────────────────────────

    async def _stop_for_researcher(self, step: Any, state: Any) -> None:
        """Stop the run at a researcher or preregister step (raises)."""
        from ..pipeline.preregistration import PREREG_FILE, assemble

        files = list(step.files)
        if step.kind == "preregister":
            await self._guard_preregistration(step.name, state)
            assemble(self._workspace, step.files)
            files = [PREREG_FILE]
        state.pending_review_stage = step.name
        state.metadata["review"] = {"kind": step.kind, "files": files}
        state.save(self._workspace)
        raise HumanReviewRequestedError(step.name)

    async def _guard_preregistration(self, name: str, state: Any) -> None:
        """Refuse to present or freeze a pre-registration once anything has been estimated.

        A pre-registration fixes the plan before results exist; one assembled
        after the estimates is not one. When estimation output is already in
        the workspace (see preregistration.estimation_outputs), the check is
        recorded like every gate and the run stops at this step with the list.
        Approving does not pass it: the researcher sends the specialist that
        produced the output back, the outputs are moved aside and recorded
        (never deleted), and the check runs again.
        """
        from ..pipeline.preregistration import LOCK_FILE, estimation_outputs

        if (self._workspace / LOCK_FILE).is_file():
            return  # already frozen: later estimates are the point
        found = estimation_outputs(self._workspace)
        detail = ("estimation output before the freeze: " + ", ".join(found)) if found else "clean"
        blocking = await self._record_gate("preregistration", passed=not found, detail=detail)
        if not found or not blocking:
            if isinstance(getattr(state, "metadata", None), dict):
                state.metadata.pop("preregistration_blocked", None)
            return
        state.metadata["preregistration_blocked"] = found
        if name in state.approved_stages:
            state.approved_stages.remove(name)
        reason = (
            f"estimation output already exists before the pre-registration was frozen: {', '.join(found)}. "
            "Send back the specialist that produced it; the outputs are then moved to set_aside/ and "
            "recorded, and this check runs again."
        )
        state.pending_review_stage = name
        state.metadata["review"] = {"kind": "gate", "files": [], "reasons": [reason]}
        state.save(self._workspace)
        raise GateHaltError(name, [reason])

    async def _freeze_preregistration(self, name: str) -> None:
        from ...db.events import log_event
        from ..pipeline.preregistration import LOCK_FILE, freeze

        state = getattr(self, "_state", None)
        if state is not None and isinstance(getattr(state, "metadata", None), dict):
            was_blocked = "preregistration_blocked" in state.metadata
            await self._guard_preregistration(name, state)  # raises while estimates exist
            step = self._spec.step(name) if getattr(self, "_spec", None) is not None else None
            if was_blocked and step is not None:
                # The approval cleared the check; the researcher has yet to see
                # the pre-registration itself, so stop there before freezing.
                if name in state.approved_stages:
                    state.approved_stages.remove(name)
                await self._stop_for_researcher(step, state)

        already = (self._workspace / LOCK_FILE).is_file()
        lock = freeze(self._workspace)
        if not already:
            await log_event(self._paper_id, "preregistration", stage=name, payload=lock)

    async def _between_groups(self, done: set[str], remaining: list[WorkOrder]) -> None:
        """After each group of a dispatch: stop if a researcher step's specialists are done."""
        state = getattr(self, "_state", None)
        # Only the initial phase resumes from saved work orders, so that is the
        # only dispatch a researcher step may stop.
        if state is None or not getattr(self, "_triggers", None) or not getattr(self, "_in_initial", False):
            return
        finished = set(state.metadata.get("done_specialists", [])) | done
        state.metadata["done_specialists"] = sorted(finished)
        for trig in self._triggers:
            if not trig.applies_to(self._mode) or state.is_complete(trig.name):
                continue
            if trig.kind == "gate":
                # A check is never approved past; it runs until the design passes.
                if set(trig.after) <= finished or _estimation_next(remaining):
                    await self._run_gate_trigger(trig, state, remaining)
                continue
            if state.is_approved(trig.name):
                continue
            if set(trig.after) <= finished:
                state.metadata["pending_orders"] = [wo.model_dump() for wo in remaining]
                await self._stop_for_researcher(trig, state)

    async def _run_open_gates(self, state: Any, remaining: list[WorkOrder]) -> None:
        """Run every gate trigger that applies and has not passed yet."""
        for trig in getattr(self, "_triggers", []):
            if trig.kind == "gate" and trig.applies_to(self._mode) and not state.is_complete(trig.name):
                await self._run_gate_trigger(trig, state, remaining)

    async def _run_gate_trigger(self, step: Any, state: Any, remaining: list[WorkOrder]) -> None:
        """Run a check that sits inside the dispatch; pass, record, retry once, or halt.

        Recorded like every gate (``gate_enforced`` or ``gate_shadow``), so the
        verdict and its reasons appear in the dossier. On a blocking failure the
        run stops for the researcher at this step (GateHaltError), with the work
        orders that had not run saved, and the check runs again on resume.
        """
        from ..specialists.dispatcher import execute_work_order

        design_file, owner = _DESIGN_CHECKS.get(step.check, ("", ""))
        result = self._run_design_check(step)
        shadow = step.on_fail == "shadow"
        blocking = await self._record_gate(step.check, passed=result.passed, detail=result.detail(), enforce=not shadow)
        retry_key = f"retried_{step.name}"
        if not result.passed and blocking and step.on_fail == "retry" and owner and not state.metadata.get(retry_key):
            state.metadata[retry_key] = True
            state.save(self._workspace)
            order = WorkOrder(
                paper_id=self._paper_id,
                specialist=owner,
                focus=(
                    f"The check '{step.check}' refused the design in {design_file} before estimation. "
                    f"Revise {design_file} (and your strategy file where it changes) so that it passes: "
                    + "; ".join(result.reasons)
                ),
            )
            contribution = await execute_work_order(
                order,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
                self._governance,
            )
            self._contributions.append(contribution)
            self._update_failure_counts([contribution])
            result = self._run_design_check(step)
            blocking = await self._record_gate(
                step.check, passed=result.passed, detail=result.detail(), enforce=not shadow
            )
        if result.passed or not blocking:
            state.mark_complete(step.name)
            if state.pending_review_stage == step.name:
                state.pending_review_stage = None
            state.save(self._workspace)
            return
        if getattr(self, "_in_initial", False):
            state.metadata["pending_orders"] = [wo.model_dump() for wo in remaining]
        files = [f for f in (design_file, "identification_strategy.md") if f]
        state.pending_review_stage = step.name
        state.metadata["review"] = {"kind": "gate", "files": files, "reasons": list(result.reasons)}
        state.save(self._workspace)
        raise GateHaltError(step.name, result.reasons)

    async def _run_specialists_step(self, step: Any) -> None:
        """A template's fixed set of specialists (a `specialists` step with no phase of its own).

        One group when `parallel`, else one after another in the listed order.
        Each gets the registry's default focus for it; retries, contract
        feedback and the cascade guard are the dispatcher's, as everywhere.
        """
        from ..specialists.registry import POLISH_SPECIALISTS, REVIEWER_SPECIALISTS, SPECIALIST_DEFAULT_FOCUS

        tolerant = set(REVIEWER_SPECIALISTS) | set(POLISH_SPECIALISTS)
        state = getattr(self, "_state", None)
        meta = state.metadata if state is not None and isinstance(getattr(state, "metadata", None), dict) else {}
        # After a stop for output that failed its contract: the specialists of
        # this step that succeeded, or whose output the researcher approved, are done.
        done_here = set((meta.get("step_done") or {}).get(step.name, []))
        for spec_name in step.run:
            if spec_name not in tolerant and self._failure_counts.get(spec_name, 0) >= _MAX_SPECIALIST_ATTEMPTS:
                raise CircuitBreakerError(
                    specialist=spec_name,
                    attempts=self._failure_counts[spec_name],
                    last_error=self._last_specialist_errors.get(spec_name),
                )
        orders = [
            WorkOrder(
                paper_id=self._paper_id,
                specialist=spec_name,
                focus=SPECIALIST_DEFAULT_FOCUS.get(
                    spec_name, f"Carry out your part of this study (step '{step.name}') as your skills describe."
                ),
                parallel_group=0 if step.parallel else i,
                context_tier=1,
            )
            for i, spec_name in enumerate(step.run)
            if spec_name not in done_here
        ]
        if not orders:
            (meta.get("step_done") or {}).pop(step.name, None)
            return
        contributions = await execute_with_dependencies(
            orders,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
        )
        self._contributions.extend(contributions)
        self._update_failure_counts(contributions)
        (meta.get("step_done") or {}).pop(step.name, None)
        failed = [c for c in contributions if not c.success and c.specialist not in tolerant]
        if failed:
            raise RuntimeError(
                f"step '{step.name}': " + "; ".join(f"{c.specialist} failed: {(c.error or '?')[:500]}" for c in failed)
            )

    async def _run_check_step(self, step: Any, state: Any) -> None:
        """A check that runs as a step of its own: pass, record, retry once, or halt.

        Same contract as a gate inside the dispatch: the verdict is recorded
        (``gate_enforced`` / ``gate_shadow``) and appears in the dossier; a
        blocking failure stops the run at this step with its reasons, and the
        check runs again on resume. Approving does not pass it.
        """
        from ...db.events import log_event

        fn = _sequence_check(step.check)
        result = await asyncio.to_thread(fn, self._workspace, **step.settings)
        for supplied in getattr(result, "inputs", ()) or ():
            # A file the researcher supplied (e.g. the paper), fingerprinted: the
            # dossier lists it as researcher input, apart from the package.
            await log_event(self._paper_id, "researcher_input", stage=step.name, payload=dict(supplied))
        shadow = step.on_fail == "shadow"
        blocking = await self._record_gate(step.check, passed=result.passed, detail=result.detail(), enforce=not shadow)
        retry_key = f"retried_{step.name}"
        if not result.passed and blocking and step.on_fail == "retry" and not state.metadata.get(retry_key):
            state.metadata[retry_key] = True
            state.save(self._workspace)
            result = await asyncio.to_thread(fn, self._workspace, **step.settings)
            blocking = await self._record_gate(
                step.check, passed=result.passed, detail=result.detail(), enforce=not shadow
            )
        if result.passed or not blocking:
            if state.pending_review_stage == step.name:
                state.pending_review_stage = None
                state.metadata.pop("review", None)
            return
        state.pending_review_stage = step.name
        state.metadata["review"] = {
            "kind": "gate",
            "files": list(_SEQUENCE_CHECK_FILES.get(step.check, ())),
            "reasons": list(result.reasons),
        }
        state.save(self._workspace)
        raise GateHaltError(step.name, result.reasons)

    def _run_design_check(self, step: Any) -> Any:
        """The deterministic check a gate trigger names, with the template's settings."""
        if step.check == "event_window":
            from ..pipeline.event_window import check_event_window

            return check_event_window(self._workspace, **step.settings)
        raise ValueError(f"check {step.check!r} cannot run inside the dispatch")

    async def _settle_researcher_decisions(self, state: Any) -> None:
        """On (re)start: freeze approved pre-registrations, run what was sent back,
        and stop again at the researcher step the send-back came from."""
        from ...db.events import log_event

        if not isinstance(getattr(state, "metadata", None), dict):
            return  # a state without researcher bookkeeping (older files, test doubles)
        for s in self._spec.steps:
            if s.kind == "preregister" and state.is_approved(s.name):
                await self._freeze_preregistration(s.name)
                if s.after:
                    state.mark_complete(s.name)
        for trig in getattr(self, "_triggers", []):
            if trig.kind == "researcher" and state.is_approved(trig.name):
                state.mark_complete(trig.name)

        if state.metadata.get("review", {}).get("kind") == "contract":
            await self._settle_contract(state)
            return
        reruns = state.metadata.pop("rerun", [])
        if not reruns:
            return
        state.metadata.pop("sent_back", None)
        # Checks that run at every start (a sequence gate with resumable=false,
        # e.g. the replication template's fetch, which also picks up a paper the
        # researcher supplied) run before a specialist is sent back to work, so
        # it works on what they provide.
        pending_at = state.pending_review_stage
        # (A rerun of a study not stopped at a researcher step stops nowhere yet: the loop runs them in order.)
        for s in self._spec.steps if pending_at else []:
            if s.name == pending_at:
                break
            if s.kind == "gate" and not s.resumable and s.check in SEQUENCE_CHECKS and s.applies_to(self._mode):
                await self._run_check_step(s, state)
        if state.metadata.get("preregistration_blocked"):
            # Sent back from a pre-registration that estimation output blocked:
            # move that output aside (recorded, never deleted) before the rerun.
            from ..pipeline.preregistration import estimation_outputs, set_aside

            found = estimation_outputs(self._workspace)
            if found:
                manifest = set_aside(self._workspace, found)
                await log_event(
                    self._paper_id, "estimation_set_aside", stage=state.pending_review_stage, payload=manifest
                )
        step_names = [s.name for s in self._spec.steps]
        rerun_steps = False
        for r in reruns:
            target, remark = r["target"], r["remark"]
            await log_event(self._paper_id, "researcher_rerun", stage=target, payload={"remark": remark})
            if target in step_names:
                # Re-run the step and everything after it; the loop stops again
                # at the researcher step, which is still pending.
                later = step_names[step_names.index(target) :]
                state.completed_stages = [c for c in state.completed_stages if c not in later]
                rerun_steps = True
            else:
                protected = await self._researcher_edited_files()
                focus = f"Revise your output. The researcher sent it back with this remark: {remark}"
                extra: dict[str, Any] = {}
                if protected:
                    # A send-back revises the specialist's work, not the
                    # researcher's: files the researcher edited are neither
                    # requested again nor left overwritten.
                    focus += (
                        " Do not change these files; the researcher edited them and they stand as they are: "
                        + ", ".join(sorted(protected))
                        + "."
                    )
                    extra["keep_files"] = sorted(protected)
                order = WorkOrder(paper_id=self._paper_id, specialist=target, focus=focus, extra=extra)
                before = {f: (self._workspace / f).read_bytes() for f in protected}
                contributions = await self._execute_orders([order])
                self._contributions.extend(contributions)
                await self._restore_researcher_edits(before, target)
        state.save(self._workspace)
        pending = state.pending_review_stage
        if pending and not state.is_approved(pending) and not rerun_steps:
            step = self._spec.step(pending)
            if step is not None and step.kind == "preregister" and state.metadata.get("preregistration_blocked"):
                # Back at a pre-registration that estimation output blocked: the
                # check runs again now (halting if anything is still there), and
                # when the workspace is clean the researcher sees the
                # pre-registration itself.
                await self._guard_preregistration(pending, state)
                await self._stop_for_researcher(step, state)
            if state.metadata.get("review", {}).get("kind") in ("deviation", "numbers"):
                # Sent back from a change to the pre-registered plan: the plan
                # check runs again in the estimation gate (halting again, with
                # the files as they are now, if the change is still there).
                # Likewise from the number check: the review step runs again and
                # its number check with it, before any reviewer.
                state.pending_review_stage = None
                state.metadata.pop("review", None)
                state.save(self._workspace)
                return
            raise HumanReviewRequestedError(pending)

    async def _stop_for_contract(self, cf: ContractFailureError, state: Any) -> dict[str, Any]:
        """Stop the run for the researcher: output kept failing its contract after the last attempt.

        The researcher step (kind ``contract``) lists, per specialist, the
        violations of each attempt and the files involved. The researcher can
        edit a file, give an instruction, send a step back (the failed
        specialist included: it gets fresh attempts with the remark), or
        approve the output as it is (recorded in the dossier, the output marked
        as failing its contract). A plain resume gives the failed specialists
        fresh attempts. Specialists that succeeded keep their output.
        """
        from ...db.events import log_event
        from ..pipeline.researcher import CONTRACT_STEP, contract_reasons

        previous = state.metadata.get("contract_pause") or {}
        phase = getattr(self, "_current_step", None) or previous.get("phase")
        succeeded = sorted({c.specialist for c in cf.contributions if c.success})
        phase_step = self._spec.step(phase) if phase else None
        if phase_step is not None and phase_step.kind == "specialists":
            step_done = state.metadata.setdefault("step_done", {})
            step_done[phase] = sorted(set(step_done.get(phase, [])) | set(succeeded))
        files = list(dict.fromkeys(n for f in cf.failures for n in f["files"]))
        reasons = contract_reasons(cf.failures)
        state.metadata["contract_pause"] = {"phase": phase, "failed": cf.failures, "succeeded": succeeded}
        if state.pending_review_stage and state.pending_review_stage != CONTRACT_STEP:
            # Stopped from a send-back at another researcher step: come back to it afterwards.
            state.metadata["contract_pause"]["return_to"] = state.pending_review_stage
        if CONTRACT_STEP in state.approved_stages:
            state.approved_stages.remove(CONTRACT_STEP)
        state.pending_review_stage = CONTRACT_STEP
        state.metadata["review"] = {"kind": "contract", "files": files, "reasons": reasons}
        state.save(self._workspace)
        names = ", ".join(f["specialist"] for f in cf.failures)
        logger.warning("Pipeline stopped for the researcher (output contract) for paper %s: %s", self._paper_id, names)
        await log_event(
            self._paper_id,
            "contract_halted",
            stage=phase,
            payload={
                "specialists": [
                    {"specialist": f["specialist"], "attempts": f["attempts"], "files": f["files"]} for f in cf.failures
                ],
                "succeeded": succeeded,
            },
        )
        await self._update_status(
            PaperStatus.PAUSED,
            error=(
                f"Stopped for you: the output of {names} did not pass its contract check after "
                f"{MAX_SPECIALIST_ATTEMPTS} attempts. Review it with `e2er review {self._paper_id}`: approve the "
                "output as it is, edit a file, give an instruction, or send the specialist back with a remark."
            ),
        )
        return {"status": "paused", "reason": "contract", "specialists": [f["specialist"] for f in cf.failures]}

    async def _settle_contract(self, state: Any) -> None:
        """On resume after a stop for output that failed its contract (see _stop_for_contract)."""
        from ...db.events import log_event
        from ..pipeline.researcher import CONTRACT_STEP

        pause = state.metadata.get("contract_pause") or {}
        approved = state.is_approved(CONTRACT_STEP)
        reruns = state.metadata.pop("rerun", [])
        state.metadata.pop("sent_back", None)
        if CONTRACT_STEP in state.approved_stages:
            state.approved_stages.remove(CONTRACT_STEP)
        failed = [f for f in pause.get("failed", []) if isinstance(f, dict)]
        phase = pause.get("phase")

        def mark_done(order: dict[str, Any], specialist: str) -> None:
            if phase == "initial":
                self._record_initial_done(WorkOrder(**order))
            elif phase:
                step_done = state.metadata.setdefault("step_done", {})
                step_done[phase] = sorted(set(step_done.get(phase, [])) | {specialist})

        if approved:
            # The researcher took the output as it is (apply_action recorded which, with its violations).
            keys = state.metadata.setdefault("contract_accepted_orders", [])
            for f in failed:
                keys.append(self._order_key(WorkOrder(**f["order"])))
                mark_done(f["order"], f["specialist"])
        else:
            step_names = [s.name for s in self._spec.steps]
            sent: set[str] = set()
            for r in reruns:
                target, remark = r["target"], r["remark"]
                await log_event(self._paper_id, "researcher_rerun", stage=target, payload={"remark": remark})
                if target in step_names:
                    later = step_names[step_names.index(target) :]
                    state.completed_stages = [c for c in state.completed_stages if c not in later]
                    sent.update(f["specialist"] for f in failed)  # the step runs them again
                    continue
                order = next((f["order"] for f in failed if f["specialist"] == target), None)
                focus = f"Revise your output. The researcher sent it back with this remark: {remark}"
                if order is not None:
                    focus = f"{order.get('focus', '')}\n\n{focus}".strip()
                wo = WorkOrder(paper_id=self._paper_id, specialist=target, focus=focus)
                contributions = await self._execute_orders([wo])  # stops again if it fails its contract
                self._contributions.extend(contributions)
                if order is not None and all(c.success for c in contributions):
                    mark_done(order, target)
                sent.add(target)
            for f in failed:
                if f["specialist"] in sent:
                    continue
                # Fresh attempts, with the researcher's instructions and edits.
                wo = WorkOrder(**{**f["order"], "paper_id": self._paper_id})
                contributions = await self._execute_orders([wo])
                self._contributions.extend(contributions)
                if all(c.success for c in contributions):
                    mark_done(f["order"], f["specialist"])
        state.metadata.pop("contract_pause", None)
        state.metadata.pop("review", None)
        return_to = pause.get("return_to")
        state.pending_review_stage = return_to or None
        state.save(self._workspace)
        if return_to and not state.is_approved(return_to):
            raise HumanReviewRequestedError(return_to)

    async def _researcher_edited_files(self) -> dict[str, str]:
        """Workspace files the researcher edited that still hold the researcher's version.

        From the ``researcher_action`` edit events: file -> SHA-256 after the
        researcher's latest edit, kept only while the file still has it.
        """
        import hashlib

        from ...db.events import fetch_events

        latest: dict[str, str] = {}
        try:
            events = await fetch_events(self._paper_id)
        except Exception:  # noqa: BLE001 — without the log there is nothing to protect
            return {}
        for e in events:
            if e.get("event_type") != "researcher_action":
                continue
            payload = e.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    continue
            if payload.get("action") == "edit" and payload.get("file") and payload.get("sha256_after"):
                latest[str(payload["file"])] = str(payload["sha256_after"])
        out: dict[str, str] = {}
        for name, digest in latest.items():
            path = self._workspace / name
            if "/" not in name and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                out[name] = digest
        return out

    async def _restore_researcher_edits(self, before: dict[str, bytes], specialist: str) -> None:
        """Put back a researcher-edited file a sent-back specialist overwrote; keep and record its version."""
        import hashlib
        from datetime import UTC, datetime

        from ...db.events import log_event
        from ..pipeline.preregistration import SET_ASIDE_DIR

        for name, original in before.items():
            path = self._workspace / name
            now = path.read_bytes() if path.is_file() else None
            if now == original:
                continue
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            kept = None
            if now is not None:
                dest = self._workspace / SET_ASIDE_DIR / stamp / "overwritten"
                dest.mkdir(parents=True, exist_ok=True)
                (dest / name).write_bytes(now)
                kept = str((dest / name).relative_to(self._workspace))
            path.write_bytes(original)
            await log_event(
                self._paper_id,
                "researcher_edit_restored",
                specialist=specialist,
                payload={
                    "file": name,
                    "sha256_researcher": hashlib.sha256(original).hexdigest(),
                    "sha256_specialist": hashlib.sha256(now).hexdigest() if now is not None else None,
                    "specialist_version": kept,
                },
            )

    async def _record_gate(self, gate: str, *, passed: bool, detail: str = "", enforce: bool = True) -> bool:
        """Log a gate verdict and return whether it should BLOCK this run.

        Emits `gate_enforced` when the regime enforces this gate, else
        `gate_shadow` — so a shadowed failure (fabrication the full stack
        would have caught) is measured, not silently absent. The caller
        blocks iff the return value is True (enforced) AND the gate failed.
        """
        from ...db.events import log_event

        # `enforce=False` is a step's own `on_fail = "shadow"`: the verdict is
        # recorded, never blocking, whatever the regime.
        enforced = enforce and self._governance_enforces(gate)
        await log_event(
            self._paper_id,
            "gate_enforced" if enforced else "gate_shadow",
            stage=gate,
            payload={
                "gate": gate,
                "passed": passed,
                "enforced": enforced,
                "regime": getattr(self, "_governance", DEFAULT_REGIME),
                "detail": detail[:2000],
            },
        )
        return enforced

    async def _check_preregistered_plan(self, workspace: Path) -> None:
        """The plan files against the frozen fingerprints; halt on a change nobody approved."""
        from ...db.events import log_event
        from ..pipeline.preregistration import PREREG_FILE, describe_deviation, deviation_details, load_lock

        lock = load_lock(workspace)
        if lock is None:
            return
        details = deviation_details(workspace, lock)
        found = [d["text"] for d in details]
        open_ = [d for d in details if not d["approved"]]
        payload: dict[str, Any] = {"passed": not found, "deviations": found, "frozen_at": lock.get("frozen_at")}
        approved = [d["text"] for d in details if d["approved"]]
        if approved:
            payload["approved"] = approved
        await log_event(self._paper_id, "preregistration_check", stage="estimation_gate", payload=payload)
        state = getattr(self, "_state", None)
        if not open_:
            if state is not None and isinstance(getattr(state, "metadata", None), dict):
                state.metadata.pop("preregistration_deviation", None)
            return
        reasons = [describe_deviation(d) for d in open_]
        detail = "the plan changed after the pre-registration: " + "; ".join(reasons)
        blocking = await self._record_gate("preregistration", passed=False, detail=detail)
        if not blocking or state is None or not isinstance(getattr(state, "metadata", None), dict):
            return
        reasons.append(
            "Approve to keep the change as a deviation from the pre-registered plan (your decision is recorded "
            "in the dossier and the deviation is disclosed), or edit the file back, or send back the step that "
            "changed it; the estimation does not run until then."
        )
        if "estimation_gate" in state.approved_stages:
            state.approved_stages.remove("estimation_gate")
        state.metadata["preregistration_deviation"] = [
            {k: d[k] for k in ("file", "sha256_frozen", "sha256_now")} for d in open_
        ]
        files = [d["file"] for d in open_ if d["file"] != PREREG_FILE and (workspace / d["file"]).is_file()]
        state.pending_review_stage = "estimation_gate"
        state.metadata["review"] = {"kind": "deviation", "files": files, "reasons": reasons}
        state.save(workspace)
        raise GateHaltError("estimation_gate", reasons)

    async def _enforce_estimation_gate(self) -> None:
        """Deterministic phase gate: an empirical paper with a populated data
        warehouse may not proceed past the analysis phase without a
        contract-clean estimation (non-empty, contains a regression, and
        implements the declared identification spec when one exists).

        The specialist-level contract flips a bad econometrics attempt to
        failure, but nothing compelled the strategist to re-dispatch — it
        could (and did) proceed to drafting around ``{}``. This gate closes
        that hole mechanically: re-dispatch econometrics_specialist (its
        consume-once contract feedback and any captured script traceback are
        injected automatically) until the contract is clean, or trip the
        circuit breaker into a resumable PAUSED — never a hollow paper.

        Runs for empirical and mixed papers. Honest-failure escape: papers without a data warehouse (theory,
        literature-only, design-without-estimates) are untouched.

        With a frozen pre-registration, the plan files are compared with their
        fingerprints first. A change the researcher has not approved stops the
        run here, at a researcher step that names each changed file with its
        SHA-256 before and after: the researcher approves the deviation (it is
        recorded in the lock and the dossier, and `e2er verify` reports it),
        edits the file back, or sends back the step that changed it.
        """
        workspace: Path | None = getattr(self, "_workspace", None)
        if workspace is not None:
            await self._check_preregistered_plan(workspace)
        if self._methodology not in ("empirical", "mixed"):
            return
        from ...db.paper_data_db import has_data_db

        if not has_data_db(self._workspace):
            return

        from ..specialists.contract_check import check_specialist_artifacts
        from ..specialists.dispatcher import execute_work_order

        specialist = "econometrics_specialist"

        # Shadow mode applies to VERIFICATION failures only. A hollow or
        # unparseable estimation file is a reliability failure: the run is
        # broken, and repairing it is not "governing" the paper. Previously
        # this returned early under `off`, so a crashed estimation script was
        # never retried and the drafter wrote tables over `{}`.
        if not self._governance_enforces("estimation"):
            failures = [c for c in check_specialist_artifacts(self._workspace, specialist) if not c.ok]
            # getattr: reliability is the safe default, so anything that
            # predates the kind field (or a test double) still blocks.
            reliability = [c for c in failures if getattr(c, "kind", KIND_RELIABILITY) == KIND_RELIABILITY]
            detail = "; ".join(f"{c.artifact}: {c.reason}" for c in failures) or "clean"
            await self._record_gate("estimation", passed=not failures, detail=detail)
            if not reliability:
                return
            logger.warning(
                "Estimation gate: %d reliability failure(s) under governance=%s — repairing anyway (%s)",
                len(reliability),
                self._governance,
                "; ".join(f"{c.artifact}: {c.reason}" for c in reliability),
            )

        while True:
            failures = [c for c in check_specialist_artifacts(self._workspace, specialist) if not c.ok]
            if not self._governance_enforces("estimation"):
                # Repair loop entered for reliability only: stop as soon as the
                # file is real, without demanding the verification contracts a
                # shadowed regime is meant to leave alone.
                failures = [c for c in failures if getattr(c, "kind", KIND_RELIABILITY) == KIND_RELIABILITY]
            if not failures:
                await self._record_gate("estimation", passed=True, detail="clean")
                return
            summary = "; ".join(f"{c.artifact}: {c.reason}" for c in failures)
            await self._record_gate("estimation", passed=False, detail=summary)

            attempts = self._failure_counts.get(specialist, 0)
            if attempts >= _MAX_SPECIALIST_ATTEMPTS:
                logger.error(
                    "Estimation gate: circuit breaker tripped for paper %s — %s failed %d times; %s",
                    self._paper_id,
                    specialist,
                    attempts,
                    summary,
                )
                raise CircuitBreakerError(
                    specialist=specialist,
                    attempts=attempts,
                    last_error=self._last_specialist_errors.get(specialist) or summary,
                )

            logger.warning(
                "Estimation gate: blocking post-analysis phases for paper %s (attempt %d/%d) — %s",
                self._paper_id,
                attempts + 1,
                _MAX_SPECIALIST_ATTEMPTS,
                summary,
            )
            order = WorkOrder(
                paper_id=self._paper_id,
                specialist=specialist,
                focus=(
                    "The analysis phase ended WITHOUT a valid estimation, so the paper "
                    "is blocked before drafting. Produce a working run_estimation.py and "
                    "a populated estimation_results.json whose 'main' entry implements "
                    "the declared identification (see identification_spec.json). Feedback "
                    "from the failed attempt, if any, is included below."
                ),
                context_tier=2,
            )
            contribution = await execute_work_order(
                order,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
                self._governance,
            )
            self._contributions.append(contribution)
            self._update_failure_counts([contribution])

    async def _run_self_attack_phase(self) -> PaperStatus:
        """Adversarial self-review to find critical flaws before external review."""
        logger.info("Running self-attack phase for paper %s", self._paper_id)
        await self._update_status(PaperStatus.SELF_ATTACK)

        attack_report = await self._strategist.run_self_attack()
        report_path = self._workspace / "self_attack_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "findings": [f.__dict__ for f in attack_report.findings],
                    "overall_severity": attack_report.overall_severity,
                },
                indent=2,
            )
        )
        logger.info(
            "Self-attack: %d findings, max severity %d",
            len(attack_report.findings),
            attack_report.overall_severity,
        )

        if not attack_report.findings:
            logger.info("Self-attack: no findings — skipping critical-finding revision step")
            return PaperStatus.SELF_ATTACK

        # v0.6 step 4: critical findings drive ONE patch_revisor call,
        # not three parallel revisor calls writing to paper_draft.tex.
        # Pre-v0.6 the parallel writes raced on the same file — last
        # writer won, the other two revisions were silently discarded,
        # and the surviving rewrite was produced without knowledge of
        # the other findings. The patch_revisor receives all the
        # critical findings in one work order, emits one patch file,
        # the merger applies it sequentially.
        if attack_report.critical_findings:
            from .findings import collect_self_attack_findings

            # severity_floor=7 mirrors the pre-v0.6 critical-only cap
            # (SelfAttackReport.critical_findings uses the same
            # threshold). Limit to top 3 to bound spend.
            findings = collect_self_attack_findings(attack_report, severity_floor=7)
            findings = sorted(findings, key=lambda f: -f.severity)[:3]

            if findings:
                try:
                    merge_result = await self._dispatch_patch_revisor(findings)
                    if merge_result.fully_applied:
                        logger.info(
                            "Self-attack patch: applied %d edits to %d critical findings",
                            merge_result.n_applied,
                            len(findings),
                        )
                    else:
                        # Don't transition to REJECTED — self-attack is
                        # advisory. The review phase will catch any
                        # remaining issues. Just log so the operator
                        # knows the patch was partial.
                        first_failures = "; ".join(f"[{r.edit.target}] {r.error}" for r in merge_result.failed[:3])
                        logger.warning(
                            "Self-attack patch: %d edits applied, %d failed. First failures: %s",
                            merge_result.n_applied,
                            merge_result.n_failed,
                            first_failures,
                        )
                except FileNotFoundError as e:
                    logger.warning(
                        "Self-attack patch_revisor did not produce a patch file: %s",
                        e,
                    )

        return PaperStatus.SELF_ATTACK

    async def _run_polish_phase(self) -> PaperStatus:
        """Parallel polish stack targeting specific paper pathologies."""
        logger.info("Running polish stack for paper %s", self._paper_id)
        await self._update_status(PaperStatus.POLISH)

        attack_report_path = self._workspace / "self_attack_report.json"
        active_polish = _select_polish_specialists(attack_report_path)

        polish_orders = [
            WorkOrder(
                paper_id=self._paper_id,
                specialist=s,
                focus=f"Polish {s.replace('polish_', '')} aspects of the paper.",
                context_tier=2,
            )
            for s in active_polish
        ]

        contributions = await execute_parallel(
            polish_orders,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
        )
        self._contributions.extend(contributions)
        return PaperStatus.POLISH

    def _reviewers_for_methodology(self) -> list[str]:
        """Filter the reviewer roster by methodology.

        Theoretical papers don't have data to review — `data_reviewer`
        reviewed an empty contract on paper cbe8048f (live test v0.4.5)
        and produced a generic stub for ~$0.34. Skip it.
        """
        if self._methodology == "theoretical":
            return [r for r in REVIEWER_SPECIALISTS if r != "data_reviewer"]
        return list(REVIEWER_SPECIALISTS)

    async def _run_review_phase(self) -> PaperStatus:
        """Parallel formal review by all reviewer specialists.

        Before reviewers run, the programmatic verify_numbers gate checks
        every number in the LaTeX tables against the analyst's source
        JSON files. Critical mismatches → REJECTED before reviewers spend
        tokens. Missing source files → skip with warning (per v0.5.0
        design).
        """
        logger.info("Running review phase for paper %s", self._paper_id)

        # Render results tables deterministically from the JSON sidecars
        # BEFORE the gate runs. Numbers in tables/*.tex come from
        # estimation_results.json / robustness_results.json, so they can't be
        # fabricated; verify_numbers then only sees correct-by-construction
        # tables (it does not resolve \input) plus any hand-written prose.
        # Closes the loop on unresolved table_spec references (one
        # section_writer fix) so the results tables don't ship blank.
        await self._resolve_table_spec()

        # --- verify_numbers pre-review gate (v0.5.0; v0.6 auto-patch loop) ---
        from ..pipeline.verify_numbers import verify_and_save

        draft_path = self._workspace / "paper_draft.tex"
        if draft_path.is_file():
            # verify_and_save always runs and writes number_verification.json —
            # so the report exists (and shadow fabrication is measurable) in
            # every regime. Only the block/auto-patch is regime-gated.
            report = verify_and_save(draft_path, self._workspace)
            enforce_numbers = self._governance_enforces("numbers")
            accepted = self._numbers_accepted(report)
            if report.critical_mismatches and enforce_numbers and not accepted:
                # v0.6 step 5: try to auto-patch before stopping. Auto-patch
                # is an enforcement action (it repairs fabricated cells), so it
                # is skipped in shadow — otherwise it would mask the very
                # fabrication the experiment is measuring.
                report = await self._verify_numbers_auto_patch(report)
                accepted = self._numbers_accepted(report)
            failed_numbers = bool(report.critical_mismatches)
            detail_numbers = ""
            if failed_numbers:
                summary = "; ".join(
                    f"{m.draft_value} vs {m.source_value} ({m.source_key}) at {m.table_context}"
                    for m in report.critical_mismatches[:5]
                )
                detail_numbers = (
                    f"{len(report.critical_mismatches)} critical mismatch(es) between "
                    f"LaTeX tables and source JSON. "
                    f"First {min(5, len(report.critical_mismatches))}: {summary}"
                )
            await self._record_gate("numbers", passed=not failed_numbers, detail=detail_numbers)
            if failed_numbers and enforce_numbers and not accepted:
                # Under `full` a failed number check stops the run for the
                # researcher (it never folds into a --review-at pause, and the
                # reviewers do not run on a draft whose tables disagree with
                # the results until the researcher has decided).
                await self._stop_at_number_check(report)
            await self._settle_number_check(report, enforced=enforce_numbers, accepted=accepted)

        # --- verify_citations pre-review gate (v0.9 M2) ---
        # Mechanical anti-hallucination for references: every \cite
        # resolves in references.bib AND in at least one of OpenAlex /
        # S2 / Crossref. Default policy: hard-block on missing-in-bib
        # only (LaTeX would also fail); ``unverifiable`` is warn-only
        # because preprints / posters legitimately aren't indexed.
        # Flip to hard-block with E2ER_STRICT_CITATION_INTEGRITY=true.
        if draft_path.is_file():
            from ..pipeline.verify_citations import verify_and_save as verify_citations_and_save
            from ..renderer.templates import assemble_refs_bib

            # Assemble refs.bib (literature.bib + user_refs.bib) NOW rather
            # than waiting for the compile phase: the gate must check against
            # the bibliography the PDF will actually be compiled with. Before
            # this, the gate defaulted to references.bib — which nothing
            # writes — and skipped itself on every standard-flow paper.
            refs_bib = assemble_refs_bib(self._workspace)
            # Always runs + writes citation_integrity.json (shadow-measurable).
            cite_report = await verify_citations_and_save(draft_path, self._workspace, bib_path=refs_bib)
            if cite_report.skipped_reason:
                logger.warning(
                    "Paper %s: verify_citations gate SKIPPED (not passed): %s",
                    self._paper_id,
                    cite_report.skipped_reason,
                )
            enforce_cites = self._governance_enforces("citations")
            failed_cites = not cite_report.passed
            detail_cites = ""
            if failed_cites:
                missing = ", ".join(c.cite_key for c in cite_report.missing_checks[:5])
                unverif = ", ".join(c.cite_key for c in cite_report.unverifiable_checks[:5])
                pieces = []
                if cite_report.missing_in_bib:
                    pieces.append(f"{cite_report.missing_in_bib} cited key(s) missing from the bibliography: {missing}")
                if cite_report.strict and cite_report.unverifiable:
                    pieces.append(f"{cite_report.unverifiable} unverifiable cite(s) (strict mode): {unverif}")
                detail_cites = "; ".join(pieces)
            await self._record_gate("citations", passed=not failed_cites, detail=detail_cites)
            if failed_cites and enforce_cites:
                raise StepFailedError(
                    PaperStatus.REJECTED,
                    "Stopped by the citation check: " + detail_cites + ". Fix the bibliography or the draft "
                    "(the workspace keeps both), then `e2er resume` runs the review step and the check again.",
                    "review",
                )

        await self._update_status(PaperStatus.REVIEW)

        review_orders = [
            WorkOrder(
                paper_id=self._paper_id,
                specialist=r,
                focus=f"Conduct a thorough {r.replace('_', ' ')} of this paper.",
                context_tier=2,
            )
            for r in self._reviewers_for_methodology()
        ]

        contributions = await execute_parallel(
            review_orders,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
        )
        self._contributions.extend(contributions)
        if not self._read_review_scores():
            # A review step without a single score is a failed step, never a
            # silent skip: the revision step would have nothing to decide on.
            why = "; ".join(
                f"{c.specialist}: {(c.error or 'no score line in its review')[:200]}"
                for c in contributions
                if c.specialist in REVIEWER_SPECIALISTS
            )
            raise StepFailedError(
                PaperStatus.FAILED,
                "The review step failed: no reviewer produced a score"
                + (f" ({why})" if why else " (no reviewer ran)")
                + ". `e2er resume` runs the review step again.",
                "review",
            )
        return PaperStatus.REVIEW

    async def _run_revision_phase(self, current_status: PaperStatus) -> PaperStatus:
        """Score the draft (internal quality review) and run the revision round the score calls for.

        Scores are parsed from the review file on disk per reviewer, NOT from
        the LLM's chat-side summary (`c.output`). Discovered run #8: under
        the CLI backend, `c.output` is the CLI's final assistant message
        (often "I've written the review" or a one-paragraph summary). It
        doesn't reliably contain the `OVERALL SCORE:` line even when the
        written file does. The file is the canonical artifact; read that.

        The `c.output` chat-summary is used as a fallback only for reviewers
        whose canonical file is absent (e.g. a specialist hard-failed
        before writing). Reviewers are tolerant of partial failure in the
        cascade-detection layer, so missing files don't halt the pipeline.
        """
        scores = self._read_review_scores()
        if not scores:
            # Auto-completing on missing review evidence is dangerous: it
            # produces a "completed" paper with no review trail. Surface as
            # FAILED so the user knows to re-run the review phase.
            state = getattr(self, "_state", None)
            if state is not None and "review" in getattr(state, "completed_stages", []):
                # Resume must run the reviewers again, not this step alone.
                state.completed_stages.remove("review")
                state.save(self._workspace)
            raise StepFailedError(
                PaperStatus.FAILED,
                "The revision step found no reviewer scores (no review file holds a score). "
                "`e2er resume` runs the review step again.",
                "revision",
            )

        result = aggregate_reviews(scores)
        logger.info("Internal quality review: %.2f of 10 (%s)", result.weighted_avg, result.rule_triggered)
        self._write_review_aggregation(result)

        if result.verdict in {"ACCEPT", "MINOR_REVISION"}:
            await self._update_status(PaperStatus.COMPLETED)
            return PaperStatus.COMPLETED

        # Deep revision: MECHANISM_FAIL means the referees rejected the paper's
        # RESEARCH (the mechanism isn't computed/convincing), which patch_revisor
        # — a prose editor — cannot fix (it can't recompute an out-of-sample test
        # or re-source a dataset). Re-do the analysis + writing against the
        # referee findings, re-review, and re-decide. Bounded by
        # _MAX_DEEP_REVISIONS. (MAJOR_REVISION stays on the lighter prose-patch
        # path below; HARD_REJECT is unsalvageable and never loops.)
        if result.verdict == "MECHANISM_FAIL" and self._deep_revision_count < _MAX_DEEP_REVISIONS:
            self._deep_revision_count += 1
            logger.info(
                "Deep revision round %d/%d for paper %s — re-dispatching research specialists on the referee findings",
                self._deep_revision_count,
                _MAX_DEEP_REVISIONS,
                self._paper_id,
            )
            await self._run_deep_revision_round()
            # Re-run the full review machinery (re-render + gates + reviewers)
            # on the revised research, then re-decide from the fresh scores.
            review_status = await self._run_review_phase()
            if review_status != PaperStatus.REVIEW:
                # A gate rejected the re-analyzed draft (e.g. verify_numbers
                # critical after re-estimation) — terminal this round.
                return review_status
            return await self._run_revision_phase(current_status)

        # MAJOR_REVISION → the existing light prose patch (unchanged).
        if result.verdict == "MAJOR_REVISION":
            return await self._run_patch_revision(scores)

        # A score with no revision round left to run (HARD_REJECT, or a
        # MECHANISM_FAIL the deep round could not lift). The internal quality
        # review gives a score and nothing else: the run has done its steps,
        # so it is COMPLETED, and the score stays in review_aggregation.json.
        # (Up to 0.13.1 this was REJECTED, which read as a peer-review
        # decision; run_outcome.effective_status reads those runs as completed.)
        logger.warning(
            "Paper %s: internal quality review %.2f of 10 (%s); no revision round left",
            self._paper_id,
            result.weighted_avg,
            result.rule_triggered,
        )
        await self._update_status(PaperStatus.COMPLETED)
        return PaperStatus.COMPLETED

    def _read_review_scores(self) -> list:
        """Parse each reviewer's score from its file on disk (canonical), with
        the in-memory chat summary as a fallback for a reviewer whose file is
        absent. Returns the list of parsed scores (possibly empty)."""
        scores = []
        seen = set()
        for reviewer in REVIEWER_SPECIALISTS:
            artifact = SPECIALIST_ARTIFACTS.get(reviewer, "")
            if artifact:
                path = self._workspace / artifact
                if path.exists():
                    score = parse_review_output(reviewer, path.read_text(encoding="utf-8"))
                    if score:
                        scores.append(score)
                        seen.add(reviewer)
        for c in self._contributions:
            if c.specialist in REVIEWER_SPECIALISTS and c.specialist not in seen:
                score = parse_review_output(c.specialist, c.output)
                if score:
                    # Salvaged from the reply text because no file was written.
                    # The verdict still gets its score, but no review FILE
                    # exists — so _referee_feedback_text has nothing to hand the
                    # revision round, and the bundle ships without the report.
                    score.source = "transcript"
                    scores.append(score)
                    seen.add(c.specialist)
        return scores

    def _write_review_aggregation(self, result) -> None:
        # Panel composition travels WITH the verdict. A verdict computed on two
        # reviewers and one computed on six were previously indistinguishable in
        # this file — the shortfall existed only as a log warning, which no
        # reader of the artifact (or of the export bundle) ever sees.
        doc: dict[str, Any] = {
            # `verdict` is the internal code that picks the revision path
            # (review_aggregator.py). It is never shown; readers get the score.
            "verdict": result.verdict,
            "weighted_avg": result.weighted_avg,
            "rule_triggered": result.rule_triggered,
            "rationale": result.rationale,
            # Which time the reviewers scored this run's draft: 1, or 2 after a
            # deep revision round re-reviewed it.
            "round": self._deep_revision_count + 1,
        }
        # Omitted, not zeroed, when the scores aren't available: an absent panel
        # block means "not recorded", where `reported: 0` would assert that no
        # reviewer reported. Writing the verdict must never depend on this.
        scores = getattr(result, "scores", None)
        if scores is not None:
            reported = [s.reviewer for s in scores]
            salvaged = [s.reviewer for s in scores if getattr(s, "source", "file") != "file"]
            doc["panel"] = {
                "expected": len(REVIEWER_SPECIALISTS),
                "reported": len(reported),
                "complete": len(reported) == len(REVIEWER_SPECIALISTS),
                "missing": sorted(set(REVIEWER_SPECIALISTS) - set(reported)),
                # Scored from the reviewer's reply text because it never wrote
                # its file: the score counts, but no report exists for the
                # revision round or the bundle.
                "scored_without_a_review_file": sorted(salvaged),
                "scores": [
                    {
                        "reviewer": s.reviewer,
                        "score": s.score,
                        "recommendation": s.recommendation,
                        "weight": s.weight,
                        "source": getattr(s, "source", "file"),
                    }
                    for s in scores
                ],
            }
        (self._workspace / "review_aggregation.json").write_text(json.dumps(doc, indent=2))

    def _referee_feedback_text(self, max_chars: int = 15000) -> str:
        """Concatenate the reviewer reports from disk for the deep-revision
        prompt — the substantive findings the research must address."""
        parts: list[str] = []
        for reviewer in REVIEWER_SPECIALISTS:
            art = SPECIALIST_ARTIFACTS.get(reviewer, "")
            if not art:
                continue
            p = self._workspace / art
            if not p.is_file():
                continue
            try:
                txt = p.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if txt:
                parts.append(f"## {reviewer}\n{txt}")
        blob = "\n\n".join(parts)
        return blob[:max_chars]

    async def _run_deep_revision_round(self) -> None:
        """Re-do the RESEARCH (not just the prose) in response to the referees,
        then the writing. The caller re-reviews and re-decides.

        Re-dispatches data_analyst → econometrics_specialist (data dependency)
        with the referee reports as guidance, re-renders the deterministic
        tables from the revised JSON, then re-dispatches section_writer to bring
        the prose in line with the revised analysis.
        """
        from ..renderer.complete import render_all_or_halt
        from ..specialists.dispatcher import execute_work_order

        feedback = self._referee_feedback_text()
        research_focus = (
            "The reviewers' findings concern this paper's RESEARCH, not its wording. "
            "Address their findings by RE-DOING your work: recompute every "
            "required quantity and leave nothing null (e.g. out-of-sample R^2, "
            "test statistics), fix the data and specification problems they "
            "name, source the dataset the research question actually specifies, "
            "and apply the standard corrections they cite. Rewrite your "
            "script/output accordingly.\n\n=== Referee reports ===\n" + feedback
        )
        for spec in ("data_analyst", "econometrics_specialist"):
            order = WorkOrder(paper_id=self._paper_id, specialist=spec, focus=research_focus, context_tier=2)
            c = await execute_work_order(
                order,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
                self._governance,
            )
            self._contributions.append(c)

        # Tables follow the revised JSON; re-render before the writer edits
        # prose. Halts if the revised analysis still can't fill them — a hole
        # here is what the writer papers over with its own numbers.
        render_all_or_halt(self._workspace)

        writer_focus = (
            "Revise the paper to reflect the REVISED analysis (the updated "
            "estimation_results.json / summary_statistics.json) and to address "
            "the referee findings below. Report only what was actually computed "
            "— do not claim or imply results that are still missing.\n\n"
            "=== Referee reports ===\n" + feedback
        )
        order = WorkOrder(paper_id=self._paper_id, specialist="section_writer", focus=writer_focus, context_tier=2)
        c = await execute_work_order(
            order,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
        )
        self._contributions.append(c)

    # ── the number check (verify_numbers before the reviewers) ─────────────

    def _number_check_status_text(self, reasons: list[str]) -> str:
        """The paper's status line while the run waits at the number check."""
        tried = getattr(self, "_number_patch_outcome", "") or "it did not run"
        shown = "; ".join(reasons[:3]) + (f"; and {len(reasons) - 3} more" if len(reasons) > 3 else "")
        return (
            f"Stopped at the number check: {len(reasons)} number(s) in the paper's tables differ from the "
            f"results files, and the automatic correction did not fix them ({tried}). {shown[:1500]}. "
            f"Open the check with `e2er review {self._paper_id}`: edit the draft or a results file, give an "
            "instruction, send back paper_drafter, section_writer (table layout) or econometrics_specialist, "
            "or approve to continue with these mismatches recorded in the dossier as your decision. "
            "The reviewers run after that."
        )

    def _number_check_state(self) -> Any:
        state = getattr(self, "_state", None)
        if state is None or not isinstance(getattr(state, "metadata", None), dict):
            return None
        return state

    def _numbers_accepted(self, report: Any) -> bool:
        """True when the researcher approved continuing with exactly these mismatches (or a subset)."""
        from ..pipeline.researcher import mismatch_key

        state = self._number_check_state()
        if state is None or not report.critical_mismatches:
            return False
        accepted = set(state.metadata.get("numbers_accepted") or [])
        return bool(accepted) and all(mismatch_key(m) in accepted for m in report.critical_mismatches)

    async def _stop_at_number_check(self, report: Any) -> None:
        """Stop the run for the researcher at the number check (raises GateHaltError).

        The step names each mismatch (table cell, value in the table, value in
        the results, source key) and offers the draft and the results files.
        The researcher edits, instructs, sends back the drafter, the table
        layout (section_writer writes table_spec.json) or the estimation, or
        approves continuing with the mismatches recorded in the dossier.
        """
        from ..pipeline.researcher import NUMBERS_STEP, describe_mismatch, mismatch_record

        mismatches = [mismatch_record(m) for m in report.critical_mismatches]
        reasons = [describe_mismatch(m) for m in mismatches]
        sources = sorted({m["source_file"] for m in mismatches if m["source_file"]})
        files = [f for f in ["paper_draft.tex", *sources, "table_spec.json"] if f and (self._workspace / f).is_file()]
        state = self._number_check_state()
        if state is None:
            raise StepFailedError(
                PaperStatus.REJECTED, "Stopped by the number check: " + "; ".join(reasons[:5]), "review"
            )
        if NUMBERS_STEP in state.approved_stages:
            state.approved_stages.remove(NUMBERS_STEP)
        tried = getattr(self, "_number_patch_outcome", "")
        state.pending_review_stage = NUMBERS_STEP
        state.metadata["number_check"] = {"mismatches": mismatches, "auto_patch": tried}
        state.metadata["review"] = {"kind": "numbers", "files": files, "reasons": reasons}
        state.save(self._workspace)
        raise GateHaltError(NUMBERS_STEP, reasons)

    async def _settle_number_check(self, report: Any, *, enforced: bool, accepted: bool) -> None:
        """After the number check let the run go on: clear its stop, record why the run continues."""
        from ...db.events import log_event
        from ..pipeline.researcher import NUMBERS_STEP, mismatch_record

        state = self._number_check_state()
        if state is not None:
            if state.pending_review_stage == NUMBERS_STEP:
                state.pending_review_stage = None
            if (state.metadata.get("review") or {}).get("kind") == "numbers":
                state.metadata.pop("review", None)
            state.metadata.pop("number_check", None)
            state.save(self._workspace)
        note_path = self._workspace / "number_check.json"
        if not report.critical_mismatches:
            note_path.unlink(missing_ok=True)
            return
        mismatches = [mismatch_record(m) for m in report.critical_mismatches]
        regime = getattr(self, "_governance", DEFAULT_REGIME)
        if enforced and accepted:
            decision = "accepted_by_researcher"
            note = (
                f"The number check found {len(mismatches)} number(s) in the tables that differ from the results; "
                "the researcher approved continuing with them (recorded in the dossier)."
            )
        else:
            decision = "recorded_and_continued"
            note = (
                f"The number check found {len(mismatches)} number(s) in the tables that differ from the results. "
                f"Under governance '{regime}' this check does not stop the run: the mismatches are recorded "
                "in the dossier and the run continued."
            )
        logger.warning("Paper %s: %s", self._paper_id, note)
        doc = {"decision": decision, "governance": regime, "note": note, "mismatches": mismatches}
        note_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        await log_event(self._paper_id, "number_check_" + decision, stage="review", payload=doc)

    async def _verify_numbers_auto_patch(self, report):
        """Try to auto-patch verify_numbers critical mismatches before REJECT.

        v0.6 step 5. Closes the proactive detect → patch → re-detect
        loop that v0.5's defensive REJECT path left out. Bounded by
        `_VERIFY_NUMBERS_AUTO_PATCH_BUDGET` (default 1 attempt) so a
        drafter that consistently disagrees with the source JSON
        doesn't loop forever — it falls through to REJECTED and the
        operator intervenes.

        Args:
            report: the current VerificationReport with critical
                mismatches.

        Returns:
            A (possibly updated) VerificationReport. If the auto-patch
            succeeded, this report will have an empty
            `critical_mismatches` list and the caller proceeds to
            reviewers. If the patch failed (budget exhausted, missing
            patch file, residual criticals), the returned report
            still has criticals and the caller transitions to
            REJECTED with the original error surface.
        """
        from ..pipeline.verify_numbers import verify_and_save
        from .findings import collect_verify_numbers_findings

        budget = _VERIFY_NUMBERS_AUTO_PATCH_BUDGET
        if budget <= 0:
            logger.debug("verify_numbers auto-patch disabled by budget; the run stops at the check")
            return report

        # One attempt per set of mismatches: a resume after the researcher's
        # decision does not pay for the same correction again, but mismatches
        # that are new (say, after the drafter was sent back) get their attempt.
        from ..pipeline.researcher import mismatch_key

        self._number_patch_outcome = ""
        keys = {mismatch_key(m) for m in report.critical_mismatches}
        state = self._number_check_state()
        if state is not None:
            tried = set(state.metadata.get("numbers_patch_tried") or [])
            if keys <= tried:
                logger.info(
                    "verify_numbers: the automatic correction already ran for these %d mismatch(es); "
                    "the run stops at the check",
                    len(keys),
                )
                self._number_patch_outcome = "already tried for these mismatches"
                return report
            state.metadata["numbers_patch_tried"] = sorted(tried | keys)
            state.save(self._workspace)

        logger.info(
            "verify_numbers gate found %d critical mismatch(es) — attempting auto-patch (budget=%d)",
            len(report.critical_mismatches),
            budget,
        )

        findings = collect_verify_numbers_findings(report)
        if not findings:
            # All mismatches were below the findings severity_floor.
            # collect_verify_numbers_findings drops minor mismatches by
            # default; if we land here with critical_mismatches but
            # zero findings, something has gone wrong with the floor
            # configuration. Fall through to REJECTED rather than
            # dispatching a useless patch_revisor.
            logger.warning(
                "verify_numbers has critical mismatches but no Findings emitted "
                "— skipping auto-patch and the run stops at the check"
            )
            return report

        try:
            merge_result = await self._dispatch_patch_revisor(findings)
        except FileNotFoundError as e:
            logger.warning(
                "verify_numbers auto-patch: patch_revisor produced no patch file (%s) — the run stops at the check",
                e,
            )
            self._number_patch_outcome = "patch_revisor wrote no patch file"
            return report

        if not merge_result.fully_applied:
            logger.warning(
                "verify_numbers auto-patch: %d edits applied, %d failed — the run stops at the check",
                merge_result.n_applied,
                merge_result.n_failed,
            )
            # Don't return early — even a partial patch may have
            # cleared some mismatches. Re-run verify_numbers below
            # to find out, then the outer caller decides.

        # Re-run verify_numbers on the patched draft.
        draft_path = self._workspace / "paper_draft.tex"
        new_report = verify_and_save(draft_path, self._workspace)
        if new_report.critical_mismatches:
            logger.warning(
                "verify_numbers auto-patch: %d critical mismatch(es) remain after patch",
                len(new_report.critical_mismatches),
            )
            self._number_patch_outcome = (
                f"patch_revisor applied {merge_result.n_applied} edit(s); "
                f"{len(new_report.critical_mismatches)} mismatch(es) remain"
                if merge_result.n_applied
                else "patch_revisor made no edits"
            )
        else:
            logger.info(
                "verify_numbers auto-patch: all critical mismatches resolved (%d edits applied)",
                merge_result.n_applied,
            )
        return new_report

    async def _dispatch_patch_revisor(self, findings: list) -> Any:
        """Dispatch patch_revisor with a findings list, then apply the merger.

        Shared helper used by both `_run_patch_revision` (MAJOR_REVISION
        path) and `_run_self_attack_phase` (critical-findings path).
        Caller is responsible for the status transition based on the
        returned MergeResult.

        Args:
            findings: list of `Finding` objects scoped to this call.
                The merger uses these to enforce scope — any edit
                whose target isn't in this list is rejected.

        Returns:
            `MergeResult` describing applied + failed edits and the
            unified diff side artifact.

        Raises:
            FileNotFoundError: when patch_revisor's LLM call completed
                but no `paper_draft.tex.edits.json` was written to the
                workspace (caller decides whether this is REJECTED or
                logged-and-continue).
        """
        import json

        from ..specialists.dispatcher import run_with_attempts
        from .patch_merger import merge_patch_file

        # Serialise findings into the work order's focus so the
        # patch_revisor can read them without an extra file load.
        findings_json = json.dumps(
            [
                {
                    "source": f.source,
                    "source_detail": f.source_detail,
                    "target": f.target,
                    "severity": f.severity,
                    "problem": f.problem,
                    "suggested_fix": f.suggested_fix,
                }
                for f in findings
            ],
            indent=2,
        )
        focus = (
            "Emit a patch file (`paper_draft.tex.edits.json`) that "
            "addresses the findings below. See your "
            "`writing/scoped-revision` skill for the patch file shape.\n\n"
            f"FINDINGS ({len(findings)} items, severity-sorted):\n"
            f"```json\n{findings_json}\n```"
        )

        revision_order = WorkOrder(
            paper_id=self._paper_id,
            specialist="patch_revisor",
            focus=focus,
            context_tier=2,
        )
        # A patch file that fails its contract (not written, not JSON) gets the
        # dispatcher's attempts with the violation fed back; a crash does not.
        # After the last attempt the caller decides (the number check stops for
        # the researcher; the revision step fails) — no separate contract stop.
        contribution = await run_with_attempts(
            revision_order,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
            retry_crashes=False,
        )
        self._contributions.append(contribution)

        return merge_patch_file(self._workspace, findings)

    async def _resolve_table_spec(self) -> None:
        """Render results tables and close the loop on cross-specialist key
        drift.

        The renderer auto-resolves order-insensitive key drift
        (``dp_full`` ≡ ``full_dp``). Anything still unresolved is a genuinely
        wrong/abbreviated/missing reference (e.g. the drafter wrote ``cw_stat``
        where the JSON has ``clark_west_stat``) that leaves those cells ``---``.
        Rather than ship a paper with blank cells, dispatch ``section_writer``
        with the unresolved references and the real available keys, then
        re-render. Deterministic normalization already covers the common case;
        this handles the long tail.

        Repair iterates up to ``_MAX_TABLE_SPEC_REPAIRS`` times because one pass
        empirically fixes most but not all of a bad spec, and stops the moment a
        pass stops reducing the unresolved count — an ambiguous reference does
        not get less ambiguous on the second ask.
        """
        from ..renderer.complete import render_all
        from ..renderer.tables import render_tables

        report = render_tables(self._workspace)
        render_all(self._workspace)  # no halt yet — the repair attempts below are the point
        if not report.unresolved:
            return

        from ..specialists.dispatcher import execute_work_order

        remaining = len(report.unresolved)
        for attempt in range(1, _MAX_TABLE_SPEC_REPAIRS + 1):
            feedback = self._build_table_spec_feedback(report.unresolved)
            if feedback is None:
                # No estimation JSON to reconcile against — nothing actionable.
                return

            logger.info(
                "table_spec: %d unresolved reference(s) after normalization — dispatching "
                "section_writer to correct table_spec.json (attempt %d/%d)",
                remaining,
                attempt,
                _MAX_TABLE_SPEC_REPAIRS,
            )
            order = WorkOrder(
                paper_id=self._paper_id,
                specialist="section_writer",
                focus=feedback,
                context_tier=2,
            )
            contribution = await execute_work_order(
                order,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
                self._governance,
            )
            self._contributions.append(contribution)

            report = render_tables(self._workspace)
            if not report.unresolved:
                logger.info("table_spec: all references resolved after %d repair attempt(s)", attempt)
                break
            if len(report.unresolved) >= remaining:
                logger.info(
                    "table_spec: repair stalled at %d unresolved reference(s) on attempt %d — "
                    "another pass would repeat it",
                    len(report.unresolved),
                    attempt,
                )
                break
            remaining = len(report.unresolved)

        # Re-render for real. Anything still unresolved halts: shipping `---`
        # cells is what invited the drafter to write its own tables over them.
        from ..renderer.complete import render_all_or_halt

        render_all_or_halt(self._workspace)

    def _build_table_spec_feedback(self, unresolved: list) -> str | None:
        """Compose a directive for section_writer to fix table_spec.json,
        listing the unresolved references and the EXACT fields available WITHIN
        EACH spec object. Returns None when there's no JSON to reconcile.

        The inventory is grouped by spec key rather than flattened into one
        list, because a flat list invites the very error it is meant to prevent.
        The 2026-08-20 canary asked for ``pct_change`` in a ``bootstrap`` column
        when the field exists only under ``main`` — a plausible move for a
        drafter told those field names were "available" without being told
        where. A stat resolves only within its own column's spec object;
        borrowing across columns would print one specification's number under
        another specification's heading, which is the fabrication this whole
        module exists to prevent.
        """
        import json

        from ..renderer.tables import _nested_paths, _scalar_at

        merged: dict[str, Any] = {}
        for fn in ("estimation_results.json", "robustness_results.json"):
            fp = self._workspace / fn
            if not fp.is_file():
                continue
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict):
                merged.update(data)

        spec_keys = sorted(k for k in merged if not k.startswith("_"))
        if not spec_keys:
            return None

        blocks: list[str] = []
        for key in spec_keys:
            spec = merged[key]
            if not isinstance(spec, dict):
                continue
            fields: set[str] = set()
            for ck in ("diagnostics", "forecast_evaluation"):
                c = spec.get(ck)
                if isinstance(c, dict):
                    fields.update(k for k, v in c.items() if not isinstance(v, dict | list))
            fields.update(k for k, v in spec.items() if not isinstance(v, dict | list))
            # Nested scalars are reachable too, under their path with dots
            # flattened to underscores — that is the form the renderer's
            # token-subset descent matches.
            for path, node in _nested_paths(spec).items():
                if "." not in path:
                    continue
                head = path.partition(".")[0]
                if path.count(".") == 1 and head in ("diagnostics", "forecast_evaluation"):
                    continue  # already listed above under its bare name
                if _scalar_at(path, node)[1]:
                    fields.add(path.replace(".", "_"))
            cf = spec.get("coefficients")
            coeffs = sorted(cf) if isinstance(cf, dict) else []
            blocks.append(f"  {key}:\n    stat `field`: {sorted(fields)}\n    coefficient `var`: {coeffs}")

        unresolved_lines = sorted(
            {f"  - {u.kind} {u.ref!r}" + (f" in column {u.column!r}" if u.column else "") for u in unresolved}
        )
        return (
            "Your `table_spec.json` references keys that do not exist in the "
            "estimation JSON, so those table cells rendered blank (`---`). "
            "Rewrite `table_spec.json` so that EVERY `spec_key`, coefficient "
            "`var`, and stat `field` is an EXACT name from the inventory below. "
            "Do not invent or abbreviate names; copy them verbatim. Keep the "
            "same table structure; only correct the keys.\n\n"
            "Two rules the inventory encodes:\n"
            "  1. A stat `field` resolves ONLY inside its own column's spec "
            "object. If a field is listed under one spec key and not another, a "
            "column on that other spec key CANNOT use it — drop the row, or drop "
            "that column from the row. Never borrow a number across columns.\n"
            "  2. Ambiguous names do not resolve. If you want `ar1` and the "
            "inventory offers `ar1_pre` and `ar1_post`, name the one you mean.\n\n"
            "Unresolved references to fix:\n" + "\n".join(unresolved_lines) + "\n\n"
            "Available references, by spec key:\n" + "\n".join(blocks) + "\n\n"
            "Output the corrected `table_spec.json` (and only that file).\n"
        )

    def _collect_revision_findings(self, scores: list) -> list:
        """Build the findings list for the MAJOR_REVISION patch_revisor call.

        Combines review-score findings (always present at the
        revision phase) with verify_numbers findings if the gate
        emitted a report. Sorted severity-desc with source priority
        (verify_numbers > self_attack > review).
        """
        import json

        from ..pipeline.verify_numbers import Mismatch, VerificationReport
        from .findings import (
            Finding,
            collect_review_findings,
            collect_verify_numbers_findings,
            combine_findings,
        )

        review_findings = collect_review_findings(scores)
        verify_findings: list[Finding] = []
        verify_path = self._workspace / "number_verification.json"
        if verify_path.is_file():
            try:
                data = json.loads(verify_path.read_text(encoding="utf-8"))
                # VerificationReport carries Mismatch dataclasses;
                # rebuild from the persisted dict shape produced by
                # `VerificationReport.to_dict()`.
                report = VerificationReport()
                report.passed = bool(data.get("passed", True))
                report.mismatches = []
                for m in data.get("mismatches", []):
                    report.mismatches.append(
                        Mismatch(
                            draft_value=m.get("draft_value", ""),
                            source_key=m.get("source_key", ""),
                            source_value=m.get("source_value", ""),
                            table_context=m.get("table_context", ""),
                            severity=m.get("severity", "minor"),
                        )
                    )
                verify_findings = collect_verify_numbers_findings(report)
            except (OSError, json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    "could not parse number_verification.json for paper %s: %s",
                    self._paper_id,
                    e,
                )

        return combine_findings(review_findings, verify_findings)

    async def _run_patch_revision(self, scores: list) -> PaperStatus:
        """MAJOR_REVISION path: collect findings, dispatch patch_revisor, apply.

        v0.6 step 3: replaces the pre-v0.6 single-revisor full-rewrite
        path. Caller is `_run_revision_phase` after the aggregator
        emits `MAJOR_REVISION`.

        Outcomes:
            COMPLETED — patch file applied without failures, OR
                       no actionable findings (skipped dispatch), OR
                       patch_revisor (legitimately) emitted an empty
                       patch because findings were unactionable.
                       Also when no edit could be applied: the
                       revision round ran and changed nothing.
            FAILED    — patch_revisor produced no patch file at all
                       (resumable).
        """
        await self._update_status(PaperStatus.REVISION)

        findings = self._collect_revision_findings(scores)
        if not findings:
            # The aggregator said MAJOR_REVISION but no individual
            # reviewer's score crossed the Finding floor and there
            # were no verify_numbers mismatches. The patch_revisor
            # wouldn't have anything to act on; transition straight
            # to COMPLETED with a warning so the operator can review.
            logger.warning(
                "Paper %s: revision round with no actionable findings — skipping patch_revisor and marking COMPLETED",
                self._paper_id,
            )
            await self._update_status(PaperStatus.COMPLETED)
            return PaperStatus.COMPLETED

        try:
            merge_result = await self._dispatch_patch_revisor(findings)
        except FileNotFoundError as e:
            # The revision step did not produce its output: a failed step, not
            # a score. FAILED is resumable.
            raise StepFailedError(
                PaperStatus.FAILED,
                f"The revision step failed: patch_revisor wrote no patch file ({e}). "
                "`e2er resume` runs the revision step again.",
                "revision",
            ) from e

        # Partial application is progress, not failure. Edits the merger
        # dropped — out-of-scope (its scope-enforcement job, e.g. an
        # over-reaching `paper:full` edit when findings are section-scoped) or
        # unmatchable (stale `find` text) — are logged but NOT fatal. Rejecting
        # a near-complete paper that the in-scope edits already revised throws
        # away good work; this mirrors the self-attack path's tolerance.
        # REJECT only when the patch achieved nothing (no edit applied).
        if merge_result.n_applied > 0:
            if merge_result.failed:
                dropped = "; ".join(f"[{r.edit.target}] {r.error}" for r in merge_result.failed[:3])
                logger.warning(
                    "Paper %s: applied %d edit(s); dropped %d (non-fatal): %s",
                    self._paper_id,
                    merge_result.n_applied,
                    merge_result.n_failed,
                    dropped,
                )
            else:
                logger.info(
                    "Paper %s: applied %d edits, draft patched + diff written",
                    self._paper_id,
                    merge_result.n_applied,
                )
            await self._update_status(PaperStatus.COMPLETED)
            return PaperStatus.COMPLETED

        # Nothing applied (every edit was out-of-scope or unmatchable, or the
        # revisor proposed none). The revision round ran and changed nothing:
        # the draft stays as the reviewers scored it, and the run is COMPLETED.
        # The merge report (paper_draft.tex.edits.json and the log) says why.
        first_failures = "; ".join(f"[{r.edit.target}] {r.error}" for r in merge_result.failed[:3])
        logger.warning(
            "Paper %s: revision round applied no edits (%d failed)%s",
            self._paper_id,
            merge_result.n_failed,
            f". First failures: {first_failures}" if first_failures else "",
        )
        from ...db.events import log_event

        # Recorded as an event, so the dossier says the revision changed nothing and why.
        await log_event(
            self._paper_id,
            "revision_not_applied",
            stage="revision",
            payload={"edits_failed": merge_result.n_failed, "first_failures": first_failures},
        )
        await self._update_status(PaperStatus.COMPLETED)
        return PaperStatus.COMPLETED

    async def _dispatch(self, decision: StrategistDecision) -> list[Contribution]:
        if not decision.work_orders:
            return []

        # v0.6 step 6 + v0.6.1: iterative-phase guard against
        # whole-draft rewrites. Both `paper_drafter` and (v0.6.1)
        # `revisor` write to `paper_draft.tex` from scratch every
        # time, causing drift in sections reviewers already approved.
        # The strategist's prompt instructs it to use `section_writer`
        # (or `patch_revisor` via the runner's revision-phase wiring)
        # on iterations 2+; this is the load-bearing hard check that
        # catches the strategist if it ignores the instruction.
        # iteration 0 = initial phase, iteration 1 = first iterative
        # pass (both legitimate full-draft calls), iteration >= 2 =
        # forbidden territory for both specialists.
        #
        # Surfaced by the v0.6.0 live run (paper 3bc58e8d): the
        # strategist dispatched the legacy `revisor` during iterative
        # phase even though `paper_drafter` was correctly skipped.
        # v0.6.0's guard only filtered `paper_drafter`; v0.6.1 closes
        # the same drift door for `revisor`.
        if self._iteration >= 2:
            forbidden_full_rewriters = {"paper_drafter", "revisor"}
            kept: list = []
            dropped: list[tuple[str, str]] = []
            for wo in decision.work_orders:
                if wo.specialist in forbidden_full_rewriters:
                    dropped.append((wo.specialist, wo.focus[:80] if wo.focus else "(no focus)"))
                else:
                    kept.append(wo)
            if dropped:
                logger.warning(
                    "Iterative-phase guard: dropped %d full-draft work "
                    "order(s) on iteration %d. The strategist should dispatch "
                    "section_writer (or patch_revisor via the revision phase) "
                    "instead; full rewrites after iteration 1 cause drift. "
                    "Dropped: %s",
                    len(dropped),
                    self._iteration,
                    "; ".join(f"{spec}({focus!r})" for spec, focus in dropped),
                )
                decision = decision.model_copy(update={"work_orders": kept})
                # If the guard dropped EVERY work order, return early —
                # nothing left to dispatch.
                if not kept:
                    return []

        # Circuit breaker: refuse to re-dispatch a non-tolerant specialist
        # that has already failed _MAX_SPECIALIST_ATTEMPTS times in a row.
        # Without this check, the strategist's revision logic re-dispatches
        # forever (the run #14 failure mode). Tolerant specialists
        # (reviewers + polish) are exempt — they can fail without blocking
        # downstream work.
        tolerant = set(REVIEWER_SPECIALISTS) | set(POLISH_SPECIALISTS)
        for wo in decision.work_orders:
            spec = wo.specialist
            if spec in tolerant:
                continue
            attempts = self._failure_counts.get(spec, 0)
            if attempts >= _MAX_SPECIALIST_ATTEMPTS:
                last_err = self._last_specialist_errors.get(spec)
                logger.error(
                    "Circuit breaker tripped: %s failed %d times in a row for paper %s",
                    spec,
                    attempts,
                    self._paper_id,
                )
                raise CircuitBreakerError(specialist=spec, attempts=attempts, last_error=last_err)

        # Convert strategist.actions.WorkOrder → specialists.contracts.WorkOrder
        # (strategist work orders carry parallel_group/context_tier but not paper_id)
        contract_orders = self._to_contract_orders(decision.work_orders)
        return await self._execute_orders(contract_orders)

    def _order_for_researcher_steps(self, orders: list[WorkOrder]) -> list[WorkOrder]:
        """Move work orders behind the specialists an open researcher step waits for.

        The strategist chooses the groups; a pre-registration only means
        something if nothing else — estimation above all — runs before the
        researcher has seen the design. So while such a step is open, every
        order not named in its `after` list is placed after the last group
        that contains one that is (all of them shift alike).
        """
        state = getattr(self, "_state", None)
        if not getattr(self, "_in_initial", False) or state is None:
            return orders
        open_steps = [
            t
            for t in getattr(self, "_triggers", [])
            if t.applies_to(self._mode)
            and not (state.is_complete(t.name) if t.kind == "gate" else state.is_approved(t.name))
        ]
        if not open_steps:
            return orders
        waited = set().union(*(set(t.after) for t in open_steps))
        groups = [o.parallel_group for o in orders if o.specialist in waited]
        if not groups:
            return orders
        last = max(groups)
        # Every other order moves by the same amount, so their order among
        # themselves (estimation before drafting) is kept.
        return [
            o if o.specialist in waited else o.model_copy(update={"parallel_group": o.parallel_group + last + 1})
            for o in orders
        ]

    async def _execute_orders(self, contract_orders: list[WorkOrder]) -> list[Contribution]:
        """Run work orders (one alone, or grouped), stopping at researcher steps between groups."""
        contract_orders = self._order_for_researcher_steps(contract_orders)
        state = getattr(self, "_state", None)
        if getattr(self, "_in_initial", False) and state is not None and _estimation_next(contract_orders):
            # The first group would estimate: an open design check runs first.
            await self._run_open_gates(state, contract_orders)
        if len(contract_orders) == 1:
            from ..specialists.dispatcher import (
                execute_work_order,
                guard_artifacts,
                raise_contract_failure,
                run_with_attempts,
            )

            args = (
                contract_orders[0],
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
                self._governance,
            )
            if contract_orders[0].specialist in (set(REVIEWER_SPECIALISTS) | set(POLISH_SPECIALISTS)):
                c = await execute_work_order(*args)
            else:
                # Output that fails its contract gets the same attempts as in a
                # parallel batch, the violation fed back each time; a crash is not
                # retried here (the strategist and the circuit breaker handle it).
                c = await run_with_attempts(*args, retry_crashes=False)
            contributions = [c]
            # After the last attempt: a stop for the researcher (ContractFailureError).
            raise_contract_failure(contract_orders, contributions)
            # Same cascade guard execute_parallel applies — a lone non-tolerant
            # specialist that "succeeded" without its canonical artifact must
            # halt here, not starve downstream specialists (unless the regime
            # shadows it, in which case the verdict is logged and the run goes on).
            await guard_artifacts(contributions, self._workspace, self._governance)
            self._update_failure_counts(contributions)
            await self._between_groups({x.specialist for x in contributions if x.success}, [])
            return contributions
        contributions = await execute_with_dependencies(
            contract_orders,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
            between_groups=self._between_groups if getattr(self, "_triggers", None) else None,
        )
        self._update_failure_counts(contributions)
        return contributions

    def _update_failure_counts(self, contributions: list[Contribution]) -> None:
        """Update per-specialist failure counters after a dispatch.

        - Success → reset to 0 (the specialist recovered, don't punish past
          attempts).
        - Failure on non-tolerant specialist → increment + record last error.
        - Tolerant specialists (reviewers, polish) are not tracked because
          their failure is non-blocking and shouldn't trip the breaker.
        """
        tolerant = set(REVIEWER_SPECIALISTS) | set(POLISH_SPECIALISTS)
        for c in contributions:
            if c.specialist in tolerant:
                continue
            if c.success:
                self._failure_counts.pop(c.specialist, None)
                self._last_specialist_errors.pop(c.specialist, None)
            else:
                self._failure_counts[c.specialist] = self._failure_counts.get(c.specialist, 0) + 1
                if c.error:
                    self._last_specialist_errors[c.specialist] = c.error

    def _to_contract_orders(self, strategist_orders: list) -> list[WorkOrder]:
        """Adapt strategist.actions.WorkOrder → specialists.contracts.WorkOrder."""
        result = []
        for wo in strategist_orders:
            result.append(
                WorkOrder(
                    paper_id=self._paper_id,
                    specialist=wo.specialist,
                    focus=wo.focus,
                    parallel_group=getattr(wo, "parallel_group", 0),
                    context_tier=getattr(wo, "context_tier", 1),
                )
            )
        return result

    async def _run_replication_phase(self) -> None:
        """Export audit trail and run replication_packager specialist.

        Skipped for `methodology=theoretical` papers — there's no data to
        package. Pre-v0.5 this ran wastefully on every paper (~$0.43 on
        the theory live test paper cbe8048f).
        """
        if self._methodology == "theoretical":
            logger.info(
                "Skipping replication phase for paper %s (methodology=theoretical)",
                self._paper_id,
            )
            return
        logger.info("Running replication phase for paper %s", self._paper_id)
        replication_dir = self._workspace / "replication"
        replication_dir.mkdir(exist_ok=True)

        try:
            from ...modules.data.audit import write_audit_csv, write_data_queries_sql

            await write_audit_csv(self._paper_id, replication_dir / "audit_log.csv")
            await write_data_queries_sql(self._paper_id, replication_dir / "data_queries.sql")
        except Exception as e:
            logger.warning("Could not export audit log: %s", e)

        order = WorkOrder(
            paper_id=self._paper_id,
            specialist="replication_packager",
            focus=(
                "Write a complete, self-contained estimation script at replication/estimation.py. "
                "Include: data loading, all estimation steps, and output of tables and figures to "
                "replication/output/. Read the econometric specification from econometric_spec.md "
                "and the data summary from data_summary.md. "
                "Also write replication/README.md documenting how to reproduce the results."
            ),
            context_tier=2,
        )
        from ..specialists.dispatcher import execute_work_order

        contribution = await execute_work_order(
            order,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
            self._governance,
        )
        self._contributions.append(contribution)

    async def _run_compile_phase(self) -> None:
        """Compile paper_draft.tex to PDF. Non-fatal — PDF is a bonus output."""
        try:
            # Re-render tables from the current spec + sidecars (a revision may
            # have changed either), then backfill stubs for any dangling
            # \input so a missing table can't abort the whole compile.
            from ..renderer.compiler import compile_latex
            from ..renderer.complete import render_all

            # Best-effort by design: this runs in `_best_effort_finalize`, where
            # the point is to get *something* compiled out of a run that may
            # already have failed. Stubs are appropriate here and only here.
            render_all(self._workspace)
            pdf = await compile_latex(self._workspace)
            if pdf:
                logger.info("Compiled PDF: %s", pdf)
            else:
                logger.debug("LaTeX compilation skipped (no compiler or no .tex)")
        except Exception as e:
            logger.warning("LaTeX compilation failed: %s", e)

    async def _run_github_push_phase(self) -> None:
        """Push LaTeX artifacts to GitHub. Non-fatal — skipped when token not configured."""
        try:
            from ...modules.github.push import push_latex_draft

            result = await push_latex_draft(self._paper_id, self._workspace, "completion")
            if result:
                logger.info(
                    "GitHub push: %d files to %s",
                    result.get("pushed_files", 0),
                    result.get("repo", ""),
                )
        except Exception as e:
            logger.warning("GitHub push failed: %s", e)

    async def _update_status(self, status: PaperStatus, error: str | None = None) -> None:
        if status in (PaperStatus.FAILED, PaperStatus.REJECTED) and not (error or "").strip():
            # A run that ends must say why (tests/test_number_check.py pins it):
            # never a failed run with an empty last_error.
            logger.warning("Paper %s set to %s without a reason", self._paper_id, status.value)
            where = getattr(self, "_current_step", None) or "?"
            error = f"The run ended as {status.value} at step '{where}' without a recorded reason; see the server log."
        try:
            from ...db.client import execute

            # Statuses that should preserve the error/reason message on the row
            # so the dashboard can render the why behind the halt without
            # parsing the events table. v0.5 adds PAUSED and REJECTED here:
            # both carry actionable operator information (budget breakdown,
            # circuit-breaker specialist, review-gate rationale) that pre-v0.5
            # was silently dropped at the SQL layer.
            preserve_error = (
                status
                in {
                    PaperStatus.FAILED,
                    PaperStatus.CANCELLED,
                    PaperStatus.PAUSED,
                    PaperStatus.REJECTED,
                }
                and error is not None
            )
            if preserve_error:
                await execute(
                    "UPDATE papers SET status = %(s)s, last_error = %(e)s, updated_at = NOW() WHERE id = %(id)s",
                    {"s": status.value, "e": error, "id": self._paper_id},
                )
            else:
                # Non-terminal transitions (or terminal without an error message) clear
                # stale errors from prior runs.
                await execute(
                    "UPDATE papers SET status = %(s)s, last_error = NULL, updated_at = NOW() WHERE id = %(id)s",
                    {"s": status.value, "id": self._paper_id},
                )
        except Exception as e:
            logger.debug("Status update skipped (no DB?): %s", e)


#: Files a researcher sees when a sequence check halts (what to inspect or fix).
_SEQUENCE_CHECK_FILES: dict[str, tuple[str, ...]] = {
    "package_integrity": ("package_manifest.json",),
    "sandbox": ("replication_plan.json", "sandbox_log.json"),
    "reproduction": ("reproduction_report.json", "reproduction_check.json"),
}


def _reproduction_with_disclaimer(check: Any) -> Any:
    """The reproduction check; in a demonstration study (E2ER_PURPOSE) it also puts the
    replication disclaimer at the top of reproduction_report.md, which the researcher reads next."""

    def run(workspace: Path, **settings: Any) -> Any:
        verdict = check(workspace, **settings)
        from ..demonstration import mark_report, study_purpose

        try:
            purpose = study_purpose(Path(workspace))
        except ValueError as e:
            logger.warning("reproduction report left unmarked: %s", e)
            return verdict
        if purpose:
            mark_report(Path(workspace) / "reproduction_report.md", "replication")
        return verdict

    return run


def _sequence_check(check: str) -> Any:
    """The function behind a check that runs as a step: (workspace, **settings) -> verdict."""
    if check == "package_integrity":
        from ..pipeline.replication import fetch_package

        return fetch_package
    if check == "sandbox":
        from ..pipeline.sandbox import run_sandbox

        return run_sandbox
    if check == "reproduction":
        from ..pipeline.reproduction import check_reproduction

        return _reproduction_with_disclaimer(check_reproduction)
    raise ValueError(f"check {check!r} cannot run as a step of its own")


def _estimation_next(orders: list[WorkOrder]) -> bool:
    """True iff the next group of ``orders`` to run contains the estimation specialist."""
    if not orders:
        return False
    first = min(o.parallel_group for o in orders)
    return any(o.specialist == _ESTIMATION_SPECIALIST and o.parallel_group == first for o in orders)


def _select_polish_specialists(attack_report_path: Path) -> list[str]:
    """Select which polish specialists to run based on self-attack findings."""
    if not attack_report_path.exists():
        return list(POLISH_SPECIALISTS)  # run all if no report

    try:
        report = json.loads(attack_report_path.read_text())
        findings = report.get("findings", [])
        categories = {f.get("category", "") for f in findings}

        active = []
        category_to_polish = {
            "equilibrium": "polish_equilibria",
            "numerics": "polish_numerics",
            "institutions": "polish_institutions",
            "bibliography": "polish_bibliography",
        }
        for cat, specialist in category_to_polish.items():
            if cat in categories:
                active.append(specialist)
        # Always run formula polish
        if "polish_formula" not in active:
            active.append("polish_formula")
        return active
    except Exception:
        return list(POLISH_SPECIALISTS)
