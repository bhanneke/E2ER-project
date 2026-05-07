"""LaTeX compiler — wraps the drafter's body in a standard preamble + bib and compiles to PDF."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from ...logging_config import get_logger
from .templates import assemble_document, assemble_refs_bib, looks_like_full_document

logger = get_logger(__name__)


async def compile_latex(workspace: Path, main_file: str = "paper_draft.tex") -> Path | None:
    """Assemble (preamble + body + bibliography) and compile to PDF.

    Pipeline:
      1. Read paper_draft.tex (the drafter's body, ideally without \\documentclass).
      2. Assemble refs.bib by merging literature.bib + user_refs.bib (deduped).
      3. Wrap body with the standard preamble (templates.PREAMBLE).
      4. Run pdflatex / bibtex / pdflatex / pdflatex (or latexmk if available).
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

    compiler = shutil.which("latexmk") or shutil.which("pdflatex")
    if not compiler:
        logger.warning("No LaTeX compiler found — skipping PDF compilation")
        return None

    # latexmk runs the bib + multiple latex passes automatically.
    if "latexmk" in compiler:
        cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", main_file]
    else:
        cmd = ["pdflatex", "-interaction=nonstopmode", main_file]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode == 0:
            pdf_path = workspace / main_file.replace(".tex", ".pdf")
            if pdf_path.exists():
                logger.info("Compiled PDF: %s", pdf_path)
                return pdf_path
            logger.warning("Compiler succeeded but PDF not found")
        else:
            logger.warning("LaTeX compilation failed: %s", stderr.decode()[:500])
    except TimeoutError:
        logger.warning("LaTeX compilation timed out")
    except Exception as e:
        logger.warning("LaTeX compilation error: %s", e)
    return None
