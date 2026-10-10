"""What a study uses, in the dashboard.

* New study: the papers to choose from (a fragment loaded after the page, since
  reading a few hundred PDFs for their titles takes a moment the first time);
  the data files are listed on the page itself (src/api/app.py, ``new.html``).
* The run page: the "Data and papers" panel, read from the study's folder: the
  files chosen, the tables of ``data.db`` with their rows and where each came
  from, the researcher's papers and the papers found on the web.
* The finish page: "Data used" and the references the paper cites, each marked
  "from your papers" or "found on the web".
* The Library page: "Add papers", the same importer as ``e2er library add``.

Everything that lists files of this computer needs the local session (see
local_session.py); without it the fragment says so in a sentence.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..core import labels
from ..logging_config import get_logger
from ..modules.literature.discovery import WEB_SEARCH_FILE
from .local_session import local_problem, require_local_session

logger = get_logger(__name__)
router = APIRouter()


# ── reading a study's folder ────────────────────────────────────────────────


def _loads(workspace: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads((workspace / "data_sources.json").read_text(encoding="utf-8"))
        loads = data.get("loads") if isinstance(data, dict) else None
        return [x for x in loads if isinstance(x, dict)] if isinstance(loads, list) else []
    except (OSError, ValueError):
        return []


def _bib_entries(workspace: Path) -> dict[str, dict[str, Any]]:
    from ..core.pipeline.verify_citations import load_bib

    for name in ("literature.bib", "refs.bib"):
        entries = load_bib(workspace / name)
        if entries:
            return entries
    return {}


def _cited(workspace: Path) -> list[str] | None:
    """The keys the paper cites, in order (None before there is a draft)."""
    from ..core.pipeline.verify_citations import parse_cite_keys

    for name in ("paper_draft.tex", "paper.tex"):
        p = workspace / name
        if p.is_file():
            try:
                return parse_cite_keys(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                return None
    return None


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("{", "").replace("}", "").split())


def _title(fields: dict[str, Any]) -> str:
    """A bibliography entry's title as the pages show it (src/core/titles.py)."""
    from ..core.titles import display_title

    return display_title(str(fields.get("title") or ""), str(fields.get("doi") or ""))


def _authors(value: Any, n: int = 2) -> str:
    names = [_clean(a) for a in str(value or "").split(" and ") if a.strip()]
    lasts = [a.split(",")[0] if "," in a else a.split()[-1] for a in names if a]
    return ", ".join(lasts[:n]) + (" et al." if len(lasts) > n else "")


