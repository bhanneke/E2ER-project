"""The order phases run in, pinned before anything moves.

docs/PIPELINES.md proposes replacing PipelineRunner.run()'s hardcoded sequence
of Python methods with a spec the runner interprets. The risk in that refactor
is not that it breaks loudly — it is that it quietly reorders something, or
drops a phase in a mode nobody exercised, and the pipeline still finishes.

So this is written first, against the current implementation, and it asserts the
sequence rather than the outcome. If it goes red during the refactor, behaviour
changed rather than moved.

Nothing real runs. Every phase body is replaced with a recorder, the budget
check and event log are stubbed, and the assertion is on the order of
`phase_start` events — which is what the runner itself uses to tell the outside
world where it is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.core.strategist.runner import PipelineRunner
from src.modules.llm.base import LLMBackend, ToolHandler, ToolLoopResult

#: Teardown, not sequence. These run through _best_effort_finalize regardless
#: of how the run ended, and never announce a phase_start.
FINALIZE_METHODS = {
    "_run_compile_phase",
    "_run_github_push_phase",
    "_run_export_phase",
}

PHASE_METHODS = {
    "_run_initial_phase": "initial",
    "_run_iterative_phase": "iterative",
    "_enforce_estimation_gate": "estimation_gate",
    "_run_self_attack_phase": "self_attack",
    "_run_polish_phase": "polish",
    "_run_review_phase": "review",
    "_run_revision_phase": "revision",
    "_run_replication_phase": "replication",
}


def _recorder(log: list[str], name: str):
    async def _call(*_a, **_k):
        log.append(name)

    return _call


class _SilentBackend(LLMBackend):
    """Never called. Present because the runner requires one."""

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
        raise AssertionError("the sequence test must not call a model")


def _recording_runner(monkeypatch, tmp_path: Path, *, mode: str, complete: set[str] | None = None):
    """A runner whose phases do nothing but announce themselves.

    Returns (runner, phases) where `phases` fills with the stage names the
    runner logs, in order.
    """
    from src.core.pipeline import state as state_mod
    from src.core.strategist import runner as runner_mod

    phases: list[str] = []
    done = set(complete or ())

    class _State:
        """Enough PipelineState for run() to sequence against."""

        iteration = 0
        pivot_count = 0
        contributions_count = 0
        last_status = ""
        pending_review_stage = ""

        def is_complete(self, name: str) -> bool:
            return name in done

        def mark_complete(self, name: str) -> None:
            done.add(name)

        def save(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(state_mod.PipelineState, "load", classmethod(lambda cls, *a, **k: _State()))

    # The runner imports these inside run(); patch at their source.
    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        if kind == "phase_start" and stage:
            phases.append(stage)

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget", AsyncMock(return_value=None))

    runner = PipelineRunner(
        paper_id="p1",
        workspace=tmp_path,
        backend=_SilentBackend(),
        model="test",
        mode=mode,
    )
    monkeypatch.setattr(runner, "_update_status", AsyncMock(return_value=None))
    monkeypatch.setattr(runner, "_should_pause_for_review", lambda *a, **k: False)

    # Finalize is stubbed by default because it is not a no-op: the structured
    # export writes a real directory under ~/e2er-papers. The two tests that
    # care about finalize replace these with their own recorders.
    for _name in FINALIZE_METHODS | {"_export_audit_log_only"}:
        monkeypatch.setattr(runner, _name, AsyncMock(return_value=None))

    from src.core.strategist.state import PaperStatus

    for method, _stage in PHASE_METHODS.items():
        if method == "_run_revision_phase":
            monkeypatch.setattr(runner, method, AsyncMock(return_value=PaperStatus.COMPLETED))
        else:
            monkeypatch.setattr(runner, method, AsyncMock(return_value=PaperStatus.IN_PROGRESS))

    assert runner_mod is not None  # import kept meaningful
    return runner, phases


# ---------------------------------------------------------------------------
# The golden sequences
# ---------------------------------------------------------------------------


async def test_single_pass_sequence_is_pinned(monkeypatch, tmp_path):
    """A single-pass run skips the iterative-only phases and nothing else."""
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode="single_pass")
    await runner.run()

    assert phases == [
        "initial",
        "estimation_gate",
        "review",
        "revision",
        "replication",
    ]


async def test_iterative_sequence_is_pinned(monkeypatch, tmp_path):
    """The full sequence. This is the one docs/PIPELINES.md must reproduce."""
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode="iterative")
    await runner.run()

    assert phases == [
        "initial",
        "iterative",
        "estimation_gate",
        "self_attack",
        "polish",
        "review",
        "revision",
        "replication",
    ]


# ---------------------------------------------------------------------------
# The properties that make the sequence what it is
# ---------------------------------------------------------------------------


async def test_the_estimation_gate_runs_even_on_a_full_resume(monkeypatch, tmp_path):
    """Deliberate, and easy to lose in a refactor.

    Every other phase is skipped once marked complete. The estimation gate is
    not — it has no mark_complete, so an empirical paper cannot reach drafting
    with a failed estimation contract just by being resumed.
    """
    runner, phases = _recording_runner(
        monkeypatch,
        tmp_path,
        mode="iterative",
        complete={"initial", "iterative", "self_attack", "polish", "review", "revision", "replication"},
    )
    await runner.run()

    assert phases == ["estimation_gate"], "the gate must survive a resume that skips everything else"


async def test_the_estimation_gate_ignores_a_completion_marker(monkeypatch, tmp_path):
    """The stronger form, and the one a mutation test asks for.

    Marking every OTHER phase complete does not prove the gate is unskippable —
    it only proves nothing marked it. This marks the gate itself complete, a
    state the current code can never produce, and requires it to run anyway.
    A refactor that gives the gate the same is_complete/mark_complete treatment
    as its neighbours looks tidier and quietly makes it skippable on resume.
    """
    runner, phases = _recording_runner(
        monkeypatch,
        tmp_path,
        mode="single_pass",
        complete={"estimation_gate"},
    )
    await runner.run()

    assert "estimation_gate" in phases, "the gate must run even when something claims it is done"


async def test_a_resume_skips_only_what_was_completed(monkeypatch, tmp_path):
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode="iterative", complete={"initial", "iterative"})
    await runner.run()

    assert phases == ["estimation_gate", "self_attack", "polish", "review", "revision", "replication"]


async def test_the_iterative_only_phases_never_run_in_single_pass(monkeypatch, tmp_path):
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode="single_pass")
    await runner.run()

    for stage in ("iterative", "self_attack", "polish"):
        assert stage not in phases


async def test_revision_is_announced_like_every_other_phase(monkeypatch, tmp_path):
    """Revision bypasses the _phase helper because it needs an argument.

    It logs its own phase_start/phase_end instead, which is the kind of special
    case a refactor drops. If revision stops announcing itself, the progress UI
    and the export both lose a stage.
    """
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode="single_pass")
    await runner.run()

    assert "revision" in phases
    assert phases.index("review") < phases.index("revision") < phases.index("replication")


async def test_every_phase_method_is_either_sequenced_or_finalize(monkeypatch, tmp_path):
    """Guards the mapping this test file is built on.

    A phase method added to the runner and to neither set below would be
    silently uncovered by everything above. This found the finalize trio on its
    first run, which is exactly the job.
    """
    runner, _ = _recording_runner(monkeypatch, tmp_path, mode="iterative")

    actual = {name for name in dir(runner) if name.startswith(("_run_", "_enforce_")) and "phase" in name}
    actual |= {"_enforce_estimation_gate"}
    unmapped = actual - set(PHASE_METHODS) - FINALIZE_METHODS

    assert unmapped == set(), f"phase methods neither sequenced nor finalize: {sorted(unmapped)}"


async def test_finalize_runs_even_when_the_pipeline_fails(monkeypatch, tmp_path):
    """Teardown is not a step, and a spec-driven runner must not make it one.

    compile, audit export, GitHub push and structured export run through
    _best_effort_finalize, which swallows every error and fires even when the
    run aborts mid-flight — a cost cap, a cancelled run, every specialist
    failing. A refactor that turns the pipeline into a list of steps will lose
    this unless it is deliberate about it, and the loss is invisible: the run
    still reports failure, it just stops leaving the partial artifacts behind.
    """
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode="single_pass")

    called: list[str] = []
    for name in sorted(FINALIZE_METHODS):
        monkeypatch.setattr(runner, name, _recorder(called, name))
    monkeypatch.setattr(runner, "_export_audit_log_only", _recorder(called, "_export_audit_log_only"))

    async def _boom():
        raise RuntimeError("every specialist failed")

    monkeypatch.setattr(runner, "_run_initial_phase", _boom)

    await runner.run()

    assert set(called) >= FINALIZE_METHODS, f"finalize did not run after a failure: {called}"


async def test_finalize_runs_after_a_successful_run(monkeypatch, tmp_path):
    runner, _ = _recording_runner(monkeypatch, tmp_path, mode="single_pass")

    called: list[str] = []
    for name in sorted(FINALIZE_METHODS):
        monkeypatch.setattr(runner, name, _recorder(called, name))
    monkeypatch.setattr(runner, "_export_audit_log_only", _recorder(called, "_export_audit_log_only"))

    await runner.run()

    assert set(called) >= FINALIZE_METHODS


@pytest.mark.parametrize("mode", ["single_pass", "iterative"])
async def test_no_phase_runs_twice(monkeypatch, tmp_path, mode):
    runner, phases = _recording_runner(monkeypatch, tmp_path, mode=mode)
    await runner.run()

    assert len(phases) == len(set(phases)), f"a phase ran more than once: {phases}"
