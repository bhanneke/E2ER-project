"""LaTeX template formatting fixes — title ordering, running header, xcolor,
graphicspath, and the figures/ mirror."""

from __future__ import annotations

from pathlib import Path

from src.core.renderer.compiler import _mirror_figures_into_subdir
from src.core.renderer.templates import _extract_braced, _running_title, assemble_document


def test_title_hoisted_before_maketitle():
    # drafter wrote \title INSIDE the body (after where \maketitle would run)
    body = r"\maketitle" + "\n" + r"\title{My Real Paper}" + "\nSome prose.\n"
    out = assemble_document(body)
    # title defined in the preamble, before \begin{document}\maketitle
    assert out.index(r"\title{My Real Paper}") < out.index(r"\begin{document}")
    assert out.index(r"\title{My Real Paper}") < out.index(r"\maketitle")
    # the body's stray \maketitle was removed (only our one remains)
    assert out.count(r"\maketitle") == 1


def test_multiline_title_extracted():
    body = "\\title{Line one\nand line two}\nBody.\n"
    content, rest = _extract_braced(body, "title")
    assert content == "Line one\nand line two"
    assert r"\title" not in rest


def test_running_header_and_produced_by():
    out = assemble_document(r"\title{T}" + "\nx\n")
    assert "Produced by E2ER" in out
    assert r"\pagestyle{fancy}" in out
    assert r"\fancypagestyle{plain}" in out  # header on the title page too


def test_xcolor_before_hyperref_and_graphicspath():
    out = assemble_document("x\n")
    assert r"\usepackage{xcolor}" in out
    assert out.index(r"\usepackage{xcolor}") < out.index(r"\usepackage{hyperref}")
    assert r"\graphicspath{{./}{figures/}}" in out


def test_default_author_is_e2er():
    out = assemble_document(r"\title{T}" + "\nx\n")
    assert r"\author{Produced by the E2ER pipeline}" in out


def test_running_title_truncates():
    long = "A " * 100
    assert len(_running_title(long)) <= 70


def test_mirror_figures_into_subdir(tmp_path: Path):
    (tmp_path / "fig_a.pdf").write_bytes(b"%PDF-1.4 a")
    (tmp_path / "fig_b.pdf").write_bytes(b"%PDF-1.4 b")
    (tmp_path / "notafig.pdf").write_bytes(b"%PDF-1.4 x")
    _mirror_figures_into_subdir(tmp_path)
    assert (tmp_path / "figures" / "fig_a.pdf").is_file()
    assert (tmp_path / "figures" / "fig_b.pdf").is_file()
    assert not (tmp_path / "figures" / "notafig.pdf").exists()  # only fig_*.pdf


def test_mirror_no_figures_is_noop(tmp_path: Path):
    _mirror_figures_into_subdir(tmp_path)  # must not raise / create anything
    assert not (tmp_path / "figures").exists()
