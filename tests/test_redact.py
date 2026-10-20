"""`e2er redact`: personal data out of a study folder before publishing, recorded and checkable.

2026-10-20: the school-fee demo's plan files named the researcher's e-mail
address ("Author context: …"); one of them is the frozen pre-registration.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.cli_publish import _amendments_for_dossier
from src.cli_redact import redact as redact_cli
from src.cli_verify import FAIL, PASS, _run_checks
from src.core import redact as rd
from tests.test_cli_verify import _clean_bundle

EMAIL = "ada@uni.example.org"
PLAN = f"# Plan\n\nAuthor context: {EMAIL} (project owner).\n\nWe expect the effect to be positive.\nContact {EMAIL}.\n"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _checks(b: Path) -> dict[str, tuple[str, str]]:
    return {c.name: (c.status, c.detail) for c in _run_checks(b, online=False)}


@pytest.fixture
def study(tmp_path: Path) -> Path:
    """An exported study with a frozen pre-registration and a plan, both naming the researcher's e-mail."""
    from src.core.export.provenance import write_provenance

    b = _clean_bundle(tmp_path)
    (b / "design").mkdir(exist_ok=True)
    (b / "design" / "preregistration.md").write_text(PLAN, encoding="utf-8")
    (b / "design" / "paper_plan.md").write_text(f"Plan by {EMAIL}\n", encoding="utf-8")
    lock = {"file": "preregistration.md", "sha256": _sha(b / "design" / "preregistration.md"), "frozen_at": "x"}
    (b / "design" / "preregistration.lock.json").write_text(json.dumps(lock))
    write_provenance(b, {"paper_id": "p1", "governance": "full"}, exported_at="20261001")
    status, detail = _checks(b)["preregistration"]
    assert status == PASS, detail
    return b


def _prov(b: Path) -> dict:
    return json.loads((b / "provenance.json").read_text())


def test_redact_replaces_the_text_records_an_amendment_per_file_and_verify_accepts_it(study: Path, capsys):
    before = {rel: _sha(study / rel) for rel in ("design/preregistration.md", "design/paper_plan.md")}
    assert redact_cli(str(study), [EMAIL], replacement="<redacted>") == 0
    out = capsys.readouterr().out
    assert "design/preregistration.md: replaced 2 occurrence(s)" in out
    text = (study / "design" / "preregistration.md").read_text()
    assert EMAIL not in text and text == PLAN.replace(EMAIL, "<redacted>"), "only the text changed"
    amendments = [a for a in _prov(study)["amendments"] if a["kind"] == "redacted"]
    assert {a["path"] for a in amendments} == set(before)
    a = next(a for a in amendments if a["path"] == "design/preregistration.md")
    assert a["sha256_before"] == before[a["path"]] and a["sha256_after"] == _sha(study / a["path"])
    assert a["reason"] == "personal contact details removed by the researcher"
    assert a["redaction"]["count"] == 2 and a["redaction"]["removed_bytes"] == len(EMAIL)
    assert EMAIL not in json.dumps(_prov(study)), "the record never holds the text"
    assert _prov(study)["files"]["design/preregistration.md"]["sha256"] == a["sha256_after"]
    checks = _checks(study)
    assert (
        checks["integrity"][0] == PASS
        and "redacted by the researcher, personal contact details only" in (checks["integrity"][1])
    )
    status, detail = checks["preregistration"]
    assert status == PASS, detail
    assert "preregistration.md redacted by the researcher after registration: contact details only" in detail
    # The dossier lists the redactions (they do not depend on the dossier, unlike the stamp).
    assert {x["path"] for x in _amendments_for_dossier(study) if x.get("kind") == "redacted"} == set(before)


def test_check_rebuilds_the_earlier_file_with_the_text(study: Path):
    rd.redact(study, EMAIL)
    lines = rd.check(study, EMAIL)
    assert len(lines) == 2 and all(line.startswith("✓") for line in lines), lines
    wrong = rd.check(study, "bob@uni.example.org")
    assert all(line.startswith("✗") for line in wrong)


