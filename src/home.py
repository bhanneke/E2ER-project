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
4. Nothing set up yet: the current folder (Setup then offers it as the studies
   folder, or the default when e2er was started in the home folder), unless it
   is a temporary folder (``/tmp``, ``$TMPDIR``): then the default studies
   folder, so a study never lands where the operating system deletes files on
   its own (five demos' run databases went that way on 2026-10-19).

Started in another folder of its own (:func:`launch_folder`) while a studies
folder is remembered, e2er still uses the studies folder, and Setup names the
folder it was started in and offers to keep that folder's settings and studies
there (a project folder of its own, rule 2).

A folder the researcher chose in a temporary folder is used, with a warning
(:func:`storage_warnings`): the operating system may delete it.

Studies made before 0.14.0 keep working from anywhere: the database records
each study's folder as an absolute path.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

ENV_PROJECT = "E2ER_PROJECT_DIR"
#: Set (to anything) to keep using a temporary current folder when nothing is set up (the test suite does).
ENV_TEMPORARY_OK = "E2ER_TEMPORARY_FOLDER_OK"


def state_dir() -> Path:
    return Path.home() / ".e2er"


def settings_file() -> Path:
    """Where e2er remembers the studies folder (and nothing secret)."""
    return state_dir() / "settings.json"


def default_studies_folder() -> Path:
    return Path.home() / "e2er-studies"


# ── temporary folders, which the operating system empties ──────────────────

#: Folders the operating system deletes files from on its own: macOS clears /tmp and the
#: per-user temporary folder ($TMPDIR, under /var/folders) of files not used for a few days;
#: Linux empties /tmp at boot and /var/tmp after some weeks.
_TEMPORARY = (
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    "/private/var/tmp",
    "/var/folders",
    "/private/var/folders",
    "/dev/shm",
)


def _temporary_roots() -> list[Path]:
    roots = [Path(r) for r in _TEMPORARY]
    for raw in (os.environ.get("TMPDIR"), os.environ.get("TEMP"), os.environ.get("TMP"), tempfile.gettempdir()):
        if raw and raw.strip():
            roots.append(Path(raw.strip()).expanduser())
    out: list[Path] = []
    for r in roots:
        for form in (r, _resolved(r)):
            if form not in out:
                out.append(form)
    return out


def _resolved(p: Path) -> Path:
    try:
        return p.expanduser().resolve()
    except (OSError, RuntimeError):
        return p.expanduser().absolute()


def temporary_root(path: str | Path) -> Path | None:
    """The temporary folder ``path`` is in (``/tmp``, ``$TMPDIR``, …), or None."""
    p = Path(path).expanduser()
    for form in (p.absolute(), _resolved(p)):
        for root in _temporary_roots():
            if form == root or root in form.parents:
                return root
    return None


def temporary_notice(path: str | Path, what: str) -> str | None:
    """Why ``path`` is a bad place for studies, when it is in a temporary folder; else None."""
    root = temporary_root(path)
    if root is None:
        return None
    return (
        f"{what} {path} is in a temporary folder ({root}): the operating system may delete it on its own, and "
        "with it your studies and their run database. Choose a folder in your home folder, such as ~/e2er-studies."
    )


def temporary_warning(path: str | Path, what: str) -> str | None:
    """:func:`temporary_notice` as a warning line (``warning: …``)."""
    notice = temporary_notice(path, what)
    return f"warning: {notice}" if notice else None


def storage_warnings(settings: object | None = None) -> list[str]:
    """Warnings for the folders e2er keeps studies, runs and exports in that lie in a temporary folder."""
    places: list[tuple[str, Path]] = [("the studies folder", project_dir())]
    if settings is not None:
        root = Path(str(getattr(settings, "workspace_root", "workspaces") or "workspaces")).expanduser()
        places.append(("the studies' run folders (WORKSPACE_ROOT)", root if root.is_absolute() else Path.cwd() / root))
        url = ""
        try:
            url = str(getattr(settings, "resolved_database_url", "") or "")
        except Exception:  # noqa: BLE001 - a broken setting is the doctor's to report
            url = ""
        if not url or url.startswith("sqlite"):
            from .db.client import _sqlite_path

            try:
                places.append(("the run database (DATABASE_URL)", Path(_sqlite_path(url))))
            except ValueError:
                pass
        out_dir = getattr(settings, "output_dir", None)
        if out_dir:
            places.append(("the exports folder (OUTPUT_DIR)", Path(str(out_dir)).expanduser()))
    out: list[str] = []
    for what, place in places:
        w = temporary_warning(place, what)
        if w and w not in out:
            out.append(w)
    return out


def print_storage_warnings() -> None:
    """Print :func:`storage_warnings` for the settings in use (standard error); a broken setup prints nothing."""
    import sys

    try:
        from .config import get_settings

        found = storage_warnings(get_settings())
    except Exception:  # noqa: BLE001 - settings errors are reported where they are used
        found = storage_warnings()
    for w in found:
        print(w, file=sys.stderr)


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
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
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
    if (
        not os.environ.get(ENV_TEMPORARY_OK)
        and temporary_root(cwd) is not None
        and temporary_root(default_studies_folder()) is None
    ):
        # Nothing set up, started in a temporary folder: the default, never a folder the OS empties.
        return default_studies_folder()
    return cwd


def launch_folder() -> Path | None:
    """The folder e2er was started in, when the researcher started it there on purpose; else None.

    The home folder, a folder above it (``/``, ``/Users``) and a temporary folder are where a
    terminal opens or the operating system empties: starting e2er there chooses nothing, and the
    studies folder (or the default) is offered as before. Any other folder is one the researcher
    went to, so Setup offers it (tester report, 2026-10-27: a fresh project folder was shown
    ``~/e2er-studies`` and Save remembered that instead).
    """
    cwd = Path.cwd()
    here = _resolved(cwd)
    home = _resolved(Path.home())
    if here == home or here in home.parents or here.parent == here:
        return None
    if not os.environ.get(ENV_TEMPORARY_OK) and temporary_root(here) is not None:
        return None
    return cwd


def offered_launch_folder() -> Path | None:
    """:func:`launch_folder` when it is not the folder in use now and has no settings of its own."""
    here = launch_folder()
    if here is None or (here / ".env").is_file() or _same(here, project_dir()):
        return None
    return here


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


def is_run_id(paper_id: object) -> bool:
    """A run id e2er makes: a UUID (canonical or hex form), never a path."""
    import uuid

    if not isinstance(paper_id, str) or not paper_id or len(paper_id) > 40:
        return False
    try:
        uuid.UUID(paper_id)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


#: What ``find_workspace`` accepts besides a UUID: one plain name (the prefix of an id that
#: ``e2er export <prefix>`` looks up, a scratch id). Never ``.``, ``/`` or ``\``.
_PLAIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")


def is_plain_id(paper_id: object) -> bool:
    """A UUID or one plain name that cannot leave the folder it is joined to."""
    return is_run_id(paper_id) or (isinstance(paper_id, str) and bool(_PLAIN_ID.fullmatch(paper_id)))


def find_workspace(paper_id: str, root: str | Path | None = None) -> Path:
    """The folder of run ``paper_id``.

    Runs before 0.14.0 live at ``<root>/<id>``; newer ones in a folder named
    after the date and title with the id in its ``manifest.json``. A subprocess
    of a run gets its folder in ``E2ER_WORKSPACE``. Falls back to
    ``<root>/<id>`` when nothing is found (the caller decides what a missing
    folder means). An id that is neither a UUID nor one plain name (letters,
    digits, ``-``, ``_``; never ``..`` or ``/``) raises ``ValueError``. The dashboard's
    routes accept UUIDs only (src/api/guards.py).
    """
    known = _KNOWN.get(paper_id)
    if known is not None and known.is_dir():
        return known
    env_ws = os.environ.get("E2ER_WORKSPACE", "").strip()
    if env_ws and os.environ.get("E2ER_PAPER_ID", "") == paper_id:
        return Path(env_ws)
    if not is_plain_id(paper_id):
        # The id becomes a folder name below: ``..`` or ``a/b`` would name a folder outside the
        # workspaces (the dashboard served the studies folder's .env through /api/papers/%2E%2E/).
        raise ValueError(f"not a run id: {paper_id!r}")
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
