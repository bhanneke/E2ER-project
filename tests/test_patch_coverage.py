"""Targeted corrections fix every passage a finding names, or record why one stays.

In the descriptive template's live run (2026-10-11) the patch revisor fixed one
of several passages that presented calculated exoplanet radii as measured. Now
a finding carries its locations (the self-critique quotes every passage), the
revisor is told to search the whole draft, a passage it leaves gets a ``keep``
entry with its reason, and a check after the revisor sends it back with every
passage left open.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.specialists.contract_check import (
    REVISION_FINDINGS_FILE,
    check_specialist_artifacts,
)
from src.core.strategist.actions import SelfAttackFinding, SelfAttackReport
from src.core.strategist.findings import Finding, collect_self_attack_findings
from src.core.strategist.patch_merger import coverage_problems, merge_patch_file

ABSTRACT = "We find that the measured radii of the planets cluster near two Earth radii."
DATA = "The archive reports the measured radius of each planet in Earth radii."
RESULTS = "Measured radii above four Earth radii are rare in the transit sample."
DRAFT = rf"""\documentclass{{article}}
\begin{{document}}
\begin{{abstract}}
{ABSTRACT}
\end{{abstract}}
\section{{Data}}
{DATA}
\section{{Results}}
{RESULTS}
\end{{document}}
"""
FIXED = {
    ABSTRACT: "We find that the radii of the planets, calculated from transit depth and stellar radius, cluster "
    "near two Earth radii.",
    DATA: "The archive reports each planet's radius in Earth radii, calculated from the transit depth and the "
    "stellar radius.",
    RESULTS: "Calculated radii above four Earth radii are rare in the transit sample.",
}
TARGET = {ABSTRACT: "abstract", DATA: "section:data", RESULTS: "section:results"}


def _finding(**kw) -> Finding:
    base = dict(
        source="self_attack",
        source_detail="self_attack",
        target="paper:full",
        severity=8,
        problem="Calculated planet radii are presented as measured.",
        suggested_fix="Say that the radii are calculated from the transit depth and the stellar radius.",
        locations=(ABSTRACT, DATA, RESULTS),
    )
    base.update(kw)
    return Finding(**base)


def _edit(passage: str, **kw) -> dict:
    return {
        "target": "paper:full",
        "edit_type": "replace_text",
        "find": passage,
        "replace": FIXED[passage],
        "source_finding": "F1",
        **kw,
    }


def _workspace(tmp_path: Path, edits: list[dict], findings: list[Finding]) -> Path:
    import hashlib

    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8", newline="\n")
    (tmp_path / "paper_draft.tex.edits.json").write_text(json.dumps(edits), encoding="utf-8", newline="\n")
    record = {
        "findings": [
            {
                "id": f"F{i}",
                "source": f.source,
                "source_detail": f.source_detail,
                "target": f.target,
                "severity": f.severity,
                "problem": f.problem,
                "suggested_fix": f.suggested_fix,
                "locations": list(f.locations),
            }
            for i, f in enumerate(findings, 1)
        ],
        "draft_sha256": hashlib.sha256(DRAFT.encode()).hexdigest(),
    }
    (tmp_path / REVISION_FINDINGS_FILE).write_text(json.dumps(record), encoding="utf-8", newline="\n")
    return tmp_path


def _open(ws: Path, findings: list[Finding]) -> list[str]:
    return coverage_problems(findings, merge_patch_file(ws, findings, persist=False))


def test_fixing_one_of_three_passages_leaves_two_open(tmp_path: Path):
    f = _finding()
    ws = _workspace(tmp_path, [_edit(RESULTS)], [f])
    problems = _open(ws, [f])
    assert len(problems) == 2
    assert "F1" in problems[0] and "We find that the measured radii" in problems[0]
    assert "The archive reports the measured radius" in problems[1]
    assert all('"edit_type": "keep"' in p for p in problems)


def test_the_contract_check_sends_the_revisor_back_with_each_passage(tmp_path: Path):
    f = _finding()
    ws = _workspace(tmp_path, [_edit(RESULTS)], [f])
    (failed,) = [c for c in check_specialist_artifacts(ws, "patch_revisor") if not c.ok]
    assert failed.artifact == "paper_draft.tex.edits.json"
    assert failed.reason.startswith("2 passage(s) left open:")
    assert (ws / "paper_draft.tex").read_text(encoding="utf-8") == DRAFT  # the check writes nothing


def test_every_passage_fixed_passes(tmp_path: Path):
    f = _finding()
    ws = _workspace(tmp_path, [_edit(p) for p in (ABSTRACT, DATA, RESULTS)], [f])
    assert _open(ws, [f]) == []
    assert all(c.ok for c in check_specialist_artifacts(ws, "patch_revisor"))


def test_a_passage_kept_with_its_reason_passes_and_one_without_a_reason_does_not(tmp_path: Path):
    f = _finding()
    keep = {"edit_type": "keep", "find": DATA, "reason": "the sentence describes the archive's column"}
    ws = _workspace(tmp_path, [_edit(ABSTRACT), _edit(RESULTS), keep], [f])
    assert _open(ws, [f]) == []
    merged = merge_patch_file(ws, [f], persist=False)
    assert [k.find for k in merged.kept] == [DATA] and merged.n_applied == 2 and not merged.failed
    ws = _workspace(tmp_path, [_edit(ABSTRACT), _edit(RESULTS), {**keep, "reason": ""}], [f])
    (problem,) = _open(ws, [f])
    assert "has no reason" in problem


def test_a_corrected_passage_that_occurs_again_unchanged_is_left_open(tmp_path: Path):
    f = _finding(locations=(), target="section:results")
    draft = DRAFT.replace(DATA, DATA + " " + RESULTS)  # the same sentence in the data section too
    ws = _workspace(tmp_path, [_edit(RESULTS, target="section:results")], [f])
    (ws / "paper_draft.tex").write_text(draft, encoding="utf-8", newline="\n")
    (problem,) = _open(ws, [f])
    assert "occurs 1 more time(s) elsewhere in the draft, unchanged" in problem


def test_a_location_the_draft_does_not_contain_and_table_cells_are_not_checked(tmp_path: Path):
    f = _finding(locations=("a sentence the critique misquoted entirely",))
    ws = _workspace(tmp_path, [], [f])
    assert _open(ws, [f]) == []
    numbers = _finding(source="verify_numbers", target="table:tab:main", locations=())
    ws = _workspace(tmp_path, [], [numbers])
    assert _open(ws, [numbers]) == []


def test_findings_about_another_draft_are_not_checked(tmp_path: Path):
    f = _finding()
    ws = _workspace(tmp_path, [_edit(RESULTS)], [f])
    (ws / "paper_draft.tex").write_text(DRAFT + "\n% changed since\n", encoding="utf-8", newline="\n")
    assert all(c.ok for c in check_specialist_artifacts(ws, "patch_revisor"))


def test_the_self_critique_carries_every_location_into_the_finding():
    report = SelfAttackReport(
        findings=[
            SelfAttackFinding(
                severity=8,
                category="numerics",
                description="Calculated radii presented as measured.",
                locations=[ABSTRACT, DATA, RESULTS],
            ),
            SelfAttackFinding(severity=8, category="framing", description="One quote as a string.", locations=DATA),
            SelfAttackFinding(severity=8, category="framing", description="No locations."),
        ],
        overall_severity=8,
    )
    a, b, c = collect_self_attack_findings(report)
    assert a.locations == (ABSTRACT, DATA, RESULTS)
    assert b.locations == (DATA,) and c.locations == ()


def test_the_self_critique_prompt_asks_for_every_passage():
    from src.core.strategist.engine import _SELF_ATTACK_SYSTEM

    assert "locations: EVERY passage of the draft that has this problem" in _SELF_ATTACK_SYSTEM


async def test_the_dispatch_records_the_findings_and_tells_the_revisor_to_fix_every_passage(
    tmp_path: Path, monkeypatch
):
    from src.core.specialists.contracts import Contribution
    from src.core.strategist.runner import PipelineRunner

    events: list = []

    async def _log_event(paper_id, kind, **kw):
        events.append((kind, kw.get("payload")))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8", newline="\n")
    seen: dict = {}

    async def _run(order, *a, **kw):
        seen["focus"] = order.focus
        # The revisor fixes one passage of three (the live run's failure), on every attempt.
        (tmp_path / "paper_draft.tex.edits.json").write_text(
            json.dumps([_edit(RESULTS)]), encoding="utf-8", newline="\n"
        )
        return Contribution(paper_id="p", specialist="patch_revisor", output="")

    monkeypatch.setattr("src.core.specialists.dispatcher.run_with_attempts", _run)
    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id, r._workspace, r._contributions = "p", tmp_path, []
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers, r._governance = [], [], "full"
    merged = await r._dispatch_patch_revisor([_finding()])
    assert "for EVERY passage with the issue" in seen["focus"] and '"locations"' in seen["focus"]
    assert '"id": "F1"' in seen["focus"]
    record = json.loads((tmp_path / REVISION_FINDINGS_FILE).read_text(encoding="utf-8"))
    assert record["findings"][0]["locations"] == [ABSTRACT, DATA, RESULTS]
    assert merged.n_applied == 1 and len(merged.uncovered) == 2
    ((kind, payload),) = events
    assert kind == "revision_coverage" and len(payload["open"]) == 2
