"""An initial phase that ends without a draft sends the paper drafter out.

The 2026-10-13 school-fee demo (policy evaluation): the strategist's plan left
the drafter out, the five reviewers judged the plan instead of a paper, and the
study "completed" with no paper.
"""

from __future__ import annotations

from pathlib import Path

from src.core.pipeline.spec import find_spec
from tests.test_replication_template import _runner, events  # noqa: F401


def _initial(monkeypatch, ws: Path):
    r = _runner(ws)
    r._spec = find_spec("policy-evaluation")
    sent: list[str] = []

    async def _body():
        return None

    async def _exec(orders):
        sent.extend(o.specialist for o in orders)
        return []

    monkeypatch.setattr(r, "_initial_phase_body", _body)
    monkeypatch.setattr(r, "_execute_orders", _exec)
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.save", lambda self, ws: None)
    return r, sent


async def test_no_draft_after_the_initial_phase_sends_the_drafter(monkeypatch, tmp_path: Path, events):  # noqa: F811
    r, sent = _initial(monkeypatch, tmp_path)
    await r._run_initial_phase()
    assert sent == ["paper_drafter"]
    assert [k for k, _s, _p in events] == ["drafter_sent_out"]


async def test_a_draft_there_sends_nobody(monkeypatch, tmp_path: Path, events):  # noqa: F811
    (tmp_path / "paper_draft.tex").write_text("\\section{Results}")
    r, sent = _initial(monkeypatch, tmp_path)
    await r._run_initial_phase()
    assert sent == [] and events == []


def test_the_event_has_a_label():
    from src.core.labels import EVENTS

    assert "drafter_sent_out" in EVENTS
