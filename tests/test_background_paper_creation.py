"""create_paper backgrounds the heavy BYOD prep (data.db import + literature
ingest) so the POST returns fast; _prepare_and_run runs them before the pipeline
and isolates their failures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.api import app as appmod


async def _run(tmp_path: Path, settings=None):
    calls: list[str] = []

    async def imp(*a, **k):
        calls.append("import")

    async def ing(*a, **k):
        calls.append("ingest")

    async def run(*a, **k):
        calls.append("pipeline")

    with (
        patch("src.modules.data.byod_import.import_corpus_into_data_db", side_effect=imp),
        patch("src.api.app._prepare_papers", side_effect=ing),
        patch("src.api.app._run_pipeline", side_effect=run),
    ):
        s = settings or type("S", (), {"max_rows_per_paper": 1000})()
        await appmod._prepare_and_run("pid", tmp_path, s, "iterative", 5.0, "empirical")
    return calls


async def test_import_then_ingest_then_pipeline(tmp_path: Path):
    assert await _run(tmp_path) == ["import", "ingest", "pipeline"]


async def test_import_failure_does_not_block_pipeline(tmp_path: Path):
    calls: list[str] = []

    async def boom(*a, **k):
        raise RuntimeError("import blew up")

    async def ing(*a, **k):
        calls.append("ingest")

    async def run(*a, **k):
        calls.append("pipeline")

    with (
        patch("src.modules.data.byod_import.import_corpus_into_data_db", side_effect=boom),
        patch("src.api.app._prepare_papers", side_effect=ing),
        patch("src.api.app._run_pipeline", side_effect=run),
    ):
        s = type("S", (), {"max_rows_per_paper": 1000})()
        await appmod._prepare_and_run("pid", tmp_path, s, "iterative", 5.0, "empirical")
    # ingest + pipeline still ran despite the import failure
    assert calls == ["ingest", "pipeline"]


def test_create_paper_does_not_import_on_request_path():
    """The synchronous import was removed from create_paper — it must only
    appear inside the background _prepare_and_run."""
    import inspect

    src = inspect.getsource(appmod.create_paper)
    assert "import_corpus_into_data_db" not in src
    assert "_prepare_and_run" in src
    # and _prepare_and_run is what actually does the import
    assert "import_corpus_into_data_db" in inspect.getsource(appmod._prepare_and_run)


async def test_a_cancel_while_preparing_marks_the_run_cancelled(tmp_path: Path):
    """Cancel pressed in the first seconds (data and literature still being prepared): the run is
    cancelled, not left at "idea" for good with nothing to cancel or resume."""
    import asyncio

    started = asyncio.Event()
    marked: list[str] = []

    async def slow(*a, **k):
        started.set()
        await asyncio.sleep(30)

    async def run(*a, **k):
        raise AssertionError("the pipeline must not start after a cancel")

    async def mark(paper_id):
        marked.append(paper_id)

    with (
        patch("src.modules.data.byod_import.import_corpus_into_data_db", side_effect=slow),
        patch("src.api.app._run_pipeline", side_effect=run),
        patch("src.api.app._mark_cancelled_before_start", side_effect=mark),
    ):
        s = type("S", (), {"max_rows_per_paper": 1000})()
        task = asyncio.create_task(appmod._prepare_and_run("pid", tmp_path, s, "single_pass", 5.0, "empirical"))
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("the task was not cancelled")
    assert marked == ["pid"]
