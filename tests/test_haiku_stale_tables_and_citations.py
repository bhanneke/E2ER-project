"""Two more findings from the 2026-10-10 E2E-01 Haiku run.

1. Stale tables. section_writer cut table_spec.json from four tables to two;
   the renderer wrote the two, and the dropped tables (``---`` in every cell)
   stayed in tables/ and shipped in the export's paper/tables/.
2. No citations. The draft cited none of the 21 entries of literature.bib; the
   citation check, which checks the cites a draft makes, skipped itself and the
   paper went through.

The draft and literature.bib are the run's own (tests/fixtures/haiku_untraced_tables).
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.pipeline.verify_citations import study_references, verify
from src.core.renderer.tables import render_tables
from src.core.specialists.contract_check import check_draft_cites, check_specialist_artifacts
from src.core.specialists.contracts import WorkOrder
from src.core.specialists.dispatcher import ContractFailureError, execute_parallel
from src.modules.llm.base import ToolLoopResult
from src.modules.tracking.usage import TokenUsage
from tests.conftest import MockLLMBackend

FIXTURE = Path(__file__).parent / "fixtures" / "haiku_untraced_tables"
NO_CITES = "The draft cites no work; cite the papers in literature.bib where they support the text"


def _copy(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest)
    return dest


# ── 1. stale tables ────────────────────────────────────────────────────────


def _four_table_spec(ws: Path) -> dict:
    spec = json.loads((ws / "table_spec.json").read_text())
    two = spec["tables"]
    extra = [
        {**two[1], "filename": name, "label": f"tab:{name[:-4]}", "rows": [{"type": "coefficient", "var": "nope"}]}
        for name in ("decomposition.tex", "robustness.tex")
    ]
    return {"tables": [*two, *extra]}


def test_tables_the_spec_no_longer_declares_are_set_aside(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    shutil.rmtree(ws / "tables")
    two = (ws / "table_spec.json").read_text()
    (ws / "table_spec.json").write_text(json.dumps(_four_table_spec(ws)))
    first = render_tables(ws)
    assert sorted(first.rendered) == ["decomposition.tex", "descriptive_stats.tex", "main.tex", "robustness.tex"]
    assert "---" in (ws / "tables" / "decomposition.tex").read_text()
    # Not the renderer's: a field-map table and an \input stub stay where they are.
    (ws / "tables" / "field_map_summary.tex").write_text("\\begin{tabular}{l}x\\end{tabular}\n")
    (ws / "tables" / "stub.tex").write_text("% stub\n")

    (ws / "table_spec.json").write_text(two)  # section_writer's rewrite: two tables
    second = render_tables(ws)

    assert sorted(second.rendered) == ["descriptive_stats.tex", "main.tex"]
    assert sorted(p.name for p in (ws / "tables").iterdir()) == [
        "descriptive_stats.tex",
        "field_map_summary.tex",
        "main.tex",
        "stub.tex",
    ]
    assert second.set_aside == [".history/tables/decomposition.tex.1", ".history/tables/robustness.tex.1"]
    assert "---" in (ws / ".history" / "tables" / "decomposition.tex.1").read_text()
    saved = json.loads((ws / "table_render_report.json").read_text())
    assert saved["set_aside"] == second.set_aside

    # A render that changes nothing sets nothing aside; a table dropped again counts up.
    assert render_tables(ws).set_aside == []
    (ws / "table_spec.json").write_text(json.dumps(_four_table_spec(ws)))
    render_tables(ws)
    (ws / "table_spec.json").write_text(two)
    assert render_tables(ws).set_aside == [".history/tables/decomposition.tex.2", ".history/tables/robustness.tex.2"]


def test_an_unreadable_spec_sets_nothing_aside(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    render_tables(ws)
    (ws / "table_spec.json").write_text("{broken")
    render_tables(ws)
    assert (ws / "tables" / "main.tex").is_file() and (ws / "tables" / "descriptive_stats.tex").is_file()


def test_the_export_leaves_out_a_stale_table_from_an_older_workspace(tmp_path: Path):
    """The run's own workspace: decomposition.tex is on disk, the render report lists two tables."""
    from src.core.export.structured import export_paper

    ws = _copy(tmp_path / "ws")
    (ws / "manifest.json").write_text(json.dumps({"paper_id": str(uuid.uuid4()), "title": "Banks"}))
    (ws / "tables" / "stub.tex").write_text("% stub\n")
    draft = ws / "paper_draft.tex"
    draft.write_text(draft.read_text().replace("\\end{document}", "\\input{tables/stub.tex}\n\\end{document}"))
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    shipped = sorted(p.name for p in (out / "paper" / "tables").iterdir())
    # The rendered tables, and what the paper includes; not the stale placeholder.
    assert shipped == ["descriptive_stats.tex", "main.tex", "stub.tex"]


