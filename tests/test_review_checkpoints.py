"""Human-in-the-loop review checkpoints (WS-P3.1).

The run pauses after a researcher-chosen stage (status=PAUSED,
`awaiting_review` event); resuming approves the pending stage and continues.
Built on the existing pause/resume machinery + .pipeline_state.json.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

from src.core.pipeline.state import PipelineState
from src.core.strategist.state import PIPELINE_STAGES, HumanReviewRequestedError

# ── PipelineState: approval + backward-compatible persistence ────────────────


def test_state_new_fields_default_empty():
    s = PipelineState(paper_id="p", mode="single_pass")
    assert s.approved_stages == []
    assert s.pending_review_stage is None


def test_state_approve_clears_pending():
    s = PipelineState(paper_id="p", mode="single_pass")
    s.pending_review_stage = "initial"
    s.approve("initial")
    assert s.is_approved("initial")
    assert s.pending_review_stage is None
    s.approve("initial")  # idempotent
    assert s.approved_stages == ["initial"]


def test_state_round_trips_checkpoint_fields(tmp_path: Path):
    s = PipelineState(paper_id="p", mode="single_pass")
    s.mark_complete("initial")
    s.pending_review_stage = "initial"
    s.save(tmp_path)
    loaded = PipelineState.load(tmp_path, "p", "single_pass")
    assert loaded.is_complete("initial")
    assert loaded.pending_review_stage == "initial"


def test_state_loads_legacy_file_without_new_keys(tmp_path: Path):
    # A state file written by an older version lacks approved_stages /
    # pending_review_stage — it must still load, with defaults.
    (tmp_path / ".pipeline_state.json").write_text(
        '{"paper_id": "p", "mode": "single_pass", "completed_stages": ["initial"]}'
    )
    loaded = PipelineState.load(tmp_path, "p", "single_pass")
    assert loaded.completed_stages == ["initial"]
    assert loaded.approved_stages == []
    assert loaded.pending_review_stage is None


# ── the pause decision ───────────────────────────────────────────────────────


def _bare_runner(review_stages):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._review_stages = set(review_stages)
    return r


def test_should_pause_only_at_requested_unapproved_stage():
    r = _bare_runner({"initial"})
    state = PipelineState(paper_id="p", mode="single_pass")
    assert r._should_pause_for_review("initial", state) is True
    assert r._should_pause_for_review("review", state) is False  # not requested
    state.approve("initial")
    assert r._should_pause_for_review("initial", state) is False  # already approved


def test_human_review_exception_carries_stage():
    e = HumanReviewRequestedError("review")
    assert e.stage == "review"
    assert "review" in str(e)


def test_pipeline_stages_are_the_real_runner_stages():
    for s in ("initial", "estimation_gate", "review", "replication"):
        assert s in PIPELINE_STAGES


# ── request model ────────────────────────────────────────────────────────────


def test_request_review_stages_defaults_empty():
    from src.api.app import CreatePaperRequest

    req = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q"})
    assert req.review_stages == []
    req2 = CreatePaperRequest.model_validate(
        {"title": "T", "research_question": "Q", "review_stages": ["initial", "review"]}
    )
    assert req2.review_stages == ["initial", "review"]


# ── end-to-end: pause after `initial`, then resume to completion ─────────────


async def test_pause_then_resume_cycle(tmp_path: Path, monkeypatch):
    from src.core.strategist.runner import PipelineRunner
    from src.core.strategist.state import PaperStatus

    monkeypatch.setattr("src.modules.tracking.usage.check_budget", AsyncMock())
    monkeypatch.setattr("src.db.events.log_event", AsyncMock())

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id = "p"
    r._workspace = tmp_path
    r._mode = "single_pass"
    r._review_stages = {"initial"}
    r._contributions = []
    r._iteration = 0
    r._pivot_count = 0
    r._max_cost_usd = 100.0
    r._governance = "full"
    r._methodology = "empirical"
    # Mock the phase bodies + finalization; we're testing control flow only.
    r._run_initial_phase = AsyncMock()
    r._enforce_estimation_gate = AsyncMock()
    r._run_review_phase = AsyncMock(return_value=PaperStatus.REVIEW)
    r._run_revision_phase = AsyncMock(return_value=PaperStatus.COMPLETED)
    r._run_replication_phase = AsyncMock()
    r._update_status = AsyncMock()
    r._best_effort_finalize = AsyncMock()
    r._in_memory_spent = Mock(return_value=0.0)

    # Run 1 — pauses right after `initial`, before reaching review.
    result1 = await r.run()
    assert result1 == {"status": "paused", "reason": "awaiting_review", "stage": "initial"}
    st = PipelineState.load(tmp_path, "p", "single_pass")
    assert st.is_complete("initial") and st.pending_review_stage == "initial"
    assert r._run_review_phase.await_count == 0  # downstream never ran
    assert r._run_initial_phase.await_count == 1

    # Simulate the resume endpoint approving the pending checkpoint.
    st.approve("initial")
    st.save(tmp_path)

    # Run 2 — initial is skipped (complete), no re-pause, runs to completion.
    result2 = await r.run()
    assert result2["status"] != "paused"
    assert r._run_initial_phase.await_count == 1  # NOT re-run
    assert r._run_review_phase.await_count == 1  # reached this time


async def test_no_review_stages_never_pauses(tmp_path: Path, monkeypatch):
    from src.core.strategist.runner import PipelineRunner
    from src.core.strategist.state import PaperStatus

    monkeypatch.setattr("src.modules.tracking.usage.check_budget", AsyncMock())
    monkeypatch.setattr("src.db.events.log_event", AsyncMock())

    r = PipelineRunner.__new__(PipelineRunner)
    for k, v in {
        "_paper_id": "p",
        "_workspace": tmp_path,
        "_mode": "single_pass",
        "_review_stages": set(),
        "_contributions": [],
        "_iteration": 0,
        "_pivot_count": 0,
        "_max_cost_usd": 100.0,
        "_governance": "full",
        "_methodology": "empirical",
    }.items():
        setattr(r, k, v)
    r._run_initial_phase = AsyncMock()
    r._enforce_estimation_gate = AsyncMock()
    r._run_review_phase = AsyncMock(return_value=PaperStatus.REVIEW)
    r._run_revision_phase = AsyncMock(return_value=PaperStatus.COMPLETED)
    r._run_replication_phase = AsyncMock()
    r._update_status = AsyncMock()
    r._best_effort_finalize = AsyncMock()
    r._in_memory_spent = Mock(return_value=0.0)

    result = await r.run()
    assert result["status"] != "paused"
