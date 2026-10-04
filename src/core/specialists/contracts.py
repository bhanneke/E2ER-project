"""Specialist contracts — WorkOrder and Contribution Pydantic models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkOrder(BaseModel):
    """Instructions passed to a specialist."""

    paper_id: str
    specialist: str
    focus: str
    context: str = ""
    tools: list[str] = Field(default_factory=list)
    output_file: str = ""
    # Additional artifacts the specialist MUST produce alongside output_file.
    # Auto-populated from registry.SPECIALIST_SIDECAR_ARTIFACTS in
    # dispatcher._inject_context. Drives the multi-file "Required Output"
    # block in the prompt; used to enforce the JSON contract that
    # verify_numbers and downstream consumers depend on.
    sidecar_artifacts: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    parallel_group: int = 0  # used by execute_with_dependencies for group ordering
    context_tier: int = 1  # 0=minimal, 1=decision-relevant, 2=full artifacts


class Contribution(BaseModel):
    """Result produced by a specialist."""

    paper_id: str
    specialist: str
    output: str
    output_file: str = ""
    artifacts: list[str] = Field(default_factory=list)
    usage_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    success: bool = True
    error: str = ""
    # The output-contract violations that failed this attempt ("artifact: reason"),
    # empty when it succeeded or failed for another reason (a crash, a timeout).
    contract_violations: list[str] = Field(default_factory=list)
    # Every attempt the dispatcher made for this work order, oldest first:
    # {"attempt": n, "error": "...", "violations": [...]}; set when it retried.
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReviewContribution(Contribution):
    """Reviewer output — includes structured score."""

    score: float = 0.0
    recommendation: str = ""
