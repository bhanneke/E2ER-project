"""FastAPI application — REST API for E2ER v3 pipeline."""

from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import tarfile
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..config import get_settings
from ..logging_config import get_logger


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Bearer-token auth for mutating endpoints.

    No-op when `api_auth_token` is unset (dev mode). When set, requires
    `Authorization: Bearer <token>` and returns 401 on mismatch.
    """
    # getattr keeps test stubs of get_settings() that omit this field working;
    # treat missing field as "auth disabled" (dev default).
    expected = getattr(get_settings(), "api_auth_token", None)
    if not expected:
        return  # auth disabled in dev
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    presented = authorization[len("Bearer ") :].strip()
    if presented != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


_API_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _API_DIR / "static"
_TEMPLATES_DIR = _API_DIR / "templates"

logger = get_logger(__name__)
app = FastAPI(title="E2ER v3", version="3.0.0", description="End-to-End Researcher pipeline API")

_cors_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# Server-rendered dashboard. Static files (htmx, css) and Jinja2 templates.
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Registry of running pipeline tasks, keyed by paper_id.
# Used by POST /api/papers/{id}/cancel to cancel an in-flight run.
_RUNNING: dict[str, asyncio.Task] = {}


@app.on_event("startup")
async def _log_config() -> None:
    s = get_settings()
    logger.info(
        "E2ER v3 starting | backend=%s model=%s data=%s lit_kb=%s github=%s default_cap=$%.2f",
        s.llm_backend,
        s.default_model,
        "on" if s.data_module_enabled else "off",
        "on" if s.literature_kb_enabled else "off",
        "on" if s.github_enabled else "off",
        s.default_max_cost_usd,
    )


# --- Request/Response Models ---


class CreatePaperRequest(BaseModel):
    title: str
    research_question: str
    datasets: list[str] = []
    mode: str = "iterative"
    methodology: str = "empirical"  # empirical | theoretical | mixed
    bibtex_path: str | None = None
    max_cost_usd: float | None = None  # falls back to settings.default_max_cost_usd


class PaperResponse(BaseModel):
    paper_id: str
    title: str
    status: str
    workspace: str


class ApprovalAction(BaseModel):
    approved: bool
    note: str = ""


# --- Paper endpoints ---


@app.post("/api/papers", response_model=PaperResponse, dependencies=[Depends(require_auth)])
async def create_paper(req: CreatePaperRequest, background_tasks: BackgroundTasks):
    """Create a new paper and start the pipeline."""
    import uuid

    from ..db.client import execute

    paper_id = str(uuid.uuid4())
    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    workspace.mkdir(parents=True, exist_ok=True)

    if req.methodology not in {"empirical", "theoretical", "mixed"}:
        raise HTTPException(
            status_code=400,
            detail=f"methodology must be one of empirical|theoretical|mixed, got {req.methodology!r}",
        )

    manifest = {
        "paper_id": paper_id,
        "title": req.title,
        "research_question": req.research_question,
        "datasets": req.datasets,
        "mode": req.mode,
        "methodology": req.methodology,
        "current_stage": "idea",
    }
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))

    cap = req.max_cost_usd if req.max_cost_usd is not None else settings.default_max_cost_usd
    try:
        await execute(
            """
            INSERT INTO papers (id, title, research_question, status, workspace, mode, methodology, max_cost_usd)
            VALUES (%(id)s, %(title)s, %(rq)s, 'idea', %(ws)s, %(mode)s, %(methodology)s, %(cap)s)
            """,
            {
                "id": paper_id,
                "title": req.title,
                "rq": req.research_question,
                "ws": str(workspace),
                "mode": req.mode,
                "methodology": req.methodology,
                "cap": cap,
            },
        )
    except Exception as e:
        logger.warning("Could not persist paper to DB: %s", e)

    if settings.github_enabled:
        background_tasks.add_task(_create_github_repo, paper_id, req.title)

    # Use asyncio.create_task (not BackgroundTasks) so we get a handle for cancel.
    task = asyncio.create_task(_run_pipeline(paper_id, workspace, req.mode, cap))
    _RUNNING[paper_id] = task
    task.add_done_callback(lambda _t: _RUNNING.pop(paper_id, None))

    return PaperResponse(
        paper_id=paper_id,
        title=req.title,
        status="idea",
        workspace=str(workspace),
    )


@app.get("/api/papers")
async def list_papers() -> list[dict[str, Any]]:
    from ..db.client import fetch_all

    try:
        return await fetch_all("SELECT id, title, status, created_at FROM papers ORDER BY created_at DESC LIMIT 50")
    except Exception as e:
        logger.warning("list_papers DB read failed; returning empty list: %s", e)
        return []


@app.get("/api/papers/{paper_id}")
async def get_paper(paper_id: str) -> dict[str, Any]:
    from ..db.client import fetch_one

    row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        usage = await fetch_one(
            """
            SELECT
                COUNT(*)::int           AS specialist_calls,
                COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens), 0)::bigint AS total_tokens,
                COALESCE(SUM(cost_usd), 0)::numeric AS total_cost_usd
            FROM llm_usage WHERE paper_id = %(id)s
            """,
            {"id": paper_id},
        )
        return {**row, "usage": usage or {}}
    except Exception as e:
        logger.warning("get_paper usage fetch failed for paper_id=%s: %s", paper_id, e)
        return {**row, "usage": {}}


@app.get("/api/papers/{paper_id}/artifacts")
async def list_artifacts(paper_id: str) -> dict[str, Any]:
    from ..config import get_settings

    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    files = [str(f.relative_to(workspace)) for f in workspace.rglob("*") if f.is_file() and not f.name.startswith(".")]
    return {"paper_id": paper_id, "files": files}


@app.post("/api/papers/{paper_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_paper(paper_id: str) -> dict[str, Any]:
    """Cancel an in-flight pipeline run. The runner's CancelledError handler
    will save state and mark the paper as cancelled in the DB."""
    task = _RUNNING.get(paper_id)
    if not task or task.done():
        raise HTTPException(status_code=404, detail="No running task for this paper")
    task.cancel()
    return {"status": "cancelling", "paper_id": paper_id}


@app.get("/api/papers/{paper_id}/audit-bundle")
async def audit_bundle(paper_id: str) -> StreamingResponse:
    """Download a tarball with everything needed to verify the paper's provenance:
    replication/, contributions.json, events.json, usage.json, manifest.json.
    """
    from ..db.client import fetch_all, fetch_one
    from ..modules.tracking.usage import get_paper_usage as _get_usage

    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    paper_row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not paper_row:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Pull DB-side audit data (best-effort; missing pieces just become empty).
    try:
        contributions = await fetch_all(
            """
            SELECT specialist, output_file, success, error_msg, usage_tokens,
                   cost_usd, duration_sec, created_at
            FROM contributions WHERE paper_id = %(p)s ORDER BY created_at
            """,
            {"p": paper_id},
        )
    except Exception as e:
        logger.warning("audit-bundle contributions fetch failed for %s: %s", paper_id, e)
        contributions = []
    try:
        events = await fetch_all(
            """
            SELECT event_type, stage, specialist, payload, created_at
            FROM pipeline_events WHERE paper_id = %(p)s ORDER BY created_at
            """,
            {"p": paper_id},
        )
    except Exception as e:
        logger.warning("audit-bundle events fetch failed for %s: %s", paper_id, e)
        events = []
    try:
        usage = await _get_usage(paper_id)
    except Exception as e:
        logger.warning("audit-bundle usage fetch failed for %s: %s", paper_id, e)
        usage = {}

    manifest = {
        "paper_id": paper_id,
        "title": paper_row.get("title"),
        "research_question": paper_row.get("research_question"),
        "status": paper_row.get("status"),
        "max_cost_usd": float(paper_row["max_cost_usd"]) if paper_row.get("max_cost_usd") is not None else None,
        "last_error": paper_row.get("last_error"),
        "github_repo": paper_row.get("github_repo"),
        "created_at": str(paper_row.get("created_at")),
    }

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # JSON-rendered DB records
        for name, blob in [
            ("manifest.json", json.dumps(manifest, indent=2, default=str)),
            ("contributions.json", json.dumps(contributions, indent=2, default=str)),
            ("events.json", json.dumps(events, indent=2, default=str)),
            ("usage.json", json.dumps(usage, indent=2, default=str)),
        ]:
            data = blob.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        # Workspace files (replication subtree + any top-level audit artefacts).
        for sub in ("replication", "audit_log.csv", "data_queries.sql"):
            path = workspace / sub
            if path.exists():
                tar.add(path, arcname=sub)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="audit-bundle-{paper_id}.tar.gz"'},
    )


# --- Data approval endpoints ---


@app.get("/api/papers/{paper_id}/pending-queries")
async def get_pending_queries(paper_id: str) -> list[dict[str, Any]]:
    from ..db.client import fetch_all

    try:
        return await fetch_all(
            """
            SELECT dqr.id, dqr.query_sql, dqr.query_type, dqr.fields_requested,
                   dqr.aggregation_level, dqr.estimated_rows, dqr.created_at,
                   dar.id AS approval_request_id, dar.status AS approval_status
            FROM data_query_records dqr
            JOIN data_approval_requests dar ON dar.query_record_id = dqr.id
            WHERE dqr.paper_id = %(pid)s AND dar.status = 'pending'
            ORDER BY dqr.created_at
            """,
            {"pid": paper_id},
        )
    except Exception as e:
        logger.error("pending-queries fetch failed for paper_id=%s: %s", paper_id, e)
        raise HTTPException(status_code=500, detail="failed to fetch pending queries; check server logs")


@app.post("/api/queries/{query_id}/approve", dependencies=[Depends(require_auth)])
async def approve_query(query_id: str, action: ApprovalAction):
    from ..db.client import execute

    try:
        if action.approved:
            await execute(
                "UPDATE data_approval_requests SET status = 'approved', reviewed_at = NOW(), "
                "note = %(note)s WHERE query_record_id = %(id)s",
                {"id": query_id, "note": action.note},
            )
            await execute(
                "UPDATE data_query_records SET validation_status = 'approved', "
                "approved_by = 'researcher' WHERE id = %(id)s",
                {"id": query_id},
            )
        else:
            await execute(
                "UPDATE data_approval_requests SET status = 'rejected', reviewed_at = NOW(), "
                "note = %(note)s WHERE query_record_id = %(id)s",
                {"id": query_id, "note": action.note},
            )
    except Exception as e:
        # A silent DB failure here would tell the LLM "approved" while the row
        # is still pending — and the next check_approval poll would surface
        # the contradiction. Fail loudly instead.
        logger.error("approve_query DB write failed for query_id=%s: %s", query_id, e)
        raise HTTPException(status_code=500, detail="approval write failed; check server logs")
    return {"status": "approved" if action.approved else "rejected", "query_id": query_id}


# --- Usage tracking endpoints ---


@app.get("/api/papers/{paper_id}/usage")
async def get_paper_usage(paper_id: str) -> dict[str, Any]:
    from ..modules.tracking.usage import get_paper_usage

    return await get_paper_usage(paper_id)


@app.get("/api/usage/summary")
async def get_usage_summary() -> dict[str, Any]:
    from ..modules.tracking.usage import get_usage_summary

    return await get_usage_summary()


# --- Health ---


@app.get("/health")
async def health():
    return {"status": "ok", "service": "e2er-v3"}


# --- Dashboard (Jinja2 + HTMX) ---

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@app.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request) -> Any:
    """Papers list — landing page."""
    from ..db.client import fetch_all

    try:
        rows = await fetch_all(
            """
            SELECT p.id, p.title, p.status, p.max_cost_usd, p.updated_at,
                   COALESCE((SELECT SUM(cost_usd) FROM llm_usage WHERE paper_id = p.id), 0) AS cost
            FROM papers p
            ORDER BY p.updated_at DESC
            LIMIT 100
            """
        )
    except Exception as e:
        logger.warning("dashboard_index: DB unavailable (%s) — rendering empty list", e)
        rows = []
    # Stringify timestamps for templating.
    for r in rows or []:
        if r.get("updated_at") is not None:
            r["updated_at"] = str(r["updated_at"])[:19]
    return templates.TemplateResponse(
        request,
        "index.html",
        {"papers": rows or []},
    )


@app.get("/papers/new", response_class=HTMLResponse)
async def new_paper_form(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "new.html",
        {"default_cap": get_settings().default_max_cost_usd},
    )


@app.post("/papers")
async def submit_new_paper(
    title: str = Form(...),
    research_question: str = Form(...),
    mode: str = Form("iterative"),
    methodology: str = Form("empirical"),
    max_cost_usd: float = Form(None),
) -> RedirectResponse:
    """Form-encoded handler that mirrors POST /api/papers. Redirects to detail page.

    NOT bearer-auth-protected: browsers can't add `Authorization: Bearer ...`
    to a regular form POST. The JSON /api/papers IS auth-protected, so machine
    clients still need a token. When deploying with API_AUTH_TOKEN set, lock
    the dashboard down at the network layer (Tailscale, VPN, localhost-only
    bind) — see SECURITY.md.
    """
    req = CreatePaperRequest(
        title=title,
        research_question=research_question,
        mode=mode,
        methodology=methodology,
        max_cost_usd=max_cost_usd,
    )
    bg = BackgroundTasks()
    resp = await create_paper(req, bg)
    # FastAPI normally runs background_tasks after the response; here we manually
    # await any tasks the create_paper handler queued (github repo creation).
    await bg()
    return RedirectResponse(url=f"/papers/{resp.paper_id}", status_code=303)


@app.get("/papers/{paper_id}", response_class=HTMLResponse)
async def paper_detail(paper_id: str, request: Request) -> Any:
    """Detail page for a single paper."""
    from ..db.client import fetch_one

    paper = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Best-effort artifact list (workspace may not exist if DB-only ghost).
    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if workspace.exists():
        artifacts = sorted(
            str(f.relative_to(workspace)) for f in workspace.rglob("*") if f.is_file() and not f.name.startswith(".")
        )
    else:
        artifacts = []

    return templates.TemplateResponse(
        request,
        "paper.html",
        {"paper": paper, "artifacts": artifacts},
    )


@app.get("/htmx/papers/{paper_id}/live", response_class=HTMLResponse)
async def paper_live_fragment(paper_id: str, request: Request) -> Any:
    """HTML fragment for the live-updating section of paper.html.

    HTMX polls this every 3s. Returns status badge, cost meter, recent events,
    and a Cancel button when the paper is still in flight.
    """
    from ..db.client import fetch_all, fetch_one

    paper = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    try:
        cost_row = await fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0)::float AS spent FROM llm_usage WHERE paper_id = %(id)s",
            {"id": paper_id},
        )
        cost_spent = float((cost_row or {}).get("spent", 0.0))
    except Exception as e:
        logger.warning("live-fragment cost fetch failed for %s: %s — showing $0 (may be wrong)", paper_id, e)
        cost_spent = 0.0
    cap = float(paper.get("max_cost_usd") or 25.0)
    cost_pct = min(100.0, (cost_spent / cap * 100.0) if cap > 0 else 0.0)

    try:
        events = await fetch_all(
            """
            SELECT event_type, stage, specialist, created_at
            FROM pipeline_events
            WHERE paper_id = %(id)s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            {"id": paper_id},
        )
    except Exception as e:
        logger.warning("live-fragment events fetch failed for %s: %s", paper_id, e)
        events = []
    for e in events or []:
        if e.get("created_at") is not None:
            e["created_at_short"] = str(e["created_at"])[11:19]

    return templates.TemplateResponse(
        request,
        "_live.html",
        {
            "paper": paper,
            "cost_spent": cost_spent,
            "cost_pct": cost_pct,
            "events": events or [],
            "can_cancel": (paper.get("status") not in _TERMINAL_STATUSES) and (paper_id in _RUNNING),
        },
    )


