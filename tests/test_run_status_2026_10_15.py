"""How a run's status ends (2026-10-14 text-analysis demo).

* The disk ran full: ``.pipeline_state.json`` could not be written, the
  failure handler's own save raised again, the run's task died and the study
  stayed "designing" with nothing running. A full disk now pauses the run with
  a plain reason; it is resumable.
* ``e2er status`` said "completed" while the replication step and the final
  export were still running, and a folder exported then was overwritten. The
  study now reads "finishing (writing the export)" until the export is written.
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from src.core.pipeline.spec import spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.strategist.runner import DISK_FULL_STATUS, PipelineRunner, disk_full
from src.core.strategist.state import PaperStatus

PID = "34f8d4c1-7486-4263-bc95-b25e68d766ed"


def _runner(tmp_path: Path, st: PipelineState) -> PipelineRunner:
    spec = spec_from_dict(
        {"name": "one-step", "steps": [{"kind": "specialists", "name": "work", "run": ["text_validator"]}]}
    )
    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id, r._workspace, r._mode, r._spec = PID, tmp_path, "single_pass", spec
    r._triggers, r._state, r._in_initial, r._contributions = [], st, False, []
    r._governance, r._failure_counts, r._last_specialist_errors = "full", {}, {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers, r._review_stages = [], [], set()
    r._max_cost_usd, r._pivot_count, r._iteration, r._deep_revision_count = 5.0, 0, 0, 0
    r._in_memory_spent = lambda: 0.0
    return r


@pytest.fixture
def db(monkeypatch):
    """The papers row as the runner writes it: (status, last_error) per update."""
    rows: list[tuple[str, str | None]] = []
    events: list[str] = []

    async def execute(sql, params=None):
        if "UPDATE papers SET status" in sql:
            rows.append((params["s"], params.get("e")))

    async def log(paper_id, kind, *, stage=None, payload=None, **kw):
        events.append(kind)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr("src.db.client.execute", execute)
    monkeypatch.setattr("src.db.events.log_event", log)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget", noop)
    return rows, events


def _load_as(monkeypatch, st: PipelineState) -> None:
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.load", classmethod(lambda cls, *a: st))


def _enospc() -> OSError:
    return OSError(errno.ENOSPC, "No space left on device", ".pipeline_state.json.tmp")


def test_disk_full_is_recognised_through_the_chain():
    assert disk_full(_enospc())
    try:
        try:
            raise _enospc()
        except OSError as e:
            raise RuntimeError("text validator failed") from e
    except RuntimeError as wrapped:
        assert disk_full(wrapped)
    assert not disk_full(OSError(errno.EACCES, "Permission denied"))
    assert not disk_full(ValueError("no"))


async def test_a_full_disk_pauses_the_run_with_a_plain_reason(tmp_path: Path, monkeypatch, db):
    rows, events = db
    st = PipelineState(paper_id=PID, mode="single_pass")
    st.save(tmp_path)  # the last good state, written before the disk ran full
    saved = (tmp_path / ".pipeline_state.json").read_text()
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st)

    async def step(step):
        raise RuntimeError("text_validator failed") from _enospc()

    def save(workspace):
        raise _enospc()

    async def finalize():
        return None

    r._run_specialists_step = step
    r._best_effort_finalize = finalize
    monkeypatch.setattr(st, "save", save)  # every save fails, also the handlers' own

    out = await r.run()
    assert out == {"status": "paused", "reason": "disk_full"}
    assert rows[-1] == ("paused", DISK_FULL_STATUS)  # not left "designing"
    assert DISK_FULL_STATUS == "The disk is full; free space and press Resume."
    assert "paused_disk_full" in events and "failed" not in events
    assert (tmp_path / ".pipeline_state.json").read_text() == saved  # the state to resume from is intact


async def test_a_full_disk_in_a_handlers_save_pauses_too(tmp_path: Path, monkeypatch, db):
    """A step failed for another reason; saving the state in the failure handler hit the full disk."""
    rows, _events = db
    st = PipelineState(paper_id=PID, mode="single_pass")
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st)

    async def step(step):
        raise ValueError("something else")

    def save(workspace):
        raise _enospc()

    async def finalize():
        return None

    r._run_specialists_step = step
    r._best_effort_finalize = finalize
    monkeypatch.setattr(st, "save", save)
    out = await r.run()
    assert out["reason"] == "disk_full" and rows[-1] == ("paused", DISK_FULL_STATUS)


async def test_anything_else_escaping_fails_the_run_instead_of_leaving_it_running(tmp_path: Path, monkeypatch, db):
    rows, _events = db
    st = PipelineState(paper_id=PID, mode="single_pass")
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st)

    async def step(step):
        raise ValueError("first")

    def save(workspace):
        raise PermissionError(errno.EACCES, "Permission denied")

    async def finalize():
        return None

    r._run_specialists_step = step
    r._best_effort_finalize = finalize
    monkeypatch.setattr(st, "save", save)
    out = await r.run()
    assert out["status"] == "failed" and rows[-1][0] == "failed" and "Permission denied" in rows[-1][1]


async def test_completed_only_after_the_final_export(tmp_path: Path, monkeypatch, db):
    rows, _events = db
    st = PipelineState(paper_id=PID, mode="single_pass")
    _load_as(monkeypatch, st)
    r = _runner(tmp_path, st)
    during_export: list[str] = []

    async def step(step):
        return None

    async def finalize():  # the replication package and the structured export
        during_export.append(rows[-1][0])

    r._run_specialists_step = step
    r._best_effort_finalize = finalize
    out = await r.run()
    assert during_export == ["finishing"]
    assert rows[-1] == ("completed", None) and out["status"] == "completed"
    assert [s for s, _ in rows].count("completed") == 1


async def test_a_pause_after_the_steps_is_not_turned_into_completed(tmp_path: Path, monkeypatch, db):
    rows, _events = db
    r = _runner(tmp_path, PipelineState(paper_id=PID, mode="single_pass"))
    r._steps_done = True  # every step has run: the export is what is left
    await r._update_status(PaperStatus.COMPLETED)
    assert rows[-1][0] == "finishing"
    await r._update_status(PaperStatus.PAUSED, error="Stopped for you")
    assert r._completed_deferred is False


def test_e2er_status_says_finishing_while_the_export_is_written():
    from src.core import labels
    from src.core.run_outcome import status_words
    from src.core.run_owner import IN_FLIGHT

    assert status_words("finishing") == "finishing (writing the export)"
    assert labels.status("finishing") == "finishing (writing the export)"
    assert "finishing" in IN_FLIGHT  # another server sees the run as running
