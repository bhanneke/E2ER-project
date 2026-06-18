"""Runner-side post-specialist execution — make the right thing happen."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.specialists.post_execution import (
    EXECUTION_CONVENTIONS,
    _is_populated,
    maybe_execute_specialist_script,
)

# ── _is_populated ────────────────────────────────────────────────────


def test_sidecar_populated_with_real_json(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"main": {"coef": 0.04}}), encoding="utf-8")
    assert _is_populated(path) is True


def test_sidecar_not_populated_empty_dict(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text("{}", encoding="utf-8")
    assert _is_populated(path) is False


def test_sidecar_not_populated_empty_list(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text("[]", encoding="utf-8")
    assert _is_populated(path) is False


def test_sidecar_not_populated_null(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text("null", encoding="utf-8")
    assert _is_populated(path) is False


def test_sidecar_not_populated_whitespace(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text("   \n\t ", encoding="utf-8")
    assert _is_populated(path) is False


def test_sidecar_not_populated_invalid_json(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text("{not json}", encoding="utf-8")
    assert _is_populated(path) is False


def test_sidecar_not_populated_missing(tmp_path: Path):
    assert _is_populated(tmp_path / "nope.json") is False


# ── No convention for the specialist → no-op ───────────────────────────────


def test_specialist_without_convention_is_noop(tmp_path: Path):
    attempt = maybe_execute_specialist_script(tmp_path, "literature_scanner")
    assert attempt.ran is False
    assert attempt.returncode is None
    assert "no execution convention" in attempt.reason


def test_econometrics_registered_in_conventions():
    """If this fails, the wire-in has drifted away from the diagnosis."""
    convention = EXECUTION_CONVENTIONS["econometrics_specialist"]
    assert "run_estimation.py" in convention.script_candidates
    # Canonical name must be tried first.
    assert convention.script_candidates[0] == "run_estimation.py"
    assert convention.sidecar == "estimation_results.json"
    assert convention.log == "run_estimation.log"
    assert convention.timeout_seconds > 0


def test_data_analyst_registered_in_conventions():
    convention = EXECUTION_CONVENTIONS["data_analyst"]
    assert convention.sidecar == "summary_statistics.json"
    assert convention.script_candidates  # non-empty


# ── Script missing → no-op ─────────────────────────────────────────────────


def test_no_script_in_workspace_is_noop(tmp_path: Path):
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is False
    assert attempt.populated_sidecar is False
    assert "no runnable script" in attempt.reason


# ── Script discovery: non-canonical filename, found by content ─────────────


def test_discovers_script_by_content_when_not_canonically_named(tmp_path: Path):
    """A specialist that named its script something off-list but writes the
    canonical sidecar must be discovered by content and executed. The
    filename here is deliberately NOT in script_candidates, forcing the
    glob path. (`analyze.py` IS a candidate and is covered by the fast path.)"""
    (tmp_path / "welch_goyal_analysis.py").write_text(
        "import json, pathlib\n"
        "pathlib.Path('estimation_results.json').write_text("
        "  json.dumps({'dp': {'oos_r2': 0.009}}))\n"
        "print('analyzed')\n",
        encoding="utf-8",
    )
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is True
    assert attempt.returncode == 0
    assert attempt.discovered is True
    assert attempt.populated_sidecar is True
    assert attempt.script == "welch_goyal_analysis.py"


# ── Output normalization: script writes an alternate output name ───────────


def test_normalizes_alternate_output_onto_canonical_sidecar(tmp_path: Path):
    """The exact M5 re-run case: `analyze.py` writes `analysis_output.json`
    (an alternate), not `estimation_results.json`. The runner runs it and
    copies the populated alternate onto the canonical sidecar so M4.3 sees it."""
    (tmp_path / "analyze.py").write_text(
        "import json, pathlib\n"
        "pathlib.Path('analysis_output.json').write_text("
        "  json.dumps({'dp': {'is_r2': 0.011, 'oos_r2': 0.009, 'cw': 1.20}}))\n"
        "print('done')\n",
        encoding="utf-8",
    )
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is True
    assert attempt.populated_sidecar is True
    assert attempt.normalized_from == "analysis_output.json"
    data = json.loads((tmp_path / "estimation_results.json").read_text())
    assert data["dp"]["oos_r2"] == 0.009
    # Audit log records the normalization.
    log = (tmp_path / "run_estimation.log").read_text(encoding="utf-8")
    assert "analysis_output.json" in log


# ── Relative workspace path (the runner's real call shape) ─────────────────


def test_runs_with_relative_workspace_path(tmp_path: Path, monkeypatch):
    """Regression: the runner passes a cwd-relative workspace path (e.g.
    `Tests/workspaces/<id>`). The first version joined it onto
    `cwd=workspace`, doubling the prefix
    (`<ws>/<ws>/run_estimation.py`) so the subprocess exited 2 and the
    sidecar stayed `{}`. Resolving the workspace to absolute fixes it.
    The other tests use an absolute `tmp_path`, which masked this."""
    ws = tmp_path / "Tests" / "workspaces" / "abc"
    ws.mkdir(parents=True)
    (ws / "run_estimation.py").write_text(
        "import json, pathlib\n"
        "pathlib.Path('estimation_results.json').write_text(json.dumps({'dp': {'oos_r2': 0.009}}))\n",
        encoding="utf-8",
    )
    (ws / "estimation_results.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    attempt = maybe_execute_specialist_script(Path("Tests/workspaces/abc"), "econometrics_specialist")
    assert attempt.ran is True
    assert attempt.returncode == 0, f"script failed: {attempt.reason}"
    assert attempt.populated_sidecar is True
    data = json.loads((ws / "estimation_results.json").read_text())
    assert data["dp"]["oos_r2"] == 0.009


# ── Sidecar already populated → no-op (idempotent) ─────────────────────────


def test_populated_sidecar_skips_execution(tmp_path: Path):
    (tmp_path / "run_estimation.py").write_text(
        # If this ran, it would crash — but it shouldn't run.
        "raise RuntimeError('should not have been executed')",
        encoding="utf-8",
    )
    (tmp_path / "estimation_results.json").write_text(
        json.dumps({"main": {"coef": 0.04, "se": 0.01}}), encoding="utf-8"
    )
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is False
    assert attempt.populated_sidecar is True
    assert "already populated" in attempt.reason


# ── Script exists, sidecar empty → runner executes ─────────────────────────


def test_runner_executes_script_when_sidecar_empty(tmp_path: Path):
    """The M4 case: script is present and correct, sidecar is `{}`.
    The runner shells out, executes, sidecar becomes populated."""
    (tmp_path / "run_estimation.py").write_text(
        # Minimal stand-in for a real estimator: writes a populated JSON.
        "import json, pathlib\n"
        "pathlib.Path('estimation_results.json').write_text("
        "  json.dumps({'main': {'coef': 0.04, 'se': 0.01, 't_stat': 4.0}})\n"
        ")\n"
        "print('estimation done')\n",
        encoding="utf-8",
    )
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is True
    assert attempt.returncode == 0
    assert attempt.populated_sidecar is True
    # Audit log written.
    log = (tmp_path / "run_estimation.log").read_text(encoding="utf-8")
    assert "returncode: 0" in log
    assert "estimation done" in log  # stdout captured
    # And the sidecar has the real numbers, not `{}`.
    data = json.loads((tmp_path / "estimation_results.json").read_text())
    assert data["main"]["coef"] == 0.04


def test_runner_handles_script_that_errors(tmp_path: Path):
    """Script exists but raises; sidecar stays empty; audit log captures
    the traceback; ran=True with non-zero returncode."""
    (tmp_path / "run_estimation.py").write_text(
        "raise RuntimeError('boom')\n",
        encoding="utf-8",
    )
    # Sidecar absent — the script's failure path.
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is True
    assert attempt.returncode != 0
    assert attempt.populated_sidecar is False
    log = (tmp_path / "run_estimation.log").read_text(encoding="utf-8")
    assert "RuntimeError" in log or "boom" in log


def test_runner_handles_script_that_exits_zero_without_writing(tmp_path: Path):
    """Script returns success but doesn't actually populate the
    sidecar — caught and reported; M4.3 will then reject the
    specialist downstream."""
    (tmp_path / "run_estimation.py").write_text(
        "print('all done (but I wrote nothing)')\n",
        encoding="utf-8",
    )
    (tmp_path / "estimation_results.json").write_text("{}", encoding="utf-8")
    attempt = maybe_execute_specialist_script(tmp_path, "econometrics_specialist")
    assert attempt.ran is True
    assert attempt.returncode == 0
    assert attempt.populated_sidecar is False
    assert "not populated" in attempt.reason


# ── Integration with run_specialist: success flips correctly ───────────────


async def test_run_specialist_runs_script_before_contract_check(tmp_workspace: Path, paper_id: str):
    """End-to-end: tool_loop returns success without populating the
    sidecar; the runner's post-exec executes the script the specialist
    wrote; the contract check then sees a populated sidecar and the
    specialist comes back as success=True."""
    from typing import Any
    from unittest.mock import patch

    from src.core.specialists.base import run_specialist
    from src.core.specialists.contracts import WorkOrder
    from src.modules.llm.base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

    class FakeWritesScriptOnly(LLMBackend):
        """tool_loop writes a substantive primary artifact + a runnable
        script + an empty sidecar — the exact M4 failure mode."""

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
            assert tool_handler is not None
            await tool_handler.handle(
                "write_file",
                {
                    "path": "econometric_spec.md",
                    "content": "# Spec\n\n" + ("Real specification content. " * 20),
                },
            )
            await tool_handler.handle(
                "write_file",
                {
                    "path": "run_estimation.py",
                    "content": (
                        "import json, pathlib\n"
                        "pathlib.Path('estimation_results.json').write_text("
                        "  json.dumps({'main': {'coef': 0.04, 'se': 0.01}}))\n"
                        "print('ran')\n"
                    ),
                },
            )
            await tool_handler.handle(
                "write_file",
                {"path": "estimation_results.json", "content": "{}"},  # the M4 mode
            )
            return ToolLoopResult(
                success=True,
                output="done",
                tool_calls_made=3,
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            )

    work_order = WorkOrder(
        paper_id=paper_id,
        specialist="econometrics_specialist",
        focus="Estimate the model.",
        context_tier=1,
    )

    async def _async_noop(*args, **kwargs):
        return None

    with (
        patch("src.core.specialists.base.save_usage", new=_async_noop),
        patch("src.core.specialists.base.compute_cost", return_value=0),
        patch("src.db.client.execute", new=_async_noop),
    ):
        contribution = await run_specialist(
            work_order,
            backend=FakeWritesScriptOnly(),
            workspace=tmp_workspace,
            model="claude-test",
            extra_tools=[],
            extra_handlers=[],
            backend_name="mock",
        )

    # The runner-side post-exec ran the script; sidecar got populated;
    # M4.3 contract check then passed.
    assert contribution.success is True, f"unexpected failure: {contribution.error}"
    data = json.loads((tmp_workspace / "estimation_results.json").read_text())
    assert data["main"]["coef"] == 0.04
    # Audit log is present.
    assert (tmp_workspace / "run_estimation.log").is_file()


async def test_run_specialist_still_fails_when_script_errors(tmp_workspace: Path, paper_id: str):
    """If the script the specialist wrote errors, the post-exec
    surfaces it via the audit log, but the sidecar stays empty and
    M4.3 still rejects the specialist."""
    from typing import Any
    from unittest.mock import patch

    from src.core.specialists.base import run_specialist
    from src.core.specialists.contracts import WorkOrder
    from src.modules.llm.base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult

    class FakeWritesBrokenScript(LLMBackend):
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
            assert tool_handler is not None
            await tool_handler.handle(
                "write_file",
                {
                    "path": "econometric_spec.md",
                    "content": "# Spec\n\n" + ("Real specification content. " * 20),
                },
            )
            await tool_handler.handle(
                "write_file",
                {"path": "run_estimation.py", "content": "raise RuntimeError('script broken')\n"},
            )
            await tool_handler.handle("write_file", {"path": "estimation_results.json", "content": "{}"})
            return ToolLoopResult(
                success=True,
                output="done",
                tool_calls_made=3,
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            )

    work_order = WorkOrder(
        paper_id=paper_id,
        specialist="econometrics_specialist",
        focus="Estimate the model.",
        context_tier=1,
    )

    async def _async_noop(*args, **kwargs):
        return None

    with (
        patch("src.core.specialists.base.save_usage", new=_async_noop),
        patch("src.core.specialists.base.compute_cost", return_value=0),
        patch("src.db.client.execute", new=_async_noop),
    ):
        contribution = await run_specialist(
            work_order,
            backend=FakeWritesBrokenScript(),
            workspace=tmp_workspace,
            model="claude-test",
            extra_tools=[],
            extra_handlers=[],
            backend_name="mock",
        )

    assert contribution.success is False
    assert "contract violation" in contribution.error
    # Post-exec log written so the next reviewer can debug.
    log = (tmp_workspace / "run_estimation.log").read_text()
    assert "RuntimeError" in log or "script broken" in log
