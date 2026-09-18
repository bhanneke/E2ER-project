"""Closed-loop table_spec key resolution.

When a table_spec reference can't be resolved even after the renderer's
order-insensitive normalization (a genuinely wrong/abbreviated name), the
runner dispatches section_writer with the available keys and re-renders — so
results tables don't ship with blank cells. Repair iterates while it is making
progress and stops as soon as it isn't.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.renderer.complete import RenderIncompleteError
from src.core.renderer.tables import UnresolvedRef
from src.core.specialists.contracts import Contribution
from src.core.strategist.runner import _MAX_TABLE_SPEC_REPAIRS, PipelineRunner

EST = {
    "full_dp": {
        "coefficients": {"dp": {"estimate": 0.0136, "p_value": 0.5}},
        "forecast_evaluation": {"clark_west_stat": 1.24, "oos_r_squared": 0.0063},
    }
}


def _make_ws(tmp_path: Path, paper_id: str, est: dict, table_spec: dict) -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "estimation_results.json").write_text(json.dumps(est), encoding="utf-8")
    (ws / "table_spec.json").write_text(json.dumps(table_spec), encoding="utf-8")
    (ws / "paper_draft.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{tables/main.tex}\n\\end{document}\n",
        encoding="utf-8",
    )
    return ws


def _runner(tmp_path: Path, mock_llm, est: dict, table_spec: dict) -> PipelineRunner:
    paper_id = str(uuid.uuid4())
    ws = _make_ws(tmp_path, paper_id, est, table_spec)
    return PipelineRunner(
        paper_id=paper_id,
        workspace=ws,
        backend=mock_llm,
        model="mock",
        mode="single_pass",
        backend_name="mock",
    )


def _contrib(runner: PipelineRunner, specialist: str) -> Contribution:
    return Contribution(paper_id=runner._paper_id, specialist=specialist, output="", success=True)


# ── _build_table_spec_feedback (pure) ──────────────────────────────────────


def test_build_feedback_lists_available_keys(tmp_path: Path, mock_llm):
    runner = _runner(tmp_path, mock_llm, EST, {"tables": []})
    fb = runner._build_table_spec_feedback([UnresolvedRef("main.tex", "stat", "cw_stat", "full_dp")])
    assert fb is not None
    assert "full_dp" in fb  # available spec_key
    assert "clark_west_stat" in fb  # available field name
    assert "cw_stat" in fb  # the unresolved ref echoed back


def test_build_feedback_none_without_estimation_json(tmp_path: Path, mock_llm):
    runner = _runner(tmp_path, mock_llm, {}, {"tables": []})
    assert runner._build_table_spec_feedback([UnresolvedRef("m", "stat", "x")]) is None


# ── _resolve_table_spec (dispatch + re-render) ─────────────────────────────


_BAD_SPEC = {
    "tables": [
        {
            "filename": "main.tex",
            "label": "tab:main",
            "caption": "C",
            "columns": [{"spec_key": "full_dp", "header": "dp"}],
            "rows": [{"type": "stat", "field": "cw_stat", "label": "CW"}],  # wrong name
        }
    ]
}


@pytest.mark.asyncio
async def test_resolve_dispatches_section_writer_and_fix_lands(tmp_path: Path, mock_llm):
    runner = _runner(tmp_path, mock_llm, EST, _BAD_SPEC)
    ws = runner._workspace
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        if work_order.specialist == "section_writer":
            # The feedback should name the right field; apply the fix.
            assert "clark_west_stat" in work_order.focus
            fixed = json.loads((ws / "table_spec.json").read_text())
            fixed["tables"][0]["rows"][0]["field"] = "clark_west_stat"
            (ws / "table_spec.json").write_text(json.dumps(fixed))
        return _contrib(runner, work_order.specialist)

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture):
        await runner._resolve_table_spec()

    assert dispatched == ["section_writer"]
    assert "1.24" in (ws / "tables" / "main.tex").read_text()  # CW value now rendered


@pytest.mark.asyncio
async def test_resolve_noop_when_everything_resolves(tmp_path: Path, mock_llm):
    # `dp_full` normalizes to `full_dp`; `oos_r_squared` exists → nothing to fix.
    good = {
        "tables": [
            {
                "filename": "main.tex",
                "label": "t",
                "caption": "C",
                "columns": [{"spec_key": "dp_full", "header": "dp"}],
                "rows": [{"type": "stat", "field": "oos_r_squared", "label": "OOS"}],
            }
        ]
    }
    runner = _runner(tmp_path, mock_llm, EST, good)
    dispatched: list[str] = []

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        return _contrib(runner, work_order.specialist)

    with patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_capture):
        await runner._resolve_table_spec()

    assert dispatched == []  # normalization resolved it; no fix dispatch
    # oos_r_squared 0.0063 renders at the default 3 decimals as 0.006.
    assert "0.006" in (runner._workspace / "tables" / "main.tex").read_text()


# ── the inventory is scoped per spec key ───────────────────────────────────

_TWO_SPECS = {
    "main": {"diagnostics": {"pct_change": 1.5}, "n_observations": 120},
    "bootstrap": {"n_observations": 120},
}


def test_feedback_scopes_fields_to_their_own_spec_key(tmp_path: Path, mock_llm):
    """A field under `main` must not be advertised as available to `bootstrap`.

    A flat union of field names is what invites a cross-column reference —
    printing one specification's number under another's heading.
    """
    runner = _runner(tmp_path, mock_llm, _TWO_SPECS, {"tables": []})
    fb = runner._build_table_spec_feedback([UnresolvedRef("m.tex", "stat", "pct_change", "bootstrap")])
    assert fb is not None
    boot_block = fb.split("  bootstrap:")[1].split("  main:")[0]
    main_block = fb.split("  main:")[1]
    assert "pct_change" in main_block
    assert "pct_change" not in boot_block
    assert "n_observations" in boot_block  # it does have this one


def test_feedback_names_the_column_of_each_unresolved_ref(tmp_path: Path, mock_llm):
    runner = _runner(tmp_path, mock_llm, _TWO_SPECS, {"tables": []})
    fb = runner._build_table_spec_feedback([UnresolvedRef("m.tex", "stat", "pct_change", "bootstrap")])
    assert "in column 'bootstrap'" in fb


def test_feedback_advertises_nested_scalars_as_flattened_paths(tmp_path: Path, mock_llm):
    est = {"main": {"transition_probabilities_pre": {"p_HH": 0.94}}}
    runner = _runner(tmp_path, mock_llm, est, {"tables": []})
    fb = runner._build_table_spec_feedback([UnresolvedRef("m.tex", "stat", "p_HH", "main")])
    # Underscore-joined is the form the renderer's token-subset descent matches.
    assert "transition_probabilities_pre_p_HH" in fb


# ── repair iterates, but only while it is buying progress ──────────────────


def _spec_with_bad_rows(n: int) -> dict:
    return {
        "tables": [
            {
                "filename": "main.tex",
                "label": "tab:main",
                "caption": "C",
                "columns": [{"spec_key": "full_dp", "header": "dp"}],
                "rows": [{"type": "stat", "field": f"bad_{i}", "label": f"L{i}"} for i in range(n)],
            }
        ]
    }


def _fix_one_per_call(runner: PipelineRunner, dispatched: list[str]):
    """A section_writer that repairs exactly one bad row per dispatch."""
    ws = runner._workspace

    async def _capture(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        spec = json.loads((ws / "table_spec.json").read_text())
        for row in spec["tables"][0]["rows"]:
            if row["field"].startswith("bad_"):
                row["field"] = "clark_west_stat"
                break
        (ws / "table_spec.json").write_text(json.dumps(spec))
        return _contrib(runner, work_order.specialist)

    return _capture


@pytest.mark.asyncio
async def test_repair_iterates_until_resolved(tmp_path: Path, mock_llm):
    """Two bad refs, one fixed per pass: the second pass is what saves the run."""
    runner = _runner(tmp_path, mock_llm, EST, _spec_with_bad_rows(2))
    dispatched: list[str] = []

    with patch(
        "src.core.specialists.dispatcher.execute_work_order",
        side_effect=_fix_one_per_call(runner, dispatched),
    ):
        await runner._resolve_table_spec()

    assert dispatched == ["section_writer", "section_writer"]
    assert "1.24" in (runner._workspace / "tables" / "main.tex").read_text()


@pytest.mark.asyncio
async def test_repair_stops_when_an_attempt_makes_no_progress(tmp_path: Path, mock_llm):
    """An ambiguous reference does not get less ambiguous on the second ask, so
    a pass that fixes nothing ends the loop instead of burning the budget."""
    runner = _runner(tmp_path, mock_llm, EST, _spec_with_bad_rows(2))
    dispatched: list[str] = []

    async def _fix_nothing(work_order, *args, **kwargs):
        dispatched.append(work_order.specialist)
        return _contrib(runner, work_order.specialist)

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_fix_nothing),
        pytest.raises(RenderIncompleteError),
    ):
        await runner._resolve_table_spec()

    assert dispatched == ["section_writer"]  # one wasted call, not three


@pytest.mark.asyncio
async def test_repair_budget_is_bounded(tmp_path: Path, mock_llm):
    """Progress on every pass still terminates: four bad refs, one fixed per
    pass, three passes allowed — the run halts rather than looping forever."""
    runner = _runner(tmp_path, mock_llm, EST, _spec_with_bad_rows(4))
    dispatched: list[str] = []

    with (
        patch(
            "src.core.specialists.dispatcher.execute_work_order",
            side_effect=_fix_one_per_call(runner, dispatched),
        ),
        pytest.raises(RenderIncompleteError),
    ):
        await runner._resolve_table_spec()

    assert len(dispatched) == _MAX_TABLE_SPEC_REPAIRS
