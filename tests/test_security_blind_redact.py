"""Redaction and double-blind records confirm no guess; the leak check sees the hidden forms of a name.

Regression tests from the security review of 2026-10-23 (repro_redact_oracle.py, repro_blind_oracle.py,
repro_leak_forms.py, repro_anon_symlink.py): a phone number came back from a redaction record in 0.02 s, a
reviewer confirmed the author of a blinded copy from an earlier redaction, eighteen spellings of a name were
tried against the leak check, and anonymising a copy wrote through a symbolic link into the original file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import zlib
from pathlib import Path

import pytest

from src.core import anonymise as an
from src.core import redact as rd

NAME = "Imogen Quarry"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """The redaction salt lives in ~/.e2er: a fresh home per test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _study(tmp_path: Path, rel: str, body: bytes) -> Path:
    f = tmp_path / "study"
    (f / rel).parent.mkdir(parents=True, exist_ok=True)
    (f / rel).write_bytes(body)
    listing = {rel: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}}
    (f / "provenance.json").write_text(json.dumps({"files": listing}))
    return f


def _brute(after: bytes, a: dict, guesses: list[bytes]) -> bytes | None:
    red = a["redaction"]
    for g in guesses:
        if len(g) != red.get("removed_bytes", len(g)):
            continue
        before = rd.restore(after, red["offsets"], red["replacement"].encode(), g)
        if hashlib.sha256(before).hexdigest() == a["sha256_before"]:
            return g
    return None


# ── e2er redact ──────────────────────────────────────────────────────────────


def test_a_redaction_record_confirms_no_guess(tmp_path):
    f = _study(tmp_path, "design/plan.md", b"Contact the PI at +49 69 798 34512 for questions.\n")
    rd.redact(f, "798 34512")
    a = json.loads((f / "provenance.json").read_text())["amendments"][-1]
    assert a["sha256_before"].startswith(rd.KEYED)
    after = (f / "design/plan.md").read_bytes()
    assert _brute(after, a, [f"798 {i:05d}".encode() for i in range(34000, 35000)]) is None
    # On this computer the check still rebuilds the earlier file.
    assert rd.check(f, "798 34512")[0].startswith("✓")
    assert not rd.check(f, "798 34513")[0].startswith("✓")
    salt = rd.salt_file()
    assert oct(salt.stat().st_mode & 0o777) == "0o600" and oct(salt.parent.stat().st_mode & 0o777) == "0o700"


def test_a_second_redaction_of_the_file_still_links_up(tmp_path):
    f = _study(tmp_path, "design/plan.md", b"Call 798 34512 or write to imogen@uni-x.de.\n")
    rd.redact(f, "798 34512")
    rd.redact(f, "imogen@uni-x.de")
    prov = json.loads((f / "provenance.json").read_text())
    first, second = prov["amendments"]
    assert first["sha256_after"] == second["sha256_before"] and second["sha256_before"].startswith(rd.KEYED)
    assert prov["files"]["design/plan.md"]["sha256"] == second["sha256_after"]
    from src.cli_verify import _amendment_problems

    assert _amendment_problems(prov) == []


def test_where_the_earlier_fingerprint_is_public_it_stays_plain(tmp_path):
    """A folder published before: its fingerprints are on the platform, and verify rolls the redaction back."""
    body = b"Contact 798 34512.\n"
    f = _study(tmp_path, "design/plan.md", body)
    (f / "e2er.json").write_text("{}")
    rd.redact(f, "798 34512")
    a = json.loads((f / "provenance.json").read_text())["amendments"][-1]
    assert a["sha256_before"] == hashlib.sha256(body).hexdigest()


def test_a_short_redacted_text_gets_a_warning(tmp_path, capsys):
    from src.cli_redact import redact

    f = _study(tmp_path, "design/plan.md", b"Room 4.102, phone 34512.\n")
    assert redact(str(f), ["34512"], replacement="<redacted>") == 0
    out = capsys.readouterr().out
    assert "warning: the text is short (5 characters)" in out and "keyed to this computer" in out
    assert redact(str(f), ["Room 4.102, phone"], replacement="<redacted>") == 0
    assert "warning" not in capsys.readouterr().out


def test_files_at_export_treats_a_keyed_fingerprint_as_unknown(tmp_path):
    from src.core.export.provenance import files_at_export

    f = _study(tmp_path, "design/plan.md", b"Contact 798 34512.\n")
    rd.redact(f, "798 34512")
    prov = json.loads((f / "provenance.json").read_text())
    exported = files_at_export(prov)
    assert not str(exported["design/plan.md"]["sha256"]).startswith(rd.KEYED)


# ── e2er publish --blind: the copy ───────────────────────────────────────────


def test_a_blinded_copy_keeps_nothing_that_confirms_the_author(tmp_path):
    body = b"# analysis.py written for the study by Imogen Quarry\nimport pandas\n"
    f = _study(tmp_path, "code/analysis.py", body)
    (f / "e2er.json").write_text("{}")  # published before: the redaction keeps the plain fingerprint
    rd.redact(f, NAME)
    copy = f.parent / "copy"
    shutil.copytree(f, copy)
    (copy / "e2er.json").unlink()
    ids = [an.Identifier("name", NAME, "test")]
    result = an.anonymise(copy, ids)
    prov = json.loads((copy / "provenance.json").read_text())
    a = [x for x in prov["amendments"] if x["kind"] == "redacted"][0]
    assert a["sha256_before"] is None
    assert not {"offsets", "removed_bytes", "bytes_before"} & set(a["redaction"])
    assert hashlib.sha256(body).hexdigest() in result.withheld  # taken out of the dossier too
    text = json.dumps(prov)
    assert hashlib.sha256(body).hexdigest() not in text
    # verify still accepts the record: the replacement is counted in the file.
    assert rd.record_problem(a, (copy / "code/analysis.py").read_bytes()) is None
    assert rd.record_problem(a, b"no replacement here") is not None
    from src.cli_verify import _amendment_problems

    assert _amendment_problems(prov) == []
    assert an.leak_check(copy, ids, pdf=lambda p: "", meta=lambda p: None).clean