@app.get("/api/papers/{paper_id}/events")
async def list_events(paper_id: str, since: str | None = None) -> list[dict[str, Any]]:
    """JSON event log. Optional `since=<iso8601>` filter for incremental polling."""
    from ..db.events import fetch_events

    return await fetch_events(paper_id, since=since)


@app.get("/api/papers/{paper_id}/artifacts/{path:path}")
async def stream_artifact(paper_id: str, path: str) -> FileResponse:
    """Serve a single artifact file from the paper workspace, mimetype-aware."""
    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Resolve and reject any path that escapes the workspace.
    target = (workspace / path).resolve()
    try:
        target.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    mtype, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), media_type=mtype or "application/octet-stream", filename=target.name)


# Accepted BYOD file extensions. Limits applied to keep workspace cheap to mount.
_DATA_EXT_ALLOW = {".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json", ".jsonl", ".txt"}
_DATA_FILE_MAX_BYTES = 200 * 1024 * 1024  # 200 MB per upload


@app.post("/api/papers/{paper_id}/files", dependencies=[Depends(require_auth)])
async def upload_data_file(paper_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a researcher-supplied data file into the paper's workspace/data/.

    Specialists running with `DATA_MODULE_ENABLED=false` (no Allium key) can
    use these files via the standard read_file tool — see the byod skill.
    """
    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    name = Path(file.filename or "").name  # strip any path components
    if not name:
        raise HTTPException(status_code=400, detail="filename is required")
    suffix = Path(name).suffix.lower()
    if suffix not in _DATA_EXT_ALLOW:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported extension {suffix!r}; allowed: {sorted(_DATA_EXT_ALLOW)}",
        )

    data_dir = workspace / "data"
    data_dir.mkdir(exist_ok=True)
    target = data_dir / name

    written = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > _DATA_FILE_MAX_BYTES:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"file too large (>{_DATA_FILE_MAX_BYTES // (1024 * 1024)} MB)",
                )
            out.write(chunk)
    return {"filename": name, "size": written, "path": f"data/{name}"}


# --- Background tasks ---


async def _run_pipeline(paper_id: str, workspace: Path, mode: str, max_cost_usd: float) -> None:
    from ..config import get_settings
    from ..core.strategist.runner import PipelineRunner
    from ..modules.data.tools import ALLIUM_TOOLS, DeferredAlliumToolHandler
    from ..modules.literature.tools import LITERATURE_TOOLS, LiteratureToolHandler
    from ..modules.llm.registry import get_backend

    settings = get_settings()
    backend = get_backend(settings)

    # Tools are unioned across all enabled providers; specialists' skill files
    # determine which they actually invoke.
    extra_tools: list[dict] = []
    extra_handlers: list = []

    if settings.data_module_enabled:
        extra_tools.extend(ALLIUM_TOOLS)
        if settings.allium_api_key:
            extra_handlers.append(DeferredAlliumToolHandler(paper_id, "pipeline", workspace))

    # Literature tools are always on — OpenAlex needs no API key.
    extra_tools.extend(LITERATURE_TOOLS)
    extra_handlers.append(LiteratureToolHandler(workspace))

    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=backend,
        model=settings.default_model,
        mode=mode,
        extra_tools=extra_tools,
        extra_handlers=extra_handlers,
        backend_name=settings.llm_backend,
        max_cost_usd=max_cost_usd,
    )
    await runner.run()


async def _create_github_repo(paper_id: str, title: str) -> None:
    from ..config import get_settings
    from ..modules.github.client import GitHubClient

    settings = get_settings()
    try:
        client = GitHubClient(settings.github_token, settings.github_username)
        repo_info = client.create_paper_repo(paper_id, title, private=True)
        from ..db.client import execute

        await execute(
            "UPDATE papers SET github_repo = %(repo)s WHERE id = %(id)s",
            {"repo": repo_info["repo_name"], "id": paper_id},
        )
        logger.info("Created GitHub repo %s for paper %s", repo_info["repo_name"], paper_id)
    except Exception as e:
        logger.warning("GitHub repo creation failed: %s", e)
