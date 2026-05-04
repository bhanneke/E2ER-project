"""Renderer — assembles specialist outputs into a cohesive paper draft."""
from __future__ import annotations

from pathlib import Path


def assemble_draft(workspace: Path) -> str:
    """Read all section artifacts and assemble a draft in LaTeX order."""
    sections = [
        ("introduction", "introduction.tex"),
        ("literature_review", "literature_review.tex"),
        ("theory", "theory.tex"),
        ("data", "data.tex"),
        ("methodology", "methodology.tex"),
        ("results", "results.tex"),
        ("discussion", "discussion.tex"),
        ("conclusion", "conclusion.tex"),
    ]

    parts = []
    for _, filename in sections:
        path = workspace / filename
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))

    # Check for monolithic draft
    if not parts:
        draft_path = workspace / "paper_draft.tex"
        if draft_path.exists():
            return draft_path.read_text(encoding="utf-8")

    return "\n\n".join(parts)


def write_assembled_draft(workspace: Path) -> Path:
    """Assemble sections into paper_draft.tex if sections exist."""
    content = assemble_draft(workspace)
    if not content:
        return workspace / "paper_draft.tex"

    draft_path = workspace / "paper_draft.tex"
    draft_path.write_text(content, encoding="utf-8")
    return draft_path
