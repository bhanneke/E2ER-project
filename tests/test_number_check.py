"""The number check before the reviewers, and how a run that fails says why.

Live run 2026-10-04 (E2E-01, Claude Code on Sonnet): the number check found
three table cells that disagreed with the results files, patch_revisor wrote
`[]`, the run marked itself rejected, then the researcher's `--review-at
review` pause swallowed that (the reviewers never ran), the approval resumed
into a revision step with no scores, which returned `failed` silently, and the
replication step ran anyway. The run ended `failed` with `last_error` NULL.

Now, under governance `full`, the run stops for the researcher at the number
check (kind `numbers`), naming each mismatch; after the decision the review
step runs its reviewers. Under `contracts`/`off` the mismatches are recorded
and the run goes on, and says so. A step that fails stops the run with a
reason, and no later step runs.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.researcher import NUMBERS_STEP, apply_action, pending_review
from src.core.pipeline.state import PipelineState
from src.core.strategist.state import PaperStatus
from tests.conftest import MockLLMBackend

TEMPLATE = """
name = "numgate"
description = "Review, revision, replication."
methodologies = ["empirical"]

[[steps]]
kind     = "aggregate"
name     = "review"
parallel = true
run = ["mechanism_reviewer", "technical_reviewer", "literature_reviewer",
       "data_reviewer", "identification_reviewer", "writing_reviewer"]

[[steps]]
kind = "specialists"
name = "revision"
run  = ["revisor", "patch_revisor"]

