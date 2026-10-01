"""`e2er verify`: what the 2026-10-01 tamper review found it let through.

Each test starts from a bundle that verifies and makes one change the review
showed passing (or crashing): links, unsafe or ambiguous provenance entries,
files that were never checked, e2er.json and .e2er/link.json drifting from the
folder, checks that disappeared with their input, passes over nothing, a
numbers gate that let fabricated cells through, and no anchor outside the
folder. The harnesses of the review are in tmp/review-verify (harness.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest

from src.cli_verify import FAIL, PASS, SKIP, _run_checks, verify
from tests.test_cli_verify import _clean_bundle


def _checks(bundle: Path) -> dict[str, tuple[str, str]]:
    return {c.name: (c.status, c.detail) for c in _run_checks(bundle, online=False)}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _reanchor(bundle: Path) -> None:
    """What a forger does after editing: rewrite provenance.json's inventory from the disk."""
    from src.core.export.provenance import inventory

    prov = json.loads((bundle / "provenance.json").read_text())
    prov["files"] = inventory(bundle)
    (bundle / "provenance.json").write_text(json.dumps(prov, indent=2))


def _edit_prov(bundle: Path, fn) -> None:
    p = bundle / "provenance.json"
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d, indent=2))


def _published(tmp_path: Path) -> Path:
    """A clean bundle as `e2er publish --to` leaves it: e2er.json and .e2er/link.json."""
    from src.core.dossier import build_dossier, dossier_id, dossier_url
    from src.core.research_object import build_manifest, write_manifest

    b = _clean_bundle(tmp_path)
    m = build_manifest(b, owner="bhanneke", project="demo", contributors=[{"github": "bhanneke"}])
    m["availability"] = {"data": {"access": "private"}, "code": {"access": "private"}}
    doc = build_dossier(m, bundle=b)
    did = dossier_id(doc)
    m["dossier"] = {"id": did, "url": dossier_url(did), "doc": doc}
    write_manifest(b, m)
    (b / ".e2er").mkdir()
    (b / ".e2er" / "link.json").write_text(
        json.dumps(
            {
                "platform_url": "https://e2er.example",
                "owner_project": "bhanneke/demo",
                "version": 1,
                "dossier_id": did,
                "content_id": m["content_id"],
            }
        )
    )
    return b


# ── links, paths, ambiguous or malformed provenance ──────────────────────────


