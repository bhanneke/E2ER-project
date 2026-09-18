"""M4.3: specialist output-contract enforcement."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.specialists.contract_check import (
    _has_coefficients,
    check_artifact_nonempty,
    check_has_regression,
    check_specialist_artifacts,
)

# ── JSON checks (the M4 failure mode) ────────────────────────────────────────


def test_empty_dict_fails(tmp_path: Path):
    """The M4 regression: estimation_results.json == "{}" must fail."""
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert not c.ok
    assert "empty JSON" in c.reason


def test_empty_list_fails(tmp_path: Path):
    (tmp_path / "x.json").write_text("[]", encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert not c.ok and "empty JSON" in c.reason


def test_literal_null_fails(tmp_path: Path):
    (tmp_path / "x.json").write_text("null", encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert not c.ok


def test_whitespace_only_json_fails(tmp_path: Path):
    (tmp_path / "x.json").write_text("   \n\t  ", encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert not c.ok


def test_non_empty_dict_passes(tmp_path: Path):
    payload = {"in_sample_r2": 0.04, "oos_r2": -0.01, "clark_west": 1.83}
    (tmp_path / "x.json").write_text(json.dumps(payload), encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert c.ok


def test_non_empty_list_passes(tmp_path: Path):
    (tmp_path / "x.json").write_text(json.dumps([{"a": 1}]), encoding="utf-8")
    assert check_artifact_nonempty(tmp_path, "x.json").ok


def test_invalid_json_fails(tmp_path: Path):
    (tmp_path / "x.json").write_text("{not json}", encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert not c.ok and "invalid JSON" in c.reason


# ── Prose / code checks ──────────────────────────────────────────────────────


def test_short_markdown_fails(tmp_path: Path):
    """50-char .md is the kind of stub a half-broken specialist writes."""
    (tmp_path / "x.md").write_text("# Stub\n\nTODO.\n", encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.md")
    assert not c.ok and "non-whitespace chars" in c.reason


def test_real_markdown_passes(tmp_path: Path):
    body = ("Lorem ipsum dolor sit amet. " * 10).strip()
    (tmp_path / "x.md").write_text(body, encoding="utf-8")
    assert check_artifact_nonempty(tmp_path, "x.md").ok


def test_short_tex_fails(tmp_path: Path):
    (tmp_path / "x.tex").write_text(r"\section{Stub}", encoding="utf-8")
    assert not check_artifact_nonempty(tmp_path, "x.tex").ok


def test_short_python_fails(tmp_path: Path):
    """run_estimation.py = `pass` is also a contract violation."""
    (tmp_path / "x.py").write_text("pass\n", encoding="utf-8")
    assert not check_artifact_nonempty(tmp_path, "x.py").ok


def test_whitespace_only_md_fails(tmp_path: Path):
    """1000 whitespace chars are still 0 non-whitespace chars."""
    (tmp_path / "x.md").write_text(" " * 1000 + "\n" * 50, encoding="utf-8")
    c = check_artifact_nonempty(tmp_path, "x.md")
    assert not c.ok and "0 non-whitespace" in c.reason


# ── Missing / unknown extension ─────────────────────────────────────────────


def test_missing_file_fails(tmp_path: Path):
    c = check_artifact_nonempty(tmp_path, "nope.json")
    assert not c.ok and c.reason == "file not written"


def test_empty_file_fails(tmp_path: Path):
    (tmp_path / "x.json").touch()
    c = check_artifact_nonempty(tmp_path, "x.json")
    assert not c.ok and "empty" in c.reason


def test_nested_relative_path(tmp_path: Path):
    """SPECIALIST_ARTIFACTS uses paths like 'replication/estimation.py'."""
    (tmp_path / "replication").mkdir()
    (tmp_path / "replication" / "estimation.py").write_text(
        "import pandas as pd\nimport statsmodels.api as sm\n\nprint('hi')\n" * 4,
        encoding="utf-8",
    )
    assert check_artifact_nonempty(tmp_path, "replication/estimation.py").ok


def test_unknown_extension_passes_when_nonempty(tmp_path: Path):
    (tmp_path / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert check_artifact_nonempty(tmp_path, "x.csv").ok


# ── check_specialist_artifacts: primary + sidecars ──────────────────────────


def test_econometrics_specialist_m4_regression(tmp_path: Path):
    """The M4 case end-to-end: econometric_spec.md exists with substance,
    but estimation_results.json is empty → contract violation."""
    (tmp_path / "econometric_spec.md").write_text("# Specification\n\n" + "Real content. " * 20, encoding="utf-8")
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")
    checks = check_specialist_artifacts(tmp_path, "econometrics_specialist")
    by_path = {c.artifact: c for c in checks}
    assert by_path["econometric_spec.md"].ok
    assert not by_path["estimation_results.json"].ok
    assert "empty JSON" in by_path["estimation_results.json"].reason


def test_all_required_artifacts_present_passes(tmp_path: Path):
    (tmp_path / "econometric_spec.md").write_text("# Spec\n\n" + "Real content. " * 30, encoding="utf-8")
    (tmp_path / "estimation_results.json").write_text(
        json.dumps({"main": {"coefficients": {"treat": {"estimate": 0.04, "se": 0.01}}}}), encoding="utf-8"
    )
    failed = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert failed == []


def test_data_analyst_sidecars_checked(tmp_path: Path):
    """data_analyst's summary_statistics.json is hard-gated."""
    (tmp_path / "data_summary.md").write_text("# Data\n\n" + "Real content. " * 20, encoding="utf-8")
    (tmp_path / "summary_statistics.json").write_text("{}", encoding="utf-8")  # bad
    (tmp_path / "figure_spec.json").write_text(json.dumps({"figs": ["f1"]}), encoding="utf-8")
    failed = [c.artifact for c in check_specialist_artifacts(tmp_path, "data_analyst") if not c.ok]
    assert failed == ["summary_statistics.json"]