def inputs_view(workspace: Path) -> dict[str, Any]:
    """What the study uses, read from its folder: the choice, the tables, the bibliography."""
    from ..core.specialists.contract_check import table_row_counts
    from ..core.study_inputs import read_record, section
    from ..modules.literature.models import SOURCE_FIELD

    workspace = Path(workspace)
    record = read_record(workspace)
    data = section(record, "data")
    papers = section(record, "papers")
    files = [
        {
            "name": str(f.get("name") or ""),
            "origin": labels.data_origin(str(f.get("origin") or "folder")),
            "size": int(f.get("size") or 0),
        }
        for f in data.get("files") or []
        if isinstance(f, dict) and f.get("name")
    ]
    try:
        counts = table_row_counts(workspace)
    except Exception:  # noqa: BLE001 — a data.db being written must not break the page
        counts = {}
    source_of: dict[str, str] = {}
    for load in _loads(workspace):
        name = labels.data_connector(str(load.get("connector") or ""))
        what = name + (f" ({load['series']})" if load.get("series") else "")
        for t in [load.get("table"), *(load.get("tables") or [])]:
            if t:
                source_of.setdefault(str(t), what)
    # A table no load recorded was made by the study's own code (a panel built from the others).
    tables = [
        {"table": t, "rows": n, "source": source_of.get(t, "made by the study")} for t, n in sorted(counts.items())
    ]

    entries = _bib_entries(workspace)
    items = {str(i.get("key")): i for i in papers.get("items") or [] if isinstance(i, dict) and i.get("key")}
    mine: list[dict[str, Any]] = []
    web: list[dict[str, Any]] = []
    for key, f in entries.items():
        row: dict[str, Any] = {
            "key": key,
            "title": _title(f),
            "authors": _authors(f.get("author")),
            "year": _clean(f.get("year")),
        }
        if f.get(SOURCE_FIELD) == "researcher":
            item = items.get(key) or {}
            row["kind"] = labels.paper_kind(str(item.get("kind") or "")) if item.get("kind") else ""
            row["origin"] = labels.paper_origin(str(item.get("origin") or "folder"))
            row["pdf"] = bool(item.get("pdf"))
            mine.append(row)
        else:
            web.append(row)
    cited = _cited(workspace)
    # The web papers the draft cites first; the others are folded (a search finds more than a paper uses).
    cited_set = set(cited or [])
    web_cited = sorted((w for w in web if w["key"] in cited_set), key=lambda w: (cited or []).index(w["key"]))
    web_other = [w for w in web if w["key"] not in cited_set]
    try:
        search = json.loads((workspace / "literature" / WEB_SEARCH_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        search = {}
    references = []
    for key in cited or []:
        cited_entry = entries.get(key)
        if cited_entry is None:
            continue
        f = cited_entry
        references.append(
            {
                "key": key,
                "title": _title(f),
                "authors": _authors(f.get("author")),
                "year": _clean(f.get("year")),
                "source": labels.reference_source(str(f.get(SOURCE_FIELD) or "")),
                "mine": f.get(SOURCE_FIELD) == "researcher",
            }
        )
    return {
        "recorded": bool(record),
        "data_chosen": bool(data.get("chosen")),
        "files": files,
        "tables": tables,
        "papers_chosen": bool(papers.get("chosen")),
        "web_search": papers.get("web_search", True) is not False,
        "prepared": "items" in papers or bool(entries),
        "mine": mine,
        "web": web,
        "web_cited": web_cited,
        "web_other": web_other,
        "web_left_out": int(search.get("left_out_count") or 0) if isinstance(search, dict) else 0,
        "missing": [str(m) for m in papers.get("missing") or []],
        "cited": cited,
        "references": references,
        "loads": [
            {
                "source": labels.data_connector(str(x.get("connector") or "")),
                "what": str(x.get("series") or x.get("dataset") or ""),
                "sha256": next((str(f.get("sha256")) for f in x.get("files") or [] if isinstance(f, dict)), ""),
                "uploaded": str(x.get("dataset") or "").startswith("Added by the researcher"),
            }
            for x in _loads(workspace)
        ],
    }


async def _workspace_of(paper_id: str) -> Path | None:
    import uuid

    from ..db.client import fetch_one

    try:
        uuid.UUID(paper_id)
    except ValueError:
        return None
    row = await fetch_one("SELECT workspace, status FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not row or not row.get("workspace"):
        return None
    return Path(str(row["workspace"]))


@router.get("/htmx/papers/{paper_id}/inputs", response_class=HTMLResponse)
async def inputs_panel(request: Request, paper_id: str) -> Any:
    """The run page's "Data and papers" panel."""
    from .app import templates

    problem = local_problem(request)
    workspace = await _workspace_of(paper_id)
    # Read off the event loop: the live panel beside it must not wait for this one.
    view = (
        await asyncio.to_thread(inputs_view, workspace)
        if workspace is not None and workspace.is_dir() and not problem
        else None
    )
    return templates.TemplateResponse(
        request, "_inputs_panel.html", {"v": view, "problem": problem, "paper_id": paper_id}
    )


# ── New study: the papers to choose from ────────────────────────────────────


def paper_choices(settings: Any, chosen: list[str] | None) -> dict[str, Any]:
    """The papers New study offers. Ticked by default: the literature folder and the .bib files, as before
    0.15.0 every study took them; the Library's papers are offered unticked."""
    from ..core.study_inputs import paper_options

    try:
        options = paper_options(settings)
    except Exception as e:  # noqa: BLE001 — a broken folder must not break New study
        logger.warning("New study: the papers could not be listed: %s", e)
        options = []
    rows = []
    for o in options:
        ticked = (o.id in chosen) if chosen is not None else o.kind != "library"
        rows.append(
            {
                **o.to_dict(),
                "authors_text": ", ".join(a.split(",")[0] if "," in a else a for a in o.authors[:3])
                + (" et al." if len(o.authors) > 3 else ""),
                "kind_label": labels.paper_kind(o.kind),
                "ticked": ticked,
            }
        )
    # The folder's papers and the .bib entries first; the Library in a group of its own.
    return {
        "papers": [r for r in rows if r["kind"] != "library"],
        "library": [r for r in rows if r["kind"] == "library"],
        "literature_dir": settings.resolved_literature_dirs() or "",
        "bib_file": settings.literature_bibtex_file or "",
    }


@router.get("/htmx/new/papers", response_class=HTMLResponse)
async def new_study_papers(request: Request, chosen: list[str] | None = None, picked: str = "") -> Any:
    from ..config import get_settings
    from .app import templates

    problem = local_problem(request)
    view = (
        await asyncio.to_thread(paper_choices, get_settings(), list(chosen or []) if picked else None)
        if not problem
        else {}
    )
    return templates.TemplateResponse(request, "_paper_choices.html", {**view, "problem": problem})


# ── the Library: Add papers ─────────────────────────────────────────────────

#: The one Library import running from the dashboard: what it is reading and how far it got.
_ADDING: dict[str, Any] = {}


def _library_target_folder() -> Path:
    from ..home import state_dir

    return state_dir() / "library-pdfs"


async def _add_to_library(target: str, label: str, cleanup: Path | None = None) -> None:
    """``e2er library add <target>`` in the background, reporting progress on the Library page."""
    from ..modules.literature import corpus
    from ..modules.literature.ingest import ingest_papers, papers_for_target

    _ADDING.clear()
    _ADDING.update({"label": label, "done": 0, "total": 0, "stored": 0, "skipped": 0, "failed": 0, "finished": False})

    def on_event(event: str, _label: str, _detail: str) -> None:
        _ADDING["done"] += 1
        if event == "stored":
            _ADDING["stored"] += 1
        elif event == "skip":
            _ADDING["skipped"] += 1
        else:
            _ADDING["failed"] += 1

    try:
        papers = await papers_for_target(target, limit=None, search=False)
        _ADDING["total"] = len(papers)
        if papers:
            with corpus.connect(None) as conn:
                await ingest_papers(conn, papers, skip_known=True, on_event=on_event)
    except Exception as e:  # noqa: BLE001 — the page reports it, the server keeps running
        logger.warning("Library: adding %s failed: %s", target, e)
        _ADDING["error"] = str(e)[:300]
    finally:
        _ADDING["finished"] = True
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)


@router.post("/library/add", dependencies=[Depends(require_local_session)])
async def library_add(request: Request) -> Any:
    """Add PDFs (uploaded, or a folder on this computer) to the Library."""
    import uuid

    form = await request.form()
    folder = str(form.get("folder") or "").strip()
    uploads = [f for f in form.getlist("pdf") if not isinstance(f, str) and f.filename]

    def back(note: str) -> RedirectResponse:
        return RedirectResponse(url=f"/library?message={quote_plus(note)}", status_code=303)

    if _ADDING and not _ADDING.get("finished"):
        return back("e2er is still adding the papers from before. Add these when it has finished.")
    if uploads:
        dest = _library_target_folder() / uuid.uuid4().hex[:12]
        dest.mkdir(parents=True, exist_ok=True)
        names = []
        for f in uploads:
            name = Path(str(f.filename)).name
            if Path(name).suffix.lower() != ".pdf":
                shutil.rmtree(dest, ignore_errors=True)
                return back(f"{name} is not a PDF. The Library reads PDFs.")
            with (dest / name).open("wb") as out:
                while chunk := await f.read(1024 * 1024):  # type: ignore[union-attr]
                    out.write(chunk)
            names.append(name)
        # The PDFs stay in ~/.e2er/library-pdfs: the Library keeps what it read, and the file to read again.
        asyncio.get_running_loop().create_task(_add_to_library(str(dest), f"{len(names)} PDF(s)"))
        return back(f"Reading {len(names)} PDF(s) into the Library. They appear below as they are read.")
    if folder:
        path = Path(folder).expanduser()
        if not path.is_dir():
            return back(f"{folder} is not a folder on this computer.")
        asyncio.get_running_loop().create_task(_add_to_library(str(path), path.name))
        return back(f"Reading the PDFs in {path} into the Library. They appear below as they are read.")
    return back("Choose PDFs or name a folder first.")


@router.get("/htmx/library/adding", response_class=HTMLResponse)
async def library_adding(request: Request) -> Any:
    from .app import templates

    return templates.TemplateResponse(request, "_library_adding.html", {"a": dict(_ADDING)})
