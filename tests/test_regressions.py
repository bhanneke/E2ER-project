"""Regression tests for bugs found during the live OpenRouter+Allium test session.

Every bug that cost real API money during the May 2026 live test gets a
unit test here. Each test is mock-only (no network, no real DB, no real
LLM) so the suite runs in seconds and catches regressions before they
hit a billable run.

Bug ledger (and the test that pins it):
  G1  dict_row factory had wrong signature (psycopg3 protocol mismatch)
       → every fetch_one/fetch_all 500'd      [test_db_uses_psycopg_dict_row]
  G2  create_paper INSERTed via fetch_one without RETURNING
       → papers row silently not persisted    [test_create_paper_uses_execute_not_fetch_one]
  G3  Settings rejected POSTGRES_PASSWORD env var
       → app refused to start                 [test_settings_tolerates_extra_env_vars]
  G4  LiteratureToolHandler had no per-call budget
       → Sonnet ran 36 tool calls, $2.80      [test_literature_handler_enforces_search_budget]
                                              [test_literature_handler_enforces_fetch_budget]
                                              [test_literature_handler_enforces_save_budget]
                                              [test_literature_handler_budgets_are_per_instance]
  G5  data_analyst's prompt didn't mandate Allium when available
       → model fabricated data ("synthetic   [test_data_analyst_prompt_mandates_allium]
       but calibrated")                       [test_data_analyst_prompt_skips_mandate_without_allium]
  G6  Strategist example omitted data_analyst
       → strategist never dispatched it       [test_strategist_system_prompt_includes_data_analyst]
                                              [test_strategist_system_prompt_includes_data_architect]
  G7  _MAX_TURNS was too tight (15) for Sonnet tool-rich specialists
       → idea_developer hit cap, success=False [test_max_turns_is_at_least_25]
  G8  check_approval didn't return rejection note
       → model saw "rejected" with no reason  [test_check_approval_returns_rejection_note]
       → kept polling, hit max_turns          [test_check_approval_returns_pending_message]
                                              [test_check_approval_returns_approval_message]
  G9  Strategist usage was never persisted   [test_strategist_decide_persists_usage]
       → cost under-reported by ~30-50%       [test_strategist_ceiling_check_persists_usage]
                                              [test_strategist_self_attack_persists_usage]
                                              [test_strategist_decide_retry_persists_usage]

Plus general regression coverage for behaviors that worked but should
stay working:
  R1  finish_reason="length" must NOT loop   [test_openrouter_bails_on_finish_length]
  R2  Strategist JSON parser handles fenced  [test_parse_decision_handles_fenced_json]
                                              [...prose-only, balanced-braces, etc. — already in test_pipeline.py]
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# G1: db.client uses psycopg's stdlib dict_row, not a custom mis-implemented one
# ---------------------------------------------------------------------------


def test_db_uses_psycopg_dict_row():
    """fetch_one and fetch_all must import dict_row from psycopg.rows.
    The custom _dict_row(cursor, data) signature broke psycopg3's row-factory
    protocol and made every DB read raise TypeError on the live system."""
    from src.db import client as dbclient

    src = Path(dbclient.__file__).read_text()
    # Must NOT define a 2-arg _dict_row that takes (cursor, data) directly.
    assert "def _dict_row(cursor, data):" not in src, (
        "Custom _dict_row(cursor, data) is the broken signature — use psycopg.rows.dict_row instead."
    )
    # Must import psycopg's stdlib factory.
    assert "from psycopg.rows import dict_row" in src, "fetch_one/fetch_all should use the stdlib dict_row factory."


# ---------------------------------------------------------------------------
# G2: create_paper INSERT must use execute(), not fetch_one()
# ---------------------------------------------------------------------------


async def test_create_paper_uses_execute_not_fetch_one():
    """The papers INSERT has no RETURNING clause; fetch_one() was raising
    'the last operation didn't produce records' and silently dropping the
    paper, causing FK violations on every downstream insert."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    captured_calls: list[tuple[str, dict | None]] = []

    async def fake_execute(sql, params=None):
        captured_calls.append(("execute", params or {}))
        return None

    async def fake_fetch_one(sql, params=None):
        captured_calls.append(("fetch_one", params or {}))
        # Match the real bug — fetch_one(INSERT without RETURNING) raises.
        raise RuntimeError("the last operation didn't produce records")

    with (
        patch("src.db.client.execute", side_effect=fake_execute),
        patch("src.db.client.fetch_one", side_effect=fake_fetch_one),
        # Stub out the background task so we don't actually run a pipeline.
        patch("src.api.app._run_pipeline", new_callable=AsyncMock),
    ):
        from src.api.app import app

        client = TestClient(app)
        resp = client.post(
            "/api/papers",
            json={
                "title": "T",
                "research_question": "RQ?",
                "mode": "single_pass",
                "max_cost_usd": 1.0,
            },
        )
    assert resp.status_code == 200
    # The INSERT into papers must have happened via execute, never fetch_one.
    insert_calls = [kind for kind, params in captured_calls if "id" in params and "title" in params and "rq" in params]
    assert insert_calls, "create_paper never sent the INSERT"
    assert all(k == "execute" for k in insert_calls), (
        f"INSERT papers must use execute() (no RETURNING clause); got {insert_calls}"
    )


