"""Shared test fixtures and mock LLM backend."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.modules.llm.base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

# ---------------------------------------------------------------------------
# Deterministic specialist outputs (filename, content)
# ---------------------------------------------------------------------------

# Mock specialist outputs. Each must clear the v0.9 M4.3
# output-contract check (>= 100 non-whitespace chars for prose / code,
# non-empty JSON) so the contract check doesn't false-trip on stubby
# tests. The bodies match what a real (skill-driven) specialist would
# emit at minimum substance — a paragraph or three, not a one-liner.
_SPECIALIST_OUTPUTS: dict[str, tuple[str, str]] = {
    "idea_developer": (
        "paper_plan.md",
        "# Paper Plan\n\n## Research Question\nDoes X affect Y in the post-treatment "
        "sample? We test this on a panel of N units over T periods.\n\n## Propositions\n"
        "- H1: X increases Y monotonically.\n- H2: Effect heterogeneity by group.",
    ),
    "literature_scanner": (
        "literature_review.md",
        "# Literature Review\n\n## Background\nPrior work establishes the baseline "
        "relationship between X and Y in canonical settings. We extend along three "
        "dimensions: identification, sample, and outcome.\n\n## Gaps\nNo prior paper "
        "tests this jointly on the post-2020 sample.",
    ),
    "identification_strategist": (
        "identification_strategy.md",
        "# Identification Strategy\n\nWe use a staggered difference-in-differences "
        "design around the treatment date, with unit and time fixed effects. "
        "Pre-trends are tested via event-study coefficients. Robustness: alternative "
        "control groups, Callaway-Sant'Anna estimator.",
    ),
    "data_architect": (
        "data_dictionary.json",
        json.dumps(
            {
                "datasets": [{"name": "panel", "freq": "monthly"}],
                "fields": [{"name": "x", "type": "float"}, {"name": "y", "type": "float"}],
                "time_filter": {"start": "2020-01-01", "end": "2024-12-31"},
            },
            indent=2,
        ),
    ),
    "econometrics_specialist": (
        "econometric_spec.md",
        "# Econometric Specification\n\nOLS with two-way fixed effects. Standard "
        "errors clustered by unit. Pre-trend test via leads-and-lags event study. "
        "Robustness: TWFE, CCDH-Sant'Anna, sun-and-abraham. Reporting horizon: "
        "[-6, +12] months around treatment.",
    ),
    "data_analyst": (
        "data_summary.md",
        "# Data Summary\n\nThe dataset contains 10,000 observations across 100 "
        "units and 100 monthly periods. Outcome y has mean 0.05 (sd 0.12). Treatment "
        "variable x is binary, with 40% of units treated at some point in the sample.",
    ),
    "theory_specialist": (
        "model_spec.md",
        "# Formal Model\n\n## Setup\nAgents maximise utility subject to budget. "
        "Demand depends on price and income. Supply is competitive.\n\n"
        "## Propositions\nP1: Equilibrium price is monotone in supply.\n"
        "P2: Quantity adjusts to clear the market in the long run.",
    ),
    "paper_drafter": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\begin{document}\n\\title{Test Paper}\n"
        "\\maketitle\n\\section{Introduction}\nWe study whether X affects Y in a "
        "panel of N units. Our main finding: a 1-unit increase in X raises Y by "
        "0.04 (s.e. 0.01) on average, robust to controls.\n\\end{document}",
    ),
    "section_writer": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n"
        "We study whether X affects Y in a panel of N units. The headline finding "
        "is a 1-unit increase in X raising Y by 0.04 on average, robust to "
        "alternative specifications and sample restrictions.\n\\end{document}",
    ),
    "abstract_writer": (
        "abstract.tex",
        "\\begin{abstract}\nWe study whether X affects Y in a panel of N units "
        "over T periods. Using staggered difference-in-differences, we find a "
        "1-unit increase in X raises Y by 0.04 on average, robust to alternative "
        "controls.\n\\end{abstract}",
    ),
    "latex_formatter": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\usepackage{booktabs}\n\\usepackage{amsmath}\n"
        "\\begin{document}\nFormatted draft with tables and equations. "
        "\\section{Results}\nMain estimate 0.04 (s.e. 0.01).\n\\end{document}",
    ),
    # Reviewers: scores embedded in text so parse_review_output() finds them.
    # Bodies bulked to clear the M4.3 100-char threshold; a real review is
    # always longer than this.
    "mechanism_reviewer": (
        "review_mechanism.md",
        "# Mechanism Review\n\nScore: 7/10\n\nThe mechanism is plausible and "
        "well-motivated. The causal chain from X to Y is grounded in the literature. "
        "Minor concern: the heterogeneity story could be tighter.",
    ),
    "technical_reviewer": (
        "review_technical.md",
        "# Technical Review\n\nScore: 7/10\n\nEconometrics are sound. Standard "
        "errors are correctly clustered. The pre-trend test passes at conventional "
        "levels. Robustness to alternative DiD estimators is reported.",
    ),
    "literature_reviewer": (
        "review_literature.md",
        "# Literature Review Review\n\nScore: 7/10\n\nWell-grounded in prior work. "
        "Citations to Welch-Goyal, Campbell-Shiller, and Lettau-Ludvigson are "
        "appropriate. One omission: the recent Goyal-Welch update.",
    ),
    "writing_reviewer": (
        "review_writing.md",
        "# Writing Review\n\nScore: 7/10\n\nProse is clear. The introduction "
        "frames the contribution well. Tables are readable. Minor: some passive "
        "constructions in section 3 could be tightened.",
    ),
    "data_reviewer": (
        "review_data.md",
        "# Data Review\n\nScore: 7/10\n\nData sourcing is appropriate. The "
        "sample period is well-justified. Frequency choice (monthly) matches the "
        "outcome's dynamics. Missing-data treatment is documented.",
    ),
    "identification_reviewer": (
        "review_identification.md",
        "# Identification Review\n\nScore: 7/10\n\nIdentification strategy is "
        "credible. Pre-trends are flat by inspection. Parallel-trends assumption "
        "discussed honestly. Robust to event-study and Callaway-Sant'Anna.",
    ),
    # V3 extensions
    "self_attacker": (
        "self_attack_report.json",
        json.dumps({"findings": [], "overall_severity": 1}, indent=2),
    ),
    "polish_formula": (
        "polish_formula.md",
        "# Formula Polish\n\nFormula check passed. All math-mode expressions "
        "balance. Subscripts and superscripts are consistent. Notation matches "
        "the standard convention for panel data econometrics.",
    ),
    "polish_numerics": (
        "polish_numerics.md",
        "# Numerics Polish\n\nNumeric consistency verified. Table values match "
        "the estimation results JSON. Rounding is consistent at 3 significant "
        "figures. No rounding errors > 0.005.",
    ),
    "polish_institutions": (
        "polish_institutions.md",
        "# Institutions Polish\n\nInstitutional context accurate. References to "
        "the Fed, ECB, and regulatory framework are correct as of the sample end "
        "date. Acronyms expanded on first use.",
    ),
    "polish_bibliography": (
        "polish_bibliography.md",
        "# Bibliography Polish\n\nBibliography complete. All cited references "
        "appear in the bib file. Bibliography entries are formatted to one style "
        "(APA). No duplicates by DOI.",
    ),
    "polish_equilibria": (
        "polish_equilibria.md",
        "# Equilibria Polish\n\nEquilibrium conditions satisfied. The first-order "
        "conditions hold at the proposed equilibrium. Comparative statics signs "
        "match the propositions in the model section.",
    ),
    "revisor": (
        "paper_draft.tex",
        "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n"
        "Revised draft incorporating reviewer feedback. We tighten the "
        "identification discussion and expand the robustness section.\n"
        "\\end{document}",
    ),
    "replication_packager": (
        "replication/estimation.py",
        "# Replication: estimation script\nimport pandas as pd\nimport "
        "statsmodels.api as sm\n\n# Load and clean.\n# Estimate with TWFE.\n"
        "# Output to estimation_results.json.\nprint('estimation complete')\n",
    ),
}


# Minimal valid sidecar contents the mock writes for specialists with
# declared SPECIALIST_SIDECAR_ARTIFACTS. Real specialists fill these
# with substantive content; the mock writes enough to clear the M4.3
# contract check (parses as non-empty JSON with the field shape the
# downstream consumers expect).
_MOCK_SIDECAR_CONTENTS: dict[str, str] = {
    "summary_statistics.json": json.dumps({"n_observations": 100, "outcome": {"mean": 0.0, "sd": 1.0}}),
    "figure_spec.json": json.dumps({"figures": [{"name": "f1", "kind": "line"}]}),
    "estimation_results.json": json.dumps({"main": {"coef": 0.04, "se": 0.01, "t": 4.0, "p": 0.001}}),
}

# JSON the strategist engine returns from decide() for "designing" status
_DESIGNING_DECISION = {
    "action": "dispatch_parallel",
    "work_orders": [
        {"specialist": "idea_developer", "focus": "Develop idea", "parallel_group": 0},
        {"specialist": "literature_scanner", "focus": "Scan literature", "parallel_group": 0},
        {
            "specialist": "identification_strategist",
            "focus": "Develop ID strategy",
            "parallel_group": 0,
        },
        {"specialist": "econometrics_specialist", "focus": "Specify model", "parallel_group": 1},
        {"specialist": "paper_drafter", "focus": "Draft paper", "parallel_group": 2},
        {"specialist": "abstract_writer", "focus": "Write abstract", "parallel_group": 2},
        {"specialist": "latex_formatter", "focus": "Format LaTeX", "parallel_group": 3},
    ],
    "rationale": "Initial design phase — run all core specialists.",
}

_CEILING_RESULT = {
    "verdict": "proceed_to_review",
    "reason": "Quality ceiling reached.",
    "suggested_pivots": [],
}
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
        *,
        paper_id: str | None = None,  # noqa: ARG002 — interface parity with backends
        specialist: str | None = None,  # noqa: ARG002
    ) -> ToolLoopResult:
        usage = TokenUsage(input_tokens=100, output_tokens=50)

        # Detect strategist vs. self-attack vs. ceiling vs. specialist
        if "adversarial reviewer" in system.lower():
            self.strategist_calls.append("self_attack")
            return ToolLoopResult(success=True, output=json.dumps(_SELF_ATTACK_RESULT), usage=usage)

        if "the strategist, the meta-agent" in system.lower():
            phase = self._detect_phase(messages)
            self.strategist_calls.append(phase)
            if phase == "ceiling":
                return ToolLoopResult(success=True, output=json.dumps(_CEILING_RESULT), usage=usage)
            return ToolLoopResult(success=True, output=json.dumps(_DESIGNING_DECISION), usage=usage)

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
                    await tool_handler.handle("list_directory", {"path": "."})
                await tool_handler.handle("write_file", {"path": filename, "content": content})
                # v0.9 M4.3: real specialists with declared sidecars in
                # SPECIALIST_SIDECAR_ARTIFACTS produce them alongside the
                # primary file. The mock didn't pre-M4.3, so under the
                # new output-contract check it would now flip every
                # sidecar-bearing specialist to success=False. Write
                # minimal valid sidecars per declared contract so the
                # mock stays a faithful stand-in.
                from src.core.specialists.registry import SPECIALIST_SIDECAR_ARTIFACTS

                for sidecar in SPECIALIST_SIDECAR_ARTIFACTS.get(specialist, []):
                    await tool_handler.handle(
                        "write_file",
                        {"path": sidecar, "content": _MOCK_SIDECAR_CONTENTS.get(sidecar, "{}")},
                    )
            except Exception:
                pass  # handler may reject; that's still a valid test signal

        return ToolLoopResult(success=True, output=content, tool_calls_made=1, usage=usage)

    def _detect_phase(self, messages: list[dict[str, Any]]) -> str:
        text = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "ceiling" in text or "diminishing returns" in text:
            return "ceiling"
        return "designing"

    def _detect_specialist(self, system: str) -> str:
        """Detect which specialist this call is for.

        Match against the canonical role line emitted by
        `_build_system_prompt`: `You are the <Title Cased Name> specialist`.
        This is exactly one occurrence per system prompt and never appears
        in skill content. The earlier "look for the name anywhere in the
        system text" heuristic was brittle: skills that referenced other
        specialists by name (e.g. writing/cite-numbers-by-source mentions
        `econometrics specialist`) would cause paper_drafter calls to
        misroute to whichever name was named earliest in
        _SPECIALIST_OUTPUTS — silently writing the wrong file and
        breaking downstream tests.
        """
        import re

        m = re.search(r"You are the ([A-Z][A-Za-z ]+) specialist", system)
        if m:
            canonical = m.group(1).strip().lower().replace(" ", "_")
            if canonical in _SPECIALIST_OUTPUTS:
                return canonical
        # Fallback: prior substring heuristic, for system prompts that
        # don't follow the role-line convention (e.g. tests that build
        # synthetic prompts).
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
                "id": "test-uuid",
                "title": "Test",
                "status": "idea",
                "research_question": "Test RQ",
                "workspace": "/tmp/test",
                "mode": "single_pass",
                "github_repo": None,
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
    monkeypatch.setattr("src.db.client.execute", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "src.db.client.fetch_one",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.db.client.fetch_all",
        AsyncMock(return_value=[]),
    )
    # Note: write_audit_csv / write_data_queries_sql intentionally NOT mocked
    # here — they call the patched fetch_all internally and degrade to an
    # empty CSV / SQL file, which is the right behavior for runner tests.
    # Tests that exercise audit-module logic directly (test_audit.py) get
    # the real fetch_all mock that returns canned rows.
    yield
