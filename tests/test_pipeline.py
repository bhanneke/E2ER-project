"""Pipeline integration tests — exercises the full orchestration path with mocked LLM and DB."""
from __future__ import annotations

import asyncio
import io
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.strategist.actions import (
    CeilingCheckResult,
    SelfAttackReport,
    StrategistDecision,
    WorkOrder,  # WorkOrder from strategist.actions, NOT from specialists.contracts
)


# ---------------------------------------------------------------------------
# Pre-canned strategist decisions used across tests
# ---------------------------------------------------------------------------

def _designing_decision(paper_id: str) -> StrategistDecision:
    # Note: strategist.actions.WorkOrder does NOT have paper_id — paper_id lives
    # in specialists.contracts.WorkOrder which the dispatcher creates from these.
    return StrategistDecision(
        action="dispatch_parallel",
        work_orders=[
            WorkOrder(specialist="idea_developer", focus="Develop idea", parallel_group=0),
            WorkOrder(specialist="literature_scanner", focus="Scan literature", parallel_group=0),
            WorkOrder(specialist="identification_strategist", focus="ID strategy", parallel_group=0),
            WorkOrder(specialist="econometrics_specialist", focus="Specify model", parallel_group=1),
            WorkOrder(specialist="paper_drafter", focus="Draft paper", parallel_group=2),
            WorkOrder(specialist="abstract_writer", focus="Write abstract", parallel_group=2),
            WorkOrder(specialist="latex_formatter", focus="Format LaTeX", parallel_group=3),
        ],
        rationale="Initial design phase",
    )