# ---------------------------------------------------------------------------
# G3: Settings tolerate extra env vars (POSTGRES_PASSWORD etc.)
# ---------------------------------------------------------------------------


def test_settings_tolerates_extra_env_vars(monkeypatch):
    """Pydantic Settings was rejecting POSTGRES_PASSWORD (used by docker
    compose for variable substitution) as 'extra_forbidden'. Result: app
    refused to start when running against a docker stack."""
    from src.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("POSTGRES_PASSWORD", "anything")
    monkeypatch.setenv("SOME_OTHER_RANDOM_VAR", "ignore-me")
    monkeypatch.setenv("DB_PASSWORD", "test")
    # If model_config has extra="ignore" (or "allow"), this should not raise.
    s = Settings()
    assert s.db_password == "test"
    cfg = getattr(Settings, "model_config", {})
    assert cfg.get("extra") in {"ignore", "allow"}, (
        f"Settings model_config must tolerate extra env vars (got extra={cfg.get('extra')!r})"
    )


# ---------------------------------------------------------------------------
# G4: LiteratureToolHandler enforces per-call budgets
# ---------------------------------------------------------------------------


async def test_literature_handler_enforces_search_budget():
    """A single literature_scanner on Sonnet 4.6 made 36 search/fetch/save
    calls and burned $2.80. Budget cap stops this."""
    from src.modules.literature.tools import LiteratureToolHandler

    handler = LiteratureToolHandler(Path("/tmp"))
    # Stub the real client so we don't hit OpenAlex.
    fake_searcher = AsyncMock(return_value=MagicMock(papers=[]))
    with patch("src.modules.literature.openalex.search_papers", fake_searcher):
        cap = LiteratureToolHandler._MAX_SEARCHES
        # First `cap` calls go through.
        for i in range(cap):
            r = await handler.handle("search_papers", {"query": f"q{i}", "limit": 1})
            assert "budget exhausted" not in r, f"call {i + 1} hit budget too early"
        # The next call must hit the cap.
        r = await handler.handle("search_papers", {"query": "qN+1", "limit": 1})
        out = json.loads(r)
        assert "budget exhausted" in (out.get("error") or "").lower()
        # Real client must NOT have been called past the cap.
        assert fake_searcher.call_count == cap


async def test_literature_handler_enforces_fetch_budget():
    from src.modules.literature.tools import LiteratureToolHandler

    handler = LiteratureToolHandler(Path("/tmp"))
    fake_fetcher = AsyncMock(return_value=None)
    with patch("src.modules.literature.openalex.fetch_by_doi", fake_fetcher):
        cap = LiteratureToolHandler._MAX_FETCHES
        for i in range(cap):
            await handler.handle("fetch_paper", {"doi": f"10.1/{i}"})
        r = await handler.handle("fetch_paper", {"doi": "10.1/over"})
        assert "budget exhausted" in (json.loads(r).get("error") or "").lower()


async def test_literature_handler_enforces_save_budget(tmp_path):
    from src.modules.literature.tools import LiteratureToolHandler

    handler = LiteratureToolHandler(tmp_path)
    cap = LiteratureToolHandler._MAX_SAVES
    for i in range(cap):
        entry = f"@article{{k{i}, title={{T}}, author={{A}}, year={{2024}}}}"
        await handler.handle("save_bibtex", {"bibtex_entry": entry})
    r = await handler.handle("save_bibtex", {"bibtex_entry": "@article{kover, title={T}, author={A}, year={2024}}"})
    assert "budget exhausted" in (json.loads(r).get("error") or "").lower()


