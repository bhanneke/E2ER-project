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
    # Distinct from FAILED so the operator can tell at a glance whether
    # the paper crashed (FAILED) or was rejected by the review gate
    # (REJECTED). v0.4.5 live tests conflated both as FAILED. Resumable
    # via /api/papers/{id}/resume — operator revises and re-runs.
    REJECTED = "rejected"
    # Circuit-breaker halt + budget-exhausted halt. Set when a non-tolerant
    # specialist has failed too many times in a row, OR when the per-paper
    # cost cap is reached. Workspace artifacts + `.pipeline_state.json`
    # are preserved, so resuming with a higher --max-cost picks up at the
    # first incomplete phase. Operator inspects the workspace + events
    # and either resumes via /api/papers/{id}/resume or restarts from IDEA.
    PAUSED = "paused"


class PipelineMode(StrEnum):
    SINGLE_PASS = "single_pass"  # Mode 1 — fast draft, single specialist sequence
    ITERATIVE = "iterative"  # Mode 2 — full loop with ceiling detection + attack


class BudgetExceededError(Exception):
    """Raised when a paper's cumulative LLM cost reaches its per-paper cap."""

    def __init__(self, spent: float, cap: float) -> None:
        self.spent = spent
        self.cap = cap
        super().__init__(f"Budget exceeded: spent ${spent:.2f}, cap ${cap:.2f}")


class CircuitBreakerError(Exception):
    """Raised when a non-tolerant specialist has failed ``max_attempts`` times in a row.

    Halts the run cleanly with status=PAUSED instead of looping through
    the strategist's revision logic until budget is exhausted (the run
    #14 failure mode where data_analyst was re-dispatched 3 times when
    Allium was unrecoverably down).

    The PipelineRunner.run() catches this, marks the paper PAUSED, logs
    a circuit_breaker_tripped event with the specialist + reason, and
    returns gracefully. The operator inspects the workspace + events
    and either fixes the underlying issue + resumes, or cancels.
    """

    def __init__(self, specialist: str, attempts: int, last_error: str | None = None) -> None:
        self.specialist = specialist
        self.attempts = attempts
        self.last_error = last_error
        msg = f"Circuit breaker: {specialist} failed {attempts} times in a row"
        if last_error:
            msg += f". Last error: {last_error[:200]}"
        super().__init__(msg)


# Every state can transition to CANCELLED (user can cancel at any point).
# CANCELLED is terminal except for restart back to IDEA.
# PAUSED is reachable from every non-terminal state (circuit breaker), and
# can transition to IDEA (restart) or any non-terminal state (resume).
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
    # IN_PROGRESS → REJECTED for the pre-review verify_numbers audit gate.
    PaperStatus.IN_PROGRESS: {
        PaperStatus.CEILING_CHECK,
        PaperStatus.REVIEW,
        PaperStatus.REJECTED,
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
        PaperStatus.REJECTED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.REVISION: {
        PaperStatus.REVIEW,
        PaperStatus.COMPLETED,
        PaperStatus.FAILED,
        PaperStatus.REJECTED,
        PaperStatus.CANCELLED,
    },
    PaperStatus.COMPLETED: set(),
    PaperStatus.FAILED: {PaperStatus.IDEA},
    PaperStatus.CANCELLED: {PaperStatus.IDEA},
    # REJECTED is reachable from REVIEW/REVISION (HARD_REJECT, MECHANISM_FAIL)
    # and can transition back to IDEA (restart) or any non-terminal phase
    # when the operator resumes after revising the source artifacts.
    PaperStatus.REJECTED: {
        PaperStatus.IDEA,
        PaperStatus.CANCELLED,
        PaperStatus.IN_PROGRESS,
        PaperStatus.REVIEW,
        PaperStatus.REVISION,
    },
    # PAUSED → can restart from IDEA, cancel, OR resume by re-entering any
    # non-terminal phase. Resume picks the phase based on the workspace's
    # last completed canonical artifact (see runner._resume_target_status).
    PaperStatus.PAUSED: {
        PaperStatus.IDEA,
        PaperStatus.CANCELLED,
        PaperStatus.DESIGNING,
        PaperStatus.DATA_COLLECTION,
        PaperStatus.IN_PROGRESS,
        PaperStatus.CEILING_CHECK,
        PaperStatus.SELF_ATTACK,
        PaperStatus.POLISH,
        PaperStatus.REVIEW,
        PaperStatus.REVISION,
    },
}

# Augment every non-terminal state with PAUSED as a valid exit target.
# Kept out of the literal above so the FSM diagram stays readable.
for _state in _NON_TERMINAL:
    VALID_TRANSITIONS[_state].add(PaperStatus.PAUSED)


def can_transition(current: PaperStatus, target: PaperStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())
