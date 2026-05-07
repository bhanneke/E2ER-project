"""Strategist action types — structured decisions emitted by the Strategist."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WorkOrder(BaseModel):
    specialist: str
    focus: str
    context_tier: Literal[0, 1, 2] = 1
    tools: list[str] = Field(default_factory=list)
    parallel_group: int = 0
    rationale: str = ""
    priority: int = 0


class StrategistDecision(BaseModel):
    action: Literal[
        "dispatch_work_order",
        "dispatch_parallel",
        "ceiling_check",
        "self_attack",
        "dispatch_polish_stack",
        "dispatch_review",
        "request_revision",
        "complete",
        "fail",
        "wait_for_data",
    ]
    work_orders: list[WorkOrder] = Field(default_factory=list)
    rationale: str = ""
    next_status: str = ""
    pivot_count: int = 0


class CeilingCheckResult(BaseModel):
    verdict: Literal["continue", "pivot", "proceed_to_review"]
    reason: str
    suggested_pivots: list[WorkOrder] = Field(default_factory=list)
    iteration: int = 0


class SelfAttackFinding(BaseModel):
    severity: int  # 1-10
    category: Literal[
        "identification",
        "mechanism",
        "numerics",
        "institutions",
        "equilibrium",
        "bibliography",
        "framing",
        "novelty",
    ]
    description: str
    suggested_fix: str = ""


class SelfAttackReport(BaseModel):
    findings: list[SelfAttackFinding]
    overall_severity: int  # max severity across all findings

    @property
    def critical_findings(self) -> list[SelfAttackFinding]:
        return [f for f in self.findings if f.severity >= 7]

    @property
    def moderate_findings(self) -> list[SelfAttackFinding]:
        return [f for f in self.findings if 4 <= f.severity < 7]
