"""`e2er review` with several options, and `e2er rerun --from <specialist>` (2026-10-13 demos).

The exoplanet and Gaia demos ran `e2er review ID --instruction "…" --approve`:
the instruction was recorded and the approval silently dropped. A stop's
send-back list offers specialists, while `e2er rerun --from` took template
steps only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src import cli_review
from src.core.pipeline.researcher import ResearcherActionError, apply_rerun, step_for_rerun
from src.core.pipeline.spec import find_spec
from src.core.pipeline.state import PipelineState

PID = "3ce438bc-e1e1-45a5-a034-d09f3ca3d12b"


class _Resp:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self.headers = {"content-type": "application/json"}
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


class _Http:
    """The review endpoint: a pending step; each POST answers with what was recorded."""

    def __init__(self, fail: str | None = None) -> None:
        self.posts: list[dict[str, Any]] = []
        self.fail = fail

    def get(self, url: str) -> _Resp:
        return _Resp(200, {"pending": {"stage": "review_design"}, "files": [{"name": "plan.md", "content": "old"}]})

    def post(self, url: str, json: dict[str, Any]) -> _Resp:  # noqa: A002 — httpx's keyword
        self.posts.append(json)
        if json["action"] == self.fail:
            return _Resp(409, {"detail": "the run is not stopped here"})
        body: dict[str, Any] = {"recorded": {"action": json["action"]}}
        if json["action"] in ("approve", "send_back"):
            body["resumed"] = {}
        return _Resp(200, body)


@pytest.fixture
def http(monkeypatch):
    h = _Http()
    monkeypatch.setattr(cli_review, "_client", lambda: h)
    return h


def test_instruction_and_approve_records_the_instruction_then_approves(http, capsys):
    assert cli_review.review(PID, instruction="Use one magnitude per event.", approve=True) == 0
    assert [p["action"] for p in http.posts] == ["instruction", "approve"]
    out = capsys.readouterr().out
    assert "✓ instruction added" in out and "✓ approved" in out and "✓ the run continues" in out


def test_edit_instruction_and_approve_run_in_order(http, monkeypatch):
    monkeypatch.setattr(cli_review, "_edit_in_editor", lambda content, name: "new")
    assert cli_review.review(PID, edit="plan.md", instruction="x", approve=True) == 0
    assert [p["action"] for p in http.posts] == ["edit", "instruction", "approve"]


def test_no_approval_when_the_instruction_was_not_recorded(monkeypatch, capsys):
    h = _Http(fail="instruction")
    monkeypatch.setattr(cli_review, "_client", lambda: h)
    assert cli_review.review(PID, instruction="x", approve=True) == 1
    assert [p["action"] for p in h.posts] == ["instruction"]
    assert "the instruction was not recorded, so the run was not continued" in capsys.readouterr().err


def test_send_back_and_approve_together_are_refused_plainly(http, capsys):
    assert cli_review.review(PID, send_back="data_architect", remark="r", approve=True) == 1
    assert http.posts == []
    assert "contradict each other" in capsys.readouterr().err


def test_instruction_and_send_back_records_both(http):
    assert cli_review.review(PID, instruction="x", send_back="data_architect", remark="r") == 0
    assert [p["action"] for p in http.posts] == ["instruction", "send_back"]


def test_instruction_alone_does_not_continue_the_run(http):
    assert cli_review.review(PID, instruction="x") == 0
    assert [p["action"] for p in http.posts] == ["instruction"]


# ── rerun --from a specialist ────────────────────────────────────────────────


def test_a_dispatched_specialist_maps_to_the_strategist_step():
    spec = find_spec("descriptive-study")
    assert step_for_rerun(spec, "single_pass", "paper_drafter") == "initial"
    assert step_for_rerun(spec, "single_pass", "data_analyst") == "initial"


def test_a_specialist_in_a_steps_run_maps_to_that_step():
    spec = find_spec("descriptive-study")
    assert step_for_rerun(spec, "single_pass", "replication_packager") == "replication"
    assert step_for_rerun(spec, "single_pass", "revisor") == "revision"


def test_a_step_name_is_kept():
    assert step_for_rerun(find_spec("descriptive-study"), "single_pass", "figure_gate") == "figure_gate"


def test_a_specialist_in_two_steps_is_refused_with_the_choice():
    with pytest.raises(ResearcherActionError, match=r"runs in more than one step \(initial, iterative\)"):
        step_for_rerun(find_spec("descriptive-study"), "iterative", "paper_drafter")


def test_a_specialist_of_another_mode_says_so(tmp_path: Path):
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["initial"]
    with pytest.raises(ResearcherActionError, match="is not part of a single pass run"):
        apply_rerun(tmp_path, st, find_spec("descriptive-study"), "polish_numerics", "r")


def test_an_unknown_name_is_refused_as_a_step():
    st = PipelineState(paper_id=PID, mode="single_pass")
    with pytest.raises(ResearcherActionError, match="is not a step of the template"):
        apply_rerun(Path("/nonexistent"), st, find_spec("descriptive-study"), "nobody", "r")


def test_the_rerun_records_the_specialist_and_tells_it(tmp_path: Path):
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.completed_stages = ["review_design", "initial", "estimation_gate", "figure_gate", "review_draft"]
    st.approved_stages = ["review_design", "review_draft"]
    st.last_status = "completed"
    payload = apply_rerun(tmp_path, st, find_spec("descriptive-study"), "paper_drafter", "Mark the members.")
    assert payload["step"] == "initial" and payload["specialist"] == "paper_drafter"
    text = (tmp_path / "researcher_instructions.md").read_text()
    assert "(for paper_drafter in step initial, rerun of the study," in text


def test_e2er_rerun_says_which_step_the_specialist_runs_in(monkeypatch, capsys):
    class _H:
        def post(self, url, json):  # noqa: A002
            return _Resp(200, {"recorded": {"step": "initial", "specialist": "paper_drafter", "reruns": ["initial"]}})

    monkeypatch.setattr(cli_review, "_client", lambda: _H())
    assert cli_review.rerun(PID, step="paper_drafter", remark="r") == 0
    assert "✓ paper_drafter runs in the step initial; the whole step runs again" in capsys.readouterr().out
