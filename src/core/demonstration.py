"""Demonstration studies: the disclaimer a study carries when it is published only to demonstrate e2er.

A study published with ``e2er publish --demonstration`` (or with
``E2ER_PURPOSE=demonstration`` in the environment or in the study folder's
``.env``) records ``purpose: "demonstration"`` in e2er.json and in its dossier;
a study made with the replication template also records ``kind: "replication"``.
The paper's first page and the reproduction report then carry the disclaimer.

The wording lives here and nowhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The purposes a study can declare. Only one exists.
DEMONSTRATION = "demonstration"
PURPOSES = (DEMONSTRATION,)

#: The disclaimer of a demonstration study, by kind.
DISCLAIMERS: dict[str, str] = {
    "study": (
        "Demonstration. This study was produced with e2er and published as is to demonstrate e2er.org. "
        "It is not presented as a research contribution, and its author does not vouch for its findings."
    ),
    "replication": (
        "Demonstration. This reproduction was run as is to demonstrate e2er's replication template. "
        "It is not an assessment of the original authors' work; differences can come from e2er itself."
    ),
}

#: The template whose studies are reproductions.
REPLICATION_TEMPLATE = "replication"

ENV = "E2ER_PURPOSE"


def disclaimer(kind: str | None = None) -> str:
    """The disclaimer for a study of this kind (``replication`` or anything else)."""
    return DISCLAIMERS["replication" if kind == "replication" else "study"]


def kind_for(template: str | None) -> str | None:
    """``replication`` for a study made with the replication template, else None (a study)."""
    return "replication" if template == REPLICATION_TEMPLATE else None


def _from_dotenv(folder: Path) -> str | None:
    """E2ER_PURPOSE from ``<folder>/.env``, reading that one key only."""
    env = folder / ".env"
    if not env.is_file():
        return None
    from dotenv import dotenv_values

    value = dotenv_values(env).get(ENV)
    return value if value is None else str(value)


def resolve_purpose(flag: bool = False, folder: Path | None = None) -> str | None:
    """The study's purpose: ``demonstration`` from the flag, else from E2ER_PURPOSE, else None.

    E2ER_PURPOSE is read from the environment, then from ``.env`` in ``folder``
    (default: the current directory, the study folder e2er runs in). An empty
    value means no purpose; any other value than ``demonstration`` is refused.
    """
    if flag:
        return DEMONSTRATION
    raw = os.environ.get(ENV)
    if raw is None:
        raw = _from_dotenv(folder or Path.cwd())
    value = (raw or "").strip().lower()
    if not value:
        return None
    if value not in PURPOSES:
        raise ValueError(f"{ENV}={raw!r} is not a known purpose; the only one is {DEMONSTRATION!r} (or leave it empty)")
    return value


def mark_report(path: Path, kind: str | None = "replication") -> bool:
    """Put the disclaimer at the top of a Markdown report. Idempotent; returns True when the file changed."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    line = f"> {disclaimer(kind)}"
    if text.startswith(line):
        return False
    path.write_text(f"{line}\n\n{text}", encoding="utf-8")
    return True


__all__ = [
    "DEMONSTRATION",
    "DISCLAIMERS",
    "ENV",
    "PURPOSES",
    "disclaimer",
    "kind_for",
    "mark_report",
    "resolve_purpose",
]