def test_data_analyst_figure_spec_is_best_effort_not_gated(tmp_path: Path):
    """figure_spec.json is a best-effort sidecar (SPECIALIST_OPTIONAL_SIDECARS):
    an empty one must NOT fail the contract when the required artifacts are
    present. This is the M5 re-run unblock — figures have no deterministic
    producer at the data-design boundary."""
    (tmp_path / "data_summary.md").write_text("# Data\n\n" + "Real content. " * 20, encoding="utf-8")
    (tmp_path / "summary_statistics.json").write_text(json.dumps({"n": 407}), encoding="utf-8")
    (tmp_path / "figure_spec.json").write_text("{}", encoding="utf-8")  # empty, but optional
    checks = check_specialist_artifacts(tmp_path, "data_analyst")
    failed = [c.artifact for c in checks if not c.ok]
    assert failed == []
    # figure_spec.json isn't even checked (skipped, not just passed).
    assert "figure_spec.json" not in [c.artifact for c in checks]


def test_unknown_specialist_returns_no_checks(tmp_path: Path):
    """If a specialist isn't in the registry, no contract enforcement.
    Better to be silent than to false-trip on undeclared outputs."""
    assert check_specialist_artifacts(tmp_path, "ghost_specialist") == []


# ── Integration: run_specialist flips success → False ──────────────────────


async def test_run_specialist_flips_success_on_contract_violation(tmp_workspace: Path, paper_id: str):
    """The M4.3 wire-in: a specialist that writes an empty
    estimation_results.json must come back as success=False with a
    'contract violation' error, regardless of the tool_loop's exit code."""
    from typing import Any
    from unittest.mock import patch

    from src.core.specialists.base import run_specialist
    from src.core.specialists.contracts import WorkOrder
    from src.modules.llm.base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

    class FakeSuccessBackend(LLMBackend):
        """tool_loop returns success but writes a hollow sidecar."""

        async def tool_loop(
            self,
            system: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            tool_handler: ToolHandler | None,
            max_turns: int = 30,
            *,
            paper_id: str | None = None,
            specialist: str | None = None,
        ) -> ToolLoopResult:
            # Write the primary artifact (substantive) so it passes,
            # but the sidecar as the M4 failure mode: literally "{}".
            assert tool_handler is not None
            await tool_handler.handle(
                "write_file",
                {"path": "econometric_spec.md", "content": "# Spec\n\n" + ("Substantive content. " * 30)},
            )
            await tool_handler.handle("write_file", {"path": "estimation_results.json", "content": "{}"})
            return ToolLoopResult(
                success=True, output="done", tool_calls_made=2, usage=TokenUsage(input_tokens=10, output_tokens=5)
            )

    work_order = WorkOrder(
        paper_id=paper_id,
        specialist="econometrics_specialist",
        focus="Specify the model.",
        context_tier=1,
    )

    # Patch save_usage + execute so the test doesn't need a DB.
    with (
        patch("src.core.specialists.base.save_usage", new=_async_noop),
        patch("src.core.specialists.base.compute_cost", return_value=0),
        patch("src.db.client.execute", new=_async_noop),
    ):
        contribution = await run_specialist(
            work_order,
            backend=FakeSuccessBackend(),
            workspace=tmp_workspace,
            model="claude-test",
            extra_tools=[],
            extra_handlers=[],
            backend_name="mock",
        )

    assert contribution.success is False
    assert "contract violation" in contribution.error
    assert "estimation_results.json" in contribution.error
    assert "empty JSON" in contribution.error
    # The primary artifact (econometric_spec.md) was substantive — it
    # shouldn't appear in the violation list.
    assert "econometric_spec.md" not in contribution.error