async def test_literature_handler_budgets_are_per_instance(tmp_path):
    """Each specialist gets a fresh handler instance so the budget resets
    per specialist run. Without this, paper-level usage exhausts caps after
    the first specialist."""
    from src.modules.literature.tools import LiteratureToolHandler

    h1 = LiteratureToolHandler(tmp_path)
    h2 = LiteratureToolHandler(tmp_path)
    fake = AsyncMock(return_value=MagicMock(papers=[]))
    with patch("src.modules.literature.openalex.search_papers", fake):
        # Exhaust h1's budget
        for i in range(LiteratureToolHandler._MAX_SEARCHES + 2):
            await h1.handle("search_papers", {"query": f"q{i}", "limit": 1})
        # h2's budget should be untouched
        r = await h2.handle("search_papers", {"query": "fresh", "limit": 1})
        assert "budget exhausted" not in r


# ---------------------------------------------------------------------------
# G5: data_analyst prompt mandates Allium when query_allium is in extra_tools
# ---------------------------------------------------------------------------


def test_data_analyst_prompt_mandates_allium():
    """When data_analyst runs WITH query_allium in its tools, the system
    prompt MUST forbid synthetic data and instruct the model to use the
    Allium workflow. The live test caught Sonnet writing 'All figures are
    synthetic but calibrated' because this guard didn't exist."""
    from src.core.specialists.base import _build_system_prompt

    p = _build_system_prompt("data_analyst", "", has_allium=True)
    must_contain = [
        "Mandatory Data Sourcing",
        "DO NOT SYNTHESIZE",
        "synthetic",  # forbidden vocabulary explicitly listed
        "query_allium",
        "feasibility",
        "production",
    ]
    for token in must_contain:
        assert token in p, f"data_analyst prompt missing guard for {token!r} when has_allium=True"


def test_data_analyst_prompt_skips_mandate_without_allium():
    """When Allium is not available, the mandate block must be omitted —
    otherwise we'd be telling the model to use a tool that isn't there."""
    from src.core.specialists.base import _build_system_prompt

    p = _build_system_prompt("data_analyst", "", has_allium=False)
    assert "Mandatory Data Sourcing" not in p
    assert "query_allium" not in p


def test_other_specialists_do_not_get_allium_mandate():
    """Only data_analyst should receive the Allium mandate — putting it on
    everyone would confuse pure-text specialists like writers."""
    from src.core.specialists.base import _build_system_prompt

    for spec in ("paper_drafter", "abstract_writer", "mechanism_reviewer"):
        p = _build_system_prompt(spec, "", has_allium=True)
        assert "Mandatory Data Sourcing" not in p, f"{spec} should not get the data_analyst Allium mandate"


# ---------------------------------------------------------------------------
# G6: Strategist worked example must include data_architect AND data_analyst
# ---------------------------------------------------------------------------


def test_strategist_system_prompt_includes_data_analyst():
    """My earlier strategist example listed idea_developer, literature_scanner,
    identification_strategist, econometrics_specialist, paper_drafter,
    abstract_writer — but NOT data_analyst. Sonnet followed the example
    literally and never dispatched it. Result: empty data_summary, paper
    written on no data."""
    from src.core.strategist.engine import _STRATEGIST_SYSTEM

    assert "data_analyst" in _STRATEGIST_SYSTEM, (
        "Strategist worked example must include data_analyst — Sonnet "
        "follows examples literally and won't dispatch what isn't shown."
    )


def test_strategist_system_prompt_includes_data_architect():
    from src.core.strategist.engine import _STRATEGIST_SYSTEM

    assert "data_architect" in _STRATEGIST_SYSTEM


def test_strategist_system_prompt_warns_data_analyst_required():
    """Belt-and-suspenders: explicit instruction not to skip data_analyst."""
    from src.core.strategist.engine import _STRATEGIST_SYSTEM

    assert "data_analyst" in _STRATEGIST_SYSTEM
    # Look for the no-skip warning we added.
    assert (
        "ALWAYS include `data_analyst`" in _STRATEGIST_SYSTEM
        or "do not skip data_analyst" in _STRATEGIST_SYSTEM.lower()
        or "skipping it leaves the paper without empirical content" in _STRATEGIST_SYSTEM
    )


# ---------------------------------------------------------------------------
# G7: _MAX_TURNS must be loose enough for tool-rich specialists
# ---------------------------------------------------------------------------


def test_max_turns_is_at_least_25():
    """idea_developer on Sonnet routinely needs 20+ turns when literature
    tools are wired in. _MAX_TURNS=15 caused success=False with no artifact
    written. Don't drop below 25 without measuring."""
    from src.core.specialists.base import _MAX_TURNS

    assert _MAX_TURNS >= 25, f"_MAX_TURNS={_MAX_TURNS} is too tight for Sonnet"


# ---------------------------------------------------------------------------
# G8: check_approval returns the rejection note inline
# ---------------------------------------------------------------------------


