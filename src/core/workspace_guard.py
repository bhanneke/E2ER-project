"""Links out of a study's folder, for the e2er commands an AI step runs.

An AI-written script runs in the operating system's sandbox (core/script_sandbox.py), but inside it
the script can still create a symbolic link in the study's folder that points elsewhere, for example
``data.db -> ~/.e2er/<run database>``. The e2er commands the model runs next (``e2er-data``,
``e2er-lit``, ``e2er-check-tables``, ``e2er-fieldmap``) are e2er's own code and run outside that
sandbox; following such a link they would read, and hand back to the model, a file outside the
study (review of 2026-11-24). So during an AI step a command refuses to run while the study's folder
holds a link that leads out of it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Folders a study's links in which do not matter to the commands, and that can be large.
_SKIP = frozenset({".git", ".venv", "venv", "__pycache__", "node_modules"})
#: An upper bound on the entries looked at, so a huge data folder cannot stall a command.
_MAX_ENTRIES = 200_000


def outside_links(workspace: Path, *, limit: int = 20) -> list[str]:
    """Links in ``workspace`` (relative paths) whose target lies outside it, at most ``limit``."""
    root = Path(workspace).resolve()
    found: list[str] = []
    seen = 0
    for here, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in _SKIP]
        for name in [*dirs, *files]:
            seen += 1
            if seen > _MAX_ENTRIES:
                return found
            p = Path(here) / name
            if not p.is_symlink():
                continue
            try:
                target = p.resolve()
            except (OSError, RuntimeError):  # a loop of links
                found.append(p.relative_to(root).as_posix())
                continue
            if not target.is_relative_to(root):
                found.append(p.relative_to(root).as_posix())
                if len(found) >= limit:
                    return found
    return found


def refusal(workspace: Path, command: str) -> str | None:
    """The sentence that refuses ``command`` while the study's folder links out of itself, or None."""
    links = outside_links(workspace)
    if not links:
        return None
    return (
        f"{command}: refused. The study's folder holds links that point outside it ({', '.join(links)}); "
        "e2er's commands do not follow them. Delete the links (write the files into the study's folder "
        "instead) and run the command again."
    )


def guard_ai_step(command: str) -> int | None:
    """For a command's entry point: exit code 2 with the reason when an AI step's folder links out, else None.

    Applies only during an AI step (``E2ER_AI_STEP``, set for every specialist's commands); a researcher
    running the command in a terminal is not checked.
    """
    if not os.environ.get("E2ER_AI_STEP"):
        return None
    workspace = Path(os.environ.get("E2ER_WORKSPACE") or Path.cwd())
    why = refusal(workspace, command)
    if why is None:
        return None
    print(why, file=sys.stderr)
    return 2
