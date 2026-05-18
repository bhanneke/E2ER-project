"""Lane A — closes #6: resume must write terminal status when state.json
shows the pipeline is already complete.

Reproduces the original bug from paper d5db4684 (2026-05-17): a paper
finished all phases on disk (state.last_status == 'completed'), but the
runner died seconds after replication. On resume, the runner saw every
stage marked complete in PipelineState, skipped every phase body, and
exited without writing the final status. The DB row stayed at
'designing' (the value run() sets on entry) until manual UPDATE.

Fix: at the end of run(), if state.last_status is set, mirror it back
to the DB via _update_status. This test pins that behavior.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.state import PipelineState
from src.core.strategist.runner import PipelineRunner


def _make_workspace_fully_complete(tmp_path: Path, paper_id: str) -> Path:
    """Build a workspace whose .pipeline_state.json says everything is done
    and last_status='completed' — exactly the case run #17 left behind."""
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps({"paper_id": paper_id, "title": "T", "research_question": "Q", "mode": "iterative"})
    )
    # PipelineState with every stage marked done
    state = PipelineState(paper_id=paper_id, mode="iterative")
    for stage in ("initial", "iterative", "self_attack", "polish", "review", "revision", "replication"):
        state.mark_complete(stage)
    state.last_status = "completed"
    state.save(ws)
    return ws


@pytest.mark.asyncio
async def test_resume_writes_final_status_when_state_complete(tmp_path, mock_llm):
    """Resume on a fully-complete workspace → runner writes the terminal status.

    Pre-v0.4 the runner exited without calling _update_status, so the
    DB row stayed at 'designing'. This test pins the fix.
    """
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_fully_complete(tmp_path, paper_id)

    # Track every status write so we can assert the final 'completed' write happened.
    status_writes: list[str] = []

    async def _capture_update_status(self, status, error=None):  # noqa: ARG001
        status_writes.append(status.value)

    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=mock_llm,
        model="mock",
        mode="iterative",
        backend_name="mock",
    )

    with (
        patch.object(PipelineRunner, "_update_status", new=_capture_update_status),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget", new_callable=AsyncMock),
    ):
        result = await runner.run()

    # Expected trace: designing (entry) → completed (terminal mirror).
    # The bug fix specifically adds the second entry; before #6 the trace
    # ended at 'designing'.
    assert "designing" in status_writes, f"sanity: entry status not recorded: {status_writes}"
    assert "completed" in status_writes, (
        f"Bug regression: resume on fully-complete workspace must write terminal "
        f"status. status writes: {status_writes}, result: {result}"
    )

    # The final entry should be `completed`, not `designing`.
    assert status_writes[-1] == "completed", (
        f"Last status write should be 'completed' (the terminal mirror), got {status_writes!r}"
    )