async def test_check_approval_returns_rejection_note():
    """A rejected query without a returned note left the model unable to
    self-correct. It saw 'rejected' but had no idea what to fix. It then
    burned through max_turns polling. The fix: return the researcher's
    note inside the tool response."""
    from src.modules.data.tools import AlliumToolHandler

    handler = AlliumToolHandler("paper-1", "data_analyst", dictionary=None)

    async def fake_status(qid):
        return ("rejected", "transaction-level — please aggregate per platform")

    with patch(
        "src.modules.data.audit.get_approval_status_with_note",
        side_effect=fake_status,
    ):
        out = await handler.handle("check_approval", {"query_id": "abc"})
    assert "REJECTED" in out
    assert "transaction-level" in out  # the actual note
    assert "aggregate per platform" in out


async def test_check_approval_returns_approval_message():
    from src.modules.data.tools import AlliumToolHandler

    handler = AlliumToolHandler("p", "data_analyst", dictionary=None)

    async def fake(qid):
        return ("approved", "ok")

    with patch("src.modules.data.audit.get_approval_status_with_note", side_effect=fake):
        out = await handler.handle("check_approval", {"query_id": "x"})
    assert "APPROVED" in out


async def test_check_approval_returns_pending_message():
    from src.modules.data.tools import AlliumToolHandler

    handler = AlliumToolHandler("p", "data_analyst", dictionary=None)

    async def fake(qid):
        return ("pending", "")

    with patch("src.modules.data.audit.get_approval_status_with_note", side_effect=fake):
        out = await handler.handle("check_approval", {"query_id": "x"})
    assert "pending" in out.lower()
    # Must instruct the model to wait, not submit duplicates.
    assert "duplicate" in out.lower() or "wait" in out.lower()


# ---------------------------------------------------------------------------
# G9: Strategist call usage is persisted to llm_usage
# ---------------------------------------------------------------------------


def _stub_engine(tmp_path: Path):
    """Build a StrategistEngine wired to a backend that returns canned usage."""
    from src.core.strategist.engine import StrategistEngine
    from src.modules.llm.base import TokenUsage, ToolLoopResult

    backend = MagicMock()
    backend.tool_loop = AsyncMock(
        return_value=ToolLoopResult(
            success=True,
            output='{"action":"complete","work_orders":[],"rationale":"done"}',
            usage=TokenUsage(input_tokens=1000, output_tokens=500),
        )
    )
    return StrategistEngine(
        backend,
        tmp_path,
        "paper-x",
        mode="single_pass",
        model="anthropic/claude-haiku-4.5",
        backend_name="openrouter",
    )


async def test_strategist_decide_persists_usage(tmp_path):
    """Before this fix, decide() accumulated total_usage in memory but never
    wrote to llm_usage — costs were under-reported by ~30-50%."""
    eng = _stub_engine(tmp_path)
    saves: list[dict] = []

    async def fake_save(**kwargs):
        saves.append(kwargs)

    with patch("src.modules.tracking.usage.save_usage", side_effect=fake_save):
        await eng.decide("designing", iteration=0)

    assert any("strategist:decide" in s["specialist"] for s in saves), (
        f"strategist.decide() did not persist usage; saves={[s['specialist'] for s in saves]}"
    )
    # Usage must include the canned tokens.
    spec_save = next(s for s in saves if s["specialist"] == "strategist:decide")
    assert spec_save["usage"].input_tokens == 1000
    assert spec_save["usage"].output_tokens == 500
    assert spec_save["paper_id"] == "paper-x"
    assert spec_save["model"] == "anthropic/claude-haiku-4.5"


async def test_strategist_decide_retry_persists_usage(tmp_path):
    """When the first decide() returns prose, we retry — both calls must
    appear in llm_usage."""
    from src.core.strategist.engine import StrategistEngine
    from src.modules.llm.base import TokenUsage, ToolLoopResult

    backend = MagicMock()
    # First call returns prose (forces retry); second returns valid JSON.
    backend.tool_loop = AsyncMock(
        side_effect=[
            ToolLoopResult(
                success=True,
                output="## Just markdown",
                usage=TokenUsage(input_tokens=500, output_tokens=200),
            ),
            ToolLoopResult(
                success=True,
                output='{"action":"complete","work_orders":[],"rationale":"done"}',
                usage=TokenUsage(input_tokens=400, output_tokens=100),
            ),
        ]
    )
    eng = StrategistEngine(
        backend,
        tmp_path,
        "p",
        "single_pass",
        model="m",
        backend_name="openrouter",
    )

    saves: list[dict] = []

    async def fake_save(**kw):
        saves.append(kw)

    with patch("src.modules.tracking.usage.save_usage", side_effect=fake_save):
        await eng.decide("designing", iteration=0)

    specs = [s["specialist"] for s in saves]
    assert "strategist:decide" in specs
    assert "strategist:decide_retry" in specs


