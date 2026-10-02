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
import re
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


def study_purpose(workspace: Path | None = None) -> str | None:
    """A study's purpose: the one chosen for it when it started (manifest.json), else E2ER_PURPOSE.

    The dashboard's "demonstration" box marks one study, not the whole server,
    so it is recorded in that study's manifest.
    """
    if workspace is not None:
        import json

        try:
            recorded = json.loads((Path(workspace) / "manifest.json").read_text(encoding="utf-8")).get("purpose")
        except (OSError, ValueError, AttributeError):
            recorded = None
        if recorded in PURPOSES:
            return str(recorded)
    return resolve_purpose()


BEGIN = "<!-- e2er:disclaimer begin -->"
END = "<!-- e2er:disclaimer end -->"
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n*", re.S)
#: A disclaimer written before the block was delimited: a quote line at the top
#: in any wording e2er used ("> Demonstration. …").
_LEGACY = re.compile(r"\A> Demonstration\.[^\n]*\n+")


def _block(kind: str | None) -> str:
    return f"{BEGIN}\n> {disclaimer(kind)}\n{END}\n\n"


def mark_report(path: Path, kind: str | None = "replication", *, purpose: str | None = DEMONSTRATION) -> bool:
    """Make the disclaimer at the top of a Markdown report match the study's purpose.

    The disclaimer sits in a delimited block, so a changed wording replaces
    it instead of adding a second one, and a study published without a
    purpose loses it. An undelimited disclaimer of an earlier e2er is
    replaced the same way. A byte-order mark stays first. Idempotent; returns
    True when the file changed.
    """
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8")
    bom = "\ufeff" if raw.startswith("\ufeff") else ""
    text = raw[len(bom) :]
    body = _BLOCK.sub("", text, count=1) if text.startswith(BEGIN) else text
    body = _LEGACY.sub("", body, count=1)
    new = bom + (_block(kind) if purpose == DEMONSTRATION else "") + body
    if new == raw:
        return False
    path.write_text(new, encoding="utf-8")
    return True


__all__ = [
    "BEGIN",
    "DEMONSTRATION",
    "DISCLAIMERS",
    "END",
    "ENV",
    "PURPOSES",
    "disclaimer",
    "kind_for",
    "mark_report",
    "resolve_purpose",
    "study_purpose",
]