# ── 2. a draft that cites nothing ──────────────────────────────────────────


def test_the_haiku_draft_fails_the_drafters_contract(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    assert study_references(ws) == 21
    check = check_draft_cites(ws)
    assert not check.ok and check.reason == NO_CITES and check.kind == "verification"
    for writer in ("paper_drafter", "field_review_writer"):
        assert check in check_specialist_artifacts(ws, writer)
    assert check not in check_specialist_artifacts(ws, "revisor")

    draft = ws / "paper_draft.tex"
    draft.write_text(draft.read_text().replace("\\end{document}", "As in \\citet{x}.\n\\end{document}"))
    assert check_draft_cites(ws).ok


def test_a_study_with_no_references_is_not_held_to_it(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    (ws / "literature.bib").unlink()
    assert study_references(ws) == 0 and check_draft_cites(ws).ok
    (ws / "literature.bib").write_text("% nothing found\n")
    assert check_draft_cites(ws).ok
    # Papers chosen for the study count, even before they reach the bibliography.
    (ws / ".study_inputs.json").write_text(
        json.dumps({"papers": {"chosen": True, "items": [{"key": "a", "title": "A", "kind": "pdf"}]}})
    )
    assert study_references(ws) == 1
    assert check_draft_cites(ws).reason == NO_CITES


async def test_the_citation_check_says_why_it_checked_nothing(tmp_path: Path):
    ws = _copy(tmp_path / "ws")
    report = await verify(ws / "paper_draft.tex")
    assert report.skipped_reason == "the draft cites none of the 21 work(s) in the study's bibliography"
    (ws / "literature.bib").unlink()
    report = await verify(ws / "paper_draft.tex")
    assert report.skipped_reason == "no references: the draft cites no work and the study has no bibliography"


def _bundle(tmp_path: Path, bib: str | None) -> Path:
    b = tmp_path / "b"
    (b / "paper").mkdir(parents=True)
    shutil.copy(FIXTURE / "paper_draft.tex", b / "paper" / "paper.tex")
    if bib is not None:
        (b / "paper" / "refs.bib").write_text(bib)
    return b


def test_e2er_verify_fails_a_paper_that_cites_none_of_its_bibliography(tmp_path: Path):
    from src.cli_verify import _check_citations_offline

    check = _check_citations_offline(_bundle(tmp_path, (FIXTURE / "literature.bib").read_text()))
    assert check.status == "FAIL" and check.detail == "paper.tex cites none of the 21 work(s) in refs.bib"


def test_e2er_verify_says_no_references_plainly(tmp_path: Path):
    from src.cli_verify import _check_citations_offline

    check = _check_citations_offline(_bundle(tmp_path, None))
    assert check.status == "SKIP"
    assert check.detail.startswith("no references: paper.tex cites nothing and the bundle has no bibliography")


class _Drafter(MockLLMBackend):
    """paper_drafter writes the Haiku draft (no citation) in every attempt."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
        sp = self._detect_specialist(system)
        if sp != "paper_drafter":
            return await super().tool_loop(system, messages, tools, tool_handler, max_turns, **kw)
        self.specialist_calls.append(sp)
        self.prompts.append(str(messages[0]["content"]))
        text = (FIXTURE / "paper_draft.tex").read_text()
        await tool_handler.handle("write_file", {"path": "paper_draft.tex", "content": text})
        return ToolLoopResult(success=True, output="done", usage=TokenUsage(input_tokens=1, output_tokens=1))


@pytest.fixture
def events(monkeypatch):
    async def _log_event(*a, **kw):
        return None

    monkeypatch.setattr("src.db.events.log_event", _log_event)


async def test_after_the_last_attempt_the_drafter_stops_at_its_contract(tmp_path: Path, events):
    ws = tmp_path / "ws"
    ws.mkdir()
    shutil.copy(FIXTURE / "literature.bib", ws / "literature.bib")
    backend = _Drafter()
    with (
        patch("src.db.client.execute", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.save_usage", new_callable=AsyncMock),
        patch("src.modules.tracking.usage.check_budget_by_paper_id", new_callable=AsyncMock),
        pytest.raises(ContractFailureError) as exc,
    ):
        order = WorkOrder(paper_id=str(uuid.uuid4()), specialist="paper_drafter", focus="draft")
        await execute_parallel([order], backend, ws, "m", [], [], "mock")
    [failure] = exc.value.failures
    assert failure["specialist"] == "paper_drafter"
    assert [a["attempt"] for a in failure["attempts"]] == [1, 2, 3]
    assert all(any(NO_CITES in v for v in a["violations"]) for a in failure["attempts"])
    # Each later attempt gets the plain feedback.
    assert NO_CITES not in backend.prompts[0]
    assert all(NO_CITES in p for p in backend.prompts[1:])