async def test_strategist_ceiling_check_persists_usage(tmp_path):
    eng = _stub_engine(tmp_path)
    # Override backend output for ceiling_check (returns a verdict JSON)
    from src.modules.llm.base import TokenUsage, ToolLoopResult

    eng._backend.tool_loop = AsyncMock(
        return_value=ToolLoopResult(
            success=True,
            output='{"verdict": "proceed_to_review", "reason": "ok"}',
            usage=TokenUsage(input_tokens=2000, output_tokens=300),
        )
    )

    saves: list[dict] = []

    async def fake(**kw):
        saves.append(kw)

    with patch("src.modules.tracking.usage.save_usage", side_effect=fake):
        await eng.ceiling_check(iteration=1, pivot_count=0)

    assert any(s["specialist"] == "strategist:ceiling_check" for s in saves)


async def test_strategist_self_attack_persists_usage(tmp_path):
    eng = _stub_engine(tmp_path)
    from src.modules.llm.base import TokenUsage, ToolLoopResult

    eng._backend.tool_loop = AsyncMock(
        return_value=ToolLoopResult(
            success=True,
            output='{"findings": [], "overall_severity": 1}',
            usage=TokenUsage(input_tokens=3000, output_tokens=200),
        )
    )

    saves: list[dict] = []

    async def fake(**kw):
        saves.append(kw)

    with patch("src.modules.tracking.usage.save_usage", side_effect=fake):
        await eng.run_self_attack()

    assert any(s["specialist"] == "strategist:self_attack" for s in saves)


# ---------------------------------------------------------------------------
# R1: OpenRouter must bail on finish_reason="length", not loop forever
# ---------------------------------------------------------------------------


async def test_openrouter_bails_on_finish_length():
    """Hitting max_tokens=4096 mid-tool-call repeatedly looped forever
    before this guard. Verify the loop returns success=False with a clear
    error message instead of cycling."""
    pytest.importorskip("openai")
    from src.modules.llm.base import ToolHandler
    from src.modules.llm.openrouter import OpenRouterBackend

    # Fake response with finish_reason="length"
    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.finish_reason = "length"
    fake_choice.message.content = "partial output truncated..."
    fake_choice.message.tool_calls = []
    fake_response.choices = [fake_choice]
    fake_response.usage.prompt_tokens = 500
    fake_response.usage.completion_tokens = 4096

    fake_create = AsyncMock(return_value=fake_response)

    # Bypass __init__ which requires a real API key.
    backend = OpenRouterBackend.__new__(OpenRouterBackend)
    backend._client = MagicMock()
    backend._client.chat.completions.create = fake_create
    backend._model = "test-model"
    backend._max_tokens = 4096

    class NoopHandler(ToolHandler):
        async def handle(self, name, inp):
            return ""

    result = await backend.tool_loop(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        tool_handler=NoopHandler(),
        max_turns=10,
    )
    assert result.success is False
    assert result.stop_reason == "length"
    assert "max_tokens" in (result.error or "")
    # Must have made exactly ONE API call, not 10.
    assert fake_create.call_count == 1


# ---------------------------------------------------------------------------
# Operational invariants: the dispatcher's auto-fill + reviewer routing
# ---------------------------------------------------------------------------


async def test_dispatcher_auto_fills_canonical_output_file(tmp_path):
    """Strategist sometimes omits output_file; dispatcher must fill it
    from SPECIALIST_ARTIFACTS to prevent freelancing. (Already covered in
    test_pipeline.py, but pinned here to keep the regression set in one
    place for the cost-cutting story.)"""
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import _inject_context

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": "p",
                "title": "T",
                "research_question": "RQ",
                "datasets": [],
                "current_stage": "designing",
            }
        )
    )
    wo = WorkOrder(
        paper_id="p",
        specialist="data_analyst",
        focus="analyze",
        context_tier=1,
    )
    out = _inject_context(wo, tmp_path)
    assert out.output_file == "data_summary.md"


# ---------------------------------------------------------------------------
# Cost-tracking integration: a paper run touches every persistence path
# ---------------------------------------------------------------------------


