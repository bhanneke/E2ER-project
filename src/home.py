"""Where e2er keeps a researcher's settings, studies and exports: the studies folder.

Before 0.14.0 everything came from the folder `e2er` was started in: its
`.env`, its `workspaces/`, its exports. Started from another folder, e2er sent
the researcher back to Setup and the studies were split across folders, while
the run database (``~/.e2er/papers.db``) was shared by all of them.

Now Setup asks once for a studies folder (default ``~/e2er-studies``) and
remembers it in ``~/.e2er/settings.json``. `e2er` started from any folder uses
it. The rules, in order:

1. ``E2ER_PROJECT_DIR`` in the environment: that folder (set by `e2er` for its
   own server process, so the server and the command agree).
2. The current folder has its own `.env`: that folder, exactly as before. A
   project folder keeps working as a project of its own, and an existing user
   sees no change until they choose to make it their studies folder.
3. The remembered studies folder.
4. Nothing set up yet: the current folder (Setup then offers the default).

Studies made before 0.14.0 keep working from anywhere: the database records
each study's folder as an absolute path.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

ENV_PROJECT = "E2ER_PROJECT_DIR"


def state_dir() -> Path:
    return Path.home() / ".e2er"


def settings_file() -> Path:
    """Where e2er remembers the studies folder (and nothing secret)."""
    return state_dir() / "settings.json"


def default_studies_folder() -> Path:
    return Path.home() / "e2er-studies"


def _read() -> dict[str, object]:
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def remembered_studies_folder() -> Path | None:
    raw = _read().get("studies_folder")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def remember_studies_folder(folder: Path) -> Path:
    """Remember ``folder`` as the studies folder (made if missing). Returns it, absolute."""
    folder = folder.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    data = _read()
    data["studies_folder"] = str(folder)
    p = settings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return folder


def project_dir() -> Path:
    """The folder whose `.env`, studies and exports e2er uses now (see the module docstring)."""
    forced = os.environ.get(ENV_PROJECT, "").strip()
    if forced:
        return Path(forced).expanduser()
    cwd = Path.cwd()
    if (cwd / ".env").is_file():
        return cwd
    remembered = remembered_studies_folder()
    if remembered is not None and remembered.is_dir():
        return remembered
    return cwd


def env_file() -> Path:
    """The settings file e2er reads and Setup writes."""
    return project_dir() / ".env"


def kind() -> str:
    """``studies``: the remembered studies folder is in use; ``project``: a folder with its own `.env`
    that is not the studies folder; ``none``: nothing set up yet."""
    here = project_dir()
    remembered = remembered_studies_folder()
    if remembered is not None and _same(here, remembered):
        return "studies"
    if (here / ".env").is_file():
        return "project"
    return "none"


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


# ── readable folder names for new studies ────────────────────────────────────


def slug(text: str, limit: int = 40) -> str:
    """A short, file-safe version of a title: ``FOMC and bank stocks`` → ``fomc-and-bank-stocks``."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.sub(r"[^a-z0-9]+", " ", plain.lower()).split()
    out = ""
    for w in words:
        nxt = f"{out}-{w}" if out else w
        if len(nxt) > limit:
            break
        out = nxt
    return out or "study"


def new_workspace(root: Path, title: str, paper_id: str, today: datetime | None = None) -> Path:
    """A new, empty folder for one run: ``<root>/2026-10-08-fomc-and-bank-stocks`` (``-2``, ``-3`` when taken).

    The run's id is written into the folder (``manifest.json``) by the caller;
    :func:`find_workspace` finds the folder from it.
    """
    stamp = (today or datetime.now()).strftime("%Y-%m-%d")
    base = f"{stamp}-{slug(title)}"
    root.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        candidate = root / (base if n == 1 else f"{base}-{n}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        _KNOWN[paper_id] = candidate.resolve()
        return candidate
    candidate = root / paper_id  # a thousand runs of one title on one day: fall back to the id
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


#: run id → folder, for the folders this process made or found.
_KNOWN: dict[str, Path] = {}


def remember_workspace(paper_id: str, folder: Path) -> None:
    _KNOWN[paper_id] = Path(folder)


def find_workspace(paper_id: str, root: str | Path | None = None) -> Path:
    """The folder of run ``paper_id``.

    Runs before 0.14.0 live at ``<root>/<id>``; newer ones in a folder named
    after the date and title with the id in its ``manifest.json``. A subprocess
    of a run gets its folder in ``E2ER_WORKSPACE``. Falls back to
    ``<root>/<id>`` when nothing is found (the caller decides what a missing
    folder means).
    """
    known = _KNOWN.get(paper_id)
    if known is not None and known.is_dir():
        return known
    env_ws = os.environ.get("E2ER_WORKSPACE", "").strip()
    if env_ws and os.environ.get("E2ER_PAPER_ID", "") == paper_id:
        return Path(env_ws)
    if root is None:
        from .config import get_settings

        root = os.environ.get("E2ER_WORKSPACE_ROOT") or get_settings().workspace_root
    base = Path(root).expanduser()
    plain = base / paper_id
    if plain.is_dir():
        return plain
    if base.is_dir():
        for d in base.iterdir():
            m = d / "manifest.json"
            if not d.is_dir() or not m.is_file():
                continue
            try:
                if json.loads(m.read_text(encoding="utf-8")).get("paper_id") == paper_id:
                    _KNOWN[paper_id] = d
                    return d
            except (OSError, ValueError, AttributeError):
                continue
    return plain


def paper_id_of(workspace: Path) -> str:
    """The run id of a run folder: from its ``manifest.json``, else the folder name (runs before 0.14.0)."""
    try:
        pid = json.loads((Path(workspace) / "manifest.json").read_text(encoding="utf-8")).get("paper_id")
    except (OSError, ValueError, AttributeError):
        pid = None
    return str(pid) if pid else Path(workspace).name
