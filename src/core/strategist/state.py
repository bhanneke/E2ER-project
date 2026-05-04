"""Paper and pipeline state machines."""
from __future__ import annotations

from enum import Enum


class PaperStatus(str, Enum):
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


class PipelineMode(str, Enum):
    SINGLE_PASS = "single_pass"   # Mode 1 — fast draft, single specialist sequence
    ITERATIVE = "iterative"       # Mode 2 — full loop with ceiling detection + attack


VALID_TRANSITIONS: dict[PaperStatus, set[PaperStatus]] = {
    PaperStatus.IDEA: {PaperStatus.DESIGNING, PaperStatus.FAILED},
    PaperStatus.DESIGNING: {PaperStatus.DATA_COLLECTION, PaperStatus.IN_PROGRESS, PaperStatus.FAILED},
    PaperStatus.DATA_COLLECTION: {PaperStatus.DATA_APPROVAL, PaperStatus.IN_PROGRESS, PaperStatus.FAILED},
    PaperStatus.DATA_APPROVAL: {PaperStatus.IN_PROGRESS, PaperStatus.DATA_COLLECTION, PaperStatus.FAILED},
    PaperStatus.IN_PROGRESS: {PaperStatus.CEILING_CHECK, PaperStatus.REVIEW, PaperStatus.FAILED},
    PaperStatus.CEILING_CHECK: {PaperStatus.SELF_ATTACK, PaperStatus.REVIEW, PaperStatus.IN_PROGRESS, PaperStatus.FAILED},
    PaperStatus.SELF_ATTACK: {PaperStatus.POLISH, PaperStatus.REVIEW, PaperStatus.FAILED},
    PaperStatus.POLISH: {PaperStatus.REVIEW, PaperStatus.FAILED},
    PaperStatus.REVIEW: {PaperStatus.REVISION, PaperStatus.COMPLETED, PaperStatus.FAILED},
    PaperStatus.REVISION: {PaperStatus.REVIEW, PaperStatus.COMPLETED, PaperStatus.FAILED},
    PaperStatus.COMPLETED: set(),
    PaperStatus.FAILED: {PaperStatus.IDEA},  # allow restart
}


def can_transition(current: PaperStatus, target: PaperStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())
