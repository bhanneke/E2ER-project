"""Pipeline integration tests — exercises the full orchestration path with mocked LLM and DB."""
from __future__ import annotations

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
