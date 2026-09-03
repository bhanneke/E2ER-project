"""Governance at the SPECIALIST-CONTRACT layer (WS-B, second half).

The three deterministic gates (estimation / numbers / citations) already
honoured the regime. The contract layer did not: `run_specialist` flipped a
hollow artifact to failure and `assert_artifacts_written` raised, in EVERY
regime. So `--governance off` still blocked — it FAILED on a missing artifact
and PAUSED (circuit breaker) on a non-compliant one — which made `off` and
`contracts` indistinguishable and the experiment's control cell invalid.

These tests pin the fix: under `off` a VERIFICATION check still RUNS and is
logged as `gate_shadow` without blocking; under `contracts`/`full` it blocks.

Revised 2026-08-11. The original version let `off` shadow everything, including
whether the artifact existed and parsed. That made the control cell measure a
broken pipeline instead of an ungoverned one — see ROBUSTNESS_REVIEW.md.
Reliability checks (file written, parses, not `{}`) now block in every regime;
only verification checks (a real regression was run, it implements the declared
spec) are switchable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.core.governance import DEFAULT_REGIME, GATES, REGIMES, enforces
from src.core.specialists.contracts import Contribution
from src.core.specialists.dispatcher import assert_artifacts_written, find_missing_artifacts, guard_artifacts
from src.modules.llm.base import LLMBackend, TokenUsage, ToolHandler, ToolLoopResult


async def _async_noop(*args, **kwargs):
    return None


# ── the regime matrix ────────────────────────────────────────────────────────


def test_full_enforces_every_gate():
    for gate in GATES:
        assert enforces("full", gate) is True


def test_contracts_enforces_only_contracts():
    assert enforces("contracts", "contracts") is True
    for gate in ("estimation", "numbers", "citations"):
        assert enforces("contracts", gate) is False


def test_off_enforces_nothing():
    for gate in GATES:
        assert enforces("off", gate) is False


def test_unknown_regime_fails_closed():
    """A typo must not silently disable the institutions."""
    for gate in GATES:
        assert enforces("nonsense", gate) is enforces(DEFAULT_REGIME, gate)


def test_runner_reads_the_same_matrix():
    """The bug was two tables: the runner had one, the specialist layer had
    none. Pin that the runner delegates rather than keeping its own copy."""
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    for regime in REGIMES:
        r._governance = regime
        for gate in GATES:
            assert r._governance_enforces(gate) is enforces(regime, gate)


# ── run_specialist: the contract flip ────────────────────────────────────────


class _HollowArtifactBackend(LLMBackend):
    """Succeeds, but writes the M4 failure mode: `estimation_results.json` == "{}"."""

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
            {"path": "econometric_spec.md", "content": "# Spec\n\n" + ("Substantive content. " * 30)},
        )
        await tool_handler.handle("write_file", {"path": "estimation_results.json", "content": "{}"})
        return ToolLoopResult(
            success=True, output="done", tool_calls_made=2, usage=TokenUsage(input_tokens=10, output_tokens=5)
        )


class _DescriptiveOnlyBackend(LLMBackend):
    """Succeeds and writes a REAL, parseable, non-empty results file that
    happens to carry no estimated regression — descriptives only.

    Reliability is satisfied (the script ran, the file is substantive); the
    verification contract `check_has_regression` is not. This is the case a
    regime is legitimately allowed to shadow.
    """

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
            {"path": "econometric_spec.md", "content": "# Spec\n\n" + ("Substantive content. " * 30)},
        )
        await tool_handler.handle(
            "write_file",
            {
                "path": "estimation_results.json",
                "content": json.dumps({"raw_gap": 0.42, "n": 1677, "_note": "descriptives only, no regression"}),
            },
        )
        return ToolLoopResult(
            success=True, output="done", tool_calls_made=2, usage=TokenUsage(input_tokens=10, output_tokens=5)
        )


async def _run_backend(backend: LLMBackend, workspace: Path, paper_id: str, governance: str):
    from src.core.specialists.base import run_specialist
    from src.core.specialists.contracts import WorkOrder

    wo = WorkOrder(paper_id=paper_id, specialist="econometrics_specialist", focus="Specify.", context_tier=1)
    logged = AsyncMock(return_value=None)
    with (
        patch("src.core.specialists.base.save_usage", new=_async_noop),
        patch("src.core.specialists.base.compute_cost", return_value=0),
        patch("src.db.client.execute", new=_async_noop),
        patch("src.db.events.log_event", new=logged),
    ):
        contribution = await run_specialist(
            wo,
            backend=backend,
            workspace=workspace,
            model="claude-test",
            extra_tools=[],
            extra_handlers=[],
            backend_name="mock",
            governance=governance,
        )
    return contribution, logged


async def _run_hollow(workspace: Path, paper_id: str, governance: str):
    return await _run_backend(_HollowArtifactBackend(), workspace, paper_id, governance)


@pytest.mark.parametrize("regime", ["full", "contracts"])
async def test_contract_violation_blocks_when_enforced(tmp_workspace: Path, paper_id: str, regime: str):
    contribution, logged = await _run_hollow(tmp_workspace, paper_id, regime)

    from src.core.specialists.contract_check import read_contract_feedback

    assert contribution.success is False
    assert "contract violation" in contribution.error
    # The retry gets the WHY (consume-once coaching feedback).
    assert read_contract_feedback(tmp_workspace, "econometrics_specialist")
    kinds = [c.args[1] for c in logged.await_args_list]
    assert "gate_enforced" in kinds


async def test_hollow_artifact_blocks_even_under_off(tmp_workspace: Path, paper_id: str):
    """`{}` is a RELIABILITY failure, and no regime may switch it off.

    This test previously asserted the opposite. The 2026-08-05 validation cell
    showed why that was wrong: the estimation script crashed on a timezone
    comparison and wrote `{}`, `off` shadowed the check, nothing flipped the
    specialist to failure, the captured traceback was therefore never fed back
    for a retry, and the drafter wrote four tables of invented numbers over the
    hole. That run measured a broken pipeline, not an ungoverned one.
    """
    from src.core.specialists.contract_check import read_contract_feedback

    contribution, logged = await _run_hollow(tmp_workspace, paper_id, "off")

    assert contribution.success is False
    assert "contract violation" in (contribution.error or "")
    # The retry still gets the WHY, in every regime.
    assert read_contract_feedback(tmp_workspace, "econometrics_specialist")
    kinds = [c.args[1] for c in logged.await_args_list]
    assert "gate_enforced" in kinds


async def test_verification_violation_is_shadowed_under_off(tmp_workspace: Path, paper_id: str):
    """The real control cell: a substantive results file with no regression in
    it passes reliability and fails verification, so `off` lets it through and
    records the verdict."""
    from src.core.specialists.contract_check import read_contract_feedback

    contribution, logged = await _run_backend(_DescriptiveOnlyBackend(), tmp_workspace, paper_id, "off")

    assert contribution.success is True
    assert "contract violation" not in (contribution.error or "")
    # No coaching → the next attempt isn't nudged, which is what makes the
    # regime a treatment rather than a label.
    assert read_contract_feedback(tmp_workspace, "econometrics_specialist") in (None, "")
    # Still MEASURED.
    shadow = [c for c in logged.await_args_list if c.args[1] == "gate_shadow"]
    assert shadow, "an unenforced verification violation must still be logged"
    payload = shadow[0].kwargs["payload"]
    assert payload["gate"] == "contracts"
    assert payload["passed"] is False
    assert payload["enforced"] is False
    assert payload["regime"] == "off"


@pytest.mark.parametrize("regime", ["full", "contracts"])
async def test_verification_violation_blocks_when_enforced(tmp_workspace: Path, paper_id: str, regime: str):
    contribution, _ = await _run_backend(_DescriptiveOnlyBackend(), tmp_workspace, paper_id, regime)
    assert contribution.success is False
    assert "contract violation" in (contribution.error or "")


def test_reliability_never_switchable():
    from src.core.governance import KIND_RELIABILITY, KIND_VERIFICATION, enforces_check

    for regime in REGIMES + ("nonsense",):
        assert enforces_check(regime, "contracts", KIND_RELIABILITY) is True
    assert enforces_check("off", "contracts", KIND_VERIFICATION) is False
    for regime in ("contracts", "full"):
        assert enforces_check(regime, "contracts", KIND_VERIFICATION) is True


async def test_default_regime_still_blocks(tmp_workspace: Path, paper_id: str):
    """Callers that don't pass a regime keep the pre-WS-B behaviour."""
    from src.core.specialists.base import run_specialist
    from src.core.specialists.contracts import WorkOrder

    wo = WorkOrder(paper_id=paper_id, specialist="econometrics_specialist", focus="Specify.", context_tier=1)
    with (
        patch("src.core.specialists.base.save_usage", new=_async_noop),
        patch("src.core.specialists.base.compute_cost", return_value=0),
        patch("src.db.client.execute", new=_async_noop),
        patch("src.db.events.log_event", new=AsyncMock(return_value=None)),
    ):
        c = await run_specialist(
            wo,
            backend=_HollowArtifactBackend(),
            workspace=tmp_workspace,
            model="claude-test",
            extra_tools=[],
            extra_handlers=[],
            backend_name="mock",
        )
    assert c.success is False


