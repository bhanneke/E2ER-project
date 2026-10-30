"""`e2er redact` changes a folder all or nothing, and `--check` with several texts.

Review of 2026-10-23: the files were written in place one after the other (a full disk left half a
redaction); with two `--text`, a refused second text kept the first one's changes; and `--check` with two
texts checked every amendment against both, so each one failed for the other text.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.cli_redact import redact as redact_cli
from src.core import redact as rd
from tests.test_redact import EMAIL, _sha, study  # noqa: F401 - the fixture

PHONE = "+49 69 1234 5678"


def _snapshot(b: Path) -> dict[str, bytes]:
    return {p.relative_to(b).as_posix(): p.read_bytes() for p in sorted(b.rglob("*")) if p.is_file()}


def test_a_failed_write_puts_every_file_back(study: Path, monkeypatch):  # noqa: F811
    before = _snapshot(study)
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # the second file: the first is already replaced
            raise OSError(28, "No space left on device")
        return real(src, dst)

    monkeypatch.setattr(rd.os, "replace", flaky)
    with pytest.raises(OSError):
        rd.redact(study, EMAIL)
    monkeypatch.setattr(rd.os, "replace", real)
    assert _snapshot(study) == before, "no file half-redacted, no temporary file left"


def test_a_full_disk_while_writing_the_temporary_files_changes_nothing(study: Path, monkeypatch, capsys):  # noqa: F811
    before = _snapshot(study)
    real_open = open

    def full(file, mode="r", *a, **k):
        if "w" in mode and ".e2er-redact-" in str(file):
            raise OSError(28, "No space left on device")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr("builtins.open", full)
    assert redact_cli(str(study), [EMAIL], replacement="<redacted>") == 1
    monkeypatch.setattr("builtins.open", real_open)
    assert "put back" in capsys.readouterr().out
    assert _snapshot(study) == before


def test_several_texts_are_all_or_nothing(study: Path, capsys):  # noqa: F811
    before = _snapshot(study)
    # The second text is refused (longer than a redaction takes out): the first must not stay redacted.
    assert redact_cli(str(study), [EMAIL, "x" * 300], replacement="<redacted>") == 1
    assert "none of the texts was redacted" in capsys.readouterr().out
    assert _snapshot(study) == before


def test_check_matches_each_amendment_to_its_own_text(study: Path, capsys):  # noqa: F811
    plan = study / "design" / "paper_plan.md"
    plan.write_text(f"Plan by {EMAIL}\nPhone {PHONE}\n", encoding="utf-8", newline="\n")
    from src.core.export.provenance import write_provenance

    write_provenance(study, {"paper_id": "p1", "governance": "full"}, exported_at="20261001")
    assert redact_cli(str(study), [EMAIL, PHONE], replacement="<redacted>") == 0
    capsys.readouterr()
    assert redact_cli(str(study), [EMAIL, PHONE], replacement="<redacted>", check=True) == 0
    out = capsys.readouterr().out
    assert "✗" not in out and out.count("✓") >= 2
    # A wrong text still fails.
    assert redact_cli(str(study), [EMAIL, "+49 69 0000 0000"], replacement="<redacted>", check=True) == 1
