"""Pipeline resilience — ensure upstream results survive downstream failures.

The critical invariant: if stage N crashes, re-running the pipeline must
   (a) not re-execute stages 1..N-1
   (b) leave their artifacts and state intact on disk
   (c) make zero new LLM/Allium/GitHub calls for completed stages

These tests exist because re-running specialists costs real money. A single
re-run of all specialists is on the order of $20-30 in Anthropic API spend.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.pipeline.state import PipelineState
from src.core.strategist.runner import PipelineRunner
from src.core.strategist.state import PaperStatus

# ---------------------------------------------------------------------------
# Fault-injection runner
# ---------------------------------------------------------------------------

# All phases run by PipelineRunner.run() in iterative mode, in execution order.
PHASE_ORDER = [
    "initial",
    "iterative",
    "self_attack",
    "polish",
    "review",
    "revision",
    "replication",
]


class _FaultyRunner(PipelineRunner):
    """PipelineRunner with controlled failure injection per phase.

    Each phase override increments a call counter and writes a sentinel file
    to the workspace. If `fail_at` matches the current phase name, the phase
    raises RuntimeError BEFORE writing the sentinel — modelling 'phase started
    but did not finish'. The sentinel lets tests verify which phases really
    completed (independent of the state file).
    """

    def __init__(self, *a, fail_at: str | None = None, **kw):
        super().__init__(*a, **kw)
        self.fail_at = fail_at
        self.calls: dict[str, int] = {p: 0 for p in PHASE_ORDER}

    def _record(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1
        if self.fail_at == name:
            raise RuntimeError(f"injected failure at {name}")
        (self._workspace / f"_phase_{name}.txt").write_text(f"ok:{name}")

    async def _run_initial_phase(self) -> None:
        self._record("initial")

    async def _run_iterative_phase(self) -> PaperStatus:
        self._record("iterative")
        return PaperStatus.IN_PROGRESS

    async def _run_self_attack_phase(self) -> PaperStatus:
        self._record("self_attack")
        return PaperStatus.IN_PROGRESS

    async def _run_polish_phase(self) -> PaperStatus:
        self._record("polish")
        return PaperStatus.IN_PROGRESS

    async def _run_review_phase(self) -> PaperStatus:
        self._record("review")
        return PaperStatus.REVIEW

    async def _run_revision_phase(self, current_status: PaperStatus) -> PaperStatus:
        self._record("revision")
        return PaperStatus.IN_PROGRESS

    async def _run_replication_phase(self) -> None:
        self._record("replication")

    async def _update_status(self, status, error=None) -> None:
        pass  # bypass DB writes

    async def _best_effort_finalize(self) -> None:
        pass  # bypass GitHub push / LaTeX compile


def _make_workspace(tmp_path: Path, mode: str = "iterative") -> tuple[Path, str]:
    pid = f"resilience-{uuid.uuid4().hex[:8]}"
    ws = tmp_path / pid
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": pid, "title": "Test", "mode": mode}))
    return ws, pid


def _make_runner(workspace: Path, paper_id: str, fail_at: str | None = None, mode: str = "iterative") -> _FaultyRunner:
    return _FaultyRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=MagicMock(),
        model="claude-test",
        mode=mode,
        backend_name="mock",
        max_cost_usd=100.0,
        fail_at=fail_at,
    )


def _runner_patches():
    """Patches needed for any PipelineRunner.run() call in tests."""
    return (
        patch("src.db.events.log_event", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    )


# ---------------------------------------------------------------------------
# 1) Crash at each phase preserves earlier completed phases in state file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail_at", PHASE_ORDER)
async def test_crash_preserves_earlier_phase_state(tmp_path, fail_at):
    ws, pid = _make_workspace(tmp_path)
    runner = _make_runner(ws, pid, fail_at=fail_at)

    p1, p2, p3 = _runner_patches()
    with p1, p2, p3:
        result = await runner.run()

    assert result["status"] == "failed", f"crash at {fail_at} should yield failed result"

    state_file = ws / ".pipeline_state.json"
    assert state_file.exists(), "state must be persisted after crash"
    state_data = json.loads(state_file.read_text())
    completed = state_data["completed_stages"]

    expected_completed = PHASE_ORDER[: PHASE_ORDER.index(fail_at)]
    for prior in expected_completed:
        assert prior in completed, (
            f"earlier phase '{prior}' lost from state after crash at '{fail_at}' "
            f"— resume would re-execute it and re-spend tokens. completed={completed}"
        )
    assert fail_at not in completed, f"failed phase '{fail_at}' must NOT be marked complete (would skip retry)"


# ---------------------------------------------------------------------------
# 2) Resume after crash does not redo completed phases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("crash_at", ["self_attack", "polish", "review", "revision", "replication"])
async def test_resume_does_not_redo_completed_phases(tmp_path, crash_at):
    ws, pid = _make_workspace(tmp_path)

    p1, p2, p3 = _runner_patches()
    with p1, p2, p3:
        r1 = _make_runner(ws, pid, fail_at=crash_at)
        await r1.run()

        r2 = _make_runner(ws, pid, fail_at=None)
        await r2.run()

    completed_in_run1 = PHASE_ORDER[: PHASE_ORDER.index(crash_at)]
    for phase in completed_in_run1:
        assert r2.calls[phase] == 0, (
            f"phase '{phase}' completed in run 1 but executed again in run 2 "
            f"(call count = {r2.calls[phase]}). This would re-spend API tokens "
            f"on every resume. r2.calls = {r2.calls}"
        )
    for phase in PHASE_ORDER[PHASE_ORDER.index(crash_at) :]:
        assert r2.calls[phase] >= 1, f"phase '{phase}' was not executed on resume (calls={r2.calls})"


# ---------------------------------------------------------------------------
# 3) Artifacts on disk survive a downstream crash
# ---------------------------------------------------------------------------


async def test_artifacts_persist_through_downstream_crash(tmp_path):
    ws, pid = _make_workspace(tmp_path)
    runner = _make_runner(ws, pid, fail_at="polish")

    p1, p2, p3 = _runner_patches()
    with p1, p2, p3:
        await runner.run()

    for phase in ["initial", "iterative", "self_attack"]:
        sentinel = ws / f"_phase_{phase}.txt"
        assert sentinel.exists(), (
            f"artifact for completed phase '{phase}' missing after crash at 'polish' "
            "— a downstream failure deleted upstream output"
        )
        assert sentinel.read_text() == f"ok:{phase}"

    # Phase that crashed: sentinel must NOT exist (proves _record raises before write).
    assert not (ws / "_phase_polish.txt").exists()


# ---------------------------------------------------------------------------
# 4) State file atomicity — corrupt main file recovers from .bak
# ---------------------------------------------------------------------------


def test_state_save_keeps_backup_for_corruption_recovery(tmp_path):
    """state.save() must use atomic-rename + keep a .bak so a corrupted main
    file recovers prior progress instead of losing all upstream phases.
    """
    ws = tmp_path / "ws"
    ws.mkdir()

    state = PipelineState(paper_id="p1", mode="iterative")
    state.mark_complete("initial")
    state.save(ws)

    state.mark_complete("iterative")
    state.save(ws)  # second save: previous good file becomes .bak

    main = ws / ".pipeline_state.json"
    bak = ws / ".pipeline_state.json.bak"
    assert main.exists()
    assert bak.exists(), (
        "save() must keep a .bak of the previous good state. Without a backup, "
        "a single corrupted write loses ALL upstream progress."
    )

    # Simulate a partial / corrupted write to the main file
    main.write_text("{ this is not valid json")

    recovered = PipelineState.load(ws, "p1", "iterative")
    assert "initial" in recovered.completed_stages, (
        f"after main file corruption, load() must recover from .bak. Got completed_stages={recovered.completed_stages}"
    )


def test_state_save_atomic_rename(tmp_path):
    """The new bytes never appear under the main filename until the full
    write is complete. A reader observing partial bytes proves non-atomicity.
    """
    ws = tmp_path / "ws"
    ws.mkdir()

    state = PipelineState(paper_id="p1", mode="iterative")
    state.mark_complete("initial")
    state.save(ws)

    main = ws / ".pipeline_state.json"
    tmp = ws / ".pipeline_state.json.tmp"

    # After save() returns, the .tmp file must be gone (renamed into place).
    assert main.exists()
    assert not tmp.exists(), "stale .tmp file left behind after save()"

    # Main file must always parse as valid JSON.
    json.loads(main.read_text())


# ---------------------------------------------------------------------------
# 5) DB phase-end logged before next phase starts
# ---------------------------------------------------------------------------


async def test_phase_end_logged_before_next_phase_starts(tmp_path):
    ws, pid = _make_workspace(tmp_path)
    runner = _make_runner(ws, pid, fail_at=None)

    log_calls: list[tuple[str, str]] = []

    async def _log(paper_id, event_type, **kw):
        log_calls.append((event_type, kw.get("stage", "")))

    with (
        patch("src.db.events.log_event", side_effect=_log),
        patch("src.modules.tracking.usage.check_budget", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
    ):
        await runner.run()

    for phase in PHASE_ORDER:
        starts = [i for i, (et, st) in enumerate(log_calls) if et == "phase_start" and st == phase]
        ends = [i for i, (et, st) in enumerate(log_calls) if et == "phase_end" and st == phase]
        assert starts, f"phase '{phase}' missing phase_start event (events={log_calls})"
        assert ends, f"phase '{phase}' missing phase_end event"
        assert starts[0] < ends[0], f"phase '{phase}' logged end before start — phase boundary violated"

    # Phase ends must come strictly before the next phase's start.
    for i, phase in enumerate(PHASE_ORDER[:-1]):
        next_phase = PHASE_ORDER[i + 1]
        my_end = next(idx for idx, (et, st) in enumerate(log_calls) if et == "phase_end" and st == phase)
        next_start = next(idx for idx, (et, st) in enumerate(log_calls) if et == "phase_start" and st == next_phase)
        assert my_end < next_start, (
            f"'{phase}' phase_end logged after '{next_phase}' phase_start — "
            "phase commit ordering broken; resume would lose work"
        )


# ---------------------------------------------------------------------------
# 6) GitHub push idempotence — re-pushing existing files uses update_file
# ---------------------------------------------------------------------------


def test_github_push_directory_idempotent_on_resume(tmp_path):
    """Re-running push_directory after a partial push must use update_file
    (not create_file) for files already on the remote — avoids duplicate
    commits and wasted API calls on resume.
    """
    from src.modules.github.client import GitHubClient

    pushed_files: dict[str, bytes] = {}

    class _FakeContents:
        def __init__(self, sha):
            self.sha = sha

    def _get_contents(path, ref="main"):
        if path in pushed_files:
            return _FakeContents(sha=f"sha-{path}")
        raise Exception(f"404: {path} not found")

    create_calls: list[str] = []
    update_calls: list[str] = []

    def _create_file(path, message, content, branch="main"):
        create_calls.append(path)
        pushed_files[path] = content

    def _update_file(path, message, content, sha, branch="main"):
        update_calls.append(path)
        pushed_files[path] = content

    mock_repo = MagicMock()
    mock_repo.get_contents.side_effect = _get_contents
    mock_repo.create_file.side_effect = _create_file
    mock_repo.update_file.side_effect = _update_file

    mock_user = MagicMock()
    mock_user.get_repo.return_value = mock_repo

    mock_gh_cls = MagicMock()
    mock_gh_cls.return_value.get_user.return_value = mock_user

    local = tmp_path / "artifacts"
    local.mkdir()
    (local / "a.txt").write_text("A")
    (local / "b.txt").write_text("B")
    (local / "c.txt").write_text("C")

    with patch("github.Github", mock_gh_cls):
        client = GitHubClient("tok", "user")
        n1 = client.push_directory("repo", local, commit_message="run 1")
        n2 = client.push_directory("repo", local, commit_message="run 2")

    assert n1 == 3, f"first push should send all 3 files, got {n1}"
    assert n2 == 3, f"second push should still process all 3 files, got {n2}"
    assert len(create_calls) == 3, f"first push must use create_file 3x for new files; got {len(create_calls)}"
    assert len(update_calls) == 3, (
        f"second push must use update_file 3x for already-pushed files "
        f"(got {len(update_calls)} updates, {len(create_calls)} total creates). "
        "Otherwise re-running creates duplicate remote commits."
    )


# ---------------------------------------------------------------------------
# 7) Full completion replay is a no-op (the critical $$ guarantee)
# ---------------------------------------------------------------------------


async def test_replay_after_completion_is_noop(tmp_path):
    """A fully-completed pipeline re-run must make zero new specialist calls.
    Re-running the CLI on a finished paper must never re-spend tokens.
    """
    ws, pid = _make_workspace(tmp_path)

    p1, p2, p3 = _runner_patches()
    with p1, p2, p3:
        r1 = _make_runner(ws, pid, fail_at=None)
        result1 = await r1.run()
        assert result1["status"] != "failed", f"first run must complete: {result1}"

        r2 = _make_runner(ws, pid, fail_at=None)
        await r2.run()

    total_r2_calls = sum(r2.calls.values())
    assert total_r2_calls == 0, (
        f"replaying a completed pipeline executed {total_r2_calls} phases "
        f"(breakdown: {r2.calls}). Every phase re-execution costs API tokens. "
        "PipelineState.is_complete() must skip every already-done phase."
    )
