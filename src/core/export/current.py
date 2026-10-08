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
* the newest folder was published: it stays as it is, and a new folder is made.

What "changed" means is a fingerprint of the run's working folder (every file's
path, size and modification time), kept for each exported folder in
``<exports>/.e2er-exports.json``. A published folder (``.e2er/link.json``) is
never removed: :func:`remove_older_copies` removes the other earlier copies on
request.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def exports_of(dest_root: Path, paper_id: str) -> list[Path]:
    """The exported folders of one run, oldest first (their provenance.json names the run)."""
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
    return sorted(found, key=lambda p: (p.stat().st_mtime, p.name))


def is_published(folder: Path) -> bool:
    return (Path(folder) / ".e2er" / "link.json").is_file()


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
    still current), ``replaced`` (the newest folder was rewritten in place) or
    ``new`` (a new folder; the newest one was published, or there was none).
    """
    from .structured import export_paper

    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    fingerprint = workspace_fingerprint(Path(workspace))
    index = _read_index(dest_root)
    mine = exports_of(dest_root, paper_id)
    latest = mine[-1] if mine else None
    if latest is not None and (index.get(latest.name) or {}).get("fingerprint") == fingerprint:
        return latest, "unchanged"
    if latest is not None and not is_published(latest):
        name = latest.name
        shutil.rmtree(latest)
        out = export_paper(workspace, dest_root, date_str=date_str, slug=name, template=template)
        state = "replaced"
    else:
        out = export_paper(workspace, dest_root, date_str=date_str, template=template)
        state = "new"
    index = _read_index(dest_root)
    index[out.name] = {"paper_id": paper_id, "fingerprint": fingerprint}
    _write_index(dest_root, index)
    return out, state


def older_copies(dest_root: Path, paper_id: str) -> list[Path]:
    """Earlier exported folders of the run that may go: never the newest, never a published one."""
    mine = exports_of(dest_root, paper_id)
    return [d for d in mine[:-1] if not is_published(d)]


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
