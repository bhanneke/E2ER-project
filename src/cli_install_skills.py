"""``e2er install-skills`` — copy bundled skill .md files to per-backend dirs.

Each headless backend (Claude Code, Codex, Gemini) discovers skill files
under a vendor-specific directory:

    ~/.claude/skills/
    ~/.codex/skills/
    ~/.gemini/skills/

E2ER bundles its full skill library under ``skills/files/`` in the wheel.
This command copies them to the chosen backend's directory so the CLI
picks them up at session start. Mirrors the install-skills convention
used by Davidvandijcke/coarse.

By default the command targets all installed backends; pass ``--backend``
to restrict. Files that already exist are skipped unless ``--force``.

Returns 0 on success, 1 on no-source-found.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .logging_config import get_logger

logger = get_logger(__name__)


def _bundled_skills_dir() -> Path | None:
    """Locate the bundled ``skills/files/`` directory.

    Priority:
      1. Source checkout — repo root has ``skills/files/`` (dev install).
      2. Installed wheel — same directory exists relative to the
         ``skills`` package via ``importlib.resources``.

    Returns None if no source is found (rare; means a broken install).
    """
    # 1) Dev install: walk up from this file looking for `skills/files/`.
    here = Path(__file__).resolve()
    for parent in [here.parent.parent, here.parent.parent.parent]:
        candidate = parent / "skills" / "files"
        if candidate.is_dir():
            return candidate

    # 2) Installed wheel: importlib.resources points at the packaged data.
    try:
        from importlib.resources import files

        pkg = files("skills.files")
        # pkg is a Traversable; convert to a real Path for shutil.copy
        # (importlib.resources supports as_file in 3.9+).
        return Path(str(pkg))
    except Exception:
        return None


def _backend_skills_dirs(backend: str) -> list[Path]:
    """Return the destination directories for the chosen backend(s)."""
    home = Path.home()
    mapping = {
        "claude": home / ".claude" / "skills",
        "codex": home / ".codex" / "skills",
        "gemini": home / ".gemini" / "skills",
    }
    if backend == "all":
        return list(mapping.values())
    return [mapping[backend]]


def install_skills(backend: str = "all", force: bool = False) -> int:
    """Copy bundled skill files to the chosen backend(s)' skill directory."""
    src = _bundled_skills_dir()
    if src is None or not src.is_dir():
        print(
            "No bundled skill files found. E2ER seems to be installed in a "
            "broken state. Try reinstalling with `pip install -e '.[dev]'` "
            "or `pip install --force-reinstall e2er`."
        )
        return 1

    targets = _backend_skills_dirs(backend)
    total_copied = 0
    total_skipped = 0

    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        for md in src.rglob("*.md"):
            # Preserve category subdirs so loaders that scan by category
            # still find their files.
            rel = md.relative_to(src)
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and not force:
                total_skipped += 1
                continue
            shutil.copy2(md, dest)
            total_copied += 1

    print(f"e2er install-skills: copied {total_copied} file(s), skipped {total_skipped}")
    if total_skipped and not force:
        print("  (--force to overwrite existing files)")
    for target in targets:
        print(f"  → {target}")
    return 0
