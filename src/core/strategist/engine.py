"""Strategist engine — the meta-agent that directs the pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, ToolLoopResult
from ...modules.llm.tools import FILE_TOOLS, FileToolHandler
from ..strategist.actions import (
    CeilingCheckResult,
    SelfAttackReport,
    SelfAttackFinding,
    StrategistDecision,
    WorkOrder,
)
from ..strategist.context import (
    build_tier1_context,
    build_tier2_context,
    build_self_attack_context,
)

logger = get_logger(__name__)

_STRATEGIST_SYSTEM = """\
You are the Strategist, the meta-agent directing an end-to-end empirical research pipeline.
Your role is to read the current paper state and decide what work to assign next.

You have deep expertise in academic research workflows for information systems, economics, and finance.
You emit structured JSON decisions — you do NOT write paper content directly.

Decision types you can emit:
- dispatch_work_order: assign one specialist
- dispatch_parallel: assign multiple specialists in parallel (list of work_orders)
- ceiling_check: assess whether current iteration has hit diminishing returns
- self_attack: adversarial review of the current draft
- dispatch_polish_stack: targeted fixes for identified weaknesses
- dispatch_review: formal review by reviewer specialists
- request_revision: send back to specific specialists with revision instructions
- complete: paper is ready
- fail: unrecoverable problem

Always output your decision as a JSON object conforming to StrategistDecision.
"""

_CEILING_CHECK_PROMPT = """\
You are assessing whether the current iteration of this paper has hit a quality ceiling.

Look at the trajectory across contributions. Answer: has improvement stalled?

Rules:
- If contributions from the last iteration show <5% qualitative improvement → verdict: "proceed_to_review"
- If there are clear specific gaps that targeted work can fix → verdict: "pivot"
  (list the work_orders needed)
- Otherwise → verdict: "continue"

Max 1 pivot allowed per paper. If pivot_count >= 1, default to "proceed_to_review".

Output JSON: {"verdict": "...", "reason": "...", "suggested_pivots": [...]}
"""

_SELF_ATTACK_SYSTEM = """\
You are an adversarial reviewer. Your goal is to find every flaw in this paper before it reaches
external reviewers. Be ruthless but specific.

For each finding, assign:
- severity: 1-10 (10 = fatal flaw, 1 = minor polish)
- category: identification | mechanism | numerics | institutions | equilibrium | bibliography | framing | novelty
- description: specific, actionable description of the problem
- suggested_fix: concrete suggestion

Output JSON: {"findings": [...], "overall_severity": N}
"""


class StrategistEngine:
    """Owns the paper-level planning loop."""

    def __init__(self, backend: LLMBackend, workspace: Path, paper_id: str, mode: str = "iterative") -> None:
        from ...modules.llm.base import TokenUsage
        self._backend = backend
        self._workspace = workspace
        self._paper_id = paper_id
        self._mode = mode
        self._handler = FileToolHandler(workspace)
        # Cumulative usage across all backend calls — read by PipelineRunner
        # for the in-memory cost cap.
        self.total_usage: TokenUsage = TokenUsage()

    async def decide(self, current_status: str, iteration: int = 0) -> StrategistDecision:
        """Ask the Strategist what to do next, given current paper state."""
        context = build_tier2_context(self._workspace, self._paper_id)
        prompt = (
            f"Paper status: {current_status}\n"
            f"Iteration: {iteration}\n"
            f"Mode: {self._mode}\n\n"
            f"{context}\n\n"
            "Decide what to do next. Output a JSON StrategistDecision."
        )

        result = await self._backend.tool_loop(
            system=_STRATEGIST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=FILE_TOOLS,
            tool_handler=self._handler,
            max_turns=10,
        )
        self.total_usage = self.total_usage + result.usage

        return _parse_decision(result.output)

    async def ceiling_check(self, iteration: int, pivot_count: int) -> CeilingCheckResult:
        """Assess whether the iteration has hit diminishing returns."""
        context = build_tier1_context(self._workspace, self._paper_id)
        prompt = (
            f"Iteration: {iteration}, Pivots used: {pivot_count}\n\n"
            f"{context}\n\n"
            + _CEILING_CHECK_PROMPT
        )

        result = await self._backend.tool_loop(
            system=_STRATEGIST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            tool_handler=None,
            max_turns=3,
        )
        self.total_usage = self.total_usage + result.usage

        raw = json.loads(result.output) if result.output.startswith("{") else {}
        return CeilingCheckResult(
            verdict=raw.get("verdict", "proceed_to_review"),
            reason=raw.get("reason", ""),
            suggested_pivots=[WorkOrder(**w) for w in raw.get("suggested_pivots", [])],
            iteration=iteration,
        )

    async def run_self_attack(self) -> SelfAttackReport:
        """Run the adversarial self-attack phase."""
        context = build_self_attack_context(self._workspace, self._paper_id)
        prompt = f"{context}\n\nFind all flaws. Output JSON SelfAttackReport."

        result = await self._backend.tool_loop(
            system=_SELF_ATTACK_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            tool_handler=None,
            max_turns=3,
        )
        self.total_usage = self.total_usage + result.usage

        raw = json.loads(result.output) if result.output.startswith("{") else {}
        findings = [SelfAttackFinding(**f) for f in raw.get("findings", [])]
        overall = raw.get("overall_severity", max((f.severity for f in findings), default=0))
        return SelfAttackReport(findings=findings, overall_severity=overall)


def _parse_decision(raw: str) -> StrategistDecision:
    from ...modules.llm.base import extract_json
    text = extract_json(raw) or raw
    try:
        data = json.loads(text)
        work_orders = [WorkOrder(**w) for w in data.get("work_orders", [])]
        return StrategistDecision(
            action=data.get("action", "fail"),
            work_orders=work_orders,
            rationale=data.get("rationale", ""),
            next_status=data.get("next_status", ""),
            pivot_count=data.get("pivot_count", 0),
        )
    except Exception as e:
        logger.warning("Failed to parse strategist decision: %s — raw: %s", e, raw[:200])
        return StrategistDecision(action="fail", rationale=f"Parse error: {e}")
