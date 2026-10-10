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


def test_reference_summary_surfaces_cite_keys_and_cite_only_rule(tmp_path: Path):
    """The block is read from the study's literature.bib: a key it shows is a key in the file."""
    from src.core.specialists.base import _load_reference_summary

    papers = [
        PaperMetadata(title="Multihoming and Platform Competition", authors=["Ada Liu"], year=2023, source="byod_pdf"),
        PaperMetadata(title="Found Online", authors=["Bo Web"], year=2021, source="openalex"),
    ]
    _write_literature_bib(tmp_path, papers)
    with patch("src.home.find_workspace", return_value=tmp_path):
        out = _load_reference_summary("paper_drafter", "pid")
    assert "Cite ONLY keys that are in literature.bib" in out
    assert "\\cite{liu2023multihoming}" in out
    assert "Do NOT invent citations" in out
    assert "Found Online" not in out, "the block lists the researcher's own papers; web hits are in the citable list"


def test_every_offered_reference_is_in_the_bib_with_the_key_the_prompt_shows(tmp_path: Path):
    """The 0.15.0 bib fix: .bib entries (their own keys), a Zotero web library and folder PDFs
    are all written into literature.bib, and the prompt shows exactly those keys."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.core.pipeline.verify_citations import load_bib
    from src.core.specialists.base import _load_reference_summary, _workspace_bib_for_prompt
    from src.core.study_inputs import prepare_papers

    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Bernanke:2005, title={What Explains the Stock Market's Reaction},"
        " author={Bernanke, Ben}, year={2005}}\n"
    )
    zotero = [PaperMetadata(title="From Zotero Online", authors=["Zed Otero"], year=2019, source="zotero")]
    settings = SimpleNamespace(
        literature_bibtex_file=str(bib),
        local_data_dir=None,
        literature_dir=None,
        local_data_dir_recursive=False,
        literature_max_ingest=500,
        literature_acquire_limit=0,
        zotero_api_key="k",
        zotero_user_id="1",
        zotero_group_id=None,
        resolved_literature_dirs=lambda: None,
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    with (
        patch("src.modules.literature.providers.ZoteroLibrary.entries", return_value=zotero),
        patch("src.modules.literature.storage.store_paper", new=AsyncMock()),
    ):
        asyncio.run(prepare_papers(ws, "pid", settings, ["q"]))
    keys = set(load_bib(ws / "literature.bib"))
    assert keys == {"Bernanke:2005", "otero2019from"}
    with patch("src.home.find_workspace", return_value=ws):
        shown = _load_reference_summary("paper_drafter", "pid") + _workspace_bib_for_prompt("paper_drafter", "pid")
    for key in keys:
        assert f"\\cite{{{key}}}" in shown


def test_bibtex_key_is_alphanumeric():
    # no-year item used to yield "…n.d.…" (dots invalid in bibtex keys)
    p = PaperMetadata(title="Fundamental Theory", authors=["Ranjan Pal"], year=None)
    key = p.bibtex_key
    assert key.isalnum() and "." not in key
    # clean keys are unchanged (natural lastname+year+word)
    q = PaperMetadata(title="Multihoming and X", authors=["Ada Liu"], year=2023)
    assert q.bibtex_key == "liu2023multihoming"
    # punctuated surname sanitized
    r = PaperMetadata(title="A Study", authors=["Anne O'Neil"], year=2020)
    assert r.bibtex_key.isalnum()


def test_reference_summary_empty_for_non_bib_specialist():
    from src.core.specialists.base import _load_reference_summary

    assert _load_reference_summary("econometrics_specialist") == ""