def test_a_link_is_never_followed_even_to_an_identical_file(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    outside = tmp_path / "README.md"
    shutil.copy2(b / "README.md", outside)
    (b / "README.md").unlink()
    os.symlink(outside, b / "README.md")
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "symbolic link" in detail


def test_a_linked_folder_cannot_hide_or_inject_files(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    moved = tmp_path / "results"
    shutil.move(str(b / "results"), moved)
    (moved / "robustness_results.json").write_text("{}")
    os.symlink(moved, b / "results")
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "results" in detail


@pytest.mark.parametrize(
    ("key", "why"),
    [
        ("/etc/hosts", "absolute"),
        ("../outside.txt", ".."),
        ("paper/../README.md", ".."),
        ("paper/./paper.tex", "normalised"),
        ("paper//paper.tex", "empty segment"),
        ("café.txt", "NFC"),
    ],
)
def test_unsafe_or_ambiguous_entries_in_provenance_fail(tmp_path: Path, key: str, why: str):
    b = _clean_bundle(tmp_path)
    _edit_prov(b, lambda d: d["files"].__setitem__(key, dict(d["files"]["README.md"])))
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and why in detail


def test_the_size_in_provenance_is_compared(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    _edit_prov(b, lambda d: d["files"]["README.md"].__setitem__("bytes", 1))
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "size" in detail


def test_forged_derivation_edges_fail(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    forged = {"type": "citation", "key": "fake2020", "status": "verified", "registry": "crossref"}
    _edit_prov(b, lambda d: d["edges"].append(forged))
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "edges" in detail


def test_a_key_given_twice_is_refused(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    p = b / "provenance.json"
    text = p.read_text().replace(
        '"files": {', '"files": {\n    "README.md": {"sha256": "' + "0" * 64 + '", "bytes": 0},', 1
    )
    p.write_text(text)
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "appears twice" in detail


@pytest.mark.parametrize(
    "write",
    [
        lambda p: p.write_text("{"),
        lambda p: p.write_text(json.dumps({"files": ["README.md"]})),
        lambda p: p.write_text(json.dumps({"files": {"README.md": "abc"}})),
        lambda p: p.write_text(json.dumps({"files": {"README.md": {"sha256": "x", "bytes": "1"}}})),
        lambda p: p.write_text("[]"),
    ],
)
def test_malformed_provenance_fails_cleanly(tmp_path: Path, write, capsys):
    b = _clean_bundle(tmp_path)
    write(b / "provenance.json")
    assert verify(str(b)) == 1
    out = capsys.readouterr().out
    assert "[FAIL] integrity" in out and "Traceback" not in out


# ── files that were never checked ────────────────────────────────────────────


@pytest.mark.parametrize(
    "rel", ["code/scratch/report.html", "results/e2er.json", "data/provenance.json", ".e2er/payload.py"]
)
def test_files_named_like_the_exempt_ones_are_checked_anywhere_but_the_root(tmp_path: Path, rel: str):
    b = _clean_bundle(tmp_path)
    (b / rel).parent.mkdir(parents=True, exist_ok=True)
    (b / rel).write_text("{}")
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "unlisted" in detail


def test_an_edited_report_html_fails(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    (b / "report.html").write_text((b / "report.html").read_text().replace("Verify Me", "Something Else"))
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "report.html" in detail


def test_a_report_html_no_fingerprint_covers_fails_and_says_what_to_do(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    _edit_prov(b, lambda d: d["files"].pop("report.html"))  # as exported before e2er fingerprinted it
    status, detail = _checks(b)["integrity"]
    assert status == FAIL and "not fingerprinted" in detail and "delete it" in detail
    (b / "report.html").unlink()
    assert _checks(b)["integrity"][0] == PASS


def test_finder_and_explorer_files_are_ignored_and_named(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    (b / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
    (b / "paper" / "._paper.tex").write_bytes(b"\0")
    (b / "results" / "Thumbs.db").write_bytes(b"x")
    status, detail = _checks(b)["integrity"]
    assert status == PASS and "ignored 3 operating-system file(s)" in detail
    assert verify(str(b)) == 0


# ── the anchor: e2er.json and .e2er/link.json ────────────────────────────────


def test_a_published_folder_verifies_and_says_it_verified_against_itself_only(tmp_path: Path, capsys):
    b = _published(tmp_path)
    assert _checks(b)["anchor"][0] == PASS
    assert verify(str(b)) == 0
    out = capsys.readouterr().out
    assert "verified against the folder only" in out
    assert "--against https://e2er.example/bhanneke/demo" in out


def test_an_unpublished_folder_says_it_verified_against_itself_only(tmp_path: Path, capsys):
    b = _clean_bundle(tmp_path)
    assert _checks(b)["anchor"][0] == SKIP
    assert verify(str(b)) == 0
    assert "verified against the folder only" in capsys.readouterr().out


def test_provenance_edited_and_reanchored_no_longer_matches_e2er_json(tmp_path: Path):
    b = _published(tmp_path)
    _edit_prov(b, lambda d: d["run"].update(model="hand-written", backend="none"))
    assert _checks(b)["integrity"][0] == PASS  # self-consistent
    status, detail = _checks(b)["anchor"]
    assert status == FAIL and "describes the content" in detail


@pytest.mark.parametrize(
    ("edit", "why"),
    [
        (lambda m: m["dossier"].__setitem__("id", "sha256:" + "e" * 64), "does not hash to its id"),
        (lambda m: m.__setitem__("title", "A DIFFERENT TITLE"), "title"),
        (lambda m: m.__setitem__("availability", {"data": "open", "code": "open"}), "availability"),
        (
            lambda m: m.__setitem__(
                "availability", {"data": {"access": "public", "url": "x"}, "code": {"access": "private"}}
            ),
            "public",
        ),
        (lambda m: m["outputs"][0].__setitem__("sha256", "0" * 64), "fingerprint"),
        (lambda m: m["dossier"]["doc"]["study"].__setitem__("title", "Other"), "does not hash"),
    ],
)
def test_e2er_json_that_does_not_describe_the_folder_fails(tmp_path: Path, edit, why, capsys):
    b = _published(tmp_path)
    m = json.loads((b / "e2er.json").read_text())
    edit(m)
    (b / "e2er.json").write_text(json.dumps(m))
    status, detail = _checks(b)["anchor"]
    assert status == FAIL and why in detail
    assert verify(str(b)) == 1
    out = capsys.readouterr().out
    assert "Traceback" not in out and out.rstrip().splitlines()[-1].startswith("   availability")


def test_e2er_json_deleted_from_a_published_folder_fails(tmp_path: Path):
    b = _published(tmp_path)
    (b / "e2er.json").unlink()
    status, detail = _checks(b)["anchor"]
    assert status == FAIL and "e2er.json is missing" in detail


def test_a_tampered_link_fails(tmp_path: Path):
    b = _published(tmp_path)
    (b / ".e2er" / "link.json").write_text('{"content_id": "sha256:00"}')
    status, detail = _checks(b)["anchor"]
    assert status == FAIL and "link.json" in detail


# ── --against: the anchor outside the folder ─────────────────────────────────


@pytest.fixture
def site(monkeypatch):
    """A fake e2er.org that answers GET only."""
    records: dict[str, object] = {}
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        seen.append(req.url.path)
        if req.url.path in records:
            return httpx.Response(200, json=records[req.url.path])
        return httpx.Response(404, json={"error": "not found"})

    from src.core import platform_client as pc

    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(handler))
    )
    return records, seen


def _study_record(content_id: str, dossier_id: str) -> dict:
    return {
        "id": "bhanneke/demo",
        "latest": {"number": 2, "content_id": content_id, "dossier_id": dossier_id},
        "versions": [
            {"number": 1, "content_id": "sha256:" + "1" * 64, "dossier_id": "sha256:" + "2" * 64},
            {"number": 2, "content_id": content_id, "dossier_id": dossier_id},
        ],
    }


def test_against_the_published_study_anchors_the_folder(tmp_path: Path, site, capsys):
    records, seen = site
    b = _published(tmp_path)
    m = json.loads((b / "e2er.json").read_text())
    records["/api/v1/studies/bhanneke/demo"] = _study_record(m["content_id"], m["dossier"]["id"])
    assert verify(str(b), against="https://e2er.example/bhanneke/demo") == 0
    out = capsys.readouterr().out
    assert "[PASS] published" in out and "version 2" in out and "the latest" in out
    assert "anchor: e2er.org" in out and "folder only" not in out
    assert seen == ["/api/v1/studies/bhanneke/demo"]


def test_against_catches_a_consistent_rewrite_of_the_whole_folder(tmp_path: Path, site):
    records, _ = site
    b = _published(tmp_path)
    m = json.loads((b / "e2er.json").read_text())
    records["/api/v1/studies/bhanneke/demo"] = _study_record(m["content_id"], m["dossier"]["id"])
    # the forger edits the paper, re-anchors provenance.json and rewrites e2er.json and the link
    tex = b / "paper" / "paper.tex"
    tex.write_text(tex.read_text().replace("See", "We find a large effect. See"))
    _reanchor(b)
    files = json.loads((b / "provenance.json").read_text())["files"]
    for o in m["outputs"]:
        o["sha256"] = files[o["path"]]["sha256"]
    m["content_id"] = "sha256:" + _sha(b / "provenance.json")
    (b / "e2er.json").write_text(json.dumps(m))
    link = json.loads((b / ".e2er" / "link.json").read_text())
    link["content_id"] = m["content_id"]
    (b / ".e2er" / "link.json").write_text(json.dumps(link))
    assert verify(str(b)) == 0  # the folder agrees with itself
    assert verify(str(b), against="https://e2er.example/bhanneke/demo") == 1


def test_against_a_dossier_address_and_a_saved_file(tmp_path: Path, site, capsys):
    records, _ = site
    b = _published(tmp_path)
    m = json.loads((b / "e2er.json").read_text())
    short = m["dossier"]["id"].removeprefix("sha256:")[:16]
    records[f"/api/v1/dossiers/{short}"] = m["dossier"]["doc"]
    assert verify(str(b), against=f"https://e2er.example/d/{short}") == 0
    assert "fixes the data files only" in capsys.readouterr().out
    saved = tmp_path / "study.json"
    saved.write_text(json.dumps(_study_record("sha256:" + "9" * 64, m["dossier"]["id"])))
    assert verify(str(b), against_file=str(saved)) == 1


def test_against_an_unreachable_site_fails_and_says_so(tmp_path: Path, site, capsys):
    b = _published(tmp_path)
    assert verify(str(b), against="https://e2er.example/bhanneke/nothing") == 1
    assert "answered 404" in capsys.readouterr().out


# ── checks that disappeared with their input ─────────────────────────────────


def test_deleting_the_preregistration_lock_fails_the_required_check(tmp_path: Path):
    from src.core.export.provenance import write_provenance

    b = _clean_bundle(tmp_path)
    (b / "design" / "preregistration.md").write_text("# Plan\n")
    (b / "design" / "preregistration.lock.json").write_text(
        json.dumps(
            {"file": "preregistration.md", "sha256": _sha(b / "design" / "preregistration.md"), "frozen_at": "x"}
        )
    )
    write_provenance(b, {"paper_id": "p1", "governance": "full"}, exported_at="20261001")
    assert json.loads((b / "provenance.json").read_text())["run"]["preregistration"]
    (b / "design" / "preregistration.lock.json").unlink()
    _reanchor(b)
    status, detail = _checks(b)["preregistration"]
    assert status == FAIL and "lock.json is missing" in detail


def test_a_replication_without_its_report_fails_instead_of_looking_like_a_paper(tmp_path: Path):
    from src.core.export.provenance import write_provenance

    b = tmp_path / "repl"
    (b / "misc").mkdir(parents=True)
    (b / "misc" / "notes.md").write_text("x")
    write_provenance(b, {"paper_id": "p1", "pipeline": "replication"}, exported_at="20261001")
    status, detail = _checks(b)["reproduction"]
    assert status == FAIL and "replication template" in detail


# ── passes over nothing ──────────────────────────────────────────────────────


def test_zero_citations_and_zero_table_cells_are_skips_not_passes(tmp_path: Path, capsys):
    from src.core.export.provenance import write_provenance

    b = tmp_path / "b"
    (b / "paper").mkdir(parents=True)
    (b / "results").mkdir()
    (b / "paper" / "paper.tex").write_text("\\begin{document}No tables, no citations.\\end{document}\n")
    (b / "results" / "estimation_results.json").write_text(json.dumps({"main": {"coefficients": {}}}))
    write_provenance(b, {"paper_id": "p1"}, exported_at="20261001")
    c = _checks(b)
    assert c["citations"][0] == SKIP and "cites nothing" in c["citations"][1]
    assert c["numbers"][0] == SKIP
    assert verify(str(b)) == 1
    assert "NOT verified" in capsys.readouterr().out


def test_the_banner_names_exactly_the_checks_that_passed(tmp_path: Path, capsys):
    b = _clean_bundle(tmp_path)
    assert verify(str(b)) == 0
    out = capsys.readouterr().out
    banner = next(line for line in out.splitlines() if line.startswith("✅"))
    assert "(numbers, spec, citations)" in banner and "1 skipped (tables)" in banner
    assert "tables, numbers, spec, and citations are internally consistent" not in out


# ── the numbers gate: every cell a source value at its precision ─────────────


@pytest.mark.parametrize("cell", ["12.6", "12.44", "999.9", "0.000"])
def test_a_table_cell_that_is_no_source_value_fails(tmp_path: Path, cell: str):
    b = _clean_bundle(tmp_path)
    tex = b / "paper" / "paper.tex"
    tex.write_text(tex.read_text().replace("Treatment & 12.5", f"Treatment & 12.5 & {cell}"))
    _reanchor(b)
    status, detail = _checks(b)["numbers"]
    assert status == FAIL and cell in detail


def test_a_rounded_cell_passes(tmp_path: Path):
    b = _clean_bundle(tmp_path)
    res = b / "results" / "estimation_results.json"
    res.write_text(json.dumps({"main": {"coefficients": {"treat": {"estimate": 12.4987}}}}))
    _reanchor(b)
    assert _checks(b)["numbers"][0] == PASS
