"""Pipeline runner — orchestrates the full paper pipeline with V3 extensions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, ToolHandler
from ..specialists.contracts import Contribution, WorkOrder
from ..specialists.dispatcher import execute_parallel, execute_with_dependencies
from ..specialists.registry import POLISH_SPECIALISTS, REVIEWER_SPECIALISTS, SPECIALIST_ARTIFACTS
from ..strategist.actions import StrategistDecision
from ..strategist.engine import StrategistEngine
from ..strategist.review_aggregator import aggregate_reviews, parse_review_output
from ..strategist.state import CircuitBreakerError, PaperStatus

logger = get_logger(__name__)

_MAX_ITERATIONS = 6
_MAX_PIVOTS = 1
# Maximum consecutive failures for a single non-tolerant specialist before
# the circuit breaker halts the run. Set from runs #14 / #18 experience:
# - data_analyst failed 3 times in a row when Allium was unrecoverable
# - retrying past the third attempt never recovered the data layer
# 3 is the cheapest threshold that doesn't false-trip on transient errors
# (one bad attempt + one retry + one confirmation that it's not transient).
_MAX_SPECIALIST_ATTEMPTS = 3


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
    ) -> None:
        self._paper_id = paper_id
        self._workspace = workspace
        self._backend = backend
        self._model = model
        self._mode = mode
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

    def _in_memory_spent(self) -> float:
        """Sum of all specialist contribution costs + strategist usage cost.

        Used as a fallback when the llm_usage DB table is unavailable so the
        cost cap still trips. Authoritative on whichever side is larger.
        """
        from ...modules.tracking.costs import compute_cost

        spec_cost = sum(c.cost_usd or 0.0 for c in self._contributions)
        strat_cost = float(compute_cost(self._model, self._strategist.total_usage))
        return spec_cost + strat_cost

    async def run(self) -> dict[str, Any]:
        """Run the full pipeline from idea to completion, with checkpoint/resume support."""
        from ...db.events import log_event
        from ...modules.tracking.usage import check_budget
        from ..pipeline.state import PipelineState

        # Initialise outside try/except so the except branch can reference state
        # if setup itself fails. Without this, a crash in load() or _update_status()
        # propagates silently from the background task with no event log.
        state: PipelineState | None = None
        try:
            state = PipelineState.load(self._workspace, self._paper_id, self._mode)
            self._iteration = state.iteration
            self._pivot_count = state.pivot_count
            prior_contributions = state.contributions_count

            status = PaperStatus.DESIGNING
            await self._update_status(status)
        except Exception as e:
            logger.error("Pipeline setup failed for paper %s: %s", self._paper_id, e)
            await log_event(self._paper_id, "failed", payload={"error": f"setup: {type(e).__name__}: {e}"})
            await self._update_status(PaperStatus.FAILED, error=f"setup error: {e}")
            return {"status": "failed", "error": f"setup: {type(e).__name__}: {e}"}

        async def _phase(name: str, fn) -> Any:
            """Run a phase with budget check, event logging, and state persistence."""
            await check_budget(self._paper_id, self._max_cost_usd, self._in_memory_spent())
            await log_event(self._paper_id, "phase_start", stage=name)
            result = await fn()
            await log_event(self._paper_id, "phase_end", stage=name)
            return result

        try:
            if not state.is_complete("initial"):
                await _phase("initial", self._run_initial_phase)
                state.contributions_count = prior_contributions + len(self._contributions)
                state.mark_complete("initial")
                state.save(self._workspace)
            status = PaperStatus.IN_PROGRESS

            if self._mode == "iterative" and not state.is_complete("iterative"):
                status = await _phase("iterative", self._run_iterative_phase)
                state.iteration = self._iteration
                state.pivot_count = self._pivot_count
                state.contributions_count = prior_contributions + len(self._contributions)
                state.mark_complete("iterative")
                state.save(self._workspace)

            if self._mode == "iterative" and not state.is_complete("self_attack"):
                status = await _phase("self_attack", self._run_self_attack_phase)
                state.mark_complete("self_attack")
                state.save(self._workspace)

            if self._mode == "iterative" and not state.is_complete("polish"):
                status = await _phase("polish", self._run_polish_phase)
                state.mark_complete("polish")
                state.save(self._workspace)

            if not state.is_complete("review"):
                status = await _phase("review", self._run_review_phase)
                state.mark_complete("review")
                state.save(self._workspace)

            if not state.is_complete("revision"):
                # _run_revision_phase needs the current status as an argument
                await check_budget(self._paper_id, self._max_cost_usd, self._in_memory_spent())
                await log_event(self._paper_id, "phase_start", stage="revision")
                status = await self._run_revision_phase(status)
                await log_event(self._paper_id, "phase_end", stage="revision")
                state.last_status = status.value
                state.contributions_count = prior_contributions + len(self._contributions)
                state.mark_complete("revision")
                state.save(self._workspace)
            else:
                # Resuming past revision — restore saved verdict
                status = PaperStatus(state.last_status)

            if not state.is_complete("replication"):
                await _phase("replication", self._run_replication_phase)
                state.contributions_count = prior_contributions + len(self._contributions)
                state.mark_complete("replication")
                state.save(self._workspace)

            # Closes #6: when run() is called on a paper whose state.json
            # already has every stage marked complete (a resume on an
            # already-finished paper), no phase body executes and the DB
            # row would stay at `designing` (the state run() set on entry).
            # Mirror state.last_status — typically `completed` — back to
            # the DB so the dashboard reflects reality.
            if state.last_status:
                final_status = PaperStatus(state.last_status)
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
                    "last_error": (cb.last_error or "")[:500],
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
        """Run the initial design + data collection specialists.

        The pipeline is useless if the strategist failed to plan the initial
        phase (e.g. produced prose instead of JSON). Raise so the run is
        marked FAILED rather than silently advancing to a review phase with
        no draft to review.
        """
        decision = await self._strategist.decide("designing", iteration=0)
        if decision.action == "fail":
            raise RuntimeError(f"Strategist could not plan the initial phase: {decision.rationale}")
        if not decision.work_orders:
            raise RuntimeError(
                "Strategist returned no work orders for the initial phase — cannot "
                "proceed without specialist assignments."
            )
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
                    "Unrecognised ceiling verdict '%s' at iter=%d; treating as proceed_to_review",
                    ceiling.verdict,
                    iteration,
                )
                break

        return PaperStatus.CEILING_CHECK

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

        # Critical findings (severity >=7) trigger targeted revision
        if attack_report.critical_findings:
            critical_work_orders = [
                WorkOrder(
                    paper_id=self._paper_id,
                    specialist="revisor",
                    focus=(f"Critical finding (severity {f.severity}): {f.description}\nFix: {f.suggested_fix}"),
                    context_tier=2,
                )
                for f in attack_report.critical_findings[:3]  # limit to top 3
            ]
            contributions = await execute_parallel(
                critical_work_orders,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
            )
            self._contributions.extend(contributions)

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
        )
        self._contributions.extend(contributions)
        return PaperStatus.POLISH

    async def _run_review_phase(self) -> PaperStatus:
        """Parallel formal review by all reviewer specialists."""
        logger.info("Running review phase for paper %s", self._paper_id)
        await self._update_status(PaperStatus.REVIEW)

        review_orders = [
            WorkOrder(
                paper_id=self._paper_id,
                specialist=r,
                focus=f"Conduct a thorough {r.replace('_', ' ')} of this paper.",
                context_tier=2,
            )
            for r in REVIEWER_SPECIALISTS
        ]

        contributions = await execute_parallel(
            review_orders,
            self._backend,
            self._workspace,
            self._model,
            self._extra_tools,
            self._extra_handlers,
            self._backend_name,
        )
        self._contributions.extend(contributions)
        return PaperStatus.REVIEW

    async def _run_revision_phase(self, current_status: PaperStatus) -> PaperStatus:
        """Aggregate reviews and decide: accept, revise, or reject.

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
        # Fallback: any reviewer whose file we couldn't parse, try the
        # chat-side summary from the contribution row in memory.
        for c in self._contributions:
            if c.specialist in REVIEWER_SPECIALISTS and c.specialist not in seen:
                score = parse_review_output(c.specialist, c.output)
                if score:
                    scores.append(score)
                    seen.add(c.specialist)

        if not scores:
            # Auto-completing on missing review evidence is dangerous: it
            # produces a "completed" paper with no review trail. Surface as
            # FAILED so the user knows to re-run the review phase.
            logger.error(
                "No review scores extracted for paper %s — marking FAILED. Re-running the review phase will recover.",
                self._paper_id,
            )
            return PaperStatus.FAILED

        result = aggregate_reviews(scores)
        logger.info("Review aggregation: %s (avg=%.2f)", result.verdict, result.weighted_avg)

        aggregation_path = self._workspace / "review_aggregation.json"
        aggregation_path.write_text(
            json.dumps(
                {
                    "verdict": result.verdict,
                    "weighted_avg": result.weighted_avg,
                    "rule_triggered": result.rule_triggered,
                    "rationale": result.rationale,
                },
                indent=2,
            )
        )

        if result.verdict in {"ACCEPT", "MINOR_REVISION"}:
            await self._update_status(PaperStatus.COMPLETED)
            return PaperStatus.COMPLETED

        if result.verdict == "MAJOR_REVISION":
            await self._update_status(PaperStatus.REVISION)
            revision_order = WorkOrder(
                paper_id=self._paper_id,
                specialist="revisor",
                focus=f"Revise paper based on review aggregation: {result.rationale}",
                context_tier=2,
            )
            from ..specialists.dispatcher import execute_work_order

            contribution = await execute_work_order(
                revision_order,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
            )
            self._contributions.append(contribution)
            return PaperStatus.COMPLETED

        # HARD_REJECT or MECHANISM_FAIL
        logger.warning("Paper %s received %s", self._paper_id, result.verdict)
        await self._update_status(
            PaperStatus.FAILED,
            error=f"{result.verdict}: {result.rationale}",
        )
        return PaperStatus.FAILED

    async def _dispatch(self, decision: StrategistDecision) -> list[Contribution]:
        if not decision.work_orders:
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
        if len(contract_orders) == 1:
            from ..specialists.dispatcher import execute_work_order

            c = await execute_work_order(
                contract_orders[0],
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
            )
            contributions = [c]
        else:
            contributions = await execute_with_dependencies(
                contract_orders,
                self._backend,
                self._workspace,
                self._model,
                self._extra_tools,
                self._extra_handlers,
                self._backend_name,
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
        """Export audit trail and run replication_packager specialist."""
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
        )
        self._contributions.append(contribution)

    async def _run_compile_phase(self) -> None:
        """Compile paper_draft.tex to PDF. Non-fatal — PDF is a bonus output."""
        try:
            from ..renderer.compiler import compile_latex

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
        try:
            from ...db.client import execute

            terminal_with_reason = status in {PaperStatus.FAILED, PaperStatus.CANCELLED} and error is not None
            if terminal_with_reason:
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
