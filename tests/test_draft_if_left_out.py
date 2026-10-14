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


# ── the iterative mode (2026-10-14 GDP demo) ───────────────────────────────
# No round dispatched the drafter; the third sent three section writers at once,
# each wrote paper_draft.tex from nothing, and the last file (introduction and
# literature only) was reviewed and exported as the paper.


def _orders(*spec_group: tuple[str, int]):
    from src.core.strategist.actions import WorkOrder

    return [WorkOrder(specialist=s, focus=f"focus {i}", parallel_group=g) for i, (s, g) in enumerate(spec_group)]


def test_section_writers_without_a_draft_become_one_drafter():
    from src.core.strategist.runner import _draft_from_section_orders

    orders = _orders(
        ("econometrics_specialist", 0), ("section_writer", 1), ("section_writer", 1), ("abstract_writer", 2)
    )
    out = _draft_from_section_orders(orders, has_draft=False)
    assert [(o.specialist, o.parallel_group) for o in out] == [
        ("econometrics_specialist", 0),
        ("abstract_writer", 2),
        ("paper_drafter", 1),
    ]
    assert "no draft yet" in out[-1].focus and "focus 1" in out[-1].focus and "focus 2" in out[-1].focus
    # With a draft, section writers edit it; with a drafter in the round, it writes them.
    assert _draft_from_section_orders(orders, has_draft=True) == orders
    with_drafter = _orders(("paper_drafter", 0), ("section_writer", 0))
    assert [o.specialist for o in _draft_from_section_orders(with_drafter, has_draft=False)] == ["paper_drafter"]


def test_section_writers_of_one_group_run_one_after_another():
    from src.core.strategist.runner import _one_draft_writer_at_a_time

    orders = _orders(
        ("econometrics_specialist", 0),
        ("section_writer", 1),
        ("data_analyst", 1),
        ("section_writer", 1),
        ("section_writer", 1),
        ("abstract_writer", 2),
    )
    out = _one_draft_writer_at_a_time(orders)
    assert [(o.specialist, o.parallel_group) for o in out] == [
        ("econometrics_specialist", 0),
        ("section_writer", 1),
        ("data_analyst", 1),
        ("section_writer", 2),
        ("section_writer", 3),
        ("abstract_writer", 4),
    ]
    single = _orders(("section_writer", 0), ("abstract_writer", 1))
    assert _one_draft_writer_at_a_time(single) == single


async def test_rounds_that_end_without_a_draft_send_the_drafter(monkeypatch, tmp_path: Path, events):  # noqa: F811
    from unittest.mock import AsyncMock

    r, sent = _initial(monkeypatch, tmp_path)
    r._mode = "iterative"
    monkeypatch.setattr(r, "_run_rounds", AsyncMock(return_value=None))
    await r._run_iterative_phase()
    assert sent == ["paper_drafter"]
    assert [(k, p["reason"]) for k, _s, p in events] == [("drafter_sent_out", "no draft after the iterative phase")]
    # A round that wrote a draft: nobody is sent.
    sent.clear()
    (tmp_path / "paper_draft.tex").write_text("\\section{Results}")
    await r._run_iterative_phase()
    assert sent == []
