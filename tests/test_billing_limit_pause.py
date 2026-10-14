"""A paid API that refuses calls for money pauses the run, like a subscription plan's limit.

Live, 2026-10-14 (the earthquake demo, DeepSeek V4 Pro on OpenRouter): the
researcher sent the drafter back at the draft review and the send-back failed
on "Error code: 402 - This request requires more credits ... adjust the key's
total limit". The run went back to the same stop with no error shown, and the
remark was gone. Earlier the same 402 had counted as failed attempts.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.llm.base import TokenUsage, ToolLoopResult
from src.modules.llm.plan_limit import (
    BILLING_TAIL,
    BillingLimitReachedError,
    PlanLimitReachedError,
    detect_billing,
    is_plan_limit_status,
)

#: The live message (2026-10-14), as the run recorded it.
LIVE_402 = (
    "Error code: 402 - {'error': {'message': \"This request requires more credits, or fewer max_tokens. You "
    "requested up to 32768 tokens, but can only afford 14986. To increase, visit "
    "https://openrouter.ai/workspaces/default/keys/c95239b4 and adjust the key's total limit\", 'code': 402, "
    "'metadata': {'limit_source': 'openrouter_key_limit', 'remedy_hint': \"Raise or remove the key's limit\"}}}"
)
KEY_LIMIT = (
    "The OpenRouter key's spending limit is reached. Raise it at openrouter.ai or choose another AI provider, "
    "then press Resume."
)


@pytest.mark.parametrize(
    "backend, text, starts",
    [
        ("openrouter", LIVE_402, "The OpenRouter key's spending limit is reached."),
        (
            "openrouter",
            "Error code: 403 - {'error': {'message': 'Key limit exceeded (total limit)'}}",
            "The OpenRouter key",
        ),
        ("openrouter", "Error code: 402 - {'error': {'message': 'Insufficient credits'}}", "The OpenRouter account"),
        (
            "anthropic",
            "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit "
            "balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase "
            "credits.'}}",
            "The Anthropic API account's credit balance is too low.",
        ),
        (
            "anthropic",
            "Error code: 400 - You have reached your specified API usage limits. You will regain access on 2026-11-01",
            "The Anthropic API key's usage limit is reached.",
        ),
    ],
)
def test_the_apis_wording_is_recognised(backend, text, starts):
    found = detect_billing(backend, text)
    assert isinstance(found, BillingLimitReachedError) and isinstance(found, PlanLimitReachedError)
    assert found.status.startswith(starts) and found.status.endswith(BILLING_TAIL)
    assert str(found) == found.status and found.event == "paused_billing_limit"


def test_the_live_402_gives_the_plain_sentence():
    assert detect_billing("openrouter", LIVE_402).status == KEY_LIMIT


@pytest.mark.parametrize(
    "backend, text",
    [
        ("openrouter", "Error code: 429 - rate limited, retry later"),
        ("openrouter", "OpenRouter returned no answer after 3 attempts: upstream error"),
        ("anthropic", "Error code: 529 - overloaded"),
        ("codex", LIVE_402),  # the CLIs have their own plan limits
    ],
)
def test_other_errors_are_not_a_billing_limit(backend, text):
    assert detect_billing(backend, text) is None


def test_the_status_is_recognised_as_a_pause_everywhere():
    from src.api.app import _plain_error
    from src.cli_status import _format_status_summary
    from src.core import labels

    assert is_plan_limit_status(KEY_LIMIT)
    assert _plain_error(KEY_LIMIT) == KEY_LIMIT
    out = _format_status_summary({"id": "abc", "status": "paused", "last_error": KEY_LIMIT})
    assert f"Paused:     {KEY_LIMIT}" in out and "e2er resume abc" in out
    assert labels.event("paused_billing_limit").startswith("Paused:")


async def test_the_openrouter_backend_raises_and_records_what_the_loop_used(monkeypatch):
    from src.modules.llm import openrouter

    backend = openrouter.OpenRouterBackend.__new__(openrouter.OpenRouterBackend)
    backend._model = "deepseek/deepseek-v4-pro"
    used = TokenUsage(input_tokens=1000, output_tokens=200)
    failed = ToolLoopResult(success=False, output="", error=LIVE_402, usage=used)
    monkeypatch.setattr(backend, "_tool_loop", AsyncMock(return_value=failed), raising=False)
    recorded = AsyncMock()
    monkeypatch.setattr("src.modules.tracking.usage.record_cancelled_loop", recorded)
    with pytest.raises(BillingLimitReachedError) as caught:
        await backend.tool_loop("s", [], [], None, 3, paper_id="p", specialist="paper_drafter")
    assert caught.value.status == KEY_LIMIT and caught.value.specialist == "paper_drafter"
    recorded.assert_awaited_once()
    assert recorded.await_args.args[-1] is used  # billed before the refusal: in the study's cost


async def test_a_failure_that_is_not_about_money_still_returns(monkeypatch):
    from src.modules.llm import openrouter

    backend = openrouter.OpenRouterBackend.__new__(openrouter.OpenRouterBackend)
    backend._model = "m"
    failed = ToolLoopResult(success=False, output="", error="Error code: 500 - upstream", usage=TokenUsage())
    monkeypatch.setattr(backend, "_tool_loop", AsyncMock(return_value=failed), raising=False)
    assert (await backend.tool_loop("s", [], [], None, 3)).error == "Error code: 500 - upstream"


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, specialist=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


async def test_no_attempt_is_counted(tmp_path, monkeypatch):
    from src.core.specialists import dispatcher
    from src.core.specialists.contracts import WorkOrder

    calls: list[str] = []

    async def fake_run_specialist(*, work_order, **kw):
        calls.append(work_order.specialist)
        raise BillingLimitReachedError("openrouter", LIVE_402, KEY_LIMIT)

    monkeypatch.setattr(dispatcher, "run_specialist", fake_run_specialist)
    wo = WorkOrder(paper_id="p", specialist="paper_drafter", focus="draft")
    with pytest.raises(BillingLimitReachedError) as caught:
        await dispatcher.run_with_attempts(wo, MagicMock(), tmp_path, "m", backend_name="openrouter")
    assert calls == ["paper_drafter"] and caught.value.specialist == "paper_drafter"


async def test_the_run_pauses_with_the_sentence(tmp_path, events):
    from src.core.strategist.runner import PipelineRunner

    paper_id = str(uuid.uuid4())
    ws = tmp_path / paper_id
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": paper_id, "title": "T", "research_question": "Q?"}))
    runner = PipelineRunner(
        paper_id=paper_id, workspace=ws, backend=MagicMock(), model="m", mode="single_pass", backend_name="openrouter"
    )
    statuses: list[tuple[str, str | None]] = []

    async def _execute(sql: str, params: dict | None = None):
        if params and "s" in params and "papers" in sql.lower():
            statuses.append((params["s"], params.get("e")))

    async def _initial(self):
        raise BillingLimitReachedError("openrouter", LIVE_402, KEY_LIMIT, "idea_developer")

    with (
        patch("src.db.client.execute", side_effect=_execute),
        patch("src.core.strategist.runner.PipelineRunner._run_initial_phase", _initial),
    ):
        result = await runner.run()
    assert result["status"] == "paused" and result["reason"] == "billing_limit"
    assert statuses[-1] == ("paused", KEY_LIMIT)
    assert "failed" not in [s for s, _ in statuses]
    kinds = [k for k, _s, _p in events]
    assert "paused_billing_limit" in kinds and "failed" not in kinds
    assert runner._failure_counts.get("idea_developer", 0) == 0


async def test_a_send_back_that_hits_the_limit_is_kept_for_resume(tmp_path: Path, events):
    """The demo case: the drafter sent back at the draft review hits 402; Resume sends it back again."""
    from src.core.specialists.contracts import Contribution
    from src.core.strategist.state import HumanReviewRequestedError
    from tests.test_researcher_step import PID
    from tests.test_researcher_step import _runner as step_runner

    r = step_runner(tmp_path, [{"kind": "researcher", "name": "review_draft", "files": ["paper_draft.tex"]}])
    st = r._state
    st.pending_review_stage = "review_draft"
    st.metadata["review"] = {"kind": "researcher", "files": ["paper_draft.tex"]}
    remarks = [
        {"target": "paper_drafter", "remark": "The counts show no rise; say so."},
        {"target": "abstract_writer", "remark": "Match the draft."},
    ]
    st.metadata["rerun"] = list(remarks)
    st.metadata["sent_back"] = True

    async def _billing(orders):
        raise BillingLimitReachedError("openrouter", LIVE_402, KEY_LIMIT, orders[0].specialist)

    r._execute_orders = _billing
    with pytest.raises(BillingLimitReachedError):
        await r._settle_researcher_decisions(st)
    assert st.metadata["rerun"] == remarks and st.metadata["sent_back"] is True
    assert st.pending_review_stage == "review_draft"
    saved = json.loads((tmp_path / ".pipeline_state.json").read_text(encoding="utf-8"))
    assert saved["metadata"]["rerun"] == remarks  # what Resume reads

    # Resume after topping up: both are sent back, then the run stops at the draft review again.
    ran: list[str] = []

    async def _exec(orders):
        ran.extend(o.specialist for o in orders)
        return [Contribution(paper_id=PID, specialist=o.specialist, output="", success=True) for o in orders]

    r._execute_orders = _exec
    r._recheck_after_send_back = AsyncMock()
    with pytest.raises(HumanReviewRequestedError):
        await r._settle_researcher_decisions(st)
    assert ran == ["paper_drafter", "abstract_writer"] and "rerun" not in st.metadata
