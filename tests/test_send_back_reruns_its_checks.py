"""A specialist sent back from a researcher step: the checks that read its work run again.

The 2026-10-13 school-fee demo (policy evaluation): at the pre-registration the
researcher sent the data analyst back, the panel was rebuilt (8 treated countries
instead of 15, ending in 2010), and the design check that had passed on the old
panel was not run again, so its report described a panel that no longer existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.pipeline.researcher import apply_action
from src.core.pipeline.spec import find_spec
from src.core.strategist.state import HumanReviewRequestedError
from tests.test_replication_template import _runner, events  # noqa: F401


@pytest.fixture
def did_runner(monkeypatch, tmp_path: Path):
    r = _runner(tmp_path)
    r._spec = find_spec("policy-evaluation")
    r._triggers = [s for s in r._spec.steps if s.kind == "gate" and s.after]
    ran: list[str] = []
    checked: list[str] = []

    async def _exec(orders):
        ran.extend(o.specialist for o in orders)
        return []

    async def _gate(step, state, remaining):
        checked.append(step.name)
        state.mark_complete(step.name)

    monkeypatch.setattr(r, "_execute_orders", _exec)
    monkeypatch.setattr(r, "_run_gate_trigger", _gate)
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.save", lambda self, ws: None)
    r._state.mark_complete("did_design_gate")
    r._state.metadata["retried_did_design_gate"] = True
    r._state.pending_review_stage = "preregister"
    r._state.metadata["review"] = {"kind": "preregister", "files": ["preregistration.md"]}
    return r, ran, checked


async def _settle(r) -> None:
    try:
        await r._settle_researcher_decisions(r._state)
    except HumanReviewRequestedError:
        pass  # back at the pre-registration, as before


@pytest.mark.parametrize("specialist", ["data_analyst", "data_architect", "identification_strategist"])
async def test_the_design_check_runs_again_on_the_new_work(did_runner, events, specialist):  # noqa: F811
    r, ran, checked = did_runner
    apply_action(r._workspace, r._state, {"action": "send_back", "step": specialist, "remark": "Rebuild."})
    await _settle(r)
    assert ran == [specialist]
    assert checked == ["did_design_gate"]
    assert "retried_did_design_gate" not in r._state.metadata  # the new work gets its own retry


async def test_a_specialist_no_check_reads_runs_alone(did_runner, events):  # noqa: F811
    r, ran, checked = did_runner
    apply_action(r._workspace, r._state, {"action": "send_back", "step": "literature_scanner", "remark": "More."})
    await _settle(r)
    assert ran == ["literature_scanner"] and checked == []


async def test_a_check_that_has_not_run_is_left_to_the_dispatch(did_runner, events):  # noqa: F811
    r, ran, checked = did_runner
    r._state.completed_stages = [c for c in r._state.completed_stages if c != "did_design_gate"]
    apply_action(r._workspace, r._state, {"action": "send_back", "step": "data_analyst", "remark": "Rebuild."})
    await _settle(r)
    assert ran == ["data_analyst"] and checked == []
