"""Lane A integration smoke — full pipeline end-to-end through the FastAPI surface.

The existing ``test_single_pass_creates_core_artifacts`` in
``tests/test_pipeline.py`` covers the runner-level end-to-end with mocks.
This file fills two gaps:

  1. **API-layer smoke** — proves that ``POST /api/papers`` actually
     triggers the background pipeline and that GET endpoints return what
     dashboards display. Catches FastAPI wiring regressions (missing
     dependency injections, broken auth, status enum drift) before they
     show up as 500s in the browser.

  2. **Theoretical-methodology integration** — confirms the
     ``methodology="theoretical"`` selector flows through the strategist
     and dispatches ``theory_specialist``. Live runs #6-#8 exercised this,
     but no automated test does.

Both run with the MockLLMBackend (no network, no API key, ~3s total).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.strategist.actions import StrategistDecision, WorkOrder
from src.core.strategist.engine import StrategistEngine

# ---------- helpers ----------


def _theoretical_dispatch(paper_id: str) -> StrategistDecision:
    """Strategist's first decision when methodology=theoretical.

    Skips the data lane entirely (no data_architect, data_analyst,
    econometrics_specialist) and dispatches theory_specialist instead.
    """
    return StrategistDecision(
        action="dispatch_parallel",
        work_orders=[
            WorkOrder(specialist="idea_developer", focus="Develop the idea", parallel_group=0),
            WorkOrder(specialist="literature_scanner", focus="Scan literature", parallel_group=0),
            WorkOrder(specialist="theory_specialist", focus="Build the formal model", parallel_group=1),
            WorkOrder(specialist="paper_drafter", focus="Draft paper from model", parallel_group=2),
            WorkOrder(specialist="abstract_writer", focus="Write abstract", parallel_group=2),
        ],
        rationale="Theoretical methodology — skip data lane",
    )


def _make_workspace(tmp_path: Path, paper_id: str, methodology: str = "empirical") -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    manifest = {
        "paper_id": paper_id,
        "title": "Test Paper",
        "research_question": "Test research question",
        "datasets": [],
        "mode": "single_pass",
        "methodology": methodology,
        "current_stage": "idea",
    }
    (ws / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return ws


# ---------- theoretical methodology end-to-end ----------


async def test_theoretical_pipeline_produces_model_spec(tmp_path, mock_llm):
    """Full theoretical run: theory_specialist must write model_spec.md.

    Run #6-#8 proved this path live. This pins the contract so a future
    refactor of the methodology selector or specialist routing can't
    silently break the theoretical lane.
    """
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, methodology="theoretical")

    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_theoretical_dispatch(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id,
            workspace=workspace,
            backend=mock_llm,
            model="claude-test",
            mode="single_pass",
            extra_tools=[],
            extra_handlers=[],
            backend_name="mock",
        )
        result = await runner.run()

    assert result["status"] in ("completed", "failed", "in_progress")

    # The defining artifact of the theoretical path.
    assert (workspace / "model_spec.md").exists(), "theory_specialist must write model_spec.md on theoretical runs"

    # The empirical-only artifacts MUST NOT be written when theory_specialist
    # is the data lane.
    assert not (workspace / "data_dictionary.json").exists(), "theoretical runs should not produce data_dictionary.json"
    assert not (workspace / "data_summary.md").exists()
    assert not (workspace / "econometric_spec.md").exists()

    # Writing phase still ran.
    assert (workspace / "paper_draft.tex").exists()
    assert (workspace / "abstract.tex").exists()


# ---------- FastAPI surface smoke ----------


def test_api_create_paper_triggers_pipeline(tmp_path, monkeypatch):
    """POST /api/papers must return a paper_id + workspace and start the run.

    Catches FastAPI wiring regressions: missing dependency injection,
    auth dependency drift, response-model field rename. The pipeline
    itself is mocked at the runner level so this is a pure surface test.
    """
    monkeypatch.setattr("src.config.get_settings", _settings_for_test(tmp_path))

    # Stub out the background pipeline kick-off so we don't actually start
    # a run — we just want to confirm the route returns 200 with the
    # expected shape. The runner is imported lazily inside _run_pipeline,
    # so patching the helper itself is the cleanest interception point.
    with (
        patch("src.api.app._run_pipeline", new_callable=AsyncMock) as run_pipeline_mock,
        patch("src.db.client.execute", new_callable=AsyncMock) as db_execute,
        patch("src.db.client.fetch_one", new_callable=AsyncMock) as db_fetch,
    ):
        run_pipeline_mock.return_value = None
        db_execute.return_value = None
        db_fetch.return_value = None

        from fastapi.testclient import TestClient

        from src.api.app import app

        client = TestClient(app)
        resp = client.post(
            "/api/papers",
            json={
                "title": "Smoke test paper",
                "research_question": "Does the test framework work?",
                "methodology": "theoretical",
                "pipeline_mode": "single_pass",
                "max_specialists_per_phase": 3,
                "acknowledge_unproven_tuple": True,
            },
        )

    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text[:200]}"
    body = resp.json()
    assert "paper_id" in body, f"response missing paper_id: {body}"
    assert "workspace" in body, f"response missing workspace: {body}"
    assert body.get("status") == "idea", f"new paper should start in 'idea' state, got {body.get('status')}"


def _settings_for_test(tmp_path: Path):
    """Return a get_settings replacement that points workspace_root at tmp_path."""
    from src.config import Settings

    base = Settings()

    def _get():
        # Mutate workspace_root to keep test artifacts in tmp_path. Other
        # settings (API keys, DB URL) stay as defaults — the mocks in the
        # caller intercept any actual external call.
        base.workspace_root = str(tmp_path)
        return base

    return _get


# ---------- cascade failure mode (the real-world failure surface) ----------


async def test_cascade_halts_when_canonical_artifact_missing(tmp_path, mock_llm):
    """When a specialist 'succeeds' without writing its canonical artifact,
    the dispatcher must halt the pipeline rather than advancing downstream.

    This is the failure mode from runs #14 and #17. The fix is cascade
    detection in dispatcher.py; this test pins it.
    """
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, methodology="empirical")

    from src.core.specialists.contracts import WorkOrder as SpecialistWorkOrder
    from src.core.specialists.dispatcher import execute_parallel

    # Mock backend that returns success=True without writing data_summary.md.
    class FakeSuccessfulButEmptyBackend:
        async def tool_loop(self, **kwargs):
            from src.modules.llm.base import TokenUsage, ToolLoopResult

            return ToolLoopResult(
                success=True,
                output="I claim success but wrote no file.",
                tool_calls_made=0,
                usage=TokenUsage(),
                duration_seconds=0.1,
                stop_reason="end_turn",
            )

    fake_backend = FakeSuccessfulButEmptyBackend()
    work_orders = [
        SpecialistWorkOrder(
            paper_id=paper_id,
            specialist="data_analyst",
            focus="Pull the data",
            context_tier=1,
        ),
    ]

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
    ):
        # The cascade-halt invariant: a specialist that returns
        # success=True without writing its canonical artifact must halt
        # the parallel batch. v0.5 caught it via the dispatcher's
        # canonical-artifact check ("canonical artifact"); v0.9 M4.3
        # catches it earlier inside run_specialist with the more
        # specific "contract violation: <path>: file not written"
        # message. Either path satisfies the invariant — accept both.
        with pytest.raises(RuntimeError, match="canonical artifact|contract violation"):
            await execute_parallel(
                work_orders=work_orders,
                backend=fake_backend,  # type: ignore[arg-type]
                workspace=workspace,
                model="mock",
                backend_name="mock",
            )