async def test_strategist_engine_constructor_takes_model_and_backend_name(tmp_path):
    """Without these args plumbed through, _record_usage can't tag the
    correct model and the cost row would be wrong even if persisted."""
    import inspect

    from src.core.strategist.engine import StrategistEngine

    sig = inspect.signature(StrategistEngine.__init__)
    assert "model" in sig.parameters
    assert "backend_name" in sig.parameters


def test_runner_passes_model_and_backend_to_strategist():
    """PipelineRunner.__init__ must wire model + backend_name through to
    the StrategistEngine — otherwise strategist usage rows are tagged
    'unknown' and cost reporting drifts."""
    from src.core.strategist.runner import PipelineRunner  # noqa: F401  (imported to validate the module exists)

    runner_path = Path(__file__).resolve().parent.parent / "src/core/strategist/runner.py"
    src_text = runner_path.read_text()
    # The construction site must pass model= and backend_name=
    assert "StrategistEngine(" in src_text
    # In a single block: backend, workspace, paper_id, mode, model=..., backend_name=...
    matches = re.findall(
        r"StrategistEngine\(\s*[^)]*\bmodel\s*=\s*model[^)]*\bbackend_name\s*=\s*backend_name",
        src_text,
        re.DOTALL,
    )
    assert matches, "PipelineRunner must construct StrategistEngine with model + backend_name"


# ===========================================================================
# Edge cases: graceful degradation under partial breakdown
# ---------------------------------------------------------------------------
# When the pipeline aborts mid-run (OpenRouter 402, cost cap, single-batch
# fail, user cancel) the partial artifacts must still be:
#   - Preserved on disk
#   - Compiled to PDF if a draft exists
#   - Audit-log-exported even without the replication_packager specialist
# These tests prove those invariants without spending a cent.
# ===========================================================================


def _make_workspace_with_manifest(tmp_path: Path, paper_id: str) -> Path:
    ws = tmp_path / paper_id
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(
        json.dumps(
            {
                "paper_id": paper_id,
                "title": "T",
                "research_question": "RQ",
                "datasets": [],
                "mode": "single_pass",
                "current_stage": "idea",
            }
        )
    )
    return ws


def _make_pipeline_runner(workspace: Path, paper_id: str, *, fail_at: str | None = None):
    """Build a PipelineRunner whose strategist returns a canned decision and
    whose specialists are mocked so we can simulate failure points."""
    from src.core.strategist.runner import PipelineRunner

    backend = MagicMock()
    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=backend,
        model="m",
        mode="single_pass",
        extra_tools=[],
        extra_handlers=[],
        backend_name="mock",
        max_cost_usd=10.0,
    )
    return runner


async def test_finalize_runs_compile_even_when_pipeline_failed(tmp_path):
    """If the pipeline raises mid-run, compile_latex must still be called
    (best-effort) so any partial paper_draft.tex gets a PDF attempt.
    Before this fix, compile only ran on the success path."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)
    # A draft to compile
    (workspace / "paper_draft.tex").write_text("\\section{Introduction}\nFailed mid-run but draft exists.\n")

    runner = _make_pipeline_runner(workspace, paper_id)
    runner._run_initial_phase = AsyncMock(side_effect=RuntimeError("simulated all-specialists failure"))

    compile_called = AsyncMock(return_value=None)
    audit_called = AsyncMock(return_value=None)

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", compile_called),
        patch.object(runner, "_export_audit_log_only", audit_called),
        patch.object(runner, "_run_github_push_phase", AsyncMock()),
    ):
        result = await runner.run()

    assert result["status"] == "failed"
    # Critical: compile + audit export ran even though the pipeline failed.
    assert compile_called.called, "Compile must run on failure path"
    assert audit_called.called, "Audit log export must run on failure path"


async def test_finalize_runs_compile_even_when_cancelled(tmp_path):
    """Same invariant for user cancellation: partial artifacts get finalized."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)

    runner = _make_pipeline_runner(workspace, paper_id)
    runner._run_initial_phase = AsyncMock(side_effect=asyncio.CancelledError())

    compile_called = AsyncMock(return_value=None)

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", compile_called),
        patch.object(runner, "_export_audit_log_only", AsyncMock()),
        patch.object(runner, "_run_github_push_phase", AsyncMock()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await runner.run()

    assert compile_called.called, "Compile must run on cancel path too"


async def test_finalize_swallows_compile_errors(tmp_path):
    """If compile itself raises, finalize must not propagate — other
    finalize steps still need to run."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)

    runner = _make_pipeline_runner(workspace, paper_id)
    runner._run_initial_phase = AsyncMock(side_effect=RuntimeError("phase failed"))

    audit_called = AsyncMock(return_value=None)
    push_called = AsyncMock(return_value=None)

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", AsyncMock(side_effect=RuntimeError("latex broken"))),
        patch.object(runner, "_export_audit_log_only", audit_called),
        patch.object(runner, "_run_github_push_phase", push_called),
    ):
        result = await runner.run()

    # The original pipeline error wins — but later finalize steps still ran.
    assert result["status"] == "failed"
    assert "phase failed" in result["error"]
    assert audit_called.called, "audit export must run even when compile raises"
    assert push_called.called, "github push must run even when compile raises"


async def test_partial_artifacts_preserved_on_failure(tmp_path):
    """Files written to the workspace before the failure point must still
    exist on disk after the run aborts. The runner should never delete or
    truncate user-visible artifacts."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)
    # Pretend an earlier specialist already wrote artifacts
    (workspace / "paper_plan.md").write_text("# Plan\n\nReal content.")
    (workspace / "literature_review.md").write_text("# Lit review\n\nReal content.")

    runner = _make_pipeline_runner(workspace, paper_id)
    runner._run_initial_phase = AsyncMock(side_effect=RuntimeError("late failure"))

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", AsyncMock()),
        patch.object(runner, "_export_audit_log_only", AsyncMock()),
        patch.object(runner, "_run_github_push_phase", AsyncMock()),
    ):
        await runner.run()

    # Files written before the failure must still be there.
    assert (workspace / "paper_plan.md").read_text().startswith("# Plan")
    assert (workspace / "literature_review.md").read_text().startswith("# Lit review")
    assert (workspace / "manifest.json").exists()
    # State checkpoint must be saved so resume works.
    assert (workspace / ".pipeline_state.json").exists()


