"""v0.8.1: LOCAL_DATA_DIR supports comma-separated roots, recursive scan, and PDFs."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.modules.local_corpus import (
    BIB_EXTENSIONS,
    DATA_EXTENSIONS,
    PDF_EXTENSIONS,
    iter_corpus_files,
    parse_corpus_roots,
)

# ── parse_corpus_roots ───────────────────────────────────────────────────────


def test_parse_corpus_roots_single(tmp_path):
    assert parse_corpus_roots(str(tmp_path)) == [tmp_path]


def test_parse_corpus_roots_comma_separated(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert parse_corpus_roots(f"{a}, {b}") == [a, b]


def test_parse_corpus_roots_drops_missing(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    assert parse_corpus_roots(f"{real},/nope/xyz") == [real]


def test_parse_corpus_roots_empty():
    assert parse_corpus_roots(None) == []
    assert parse_corpus_roots("") == []


# ── iter_corpus_files ────────────────────────────────────────────────────────


def _make_corpus(root: Path) -> None:
    (root / "top.csv").write_text("a\n1\n")
    (root / "refs.bib").write_text("@article{x, title={X}}")
    (root / "paper.pdf").write_bytes(b"%PDF-1.4")
    sub = root / "raw"
    sub.mkdir()
    (sub / "deep.csv").write_text("a\n1\n")
    (sub / "deep.pdf").write_bytes(b"%PDF-1.4")


def test_iter_top_level_only_by_default(tmp_path):
    _make_corpus(tmp_path)
    files = {p.name for _, p in iter_corpus_files([tmp_path], DATA_EXTENSIONS, recursive=False)}
    assert files == {"top.csv"}


def test_iter_recursive_finds_subdirs(tmp_path):
    _make_corpus(tmp_path)
    files = {p.name for _, p in iter_corpus_files([tmp_path], DATA_EXTENSIONS, recursive=True)}
    assert files == {"top.csv", "deep.csv"}


def test_iter_suffix_filter(tmp_path):
    _make_corpus(tmp_path)
    bibs = list(iter_corpus_files([tmp_path], BIB_EXTENSIONS, recursive=False))
    assert len(bibs) == 1 and bibs[0][1].suffix == ".bib"
    pdfs = list(iter_corpus_files([tmp_path], PDF_EXTENSIONS, recursive=True))
    assert {p.name for _, p in pdfs} == {"paper.pdf", "deep.pdf"}


# ── LocalBibLibrary multi-path + recursive ───────────────────────────────────


def test_local_bib_library_multi_root(tmp_path):
    from src.modules.literature.providers import LocalBibLibrary

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "alpha.bib").write_text(_bib("Alpha"))
    (b / "beta.bib").write_text(_bib("Beta"))

    lib = LocalBibLibrary(None, f"{a},{b}", recursive=False)
    titles = sorted(p.title for p in lib.entries())
    assert titles == ["Alpha", "Beta"]


def test_local_bib_library_recursive(tmp_path):
    from src.modules.literature.providers import LocalBibLibrary

    (tmp_path / "top.bib").write_text(_bib("Top"))
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "deep.bib").write_text(_bib("Deep"))

    flat = LocalBibLibrary(None, str(tmp_path), recursive=False)
    assert {p.title for p in flat.entries()} == {"Top"}

    deep = LocalBibLibrary(None, str(tmp_path), recursive=True)
    assert {p.title for p in deep.entries()} == {"Top", "Deep"}


def _bib(title: str) -> str:
    key = title.lower()
    return f"@article{{{key}, title={{{title}}}, author={{Doe, J.}}, year={{2024}}}}\n"


# ── workspace staging: data files (recursive) + PDFs into literature/ ────────


def test_staging_recursive_data_preserves_subdirs(tmp_path):
    from src.api.app import _link_local_data_dir_into_workspace

    corpus = tmp_path / "corpus"
    (corpus / "raw").mkdir(parents=True)
    (corpus / "top.csv").write_text("a\n")
    (corpus / "raw" / "deep.csv").write_text("b\n")

    ws = tmp_path / "ws"
    ws.mkdir()
    _link_local_data_dir_into_workspace(ws, str(corpus), recursive=True)

    assert (ws / "data" / "top.csv").is_symlink()
    assert (ws / "data" / "raw" / "deep.csv").is_symlink()


def test_staging_pdfs_land_in_literature_dir(tmp_path):
    from src.api.app import _link_local_data_dir_into_workspace

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "smith2024.pdf").write_bytes(b"%PDF-1.4 fake")
    (corpus / "data.csv").write_text("a\n")

    ws = tmp_path / "ws"
    ws.mkdir()
    _link_local_data_dir_into_workspace(ws, str(corpus), recursive=False)

    assert (ws / "literature" / "smith2024.pdf").is_symlink()
    # Sanity: csv still goes to data/, PDF does NOT.
    assert (ws / "data" / "data.csv").is_symlink()
    assert not (ws / "data" / "smith2024.pdf").exists()


# ── read_reference with workspace `path` ─────────────────────────────────────


async def test_read_reference_with_local_path(tmp_path):
    from src.modules.literature.tools import LiteratureToolHandler

    pdf = tmp_path / "literature" / "x.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 stub")

    handler = LiteratureToolHandler(tmp_path)
    with patch("src.modules.literature.pdf.extract_pdf_text", return_value="FULLTEXT"):
        result = json.loads(await handler.handle("read_reference", {"path": "literature/x.pdf"}))
    assert result["text"] == "FULLTEXT"
    assert result["path"] == "literature/x.pdf"


async def test_read_reference_path_blocks_traversal(tmp_path):
    from src.modules.literature.tools import LiteratureToolHandler

    handler = LiteratureToolHandler(tmp_path)
    result = json.loads(await handler.handle("read_reference", {"path": "../escape.pdf"}))
    assert "inside the workspace" in result["error"]


# ── reference summary mentions local PDFs to bib specialists ─────────────────


def test_local_pdfs_summary_for_bib_specialist(tmp_path):
    from src.core.specialists.base import _list_local_pdfs_for_prompt

    paper_id = "pid"
    (tmp_path / paper_id / "literature").mkdir(parents=True)
    (tmp_path / paper_id / "literature" / "smith.pdf").write_bytes(b"%PDF")

    with patch("src.config.get_settings", return_value=SimpleNamespace(workspace_root=str(tmp_path))):
        out = _list_local_pdfs_for_prompt("paper_drafter", paper_id)
    assert "literature/smith.pdf" in out
    assert "read_reference" in out


def test_local_pdfs_summary_omitted_for_non_bib_specialist(tmp_path):
    from src.core.specialists.base import _list_local_pdfs_for_prompt

    paper_id = "pid"
    (tmp_path / paper_id / "literature").mkdir(parents=True)
    (tmp_path / paper_id / "literature" / "x.pdf").write_bytes(b"%PDF")
    with patch("src.config.get_settings", return_value=SimpleNamespace(workspace_root=str(tmp_path))):
        assert _list_local_pdfs_for_prompt("data_analyst", paper_id) == ""
