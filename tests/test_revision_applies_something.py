"""A revision round that applies no edit while findings are open sends the revisor back, then stops.

Demo 1 (2026-10-13, exoplanets): the panel's findings were `section:literature`;
the revisor targeted `paper:full` (as its skill and the coverage check tell it to
for a passage outside the named section), the merger rejected all five edits as
"not in work order findings", nothing sent the revisor back, and the paper
shipped as the reviewers had scored it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.specialists.contract_check import REVISION_FINDINGS_FILE, check_specialist_artifacts
from src.core.specialists.contracts import Contribution
from src.core.specialists.dispatcher import ContractFailureError
from src.core.strategist.findings import Finding
from src.core.strategist.patch_merger import merge_patch_file
from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import PaperStatus

LIT = "Prior work measured radii for every planet in the archive."
CONCLUSION = "Readers should treat the two provenances separately."
DRAFT = rf"""\documentclass{{article}}
\begin{{document}}
\section{{Literature}}
{LIT}
\section{{Conclusion}}
{CONCLUSION}
\end{{document}}
"""


def _finding() -> Finding:
    return Finding(
        source="review",
        source_detail="literature_reviewer",
        target="section:literature",
        severity=6,
        problem="The paper says prior work measured every radius; most radii are calculated.",
        suggested_fix="Say that most radii in the archive are calculated from the transit depth.",
    )


def _workspace(tmp_path: Path, edits: list[dict]) -> Path:
    f = _finding()
    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8", newline="\n")
    (tmp_path / "paper_draft.tex.edits.json").write_text(json.dumps(edits), encoding="utf-8", newline="\n")
    record = {
        "findings": [
            {
                "id": "F1",
                "source": f.source,
                "source_detail": f.source_detail,
                "target": f.target,
                "severity": f.severity,
                "problem": f.problem,
                "suggested_fix": f.suggested_fix,
            }
        ],
        "draft_sha256": hashlib.sha256(DRAFT.encode()).hexdigest(),
        "require_change": True,  # the revision round after the review panel
    }
    (tmp_path / REVISION_FINDINGS_FILE).write_text(json.dumps(record), encoding="utf-8", newline="\n")
    return tmp_path


def _violations(ws: Path) -> list[str]:
    return [c.reason for c in check_specialist_artifacts(ws, "patch_revisor") if not c.ok]


def test_a_full_paper_edit_is_a_text_edit_on_the_draft(tmp_path):
    """The demo-1 patch: `paper:full` targets against `section:literature` findings now apply."""
    edit = {"target": "paper:full", "edit_type": "replace_text", "find": LIT, "replace": "Most radii are calculated."}
    ws = _workspace(tmp_path, [edit])
    merged = merge_patch_file(ws, [_finding()], persist=False)
    assert merged.n_applied == 1 and not merged.failed
    assert _violations(ws) == []


def test_edits_that_all_fail_send_the_revisor_back_with_the_reasons(tmp_path):
    edits = [
        {"target": "section:literature", "edit_type": "replace_text", "find": "not in the draft", "replace": "x"},
        {"target": "section:methods", "edit_type": "replace_text", "find": LIT, "replace": "y"},
    ]
    ws = _workspace(tmp_path, edits)
    (reason,) = [r for r in _violations(ws) if "changes nothing" in r]
    assert reason.startswith("the revision changes nothing although 1 finding(s) are open")
    assert "find string not found within 'section:literature'" in reason
    assert "not in work order findings" in reason
    assert (ws / "paper_draft.tex").read_text(encoding="utf-8") == DRAFT  # the check writes nothing


def test_an_empty_patch_against_open_findings_is_sent_back(tmp_path):
    ws = _workspace(tmp_path, [])
    assert any("the patch has no edit" in r for r in _violations(ws))


def test_a_passage_kept_with_its_reason_is_an_answer(tmp_path):
    keep = {"edit_type": "keep", "find": LIT, "reason": "the cited survey did measure every radius"}
    ws = _workspace(tmp_path, [keep])
    assert not any("changes nothing" in r for r in _violations(ws))


# ── the revision round stops for the researcher after the last attempt ──────


def _runner(tmp_path: Path, mock_llm) -> PipelineRunner:
    paper_id = str(uuid.uuid4())
    ws = tmp_path / paper_id
    ws.mkdir()
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": paper_id, "title": "T", "research_question": "q?"}), encoding="utf-8", newline="\n"
    )
    (ws / "paper_draft.tex").write_text(DRAFT, encoding="utf-8", newline="\n")
    (ws / "review_literature.md").write_text(
        "# Review\n\nThe literature section misstates prior work.\n\n"
        "OVERALL SCORE: 4.0/10\nRECOMMENDATION: Major Revision\n",
        encoding="utf-8",
        newline="\n",
    )
    return PipelineRunner(paper_id=paper_id, workspace=ws, backend=mock_llm, model="mock", backend_name="mock")


class _Major:
    verdict = "MAJOR_REVISION"
    weighted_avg = 4.0
    rule_triggered = "weighted_avg < 5"
    rationale = "test"


@pytest.mark.asyncio
async def test_a_revision_that_applies_nothing_stops_for_the_researcher(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace
    calls: list[str] = []

    async def _rejected(work_order, *args, **kwargs):
        calls.append(work_order.specialist)
        (ws / "paper_draft.tex.edits.json").write_text(
            json.dumps([{"target": "section:methods", "edit_type": "replace_text", "find": LIT, "replace": "x"}]),
            encoding="utf-8",
            newline="\n",
        )
        return Contribution(
            paper_id=runner._paper_id,
            specialist=work_order.specialist,
            output="",
            success=False,
            error="contract violation",
            contract_violations=["paper_draft.tex.edits.json: the revision changes nothing"],
        )

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Major()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_rejected),
        pytest.raises(ContractFailureError) as stop,
    ):
        await runner._run_revision_phase(PaperStatus.REVIEW)
    assert calls == ["patch_revisor"] * 3  # every attempt, the violation fed back, then the stop
    assert [f["specialist"] for f in stop.value.failures] == ["patch_revisor"]
    assert (ws / "paper_draft.tex").read_text(encoding="utf-8") == DRAFT


@pytest.mark.asyncio
async def test_after_the_researcher_approves_the_round_completes_without_running_the_revisor_again(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace
    (ws / "paper_draft.tex.edits.json").write_text("[]", encoding="utf-8", newline="\n")

    class _State:
        metadata = {"contract_accepted_skip": [{"phase": "revision", "specialist": "patch_revisor"}]}

        def save(self, _ws):
            pass

    runner._state = _State()
    runner._current_step = "revision"

    async def _never(work_order, *args, **kwargs):
        raise AssertionError("the approved revisor ran again")

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Major()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_never),
        patch("src.db.client.execute"),
    ):
        status = await runner._run_revision_phase(PaperStatus.REVIEW)
    assert status == PaperStatus.COMPLETED
    assert "contract_accepted_skip" not in runner._state.metadata


@pytest.mark.asyncio
async def test_after_the_stop_reran_the_revisor_its_patch_is_applied_once(tmp_path, mock_llm):
    runner = _runner(tmp_path, mock_llm)
    ws = runner._workspace
    fixed = "Most radii in the archive are calculated from the transit depth."
    (ws / "paper_draft.tex.edits.json").write_text(
        json.dumps([{"target": "paper:full", "edit_type": "replace_text", "find": LIT, "replace": fixed}]),
        encoding="utf-8",
        newline="\n",
    )

    class _State:
        metadata = {"step_done": {"revision": ["patch_revisor"]}}

        def save(self, _ws):
            pass

    runner._state = _State()
    runner._current_step = "revision"

    async def _never(work_order, *args, **kwargs):
        raise AssertionError("the revisor ran twice")

    with (
        patch("src.core.strategist.runner.aggregate_reviews", return_value=_Major()),
        patch("src.core.specialists.dispatcher.execute_work_order", side_effect=_never),
        patch("src.db.client.execute"),
    ):
        status = await runner._run_revision_phase(PaperStatus.REVIEW)
    assert status == PaperStatus.COMPLETED
    assert fixed in (ws / "paper_draft.tex").read_text(encoding="utf-8")
    assert "revision" not in runner._state.metadata["step_done"]


def test_the_number_checks_correction_may_still_answer_with_an_empty_patch(tmp_path):
    ws = _workspace(tmp_path, [])
    record = json.loads((ws / REVISION_FINDINGS_FILE).read_text(encoding="utf-8"))
    record.pop("require_change")
    (ws / REVISION_FINDINGS_FILE).write_text(json.dumps(record), encoding="utf-8", newline="\n")
    assert not any("changes nothing" in r for r in _violations(ws))
