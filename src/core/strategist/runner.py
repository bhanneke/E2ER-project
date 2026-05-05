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
from ..specialists.registry import REVIEWER_SPECIALISTS, POLISH_SPECIALISTS
from ..strategist.actions import CeilingCheckResult, SelfAttackReport, StrategistDecision
from ..strategist.engine import StrategistEngine
from ..strategist.review_aggregator import aggregate_reviews, parse_review_output
from ..strategist.state import PaperStatus

logger = get_logger(__name__)

_MAX_ITERATIONS = 6
_MAX_PIVOTS = 1


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
    ) -> None:
        self._paper_id = paper_id
        self._workspace = workspace
        self._backend = backend
        self._model = model
        self._mode = mode
        self._extra_tools = extra_tools or []
        self._extra_handlers = extra_handlers or []
        self._backend_name = backend_name
        self._strategist = StrategistEngine(backend, workspace, paper_id, mode)
        self._contributions: list[Contribution] = []
        self._iteration = 0
        self._pivot_count = 0

    async def run(self) -> dict[str, Any]:
        """Run the full pipeline from idea to completion."""
        status = PaperStatus.DESIGNING
        await self._update_status(status)

        try:
            # Phase 1: Initial design + data + contributions
            await self._run_initial_phase()
            status = PaperStatus.IN_PROGRESS

            if self._mode == "iterative":
                # Phase 2: Iterative improvement with ceiling detection
                status = await self._run_iterative_phase()

            # Phase 3: Self-attack (V3 extension)
            if self._mode == "iterative":
                status = await self._run_self_attack_phase()

            # Phase 4: Polish stack (V3 extension)
            if self._mode == "iterative":
                status = await self._run_polish_phase()

            # Phase 5: Formal review
            status = await self._run_review_phase()

            # Phase 6: Revision loop
            status = await self._run_revision_phase(status)

            return {"status": status.value, "contributions": len(self._contributions)}

        except Exception as e:
            logger.error("Pipeline failed for paper %s: %s", self._paper_id, e)
            await self._update_status(PaperStatus.FAILED)
            return {"status": "failed", "error": str(e)}

    async def _run_initial_phase(self) -> None:
        """Run the initial design + data collection specialists."""
        decision = await self._strategist.decide("designing", iteration=0)
        contributions = await self._dispatch(decision)
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
                        self._backend, self._workspace, self._model,
                        self._extra_tools, self._extra_handlers, self._backend_name,
                    )
                    self._contributions.extend(pivot_contributions)
                    break  # one pivot per paper

        return PaperStatus.CEILING_CHECK

    async def _run_self_attack_phase(self) -> PaperStatus:
        """Adversarial self-review to find critical flaws before external review."""
        logger.info("Running self-attack phase for paper %s", self._paper_id)
        await self._update_status(PaperStatus.SELF_ATTACK)

        attack_report = await self._strategist.run_self_attack()
        report_path = self._workspace / "self_attack_report.json"
        report_path.write_text(
            json.dumps(
                {"findings": [f.__dict__ for f in attack_report.findings],
                 "overall_severity": attack_report.overall_severity},
                indent=2,
            )
        )
        logger.info(
            "Self-attack: %d findings, max severity %d",
            len(attack_report.findings), attack_report.overall_severity,
        )

        # Critical findings (severity >=7) trigger targeted revision
        if attack_report.critical_findings:
            critical_work_orders = [
                WorkOrder(
                    paper_id=self._paper_id,
                    specialist="revisor",
                    focus=(
                        f"Critical finding (severity {f.severity}): {f.description}\n"
                        f"Fix: {f.suggested_fix}"
                    ),
                    context_tier=2,
                )
                for f in attack_report.critical_findings[:3]  # limit to top 3
            ]
            contributions = await execute_parallel(
                critical_work_orders,
                self._backend, self._workspace, self._model,
                self._extra_tools, self._extra_handlers, self._backend_name,
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
            self._backend, self._workspace, self._model,
            self._extra_tools, self._extra_handlers, self._backend_name,
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
            self._backend, self._workspace, self._model,
            self._extra_tools, self._extra_handlers, self._backend_name,
        )
        self._contributions.extend(contributions)
        return PaperStatus.REVIEW

    async def _run_revision_phase(self, current_status: PaperStatus) -> PaperStatus:
        """Aggregate reviews and decide: accept, revise, or reject."""
        from ..strategist.review_aggregator import ReviewScore

        scores = []
        for c in self._contributions:
            if c.specialist in REVIEWER_SPECIALISTS:
                score = parse_review_output(c.specialist, c.output)
                if score:
                    scores.append(score)

        if not scores:
            logger.warning("No review scores extracted — proceeding to completion")
            return PaperStatus.COMPLETED

        result = aggregate_reviews(scores)
        logger.info("Review aggregation: %s (avg=%.2f)", result.verdict, result.weighted_avg)

        aggregation_path = self._workspace / "review_aggregation.json"
        aggregation_path.write_text(
            json.dumps(
                {"verdict": result.verdict, "weighted_avg": result.weighted_avg,
                 "rule_triggered": result.rule_triggered, "rationale": result.rationale},
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
                revision_order, self._backend, self._workspace, self._model,
                self._extra_tools, self._extra_handlers, self._backend_name,
            )
            self._contributions.append(contribution)
            return PaperStatus.COMPLETED

        # HARD_REJECT or MECHANISM_FAIL
        logger.warning("Paper %s received %s", self._paper_id, result.verdict)
        await self._update_status(PaperStatus.FAILED)
        return PaperStatus.FAILED

    async def _dispatch(self, decision: StrategistDecision) -> list[Contribution]:
        if not decision.work_orders:
            return []
        # Convert strategist.actions.WorkOrder → specialists.contracts.WorkOrder
        # (strategist work orders carry parallel_group/context_tier but not paper_id)
        contract_orders = self._to_contract_orders(decision.work_orders)
        if len(contract_orders) == 1:
            from ..specialists.dispatcher import execute_work_order
            c = await execute_work_order(
                contract_orders[0],
                self._backend, self._workspace, self._model,
                self._extra_tools, self._extra_handlers, self._backend_name,
            )
            return [c]
        return await execute_with_dependencies(
            contract_orders,
            self._backend, self._workspace, self._model,
            self._extra_tools, self._extra_handlers, self._backend_name,
        )

    def _to_contract_orders(self, strategist_orders: list) -> list[WorkOrder]:
        """Adapt strategist.actions.WorkOrder → specialists.contracts.WorkOrder."""
        result = []
        for wo in strategist_orders:
            result.append(WorkOrder(
                paper_id=self._paper_id,
                specialist=wo.specialist,
                focus=wo.focus,
                parallel_group=getattr(wo, "parallel_group", 0),
                context_tier=getattr(wo, "context_tier", 1),
            ))
        return result

    async def _update_status(self, status: PaperStatus) -> None:
        try:
            from ...db.client import execute
            await execute(
                "UPDATE papers SET status = %(s)s, updated_at = NOW() WHERE id = %(id)s",
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
