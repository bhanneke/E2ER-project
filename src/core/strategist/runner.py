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
from ..strategist.state import BudgetExceededError, CircuitBreakerError, PaperStatus

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
_MAX_SPECIALIST_ATTEMPTS = 3
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
    ) -> None:
        self._paper_id = paper_id
        self._workspace = workspace
        self._backend = backend
        self._model = model
        self._mode = mode
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
                status = _coerce_paper_status(state.last_status, status)

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
                final_status = _coerce_paper_status(state.last_status, status)
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
        out = await asyncio.to_thread(export_paper, self._workspace, dest_root, date_str=date_str)
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
            report = verify_and_save(draft_path, self._workspace)
            if report.critical_mismatches:
                # v0.6 step 5: try to auto-patch before rejecting. If the
                # patch_revisor can fix the mismatches by editing the
                # table cells the drafter got wrong, the paper continues
                # to reviewers; otherwise REJECTED with the same error
                # surface as v0.5.
                report = await self._verify_numbers_auto_patch(report)
                if report.critical_mismatches:
                    summary = "; ".join(
                        f"{m.draft_value} vs {m.source_value} ({m.source_key}) at {m.table_context}"
                        for m in report.critical_mismatches[:5]
                    )
                    error = (
                        f"verify_numbers: {len(report.critical_mismatches)} critical "
                        f"mismatch(es) between LaTeX tables and source JSON. "
                        f"First {min(5, len(report.critical_mismatches))}: {summary}"
                    )
                    logger.error("Paper %s: %s", self._paper_id, error)
                    await self._update_status(PaperStatus.REJECTED, error=error)
                    return PaperStatus.REJECTED

        # --- verify_citations pre-review gate (v0.9 M2) ---
        # Mechanical anti-hallucination for references: every \cite
        # resolves in references.bib AND in at least one of OpenAlex /
        # S2 / Crossref. Default policy: hard-block on missing-in-bib
        # only (LaTeX would also fail); ``unverifiable`` is warn-only
        # because preprints / posters legitimately aren't indexed.
        # Flip to hard-block with E2ER_STRICT_CITATION_INTEGRITY=true.
        if draft_path.is_file():
            from ..pipeline.verify_citations import verify_and_save as verify_citations_and_save

            cite_report = await verify_citations_and_save(draft_path, self._workspace)
            if not cite_report.passed:
                missing = ", ".join(c.cite_key for c in cite_report.missing_checks[:5])
                unverif = ", ".join(c.cite_key for c in cite_report.unverifiable_checks[:5])
                pieces = []
                if cite_report.missing_in_bib:
                    pieces.append(f"{cite_report.missing_in_bib} cited key(s) missing from references.bib: {missing}")
                if cite_report.strict and cite_report.unverifiable:
                    pieces.append(f"{cite_report.unverifiable} unverifiable cite(s) (strict mode): {unverif}")
                error = "verify_citations: " + "; ".join(pieces)
                logger.error("Paper %s: %s", self._paper_id, error)
                await self._update_status(PaperStatus.REJECTED, error=error)
                return PaperStatus.REJECTED

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
        scores = self._read_review_scores()
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

        # HARD_REJECT, or MECHANISM_FAIL the deep round couldn't lift — distinct
        # from FAILED (crash). The operator can revise + POST /resume.
        logger.warning("Paper %s received %s", self._paper_id, result.verdict)
        await self._update_status(
            PaperStatus.REJECTED,
            error=f"{result.verdict}: {result.rationale}",
        )
        return PaperStatus.REJECTED

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
                    scores.append(score)
                    seen.add(c.specialist)
        return scores

    def _write_review_aggregation(self, result) -> None:
        (self._workspace / "review_aggregation.json").write_text(
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
        from ..renderer.tables import ensure_input_stubs, render_tables
        from ..specialists.dispatcher import execute_work_order

        feedback = self._referee_feedback_text()
        research_focus = (
            "The reviewers rejected this paper's RESEARCH, not its wording. "
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
            )
            self._contributions.append(c)

        # Tables follow the revised JSON; re-render before the writer edits prose.
        render_tables(self._workspace)
        ensure_input_stubs(self._workspace)

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
        )
        self._contributions.append(c)

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
            logger.debug("verify_numbers auto-patch disabled by budget; falling through to REJECTED")
            return report

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
                "— skipping auto-patch and falling through to REJECTED"
            )
            return report

        try:
            merge_result = await self._dispatch_patch_revisor(findings)
        except FileNotFoundError as e:
            logger.warning(
                "verify_numbers auto-patch: patch_revisor produced no patch file (%s) — falling through to REJECTED",
                e,
            )
            return report

        if not merge_result.fully_applied:
            logger.warning(
                "verify_numbers auto-patch: %d edits applied, %d failed — falling through to REJECTED",
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

        from ..specialists.dispatcher import execute_work_order
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

        return merge_patch_file(self._workspace, findings)

    async def _resolve_table_spec(self) -> None:
        """Render results tables and close the loop on cross-specialist key
        drift.

        The renderer auto-resolves order-insensitive key drift
        (``dp_full`` ≡ ``full_dp``). Anything still unresolved is a genuinely
        wrong/abbreviated/missing reference (e.g. the drafter wrote ``cw_stat``
        where the JSON has ``clark_west_stat``) that leaves those cells ``---``.
        Rather than ship a paper with blank cells, dispatch ONE ``section_writer``
        call with the unresolved references and the real available keys, then
        re-render. Deterministic normalization already covers the common case;
        this handles the long tail.
        """
        from ..renderer.tables import ensure_input_stubs, render_tables

        report = render_tables(self._workspace)
        ensure_input_stubs(self._workspace)
        if not report.unresolved:
            return

        feedback = self._build_table_spec_feedback(report.unresolved)
        if feedback is None:
            # No estimation JSON to reconcile against — nothing actionable.
            return

        logger.info(
            "table_spec: %d unresolved reference(s) after normalization — dispatching "
            "section_writer to correct table_spec.json",
            len(report.unresolved),
        )
        from ..specialists.dispatcher import execute_work_order

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
        )
        self._contributions.append(contribution)

        # Re-render with the corrected spec. Remaining unresolved refs stay
        # `---` (and visible in table_render_report.json) — one fix attempt.
        report2 = render_tables(self._workspace)
        ensure_input_stubs(self._workspace)
        if report2.unresolved:
            logger.warning(
                "table_spec: %d reference(s) still unresolved after section_writer fix — "
                "rendered as --- (see table_render_report.json)",
                len(report2.unresolved),
            )
        else:
            logger.info("table_spec: all references resolved after section_writer fix")

    def _build_table_spec_feedback(self, unresolved: list) -> str | None:
        """Compose a directive for section_writer to fix table_spec.json,
        listing the unresolved references and the EXACT keys/fields available
        in the estimation JSON. Returns None when there's no JSON to reconcile.
        """
        import json

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

        fields: set[str] = set()
        coeffs: set[str] = set()
        for v in merged.values():
            if not isinstance(v, dict):
                continue
            for ck in ("diagnostics", "forecast_evaluation"):
                c = v.get(ck)
                if isinstance(c, dict):
                    fields.update(c.keys())
            fields.update(k for k, val in v.items() if not isinstance(val, dict | list))
            cf = v.get("coefficients")
            if isinstance(cf, dict):
                coeffs.update(cf.keys())

        unresolved_lines = sorted({f"  - {u.kind}: {u.ref!r}" for u in unresolved})
        return (
            "Your `table_spec.json` references keys that do not exist in the "
            "estimation JSON, so those table cells rendered blank (`---`). "
            "Rewrite `table_spec.json` so that EVERY `spec_key`, coefficient "
            "`var`, and stat `field` is an EXACT key present in the JSON below. "
            "Do not invent or abbreviate names; copy them verbatim. Keep the "
            "same table structure; only correct the keys. Output the corrected "
            "`table_spec.json` (and only that file).\n\n"
            "Unresolved references to fix:\n" + "\n".join(unresolved_lines) + "\n\n"
            f"Available `spec_key` values (top-level keys): {spec_keys}\n"
            f"Available stat `field` names: {sorted(fields)}\n"
            f"Available coefficient `var` names: {sorted(coeffs)}\n"
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
            REJECTED  — patch_revisor produced no patch file at all,
                       or one or more edits failed. The error message
                       names the first failures so the operator can
                       revise + resume.
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
                "Paper %s: MAJOR_REVISION verdict with no actionable findings "
                "— skipping patch_revisor and marking COMPLETED",
                self._paper_id,
            )
            await self._update_status(PaperStatus.COMPLETED)
            return PaperStatus.COMPLETED

        try:
            merge_result = await self._dispatch_patch_revisor(findings)
        except FileNotFoundError as e:
            error_msg = f"patch_revisor did not produce a patch file: {e}"
            logger.error("Paper %s: %s", self._paper_id, error_msg)
            await self._update_status(PaperStatus.REJECTED, error=error_msg)
            return PaperStatus.REJECTED

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

        # Nothing applied — the revision didn't happen (every edit was
        # out-of-scope or unmatchable). Surface for operator revise + resume.
        first_failures = "; ".join(f"[{r.edit.target}] {r.error}" for r in merge_result.failed[:3])
        error_msg = f"patch_revisor: 0 edits applied, {merge_result.n_failed} failed. First failures: {first_failures}"
        logger.warning("Paper %s: %s", self._paper_id, error_msg)
        await self._update_status(PaperStatus.REJECTED, error=error_msg)
        return PaperStatus.REJECTED

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
        if len(contract_orders) == 1:
            from ..specialists.dispatcher import assert_artifacts_written, execute_work_order

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
            # Same cascade guard execute_parallel applies — a lone non-tolerant
            # specialist that "succeeded" without its canonical artifact must
            # halt here, not starve downstream specialists.
            assert_artifacts_written(contributions, self._workspace)
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
        )
        self._contributions.append(contribution)

    async def _run_compile_phase(self) -> None:
        """Compile paper_draft.tex to PDF. Non-fatal — PDF is a bonus output."""
        try:
            # Re-render tables from the current spec + sidecars (a revision may
            # have changed either), then backfill stubs for any dangling
            # \input so a missing table can't abort the whole compile.
            from ..renderer.compiler import compile_latex
            from ..renderer.tables import ensure_input_stubs, render_tables

            render_tables(self._workspace)
            ensure_input_stubs(self._workspace)
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
