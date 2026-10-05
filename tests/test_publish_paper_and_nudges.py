"""e2er publish: the paper public with its PDF address, and what readers on e2er.org see for the rest."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.cli_publish import publish, request_body
from src.core.availability import paper_access, reader_notes
from src.core.dossier import dossier_id
from tests.run_db import make_run_db, paper_id_of

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "tests" / "fixtures" / "showcase_export"
BASE = dict(owner="bhanneke", project="demo", github="bhanneke", orcid="0009-0000-7466-9581", name=None)
REPO = dict(repo="https://github.com/bhanneke/E2ER-project", commit="abc1234", path="examples/showcase")
PDF = "https://example.org/demo/paper.pdf"


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst, ignore=shutil.ignore_patterns(".e2er", "e2er.json"))
    make_run_db(tmp_path, paper_id_of(dst))
    return dst


def _manifest(bundle: Path) -> dict:
    return json.loads((bundle / "e2er.json").read_text())


def test_the_paper_is_private_unless_stated_and_the_manifest_then_has_no_access(bundle: Path, tmp_path: Path, capsys):
    assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e")) == 0
    assert "access" not in _manifest(bundle)
    out = capsys.readouterr().out
    assert "note: The paper is not public: readers on e2er.org see a button to ask you for it" in out
    assert "--paper public --paper-url <address of the PDF> publishes it." in out
    assert "note: The data are private: readers on e2er.org see a button to ask you for them" in out
    assert "note: The code is private: readers on e2er.org see a button to ask you for it" in out


def test_a_public_paper_gives_its_address_in_e2er_json_and_the_request_but_not_in_the_dossier(
    bundle: Path, tmp_path: Path, capsys
):
    assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e")) == 0
    private = _manifest(bundle)
    capsys.readouterr()
    assert publish(str(bundle), **BASE, **REPO, paper="public", paper_url=PDF, out=str(tmp_path / "e")) == 0
    m = _manifest(bundle)
    assert m["access"] == {"status": "public", "pdf": PDF}
    assert request_body(m, bundle)["manifest"]["access"] == {"status": "public", "pdf": PDF}
    # The address is not part of the content: the dossier and every fingerprint stay as they were.
    assert PDF not in json.dumps(m["dossier"]["doc"])
    assert m["dossier"]["id"] == private["dossier"]["id"] == dossier_id(m["dossier"]["doc"])
    assert m["content_id"] == private["content_id"]
    out = capsys.readouterr().out
    assert f"paper: public ({PDF})" in out and "The paper is not public" not in out


def test_a_public_paper_without_an_address_takes_the_pdf_in_the_repository_at_the_commit():
    access, notes = paper_access(
        "public", None, {"url": "https://github.com/a/b.git", "commit": "abc1234", "path": "s/"}
    )
    assert access == {"status": "public", "pdf": "https://github.com/a/b/raw/abc1234/s/paper/paper.pdf"} and not notes


@pytest.mark.parametrize(
    ("paper", "url", "repo", "error"),
    [
        ("public", None, None, "--paper public needs the address of the PDF"),
        ("public", None, {"url": "https://github.com/a/b"}, "--paper public needs the address of the PDF"),
        ("public", "http://example.org/p.pdf", None, "must be an https address"),
        ("public", "https://example.org/a b.pdf", None, "must be an https address"),
        ("shared", None, None, "--paper must be public or private"),
    ],
)
def test_a_public_paper_needs_an_https_address(paper, url, repo, error):
    with pytest.raises(ValueError, match=error):
        paper_access(paper, url, repo)


def test_an_address_for_a_private_paper_is_ignored_with_a_note():
    access, notes = paper_access(None, PDF, None)
    assert access is None and notes == ["--paper-url ignored: the paper is private, so no address is published"]


def test_publish_refuses_a_public_paper_without_an_address_and_writes_nothing(bundle: Path, tmp_path: Path, capsys):
    assert publish(str(bundle), **BASE, paper="public", out=str(tmp_path / "e")) == 1
    assert "--paper public needs the address of the PDF" in capsys.readouterr().out
    assert not (bundle / "e2er.json").exists()


def test_reader_notes_name_one_flag_each_and_nothing_for_what_is_public():
    public = {"data": {"access": "public"}, "code": {"access": "public"}}
    assert reader_notes(public, {"status": "public", "pdf": PDF}) == []
    notes = reader_notes({"data": {"access": "private"}, "code": {"access": "public"}}, None)
    assert len(notes) == 2 and all(". " not in n and n.endswith(".") for n in notes)  # one sentence each
    assert "--data public" in notes[1]


def test_data_under_a_source_s_terms_get_no_nudge_but_the_reason(bundle: Path):
    notes = reader_notes(
        {"data": {"access": "private"}, "code": {"access": "private"}}, None, ["Global Macro Database (GMD)"]
    )
    gmd = [n for n in notes if "Global Macro Database" in n]
    assert len(gmd) == 1 and "--data public" not in gmd[0]
    assert "do not allow passing them on outside the study's replication package" in gmd[0]
    assert "a link to the source instead of a request button" in gmd[0]
