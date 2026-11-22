# ruff: noqa: F811 — the fixture imported from tests/test_package.py is an argument here
"""Which files an amendment may change, by its kind (review 2026-11, finding 7).

`e2er verify` checked only that abstract amendments stay in the abstract's files: any other kind (a "stamp",
a "readme", or none) could name any file, so a changed result recorded as an amendment passed integrity.
"""

from __future__ import annotations

import json

import pytest

from src.cli_verify import FAIL, PASS, _amendment_problems, _check_integrity
from src.core.export.provenance import amend
from tests.test_package import _export, offline_lock  # noqa: F401 — fixture


def _amendment(path: str, kind: str | None = None) -> dict:
    a = {"path": path, "sha256_before": "0" * 64, "sha256_after": "1" * 64}
    if kind:
        a["kind"] = kind
    return a


def _prov(*amendments: dict) -> dict:
    return {"files": {a["path"]: {"sha256": a["sha256_after"]} for a in amendments}, "amendments": list(amendments)}


@pytest.mark.parametrize(
    "path,kind",
    [
        ("results/estimation_results.json", "stamp"),
        ("results/estimation_results.json", None),
        ("data/data.db", "readme"),
        ("code/run_estimation.py", None),
        ("reproduce.json", "stamp"),
        ("results/estimation_results.json", "something_new"),
        ("README.md", "stamp"),
    ],
)
def test_a_kind_may_not_relabel_a_change_of_another_file(path: str, kind: str | None):
    [problem] = _amendment_problems(_prov(_amendment(path, kind)))
    assert path in problem and "no e2er command records such an amendment" in problem


@pytest.mark.parametrize(
    "path,kind",
    [
        ("paper/paper.tex", "stamp"),
        ("paper/paper.pdf", "stamp"),
        ("README.md", "readme"),
        ("paper/abstract.tex", "abstract_rewritten"),
        ("report.html", "abstract_edited_by_researcher"),
        ("paper/refs.bib", None),
        ("misc/reproduction_report.md", None),
        ("code/run_estimation.py", "redacted"),  # its change is checked against the file (_redaction_problems)
        ("code/run_estimation.py", "anonymised"),
    ],
)
def test_the_changes_e2er_records_are_still_accepted(path: str, kind: str | None):
    assert _amendment_problems(_prov(_amendment(path, kind))) == []


def test_a_results_edit_recorded_as_a_stamp_fails_integrity_and_every_amended_file_is_named(tmp_path, offline_lock):
    folder = _export(tmp_path)
    res = folder / "results" / "estimation_results.json"
    doc = json.loads(res.read_text(encoding="utf-8"))
    doc["main"]["mean"] += 1
    res.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    amend(folder, "results/estimation_results.json", "stamped", at="x")
    prov_path = folder / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    prov["amendments"][-1]["kind"] = "stamp"
    prov_path.write_text(json.dumps(prov, indent=2), encoding="utf-8", newline="\n")
    check = _check_integrity(folder)
    assert check.status == FAIL and "results/estimation_results.json" in check.detail


def test_the_integrity_line_names_every_amended_file(tmp_path, offline_lock):
    folder = _export(tmp_path)
    paths = ["README.md", "paper/refs.bib", "paper/paper.tex", "misc/reproduction_report.md"]
    for rel in paths:
        f = folder / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n% changed\n")
        amend(folder, rel, "changed by e2er publish", at="x")
    check = _check_integrity(folder)
    assert check.status == PASS, check.detail
    assert all(p in check.detail for p in paths), check.detail
