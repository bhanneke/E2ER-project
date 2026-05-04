"""LaTeX compiler — compiles paper_draft.tex to PDF."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


async def compile_latex(workspace: Path, main_file: str = "paper_draft.tex") -> Path | None:
    """Compile LaTeX to PDF using pdflatex or latexmk. Returns PDF path or None."""
    tex_path = workspace / main_file
    if not tex_path.exists():
        logger.warning("No LaTeX file found at %s", tex_path)
        return None

    compiler = shutil.which("latexmk") or shutil.which("pdflatex")
    if not compiler:
        logger.warning("No LaTeX compiler found — skipping PDF compilation")
        return None

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
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode == 0:
            pdf_path = workspace / main_file.replace(".tex", ".pdf")
            if pdf_path.exists():
                logger.info("Compiled PDF: %s", pdf_path)
                return pdf_path
            logger.warning("Compiler succeeded but PDF not found")
        else:
            logger.warning("LaTeX compilation failed: %s", stderr.decode()[:500])
    except asyncio.TimeoutError:
        logger.warning("LaTeX compilation timed out")
    except Exception as e:
        logger.warning("LaTeX compilation error: %s", e)
    return None
