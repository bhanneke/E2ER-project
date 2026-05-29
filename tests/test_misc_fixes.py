"""Misc bug-fix regressions from the 2026-05 full code review (batch 3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── #4: literature_items INSERT persists citations ───────────────────────────


async def test_store_paper_inserts_citations():
    from src.modules.literature.models import PaperMetadata
    from src.modules.literature.storage import store_paper

    paper = PaperMetadata(title="X", doi="10.1/x", citations=42, source="openalex")
    with patch("src.db.client.fetch_one", new=AsyncMock(return_value={"id": "row-1"})) as fo:
        await store_paper(paper, "paper-1")
    sql, params = fo.await_args.args
    assert "citations" in sql
    assert params["citations"] == 42


# ── #10: --acknowledge / flat-rate backend controls the $1 floor ─────────────


def _post_body(backend: str, acknowledge: bool) -> dict:
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"paper_id": "p1"}
    from src import cli_run

    with (
        patch("src.config.get_settings", return_value=SimpleNamespace(llm_backend=backend)),
        patch("httpx.post", return_value=fake_resp) as post,
    ):
        cli_run._submit_paper("rq?", "empirical", "single_pass", 5.0, acknowledge=acknowledge)
    return post.call_args.kwargs["json"]


def test_metered_backend_enforces_floor_by_default():
    assert _post_body("anthropic", acknowledge=False)["acknowledge_unproven_tuple"] is False


def test_acknowledge_flag_lifts_floor():
    assert _post_body("anthropic", acknowledge=True)["acknowledge_unproven_tuple"] is True


def test_flat_rate_backend_auto_acknowledges():
    assert _post_body("claude_code", acknowledge=False)["acknowledge_unproven_tuple"] is True


# ── single-order cascade guard is now shared ─────────────────────────────────


def test_assert_artifacts_written_raises_on_missing(tmp_path):
    from src.core.specialists.contracts import Contribution
    from src.core.specialists.dispatcher import assert_artifacts_written
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS

    # paper_drafter is non-tolerant and has a canonical artifact.
    contribs = [Contribution(paper_id="p", specialist="paper_drafter", output="", success=True)]
    with pytest.raises(RuntimeError, match="canonical artifact"):
        assert_artifacts_written(contribs, tmp_path)

    # Once the artifact exists, it passes.
    (tmp_path / SPECIALIST_ARTIFACTS["paper_drafter"]).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / SPECIALIST_ARTIFACTS["paper_drafter"]).write_text("\\documentclass{article}")
    assert_artifacts_written(contribs, tmp_path)  # no raise


# ── FileToolHandler sandbox uses path containment, not str-prefix ────────────


def test_file_tool_handler_blocks_sibling_prefix_escape(tmp_path):
    from src.modules.llm.tools import FileToolHandler

    (tmp_path / "abc-evil").mkdir()
    h = FileToolHandler(tmp_path / "abc")
    with pytest.raises(PermissionError):
        h._resolve("../abc-evil/secret.txt")
    # A legitimate in-workspace path resolves fine.
    assert h._resolve("sub/ok.txt").is_relative_to(tmp_path / "abc")
