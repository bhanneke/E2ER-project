"""Shared test fixtures and mock LLM backend."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.modules.llm.base import LLMBackend, ToolHandler, ToolLoopResult, TokenUsage


# ---------------------------------------------------------------------------
# Deterministic specialist outputs (filename, content)
# ---------------------------------------------------------------------------

_SPECIALIST_OUTPUTS: dict[str, tuple[str, str]] = {
    "idea_developer": (
        "paper_plan.md",
        "# Paper Plan\n\n## Research Question\nDoes X affect Y?\n\n## Propositions\n- H1: X increases Y.",
    ),
    "literature_scanner": (
        "literature_review.md",
        "# Literature Review\n\n## Background\nPrior work establishes the baseline.",
    ),
    "identification_strategist": (
        "identification_strategy.md",
        "# Identification Strategy\n\nWe use difference-in-differences around the treatment date.",
    ),
    "data_architect": (
        "data_dictionary.json",
        json.dumps({"datasets": [], "fields": [], "time_filter": None}, indent=2),
    ),
    "econometrics_specialist": (
        "econometric_spec.md",
        "# Econometric Specification\n\nOLS with two-way fixed effects.",
    ),
    "data_analyst": (
        "data_summary.md",
        "# Data Summary\n\nThe dataset contains 10,000 observations.",
    ),
    "paper_drafter": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\begin{document}\n\\title{Test}\n\\maketitle\nContent.\n\\end{document}",
    ),
    "section_writer": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\nTest.\n\\end{document}",
    ),
    "abstract_writer": (
        "abstract.tex",
        "\\begin{abstract}\nWe study whether X affects Y.\n\\end{abstract}",
    ),
    "latex_formatter": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\usepackage{booktabs}\n\\begin{document}\nFormatted.\n\\end{document}",
    ),
    # Reviewers: scores embedded in text so parse_review_output() finds them
    "mechanism_reviewer": (
        "review_mechanism.md",
        "# Mechanism Review\n\nScore: 7/10\n\nThe mechanism is plausible and well-motivated.",
    ),
    "technical_reviewer": (
        "review_technical.md",
        "# Technical Review\n\nScore: 7/10\n\nEconometrics are sound.",
    ),
    "literature_reviewer": (
        "review_literature.md",
        "# Literature Review\n\nScore: 7/10\n\nWell-grounded in prior work.",
    ),
    "writing_reviewer": (
        "review_writing.md",
        "# Writing Review\n\nScore: 7/10\n\nProse is clear.",
    ),
    "data_reviewer": (
        "review_data.md",
        "# Data Review\n\nScore: 7/10\n\nData sourcing is appropriate.",
    ),
    "identification_reviewer": (
        "review_identification.md",
        "# Identification Review\n\nScore: 7/10\n\nIdentification strategy is credible.",
    ),
    # V3 extensions
    "self_attacker": (
        "self_attack_report.json",
        json.dumps({"findings": [], "overall_severity": 1}, indent=2),
    ),
    "polish_formula": ("polish_formula.md", "Formula check passed."),
    "polish_numerics": ("polish_numerics.md", "Numeric consistency verified."),
    "polish_institutions": ("polish_institutions.md", "Institutional context accurate."),
    "polish_bibliography": ("polish_bibliography.md", "Bibliography complete."),
    "polish_equilibria": ("polish_equilibria.md", "Equilibrium conditions satisfied."),
    "revisor": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\begin{document}\nRevised draft.\n\\end{document}",
    ),
    "replication_packager": (
        "replication/estimation.py",
        "# Replication: estimation script\nimport pandas as pd\n",
    ),
}

# JSON the strategist engine returns from decide() for "designing" status
_DESIGNING_DECISION = {
    "action": "dispatch_parallel",
    "work_orders": [
        {"specialist": "idea_developer", "focus": "Develop idea", "parallel_group": 0},
        {"specialist": "literature_scanner", "focus": "Scan literature", "parallel_group": 0},
        {"specialist": "identification_strategist", "focus": "Develop ID strategy", "parallel_group": 0},
        {"specialist": "econometrics_specialist", "focus": "Specify model", "parallel_group": 1},
        {"specialist": "paper_drafter", "focus": "Draft paper", "parallel_group": 2},
        {"specialist": "abstract_writer", "focus": "Write abstract", "parallel_group": 2},
        {"specialist": "latex_formatter", "focus": "Format LaTeX", "parallel_group": 3},
    ],
    "rationale": "Initial design phase — run all core specialists.",
}

_CEILING_RESULT = {"verdict": "proceed_to_review", "reason": "Quality ceiling reached.", "suggested_pivots": []}
_SELF_ATTACK_RESULT = {"findings": [], "overall_severity": 1}


class MockLLMBackend(LLMBackend):
    """
    Deterministic LLM backend for testing.

    Specialist calls: writes the expected output file via the tool_handler so
    the FileToolHandler is exercised, then returns a ToolLoopResult with the
    canned content.

    Strategist calls: returns JSON decisions without hitting any API.
    """

    def __init__(self, fail_specialists: set[str] | None = None) -> None:
        self.specialist_calls: list[str] = []
        self.strategist_calls: list[str] = []
        # Names in this set will raise RuntimeError when invoked, simulating
        # transient backend failures. Used by parallel-dispatch tests.
        self._fail_specialists: set[str] = fail_specialists or set()

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler | None,
        max_turns: int = 30,
    ) -> ToolLoopResult:
        usage = TokenUsage(input_tokens=100, output_tokens=50)

        # Detect strategist vs. self-attack vs. ceiling vs. specialist
        if "adversarial reviewer" in system.lower():
            self.strategist_calls.append("self_attack")
            return ToolLoopResult(
                success=True, output=json.dumps(_SELF_ATTACK_RESULT), usage=usage
            )

        if "the strategist, the meta-agent" in system.lower():
            phase = self._detect_phase(messages)
            self.strategist_calls.append(phase)
            if phase == "ceiling":
                return ToolLoopResult(success=True, output=json.dumps(_CEILING_RESULT), usage=usage)
            return ToolLoopResult(
                success=True, output=json.dumps(_DESIGNING_DECISION), usage=usage
            )

        # Specialist call
        specialist = self._detect_specialist(system)
        self.specialist_calls.append(specialist)
        if specialist in self._fail_specialists:
            raise RuntimeError(f"simulated failure for {specialist}")
        filename, content = _SPECIALIST_OUTPUTS.get(
            specialist, (f"{specialist}.md", f"# Output\n\nTest output for {specialist}.")
        )

        # Write the file through the real FileToolHandler so path sandboxing is exercised
        if tool_handler is not None:
            try:
                # Create parent directory for nested paths (e.g. replication/estimation.py)
                if "/" in filename:
                    parent = filename.rsplit("/", 1)[0]
                    await tool_handler.handle("list_directory", {"path": "."})
                await tool_handler.handle("write_file", {"path": filename, "content": content})
            except Exception:
                pass  # handler may reject; that's still a valid test signal

        return ToolLoopResult(success=True, output=content, tool_calls_made=1, usage=usage)

    def _detect_phase(self, messages: list[dict[str, Any]]) -> str:
        text = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "ceiling" in text or "diminishing returns" in text:
            return "ceiling"
        return "designing"

    def _detect_specialist(self, system: str) -> str:
        system_lower = system.lower()
        for name in _SPECIALIST_OUTPUTS:
            if name.replace("_", " ") in system_lower:
                return name
        return "unknown"


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm() -> MockLLMBackend:
    return MockLLMBackend()


@pytest.fixture
def paper_id() -> str:
    return f"test-{uuid.uuid4()}"


@pytest.fixture
def tmp_workspace(tmp_path: Path, paper_id: str) -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    return ws


@pytest.fixture
def sample_manifest(tmp_workspace: Path, paper_id: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "paper_id": paper_id,
        "title": "Test Paper: DeFi Liquidity",
        "research_question": "How does concentrated liquidity in Uniswap v3 affect price discovery?",
        "datasets": [],
        "mode": "single_pass",
        "current_stage": "idea",
    }
    (tmp_workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


@pytest.fixture
def mock_db():
    """Patch all DB helper functions to avoid needing a live PostgreSQL instance."""

    async def _execute(sql: str, params: dict | None = None) -> None:
        pass

    async def _fetch_one(sql: str, params: dict | None = None) -> dict | None:
        if "INSERT INTO" in sql and "RETURNING id" in sql:
            return {"id": str(uuid.uuid4())}
        if "SELECT" in sql and "papers" in sql:
            return {
                "id": "test-uuid", "title": "Test", "status": "idea",
                "research_question": "Test RQ", "workspace": "/tmp/test",
                "mode": "single_pass", "github_repo": None,
                "created_at": "2026-01-01T00:00:00",
            }
        return None

    async def _fetch_all(sql: str, params: dict | None = None) -> list[dict]:
        return []

    with (
        patch("src.db.client.execute", side_effect=_execute),
        patch("src.db.client.fetch_one", side_effect=_fetch_one),
        patch("src.db.client.fetch_all", side_effect=_fetch_all),
    ):
        yield


@pytest.fixture(autouse=True)
def _block_real_db_pool(monkeypatch):
    """Hard-fail on any unmocked DB helper.

    The runner's _best_effort_finalize() (added to support graceful
    degradation on partial breakdowns) calls write_audit_csv/
    write_data_queries_sql in a finally block. Without mocks, those
    helpers try to connect to a real Postgres pool and hang for 30s+
    each, sometimes blocking the whole test process. This fixture
    swaps in fast no-ops so tests that don't explicitly need the DB
    don't pay that cost.

    Tests that DO need DB behavior should patch over these (the
    `with patch(...)` chain in those tests runs after this fixture
    and takes precedence).
    """
    from unittest.mock import AsyncMock
    monkeypatch.setattr("src.db.client.execute", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "src.db.client.fetch_one", AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.db.client.fetch_all", AsyncMock(return_value=[]),
    )
    # Note: write_audit_csv / write_data_queries_sql intentionally NOT mocked
    # here — they call the patched fetch_all internally and degrade to an
    # empty CSV / SQL file, which is the right behavior for runner tests.
    # Tests that exercise audit-module logic directly (test_audit.py) get
    # the real fetch_all mock that returns canned rows.
    yield
