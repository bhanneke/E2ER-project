"""Tests for the methodology field — empirical | theoretical | mixed.

These tests pin the contract that lets users select between empirical
(default), theoretical (formal model only), and mixed (both) papers
when creating a paper.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Registry contract
# ---------------------------------------------------------------------------


def test_theory_specialist_registered():
    """theory_specialist must be in SPECIALIST_ARTIFACTS and SPECIALIST_SKILLS."""
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SKILLS

    assert "theory_specialist" in SPECIALIST_ARTIFACTS, (
        "theory_specialist missing from SPECIALIST_ARTIFACTS — strategist will "
        "have no canonical output filename to inject when dispatching it"
    )
    assert SPECIALIST_ARTIFACTS["theory_specialist"] == "model_spec.md"

    assert "theory_specialist" in SPECIALIST_SKILLS
    skills = SPECIALIST_SKILLS["theory_specialist"]
    # Skills must be ones that actually exist on disk
    assert "base/economist" in skills
    assert "modeling/game-theory" in skills


def test_theory_specialist_skill_files_exist():
    """The skill files referenced by theory_specialist must exist on disk."""
    from src.core.specialists.registry import SPECIALIST_SKILLS

    skills_dir = Path(__file__).resolve().parent.parent / "skills" / "files"
    for skill in SPECIALIST_SKILLS["theory_specialist"]:
        path = skills_dir / f"{skill}.md"
        assert path.exists(), f"theory_specialist references missing skill file: {path}"


# ---------------------------------------------------------------------------
# Strategist prompt contract
# ---------------------------------------------------------------------------


def test_strategist_prompt_lists_theory_specialist():
    """The strategist's specialist roster must include theory_specialist
    so the LLM knows it's a valid dispatch target."""
    from src.core.strategist import engine

    assert "theory_specialist" in engine._STRATEGIST_SYSTEM, (
        "Strategist system prompt does not list theory_specialist — the LLM will never dispatch it"
    )


def test_strategist_prompt_documents_methodology_dispatch():
    """The strategist must know the dispatch rule for each methodology."""
    from src.core.strategist import engine

    prompt = engine._STRATEGIST_SYSTEM
    for required in ("empirical", "theoretical", "mixed"):
        assert required in prompt, f"Strategist prompt missing methodology '{required}'"
    assert "Methodology" in prompt, "Strategist must reference the Methodology context field"


# ---------------------------------------------------------------------------
# Manifest persistence
# ---------------------------------------------------------------------------


def test_methodology_surfaces_in_tier0_context(tmp_path):
    """build_tier0_context must include the manifest's methodology so the
    strategist sees it on every decide() call."""
    from src.core.strategist.context import build_tier0_context

    pid = "p-test"
    workspace = tmp_path / pid
    workspace.mkdir()
    (workspace / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": pid,
                "title": "T",
                "research_question": "RQ?",
                "methodology": "theoretical",
                "datasets": [],
                "current_stage": "idea",
            }
        )
    )

    ctx = build_tier0_context(workspace, pid)
    assert "Methodology: theoretical" in ctx, f"tier0 context did not surface methodology; got:\n{ctx}"


def test_methodology_defaults_to_empirical_when_missing(tmp_path):
    """Older manifests without the methodology field must default to empirical."""
    from src.core.strategist.context import build_tier0_context

    pid = "p-legacy"
    workspace = tmp_path / pid
    workspace.mkdir()
    (workspace / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": pid,
                "title": "Legacy paper",
                "research_question": "RQ?",
                "datasets": [],
                "current_stage": "idea",
            }
        )
    )

    ctx = build_tier0_context(workspace, pid)
    assert "Methodology: empirical" in ctx


# ---------------------------------------------------------------------------
# API contract — methodology field accepted and validated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("methodology", ["empirical", "theoretical", "mixed"])
def test_create_paper_accepts_valid_methodology(methodology, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        from src.api.app import app

        client = TestClient(app)
        resp = client.post(
            "/api/papers",
            json={
                "title": "T",
                "research_question": "RQ?",
                "mode": "single_pass",
                "methodology": methodology,
                "max_cost_usd": 1.0,
            },
        )

    assert resp.status_code == 200, f"create_paper rejected methodology={methodology}: {resp.text}"
    paper_id = resp.json()["paper_id"]

    # Manifest written with correct methodology
    manifest = json.loads((tmp_path / paper_id / "manifest.json").read_text())
    assert manifest["methodology"] == methodology


def test_create_paper_rejects_invalid_methodology(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        from src.api.app import app

        client = TestClient(app)
        resp = client.post(
            "/api/papers",
            json={
                "title": "T",
                "research_question": "RQ?",
                "methodology": "qualitative",  # not in {empirical, theoretical, mixed}
                "max_cost_usd": 1.0,
            },
        )

    assert resp.status_code == 400


def test_create_paper_methodology_defaults_to_empirical(tmp_path, monkeypatch):
    """Omitting methodology in the request must default to empirical for back-compat."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        from src.api.app import app

        client = TestClient(app)
        resp = client.post(
            "/api/papers",
            json={
                "title": "T",
                "research_question": "RQ?",
                "max_cost_usd": 1.0,
            },
        )

    assert resp.status_code == 200
    paper_id = resp.json()["paper_id"]
    manifest = json.loads((tmp_path / paper_id / "manifest.json").read_text())
    assert manifest["methodology"] == "empirical"


# ---------------------------------------------------------------------------
# Mocked specialist invocation
# ---------------------------------------------------------------------------


async def test_theory_specialist_writes_model_spec(tmp_workspace, mock_llm, paper_id):
    """When a theory_specialist work order is executed, it writes model_spec.md
    via the FileToolHandler. This pins the artifact contract."""
    from src.core.specialists.base import run_specialist
    from src.core.specialists.contracts import WorkOrder

    work_order = WorkOrder(
        paper_id=paper_id,
        specialist="theory_specialist",
        focus="Develop a formal model for the research question.",
        context_tier=1,
    )

    contribution = await run_specialist(
        work_order,
        backend=mock_llm,
        workspace=tmp_workspace,
        model="claude-test",
        extra_tools=[],
        extra_handlers=[],
        backend_name="mock",
    )

    assert contribution.success, f"theory_specialist run failed: {contribution.error}"
    artifact = tmp_workspace / "model_spec.md"
    assert artifact.exists(), "theory_specialist must write model_spec.md"
    assert "Formal Model" in artifact.read_text() or "Propositions" in artifact.read_text()