# ── the cascade guard (missing canonical artifact) ───────────────────────────


def _missing_artifact_contribs() -> list[Contribution]:
    return [Contribution(paper_id="p1", specialist="econometrics_specialist", output="", success=True)]


def test_find_missing_artifacts_is_regime_independent(tmp_path: Path):
    """The CHECK never changes — only whether it blocks."""
    missing = find_missing_artifacts(_missing_artifact_contribs(), tmp_path)
    assert [m[0] for m in missing] == ["econometrics_specialist"]


@pytest.mark.parametrize("regime", ["full", "contracts"])
async def test_cascade_guard_raises_when_enforced(tmp_path: Path, regime: str):
    with patch("src.db.events.log_event", new=AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="did not produce canonical artifact"):
            await guard_artifacts(_missing_artifact_contribs(), tmp_path, regime)


async def test_cascade_guard_halts_in_every_regime(tmp_path: Path):
    """A missing canonical artifact halts under `off` too.

    This test previously asserted the opposite, on the theory that letting the
    cascade run measures what an ungoverned pipeline ships. It does not: a
    specialist that produced nothing starves every specialist downstream, so
    what gets measured is the collapse, not the governance. Reliability is not
    a treatment condition.
    """
    logged = AsyncMock(return_value=None)
    with patch("src.db.events.log_event", new=logged), pytest.raises(RuntimeError, match="canonical artifact"):
        await guard_artifacts(_missing_artifact_contribs(), tmp_path, "off")

    enforced = [c for c in logged.await_args_list if c.args[1] == "gate_enforced"]
    assert enforced
    assert enforced[0].kwargs["payload"]["check"] == "missing_artifact"
    assert enforced[0].kwargs["payload"]["enforced"] is True


