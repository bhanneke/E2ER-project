"""LaTeX compiler — wraps the drafter's body in a standard preamble + bib and compiles to PDF."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from ...logging_config import get_logger
from .templates import assemble_document, assemble_refs_bib, looks_like_full_document

logger = get_logger(__name__)

# Compiler preference order. latexmk and tectonic both run bib + multiple
# passes in one shot; tectonic is self-contained (single binary, fetches
# packages on demand) so it's the zero-install fallback. Bare pdflatex is last
# (it doesn't run the bibliography on its own).
_ENGINE_PREFERENCE = ("latexmk", "tectonic", "pdflatex")


def _select_engine() -> str | None:
    for name in _ENGINE_PREFERENCE:
        if shutil.which(name):
            return name
    return None


def _build_cmd(engine: str, main_file: str) -> list[str]:
    if engine == "latexmk":
        return ["latexmk", "-pdf", "-interaction=nonstopmode", main_file]
    if engine == "tectonic":
        # Non-interactive by default; --keep-logs leaves a .log for debugging.
        # -Z continue-on-errors is tectonic's nonstopmode equivalent: a missing
        # figure or a stray undefined macro still yields a PDF instead of
        # halting (so a paper always compiles to *something*). Default output is
        # the input file's directory (cwd=workspace) → workspace/<main>.pdf.
        return ["tectonic", "--keep-logs", "--chatter", "minimal", "-Z", "continue-on-errors", main_file]
    return ["pdflatex", "-interaction=nonstopmode", main_file]


async def compile_latex(workspace: Path, main_file: str = "paper_draft.tex") -> Path | None:
    """Assemble (preamble + body + bibliography) and compile to PDF.

    Pipeline:
      1. Read paper_draft.tex (the drafter's body, ideally without \\documentclass).
      2. Assemble refs.bib by merging literature.bib + user_refs.bib (deduped).
      3. Wrap body with the standard preamble (templates.PREAMBLE).
      4. Compile with the first available engine: latexmk, tectonic, or pdflatex.
    """
    tex_path = workspace / main_file
    if not tex_path.exists():
        logger.warning("No LaTeX file found at %s", tex_path)
        return None

    # Assemble refs.bib (no-op if no sources present).
    refs = assemble_refs_bib(workspace)
    if refs:
        logger.info("Assembled refs.bib at %s", refs)

    # Wrap the body if needed. Original draft is preserved as paper_draft.body.tex.
    body = tex_path.read_text(encoding="utf-8")
    if not looks_like_full_document(body):
        backup = workspace / "paper_draft.body.tex"
        backup.write_text(body, encoding="utf-8")
        wrapped = assemble_document(body)
        tex_path.write_text(wrapped, encoding="utf-8")
        logger.info("Wrapped paper_draft.tex with preamble (body backup at %s)", backup)

    engine = _select_engine()
    if engine is None:
        logger.warning(
            "No LaTeX compiler found (looked for latexmk, tectonic, pdflatex) — skipping PDF compilation"
        )
        return None

    cmd = _build_cmd(engine, main_file)
    # tectonic fetches packages from the network on first use (cached after),
    # so give it a longer ceiling than a local TeX install.
    timeout = 600 if engine == "tectonic" else 180

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        # Use the PDF if it was produced, even on a non-zero exit: with
        # continue-on-errors / nonstopmode the engine often emits a usable PDF
        # while still returning non-zero on non-fatal warnings (undefined refs,
        # a missing figure). A produced PDF beats no PDF.
        pdf_path = workspace / main_file.replace(".tex", ".pdf")
        if pdf_path.exists():
            if proc.returncode != 0:
                logger.warning("LaTeX compile had non-fatal errors but produced a PDF: %s", stderr.decode()[:300])
            else:
                logger.info("Compiled PDF: %s", pdf_path)
            return pdf_path
        logger.warning("LaTeX compilation failed (no PDF produced): %s", stderr.decode()[:500])
    except TimeoutError:
        logger.warning("LaTeX compilation timed out")
    except Exception as e:
        logger.warning("LaTeX compilation error: %s", e)
    return None
