"""Skills loader — reads skill markdown files and injects into specialist prompts.

Source of truth for which skills attach to which specialist:
  ``src.core.specialists.registry.SPECIALIST_SKILLS``

That dict uses full paths (e.g. ``"data/cleaning"``) so each entry uniquely
identifies a single ``.md`` file under ``skills/files/``. We previously had
a parallel ``_SPECIALIST_SKILLS`` here using stem-only names; the two
drifted apart whenever someone added a skill to one but not the other.
Consolidated into a single source 2026-05-15.
"""

from __future__ import annotations

from pathlib import Path

# Search in two locations: src/skills/files/ (installed package) and
# project-root skills/files/ (development checkout, Docker mount).
_SKILLS_DIRS = [
    Path(__file__).parent / "files",
    Path(__file__).parent.parent.parent / "skills" / "files",
]


def load_skills_for_specialist(specialist: str) -> str:
    """Load and concatenate skill files for a specialist.

    Returns the empty string if the specialist isn't registered or none of
    its skills resolve to a file on disk. Each skill is separated by
    ``\\n\\n---\\n\\n`` so prompts can split them back out if needed.
    """
    # Lazy import to avoid a circular dependency: registry imports nothing
    # from this module, but other things in `core.specialists` do.
    from ..core.specialists.registry import SPECIALIST_SKILLS

    skill_paths = SPECIALIST_SKILLS.get(specialist, [])
    parts = []
    for path in skill_paths:
        content = _load_skill(path)
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts)


def _load_skill(path_or_stem: str) -> str:
    """Load a skill file by full path (e.g. ``"data/cleaning"``) or by stem.

    Preferred form is the full path including category — uniquely
    identifies the file. The stem-only fallback exists so tests and
    scripts that haven't been updated yet keep working; new code should
    always use the full path.
    """
    rel = f"{path_or_stem}.md"
    for skills_dir in _SKILLS_DIRS:
        candidate = skills_dir / rel
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                continue
        # Stem-only fallback: search recursively. Slower, but only fires
        # when the caller hasn't migrated to the full-path form yet.
        if "/" not in path_or_stem and skills_dir.exists():
            for found in skills_dir.rglob(f"{path_or_stem}.md"):
                try:
                    return found.read_text(encoding="utf-8")
                except Exception:
                    continue
    return ""


def list_available_skills() -> list[str]:
    """List all skill file paths (relative to skills dir, without .md)."""
    seen: set[str] = set()
    for skills_dir in _SKILLS_DIRS:
        if not skills_dir.exists():
            continue
        for p in skills_dir.rglob("*.md"):
            rel = p.relative_to(skills_dir).with_suffix("")
            seen.add(str(rel))
    return sorted(seen)
