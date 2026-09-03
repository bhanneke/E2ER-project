"""Reviewers must deliver their review by WRITING it (canary #4, 2026-08-25).

Five of six reviewers returned `tools_called=0` and emitted the review as reply
text instead of writing `review_*.md`. The retry recovered all five, but each
wasted attempt cost ~90k tokens (~440k of a 4.67M-token run), and — the part
that actually degrades output — a reviewer with no FILE leaves
`_referee_feedback_text` nothing to hand the deep-revision round and ships an
export bundle with no referee report.

The score itself was never lost: `_read_review_scores` salvages it from the
reply text. That fallback is why this defect stayed invisible, so the second
half of these tests makes a salvaged panel visible in the artifact.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from src.core.specialists.base import _build_user_prompt, _translate_tool_names_for_cli
from src.core.specialists.contracts import WorkOrder
from src.core.strategist.review_aggregator import AggregationResult, ReviewScore
from src.core.strategist.runner import PipelineRunner


def _reviewer_prompt(specialist: str = "mechanism_reviewer") -> str:
    return _build_user_prompt(
        WorkOrder(
            paper_id=str(uuid.uuid4()),
            specialist=specialist,
            focus="Review the mechanism.",
            context="THE FULL DRAFT",
            output_file="review_mechanism.md",
        )
    )


# ── the prompt ───────────────────────────────────────────────────────────────


def test_reviewer_is_told_the_write_call_is_still_required():
    """The block's only tool guidance used to be prohibitive ("do NOT call
    read_file or list_directory"), which reads as "don't use tools"."""
    p = _reviewer_prompt()
    assert "You MUST still call write_file" in p
    assert "ONLY tool restriction" in p


def test_reviewer_is_told_that_a_reply_is_not_a_delivery():
    """The failure mode was a complete, high-quality review delivered to the
    wrong channel. Name that outcome as a failure."""
    p = _reviewer_prompt()
    assert "FAILED invocation" in p
    assert "never reads your reply" in p


def test_closing_format_is_scoped_to_the_file_not_the_reply():
    """ "Your review file MUST end with these two lines" was satisfiable by
    ending the REPLY with them — which is exactly what the model did."""
    p = _reviewer_prompt()
    assert "write INTO the file" in p
    assert "not\non your reply" in p or "not on your reply" in p


def test_the_read_restriction_survives():
    """Reviewers get the draft pre-loaded; re-reading it is quadratic. The fix
    must not trade one waste for another."""
    p = _reviewer_prompt()
    assert "Do NOT call read_file or list_directory" in p


def test_the_write_requirement_survives_cli_translation():
    """CLI backends see `Write`, not `write_file`. The canary ran on claude_code,
    so an instruction that only reads correctly under the SDK is no fix."""
    translated = _translate_tool_names_for_cli(_reviewer_prompt())
    assert "You MUST still call Write" in translated
    assert "write_file" not in translated


def test_non_reviewers_are_unaffected():
    p = _build_user_prompt(
        WorkOrder(
            paper_id=str(uuid.uuid4()),
            specialist="data_analyst",
            focus="Analyse.",
            output_file="data_summary.md",
        )
    )
    assert "FAILED invocation" not in p
    assert "Required Output" in p


# ── panel composition in the artifact ────────────────────────────────────────


def _runner(tmp_path: Path) -> PipelineRunner:
    paper_id = str(uuid.uuid4())
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    return PipelineRunner(
        paper_id=paper_id, workspace=ws, backend=None, model="mock", mode="single_pass", backend_name="mock"
    )


def _result(scores: list[ReviewScore]) -> AggregationResult:
    return AggregationResult(
        verdict="HARD_REJECT", weighted_avg=2.0, rule_triggered="Rule 2", scores=scores, rationale="because"
    )


def _written(runner: PipelineRunner) -> dict:
    return json.loads((runner._workspace / "review_aggregation.json").read_text())


def test_aggregation_artifact_records_panel_completeness(tmp_path):
    """A verdict from two reviewers and one from six used to be identical here.
    The shortfall existed only as a log warning, which no reader of the bundle
    ever sees."""
    runner = _runner(tmp_path)
    runner._write_review_aggregation(
        _result([ReviewScore(reviewer="mechanism_reviewer", score=2.0, recommendation="reject")])
    )
    panel = _written(runner)["panel"]
    assert panel["reported"] == 1
    assert panel["expected"] > 1
    assert panel["complete"] is False
    assert "technical_reviewer" in panel["missing"]


def test_aggregation_artifact_flags_a_score_with_no_review_file(tmp_path):
    """A salvaged score counts toward the verdict but leaves no report for the
    revision round — the artifact must say so."""
    runner = _runner(tmp_path)
    salvaged = ReviewScore(reviewer="writing_reviewer", score=6.0, recommendation="minor_revision")
    salvaged.source = "transcript"
    runner._write_review_aggregation(
        _result([ReviewScore(reviewer="mechanism_reviewer", score=7.0, recommendation="accept"), salvaged])
    )
    panel = _written(runner)["panel"]
    assert panel["scored_without_a_review_file"] == ["writing_reviewer"]
    by_reviewer = {s["reviewer"]: s["source"] for s in panel["scores"]}
    assert by_reviewer["writing_reviewer"] == "transcript"
    assert by_reviewer["mechanism_reviewer"] == "file"


def test_a_full_clean_panel_says_so(tmp_path):
    from src.core.specialists.registry import REVIEWER_SPECIALISTS

    runner = _runner(tmp_path)
    runner._write_review_aggregation(
        _result([ReviewScore(reviewer=r, score=7.0, recommendation="accept") for r in REVIEWER_SPECIALISTS])
    )
    panel = _written(runner)["panel"]
    assert panel["complete"] is True
    assert panel["missing"] == []
    assert panel["scored_without_a_review_file"] == []


def test_the_verdict_fields_are_unchanged(tmp_path):
    """Panel data is additive — existing consumers must not break."""
    runner = _runner(tmp_path)
    runner._write_review_aggregation(
        _result([ReviewScore(reviewer="mechanism_reviewer", score=2.0, recommendation="reject")])
    )
    d = _written(runner)
    assert d["verdict"] == "HARD_REJECT"
    assert d["weighted_avg"] == 2.0
    assert d["rule_triggered"] == "Rule 2"
    assert d["rationale"] == "because"


def test_salvaged_scores_are_marked_when_read_from_contributions(tmp_path):
    """The fallback that hid this defect now labels what it did."""
    from src.core.specialists.contracts import Contribution

    runner = _runner(tmp_path)
    runner._contributions.append(
        Contribution(
            paper_id=runner._paper_id,
            specialist="writing_reviewer",
            output="Solid.\n\nOVERALL SCORE: 6/10\nRECOMMENDATION: Minor Revision\n",
            success=False,
        )
    )
    scores = runner._read_review_scores()
    assert [s.reviewer for s in scores] == ["writing_reviewer"]
    assert scores[0].source == "transcript"


def test_scores_read_from_a_real_file_are_marked_file(tmp_path):
    runner = _runner(tmp_path)
    (runner._workspace / "review_writing.md").write_text(
        "Solid.\n\nOVERALL SCORE: 6/10\nRECOMMENDATION: Minor Revision\n"
    )
    scores = runner._read_review_scores()
    assert [s.reviewer for s in scores] == ["writing_reviewer"]
    assert scores[0].source == "file"
