"""provenance.json validates against docs/schemas/provenance.schema.json after every change e2er makes.

Review of 2026-10-23: the schema's top level allows no other key and listed no ``amendments``, which
`e2er redact`, `e2er abstract`, the anonymised copy and publish's stamp all add; ``run.purpose``,
``run.preregistration``, ``run.template``, ``run.derived_data`` and the data edge's ``sources`` were
undocumented too. Only a fresh export was validated.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.test_cli_abstract import GOOD, SHOWCASE, _fake_pdf

jsonschema = pytest.importorskip("jsonschema")
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "docs" / "schemas" / "provenance.schema.json").read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)


def _validate(folder: Path) -> dict:
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    jsonschema.validate(prov, SCHEMA)
    return prov


def test_a_redacted_stamped_and_abstracted_folder_validates(tmp_path: Path):
    from src.cli_abstract import rewrite
    from src.cli_publish import _amend
    from src.core import redact as rd

    b = tmp_path / "study" / "exports" / "showcase"
    shutil.copytree(SHOWCASE, b)
    _validate(b)
    mine = tmp_path / "mine.tex"
    mine.write_text(GOOD, encoding="utf-8", newline="\n")
    rewrite(b, from_file=mine, reason="corrected", compile_pdf=_fake_pdf, say=lambda _s: None)
    readme = b / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nContact: ada@uni.example.org\n", encoding="utf-8", newline="\n"
    )
    _amend(b, "README.md", "a contact line")
    rd.redact(b, "ada@uni.example.org")
    (b / "code" / "note.txt").write_text("Phone +49 69 1234\n", encoding="utf-8", newline="\n")
    _amend(b, "code/note.txt", "a note")  # a file publish added: sha256_before null
    (b / "design").mkdir(exist_ok=True)
    plan = b / "design" / "contact.md"
    plan.write_text("Ann at ann@example.org\n", encoding="utf-8", newline="\n")
    _amend(b, "design/contact.md", "added")
    pdf = b / "paper" / "paper.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"%stamp")
    _amend(b, "paper/paper.pdf", "stamped", kind="stamp")
    prov = _validate(b)
    kinds = [a.get("kind") for a in prov["amendments"]]
    assert {"abstract_edited_by_researcher", "redacted", "stamp"} <= set(kinds)


def test_the_run_fields_and_the_data_edge_validate(tmp_path: Path):
    from src.core.export.provenance import build_provenance

    b = tmp_path / "b"
    (b / "data").mkdir(parents=True)
    (b / "data" / "data.db").write_bytes(b"x")
    (b / "data" / "data_sources.json").write_text('{"loads": []}', encoding="utf-8", newline="\n")
    (b / "design").mkdir()
    (b / "design" / "preregistration.md").write_text("plan\n", encoding="utf-8", newline="\n")
    (b / "design" / "preregistration.lock.json").write_text(
        json.dumps({"file": "preregistration.md", "sha256": "0" * 64, "frozen_at": "2026-10-01T00:00:00Z"}),
        encoding="utf-8",
        newline="\n",
    )
    prov = build_provenance(
        b,
        {"paper_id": "p", "purpose": "demonstration", "pipeline": "empirical"},
        exported_at="20261023",
        derived_data=[
            {"path": "data/x.csv", "named": "data/x.csv", "connectors": ["gmd"], "writers": [], "holds_rows": True}
        ],
    )
    assert prov["run"]["purpose"] == "demonstration" and prov["run"]["preregistration"]
    assert any(e.get("sources") for e in prov["edges"])
    jsonschema.validate(prov, SCHEMA)
