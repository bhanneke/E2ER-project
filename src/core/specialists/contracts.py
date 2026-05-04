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
    extra: dict[str, Any] = Field(default_factory=dict)


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
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReviewContribution(Contribution):
    """Reviewer output — includes structured score."""
    score: float = 0.0
    recommendation: str = ""
