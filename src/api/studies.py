"""Studies in the dashboard: the list, one study's attempts, archiving, moving.

A study is the group of attempts at one research question under one template
(src/db/studies.py). The list shows one row per study; a study's page shows
its attempts as versions.

The endpoints that change something (archive, unarchive, move) and the JSON
reads need the local session (see local_session.py), like every other part of
the dashboard that acts on the researcher's data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..db import studies as st
from ..logging_config import get_logger
from .local_session import require_local_session

logger = get_logger(__name__)
router = APIRouter()

_GUARD = [Depends(require_local_session)]


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _study_view(s: st.Study, show_archived: bool) -> dict[str, Any]:
    return {**s.as_dict(show_archived), "has_archived": bool(s.archived)}


# ── pages ────────────────────────────────────────────────────────────────────


async def studies_page(request: Request, q: str = "", archived: str | None = None) -> Any:
    """The landing page: one row per study. Called by the `/` route in app.py."""
    from .app import templates

    show_archived = _flag(archived)
    try:
        rows, n_archived = await st.list_studies(q, show_archived)
        studies = [_study_view(s, show_archived) for s in rows]
        n_attempts = sum(s["attempts"] for s in studies)
    except Exception as e:  # noqa: BLE001 — an unreachable DB renders an empty list
        logger.warning("studies list: DB unavailable (%s) — rendering empty list", e)
        studies, n_archived, n_attempts = [], 0, 0
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "studies": studies,
            "q": q,
            "show_archived": show_archived,
            "n_archived": n_archived,
            "n_attempts": n_attempts,
        },
    )


@router.get("/studies/{key}", response_class=HTMLResponse)
async def study_page(request: Request, key: str, archived: str | None = None) -> Any:
    from .app import templates

    show_archived = _flag(archived)
    try:
        study = await st.resolve_study(key)
    except st.StudyError as e:
        raise HTTPException(status_code=404, detail="Study not found") from e
    all_studies, _ = await st.list_studies("", show_archived=True)
    others = [{"key": o.key, "title": o.title, "template": o.template} for o in all_studies if o.key != study.key]
    attempts = list(reversed(study.shown(show_archived)))  # newest first
    return templates.TemplateResponse(
        request,
        "study.html",
        {
            "study": _study_view(study, show_archived),
            "attempts": attempts,
            "show_archived": show_archived,
            "others": others,
        },
    )


# ── JSON ─────────────────────────────────────────────────────────────────────


@router.get("/api/studies", dependencies=_GUARD)
async def api_studies(q: str = "", archived: str | None = None) -> dict[str, Any]:
    show_archived = _flag(archived)
    rows, n_archived = await st.list_studies(q, show_archived)
    return {"studies": [_study_view(s, show_archived) for s in rows], "archived_attempts": n_archived}


@router.get("/api/studies/{key}", dependencies=_GUARD)
async def api_study(key: str) -> dict[str, Any]:
    try:
        study = await st.resolve_study(key)
    except st.StudyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"study": _study_view(study, True), "attempts": study.attempts}


def _refused(e: st.StudyError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(e))


@router.post("/api/papers/{paper_id}/archive", dependencies=_GUARD)
async def api_archive_attempt(paper_id: str) -> dict[str, Any]:
    try:
        a = await st.archive_attempt(paper_id)
    except st.StudyError as e:
        raise _refused(e) from e
    return {"archived": 1, "id": a["id"], "message": f"Archived v{a['version']}. Nothing was deleted."}


@router.post("/api/papers/{paper_id}/unarchive", dependencies=_GUARD)
async def api_unarchive_attempt(paper_id: str) -> dict[str, Any]:
    try:
        a = await st.unarchive_attempt(paper_id)
    except st.StudyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"unarchived": 1, "id": a["id"]}


@router.post("/api/studies/{key}/archive", dependencies=_GUARD)
async def api_archive_study(key: str) -> dict[str, Any]:
    try:
        study, n = await st.archive_study(key)
    except st.StudyError as e:
        raise _refused(e) from e
    return {"archived": n, "key": study.key, "message": f"Archived {n} attempt{'s' if n != 1 else ''}."}


@router.post("/api/studies/{key}/unarchive", dependencies=_GUARD)
async def api_unarchive_study(key: str) -> dict[str, Any]:
    try:
        study, n = await st.unarchive_study(key)
    except st.StudyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"unarchived": n, "key": study.key}


@router.get("/api/archive/failed", dependencies=_GUARD)
async def api_failed_preview() -> dict[str, Any]:
    """What the bulk action would archive, shown before the researcher confirms."""
    items = await st.failed_candidates()
    return {
        "count": len(items),
        "attempts": [
            {k: a[k] for k in ("id", "short_id", "status", "version", "study_title", "study_key", "created_at")}
            for a in items
        ],
    }


class BulkArchive(BaseModel):
    ids: list[str]


@router.post("/api/archive/failed", dependencies=_GUARD)
async def api_archive_failed(body: BulkArchive) -> dict[str, Any]:
    """Archive the failed and cancelled attempts the researcher confirmed (by id)."""
    done = await st.archive_failed(body.ids)
    return {"archived": len(done), "ids": [a["id"] for a in done]}


class MoveRequest(BaseModel):
    study: str  # a study key, an attempt id, or "new"


@router.post("/api/papers/{paper_id}/move", dependencies=_GUARD)
async def api_move_attempt(paper_id: str, body: MoveRequest) -> dict[str, Any]:
    try:
        dest = await st.move_attempt(paper_id, body.study)
    except st.StudyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"id": paper_id, "study": dest}
