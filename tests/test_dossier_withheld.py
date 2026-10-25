"""The dossier withholds the step fingerprints of files redacted (or anonymised) after the step.

The run database records the SHA-256 of every file a step wrote. For a file the researcher later redacted
(`e2er redact`), that fingerprint confirms a guess of the text taken out: put the guess where the replacement
sits and hash. Björn approved on 2026-10-25 that such fingerprints are withheld from the next publication on:
``{"sha256": null, "withheld": "redacted after the step"}``; every other file keeps its fingerprint.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

from src.cli_publish import publish, request_body
from src.cli_verify import FAIL, _run_checks
from src.core import redact as rd
from src.core.dossier import dossier_id, withhold_earlier_fingerprints
from tests.run_db import paper_id_of
from tests.test_publish_access import BASE, REPO
from tests.test_publish_data_terms import _add, plain_bundle  # noqa: F401 — fixture

EMAIL = "ada@uni.example.org"
PLAN = f"# Plan\n\nAuthor context: {EMAIL} (project owner).\n\nWe expect the effect to be positive.\n".encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_outputs(db: Path, paper_id: str, outputs: dict[str, list[dict]]) -> None:
    """The specialist_end events carry the files each step wrote, as the runner records them since 0.12.1."""
    ws = f"/Users/someone/e2er-studies/s/workspaces/{paper_id}/"
    con = sqlite3.connect(db)
    for sp, outs in outputs.items():
        payload = {"success": True, "outputs": [{**o, "file": ws + o["file"], "changed": True} for o in outs]}
        con.execute(
            "UPDATE pipeline_events SET payload = ? WHERE paper_id = ? AND event_type = 'specialist_end' "
            "AND specialist = ?",
            (json.dumps(payload), paper_id, sp),
        )
    con.commit()
    con.close()


def test_a_redacted_files_earlier_fingerprint_is_in_nothing_publish_writes_or_sends(
    plain_bundle: Path,  # noqa: F811
    tmp_path: Path,
    capsys,
):
    b = plain_bundle
    _add(b, "design/paper_plan.md", PLAN)
    old = _sha(PLAN)
    kept = _sha((b / "design" / "literature_review.md").read_bytes())
    _record_outputs(
        tmp_path / "e2er.db",
        paper_id_of(b),
        {
            "idea_developer": [{"file": "paper_plan.md", "sha256": old}],
            "paper_drafter": [{"file": "literature_review.md", "sha256": kept}],
        },
    )
    rd.redact(b, EMAIL)
    new = _sha((b / "design" / "paper_plan.md").read_bytes())
    assert new != old

    assert publish(str(b), **BASE, **REPO, out=str(tmp_path / "entry"), yes=True) == 0, capsys.readouterr().out
    manifest = json.loads((b / "e2er.json").read_text(encoding="utf-8"))
    doc = manifest["dossier"]["doc"]
    entry = next((tmp_path / "entry").rglob("*.json")).read_text(encoding="utf-8")
    body = json.dumps(request_body(manifest, b))
    for name, text in [("e2er.json", (b / "e2er.json").read_text()), ("registry entry", entry), ("request", body)]:
        assert old not in text, f"{name} carries the fingerprint of the file before its redaction"
        assert kept in text, f"{name} lost the fingerprint of a file nobody redacted"
    steps = {s["specialist"]: s for s in doc["workflow"] if s.get("type") == "specialist"}
    assert steps["idea_developer"]["output"] == {
        "file": "design/paper_plan.md",
        "sha256": None,
        "withheld": "redacted after the step",
    }
    assert steps["paper_drafter"]["output"] == {"file": "design/literature_review.md", "sha256": kept}
    # The redaction's own record is in the dossier, keyed: it confirms nothing.
    [a] = [a for a in doc["amendments"] if a["kind"] == "redacted"]
    assert a["sha256_before"].startswith("hmac-sha256:") and a["sha256_after"] == new
    assert manifest["dossier"]["id"] == dossier_id(doc)
    checks = {c.name: c for c in _run_checks(b, online=False)}
    assert not [c for c in checks.values() if c.status == FAIL], {n: c.detail for n, c in checks.items()}
    assert checks["anchor"].status != FAIL and checks["integrity"].status != FAIL


def _doc(outputs: list[dict], **extra) -> dict:
    return {"workflow": [{"type": "specialist", "specialist": "x", "output": o} for o in outputs], **extra}


def test_every_earlier_version_of_the_file_goes_and_the_published_one_stays():
    first, second, now = "1" * 64, "2" * 64, "3" * 64
    amendments = [{"path": "design/plan.md", "kind": "redacted", "sha256_before": "hmac-sha256:" + "f" * 64}]
    doc = _doc(
        [
            {"file": "design/plan.md", "sha256": first},
            {"file": "design/plan.md", "sha256": second},
            {"file": "design/plan.md", "sha256": now},  # the file as published: nothing to guess
            {"file": "design/other.md", "sha256": "4" * 64},
            {"file": "plan.md", "sha256": "5" * 64, "exported": False},  # not in the folder: not redacted
        ],
        run={"events": [{"event": "x", "items": [{"file": "copy.md", "sha256": first}]}]},
    )
    withhold_earlier_fingerprints(doc, amendments, {"design/plan.md": {"sha256": now}})
    outs = [s["output"] for s in doc["workflow"]]
    assert [o.get("sha256") for o in outs] == [None, None, now, "4" * 64, "5" * 64]
    assert outs[0]["withheld"] == outs[1]["withheld"] == "redacted after the step"
    assert "withheld" not in outs[2] and "withheld" not in outs[3]
    # The same fingerprint elsewhere (an event naming the file under another name) goes too.
    item = doc["run"]["events"][0]["items"][0]
    assert item == {"file": "copy.md", "sha256": None, "withheld": "redacted after the step"}


def test_an_older_runs_hash_at_export_and_a_supplied_file_are_withheld():
    before = "1" * 64
    doc = {
        "workflow": [
            {"type": "specialist", "specialist": "x", "output": {"file": "paper/paper.tex", "recorded": False,
                                                                 "exported": True, "sha256_at_export": before}},
            {"type": "researcher", "action": "supplied_input", "file": "paper/paper.tex", "sha256": before,
             "replaces_sha256": "6" * 64},
        ]
    }  # fmt: skip
    amendments = [{"path": "paper/paper.tex", "kind": "anonymised", "sha256_before": None}]
    withhold_earlier_fingerprints(doc, amendments, {"paper/paper.tex": {"sha256": "2" * 64}})
    out, supplied = doc["workflow"][0]["output"], doc["workflow"][1]
    assert "sha256_at_export" not in out and out["withheld"] == "anonymised after the step"
    assert supplied["sha256"] is None and supplied["replaces_sha256"] is None
    assert supplied["withheld"] == "anonymised after the step"
    assert before not in json.dumps(doc) and "6" * 64 not in json.dumps(doc)


def test_fingerprints_public_by_design_stay_and_a_study_without_such_amendments_is_unchanged():
    frozen = "1" * 64
    prereg = {"file": "design/preregistration.md", "sha256": frozen, "frozen_at": "2026-10-01T00:00:00Z"}
    doc = _doc([{"file": "design/preregistration.md", "sha256": frozen}], preregistration=prereg)
    amendments = [{"path": "design/preregistration.md", "kind": "redacted", "sha256_before": frozen}]
    withhold_earlier_fingerprints(doc, amendments, {"design/preregistration.md": {"sha256": "2" * 64}})
    # The frozen fingerprint is in the lock file anyway: anyone checks the deposited plan with it.
    assert doc["workflow"][0]["output"]["sha256"] == frozen and "withheld" not in doc["workflow"][0]["output"]

    plain = _doc([{"file": "paper/paper.tex", "sha256": "7" * 64}])
    before = copy.deepcopy(plain)
    others = [{"path": "paper/paper.tex", "kind": "stamp"}, {"path": "paper/refs.bib", "sha256_before": "8" * 64}]
    withhold_earlier_fingerprints(plain, others, {"paper/paper.tex": {"sha256": "9" * 64}})
    assert plain == before and dossier_id(plain) == dossier_id(before)
