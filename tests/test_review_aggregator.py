"""Tests for the mechanical 3-rule review aggregation."""

from src.core.strategist.review_aggregator import (
    ReviewScore,
    aggregate_reviews,
    parse_review_output,
)


def _score(reviewer: str, score: float) -> ReviewScore:
    return ReviewScore(reviewer=reviewer, score=score, recommendation="major_revision")


def test_mechanism_fail_triggers_rule1():
    scores = [
        _score("mechanism_reviewer", 4.0),
        _score("technical_reviewer", 8.0),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "MECHANISM_FAIL"
    assert "Rule 1" in result.rule_triggered


def test_hard_reject_triggers_rule2():
    scores = [
        _score("mechanism_reviewer", 6.0),
        _score("technical_reviewer", 3.5),  # below 4
        _score("writing_reviewer", 7.0),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "HARD_REJECT"
    assert "Rule 2" in result.rule_triggered


def test_accept_via_weighted_average():
    scores = [
        _score("mechanism_reviewer", 8.5),
        _score("technical_reviewer", 9.0),
        _score("writing_reviewer", 8.0),
        _score("literature_reviewer", 7.5),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "ACCEPT"
    assert result.weighted_avg >= 8.0


def test_technical_reviewer_has_higher_weight():
    scores = [
        _score("mechanism_reviewer", 6.5),
        _score("technical_reviewer", 8.5),  # 1.5x weight pulls average up
    ]
    result = aggregate_reviews(scores)
    # technical gets 1.5x weight: (6.5*1 + 8.5*1.5) / 2.5 = 7.9
    assert result.weighted_avg > 7.5


def test_major_revision_range():
    scores = [
        _score("mechanism_reviewer", 6.0),
        _score("technical_reviewer", 5.5),
        _score("writing_reviewer", 6.0),
    ]
    result = aggregate_reviews(scores)
    assert result.verdict == "MAJOR_REVISION"


# ---------------------------------------------------------------------------
# parse_review_output — handles the four formats observed in real Sonnet
# reviewer output (May 2026 NFT-paper run #6). Before the parser rewrite,
# only the canonical `OVERALL SCORE: N/10` matched; markdown bold inside
# the score line, bare dimension lists, and bold-wrapped overall lines all
# silently returned None, so only 1 of 6 reviewers' scores entered the
# weighted aggregation.
# ---------------------------------------------------------------------------


def test_parse_canonical_overall_score():
    """The format the skill mandates: clean `OVERALL SCORE: N/10` line."""
    raw = "Body of review here.\n\nOVERALL SCORE: 7.5/10\nRECOMMENDATION: Minor Revision"
    s = parse_review_output("technical_reviewer", raw)
    assert s is not None
    assert s.score == 7.5
    assert s.recommendation == "minor_revision"


def test_parse_bold_wrapped_overall_score():
    """literature_reviewer-style: markdown bold around the whole line."""
    raw = "Some body.\n\n**OVERALL SCORE: 6.2/10**\n**RECOMMENDATION: Major Revision**"
    s = parse_review_output("literature_reviewer", raw)
    assert s is not None
    assert s.score == 6.2


def test_parse_weighted_overall_with_colon_bold():
    """mechanism_reviewer-style: `**Weighted overall score:** 5.6/10`.
    Old parser failed here because `:**` between colon and digit isn't
    whitespace; new parser tolerates up to 15 non-digit chars."""
    raw = "Body of mechanism review.\n\n**Weighted overall score:** 5.6/10\nMajor revision needed."
    s = parse_review_output("mechanism_reviewer", raw)
    assert s is not None
    assert s.score == 5.6


def test_parse_dimension_scores_averaged_when_no_overall():
    """Reviewer who lists dimensions but no overall — average the dimensions.
    Real mechanism_reviewer output sometimes does this."""
    raw = (
        "## DIMENSION SCORES\n"
        "- Contribution: 6/10\n"
        "- Identification: 6.5/10\n"
        "- Empirics: 7/10\n"
        "- Writing: 7/10\n"
        "- Literature: 5.5/10\n"
        "\n## MAJOR CONCERNS\n- foo\n"
    )
    s = parse_review_output("mechanism_reviewer", raw)
    assert s is not None
    # Average of 6, 6.5, 7, 7, 5.5 = 6.4
    assert 6.3 < s.score < 6.5


def test_parse_lone_n_over_10_fallback():
    """Last-resort fallback: reviewer just wrote `7/10` somewhere."""
    raw = "Long discursive review. I'd give this a 7/10 overall, frankly. Lots to say."
    s = parse_review_output("data_reviewer", raw)
    assert s is not None
    assert s.score == 7.0


def test_parse_returns_none_when_no_score():
    """A review with no number on a 0-10 scale anywhere should be None,
    not a default — the aggregator's partial-review warning relies on this."""
    raw = "This paper has issues with identification and the model setup. No score given here."
    s = parse_review_output("identification_reviewer", raw)
    assert s is None


def test_parse_clamps_to_0_10_range():
    """A model that hallucinates a 12/10 score gets clamped."""
    raw = "OVERALL SCORE: 12/10\nRECOMMENDATION: Accept"
    s = parse_review_output("technical_reviewer", raw)
    assert s is not None
    assert s.score == 10.0


def test_parse_prefers_overall_over_dimension():
    """When both a dimension section AND an overall line exist, prefer overall."""
    raw = "## DIMENSION SCORES\n- Contribution: 5/10\n- Empirics: 5/10\n\nOVERALL SCORE: 7.5/10\n"
    s = parse_review_output("technical_reviewer", raw)
    assert s is not None
    assert s.score == 7.5  # not the dimension average of 5


def test_parse_recommendation_extracted():
    """Recommendation falls back to major_revision when absent, else extracted."""
    raw_accept = "OVERALL SCORE: 8.5/10\nRECOMMENDATION: Accept"
    assert parse_review_output("technical_reviewer", raw_accept).recommendation == "accept"

    raw_reject = "OVERALL SCORE: 3.0/10\nRECOMMENDATION: Reject"
    assert parse_review_output("technical_reviewer", raw_reject).recommendation == "reject"

    raw_no_rec = "OVERALL SCORE: 6.0/10"
    assert parse_review_output("technical_reviewer", raw_no_rec).recommendation == "major_revision"


def test_reviewer_user_prompt_contains_mandatory_closing_format():
    """Reviewer work-orders must explicitly require the parser's closing
    format. Discovered May 2026 NFT-paper run #7: 4 of 6 reviewers ignored
    the skill's mandate and ended with prose conclusions, so their reviews
    couldn't be aggregated. The fix is to repeat the requirement in the
    work-order focus so the model sees it twice (skill + dispatch).
    """
    from src.core.specialists.base import _build_user_prompt
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.registry import REVIEWER_SPECIALISTS

    for reviewer in REVIEWER_SPECIALISTS:
        wo = WorkOrder(
            paper_id="test-id",
            specialist=reviewer,
            focus="Review the paper.",
            context_tier=2,
        )
        prompt = _build_user_prompt(wo)
        assert "OVERALL SCORE:" in prompt, (
            f"{reviewer} work-order prompt missing the parser-required "
            f"`OVERALL SCORE:` line. Without it, the model writes prose-only "
            f"reviews that fail aggregation."
        )
        assert "RECOMMENDATION:" in prompt, f"{reviewer} prompt missing RECOMMENDATION line"
        # Non-reviewers should NOT get this block (no scoring expected).
    from src.core.specialists.registry import POLISH_SPECIALISTS

    for non_reviewer in ["idea_developer", "paper_drafter", *POLISH_SPECIALISTS]:
        wo = WorkOrder(
            paper_id="test-id",
            specialist=non_reviewer,
            focus="Do your work.",
            context_tier=2,
        )
        prompt = _build_user_prompt(wo)
        assert "OVERALL SCORE:" not in prompt, (
            f"{non_reviewer} work-order shouldn't contain the reviewer-only closing-format block"
        )


def test_runner_aggregation_prefers_disk_over_chat_summary(tmp_path, monkeypatch):
    """Run #8 regression: the runner's _run_revision_phase used to call
    parse_review_output on `c.output` (the LLM's chat-side summary) and
    only fell back to reading files on disk when ALL chat outputs were
    empty. Under the CLI backend, `c.output` is the CLI's final assistant
    message ("I've written the review."), which rarely contains the
    OVERALL SCORE line even when the *file* on disk does. Result: 4/6
    chat summaries parsed in run #8, the 2 with terse chat outputs were
    dropped, panel verdict computed from partial data.

    Fix: always read from disk first; fall back to chat summary only for
    reviewers whose file is missing. This test pins that ordering by
    setting up a disagreement — disk says 7/10, chat says 3/10 — and
    asserting the disk score wins.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from src.core.specialists.contracts import Contribution
    from src.core.strategist.runner import PipelineRunner
    from src.core.strategist.state import PaperStatus

    paper_id = "11111111-2222-3333-4444-555555555555"
    workspace = tmp_path / paper_id
    workspace.mkdir(parents=True)

    # Disk: mechanism_reviewer wrote a 7/10 review file.
    (workspace / "review_mechanism.md").write_text(
        "Comprehensive review body.\n\nOVERALL SCORE: 7/10\nRECOMMENDATION: Minor Revision\n"
    )
    # Chat-side summary from the same reviewer says 3/10 — disagreement.
    chat_summary = "OVERALL SCORE: 3/10\nRECOMMENDATION: Reject"

    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=MagicMock(),
        model="claude-test",
        mode="single_pass",
        backend_name="claude_code",
        max_cost_usd=10.0,
    )
    runner._contributions = [
        Contribution(
            paper_id=paper_id,
            specialist="mechanism_reviewer",
            output=chat_summary,
            output_file=str(workspace / "review_mechanism.md"),
            usage_tokens=100,
            cost_usd=0.0,
            duration_seconds=1.0,
            success=True,
        )
    ]

    # Stub out the DB / event side-effects we don't care about.
    monkeypatch.setattr("src.db.client.execute", AsyncMock())
    monkeypatch.setattr("src.db.events.log_event", AsyncMock())
    monkeypatch.setattr(runner, "_update_status", AsyncMock())

    asyncio.run(runner._run_revision_phase(PaperStatus.REVIEW))
    # Verdict was computed from the DISK score (7/10), not the chat (3/10).
    aggregation_path = workspace / "review_aggregation.json"
    assert aggregation_path.exists(), "aggregation should have been written"
    import json

    agg = json.loads(aggregation_path.read_text())
    # 7/10 = MINOR_REVISION; 3/10 would have been HARD_REJECT (Rule 2).
    assert agg["verdict"] in {"MINOR_REVISION", "MAJOR_REVISION"}, (
        f"verdict must be from the disk score (7/10), not the chat summary (3/10). "
        f"Got verdict={agg['verdict']}, breakdown={agg.get('rationale', '')}"
    )
    assert "mechanism_reviewer=7" in agg.get("rationale", ""), (
        f"breakdown should reflect disk score 7.0, not chat score 3.0; got {agg.get('rationale')}"
    )


def test_aggregator_picks_up_six_real_reviewers_from_run_6():
    """End-to-end: simulate the six review files from May 2026 NFT-paper
    run #6 with their actual observed formats. The old parser caught 1/6;
    the new one must catch at least 5/6 (data_reviewer in run #6 was
    legitimately empty due to a theoretical paper having no data)."""
    reviews = {
        "literature_reviewer": (
            "## DIMENSION SCORES\n- Contribution: 6.5/10\n\n**OVERALL SCORE: 6.2/10**\nRECOMMENDATION: Major Revision"
        ),
        "mechanism_reviewer": (
            "## DIMENSION SCORES\n- Contribution: **6/10**\n\n"
            "**Weighted overall score:** 5.6/10\n**Recommendation:** Major Revision"
        ),
        "technical_reviewer": (
            "## DIMENSION SCORES\n- Identification: 6/10\n- Empirics: 7/10\n(no overall line provided)"
        ),
        "writing_reviewer": "Long prose review. The paper scores about 7/10 in my view.",
        "identification_reviewer": "OVERALL SCORE: 7.0/10\nRECOMMENDATION: Major Revision",
        "data_reviewer": "Pure theory paper; no data to review.",
    }
    parsed = {r: parse_review_output(r, raw) for r, raw in reviews.items()}
    extracted = [(r, s) for r, s in parsed.items() if s is not None]
    assert len(extracted) >= 5, (
        f"Parser must extract >=5 of 6 real-world reviewer outputs; got "
        f"{[(r, s.score if s else None) for r, s in parsed.items()]}"
    )
    # data_reviewer is legitimately None (no data, no score).
    assert parsed["data_reviewer"] is None