[[steps]]
kind = "specialists"
name = "replication"
run  = ["replication_packager"]
"""


def _draft(value: str) -> str:
    return (
        "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
        "\\begin{table}\\caption{Main}\\label{tab:main}\n\\begin{tabular}{lcc}\n\\toprule\n"
        "Variable & Coef & SE \\\\\n\\midrule\n"
        f"log RV & {value} & 0.10 \\\\\n"
        "\\bottomrule\n\\end{tabular}\n\\end{table}\n\\end{document}\n"
    )


@pytest.fixture
def events(monkeypatch) -> list[tuple[str, str | None, dict]]:
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    async def _fetch_events(paper_id, *a, **kw):
        return []

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    monkeypatch.setattr("src.db.events.fetch_events", _fetch_events)
    return log


@pytest.fixture
def study(tmp_path: Path, monkeypatch) -> tuple[str, Path]:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "numgate.toml").write_text(TEMPLATE)
    pid = str(uuid.uuid4())
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": pid, "research_question": "Q?"}))
    (ws / "paper_draft.tex").write_text(_draft("0.80"))  # the results say 0.50
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"coef": 0.50, "se": 0.10}}))
    return pid, ws


class _Backend(MockLLMBackend):
    """Counts calls per specialist; reviewers optionally write no score."""

    def __init__(self, scoreless_reviews: bool = False) -> None:
        super().__init__()
        self.scoreless = scoreless_reviews

    async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
        from src.modules.llm.base import ToolLoopResult
        from src.modules.tracking.usage import TokenUsage

        if "You are the Patch Revisor specialist" in system:
            # As in the live run: patch_revisor finds nothing it can fix and says so with `[]`.
            self.specialist_calls.append("patch_revisor")
            await tool_handler.handle("write_file", {"path": "paper_draft.tex.edits.json", "content": "[]"})
            return ToolLoopResult(success=True, output="[]", usage=TokenUsage(input_tokens=1, output_tokens=1))
        sp = self._detect_specialist(system)
        if self.scoreless and sp.endswith("_reviewer"):
            from src.core.specialists.registry import SPECIALIST_ARTIFACTS

            self.specialist_calls.append(sp)
            text = "# Review\n\n" + "The draft reads well and the tables are complete. " * 4
            await tool_handler.handle("write_file", {"path": SPECIALIST_ARTIFACTS[sp], "content": text})
            return ToolLoopResult(success=True, output=text, usage=TokenUsage(input_tokens=1, output_tokens=1))
        return await super().tool_loop(system, messages, tools, tool_handler, max_turns, **kw)


class _Run:
    """One PipelineRunner.run() with the database stubbed; records each status write."""

    def __init__(self) -> None:
        self.statuses: list[tuple[str, str | None]] = []

    async def __call__(self, pid: str, ws: Path, backend: MockLLMBackend, governance: str = "full") -> dict[str, Any]:
        from src.core.strategist.runner import PipelineRunner

        async def _execute(sql: str, params: dict[str, Any] | None = None, *a, **kw):
            if sql.lstrip().startswith("UPDATE papers SET status") and params:
                self.statuses.append((str(params.get("s")), params.get("e")))

        with (
            patch("src.db.client.execute", side_effect=_execute),
            patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
            patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
            patch("src.modules.tracking.usage.check_budget", new_callable=AsyncMock),
            patch("src.core.pipeline.verify_citations.verify_and_save", new=_citations_pass),
            patch("src.core.strategist.runner.PipelineRunner._best_effort_finalize", new_callable=AsyncMock),
        ):
            runner = PipelineRunner(
                paper_id=pid,
                workspace=ws,
                backend=backend,
                model="m",
                mode="single_pass",
                backend_name="mock",
                pipeline="numgate",
                max_cost_usd=100.0,
                governance=governance,
            )
            return await runner.run()

    @property
    def last(self) -> tuple[str, str | None]:
        return self.statuses[-1]


async def _citations_pass(draft_path, workspace, bib_path=None):
    from src.core.pipeline.verify_citations import CitationIntegrityReport

    return CitationIntegrityReport(skipped_reason="no citations in this test")


def _state(ws: Path, pid: str) -> PipelineState:
    return PipelineState.load(ws, pid, "single_pass")


def _act(ws: Path, pid: str, action: dict[str, Any]) -> dict[str, Any]:
    state = _state(ws, pid)
    payload = apply_action(ws, state, action)
    state.save(ws)
    return payload


# ── governance full: the run stops at the number check ─────────────────────


async def test_a_failed_number_check_stops_the_run_for_the_researcher(study, events):
    pid, ws = study
    backend = _Backend()
    run = _Run()
    out = await run(pid, ws, backend)

    assert out == {"status": "paused", "reason": "number_check", "stage": NUMBERS_STEP, "reasons": out["reasons"]}
    # Each mismatch named: the cell, the value in the table, in the results, the source key.
    [reason] = out["reasons"]
    assert reason.startswith("tab:main (Main")
    assert reason.endswith(": the table says 0.80, the results say 0.5 (estimation_results.json.main.coef)")
    status, error = run.last
    assert status == "paused"
    assert error.startswith("Stopped at the number check: 1 number(s) in the paper's tables differ from the results")
    assert "the table says 0.80, the results say 0.5" in error
    assert f"e2er review {pid}" in error and "approve to continue" in error
    # The automatic correction got its attempt (its `[]` is a valid answer, so one
    # attempt, not three); the reviewers did not run.
    assert backend.specialist_calls.count("patch_revisor") == 1
    assert "patch_revisor made no edits" in error
    assert not [s for s in backend.specialist_calls if s.endswith("_reviewer")]
    # The researcher step: kind numbers, the draft and the results file on offer.
    state = _state(ws, pid)
    pending = pending_review(ws, state)
    assert pending is not None and (pending.stage, pending.kind) == (NUMBERS_STEP, "numbers")
    assert pending.files == ("paper_draft.tex", "estimation_results.json")
    assert not state.is_complete("review")
    assert [m["in_table"] for m in state.metadata["number_check"]["mismatches"]] == ["0.80"]
    assert ("gate_halted", NUMBERS_STEP) in [(k, s) for k, s, _ in events]


async def test_approving_continues_with_the_mismatches_recorded_and_the_reviewers_run(study, events):
    pid, ws = study
    backend = _Backend()
    run = _Run()
    await run(pid, ws, backend)
    patches_before = backend.specialist_calls.count("patch_revisor")

    payload = _act(ws, pid, {"action": "approve"})
    assert payload["decision"] == "numbers_accepted"
    assert payload["mismatches"][0]["in_table"] == "0.80" and payload["mismatches"][0]["in_results"] == "0.5"

    out = await run(pid, ws, backend)
    assert out["status"] == "completed", out
    assert run.last == ("completed", None)
    # The reviewers ran; the same mismatches are not paid for again.
    assert len([s for s in backend.specialist_calls if s.endswith("_reviewer")]) == 6
    assert backend.specialist_calls.count("patch_revisor") == patches_before
    assert "replication_packager" in backend.specialist_calls
    state = _state(ws, pid)
    assert state.pending_review_stage is None and state.is_complete("review")
    note = json.loads((ws / "number_check.json").read_text())
    assert note["decision"] == "accepted_by_researcher"
    assert [k for k, _s, _p in events if k.startswith("number_check_")] == ["number_check_accepted_by_researcher"]


async def test_a_new_mismatch_after_the_approval_stops_the_run_again(study, events):
    pid, ws = study
    run = _Run()
    await run(pid, ws, _Backend())
    _act(ws, pid, {"action": "approve"})
    (ws / "paper_draft.tex").write_text(_draft("0.95"))  # a different wrong value
    out = await run(pid, ws, _Backend())
    assert out.get("reason") == "number_check"
    assert "the table says 0.95" in out["reasons"][0]


async def test_an_edit_that_fixes_the_table_lets_the_run_finish_without_a_record(study, events):
    pid, ws = study
    run = _Run()
    await run(pid, ws, _Backend())
    _act(ws, pid, {"action": "edit", "file": "paper_draft.tex", "content": _draft("0.50")})
    out = await run(pid, ws, _Backend())  # `e2er resume`
    assert out["status"] == "completed", out
    assert not (ws / "number_check.json").exists()
    assert _state(ws, pid).pending_review_stage is None


async def test_a_plain_resume_checks_again_and_stops_again_without_a_second_patch(study, events):
    pid, ws = study
    backend = _Backend()
    run = _Run()
    await run(pid, ws, backend)
    n = backend.specialist_calls.count("patch_revisor")
    out = await run(pid, ws, backend)
    assert out.get("reason") == "number_check"
    assert backend.specialist_calls.count("patch_revisor") == n
    assert "already tried for these mismatches" in run.last[1]


async def test_sending_the_drafter_back_runs_it_and_then_the_check(study, events):
    pid, ws = study
    backend = _Backend()
    run = _Run()
    await run(pid, ws, backend)
    _act(ws, pid, {"action": "send_back", "step": "paper_drafter", "remark": "Use the coefficient from the results."})
    before = len(backend.specialist_calls)
    out = await run(pid, ws, backend)
    after = backend.specialist_calls[before:]
    # The drafter runs first (the mock's draft has no such table), then the
    # check passes and the reviewers run on the new draft.
    assert after[0] == "paper_drafter"
    assert len([s for s in after if s.endswith("_reviewer")]) == 6
    assert out["status"] == "completed", out
    assert "Use the coefficient from the results." in (ws / "researcher_instructions.md").read_text()


# ── governance contracts/off: record and continue, and say so ─────────────


@pytest.mark.parametrize("regime", ["contracts", "off"])
async def test_under_contracts_or_off_the_run_records_the_mismatches_and_continues(study, events, regime):
    from src.core.run_outcome import run_notes

    pid, ws = study
    backend = _Backend()
    run = _Run()
    out = await run(pid, ws, backend, governance=regime)
    assert out["status"] == "completed", out
    assert "patch_revisor" not in backend.specialist_calls  # no repair in shadow
    assert len([s for s in backend.specialist_calls if s.endswith("_reviewer")]) == 6
    note = json.loads((ws / "number_check.json").read_text())
    assert note["decision"] == "recorded_and_continued" and note["governance"] == regime
    assert note["mismatches"][0]["cell"].startswith("tab:main")
    [text] = run_notes(ws)
    assert f"governance '{regime}'" in text and "the run continued" in text
    assert any(k == "number_check_recorded_and_continued" for k, _s, _p in events)


# ── a failed step stops the run and says why ───────────────────────────────


async def test_a_review_step_without_scores_fails_with_a_reason_and_nothing_runs_after_it(study, events):
    pid, ws = study
    (ws / "paper_draft.tex").write_text(_draft("0.50"))
    backend = _Backend(scoreless_reviews=True)
    run = _Run()
    out = await run(pid, ws, backend)
    assert out["status"] == "failed"
    status, error = run.last
    assert status == "failed"
    assert error and "no reviewer produced a score" in error and "e2er resume" in error
    assert "replication_packager" not in backend.specialist_calls
    assert "revisor" not in backend.specialist_calls
    state = _state(ws, pid)
    assert not state.is_complete("review")  # resumable: resume runs the reviewers again
    assert ("failed", "review") in [(k, s) for k, s, _ in events]

    backend.scoreless = False
    out = await run(pid, ws, backend)  # `e2er resume`
    assert out["status"] == "completed", out


async def test_a_resumed_run_whose_state_says_failed_keeps_its_reason(study, events):
    pid, ws = study
    state = _state(ws, pid)
    for s in ("review", "revision", "replication"):
        state.mark_complete(s)
    state.last_status = "failed"
    state.metadata["last_error"] = "The review step failed: no reviewer produced a score."
    state.save(ws)
    run = _Run()
    out = await run(pid, ws, _Backend())
    assert out["status"] == "failed"
    assert run.last == ("failed", "The review step failed: no reviewer produced a score.")


async def test_no_failed_or_rejected_status_is_ever_written_without_a_reason(study, events):
    """Every status write of `failed`/`rejected`, on every path these tests drive, carries last_error."""
    from src.core.strategist.runner import PipelineRunner

    pid, ws = study
    runner = PipelineRunner(paper_id=pid, workspace=ws, backend=_Backend(), model="m", backend_name="mock")
    writes: list[tuple[str, str | None]] = []

    async def _execute(sql: str, params: dict[str, Any] | None = None, *a, **kw):
        if params and "s" in params:
            writes.append((params["s"], params.get("e")))

    with patch("src.db.client.execute", side_effect=_execute):
        await runner._update_status(PaperStatus.FAILED)
        await runner._update_status(PaperStatus.REJECTED, error="  ")
    assert all(e and e.strip() for _s, e in writes), writes


def test_the_runner_never_returns_or_writes_a_bare_failure():
    """Source-level guard: a phase ends the run by raising StepFailedError with a reason.

    Fails when someone adds `return PaperStatus.FAILED` / `REJECTED` (which used to
    let the next step run and left last_error empty) or an `_update_status` to
    FAILED/REJECTED without an `error`.
    """
    import src.core.strategist.runner as runner_mod

    tree = ast.parse(Path(runner_mod.__file__).read_text(encoding="utf-8"))

    def is_failure(node: ast.AST | None) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "PaperStatus"
            and node.attr in ("FAILED", "REJECTED")
        )

    bad: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and is_failure(node.value):
            bad.append(node.lineno)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_update_status":
            if node.args and is_failure(node.args[0]) and not any(k.arg == "error" for k in node.keywords):
                bad.append(node.lineno)
    assert not bad, f"bare failure status at runner.py lines {bad}"


# ── patch_revisor's empty patch, and what the researcher reads ─────────────


def test_an_empty_patch_file_is_an_answer_and_other_empty_json_is_not(tmp_path: Path):
    """writing/scoped-revision says `[]` is valid ("nothing to patch"); the contract agrees now."""
    from src.core.specialists.contract_check import check_artifact_nonempty

    (tmp_path / "paper_draft.tex.edits.json").write_text("[]")
    (tmp_path / "estimation_results.json").write_text("[]")
    assert check_artifact_nonempty(tmp_path, "paper_draft.tex.edits.json").ok
    assert not check_artifact_nonempty(tmp_path, "estimation_results.json").ok
    (tmp_path / "paper_draft.tex.edits.json").write_text("{}")
    assert not check_artifact_nonempty(tmp_path, "paper_draft.tex.edits.json").ok


def test_e2er_review_names_each_mismatch():
    from src.cli_review import format_pending

    text = format_pending(
        {
            "pending": {
                "stage": NUMBERS_STEP,
                "kind": "numbers",
                "mismatches": [
                    {
                        "cell": "tab:robust_samples (Robustness...), row 1, col 3",
                        "in_table": "15",
                        "in_results": "17",
                        "source_key": "summary_statistics.json.n_units",
                    }
                ],
                "auto_patch": "patch_revisor made no edits",
            },
            "files": [{"name": "paper_draft.tex", "exists": True}],
            "sendable": ["paper_drafter", "section_writer", "econometrics_specialist"],
        }
    )
    assert "Researcher step: number_check (the number check: tables differ from the results)" in text
    assert (
        "tab:robust_samples (Robustness...), row 1, col 3: the table says 15, the results say 17 "
        "(summary_statistics.json.n_units)" in text
    )
    assert "The automatic correction did not fix them: patch_revisor made no edits." in text
    assert "Approve to continue with these mismatches: the dossier records them as your decision." in text


def test_the_dossier_records_the_researchers_decision_on_the_halted_check(tmp_path: Path):
    from src.core.dossier import read_run
    from tests.test_dossier_run import PID, _db

    mismatch = {"cell": "tab:main, row 1, col 1", "in_table": "0.80", "in_results": "0.5", "source_key": "k"}
    decision = {"action": "approve", "step": NUMBERS_STEP, "decision": "numbers_accepted", "mismatches": [mismatch]}
    db = _db(
        tmp_path,
        [
            ("gate_halted", NUMBERS_STEP, None, {"reasons": ["tab:main: ..."]}, "2026-10-04 12:00:00"),
            ("researcher_action", NUMBERS_STEP, None, decision, "2026-10-04 12:05:00"),
        ],
    )
    run = read_run(db, PID)
    [check] = [s for s in run.workflow if s.get("type") == "check"]
    assert check["halted"] and check["approved_by_researcher"]["mismatches"] == [mismatch]
    [step] = [s for s in run.workflow if s.get("type") == "researcher"]
    assert step["decision"] == "numbers_accepted" and step["mismatches"] == [mismatch]


async def test_the_review_api_page_and_resume_at_the_number_check(study, events):
    from fastapi.testclient import TestClient

    from src.api.app import app

    pid, ws = study
    await _Run()(pid, ws, _Backend())
    row = {"id": pid, "workspace": str(ws), "mode": "single_pass", "pipeline": "numgate", "status": "paused"}
    with (
        patch("src.db.client.fetch_one", new_callable=AsyncMock, return_value=row),
        patch("src.db.events.fetch_events", new_callable=AsyncMock, return_value=[]),
    ):
        client = TestClient(app)
        got = client.get(f"/api/papers/{pid}/review").json()
        page = client.get(f"/papers/{pid}/review").text
    pending = got["pending"]
    assert pending["kind"] == "numbers" and pending["stage"] == NUMBERS_STEP
    assert pending["mismatches"][0]["in_table"] == "0.80" and pending["mismatches"][0]["in_results"] == "0.5"
    assert pending["auto_patch"] == "patch_revisor made no edits"
    assert {"paper_drafter", "section_writer", "econometrics_specialist"} <= set(got["sendable"])
    assert "Continue with these mismatches" in page and "estimation_results.json.main.coef" in page


def test_a_plain_resume_never_approves_the_number_check():
    import inspect

    from src.api import app as app_module

    src = inspect.getsource(app_module.resume_paper)
    assert 'get("kind") == "numbers"' in src and "not numbers_stop" in src


def test_verify_passes_only_the_cells_the_researcher_continued_with(tmp_path: Path):
    from src.cli_verify import _researcher_approved_cells
    from src.core.pipeline.verify_numbers import Mismatch

    approved = Mismatch("41.20", "s.json.kbe.mean", "36.69", "tab:sample (Sample prices...), row 2, col 2", "critical")
    other = Mismatch("7", "s.json.n", "9", "tab:sample (Sample prices...), row 3, col 2", "critical")
    (tmp_path / "reviews").mkdir()
    record = {"cell": approved.table_context, "in_table": "41.20", "in_results": "36.69", "source_key": "k"}
    path = tmp_path / "reviews" / "number_check.json"
    path.write_text(json.dumps({"decision": "accepted_by_researcher", "mismatches": [record]}))
    assert _researcher_approved_cells(tmp_path, [approved, other]) == ([approved], [other])
    # A regime that did not stop records the mismatches; that is no decision.
    path.write_text(json.dumps({"decision": "recorded_and_continued", "mismatches": [record]}))
    assert _researcher_approved_cells(tmp_path, [approved]) == ([], [approved])
