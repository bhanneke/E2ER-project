"""Strategist engine — the meta-agent that directs the pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend
from ...modules.llm.tools import FILE_TOOLS, FileToolHandler
from ..strategist.actions import (
    CeilingCheckResult,
    SelfAttackFinding,
    SelfAttackReport,
    StrategistDecision,
    WorkOrder,
)
from ..strategist.context import (
    build_self_attack_context,
    build_tier1_context,
    build_tier2_context,
)

logger = get_logger(__name__)

_STRATEGIST_SYSTEM = """\
You are the Strategist, the meta-agent directing an end-to-end empirical research pipeline.
Your role is to read the current paper state and decide what work to assign next.

You have deep expertise in academic research workflows for information systems, economics, and finance.
You emit structured JSON decisions — you do NOT write paper content directly.

## CRITICAL OUTPUT FORMAT
Your entire response MUST be a single JSON object — nothing else.
- Do NOT write any prose, analysis, headings, or markdown before or after the JSON.
- Do NOT wrap the JSON in code fences (no ```json blocks).
- Begin your response with `{` and end it with `}`.
- If you write any text outside the JSON, the pipeline will fail.

## JSON Schema (StrategistDecision)
```
{
  "action": "dispatch_parallel" | "dispatch_work_order" | "complete" | "fail"
            | "ceiling_check" | "self_attack" | "dispatch_polish_stack"
            | "dispatch_review" | "request_revision",
  "work_orders": [
    {
      "specialist": "<one of: idea_developer, literature_scanner, identification_strategist,
                     data_architect, econometrics_specialist, data_analyst, theory_specialist,
                     paper_drafter, section_writer, abstract_writer, latex_formatter, revisor>",
      "focus": "<one-paragraph specific instruction for this specialist>",
      "parallel_group": <integer 0..N — same group runs in parallel; later groups depend on earlier>
    }
  ],
  "rationale": "<short justification>"
}
```

Note: reviewer specialists (mechanism_reviewer, technical_reviewer,
literature_reviewer, writing_reviewer, data_reviewer, identification_reviewer)
and polish specialists (polish_formula, polish_numerics, polish_institutions,
polish_bibliography, polish_equilibria) are NOT in your dispatch roster.
The runner invokes those directly during the review and polish phases —
do not return them as work_orders.

## Example for the initial design phase
{
  "action": "dispatch_parallel",
  "work_orders": [
    {"specialist":"idea_developer","focus":"Develop RQ into paper plan.","parallel_group":0},
    {"specialist":"literature_scanner","focus":"Survey prior work.","parallel_group":0},
    {"specialist":"identification_strategist","focus":"Propose ID strategy.","parallel_group":0},
    {"specialist":"data_architect","focus":"Write data_dictionary.json.","parallel_group":1},
    {"specialist":"data_analyst","focus":"Acquire data via Allium.","parallel_group":2},
    {"specialist":"econometrics_specialist","focus":"Specify the econometric model.","parallel_group":2},
    {"specialist":"paper_drafter","focus":"Draft the paper body.","parallel_group":3},
    {"specialist":"abstract_writer","focus":"Write the abstract.","parallel_group":3}
  ],
  "rationale": "Initial design + data acquisition + writing pass."
}

## Methodology-aware dispatch

The paper's `Methodology:` field (in the context block) is one of `empirical`,
`theoretical`, or `mixed`. Dispatch differently:

- `empirical` (default): dispatch the data + econometrics specialists. Do NOT
  dispatch `theory_specialist`. ALWAYS include `data_analyst` after
  `data_architect` — that's the specialist that actually queries data;
  skipping it leaves the paper without empirical content.
- `theoretical`: dispatch `theory_specialist` to develop the formal model.
  Do NOT dispatch `data_architect`, `data_analyst`, or `econometrics_specialist`
  for a pure theoretical paper.
- `mixed`: dispatch `theory_specialist` AND the empirical specialists. Theory
  develops the model; empirical specialists test its predictions.

`theory_specialist` writes `model_spec.md` (formal model in LaTeX with
assumptions, derivations, propositions). Place it in the same parallel_group
as `identification_strategist` since they're both upstream of writing.

Output ONLY the JSON object. No commentary.
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

    def __init__(
        self,
        backend: LLMBackend,
        workspace: Path,
        paper_id: str,
        mode: str = "iterative",
        model: str = "",
        backend_name: str = "anthropic",
    ) -> None:
        from ...modules.llm.base import TokenUsage

        self._backend = backend
        self._workspace = workspace
        self._paper_id = paper_id
        self._mode = mode
        self._model = model
        self._backend_name = backend_name
        self._handler = FileToolHandler(workspace)
        # Cumulative usage across all backend calls — read by PipelineRunner
        # for the in-memory cost cap.
        self.total_usage: TokenUsage = TokenUsage()

    async def _record_usage(self, kind: str, usage) -> None:
        """Persist a strategist call to llm_usage so it shows up in audit/cost.
        Without this, strategist tokens are invisible to GET /api/papers and
        the audit bundle, leading to systematic cost under-reporting."""
        from ...modules.tracking.usage import save_usage

        try:
            await save_usage(
                paper_id=self._paper_id,
                specialist=f"strategist:{kind}",
                backend=self._backend_name,
                model=self._model or "unknown",
                usage=usage,
            )
        except Exception as e:
            logger.debug("Strategist usage save skipped: %s", e)

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

        msgs = [{"role": "user", "content": prompt}]
        result = await self._backend.tool_loop(
            system=_STRATEGIST_SYSTEM,
            messages=msgs,
            tools=FILE_TOOLS,
            tool_handler=self._handler,
            max_turns=10,
        )
        self.total_usage = self.total_usage + result.usage
        await self._record_usage("decide", result.usage)

        decision = _parse_decision(result.output)
        # If the model produced prose instead of JSON, retry once with a strict
        # follow-up that includes its prior output. Smaller models (Haiku, etc.)
        # often need this nudge.
        if decision.action == "fail" and "Parse error" in (decision.rationale or ""):
            retry_msgs = msgs + [
                {"role": "assistant", "content": result.output[:4000]},
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON. "
                        "Output ONLY a JSON object (begin with `{`, end with `}`, "
                        "no prose, no fences) matching the StrategistDecision schema."
                    ),
                },
            ]
            retry = await self._backend.tool_loop(
                system=_STRATEGIST_SYSTEM,
                messages=retry_msgs,
                tools=[],
                tool_handler=None,
                max_turns=2,
            )
            self.total_usage = self.total_usage + retry.usage
            await self._record_usage("decide_retry", retry.usage)
            decision = _parse_decision(retry.output)

        return decision

    async def ceiling_check(self, iteration: int, pivot_count: int) -> CeilingCheckResult:
        """Assess whether the iteration has hit diminishing returns."""
        context = build_tier1_context(self._workspace, self._paper_id)
        prompt = f"Iteration: {iteration}, Pivots used: {pivot_count}\n\n{context}\n\n" + _CEILING_CHECK_PROMPT

        result = await self._backend.tool_loop(
            system=_STRATEGIST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            tool_handler=None,
            max_turns=3,
        )
        self.total_usage = self.total_usage + result.usage
        await self._record_usage("ceiling_check", result.usage)

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
        await self._record_usage("self_attack", result.usage)

        raw = json.loads(result.output) if result.output.startswith("{") else {}
        findings = [SelfAttackFinding(**f) for f in raw.get("findings", [])]
        overall = raw.get("overall_severity", max((f.severity for f in findings), default=0))
        return SelfAttackReport(findings=findings, overall_severity=overall)


def _parse_decision(raw: str) -> StrategistDecision:
    """Parse a StrategistDecision from raw LLM output.

    Handles three common output shapes:
      1. Pure JSON object.
      2. JSON wrapped in a ```json ... ``` (or bare ```...```) fenced block.
      3. JSON embedded in surrounding prose.

    We need the OUTERMOST JSON object (the StrategistDecision itself), not
    one of the inner work_order objects. So the parser tries strategies that
    target the outer object first.
    """
    import re

    if not raw or not raw.strip():
        return StrategistDecision(action="fail", rationale="Parse error: empty response")

    candidates: list[str] = []

    # 1. Fenced block: ```json {...} ``` — greedy DOTALL captures the whole inner.
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw)
    if m:
        candidates.append(m.group(1).strip())

    # 2. Outermost balanced {...} object found by scanning forward.
    text = raw.strip()
    if text.startswith("{") and text.endswith("}"):
        candidates.append(text)
    else:
        # Find the first '{' and walk forward tracking depth in strings.
        start = text.find("{")
        if start >= 0:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(text)):
                ch = text[i]
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start : i + 1])
                        break

    data: dict[str, Any] | None = None
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict) and "action" in parsed:
                data = parsed
                break
        except Exception:
            continue

    if not isinstance(data, dict):
        snippet = raw[:200].replace("\n", " ")
        logger.warning("Failed to parse strategist decision — raw: %s", snippet)
        return StrategistDecision(
            action="fail",
            rationale=f"Parse error: response was not JSON (started with {raw[:60]!r})",
        )

    try:
        work_orders = [WorkOrder(**w) for w in data.get("work_orders", [])]
        return StrategistDecision(
            action=data.get("action", "fail"),
            work_orders=work_orders,
            rationale=data.get("rationale", ""),
            next_status=data.get("next_status", ""),
            pivot_count=data.get("pivot_count", 0),
        )
    except Exception as e:
        logger.warning("Failed to build StrategistDecision: %s — data: %s", e, str(data)[:200])
        return StrategistDecision(action="fail", rationale=f"Parse error: {e}")
