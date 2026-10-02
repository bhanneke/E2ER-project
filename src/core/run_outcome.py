"""A run's outcome in plain words: whether it finished, and, separately, its internal quality review score.

e2er's internal quality review gives a score, nothing else. Six reviewer
specialists each score the draft from one angle (data, identification,
literature, mechanism, technical, writing) on a scale of 0 to 10, and the
combined score is their weighted average (``review_aggregator._WEIGHTS``). The
score decides whether a revision round runs; it never decides whether the run
counts as finished.

The status of a run says only that:

* ``completed`` — every step ran (whatever the score);
* ``stopped``   — a check stopped the run before it finished. The database
  stores this as ``rejected`` (``PaperStatus.REJECTED``), an internal code
  that is never shown;
* ``failed``, ``cancelled``, ``paused`` and the in-progress phases as stored.

Runs of e2er 0.13.1 and earlier also stored ``rejected`` when the internal
quality review scored low, after the run had finished all its steps. Such a
run has the review's file (``review_aggregation.json``); :func:`effective_status`
reads it as ``completed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Stored statuses that name a review result instead of whether the run finished.
#: Internal codes: read through :func:`effective_status`, never shown.
REVIEW_RESULT_STATUSES = frozenset(
    {
        "rejected",
        "accepted",
        "accept",
        "reject",
        "hard_reject",
        "major_revision",
        "minor_revision",
        "mechanism_fail",
    }
)

#: The words shown for a status. Anything else is shown with ``_`` as a space.
STATUS_WORDS = {
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "paused": "paused",
    "stopped": "stopped by a check",
    "in_progress": "in progress",
    "data_approval": "waiting for data approval",
}

#: The name of the review in visible text.
REVIEW_NAME = "internal quality review"

#: The file the run writes after the internal quality review.
AGGREGATION_FILE = "review_aggregation.json"


def effective_status(stored: str | None, reviewed: bool) -> str:
    """The status to show and to publish for a stored one.

    ``reviewed``: the run reached its internal quality review (its
    ``review_aggregation.json`` exists). A stored ``rejected`` is then a run
    that finished with a low score (``completed``); without the review, a check
    stopped it (``stopped``). Any other review word is ``completed``.
    """
    s = (stored or "").strip().lower()
    if s not in REVIEW_RESULT_STATUSES:
        return s
    if s == "rejected" and not reviewed:
        return "stopped"
    return "completed"


def status_words(status: str | None) -> str:
    """``stopped`` → ``stopped by a check``; a status as it is shown."""
    s = (status or "").strip().lower()
    return STATUS_WORDS.get(s, s.replace("_", " "))


def read_aggregation(*folders: Path | str | None) -> dict[str, Any] | None:
    """``review_aggregation.json`` from the first folder that has it (a workspace, or a bundle's ``reviews/``)."""
    for folder in folders:
        if not folder:
            continue
        for path in (Path(folder) / AGGREGATION_FILE, Path(folder) / "reviews" / AGGREGATION_FILE):
            try:
                if path.is_file():
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(doc, dict):
                        return doc
            except (OSError, ValueError):
                continue
    return None


def workspace_status(stored: str | None, workspace: Path | str | None) -> str:
    """:func:`effective_status` for a run whose workspace is at hand."""
    reviewed = bool(workspace) and (Path(str(workspace)) / AGGREGATION_FILE).is_file()
    return effective_status(stored, reviewed)


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def internal_review(agg: dict[str, Any] | None, rounds: int | None = None) -> dict[str, Any] | None:
    """The dossier's ``run.internal_review`` from a ``review_aggregation.json``.

    Shape::

        {"score": 6.11,                 # weighted average, 2 decimals
         "scale": 10,
         "combined": "weighted average",
         "reviewers": {"data_reviewer": 7.0, ...},   # each reviewer's score
         "weights": {"data_reviewer": 1.25, ...},    # its weight in the average
         "rounds": 1}                   # times the reviewers scored the draft

    ``reviewers`` and ``weights`` are present when the file lists the panel.
    ``score`` is the combined score exactly as the run computed it: when a
    reviewer's score alone decided (mechanism below 5, any reviewer below 4),
    the run's file records that score instead of an average, and ``combined``
    says which (``"mechanism score"``, ``"lowest reviewer score"``).
    Returns None when there is no file or no score in it.
    """
    if not agg:
        return None
    score = _num(agg.get("weighted_avg"))
    if score is None:
        return None
    rule = str(agg.get("rule_triggered") or "")
    if rule.startswith("Rule 1: mechanism_reviewer"):
        combined = "mechanism score"
    elif rule.startswith("Rule 2"):
        combined = "lowest reviewer score"
    else:
        combined = "weighted average"
    out: dict[str, Any] = {"score": round(score, 2), "scale": 10, "combined": combined}
    raw_panel = agg.get("panel")
    panel: dict[str, Any] = raw_panel if isinstance(raw_panel, dict) else {}
    rows = [r for r in (panel.get("scores") or []) if isinstance(r, dict) and r.get("reviewer")]
    if rows:
        out["reviewers"] = {str(r["reviewer"]): _num(r.get("score")) for r in rows}
        weights = {str(r["reviewer"]): _num(r.get("weight")) for r in rows if _num(r.get("weight")) is not None}
        if weights:
            out["weights"] = weights
        if panel.get("missing"):
            out["missing"] = sorted(str(m) for m in panel["missing"])
    n = agg.get("round") if isinstance(agg.get("round"), int) else rounds
    if isinstance(n, int) and n > 0:
        out["rounds"] = n
    return out


def score_words(score: float | None, *, short: bool = False) -> str:
    """``e2er's internal quality review: 6.1 of 10`` (one decimal)."""
    if score is None:
        return ""
    value = f"{score:.1f} of 10"
    return value if short else f"e2er's {REVIEW_NAME}: {value}"


def angle(reviewer: str) -> str:
    """``identification_reviewer`` → ``identification``: the angle a reviewer scores from."""
    return reviewer.removesuffix("_reviewer").replace("_", " ")


def review_detail(agg: dict[str, Any] | None) -> str:
    """``6.1 of 10 (weighted average): data 7.0, identification 4.0, …`` for a page or README."""
    review = internal_review(agg)
    if review is None:
        return ""
    head = f"{score_words(review['score'], short=True)} ({review['combined']})"
    reviewers = review.get("reviewers") or {}
    parts = [f"{angle(r)} {s:.1f}" for r, s in sorted(reviewers.items()) if isinstance(s, (int, float))]
    return head + (": " + ", ".join(parts) if parts else "")
