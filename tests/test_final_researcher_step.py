"""A template whose last step is a researcher step completes once that step is approved.

Regression, 2026-09-29: the replication run 08af321d was approved at its final
`review_report` step and resumed; every step was complete, finalize ran, but
the paper stayed `in_progress`, because the completion rule tested the state's
`last_status` for an empty value while its default is `in_progress`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.pipeline.spec import spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.strategist.state import PaperStatus

PID = "12345678-1234-1234-1234-123456789abc"


def _runner(ws: Path, spec, state: PipelineState, monkeypatch):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id, r._workspace, r._mode, r._spec = PID, ws, "single_pass", spec
    r._triggers, r._state, r._in_initial, r._contributions = [], state, False, []
    r._governance, r._failure_counts, r._last_specialist_errors = "full", {}, {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers, r._review_stages = [], [], set()
    r._max_cost_usd, r._pivot_count, r._iteration, r._deep_revision_count = 5.0, 0, 0, 0
    r._in_memory_spent = lambda: 0.0
    statuses: list[PaperStatus] = []
    finalized: list[bool] = []

    async def _status(status, error=None):
        statuses.append(status)

    async def _finalize():
        finalized.append(True)

    async def _noop(*a, **k):
        return None

    r._update_status = _status
    r._best_effort_finalize = _finalize
    monkeypatch.setattr("src.db.events.log_event", _noop)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget", _noop)
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.load", classmethod(lambda cls, *a: state))
    return r, statuses, finalized


def _spec():
    return spec_from_dict(
        {
            "name": "ends-with-a-review",
            "steps": [
                {"kind": "specialists", "name": "work", "run": ["replication_planner"]},
                {"kind": "researcher", "name": "review_final", "files": ["replication_plan.md"]},
            ],
        }
    )


async def test_approving_the_final_researcher_step_completes_and_finalizes(tmp_path: Path, monkeypatch):
    state = PipelineState(paper_id=PID, mode="single_pass")
    state.completed_stages = ["work"]
    state.pending_review_stage = None
    state.approve("review_final")
    assert state.last_status == "in_progress"  # the default the old rule missed
    r, statuses, finalized = _runner(tmp_path, _spec(), state, monkeypatch)
    out = await r.run()
    assert out["status"] == "completed"
    assert statuses[-1] == PaperStatus.COMPLETED and finalized == [True]
    assert state.is_complete("review_final") and state.last_status == "completed"


async def test_before_approval_the_run_stops_at_the_final_step(tmp_path: Path, monkeypatch):
    state = PipelineState(paper_id=PID, mode="single_pass")
    state.completed_stages = ["work"]
    r, statuses, _ = _runner(tmp_path, _spec(), state, monkeypatch)
    out = await r.run()
    assert out["status"] == "paused" and out["stage"] == "review_final"
    assert PaperStatus.COMPLETED not in statuses


@pytest.mark.parametrize("last", ["rejected", "failed"])
async def test_a_status_a_step_set_is_kept(tmp_path: Path, monkeypatch, last):
    state = PipelineState(paper_id=PID, mode="single_pass")
    state.completed_stages = ["work"]
    state.approve("review_final")
    state.last_status = last
    r, statuses, _ = _runner(tmp_path, _spec(), state, monkeypatch)
    out = await r.run()
    assert out["status"] == last
