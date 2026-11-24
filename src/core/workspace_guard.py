"""Links out of a study's folder, for the e2er commands an AI step runs.

An AI-written script runs in the operating system's sandbox (core/script_sandbox.py), which denies
e2er's folder, the run database and the user's secrets. The e2er commands the model runs next
(``e2er-data``, ``e2er-lit``, ``e2er-check-tables``, ``e2er-fieldmap``) are e2er's own code and run
outside that sandbox: following a link such as ``data.db -> ~/.e2er/<run database>`` they would read
what the sandbox denies and hand it to the model (review of 2026-11-24). So during an AI step a command
refuses to run while the study's folder holds a link into what the sandbox denies, or a link out of the
study anywhere but where e2er links the researcher's data and PDFs (``data/``, ``literature/``, files
only): through such a link a command could write outside the study (Codex's and Gemini's shells, and
bubblewrap, can make links). The sandbox on macOS lets a script make no link at all.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Folders a study's links in which do not matter to the commands, and that can be large.
_SKIP = frozenset({".git", ".venv", "venv", "__pycache__", "node_modules"})
#: Where e2er links the researcher's own files into a study (study_inputs, local_corpus): the only places a
#: link may lead out of the study, and only to a file. Anywhere else (data_dictionary.json, tables/,
#: results/ …) an e2er command could write through it, outside the AI CLI's own sandbox (Codex, Gemini).
_STAGED = frozenset({"data", "literature"})
#: An upper bound on the entries looked at, so a huge data folder cannot stall a command.
_MAX_ENTRIES = 200_000


class TooManyEntriesError(Exception):
    """The study's folder holds more entries than the check looks at."""


def denied_links(workspace: Path, *, limit: int = 20) -> list[str]:
    """Links in ``workspace`` (relative paths) that lead into what the script sandbox denies, at most ``limit``.

    Raises :class:`TooManyEntriesError` past :data:`_MAX_ENTRIES` entries: a check that stopped early
    would pass a link it never saw.
    """
    from .script_sandbox import denied_paths

    root = Path(workspace).resolve()
    denied = [Path(d).resolve() for d in denied_paths(workspace=root)]
    found: list[str] = []
    seen = 0
    for here, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in _SKIP]
        for name in [*dirs, *files]:
            seen += 1
            if seen > _MAX_ENTRIES:
                raise TooManyEntriesError(f"more than {_MAX_ENTRIES:,} files and folders")
            p = Path(here) / name
            if not p.is_symlink():
                continue
            try:
                target = p.resolve()
            except (OSError, RuntimeError):  # a loop of links
                found.append(p.relative_to(root).as_posix())
                continue
            if target.is_relative_to(root):
                continue  # a link within the study
            rel = p.relative_to(root)
            staged = rel.parts[0] in _STAGED and not target.is_dir()
            if not staged or any(target == d or target.is_relative_to(d) for d in denied):
                found.append(rel.as_posix())
                if len(found) >= limit:
                    return found
    return found


def refusal(workspace: Path, command: str) -> str | None:
    """The sentence that refuses ``command`` while the study's folder links out of itself, or None."""
    try:
        links = denied_links(workspace)
    except TooManyEntriesError as e:
        return (
            f"{command}: refused. The study's folder holds {e}, more than e2er checks for links; "
            "remove files the study does not need and run the command again."
        )
    if not links:
        return None
    return (
        f"{command}: refused. The study's folder holds links that lead out of it ({', '.join(links)}); e2er's "
        "commands follow only the links e2er makes to your data and PDFs. Delete these links (write the "
        "files into the study's folder instead) and run the command again."
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
