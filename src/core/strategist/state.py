"""Paper and pipeline state machines."""

from __future__ import annotations

from enum import StrEnum


class PaperStatus(StrEnum):
    IDEA = "idea"
    DESIGNING = "designing"
    DATA_COLLECTION = "data_collection"
    DATA_APPROVAL = "data_approval"
    IN_PROGRESS = "in_progress"
    CEILING_CHECK = "ceiling_check"
    SELF_ATTACK = "self_attack"
    POLISH = "polish"
    REVIEW = "review"
    REVISION = "revision"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineMode(StrEnum):
    SINGLE_PASS = "single_pass"  # Mode 1 — fast draft, single specialist sequence
    ITERATIVE = "iterative"  # Mode 2 — full loop with ceiling detection + attack


class BudgetExceededError(Exception):
    """Raised when a paper's cumulative LLM cost reaches its per-paper cap."""

    def __init__(self, spent: float, cap: float) -> None:
        self.spent = spent
        self.cap = cap
        super().__init__(f"Budget exceeded: spent ${spent:.2f}, cap ${cap:.2f}")


# Every state can transition to CANCELLED (user can cancel at any point).
# CANCELLED is terminal except for restart back to IDEA.
_NON_TERMINAL = {
    PaperStatus.IDEA,
    PaperStatus.DESIGNING,
    PaperStatus.DATA_COLLECTION,
    PaperStatus.DATA_APPROVAL,
    PaperStatus.IN_PROGRESS,
    PaperStatus.CEILING_CHECK,
    PaperStatus.SELF_ATTACK,
    PaperStatus.POLISH,
    PaperStatus.REVIEW,
    PaperStatus.REVISION,
}

VALID_TRANSITIONS: dict[PaperStatus, set[PaperStatus]] = {
    PaperStatus.IDEA: {PaperStatus.DESIGNING, PaperStatus.FAILED, PaperStatus.CANCELLED},
    PaperStatus.DESIGNING: {
        PaperStatus.DATA_COLLECTION,
        PaperStatus.IN_PROGRESS,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.DATA_COLLECTION: {
        PaperStatus.DATA_APPROVAL,
        PaperStatus.IN_PROGRESS,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.DATA_APPROVAL: {
        PaperStatus.IN_PROGRESS,
        PaperStatus.DATA_COLLECTION,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.IN_PROGRESS: {
        PaperStatus.CEILING_CHECK,
        PaperStatus.REVIEW,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.CEILING_CHECK: {
        PaperStatus.SELF_ATTACK,
        PaperStatus.REVIEW,
        PaperStatus.IN_PROGRESS,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.SELF_ATTACK: {
        PaperStatus.POLISH,
        PaperStatus.REVIEW,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.POLISH: {PaperStatus.REVIEW, PaperStatus.FAILED, PaperStatus.CANCELLED},
    PaperStatus.REVIEW: {
        PaperStatus.REVISION,
        PaperStatus.COMPLETED,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.REVISION: {
        PaperStatus.REVIEW,
        PaperStatus.COMPLETED,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.COMPLETED: set(),
    PaperStatus.FAILED: {PaperStatus.IDEA},
    PaperStatus.CANCELLED: {PaperStatus.IDEA},
}


def can_transition(current: PaperStatus, target: PaperStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())
