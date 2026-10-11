"""A send-back at a failed check reruns the specialist, then the check, and the run continues if it passes.

Before (template live runs, 2026-10-11): after sending a specialist back at a
check stop, the run stopped at the same check again and needed an approve
before the check ran. Now the check runs right after the specialist; the run
stops there again only when the check still fails. The dashboard's version is
pinned in tests/test_timeseries_template_replay.py (the forecast check);
this file pins the runner and `e2er review`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.cli_review import _post
from src.core.pipeline.researcher import apply_action
from src.core.strategist.state import HumanReviewRequestedError
from tests.test_replication_template import _fetched, _runner, events, workspace  # noqa: F401


def _stopped_at(r: Any, stage: str, kind: str) -> None:
    r._state.pending_review_stage = stage
    r._state.metadata["review"] = {"kind": kind, "files": [], "reasons": ["the check failed"]}


@pytest.fixture
def ran(monkeypatch, workspace: Path):  # noqa: F811
    """The runner with a fetched package, and the specialists' work recorded instead of run."""
    _fetched(workspace)  # the fetch check runs first at every start
    r = _runner(workspace)
    log: list[str] = []

    async def _exec(orders):
        log.extend(o.specialist for o in orders)
        return []

    monkeypatch.setattr(r, "_execute_orders", _exec)
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.save", lambda self, ws: None)
    return r, log


async def test_a_send_back_at_a_check_runs_the_specialist_and_does_not_stop_there_again(ran, workspace: Path, events):  # noqa: F811
    r, log = ran
    _stopped_at(r, "sandbox_run", "gate")
    payload = apply_action(
        workspace,
        r._state,
        {"action": "send_back", "step": "replication_planner", "remark": "Pin the R version."},
    )
    assert payload["then"] == "check_runs_again"
    await r._settle_researcher_decisions(r._state)  # no HumanReviewRequestedError: no stop before the check
    assert log == ["replication_planner"]
    assert r._state.pending_review_stage is None and "review" not in r._state.metadata
    # The check has not passed: the run reaches it again and runs it on the new output.
    assert not r._state.is_complete("sandbox_run")


async def test_a_send_back_at_a_researcher_step_still_stops_there_again(ran, workspace: Path, events):  # noqa: F811
    r, log = ran
    _stopped_at(r, "review_plan", "researcher")
    payload = apply_action(
        workspace,
        r._state,
        {"action": "send_back", "step": "replication_planner", "remark": "Use the paper."},
    )
    assert "then" not in payload
    with pytest.raises(HumanReviewRequestedError):
        await r._settle_researcher_decisions(r._state)
    assert log == ["replication_planner"] and r._state.pending_review_stage == "review_plan"


async def test_the_check_runs_again_and_stops_only_if_it_still_fails(ran, workspace: Path, events):  # noqa: F811
    from src.core.strategist.state import GateHaltError

    r, _log = ran
    _stopped_at(r, "sandbox_run", "gate")
    apply_action(workspace, r._state, {"action": "send_back", "step": "replication_planner", "remark": "Fix it."})
    await r._settle_researcher_decisions(r._state)
    # The package was never fetched here, so the check still fails: the run stops at it again, with reasons.
    with pytest.raises(GateHaltError):
        await r._run_check_step(r._spec.step("sandbox_run"), r._state)
    assert r._state.pending_review_stage == "sandbox_run" and r._state.metadata["review"]["kind"] == "gate"


class _Response:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, body: dict) -> None:
        self._body = body

    def json(self) -> dict:
        return self._body


class _Http:
    def __init__(self, body: dict) -> None:
        self.body = body

    def post(self, url: str, json: dict) -> _Response:  # noqa: A002 — httpx's keyword
        return _Response(self.body)


def test_e2er_review_says_the_check_runs_again_after_a_send_back(capsys):
    recorded = {"action": "send_back", "target": "econometrics_specialist", "then": "check_runs_again"}
    assert _post(_Http({"recorded": recorded, "resumed": {}}), "p", {"action": "send_back"}) == 0
    out = capsys.readouterr().out
    assert "✓ sent back econometrics_specialist (recorded for the dossier)" in out
    assert "the check runs again on the new output, and the run stops here again only if it fails" in out
    recorded.pop("then")
    _post(_Http({"recorded": recorded, "resumed": {}}), "p", {"action": "send_back"})
    assert capsys.readouterr().out.endswith("✓ the run continues\n")
