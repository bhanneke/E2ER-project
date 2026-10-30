"""One current study folder per run, instead of a numbered copy at every stop.

`export_paper` makes a new numbered folder each time (``…-01``, ``…-02``). The
run itself exported at every stop and at its end, and "Prepare the folder" on
the finish page made one more, so a finished study had five copies and the
researcher could not tell which one counts.

:func:`export_current` keeps one current folder per run:

* the run has not changed since the newest folder was made: that folder is used
  again (nothing is copied);
* it has changed, and the newest folder was never published: that folder is
  replaced, under the same name;
* the newest folder was published, or changed after export (``e2er redact``,
  ``e2er abstract``, the stamp: amendments in its provenance.json): it stays as it
  is, and a new folder is made. Replacing it would silently undo a redaction.

A replaced folder is built next to the old one first (a hidden temporary folder in
the exports folder) and moved into place only when it is complete, so a failed
export leaves the earlier folder as it was. One export per run at a time: a lock
file per run (``.e2er-export-<run>.lock``) keeps two exports of the same run (the
run's own and "Prepare the folder") from building over each other.

What "changed" means is a fingerprint of the run's working folder (every file's
path, size and modification time), kept for each exported folder in
``<exports>/.e2er-exports.json``. A published folder (``.e2er/link.json``) is
never removed: :func:`remove_older_copies` removes the other earlier copies on
request.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

INDEX = ".e2er-exports.json"


def workspace_fingerprint(workspace: Path) -> str:
    """Every file of the run's folder (path, size, modification time), as one hash.

    Hidden files and folders (``.previous``, ``.e2er``) and Python caches do not count.
    """
    h = hashlib.sha256()
    root = Path(workspace)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{p.relative_to(root).as_posix()}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def _read_index(dest_root: Path) -> dict[str, Any]:
    try:
        data = json.loads((dest_root / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_index(dest_root: Path, data: dict[str, Any]) -> None:
    p = dest_root / INDEX
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


_NUMBERED = re.compile(r"-(\d{8})-(\d{2,})$")


def export_order(folder: Path) -> tuple[str, int, float, str]:
    """Sort key of exported folders, oldest first: the date and number in the name (``…-YYYYMMDD-NN``).

    Not the modification time: redacting, stamping or copying an older folder changes its time, which
    made it "the newest" (and the next export replaced the wrong one). A folder without the numbered name
    sorts by its time, before the numbered ones of the same date.
    """
    m = _NUMBERED.search(folder.name)
    try:
        mtime = folder.stat().st_mtime
    except OSError:
        mtime = 0.0
    if m:
        return (m.group(1), int(m.group(2)), mtime, folder.name)
    return ("", -1, mtime, folder.name)


def exports_of(dest_root: Path, paper_id: str) -> list[Path]:
    """The exported folders of one run, oldest first (their provenance.json names the run; see :func:`export_order`)."""
    root = Path(dest_root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for d in root.iterdir():
        prov = d / "provenance.json"
        if not d.is_dir() or not prov.is_file():
            continue
        try:
            if (json.loads(prov.read_text(encoding="utf-8")).get("run") or {}).get("paper_id") == paper_id:
                found.append(d)
        except (OSError, ValueError):
            continue
    return sorted(found, key=export_order)


def is_published(folder: Path) -> bool:
    return (Path(folder) / ".e2er" / "link.json").is_file()


def is_amended(folder: Path) -> bool:
    """The folder changed after export (amendments in its provenance.json: a redaction, an abstract, a stamp)."""
    try:
        prov = json.loads((Path(folder) / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(prov, dict) and bool(prov.get("amendments"))


def is_kept(folder: Path) -> bool:
    """A folder export never replaces or removes: published, or changed after export."""
    return is_published(folder) or is_amended(folder)


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def export_lock(dest_root: Path, paper_id: str) -> Iterator[None]:
    """One export of the run at a time, in this process (a thread lock) and across processes (a lock file)."""
    key = f"{Path(dest_root).resolve()}\0{paper_id}"
    with _THREAD_LOCKS_GUARD:
        tlock = _THREAD_LOCKS.setdefault(key, threading.Lock())
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", paper_id)[:80] or "run"
    with tlock:
        from ..file_lock import exclusive

        with open(Path(dest_root) / f".e2er-export-{safe}.lock", "a+") as fh, exclusive(fh):
            yield


def published_link(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((Path(folder) / ".e2er" / "link.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def export_current(
    workspace: Path,
    dest_root: Path,
    *,
    paper_id: str,
    date_str: str,
    template: str | None = None,
) -> tuple[Path, str]:
    """The run's current exported folder, made or brought up to date.

    Returns the folder and what happened: ``unchanged`` (the newest folder is
    still current), ``replaced`` (the newest folder was rebuilt under its name)
    or ``new`` (a new folder; the newest one was published or amended, or there
    was none).
    """
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    with export_lock(dest_root, paper_id):
        return _export_current(Path(workspace), dest_root, paper_id=paper_id, date_str=date_str, template=template)


def _build_aside(
    workspace: Path, dest_root: Path, name: str, *, paper_id: str, date_str: str, template: str | None
) -> tuple[Path, Path]:
    """Export into a hidden temporary folder beside the exports: (the built folder, its temporary parent)."""
    from .structured import export_paper

    tmp_parent = Path(tempfile.mkdtemp(prefix=".e2er-building-", dir=dest_root))
    try:
        built = export_paper(workspace, tmp_parent, date_str=date_str, slug=name, template=template, paper_id=paper_id)
    except BaseException:
        shutil.rmtree(tmp_parent, ignore_errors=True)
        raise
    return built, tmp_parent


def _export_current(
    workspace: Path, dest_root: Path, *, paper_id: str, date_str: str, template: str | None
) -> tuple[Path, str]:
    from .structured import create_versioned_folder

    fingerprint = workspace_fingerprint(workspace)
    index = _read_index(dest_root)
    mine = exports_of(dest_root, paper_id)
    latest = mine[-1] if mine else None
    if latest is not None and (index.get(latest.name) or {}).get("fingerprint") == fingerprint:
        return latest, "unchanged"
    if latest is not None and not is_kept(latest):
        name = latest.name
        built, tmp_parent = _build_aside(
            workspace, dest_root, name, paper_id=paper_id, date_str=date_str, template=template
        )
        try:
            # The old folder moves aside only now that the new one is complete, and comes back if the move fails.
            old = tmp_parent / ".old"
            os.rename(latest, old)
            try:
                os.rename(built, latest)
            except BaseException:
                os.rename(old, latest)
                raise
        finally:
            shutil.rmtree(tmp_parent, ignore_errors=True)
        out = latest
        state = "replaced"
    else:
        manifest = _manifest(workspace)
        reserved = create_versioned_folder(dest_root, manifest.get("title") or workspace.name, date_str)
        try:
            built, tmp_parent = _build_aside(
                workspace, dest_root, reserved.name, paper_id=paper_id, date_str=date_str, template=template
            )
        except BaseException:
            reserved.rmdir()
            raise
        try:
            reserved.rmdir()
            os.rename(built, reserved)
        finally:
            shutil.rmtree(tmp_parent, ignore_errors=True)
        out = reserved
        state = "new"
    index = _read_index(dest_root)
    index[out.name] = {"paper_id": paper_id, "fingerprint": fingerprint}
    _write_index(dest_root, index)
    return out, state


def _manifest(workspace: Path) -> dict[str, Any]:
    try:
        data = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def older_copies(dest_root: Path, paper_id: str) -> list[Path]:
    """Earlier exported folders of the run that may go: never the newest, never a published or amended one."""
    mine = exports_of(dest_root, paper_id)
    return [d for d in mine[:-1] if not is_kept(d)]


def remove_older_copies(dest_root: Path, paper_id: str) -> list[str]:
    """Remove :func:`older_copies` (and the registry-entry folder an older e2er made next to each)."""
    removed: list[str] = []
    index = _read_index(Path(dest_root))
    for d in older_copies(dest_root, paper_id):
        shutil.rmtree(d, ignore_errors=True)
        entry = d.parent / f"{d.name}-registry-entry"
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        index.pop(d.name, None)
        removed.append(d.name)
    if removed:
        _write_index(Path(dest_root), index)
    return removed
