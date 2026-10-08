"""The run's stops and reruns (2026-10-06 review, P1).

* A review run again (deep revision, rerun from the review step) was scored
  from the reviewer files of the round before when a reviewer wrote nothing.
* The deep revision's round lived in memory only: a resume after a stop inside
  its re-review (the number check) ran the whole deep revision again.
* Approving output that failed its contract worked only in the initial phase,
  and a second contract stop forgot the researcher step to come back to.
* `e2er rerun` kept the approvals of the number check and the contract stops for
  the steps it runs again.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.pipeline.researcher import CONTRACT_STEP, apply_rerun
from src.core.pipeline.spec import find_spec
from src.core.pipeline.state import PipelineState
from src.core.specialists.base import set_aside_previous_outputs
from src.core.specialists.contracts import Contribution, WorkOrder
from src.core.specialists.dispatcher import ContractFailureError
from src.core.specialists.registry import REVIEWER_SPECIALISTS, SPECIALIST_REWRITES_OUTPUTS
from src.core.strategist.runner import GateHaltError, PipelineRunner
from src.core.strategist.state import PaperStatus
from tests.pipeline.integration.test_patch_revision_wiring import _review_file, _runner, _Verdict

PID = "11111111-2222-3333-4444-555555555555"


async def _noop(*a, **k):
    return None


# ── reviewers start from no file ─────────────────────────────────────────────


def test_reviewers_rewrite_their_files_whole():
    assert set(REVIEWER_SPECIALISTS) <= SPECIALIST_REWRITES_OUTPUTS


def test_a_reviewer_run_again_finds_no_review_of_the_round_before(tmp_path: Path):
    (tmp_path / "review_mechanism.md").write_text("OVERALL SCORE: 3.0/10\nRECOMMENDATION: Reject\n")
    order = WorkOrder(paper_id=PID, specialist="mechanism_reviewer", focus="review", output_file="review_mechanism.md")
    moved = set_aside_previous_outputs(tmp_path, order)
    assert moved == [("review_mechanism.md", ".history/review_mechanism.md.1")]
    assert not (tmp_path / "review_mechanism.md").exists()
    # A second round keeps the first one's file too, under the next number.
    (tmp_path / "review_mechanism.md").write_text("OVERALL SCORE: 6.0/10\n")
    assert set_aside_previous_outputs(tmp_path, order) == [("review_mechanism.md", ".history/review_mechanism.md.2")]
    assert (tmp_path / ".history" / "review_mechanism.md.1").read_text().startswith("OVERALL SCORE: 3.0")


def test_only_each_reviewers_latest_reply_can_stand_in_for_its_file(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    old = Contribution(
        paper_id=PID, specialist="mechanism_reviewer", output="OVERALL SCORE: 3.0/10\nRECOMMENDATION: Reject"
    )
    new = Contribution(paper_id=PID, specialist="mechanism_reviewer", output="I could not finish.", success=False)
    runner._contributions = [old, new]
    assert runner._read_review_scores() == []  # the round before never scores this one
    runner._contributions = [old]
    assert [s.reviewer for s in runner._read_review_scores()] == ["mechanism_reviewer"]


# ── the deep revision's round is in the state file ───────────────────────────


def _with_state(runner: PipelineRunner) -> PipelineState:
    st = PipelineState(paper_id=runner._paper_id, mode="single_pass")
    runner._state = st
    return st


@pytest.mark.asyncio
async def test_a_stop_in_the_deep_revisions_review_is_kept_in_the_state(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    st = _with_state(runner)
    _review_file(runner._workspace, "mechanism_reviewer", 3.0, "Reject")

    async def _ok(work_order, *a, **k):
        return Contribution(paper_id=runner._paper_id, specialist=work_order.specialist, output="ok", success=True)

    async def _number_check_stops():
        raise GateHaltError("number_check", ["tab:main row 1: the table says 1.2, the results say 1.3"])

    with (
        patch("src.core.strategist.runner.aggregate_reviews", side_effect=lambda _s: _Verdict("MECHANISM_FAIL", 3.0)),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_ok),
        patch.object(runner, "_run_review_phase", new=_number_check_stops),
        patch("src.db.client.execute", new=_noop),
        pytest.raises(GateHaltError),
    ):
        await runner._run_revision_phase(PaperStatus.REVIEW)
    saved = json.loads((runner._workspace / ".pipeline_state.json").read_text())
    assert saved["metadata"]["deep_revision"] == {"round": 1, "step": "review"}
    assert st.metadata["deep_revision"]["step"] == "review"


@pytest.mark.asyncio
async def test_a_resume_after_that_stop_runs_the_review_again_not_the_deep_revision(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    st = _with_state(runner)
    st.metadata["deep_revision"] = {"round": 1, "step": "review"}
    _review_file(runner._workspace, "mechanism_reviewer", 3.0, "Reject")  # the round before's review
    dispatched: list[str] = []
    reviews = 0

    async def _capture(work_order, *a, **k):
        dispatched.append(work_order.specialist)
        return Contribution(paper_id=runner._paper_id, specialist=work_order.specialist, output="ok", success=True)

    async def _review():
        nonlocal reviews
        reviews += 1
        return PaperStatus.REVIEW

    with (
        patch("src.core.strategist.runner.aggregate_reviews", side_effect=lambda _s: _Verdict("MECHANISM_FAIL", 3.0)),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch.object(runner, "_run_review_phase", new=_review),
        patch("src.db.client.execute", new=_noop),
    ):
        result = await runner._run_revision_phase(PaperStatus.REVIEW)
    assert result == PaperStatus.COMPLETED
    assert reviews == 1  # the re-review that the stop interrupted
    assert not {"data_analyst", "econometrics_specialist", "section_writer"} & set(dispatched)
    assert runner._deep_revision_count == 1
    assert st.metadata["deep_revision"] == {"round": 1, "step": "done"}


@pytest.mark.asyncio
async def test_a_finished_deep_revision_is_not_repeated_on_a_resume(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    st = _with_state(runner)
    st.metadata["deep_revision"] = {"round": 1, "step": "done"}
    _review_file(runner._workspace, "mechanism_reviewer", 3.0, "Reject")
    dispatched: list[str] = []

    async def _capture(work_order, *a, **k):
        dispatched.append(work_order.specialist)
        return Contribution(paper_id=runner._paper_id, specialist=work_order.specialist, output="ok", success=True)

    with (
        patch("src.core.strategist.runner.aggregate_reviews", side_effect=lambda _s: _Verdict("MECHANISM_FAIL", 3.0)),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture),
        patch("src.db.client.execute", new=_noop),
    ):
        assert await runner._run_revision_phase(PaperStatus.REVIEW) == PaperStatus.COMPLETED
    assert dispatched == []


# ── contract stops outside the initial phase ─────────────────────────────────


def _bare_runner(tmp_path: Path, st: PipelineState) -> PipelineRunner:
    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id, r._workspace, r._mode, r._spec = PID, tmp_path, "single_pass", find_spec("empirical")
    r._state, r._contributions, r._current_step = st, [], "revision"
    r._update_status = _noop
    return r


def _failure(specialist: str) -> dict:
    return {
        "specialist": specialist,
        "order": {"paper_id": PID, "specialist": specialist, "focus": "patch the draft"},
        "attempts": [{"attempt": 1, "error": "x", "violations": ["paper_draft.tex: too short"]}],
        "files": ["paper_draft.tex"],
    }


@pytest.mark.asyncio
async def test_an_approved_output_in_the_revision_is_kept_on_resume(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("src.db.events.log_event", _noop)
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.metadata["contract_pause"] = {"phase": "revision", "failed": [_failure("patch_revisor")], "succeeded": []}
    st.pending_review_stage = CONTRACT_STEP
    st.approve(CONTRACT_STEP)
    r = _bare_runner(tmp_path, st)
    await r._settle_contract(st)
    assert st.metadata["contract_accepted_skip"] == [{"phase": "revision", "specialist": "patch_revisor"}]

    async def _must_not_run(orders):
        raise AssertionError(f"ran again: {[o.specialist for o in orders]}")

    r._dispatch_orders = _must_not_run
    got = await r._execute_orders([WorkOrder(paper_id=PID, specialist="patch_revisor", focus="patch it again")])
    assert [c.specialist for c in got] == ["patch_revisor"] and got[0].success
    assert "contract_accepted_skip" not in st.metadata  # used once
    # The next dispatch of the specialist runs it as usual.
    ran: list[str] = []

    async def _run(orders):
        ran.extend(o.specialist for o in orders)
        return []

    r._dispatch_orders = _run
    await r._execute_orders([WorkOrder(paper_id=PID, specialist="patch_revisor", focus="later")])
    assert ran == ["patch_revisor"]


def test_an_unused_approval_lapses_when_its_phase_ends(tmp_path: Path):
    st = PipelineState(paper_id=PID, mode="iterative")
    st.metadata["contract_accepted_skip"] = [
        {"phase": "iterative", "specialist": "data_analyst"},
        {"phase": "revision", "specialist": "patch_revisor"},
    ]
    r = _bare_runner(tmp_path, st)
    r._drop_accepted_skips("iterative")
    assert st.metadata["contract_accepted_skip"] == [{"phase": "revision", "specialist": "patch_revisor"}]


@pytest.mark.asyncio
async def test_a_second_contract_stop_keeps_the_step_to_come_back_to(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("src.db.events.log_event", _noop)
    st = PipelineState(paper_id=PID, mode="single_pass")
    # The first stop came from a send-back at the draft review; it is being settled.
    st.metadata["contract_pause"] = {
        "phase": "revision",
        "failed": [_failure("patch_revisor")],
        "succeeded": [],
        "return_to": "review_draft",
    }
    st.pending_review_stage = CONTRACT_STEP
    r = _bare_runner(tmp_path, st)
    c = Contribution(paper_id=PID, specialist="patch_revisor", output="", success=False)
    await r._stop_for_contract(ContractFailureError([_failure("patch_revisor")], [c]), st)
    assert st.metadata["contract_pause"]["return_to"] == "review_draft"
    assert st.pending_review_stage == CONTRACT_STEP


# ── e2er rerun withdraws the approvals at the checks it runs again ──────────


def _approved_state() -> PipelineState:
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["initial", "estimation_gate", "review", "revision", "replication"]
    st.last_status = "completed"
    st.metadata = {
        "numbers_accepted": ["tab:main, row 2, col 2|41.20|s.json.kbe.mean"],
        "numbers_patch_tried": ["x"],
        "contract_accepted_orders": ["data_analyst\nload"],
        "contract_accepted_skip": [{"phase": "revision", "specialist": "patch_revisor"}],
        "deep_revision": {"round": 1, "step": "done"},
    }
    return st


def test_a_rerun_from_the_review_withdraws_the_number_check_approvals(tmp_path: Path):
    st = _approved_state()
    apply_rerun(tmp_path, st, find_spec("empirical"), "review", "Check the tables again.")
    for key in ("numbers_accepted", "numbers_patch_tried", "contract_accepted_skip", "deep_revision"):
        assert key not in st.metadata, key
    assert st.metadata["contract_accepted_orders"] == ["data_analyst\nload"]  # the initial phase is not rerun


def test_a_rerun_from_the_start_withdraws_every_approval(tmp_path: Path):
    st = _approved_state()
    apply_rerun(tmp_path, st, find_spec("empirical"), "initial", "Start over with the FRED series.")
    assert "contract_accepted_orders" not in st.metadata and "numbers_accepted" not in st.metadata


def test_a_rerun_of_the_replication_step_keeps_the_earlier_approvals(tmp_path: Path):
    st = _approved_state()
    apply_rerun(tmp_path, st, find_spec("empirical"), "replication", "Package it again.")
    assert st.metadata["numbers_accepted"] and st.metadata["contract_accepted_orders"]
    assert st.metadata["deep_revision"] == {"round": 1, "step": "done"}