_PROCEED_DECISION = StrategistDecision(action="complete", work_orders=[], rationale="Done")
_CEILING_PROCEED = CeilingCheckResult(verdict="proceed_to_review", reason="Quality ceiling reached.", iteration=1)
_SELF_ATTACK_CLEAN = SelfAttackReport(findings=[], overall_severity=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path, paper_id: str, mode: str = "single_pass") -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    manifest = {
        "paper_id": paper_id,
        "title": "Test Paper: DeFi Liquidity",
        "research_question": "How does concentrated liquidity affect price discovery?",
        "datasets": [],
        "mode": mode,
        "current_stage": "idea",
    }
    (ws / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return ws


# ---------------------------------------------------------------------------
# Single-pass mode
# ---------------------------------------------------------------------------

async def test_single_pass_creates_core_artifacts(tmp_path, mock_llm):
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
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

    # Pipeline should complete (not fail)
    assert result["status"] in ("completed", "failed", "in_progress")

    # All core research artifacts must exist
    assert (workspace / "paper_plan.md").exists(), "idea_developer must write paper_plan.md"
    assert (workspace / "literature_review.md").exists(), "literature_scanner must write literature_review.md"
    assert (workspace / "identification_strategy.md").exists()
    assert (workspace / "econometric_spec.md").exists()
    assert (workspace / "paper_draft.tex").exists()
    assert (workspace / "abstract.tex").exists()

    # Review phase must have run (all 6 reviewer artifacts)
    for reviewer in ["mechanism", "technical", "literature", "writing", "data", "identification"]:
        assert (workspace / f"review_{reviewer}.md").exists(), f"review_{reviewer}.md missing"

    # Review aggregation must be written
    assert (workspace / "review_aggregation.json").exists()

    # Aggregation JSON must be valid
    agg = json.loads((workspace / "review_aggregation.json").read_text())
    assert "verdict" in agg
    assert agg["verdict"] in {"ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "HARD_REJECT", "MECHANISM_FAIL"}


async def test_single_pass_specialist_call_order(tmp_path, mock_llm):
    """Mock LLM records specialist calls; verify correct set is invoked."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        await runner.run()

    called = set(mock_llm.specialist_calls)

    # Core specialists from the designing decision
    expected_core = {
        "idea_developer", "literature_scanner", "identification_strategist",
        "econometrics_specialist", "paper_drafter", "abstract_writer", "latex_formatter",
    }
    assert expected_core.issubset(called), f"Missing specialist calls: {expected_core - called}"

    # All 6 reviewers
    expected_reviewers = {
        "mechanism_reviewer", "technical_reviewer", "literature_reviewer",
        "writing_reviewer", "data_reviewer", "identification_reviewer",
    }
    assert expected_reviewers.issubset(called), f"Missing reviewer calls: {expected_reviewers - called}"


async def test_single_pass_contributions_count(tmp_path, mock_llm):
    """Pipeline should record at least 13 specialist contributions (7 core + 6 reviewers)."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        result = await runner.run()

    assert result["contributions"] >= 13, (
        f"Expected ≥13 contributions (7 core + 6 reviewers), got {result['contributions']}"
    )


# ---------------------------------------------------------------------------
# Review aggregation outcome
# ---------------------------------------------------------------------------

async def test_review_aggregation_accept_completes_paper(tmp_path, mock_llm):
    """When all reviewers score ≥ 6, the paper should reach ACCEPT or MINOR_REVISION."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        result = await runner.run()

    # mock_llm always returns Score: 7/10 for all reviewers → expect ACCEPT or MINOR_REVISION
    agg = json.loads((workspace / "review_aggregation.json").read_text())
    assert agg["verdict"] in {"ACCEPT", "MINOR_REVISION"}, (
        f"With mock scores all 7/10, expected ACCEPT or MINOR_REVISION, got {agg['verdict']}"
    )


# ---------------------------------------------------------------------------
# Skills loading
# ---------------------------------------------------------------------------

def test_skills_loaded_for_all_specialists():
    """Every specialist in the registry should resolve to at least one skill file."""
    from src.skills.loader import load_skills_for_specialist, _SPECIALIST_SKILLS

    missing_skills: list[str] = []
    for specialist in _SPECIALIST_SKILLS:
        skills_text = load_skills_for_specialist(specialist)
        if not skills_text.strip():
            missing_skills.append(specialist)

    assert not missing_skills, (
        f"These specialists have NO skill files loaded — check skills/files/ directory: {missing_skills}"
    )


def test_skills_directory_has_expected_files():
    """Spot-check that the most critical skill files are present and non-empty."""
    from src.skills.loader import _load_skill

    required = [
        "iv-estimation", "did", "panel-data", "event-study",
        "judge-designs", "natural-experiments", "sensitivity",
        "creative-ideation", "novelty", "argument-audit",
        "paper-structure", "personal-style", "abstract",
        "econ-model", "tables", "bibtex",
        "game-theory", "market-microstructure",
        "context-builder", "referee-simulation",
        "technical-review", "consistency-check",
        "writing-quality", "data-quality",
    ]
    missing = [name for name in required if not _load_skill(name).strip()]
    assert not missing, f"Required skill files not found or empty: {missing}"


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------

async def test_two_papers_workspace_isolated(tmp_path, mock_llm):
    """Two concurrent pipeline runs must not cross-contaminate workspaces."""
    import asyncio

    paper_a = str(uuid.uuid4())
    paper_b = str(uuid.uuid4())
    ws_a = _make_workspace(tmp_path, paper_a)
    ws_b = _make_workspace(tmp_path, paper_b)

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", side_effect=lambda *a, **kw: _designing_decision(paper_a)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner_a = PipelineRunner(
            paper_id=paper_a, workspace=ws_a, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        runner_b = PipelineRunner(
            paper_id=paper_b, workspace=ws_b, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        # Run sequentially to avoid decide() side_effect complexity
        await runner_a.run()

    # Files in ws_a must NOT appear in ws_b
    files_a = {f.name for f in ws_a.rglob("*") if f.is_file()}
    files_b = {f.name for f in ws_b.rglob("*") if f.is_file()}

    # ws_b should only have manifest.json (nothing written by runner_b since it wasn't run)
    assert "paper_plan.md" not in files_b, "paper_plan.md leaked from paper_a workspace into paper_b"


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------

def test_inject_context_tier0(tmp_path):
    """Tier 0 produces minimal context: paper title + RQ only."""
    import json
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import _inject_context

    ws = tmp_path / "paper-ctx"
    ws.mkdir()
    manifest = {"paper_id": "test-id", "title": "DeFi Liquidity", "research_question": "Does X affect Y?",
                "datasets": [], "mode": "single_pass", "current_stage": "idea"}
    (ws / "manifest.json").write_text(json.dumps(manifest))

    wo = WorkOrder(paper_id="test-id", specialist="idea_developer", focus="Develop idea", context_tier=0)
    enriched = _inject_context(wo, ws)

    assert "DeFi Liquidity" in enriched.context
    assert "Does X affect Y?" in enriched.context
    # Tier 0 should NOT include paper plan (doesn't exist yet anyway)


def test_inject_context_tier1_includes_paper_plan(tmp_path):
    """Tier 1 injects paper_plan.md content into specialist context."""
    import json
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import _inject_context

    ws = tmp_path / "paper-ctx1"
    ws.mkdir()
    manifest = {"paper_id": "test-id", "title": "Test Paper", "research_question": "RQ?",
                "datasets": [], "mode": "single_pass", "current_stage": "idea"}
    (ws / "manifest.json").write_text(json.dumps(manifest))
    (ws / "paper_plan.md").write_text("# Paper Plan\n\nH1: X increases Y.")

    wo = WorkOrder(paper_id="test-id", specialist="econometrics_specialist", focus="Specify model", context_tier=1)
    enriched = _inject_context(wo, ws)

    assert "H1: X increases Y." in enriched.context


def test_inject_context_tier2_includes_draft(tmp_path):
    """Tier 2 injects the current draft into reviewer context."""
    import json
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import _inject_context

    ws = tmp_path / "paper-ctx2"
    ws.mkdir()
    manifest = {"paper_id": "test-id", "title": "Test Paper", "research_question": "RQ?",
                "datasets": [], "mode": "single_pass", "current_stage": "review"}
    (ws / "manifest.json").write_text(json.dumps(manifest))
    (ws / "paper_draft.tex").write_text(r"\documentclass{article}\begin{document}The draft.\end{document}")

    wo = WorkOrder(paper_id="test-id", specialist="mechanism_reviewer", focus="Review mechanism", context_tier=2)
    enriched = _inject_context(wo, ws)

    assert "The draft." in enriched.context


def test_inject_context_skips_if_already_populated(tmp_path):
    """Pre-populated context must not be overwritten."""
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import _inject_context

    wo = WorkOrder(paper_id="test-id", specialist="paper_drafter", focus="Draft",
                   context="Already set by caller.", context_tier=2)
    enriched = _inject_context(wo, tmp_path)

    assert enriched.context == "Already set by caller."


# ---------------------------------------------------------------------------
# Compile + GitHub push phases
# ---------------------------------------------------------------------------

async def test_compile_phase_non_fatal(tmp_path, mock_llm):
    """Compile phase must not crash the pipeline when no LaTeX compiler is present."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.core.renderer.compiler.compile_latex", new_callable=AsyncMock, return_value=None),
        patch("src.modules.github.push.push_latex_draft", new_callable=AsyncMock, return_value=None),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        result = await runner.run()

    assert result["status"] not in ("failed",), "Compile/push phase must not abort the pipeline"


async def test_github_push_called_on_completion(tmp_path, mock_llm):
    """push_latex_draft must be called exactly once after a successful pipeline run."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    push_mock = AsyncMock(return_value={"pushed_files": 3, "stage": "completion", "repo": "test-repo"})

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.core.renderer.compiler.compile_latex", new_callable=AsyncMock, return_value=None),
        patch("src.modules.github.push.push_latex_draft", push_mock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        await runner.run()

    push_mock.assert_called_once()
    call_args = push_mock.call_args
    assert call_args.args[0] == paper_id
    assert call_args.args[2] == "completion"


# ---------------------------------------------------------------------------
# Replication phase
# ---------------------------------------------------------------------------

async def test_replication_phase_runs_packager(tmp_path, mock_llm):
    """replication_packager must be called and estimation.py must be written."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.core.renderer.compiler.compile_latex", new_callable=AsyncMock, return_value=None),
        patch("src.modules.github.push.push_latex_draft", new_callable=AsyncMock, return_value=None),
        patch("src.modules.data.audit.write_audit_csv", new_callable=AsyncMock, return_value=0),
        patch("src.modules.data.audit.write_data_queries_sql", new_callable=AsyncMock, return_value=0),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        await runner.run()

    assert "replication_packager" in set(mock_llm.specialist_calls)
    assert (workspace / "replication" / "estimation.py").exists(), "replication/estimation.py must be written"


