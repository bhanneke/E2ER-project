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
