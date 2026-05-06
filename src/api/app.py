"""FastAPI application — REST API for E2ER v3 pipeline."""
from __future__ import annotations

import asyncio
import io
import json
import tarfile
from pathlib import Path
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)
app = FastAPI(title="E2ER v3", version="3.0.0", description="End-to-End Researcher pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    datasets: List[str] = []
    mode: str = "iterative"
    bibtex_path: Optional[str] = None
    max_cost_usd: Optional[float] = None  # falls back to settings.default_max_cost_usd


class PaperResponse(BaseModel):
    paper_id: str
    title: str
    status: str
    workspace: str


class ApprovalAction(BaseModel):
    approved: bool
    note: str = ""


# --- Paper endpoints ---

@app.post("/api/papers", response_model=PaperResponse)
async def create_paper(req: CreatePaperRequest, background_tasks: BackgroundTasks):
    """Create a new paper and start the pipeline."""
    from ..db.client import fetch_one
    import uuid

    paper_id = str(uuid.uuid4())
    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    workspace.mkdir(parents=True, exist_ok=True)

    manifest = {
        "paper_id": paper_id,
        "title": req.title,
        "research_question": req.research_question,
        "datasets": req.datasets,
        "mode": req.mode,
        "current_stage": "idea",
    }
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))

    cap = req.max_cost_usd if req.max_cost_usd is not None else settings.default_max_cost_usd
    try:
        await fetch_one(
            """
            INSERT INTO papers (id, title, research_question, status, workspace, mode, max_cost_usd)
            VALUES (%(id)s, %(title)s, %(rq)s, 'idea', %(ws)s, %(mode)s, %(cap)s)
            """,
            {"id": paper_id, "title": req.title, "rq": req.research_question,
             "ws": str(workspace), "mode": req.mode, "cap": cap},
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
    except Exception:
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
    except Exception:
        return {**row, "usage": {}}


@app.get("/api/papers/{paper_id}/artifacts")
async def list_artifacts(paper_id: str) -> dict[str, Any]:
    from ..db.client import fetch_one
    from ..config import get_settings
    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    files = [str(f.relative_to(workspace)) for f in workspace.rglob("*") if f.is_file() and not f.name.startswith(".")]
    return {"paper_id": paper_id, "files": files}


@app.post("/api/papers/{paper_id}/cancel")
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
    except Exception:
        contributions = []
    try:
        events = await fetch_all(
            """
            SELECT event_type, stage, specialist, payload, created_at
            FROM pipeline_events WHERE paper_id = %(p)s ORDER BY created_at
            """,
            {"p": paper_id},
        )
    except Exception:
        events = []
    try:
        usage = await _get_usage(paper_id)
    except Exception:
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
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/queries/{query_id}/approve")
async def approve_query(query_id: str, action: ApprovalAction):
    from ..db.client import execute
    if action.approved:
        await execute(
            "UPDATE data_approval_requests SET status = 'approved', reviewed_at = NOW(), note = %(note)s WHERE query_record_id = %(id)s",
            {"id": query_id, "note": action.note},
        )
        await execute(
            "UPDATE data_query_records SET validation_status = 'approved', approved_by = 'researcher' WHERE id = %(id)s",
            {"id": query_id},
        )
    else:
        await execute(
            "UPDATE data_approval_requests SET status = 'rejected', reviewed_at = NOW(), note = %(note)s WHERE query_record_id = %(id)s",
            {"id": query_id, "note": action.note},
        )
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


# --- Background tasks ---

async def _run_pipeline(paper_id: str, workspace: Path, mode: str, max_cost_usd: float) -> None:
    from ..config import get_settings
    from ..modules.llm.registry import get_backend
    from ..core.strategist.runner import PipelineRunner
    from ..modules.data.tools import ALLIUM_TOOLS, DeferredAlliumToolHandler

    settings = get_settings()
    backend = get_backend(settings)

    extra_tools = ALLIUM_TOOLS if settings.data_module_enabled else []
    extra_handlers = []
    if settings.data_module_enabled and settings.allium_api_key:
        extra_handlers = [DeferredAlliumToolHandler(paper_id, "pipeline", workspace)]

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
