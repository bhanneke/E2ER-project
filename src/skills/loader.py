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
    # Packs installed from the RISE catalogue by `e2er skills install`.
    # Last, so a bundled skill of the same name still wins: an installed pack
    # should extend the library, not silently replace part of it.
    Path.home() / ".e2er" / "skills",
]


#: The directories of e2er's own skills (the first two of _SKILLS_DIRS).
_BUNDLED_DIRS = _SKILLS_DIRS[:2]


def is_bundled_skill(path: str) -> bool:
    """True iff ``path`` (``"econometrics/event-study"``) is one of e2er's own skills.

    Its own when the file is bundled with e2er, or when the path is in one of
    e2er's skill categories (a skill e2er has since removed is still its own).
    A path whose first part is not such a category is an installed pack's
    (``~/.e2er/skills/<pack>/<skill>.md``, from ``e2er skills install`` or
    copied there).
    """
    if "/" not in path:
        return True
    head = path.split("/", 1)[0]
    return any((d / f"{path}.md").is_file() or (d / head).is_dir() for d in _BUNDLED_DIRS)


def skill_component(path: str) -> str:
    """The component id of a skill a specialist read, named by its origin.

    e2er's own skills are ``skill:e2er/<category>/<name>`` (unchanged, so
    existing dossiers keep their ids); a skill from an installed pack is
    ``skill:<pack>/<skill>``, the id under which e2er.org lists contributed
    parts and catalogue packs, so the dossier links the listed part and the
    study credits its author.
    """
    return f"skill:e2er/{path}" if is_bundled_skill(path) else f"skill:{path}"


def loaded_skill_names(specialist: str) -> list[str]:
    """The skills a specialist dispatched now reads: those of :func:`load_skills_for_specialist` that resolve to a file.

    Recorded with each dispatch (``specialist_start``), so the dossier lists
    the skills that ran, not the ones a later checkout would give.
    """
    from ..core.pipeline.components import skills_for

    return [p for p in skills_for(specialist) if _load_skill(p)]


def load_skills_for_specialist(specialist: str) -> str:
    """Load and concatenate skill files for a specialist.

    Returns the empty string if the specialist isn't registered or none of
    its skills resolve to a file on disk. Each skill is separated by
    ``\\n\\n---\\n\\n`` so prompts can split them back out if needed.
    """
    # Lazy import to avoid a circular dependency: registry imports nothing
    # from this module, but other things in `core.specialists` do.
    # The registry's skills, plus any the active template adds for this
    # specialist (`[skills]` in the template; see core/pipeline/components.py).
    from ..core.pipeline.components import skills_for

    skill_paths = skills_for(specialist)
    parts = []
    for path in skill_paths:
        content = _load_skill(path)
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts)


def skill_exists(path: str) -> bool:
    """True iff ``path`` (e.g. ``"econometrics/event-study"``) names a skill file on disk."""
    return any((d / f"{path}.md").is_file() for d in _SKILLS_DIRS)


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
