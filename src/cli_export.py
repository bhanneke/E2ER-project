"""`e2er export <paper_id> [--to DIR]` — assemble a structured project folder.

On-demand / re-export counterpart to the runner's auto-export at terminal
status. Each invocation produces a fresh versioned folder (``…-NN``).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def _recorded_template(paper_id: str) -> str | None:
    """The template the study was run with, from its papers row (None when the database has no row)."""
    import asyncio

    from .db.client import fetch_one

    try:
        row = asyncio.run(fetch_one("SELECT pipeline FROM papers WHERE id = %(id)s", {"id": paper_id}))
    except Exception:  # noqa: BLE001 — no database: fall back to manifest.json
        return None
    return str(row["pipeline"]) if row and row.get("pipeline") else None


class ExportLookupError(Exception):
    """The paper id could not be resolved to one workspace. The message is shown as is."""


def _paper_rows() -> list[dict]:
    import asyncio

    from .db.client import fetch_all

    try:
        return list(asyncio.run(fetch_all("SELECT id, workspace FROM papers")) or [])
    except Exception:  # noqa: BLE001 — no database: only the workspace folder can answer
        return []


def expand_paper_id(ref: str) -> str:
    """The full paper id for a unique prefix of it (4+ characters); else ``ref`` unchanged.

    `e2er status`, `review`, `resume`, `cancel` and `rerun` take the id the way
    `export` and `archive` do: the first characters suffice. A prefix that matches
    several papers raises ExportLookupError.
    """
    ref = ref.strip()
    if len(ref) < 4:
        return ref
    ids = [str(r.get("id", "")) for r in _paper_rows()]
    if ref in ids:
        return ref
    hits = [i for i in ids if i.startswith(ref.casefold())]
    if len(hits) > 1:
        raise ExportLookupError(f"{ref!r} matches {len(hits)} papers; give more of the id.")
    return hits[0] if hits else ref


def _study_latest_run(key: str) -> tuple[str, str] | None:
    """(run id, plain note) of the latest run of the study ``key`` (as `e2er list` shows it), else None."""
    import asyncio

    from .db import studies as st

    try:
        studies = asyncio.run(st.load())
    except Exception:  # noqa: BLE001 — no database: the key cannot be looked up
        return None
    study = studies.get(key)
    if study is None or not study.attempts:
        return None
    latest = study.latest() or study.latest(show_archived=True)
    if latest is None:  # pragma: no cover — a study has at least one attempt
        return None
    runs = len(study.attempts)
    which = "its only run" if runs == 1 else f"its latest run (v{latest['version']} of {runs})"
    return latest["id"], f"Study {study.key}: {which} is {latest['short_id']}."


#: A study key as `e2er list` prints it (10 hex characters; a run id has a dash after 8).
_STUDY_KEY = re.compile(r"[0-9a-f]{10}")


def expand_paper_ref(ref: str) -> tuple[str, str]:
    """The run id for a run id, a unique prefix of one, or a study key; and a note when it was a study key.

    `e2er list` prints each study's key (``b33f3ad47b``); `e2er status`, `cancel`,
    `resume`, `review` and `rerun` take it and act on the study's latest run. A
    key never collides with a run id prefix: a run id has a dash after 8 characters.
    """
    ref = ref.strip()
    if _STUDY_KEY.fullmatch(ref.casefold()):
        found = _study_latest_run(ref.casefold())
        if found is not None:
            return found
    return expand_paper_id(ref), ""


def resolve_workspace(ref: str, settings) -> tuple[str, Path]:
    """(paper id, workspace folder) for a full paper id or a unique prefix (4+ characters).

    The workspace recorded in the database comes first, so the command works from
    any folder; a relative record (older runs stored ``workspaces/<id>``) and the
    configured ``WORKSPACE_ROOT`` are tried after it.
    """
    ref = ref.strip()
    rows = _paper_rows()
    hits = [r for r in rows if str(r.get("id")) == ref]
    if not hits and len(ref) >= 4:
        hits = [r for r in rows if str(r.get("id", "")).startswith(ref.casefold())]
    if len(hits) > 1:
        raise ExportLookupError(f"{ref!r} matches {len(hits)} papers; give more of the id.")
    paper_id = str(hits[0]["id"]) if hits else ref
    root = Path(settings.workspace_root).expanduser()
    candidates: list[Path] = []
    stored = str(hits[0].get("workspace") or "") if hits else ""
    if stored:
        candidates.append(Path(stored).expanduser())
    from .home import find_workspace

    candidates.append(find_workspace(paper_id, root))
    if not hits and len(ref) >= 4 and root.is_dir():
        # No database row: a unique prefix among the workspace folders.
        folders = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(ref)]
        if len(folders) > 1:
            raise ExportLookupError(f"{ref!r} matches {len(folders)} workspaces in {root}; give more of the id.")
        if folders:
            paper_id = folders[0].name
            candidates.append(folders[0])
    for c in candidates:
        if c.is_dir():
            return paper_id, c.resolve()
    looked = ", ".join(str(c) for c in dict.fromkeys(candidates))
    if not hits:
        raise ExportLookupError(
            f"no paper {ref!r} in the database ({len(rows)} paper(s) recorded) and no workspace at {looked}. "
            "Run the command from the study's folder (where its .env is), or check the id with `e2er list --attempts`."
        )
    raise ExportLookupError(
        f"paper {paper_id} is recorded, but its workspace is not at {looked}. "
        "Run the command from the folder the study was started in, or set WORKSPACE_ROOT to the folder "
        "that holds the workspaces."
    )


def export(paper_id: str, to: str | None = None, *, package: bool = False) -> int:
    from .config import get_settings
    from .core.export.structured import export_paper

    settings = get_settings()
    try:
        paper_id, workspace = resolve_workspace(paper_id, settings)
    except ExportLookupError as e:
        print(f"error: {e}")
        return 1

    dest_root = Path(to).expanduser() if to else settings.resolved_output_root()
    date_str = datetime.now().strftime("%Y%m%d")
    try:
        out = export_paper(
            workspace, dest_root, date_str=date_str, template=_recorded_template(paper_id), paper_id=paper_id
        )
    except Exception as e:  # noqa: BLE001
        print(f"error: export failed: {e}")
        return 1
    print(f"Exported → {out}")
    if package:
        from .cli_package import pack_folder

        return pack_folder(out, None, offline=False, no_data=False)
    return 0