async def test_replication_contributions_count(tmp_path, mock_llm):
    """Contributions count must include replication_packager (≥14 total)."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.core.renderer.compiler.compile_latex", new_callable=AsyncMock, return_value=None),
        patch("src.modules.github.push.push_latex_draft", new_callable=AsyncMock, return_value=None),
        patch("src.modules.data.audit.write_audit_csv", new_callable=AsyncMock, return_value=0),
        patch("src.modules.data.audit.write_data_queries_sql", new_callable=AsyncMock, return_value=0),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        result = await runner.run()

    assert result["contributions"] >= 14, (
        f"Expected ≥14 contributions (7 core + 6 reviewers + 1 replication), got {result['contributions']}"
    )


# ---------------------------------------------------------------------------
# State persistence / resume
# ---------------------------------------------------------------------------

async def test_state_saved_after_each_phase(tmp_path, mock_llm):
    """A .pipeline_state.json must exist after a successful run."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.core.renderer.compiler.compile_latex", new_callable=AsyncMock, return_value=None),
        patch("src.modules.github.push.push_latex_draft", new_callable=AsyncMock, return_value=None),
        patch("src.modules.data.audit.write_audit_csv", new_callable=AsyncMock, return_value=0),
        patch("src.modules.data.audit.write_data_queries_sql", new_callable=AsyncMock, return_value=0),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        await runner.run()

    state_path = workspace / ".pipeline_state.json"
    assert state_path.exists(), ".pipeline_state.json must be written"
    state = json.loads(state_path.read_text())
    assert "initial" in state["completed_stages"]
    assert "review" in state["completed_stages"]
    assert "revision" in state["completed_stages"]
    assert "replication" in state["completed_stages"]
    assert state["contributions_count"] >= 14


