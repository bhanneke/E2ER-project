"""LaTeX compiler engine selection + command construction.

Regression for the no-PDF-compile bug: the compiler only knew latexmk/pdflatex
and skipped compilation when only `tectonic` was installed (the common
zero-install case on macOS). It now prefers latexmk → tectonic → pdflatex and
passes tectonic's continue-on-errors so a missing figure still yields a PDF.
"""

from __future__ import annotations

from unittest.mock import patch

from src.core.renderer.compiler import _build_cmd, _select_engine


def _which(available: set[str]):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def test_prefers_latexmk_then_tectonic_then_pdflatex():
    with patch("src.core.renderer.compiler.shutil.which", _which({"latexmk", "tectonic", "pdflatex"})):
        assert _select_engine() == "latexmk"
    with patch("src.core.renderer.compiler.shutil.which", _which({"tectonic", "pdflatex"})):
        assert _select_engine() == "tectonic"
    with patch("src.core.renderer.compiler.shutil.which", _which({"pdflatex"})):
        assert _select_engine() == "pdflatex"


def test_tectonic_is_discovered_when_only_engine():
    """The exact bug: only tectonic installed → it must be selected, not None."""
    with patch("src.core.renderer.compiler.shutil.which", _which({"tectonic"})):
        assert _select_engine() == "tectonic"


def test_no_engine_returns_none():
    with patch("src.core.renderer.compiler.shutil.which", _which(set())):
        assert _select_engine() is None


def test_build_cmd_tectonic_has_continue_on_errors():
    cmd = _build_cmd("tectonic", "paper_draft.tex")
    assert cmd[0] == "tectonic"
    assert "-Z" in cmd and "continue-on-errors" in cmd
    assert cmd[-1] == "paper_draft.tex"


def test_build_cmd_latexmk_and_pdflatex():
    assert _build_cmd("latexmk", "p.tex") == ["latexmk", "-pdf", "-interaction=nonstopmode", "p.tex"]
    assert _build_cmd("pdflatex", "p.tex") == ["pdflatex", "-interaction=nonstopmode", "p.tex"]