async def _async_noop(*args, **kwargs):
    return None


# ── econometrics: results JSON must hold an actual regression ─────────────────


def test_has_coefficients_finds_nested_block():
    assert _has_coefficients({"main": {"coefficients": {"x": {"estimate": 1.0}}}})
    assert _has_coefficients({"raw_gap": {"coefficients": {"const": {}, "t": {}}}})
    assert not _has_coefficients({"_note": "n", "summary": {"mean": 3}})
    assert not _has_coefficients({"main": {"coefficients": {}}})  # empty block


def test_check_has_regression(tmp_path: Path):
    good = tmp_path / "g"
    good.mkdir()
    (good / "estimation_results.json").write_text(
        json.dumps({"main": {"coefficients": {"treat": {"estimate": -0.01, "p_value": 0.0}}}})
    )
    assert check_has_regression(good, "estimation_results.json").ok

    bad = tmp_path / "b"
    bad.mkdir()
    (bad / "estimation_results.json").write_text(json.dumps({"_note": "x", "raw_gap_mean": 0.05}))
    c = check_has_regression(bad, "estimation_results.json")
    assert not c.ok and "coefficients" in c.reason


def test_econometrics_gate_flags_descriptive_only(tmp_path: Path):
    (tmp_path / "econometric_spec.md").write_text("# Spec\n" + "x " * 100)
    (tmp_path / "estimation_results.json").write_text(json.dumps({"_note": "no model", "means": {"a": 1}}))
    failed = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert any("no estimated regression" in c.reason for c in failed)


def test_econometrics_gate_passes_with_real_regression(tmp_path: Path):
    (tmp_path / "econometric_spec.md").write_text("# Spec\n" + "x " * 100)
    (tmp_path / "estimation_results.json").write_text(
        json.dumps({"main": {"coefficients": {"treat": {"estimate": -0.01}}, "diagnostics": {"n": 100}}})
    )
    assert all(c.ok for c in check_specialist_artifacts(tmp_path, "econometrics_specialist"))


# ---------------------------------------------------------------------------
# The draft may REFERENCE tables; it may not CONTAIN them.
#
# In the 2026-08-05 validation cell the renderer produced three table files
# and the draft `\input`-ed none of them, carrying four inline `tabular`
# blocks under the same labels with numbers the model wrote itself. 53 of 110
# values traced to nothing. Nothing forbade it.
# ---------------------------------------------------------------------------


def _draft(tmp_path: Path, body: str) -> Path:
    (tmp_path / "paper_draft.tex").write_text("\\begin{document}\n" + body + "\n\\end{document}\n" + "x " * 100)
    return tmp_path


def test_inline_tabular_in_draft_is_a_violation(tmp_path: Path):
    from src.core.specialists.contract_check import check_no_inline_tables

    ws = _draft(tmp_path, "\\begin{tabular}{lc}\nTreatment & 0.42 \\\\\n\\end{tabular}")
    check = check_no_inline_tables(ws)
    assert check.ok is False
    assert "inline tabular" in check.reason


def test_input_referenced_tables_are_fine(tmp_path: Path):
    from src.core.specialists.contract_check import check_no_inline_tables

    ws = _draft(tmp_path, "See Table~\\ref{tab:main}.\n\\input{tables/main.tex}")
    assert check_no_inline_tables(ws).ok is True


def test_inline_table_ban_is_verification_not_reliability(tmp_path: Path):
    """It is about whether numbers trace, so a regime may shadow it — unlike a
    missing or unparseable artifact."""
    from src.core.specialists.contract_check import KIND_VERIFICATION, check_no_inline_tables

    ws = _draft(tmp_path, "\\begin{tabular}{lc}\nx & 1 \\\\\n\\end{tabular}")
    assert check_no_inline_tables(ws).kind == KIND_VERIFICATION


def test_drafting_specialists_get_the_inline_table_check(tmp_path: Path):
    ws = _draft(tmp_path, "\\begin{tabular}{lc}\nx & 1 \\\\\n\\end{tabular}")
    failed = [c for c in check_specialist_artifacts(ws, "paper_drafter") if not c.ok]
    assert any("inline tabular" in c.reason for c in failed)


def test_missing_draft_is_not_an_inline_table_violation(tmp_path: Path):
    """Absence is the non-empty check's business; don't double-report it."""
    from src.core.specialists.contract_check import check_no_inline_tables

    assert check_no_inline_tables(tmp_path).ok is True