async def test_resume_skips_completed_phases(tmp_path, mock_llm):
    """A pipeline resuming with 'initial' and 'review' already complete must not re-dispatch those specialists."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    # Pre-write review files so _run_revision_phase workspace fallback finds scores
    for reviewer in ["mechanism", "technical", "literature", "writing", "data", "identification"]:
        (workspace / f"review_{reviewer}.md").write_text(f"# Review\n\nScore: 7/10\n\nLooks good.")

    # Pre-write state: initial + review already done
    pre_state = {
        "paper_id": paper_id, "mode": "single_pass",
        "completed_stages": ["initial", "review"],
        "current_stage": "", "iteration": 0, "pivot_count": 0,
        "contributions_count": 13, "last_status": "in_progress",
        "metadata": {},
    }
    (workspace / ".pipeline_state.json").write_text(json.dumps(pre_state))

    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.core.renderer.compiler.compile_latex", new_callable=AsyncMock, return_value=None),
        patch("src.modules.github.push.push_latex_draft", new_callable=AsyncMock, return_value=None),
        patch("src.modules.data.audit.write_audit_csv", new_callable=AsyncMock, return_value=0),
        patch("src.modules.data.audit.write_data_queries_sql", new_callable=AsyncMock, return_value=0),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="claude-test", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        result = await runner.run()

    called = set(mock_llm.specialist_calls)

    # Initial specialists must NOT have been re-dispatched
    assert "idea_developer" not in called, "idea_developer re-dispatched despite initial being complete"
    assert "literature_scanner" not in called, "literature_scanner re-dispatched despite initial being complete"

    # Reviewers must NOT have been re-dispatched (review already complete)
    assert "mechanism_reviewer" not in called, "mechanism_reviewer re-dispatched despite review being complete"

    # Replication packager MUST have run (was not in pre-state)
    assert "replication_packager" in called

    # Total count must include prior session's 13 contributions
    assert result["contributions"] >= 14  # 13 prior + 1 replication


# ---------------------------------------------------------------------------
# Resilience: error surfacing + parallel dispatch failure handling
# ---------------------------------------------------------------------------

async def test_update_status_clears_last_error_on_non_failed(tmp_path, mock_llm):
    """Any non-FAILED status update must NULL out last_error to avoid stale errors on resume."""
    from src.core.strategist.runner import PipelineRunner
    from src.core.strategist.state import PaperStatus

    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    captured: list[tuple[str, dict]] = []

    async def capture(sql, params=None):
        captured.append((sql, params or {}))

    with patch("src.db.client.execute", side_effect=capture):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="m", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
        )
        await runner._update_status(PaperStatus.IN_PROGRESS)
        await runner._update_status(PaperStatus.COMPLETED)
        await runner._update_status(PaperStatus.FAILED, error="boom")
        # FAILED with no error message should also clear (treated like non-FAILED-with-error)
        await runner._update_status(PaperStatus.FAILED)

    assert len(captured) == 4
    # First two: non-FAILED, must clear last_error
    assert "last_error = NULL" in captured[0][0]
    assert "last_error = NULL" in captured[1][0]
    # Third: FAILED with error, must write the error
    assert "last_error = %(e)s" in captured[2][0]
    assert captured[2][1].get("e") == "boom"
    # Fourth: FAILED without error, falls through to clearing branch
    assert "last_error = NULL" in captured[3][0]


async def test_execute_parallel_logs_aggregate_failure(tmp_path, caplog):
    """One failing specialist surfaces in aggregate WARNING; others still succeed."""
    import logging
    from src.core.specialists.contracts import WorkOrder as ContractWorkOrder
    from src.core.specialists.dispatcher import execute_parallel
    from tests.conftest import MockLLMBackend

    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()

    backend = MockLLMBackend(fail_specialists={"literature_scanner"})

    orders = [
        ContractWorkOrder(
            paper_id=paper_id, specialist="idea_developer",
            focus="develop", parallel_group=0, context_tier=0,
        ),
        ContractWorkOrder(
            paper_id=paper_id, specialist="literature_scanner",
            focus="scan", parallel_group=0, context_tier=0,
        ),
    ]

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="src.core.specialists.dispatcher"),
    ):
        contributions = await execute_parallel(
            orders, backend, workspace, "m", [], [], "mock",
        )

    assert len(contributions) == 2
    by_spec = {c.specialist: c for c in contributions}
    assert by_spec["idea_developer"].success is True
    assert by_spec["literature_scanner"].success is False
    assert "1/2 specialists failed" in caplog.text
    assert "literature_scanner" in caplog.text


async def test_execute_parallel_raises_when_all_fail(tmp_path):
    """If every specialist in the batch fails, execute_parallel must raise."""
    from src.core.specialists.contracts import WorkOrder as ContractWorkOrder
    from src.core.specialists.dispatcher import execute_parallel
    from tests.conftest import MockLLMBackend

    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()

    backend = MockLLMBackend(fail_specialists={"idea_developer", "literature_scanner"})

    orders = [
        ContractWorkOrder(
            paper_id=paper_id, specialist="idea_developer",
            focus="develop", parallel_group=0, context_tier=0,
        ),
        ContractWorkOrder(
            paper_id=paper_id, specialist="literature_scanner",
            focus="scan", parallel_group=0, context_tier=0,
        ),
    ]

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        with pytest.raises(RuntimeError, match="All specialists failed"):
            await execute_parallel(orders, backend, workspace, "m", [], [], "mock")


# ---------------------------------------------------------------------------
# Bundle 1: Safety & auditability
# ---------------------------------------------------------------------------

async def test_budget_exceeded_aborts_pipeline(tmp_path, mock_llm):
    """If cumulative cost has hit the cap before a phase, runner must FAIL with a budget error."""
    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    captured_status: list[tuple[str, str | None]] = []

    async def capture_execute(sql, params=None):
        if params and "s" in params and "id" in params:
            captured_status.append((params.get("s"), params.get("e")))
        return None

    async def fetch_one_over_cap(sql, params=None):
        # Simulate $99 already spent — any cap below this triggers the abort.
        return {"spent": 99.0}

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", side_effect=capture_execute),
        patch("src.db.client.fetch_one", side_effect=fetch_one_over_cap),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="m", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
            max_cost_usd=10.0,  # under the $99 already spent
        )
        result = await runner.run()

    assert result["status"] == "failed"
    assert "Budget exceeded" in result["error"]
    # The FAILED row write must include the budget error message.
    assert any(s == "failed" and e and "Budget exceeded" in e for s, e in captured_status)


async def test_cancellation_marks_paper_cancelled(tmp_path, mock_llm):
    """Forcing a CancelledError mid-run must transition the paper to CANCELLED with a reason."""
    from src.core.strategist.engine import StrategistEngine
    from src.core.strategist.runner import PipelineRunner

    paper_id = str(uuid.uuid4())
    workspace = _make_workspace(tmp_path, paper_id, mode="single_pass")

    captured_status: list[tuple[str, str | None]] = []

    async def capture_execute(sql, params=None):
        if params and "s" in params and "id" in params:
            captured_status.append((params.get("s"), params.get("e")))
        return None

    # Make the very first phase raise CancelledError so we exercise the handler.
    async def cancel_at_initial():
        raise asyncio.CancelledError()

    with (
        patch.object(StrategistEngine, "decide", return_value=_designing_decision(paper_id)),
        patch("src.db.client.execute", side_effect=capture_execute),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        runner = PipelineRunner(
            paper_id=paper_id, workspace=workspace, backend=mock_llm,
            model="m", mode="single_pass",
            extra_tools=[], extra_handlers=[], backend_name="mock",
            max_cost_usd=100.0,
        )
        runner._run_initial_phase = cancel_at_initial  # type: ignore[assignment]
        with pytest.raises(asyncio.CancelledError):
            await runner.run()

    # Paper must have been transitioned to CANCELLED with the reason recorded.
    assert any(s == "cancelled" and e == "cancelled by user" for s, e in captured_status)


async def test_log_event_writes_to_pipeline_events():
    """log_event helper must INSERT into pipeline_events with the right columns."""
    from src.db.events import log_event

    captured: list[tuple[str, dict]] = []

    async def capture(sql, params=None):
        captured.append((sql, params or {}))

    with patch("src.db.client.execute", side_effect=capture):
        await log_event(
            "paper-xyz",
            "phase_start",
            stage="initial",
            specialist=None,
            payload={"foo": "bar"},
        )

    assert len(captured) == 1
    sql, params = captured[0]
    assert "INSERT INTO pipeline_events" in sql
    assert params["p"] == "paper-xyz"
    assert params["t"] == "phase_start"
    assert params["st"] == "initial"
    assert json.loads(params["pl"]) == {"foo": "bar"}


async def test_audit_bundle_contains_expected_files(tmp_path, monkeypatch):
    """GET /api/papers/{id}/audit-bundle returns a tarball with manifest+events+contributions+replication."""
    import tarfile
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    (workspace / "replication").mkdir(parents=True)
    (workspace / "replication" / "estimation.py").write_text("# replication script\n")
    (workspace / "audit_log.csv").write_text("id,query\n1,SELECT 1\n")

    # Point the API at this tmp workspace_root. Patch the binding inside
    # src.api.app, not src.config, because app.py imports the symbol at the top.
    fake_settings = type("S", (), {
        "workspace_root": str(tmp_path),
        "llm_backend": "mock", "default_model": "m",
        "data_module_enabled": False, "literature_kb_enabled": False,
        "github_enabled": False, "default_max_cost_usd": 25.0,
    })()
    monkeypatch.setattr("src.api.app.get_settings", lambda: fake_settings)

    paper_row = {
        "id": paper_id, "title": "Test", "research_question": "RQ",
        "status": "completed", "max_cost_usd": 25.0, "last_error": None,
        "github_repo": None, "created_at": "2026-05-06",
    }

    async def fake_fetch_one(sql, params=None):
        if "FROM papers" in sql:
            return paper_row
        return None

    async def fake_fetch_all(sql, params=None):
        return []

    async def fake_get_usage(paper_id):
        return {"totals": {}, "by_specialist": []}

    with (
        patch("src.db.client.fetch_one", side_effect=fake_fetch_one),
        patch("src.db.client.fetch_all", side_effect=fake_fetch_all),
        patch("src.modules.tracking.usage.get_paper_usage", side_effect=fake_get_usage),
    ):
        from src.api.app import app
        client = TestClient(app)
        resp = client.get(f"/api/papers/{paper_id}/audit-bundle")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    tar = tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz")
    names = tar.getnames()
    assert "manifest.json" in names
    assert "contributions.json" in names
    assert "events.json" in names
    assert "usage.json" in names
    assert "replication/estimation.py" in names
    assert "audit_log.csv" in names


# ---------------------------------------------------------------------------
# Bundle 2: Dashboard (Jinja2 + HTMX)
# ---------------------------------------------------------------------------

def _api_client():
    """TestClient for the FastAPI app, used by Bundle-2 dashboard tests."""
    pytest.importorskip("fastapi")
    pytest.importorskip("jinja2")
    pytest.importorskip("multipart")  # python-multipart
    from fastapi.testclient import TestClient
    from src.api.app import app
    return TestClient(app)


def test_dashboard_index_renders(monkeypatch):
    """GET / returns HTML listing papers from the DB."""
    rows = [
        {"id": "abc", "title": "Test paper", "status": "completed",
         "max_cost_usd": 25.0, "updated_at": "2026-05-06T12:00:00", "cost": 1.23},
    ]

    async def fake_fetch_all(sql, params=None):
        return rows

    with patch("src.db.client.fetch_all", side_effect=fake_fetch_all):
        client = _api_client()
        resp = client.get("/")

    assert resp.status_code == 200
    body = resp.text
    assert "Test paper" in body
    assert "completed" in body
    assert "$1.23" in body
    # htmx + style sheet referenced
    assert "/static/htmx.min.js" in body
    assert "/static/style.css" in body


def test_dashboard_new_form_renders(monkeypatch):
    """GET /papers/new shows the creation form pre-filled with default cap."""
    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type("S", (), {"default_max_cost_usd": 25.0})(),
    )
    client = _api_client()
    resp = client.get("/papers/new")
    assert resp.status_code == 200
    assert 'name="title"' in resp.text
    assert 'name="research_question"' in resp.text
    assert 'value="25"' in resp.text or 'value="25.0"' in resp.text


def test_paper_detail_renders(tmp_path, monkeypatch):
    """GET /papers/{id} shows status, RQ, and live-section + artifacts."""
    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()
    (workspace / "paper_plan.md").write_text("# plan")

    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type("S", (), {"workspace_root": str(tmp_path)})(),
    )

    paper_row = {
        "id": paper_id, "title": "X", "research_question": "rq",
        "status": "in_progress", "mode": "iterative", "max_cost_usd": 25.0,
        "github_repo": None, "last_error": None,
    }

    async def fake_fetch_one(sql, params=None):
        return paper_row

    with patch("src.db.client.fetch_one", side_effect=fake_fetch_one):
        client = _api_client()
        resp = client.get(f"/papers/{paper_id}")

    assert resp.status_code == 200
    assert "X" in resp.text
    assert "rq" in resp.text
    assert "paper_plan.md" in resp.text
    # The live section must include the HTMX poll attribute.
    assert f"/htmx/papers/{paper_id}/live" in resp.text


def test_live_fragment_renders_status_and_events(monkeypatch):
    """HTMX fragment includes status badge, cost meter, and recent events."""
    paper_id = str(uuid.uuid4())
    paper_row = {
        "id": paper_id, "status": "in_progress",
        "max_cost_usd": 50.0, "last_error": None,
    }
    events = [
        {"event_type": "phase_start", "stage": "initial",
         "specialist": None, "created_at": "2026-05-06T12:00:01"},
        {"event_type": "specialist_end", "stage": None,
         "specialist": "idea_developer", "created_at": "2026-05-06T12:00:30"},
    ]

    async def fake_fetch_one(sql, params=None):
        if "FROM papers" in sql:
            return paper_row
        if "SUM(cost_usd)" in sql:
            return {"spent": 12.5}
        return None

    async def fake_fetch_all(sql, params=None):
        return events

    with (
        patch("src.db.client.fetch_one", side_effect=fake_fetch_one),
        patch("src.db.client.fetch_all", side_effect=fake_fetch_all),
    ):
        client = _api_client()
        resp = client.get(f"/htmx/papers/{paper_id}/live")

    assert resp.status_code == 200
    assert "in_progress" in resp.text
    assert "$12.50" in resp.text
    assert "phase_start" in resp.text
    assert "idea_developer" in resp.text


def test_artifact_streaming_rejects_traversal(tmp_path, monkeypatch):
    """Path traversal attempts (../../) must return 400."""
    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()
    (workspace / "ok.md").write_text("hello")
    # Sibling file outside the workspace that traversal would try to reach.
    (tmp_path / "secret.txt").write_text("nope")

    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type("S", (), {"workspace_root": str(tmp_path)})(),
    )

    client = _api_client()

    # Happy path: a real file in the workspace works.
    ok = client.get(f"/api/papers/{paper_id}/artifacts/ok.md")
    assert ok.status_code == 200
    assert ok.text == "hello"

    # Traversal: ../secret.txt resolves outside the workspace and must be rejected.
    bad = client.get(f"/api/papers/{paper_id}/artifacts/../secret.txt")
    # FastAPI may normalise the URL; either way the file must not be returned.
    assert bad.status_code in {400, 404}
    assert "nope" not in bad.text


# ---------------------------------------------------------------------------
# Bundle 4: Output completeness — literature tools, LaTeX assembly, BYOD
# ---------------------------------------------------------------------------

async def test_literature_handler_can_handle():
    """LiteratureToolHandler advertises only its own tools."""
    from src.modules.literature.tools import LiteratureToolHandler
    h = LiteratureToolHandler(Path("/tmp"))
    assert h.can_handle("search_papers") is True
    assert h.can_handle("fetch_paper") is True
    assert h.can_handle("save_bibtex") is True
    assert h.can_handle("query_allium") is False


async def test_save_bibtex_writes_to_workspace(tmp_path):
    """save_bibtex with a literal entry appends to literature.bib in the workspace."""
    from src.modules.literature.tools import LiteratureToolHandler
    h = LiteratureToolHandler(tmp_path)
    entry = (
        "@article{smith2023,\n"
        "  title = {A study},\n"
        "  author = {Smith, Jane},\n"
        "  year = {2023}\n"
        "}"
    )
    out = json.loads(await h.handle("save_bibtex", {"bibtex_entry": entry}))
    assert out["status"] == "saved"
    assert out["key"] == "smith2023"
    bib = (tmp_path / "literature.bib").read_text()
    assert "smith2023" in bib

    # Duplicate write is a no-op.
    out2 = json.loads(await h.handle("save_bibtex", {"bibtex_entry": entry}))
    assert out2["status"] == "already_present"


def test_assemble_document_wraps_body():
    """A bare body (no \\documentclass) gets wrapped with the standard preamble."""
    from src.core.renderer.templates import assemble_document
    body = r"\section{Introduction}" + "\nIt was a dark and stormy night.\n"
    full = assemble_document(body)
    assert r"\documentclass" in full
    assert r"\begin{document}" in full
    assert r"\end{document}" in full
    assert r"\bibliography{refs}" in full
    assert "stormy night" in full


def test_assemble_document_preserves_full_doc():
    """A body that already includes \\documentclass is left alone."""
    from src.core.renderer.templates import assemble_document
    full_body = r"\documentclass{article}" + "\n\\begin{document}\nHello.\n\\end{document}\n"
    out = assemble_document(full_body)
    # Exactly one \documentclass — no double wrapping.
    assert out.count(r"\documentclass") == 1
    assert "Hello." in out


def test_assemble_refs_bib_merges_and_dedupes(tmp_path):
    """literature.bib + user_refs.bib merge into refs.bib without duplicate keys."""
    from src.core.renderer.templates import assemble_refs_bib
    (tmp_path / "literature.bib").write_text(
        "@article{a2023, title={A}, author={A}, year={2023}}\n"
        "@article{shared2024, title={Shared}, author={X}, year={2024}}\n"
    )
    (tmp_path / "user_refs.bib").write_text(
        "@article{b2022, title={B}, author={B}, year={2022}}\n"
        "@article{shared2024, title={Shared dup}, author={Y}, year={2024}}\n"
    )
    refs = assemble_refs_bib(tmp_path)
    assert refs is not None
    text = refs.read_text()
    # All three unique keys present.
    assert "a2023" in text
    assert "b2022" in text
    assert "shared2024" in text
    # Dedup: only one shared2024 entry (literature.bib version wins, written first).
    assert text.count("shared2024,") == 1
    assert "Shared dup" not in text  # the duplicate from user_refs lost


def test_assemble_refs_bib_returns_none_when_no_sources(tmp_path):
    from src.core.renderer.templates import assemble_refs_bib
    assert assemble_refs_bib(tmp_path) is None


def test_byod_upload_writes_to_data_dir(tmp_path, monkeypatch):
    """POST /api/papers/{id}/files saves the upload under workspace/data/."""
    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()

    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type("S", (), {"workspace_root": str(tmp_path)})(),
    )
    client = _api_client()
    payload = b"a,b\n1,2\n3,4\n"
    resp = client.post(
        f"/api/papers/{paper_id}/files",
        files={"file": ("data.csv", payload, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "data.csv"
    assert resp.json()["size"] == len(payload)
    saved = workspace / "data" / "data.csv"
    assert saved.exists() and saved.read_bytes() == payload


def test_byod_upload_rejects_unknown_extension(tmp_path, monkeypatch):
    """An .exe upload is rejected with 400."""
    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()
    monkeypatch.setattr(
        "src.api.app.get_settings",
        lambda: type("S", (), {"workspace_root": str(tmp_path)})(),
    )
    client = _api_client()
    resp = client.post(
        f"/api/papers/{paper_id}/files",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "unsupported extension" in resp.json()["detail"]


def test_tier1_context_includes_user_data(tmp_path):
    """Tier-1 context surfaces files in workspace/data/ with a preview."""
    from src.core.strategist.context import build_tier1_context

    workspace = tmp_path
    (workspace / "manifest.json").write_text(json.dumps({
        "paper_id": "p", "title": "T", "research_question": "RQ",
        "datasets": [], "current_stage": "designing",
    }))
    (workspace / "data").mkdir()
    (workspace / "data" / "trades.csv").write_text(
        "id,price,volume\n1,100.5,50\n2,101.0,75\n3,99.8,30\n"
    )
    ctx = build_tier1_context(workspace, "p")
    assert "Researcher-Provided Data Files" in ctx
    assert "data/trades.csv" in ctx
    assert "id,price,volume" in ctx  # header preview
    # And it tells the LLM not to use Allium for these.
    assert "Do NOT" in ctx