async def test_failed_status_records_useful_last_error(tmp_path):
    """A failed paper's last_error must contain the originating exception
    type AND a useful message — not just a generic 'failed'."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)
    runner = _make_pipeline_runner(workspace, paper_id)
    runner._run_initial_phase = AsyncMock(side_effect=RuntimeError("Strategist returned no work orders"))

    captured: list[tuple[str, str | None]] = []

    async def fake_execute(sql, params=None):
        if params and "s" in params and "id" in params:
            captured.append((params.get("s"), params.get("e")))
        return None

    with (
        patch("src.db.client.execute", side_effect=fake_execute),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", AsyncMock()),
        patch.object(runner, "_export_audit_log_only", AsyncMock()),
        patch.object(runner, "_run_github_push_phase", AsyncMock()),
    ):
        result = await runner.run()

    assert result["status"] == "failed"
    # last_error written to DB must include both the type and the message.
    failed_writes = [(s, e) for s, e in captured if s == "failed"]
    assert failed_writes, "papers row never marked failed"
    s, err = failed_writes[-1]
    assert "RuntimeError" in (err or "")
    assert "Strategist returned no work orders" in (err or "")


async def test_audit_export_runs_independent_of_replication_packager(tmp_path):
    """The audit_log.csv export comes from the DB and must succeed even
    when the replication_packager specialist never ran — so a credit-out
    pipeline still leaves a provenance trail of the queries that did fire."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)
    runner = _make_pipeline_runner(workspace, paper_id)

    written: list[str] = []

    async def fake_audit_csv(pid, path):
        Path(path).write_text("query_id,sql,status\n")
        written.append(str(path))

    async def fake_data_sql(pid, path):
        Path(path).write_text("-- queries\n")
        written.append(str(path))

    with (
        patch("src.modules.data.audit.write_audit_csv", side_effect=fake_audit_csv),
        patch("src.modules.data.audit.write_data_queries_sql", side_effect=fake_data_sql),
    ):
        await runner._export_audit_log_only()

    assert any("audit_log.csv" in p for p in written)
    assert any("data_queries.sql" in p for p in written)
    assert (workspace / "replication" / "audit_log.csv").exists()
    assert (workspace / "replication" / "data_queries.sql").exists()