def test_an_anonymised_file_records_no_offsets_and_still_verifies(tmp_path):
    f = _study(tmp_path, "paper/paper.md", b"By Imogen Quarry. Thanks to Imogen Quarry.\n")
    ids = [an.Identifier("name", NAME, "test")]
    an.anonymise(f, ids)
    a = json.loads((f / "provenance.json").read_text())["amendments"][-1]
    reps = a["anonymisation"]["replacements"]
    assert reps == [{"text": an.MARK, "count": 2}]
    assert an.record_problem(a, (f / "paper/paper.md").read_bytes()) is None
    assert an.record_problem(a, b"only one [anonymised]") is not None


def test_anonymising_refuses_a_symbolic_link(tmp_path):
    orig = tmp_path / "outside_original.csv"
    orig.write_text("id,owner\n1,Imogen Quarry\n")
    f = tmp_path / "study"
    (f / "data").mkdir(parents=True)
    os.symlink(orig, f / "data" / "raw.csv")
    (f / "provenance.json").write_text(json.dumps({"files": {"data/raw.csv": {"sha256": "x"}}}))
    with pytest.raises(an.AnonymiseError, match="symbolic links"):
        an.anonymise(f, [an.Identifier("name", NAME, "test")])
    assert orig.read_text() == "id,owner\n1,Imogen Quarry\n"


# ── the leak check ───────────────────────────────────────────────────────────

IDS = [
    an.Identifier("name", NAME, "t"),
    an.Identifier("email", "imogen.quarry@uni-x.de", "t"),
    an.Identifier("github", "iquarry", "t"),
]


@pytest.mark.parametrize(
    "text",
    [
        "data/imogen_quarry_survey.csv",
        "ImogenQuarry",
        "imogen-quarry",
        "imogen.quarry.notes",
        "Im​ogen Quarry",
        "Ｉｍｏｇｅｎ Ｑｕａｒｒｙ",
        "&#73;mogen Quarry",
        "Imogen%20Quarry",
    ],
)
def test_the_forms_a_name_hides_in_are_leaks(text):
    assert an.leak_check(None, IDS, texts={"t": text}).leaks, text


@pytest.mark.parametrize("text", ["Prof. Quarry's lab", "QUARRY", "Imogen Q."])
def test_the_surname_alone_and_an_initial_are_shown_for_confirmation(text):
    r = an.leak_check(None, IDS, texts={"t": text})
    assert r.confirm and not r.leaks, text


def test_a_file_name_is_searched(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "quarry_imogen_raw.csv").write_text("a,b\n1,2\n")
    (tmp_path / "data" / "imogen_quarry.csv").write_text("a,b\n1,2\n")
    r = an.leak_check(tmp_path, IDS, pdf=lambda p: "", meta=lambda p: None)
    assert any("imogen_quarry.csv (its name)" in str(x) for x in r.leaks)


def _pdf(*, stream: bytes = b"", title_hex: str = "") -> bytes:
    body = b"%PDF-1.4\n1 0 obj << /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n"
    body += stream + b"\nendstream\nendobj\n"
    if title_hex:
        body += b"2 0 obj << /Title <" + title_hex.encode() + b"> >> endobj\n"
    return body + b"%%EOF\n"


def test_a_pdfs_compressed_streams_and_hex_strings_are_searched():
    deflated = zlib.compress(b"BT (Imogen Quarry) Tj ET")
    r = an.leak_check(None, IDS, files={"paper.pdf": _pdf(stream=deflated)}, pdf=lambda p: "", meta=lambda p: None)
    assert any("compressed or hex-coded" in str(x) for x in r.leaks)
    title = ("FEFF" + NAME.encode("utf-16-be").hex()).upper()
    r = an.leak_check(None, IDS, files={"paper.pdf": _pdf(title_hex=title)}, pdf=lambda p: "", meta=lambda p: None)
    assert r.leaks


def test_a_pdfs_metadata_is_searched():
    r = an.leak_check(
        None, IDS, files={"paper.pdf": _pdf()}, pdf=lambda p: "", meta=lambda p: "Author:  Imogen Quarry\n"
    )
    assert any("(its metadata)" in str(x) for x in r.leaks)


def test_a_utf16be_text_is_searched():
    r = an.leak_check(None, IDS, files={"notes.bin": b"\x00\x01" + NAME.encode("utf-16-be")})
    assert r.leaks


def _png(chunk_type: bytes, data: bytes) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(chunk_type, data) + chunk(b"IEND", b"")


def test_a_pngs_compressed_text_chunk_is_searched():
    png = _png(b"zTXt", b"Author\x00\x00" + zlib.compress(NAME.encode()))
    r = an.leak_check(None, IDS, files={"figures/fig1.png": png})
    assert any("text metadata" in str(x) for x in r.leaks)
    itxt = _png(b"iTXt", b"Author\x00\x01\x00\x00\x00" + zlib.compress(NAME.encode()))
    assert an.leak_check(None, IDS, files={"figures/fig2.png": itxt}).leaks


def test_a_plain_text_without_the_name_stays_clean():
    r = an.leak_check(None, IDS, texts={"t": "Written by the authors of the study, with thanks to the reviewers."})
    assert r.clean and not r.confirm
