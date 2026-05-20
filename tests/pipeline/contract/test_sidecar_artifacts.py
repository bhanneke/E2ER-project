"""v0.5: machine-readable JSON sidecar contract for verify_numbers.

Pre-v0.5, every specialist was told to write EXACTLY ONE file. Even
when a skill (e.g. data/figure-spec.md) described a JSON sidecar, the
system prompt's single-file rule overrode it and the JSON never
appeared. The 2026-05-20 live runs confirmed this empirically: both
the empirical paper and the theoretical paper produced
number_verification.json with skipped_reason='no source JSON files
found' — the gate was effectively a no-op.

This module pins:
1. The registry declares which sidecars each specialist must produce.
2. _inject_context auto-populates sidecar_artifacts from the registry.
3. The prompt's Required Output block lists every required file when
   sidecars exist, and reverts to the single-file rule when they don't.
4. Each schema skill file referenced by the registry actually exists.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from src.core.specialists.contracts import WorkOrder
from src.core.specialists.dispatcher import _inject_context
from src.core.specialists.registry import (
    SPECIALIST_ARTIFACTS,
    SPECIALIST_SIDECAR_ARTIFACTS,
    SPECIALIST_SKILLS,
)

# ---------------------------------------------------------------------------
# Registry shape — the sidecar contract
# ---------------------------------------------------------------------------


class TestSidecarRegistry:
    def test_data_analyst_emits_summary_statistics_and_figures(self):
        sidecars = SPECIALIST_SIDECAR_ARTIFACTS["data_analyst"]
        assert "summary_statistics.json" in sidecars, (
            "data_analyst MUST emit summary_statistics.json — verify_numbers "
            "depends on it as the source-of-truth for descriptive statistics"
        )
        assert "figure_spec.json" in sidecars, (
            "data_analyst MUST emit figure_spec.json — the data/figure-spec "
            "skill teaches the schema and the renderer consumes it"
        )

    def test_econometrics_specialist_emits_estimation_results(self):
        sidecars = SPECIALIST_SIDECAR_ARTIFACTS["econometrics_specialist"]
        assert "estimation_results.json" in sidecars, (
            "econometrics_specialist MUST emit estimation_results.json — "
            "every coefficient/SE/t-stat in the paper's regression tables "
            "must trace back to a value in this file or verify_numbers "
            "flags it as a hallucination"
        )

    def test_no_phantom_specialists_in_sidecar_dict(self):
        """Every key in SPECIALIST_SIDECAR_ARTIFACTS must also be in
        SPECIALIST_ARTIFACTS (the source-of-truth specialist list)."""
        unknown = set(SPECIALIST_SIDECAR_ARTIFACTS) - set(SPECIALIST_ARTIFACTS)
        assert not unknown, f"sidecars declared for unknown specialists: {unknown}"

    def test_primary_artifact_not_listed_as_sidecar(self):
        """The primary output_file must NOT also appear in sidecar_artifacts —
        the prompt would otherwise list it twice."""
        for specialist, sidecars in SPECIALIST_SIDECAR_ARTIFACTS.items():
            primary = SPECIALIST_ARTIFACTS.get(specialist)
            if primary:
                assert primary not in sidecars, (
                    f"{specialist}'s primary artifact {primary} is also "
                    f"listed in its sidecar list — the prompt would "
                    f"duplicate the file in 'Required Output'"
                )


# ---------------------------------------------------------------------------
# Schema skill files actually exist
# ---------------------------------------------------------------------------


class TestSchemaSkillsExist:
    def test_summary_statistics_schema_skill_exists(self):
        skill_path = Path(__file__).resolve().parents[3] / "skills" / "files" / "data" / "summary-statistics-schema.md"
        assert skill_path.exists(), (
            f"summary-statistics-schema.md missing at {skill_path} — without it "
            f"the data_analyst has no reference for the JSON shape"
        )

    def test_estimation_results_schema_skill_exists(self):
        skill_path = (
            Path(__file__).resolve().parents[3] / "skills" / "files" / "econometrics" / "estimation-results-schema.md"
        )
        assert skill_path.exists(), (
            f"estimation-results-schema.md missing at {skill_path} — without "
            f"it the econometrics_specialist has no reference for the JSON shape"
        )

    def test_data_analyst_loads_summary_schema_skill(self):
        skills = SPECIALIST_SKILLS["data_analyst"]
        assert "data/summary-statistics-schema" in skills, (
            "data_analyst's skill list must include data/summary-statistics-schema "
            "so the schema is injected into its system prompt"
        )

    def test_econometrics_specialist_loads_estimation_schema_skill(self):
        skills = SPECIALIST_SKILLS["econometrics_specialist"]
        assert "econometrics/estimation-results-schema" in skills, (
            "econometrics_specialist's skill list must include econometrics/estimation-results-schema"
        )


# ---------------------------------------------------------------------------
# _inject_context auto-populates sidecar_artifacts
# ---------------------------------------------------------------------------


class TestInjectContextPopulatesSidecars:
    def _wo(self, specialist: str, ws: Path) -> WorkOrder:
        return WorkOrder(
            paper_id=str(uuid.uuid4()),
            specialist=specialist,
            focus="test",
        )

    def test_data_analyst_gets_sidecars_from_registry(self, tmp_path):
        wo = self._wo("data_analyst", tmp_path)
        assert wo.sidecar_artifacts == []  # empty by default
        injected = _inject_context(wo, tmp_path)
        assert set(injected.sidecar_artifacts) == set(SPECIALIST_SIDECAR_ARTIFACTS["data_analyst"])

    def test_econometrics_gets_sidecars_from_registry(self, tmp_path):
        wo = self._wo("econometrics_specialist", tmp_path)
        injected = _inject_context(wo, tmp_path)
        assert "estimation_results.json" in injected.sidecar_artifacts

    def test_specialist_without_sidecars_gets_empty_list(self, tmp_path):
        """idea_developer is not in SPECIALIST_SIDECAR_ARTIFACTS — must
        receive empty sidecar list (the prompt falls back to EXACTLY-ONE)."""
        wo = self._wo("idea_developer", tmp_path)
        injected = _inject_context(wo, tmp_path)
        assert injected.sidecar_artifacts == []

    def test_caller_provided_sidecars_not_overwritten(self, tmp_path):
        """If the strategist explicitly set sidecars, _inject_context must
        not clobber them with the registry default."""
        wo = WorkOrder(
            paper_id=str(uuid.uuid4()),
            specialist="data_analyst",
            focus="test",
            sidecar_artifacts=["custom_thing.json"],
        )
        injected = _inject_context(wo, tmp_path)
        assert injected.sidecar_artifacts == ["custom_thing.json"]


# ---------------------------------------------------------------------------
# Prompt construction — multi-file vs single-file branches
# ---------------------------------------------------------------------------


class TestPromptMultiFileOutput:
    def _build(self, specialist: str, sidecars: list[str] | None = None) -> str:
        from src.core.specialists.base import _build_user_prompt

        wo = WorkOrder(
            paper_id=str(uuid.uuid4()),
            specialist=specialist,
            focus="test focus",
            output_file=SPECIALIST_ARTIFACTS.get(specialist, "out.md"),
            sidecar_artifacts=sidecars or [],
        )
        return _build_user_prompt(wo)

    def test_single_file_path_when_no_sidecars(self):
        """Specialists without sidecars get the original EXACTLY ONE FILE
        instruction. This is the v0.4.x behaviour for writers, reviewers,
        polish, etc. that genuinely produce one artifact."""
        prompt = self._build("idea_developer", sidecars=[])
        assert "EXACTLY ONE file" in prompt
        assert "Required Output\n" in prompt
        # The multi-file header should NOT appear
        assert "multiple files" not in prompt

    def test_multi_file_path_when_sidecars_present(self):
        prompt = self._build(
            "data_analyst",
            sidecars=["summary_statistics.json", "figure_spec.json"],
        )
        # New header
        assert "Required Output — multiple files" in prompt
        # Old single-file language must NOT appear
        assert "EXACTLY ONE file" not in prompt
        # Primary file listed
        assert "data_summary.md" in prompt
        # Each sidecar listed
        assert "summary_statistics.json" in prompt
        assert "figure_spec.json" in prompt

    def test_multi_file_prompt_mentions_empty_object_fallback(self):
        """The 'write {} if data was unavailable' rule must be in the prompt —
        without it the specialist may omit the file entirely, which
        downstream tools (verify_numbers) can't distinguish from a
        genuine omission."""
        prompt = self._build("data_analyst", sidecars=["summary_statistics.json"])
        # The prompt explicitly instructs `{}` on failure
        assert "{}" in prompt
        # And explains the rationale (empty != missing)
        assert "empty" in prompt.lower() and "missing" in prompt.lower()

    def test_multi_file_prompt_rejects_subdirectories(self):
        """Same anti-nesting rule as the single-file path. Without it
        we'd reintroduce the CLI-backend nested-write recovery bug."""
        prompt = self._build("data_analyst", sidecars=["summary_statistics.json"])
        assert "Do NOT create subdirectories" in prompt

    def test_multi_file_prompt_enforces_valid_json_for_sidecars(self):
        prompt = self._build("data_analyst", sidecars=["summary_statistics.json"])
        assert "valid JSON" in prompt
        assert "plain numbers" in prompt