async def test_audit_export_skips_when_files_already_exist(tmp_path):
    """If replication phase already wrote the audit CSV, finalize must NOT
    overwrite it — that would clobber a successfully-completed run with
    an empty file from a re-run."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)
    rep = workspace / "replication"
    rep.mkdir()
    # Pretend replication phase already wrote real content
    (rep / "audit_log.csv").write_text("REAL CONTENT FROM REAL RUN\n")
    (rep / "data_queries.sql").write_text("-- REAL QUERIES\n")

    runner = _make_pipeline_runner(workspace, paper_id)
    overwrite_attempted = AsyncMock()

    with (
        patch("src.modules.data.audit.write_audit_csv", overwrite_attempted),
        patch("src.modules.data.audit.write_data_queries_sql", overwrite_attempted),
    ):
        await runner._export_audit_log_only()

    assert not overwrite_attempted.called, "must not clobber existing audit files"
    # Real content preserved.
    assert (rep / "audit_log.csv").read_text() == "REAL CONTENT FROM REAL RUN\n"


async def test_pipeline_failure_returns_useful_summary(tmp_path):
    """The result dict from runner.run() must contain status=failed and an
    error key that tools (like the API response) can surface to the user."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)
    runner = _make_pipeline_runner(workspace, paper_id)
    runner._run_initial_phase = AsyncMock(side_effect=Exception("OpenRouter 402"))

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", AsyncMock()),
        patch.object(runner, "_export_audit_log_only", AsyncMock()),
        patch.object(runner, "_run_github_push_phase", AsyncMock()),
    ):
        result = await runner.run()

    assert result["status"] == "failed"
    assert "error" in result
    assert "OpenRouter 402" in result["error"]


async def test_specialist_failure_in_dispatcher_records_failed_contribution():
    """When OpenRouter returns 402/403 mid-tool-loop, dispatcher must NOT
    drop the failure on the floor — it returns a Contribution(success=False)
    that flows into the audit trail."""
    from src.core.specialists.contracts import WorkOrder as ContractWO
    from src.core.specialists.dispatcher import execute_work_order
    from src.modules.llm.base import TokenUsage, ToolLoopResult

    fake_backend = MagicMock()
    fake_backend.tool_loop = AsyncMock(
        return_value=ToolLoopResult(
            success=False,
            output="",
            error="402: credit exhausted",
            tool_calls_made=0,
            usage=TokenUsage(),
        )
    )

    wo = ContractWO(
        paper_id=str(uuid.uuid4()),
        specialist="idea_developer",
        focus="develop",
        context_tier=0,
    )

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        (ws / "manifest.json").write_text("{}")
        with (
            patch("src.db.client.execute", new_callable=AsyncMock),
            patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        ):
            contribution = await execute_work_order(
                wo,
                fake_backend,
                ws,
                "m",
                [],
                [],
                "mock",
            )

    assert contribution.success is False
    assert "402" in (contribution.error or "")


# ---------------------------------------------------------------------------
# Cost-cap edge case: the cap must trip even when DB is unreachable
# ---------------------------------------------------------------------------


async def test_in_memory_cost_cap_trips_without_db():
    """check_budget must enforce the cap purely from in-memory contribution
    cost when the DB query raises. Without this, papers run unbounded
    against a non-DB workspace (the original $25 runaway scenario)."""
    from src.core.strategist.state import BudgetExceeded
    from src.modules.tracking.usage import check_budget

    async def boom(*a, **kw):
        raise RuntimeError("DB unreachable")

    with patch("src.db.client.fetch_one", side_effect=boom):
        # Under cap — passes
        await check_budget("p", max_cost_usd=10.0, in_memory_spent=4.0)
        # Over cap via in-memory — must raise
        with pytest.raises(BudgetExceeded):
            await check_budget("p", max_cost_usd=10.0, in_memory_spent=15.0)


# ---------------------------------------------------------------------------
# Resume-after-partial-failure: the state file must enable picking up
# ---------------------------------------------------------------------------


async def test_state_checkpoint_written_before_each_phase_save(tmp_path):
    """If we crash between phases, the state file must already record what
    we completed so the next run resumes correctly. Tested by simulating a
    failure after one phase succeeds."""
    paper_id = str(uuid.uuid4())
    workspace = _make_workspace_with_manifest(tmp_path, paper_id)

    # Build runner where initial phase succeeds, review phase fails.
    runner = _make_pipeline_runner(workspace, paper_id)

    async def first_phase_succeeds():
        pass

    async def review_phase_blows_up():
        raise RuntimeError("review phase OpenRouter 402")

    runner._run_initial_phase = AsyncMock(side_effect=first_phase_succeeds)
    runner._run_review_phase = AsyncMock(side_effect=review_phase_blows_up)

    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value={"spent": 0.0}),
        patch.object(runner, "_run_compile_phase", AsyncMock()),
        patch.object(runner, "_export_audit_log_only", AsyncMock()),
        patch.object(runner, "_run_github_push_phase", AsyncMock()),
    ):
        await runner.run()

    # State file must record initial as complete (so resume skips it).
    state_file = workspace / ".pipeline_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "initial" in state.get("completed_stages", [])
    # Review must NOT be marked complete (it failed).
    assert "review" not in state.get("completed_stages", [])