async def test_cascade_guard_silent_when_artifacts_present(tmp_path: Path):
    (tmp_path / "estimation_results.json").write_text(json.dumps({"main": {"coefficients": {"x": {"estimate": 1}}}}))
    (tmp_path / "econometric_spec.md").write_text("# Spec\n" + "content " * 50)
    logged = AsyncMock(return_value=None)
    with patch("src.db.events.log_event", new=logged):
        await guard_artifacts(_missing_artifact_contribs(), tmp_path, "off")
    assert not logged.await_args_list


def test_unconditional_assert_still_available(tmp_path: Path):
    """`assert_artifacts_written` keeps its always-enforcing semantics for
    callers (and tests) that want the check without a regime."""
    with pytest.raises(RuntimeError):
        assert_artifacts_written(_missing_artifact_contribs(), tmp_path)


# ── the regime reaches the specialist layer through the dispatcher ───────────


async def test_dispatcher_threads_regime_to_run_specialist(tmp_path: Path):
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import execute_work_order

    seen: dict = {}

    async def fake_run_specialist(**kwargs):
        seen.update(kwargs)
        return Contribution(paper_id="p1", specialist="paper_drafter", output="", success=True)

    with (
        patch("src.core.specialists.dispatcher.run_specialist", new=fake_run_specialist),
        patch("src.db.events.log_event", new=AsyncMock(return_value=None)),
    ):
        await execute_work_order(
            WorkOrder(paper_id="p1", specialist="paper_drafter", focus="f", context_tier=0),
            backend=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            model="m",
            governance="off",
        )
    assert seen["governance"] == "off"


async def test_execute_parallel_threads_regime(tmp_path: Path):
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import execute_parallel

    seen: list[str] = []

    async def fake_run_specialist(**kwargs):
        seen.append(kwargs["governance"])
        return Contribution(paper_id="p1", specialist=kwargs["work_order"].specialist, output="", success=True)

    with (
        patch("src.core.specialists.dispatcher.run_specialist", new=fake_run_specialist),
        patch("src.db.events.log_event", new=AsyncMock(return_value=None)),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new=_async_noop),
    ):
        await execute_parallel(
            [
                WorkOrder(paper_id="p1", specialist="peer_reviewer", focus="f", context_tier=0),
                WorkOrder(paper_id="p1", specialist="technical_reviewer", focus="f", context_tier=0),
            ],
            backend=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            model="m",
            governance="off",
        )
    assert seen == ["off", "off"]


async def test_runner_passes_its_regime_into_dispatch(tmp_path: Path):
    """End of the chain: PipelineRunner(governance=…) must reach the
    dispatcher, or the whole thread is decorative."""
    from src.core.specialists.contracts import WorkOrder as CWorkOrder
    from src.core.strategist.actions import StrategistDecision, WorkOrder
    from src.core.strategist.runner import PipelineRunner

    seen: dict = {}

    async def fake_execute_work_order(*args, **kwargs):
        seen["positional"] = args
        return Contribution(paper_id="p1", specialist="paper_drafter", output="", success=True)

    r = PipelineRunner.__new__(PipelineRunner)
    r._governance = "off"
    r._paper_id = "p1"
    r._workspace = tmp_path
    r._backend = None
    r._model = "m"
    r._backend_name = "mock"
    r._extra_tools = []
    r._extra_handlers = []
    r._failure_counts = {}
    r._last_specialist_errors = {}
    r._iteration = 1
    r._mode = "single_pass"

    decision = StrategistDecision(
        action="dispatch_work_order",
        work_orders=[WorkOrder(specialist="paper_drafter", focus="f", parallel_group=0, context_tier=0)],
    )

    with (
        patch("src.core.specialists.dispatcher.execute_work_order", new=fake_execute_work_order),
        patch("src.core.specialists.dispatcher.guard_artifacts", new=AsyncMock(return_value=None)) as guard,
        patch.object(
            PipelineRunner,
            "_to_contract_orders",
            lambda self, wos: [CWorkOrder(paper_id="p1", specialist="paper_drafter", focus="f", context_tier=0)],
        ),
    ):
        await r._dispatch(decision)

    assert seen["positional"][-1] == "off"
    assert guard.await_args.args[-1] == "off"
