"""FastAPI application — REST API for E2ER v3 pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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


# --- Request/Response Models ---

class CreatePaperRequest(BaseModel):
    title: str
    research_question: str
    datasets: list[str] = []
    mode: str = "iterative"
    bibtex_path: str | None = None


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

    try:
        await fetch_one(
            """
            INSERT INTO papers (id, title, research_question, status, workspace, mode)
            VALUES (%(id)s, %(title)s, %(rq)s, 'idea', %(ws)s, %(mode)s)
            """,
            {"id": paper_id, "title": req.title, "rq": req.research_question,
             "ws": str(workspace), "mode": req.mode},
        )
    except Exception as e:
        logger.warning("Could not persist paper to DB: %s", e)

    if settings.github_enabled:
        background_tasks.add_task(_create_github_repo, paper_id, req.title)

    background_tasks.add_task(_run_pipeline, paper_id, workspace, req.mode)

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
    return row


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

async def _run_pipeline(paper_id: str, workspace: Path, mode: str) -> None:
    from ..config import get_settings
    from ..modules.llm.registry import get_backend
    from ..core.strategist.runner import PipelineRunner
    from ..modules.data.tools import ALLIUM_TOOLS, AlliumToolHandler

    settings = get_settings()
    backend = get_backend(settings)

    extra_tools = ALLIUM_TOOLS if settings.data_module_enabled else []
    extra_handlers = []
    if settings.data_module_enabled and settings.allium_api_key:
        extra_handlers = [AlliumToolHandler(paper_id, "pipeline", None)]

    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=backend,
        model=settings.default_model,
        mode=mode,
        extra_tools=extra_tools,
        extra_handlers=extra_handlers,
        backend_name=settings.llm_backend,
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