def test_a_further_edit_dressed_up_as_a_redaction_is_caught_by_check(study: Path):
    """verify cannot see the removed text; --check, with the text, rebuilds the file and finds the extra edit."""
    rd.redact(study, EMAIL)
    p = study / "design" / "preregistration.md"
    forged = p.read_bytes().replace(b"positive", b"negative")
    p.write_bytes(forged)

    def edit(prov):
        a = next(a for a in prov["amendments"] if a["path"] == "design/preregistration.md")
        a["sha256_after"] = hashlib.sha256(forged).hexdigest()
        prov["files"]["design/preregistration.md"]["sha256"] = a["sha256_after"]
        prov["files"]["design/preregistration.md"]["bytes"] = len(forged)

    prov = _prov(study)
    edit(prov)
    (study / "provenance.json").write_text(json.dumps(prov, indent=2))
    assert any(line.startswith("✗ design/preregistration.md") for line in rd.check(study, EMAIL))


def test_an_ordinary_edit_of_the_preregistration_still_fails(study: Path):
    rd.redact(study, EMAIL)
    from src.core.export.provenance import amend

    p = study / "design" / "preregistration.md"
    p.write_text(p.read_text().replace("positive", "negative"))
    amend(study, "design/preregistration.md", "changed", at="x")
    status, detail = _checks(study)["preregistration"]
    assert status == FAIL and "preregistration.md was changed after it was frozen" in detail


def test_a_redaction_record_that_does_not_match_the_file_fails_integrity(study: Path):
    rd.redact(study, EMAIL)
    prov = _prov(study)
    a = next(a for a in prov["amendments"] if a["path"] == "design/paper_plan.md")
    a["redaction"]["offsets"] = [0]
    (study / "provenance.json").write_text(json.dumps(prov, indent=2))
    status, detail = _checks(study)["integrity"]
    assert status == FAIL and "design/paper_plan.md: the redaction record does not match the file" in detail


def test_text_in_a_binary_file_or_a_pdf_stops_the_redaction_and_changes_nothing(study: Path, capsys):
    from tests.test_publish_data_terms import _add

    _add(study, "data/data.db", b"SQLite format 3\x00 rows " + EMAIL.encode() + b"\x00")
    before = (study / "provenance.json").read_bytes()
    assert redact_cli(str(study), [EMAIL], replacement="<redacted>") == 1
    out = capsys.readouterr().out
    assert "data/data.db holds it in binary form" in out and "nothing was changed" in out
    assert (study / "provenance.json").read_bytes() == before
    assert EMAIL in (study / "design" / "preregistration.md").read_text()
    (study / "data" / "data.db").unlink()
    _add(study, "paper/paper.pdf", b"%PDF-1.4 " + EMAIL.encode())
    with pytest.raises(rd.RedactError, match="paper/paper.pdf: the PDF's text holds it"):
        rd.redact(study, EMAIL)


def test_a_folder_changed_after_export_is_refused(study: Path):
    p = study / "design" / "paper_plan.md"
    p.write_text(p.read_text() + "edited\n")
    with pytest.raises(rd.RedactError, match="do(es)? not match provenance.json"):
        rd.redact(study, EMAIL)


def test_dry_run_changes_nothing_and_a_replacement_holding_the_text_is_refused(study: Path, capsys):
    before = (study / "provenance.json").read_bytes()
    assert redact_cli(str(study), [EMAIL], replacement="<redacted>", dry_run=True) == 0
    assert "would replace 2 occurrence(s)" in capsys.readouterr().out
    assert (study / "provenance.json").read_bytes() == before
    with pytest.raises(rd.RedactError):
        rd.redact(study, EMAIL, replacement=f"[{EMAIL}]")


def test_replace_and_restore_are_inverse():
    data = b"a X b X c"
    new, offsets = rd.replace_with_offsets(data, b"X", b"<r>")
    assert new == b"a <r> b <r> c" and offsets == [2, 8]
    assert rd.restore(new, offsets, b"<r>", b"X") == data
