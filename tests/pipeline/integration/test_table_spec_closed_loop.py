"""Closed-loop table_spec key resolution.

When a table_spec reference can't be resolved even after the renderer's
order-insensitive normalization (a genuinely wrong/abbreviated name), the
runner dispatches ONE section_writer fix with the available keys, then
re-renders — so results tables don't ship with blank cells.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.renderer.tables import UnresolvedRef
from src.core.specialists.contracts import Contribution
from src.core.strategist.runner import PipelineRunner

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
