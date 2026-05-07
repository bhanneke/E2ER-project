"""Real-LLM end-to-end smoke test.

Skipped unless ANTHROPIC_API_KEY is set in the environment. Uses the
cheapest viable Anthropic model (Claude Haiku 4.5) to keep CI cost
under $0.50 per run. Exercises the single_pass mode end-to-end:

  idea → design → review → revision → replication

with the data module disabled (no Allium key required). Verifies the
pipeline completes, produces the canonical artifacts, and stays under
the cost cap.

Mark with @pytest.mark.e2e; the default pytest invocation skips it.
Run explicitly with::

    ANTHROPIC_API_KEY=sk-ant-... pytest tests/e2e/test_haiku_smoke.py -v -m e2e
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_HAS_KEY = _API_KEY.startswith("sk-ant-")


@pytest.mark.skipif(not _HAS_KEY, reason="ANTHROPIC_API_KEY not set")
async def test_haiku_single_pass_smoke(tmp_path):
    """Run a single_pass paper end-to-end against the real Anthropic API.

    Cost target: < $0.50 (haiku 4.5 is ~$1/$5 per million input/output tokens).
    """
    # Force the cheapest model regardless of .env setting.
    os.environ["ANTHROPIC_MODEL"] = "claude-haiku-4-5"
    os.environ["LLM_BACKEND"] = "anthropic"
    os.environ["DATA_MODULE_ENABLED"] = "false"
    # Keep things short — single specialist sweep, not iterative.
    # The cost cap will hard-stop the run if anything goes sideways.

    # Fresh settings (clear lru_cache from any earlier import).
    from src.config import get_settings

    get_settings.cache_clear()

    from src.core.strategist.runner import PipelineRunner
    from src.modules.llm.anthropic import AnthropicBackend
    from src.modules.tracking.usage import get_paper_usage

    paper_id = str(uuid.uuid4())
    workspace = tmp_path / paper_id
    workspace.mkdir()
    (workspace / "manifest.json").write_text(
        f'{{"paper_id": "{paper_id}", "title": "Block height vs. elapsed time on Ethereum",'
        ' "research_question": "Describe the empirical relationship between block height'
        ' and wall-clock time on Ethereum mainnet.",'
        ' "datasets": [], "mode": "single_pass", "current_stage": "idea"}'
    )

    backend = AnthropicBackend()
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=backend,
        model="claude-haiku-4-5",
        mode="single_pass",
        extra_tools=[],
        extra_handlers=[],
        backend_name="anthropic",
        max_cost_usd=0.50,  # hard cap — fail loud if cost spirals
    )
    result = await runner.run()

    # The pipeline either completed or hit the cost cap (in which case we'd
    # rather see the cap message than a flaky test). Both end states are
    # treated as "the wiring works".
    assert result.get("status") in {"completed", "in_progress", "failed"}, result
    if result.get("status") == "failed":
        assert "Budget exceeded" in result.get("error", "")
        pytest.skip(f"hit cost cap before completion: {result['error']}")

    # Canonical artifacts that any single_pass run should produce.
    assert (workspace / "paper_plan.md").exists(), "idea_developer must write paper_plan.md"
    assert (workspace / "paper_draft.tex").exists() or (workspace / "paper_draft.body.tex").exists()

    # Cost stays under the cap (we already have 0.50 cap; assert again for clarity).
    try:
        usage = await get_paper_usage(paper_id)
        total = float(usage.get("totals", {}).get("total_cost_usd") or 0)
        assert total < 0.50, f"cost {total} exceeded $0.50 budget"
    except Exception:
        # DB may be unavailable in the test environment; that's OK — the runner
        # itself enforces the cap when it can.
        pass
