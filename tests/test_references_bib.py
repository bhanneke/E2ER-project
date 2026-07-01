"""References: generate literature.bib from the ingested library so \\cite{}
resolves (save_bibtex is ignored on CLI backends), and surface the real cite
keys to the drafter so it cites what exists instead of hallucinating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.modules.literature.discovery import _write_literature_bib
from src.modules.literature.models import PaperMetadata
from src.modules.literature.providers import ReferenceLibrary


def test_write_literature_bib_keys_match_cite_keys(tmp_path: Path):
    items = [
        PaperMetadata(title="Multihoming and Platform Competition", authors=["Ada Liu"], year=2023, journal="RFS"),
        PaperMetadata(title="Blockchain Institutions", authors=["H. Halaburda"], year=2023),
    ]
    _write_literature_bib(tmp_path, items)
    bib = (tmp_path / "literature.bib").read_text()
    assert bib.count("@article") == 2
    # The generated bib keys are exactly the keys a drafter naturally cites.
    for it in items:
        assert f"{{{it.bibtex_key}," in bib


def test_write_literature_bib_dedupes_and_preserves_existing(tmp_path: Path):
    (tmp_path / "literature.bib").write_text("@article{existing2020foo, title={Foo}}\n")
    items = [PaperMetadata(title="Foo Bar", authors=["Zoe Q"], year=2021)]
    _write_literature_bib(tmp_path, items)
    bib = (tmp_path / "literature.bib").read_text()
    assert "existing2020foo" in bib  # a pre-existing save_bibtex entry is kept
    assert items[0].bibtex_key in bib


def test_write_literature_bib_empty_is_noop(tmp_path: Path):
    _write_literature_bib(tmp_path, [])
    assert not (tmp_path / "literature.bib").exists()


class _FakeLib(ReferenceLibrary):
    name = "fake"

    def __init__(self, papers):
        self._papers = papers

    def entries(self):
        return self._papers


def test_reference_summary_surfaces_cite_keys_and_cite_only_rule():
    from src.core.specialists.base import _load_reference_summary

    papers = [PaperMetadata(title="Multihoming and Platform Competition", authors=["Ada Liu"], year=2023)]
    with patch("src.modules.literature.registry.reference_libraries", return_value=[_FakeLib(papers)]):
        out = _load_reference_summary("paper_drafter")
    assert "Cite ONLY from this list" in out
    assert "\\cite{liu2023multihoming}" in out
    assert "Do NOT invent citations" in out


def test_reference_summary_empty_for_non_bib_specialist():
    from src.core.specialists.base import _load_reference_summary

    assert _load_reference_summary("econometrics_specialist") == ""
