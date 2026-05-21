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
from pydantic import AliasChoices, BaseModel, Field

from ..config import get_settings
from ..logging_config import get_logger


def _validate_uuid(paper_id: str) -> str:
    """Validate that paper_id is a syntactically valid UUID, else 404.

    Without this, an invalid string flows into a `uuid` column and psycopg
    raises InvalidTextRepresentation, which Starlette surfaces as 500 — not
    helpful for a typo'd URL.
    """
    import uuid as _uuid

    try:
        _uuid.UUID(paper_id)
    except (ValueError, AttributeError, TypeError) as e:
        raise HTTPException(status_code=404, detail="Paper not found") from e
    return paper_id


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


# First-run guardrail: until a paper at the same (model, methodology, mode)
# tuple has reached `completed`, cap is forced to $1.00 unless the requester
# acknowledges. Caps blast radius on the first-of-anything to roughly the
# cost of one Haiku run.
_UNPROVEN_TUPLE_CAP = 1.0


async def _tuple_is_proven(model: str, methodology: str, mode: str) -> bool:
    """Has any paper with this (model, methodology, mode) tuple completed?

    Returns False when the DB is unavailable — fail safe (treat as unproven)
    rather than fail open. The user can still proceed by acknowledging.
    """
    from ..db.client import fetch_one

    try:
        row = await fetch_one(
            """
            SELECT 1 FROM papers
            WHERE status = 'completed'
              AND model = %(model)s
              AND methodology = %(methodology)s
              AND mode = %(mode)s
            LIMIT 1
            """,
            {"model": model, "methodology": methodology, "mode": mode},
        )
    except Exception as e:
        logger.warning(
            "tuple-proven check failed for (%s, %s, %s): %s — treating as unproven", model, methodology, mode, e
        )
        return False
    return row is not None


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
    # CLI backends (Claude Code Max, Codex CLI, Gemini CLI) run on flat-rate
    # plans, so the cost meter values are Sonnet-equivalent ESTIMATES, not
    # what the user actually pays. The budget cap still functions as a
    # token-spend guardrail — useful for runaway protection — but the dollar
    # number in `/api/papers/<id>` is informational only.
    if s.llm_backend in {"claude_code", "codex_cli", "gemini_cli"}:
        logger.warning(
            "Backend %s: cost values are Sonnet-rate ESTIMATES (synthetic). "
            "Actual user cost on a flat-rate plan is $0. Budget cap still "
            "operates as a token-spend guardrail.",
            s.llm_backend,
        )


@app.on_event("shutdown")
async def _graceful_shutdown_runners() -> None:
    """Closes #5: on SIGTERM/SIGINT, transition in-flight papers to 'paused'
    rather than letting them rot at their last in-flight status.

    Without this, a server restart while a paper is mid-`revision` (etc.)
    leaves a zombie row that requires manual UPDATE before /resume will
    accept it (pre-v0.4 behaviour; #7 also softens the resume gate).
    """
    if not _RUNNING:
        return
    logger.info("Shutting down — cancelling %d in-flight paper task(s)", len(_RUNNING))
    paper_ids = list(_RUNNING.keys())

    # Cancel everything first so all runners get their CancelledError
    # handler to run (which saves state.json). Brief timeout per task —
    # we're shutting down, can't block forever.
    for paper_id in paper_ids:
        task = _RUNNING.get(paper_id)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as e:
                logger.warning("Error awaiting cancelled task for %s: %s", paper_id, e)

    # The runner's CancelledError handler marks status=CANCELLED, but a
    # server-initiated shutdown isn't a user cancel — re-mark as PAUSED so
    # the operator's mental model + the /resume eligibility logic match.
    # Skip papers whose state.json says `last_status: completed` — those
    # genuinely finished; don't downgrade them.
    from ..core.pipeline.state import PipelineState
    from ..db.client import execute

    settings = get_settings()
    for paper_id in paper_ids:
        try:
            workspace = Path(settings.workspace_root) / paper_id
            if workspace.exists():
                try:
                    state = PipelineState.load(workspace, paper_id, mode="iterative")
                    if state.last_status == "completed":
                        # Genuinely complete — leave it alone.
                        continue
                except Exception:
                    pass
            await execute(
                "UPDATE papers SET status = 'paused', "
                "last_error = 'Server shutdown while in-flight; POST /resume to continue.' "
                "WHERE id = %(id)s AND status NOT IN ('completed','cancelled')",
                {"id": paper_id},
            )
        except Exception as e:
            logger.warning("Could not transition paper %s to paused on shutdown: %s", paper_id, e)


# --- Request/Response Models ---


class CreatePaperRequest(BaseModel):
    title: str
    research_question: str
    datasets: list[str] = []
    # Accept both `mode` (canonical) and `pipeline_mode` (legacy alias used
    # by some external clients + the integration smoke test). Without this
    # alias the API silently fell back to the "iterative" default whenever
    # a caller sent `pipeline_mode` — observed in live test eea5379b where
    # `--mode single_pass` from `e2er run` reached the API as `pipeline_mode`
    # and the first-run log line reported `mode=iterative`.
    mode: str = Field(default="iterative", validation_alias=AliasChoices("mode", "pipeline_mode"))
    methodology: str = "empirical"  # empirical | theoretical | mixed
    bibtex_path: str | None = None
    max_cost_usd: float | None = None  # falls back to settings.default_max_cost_usd
    # First-run guardrail: when no paper at the current (model, methodology, mode)
    # tuple has ever reached `completed`, the cap is forced to $1.00 unless the
    # requester explicitly acknowledges. Defaults to False so the cheap path
    # is the easy path. See `_UNPROVEN_TUPLE_CAP`.
    acknowledge_unproven_tuple: bool = False


class ResumeRequest(BaseModel):
    """Body for POST /api/papers/{id}/resume.

    Pre-v0.5 the endpoint took no body and always used the cap stored
    on the papers row. That made budget-pause recovery a two-step
    operator dance: UPDATE the row in SQL, THEN POST /resume. The
    2026-05-20 live validation hit this exact friction. v0.5 lets the
    operator raise the cap atomically with the resume request.

    `max_cost_usd=None` preserves the prior behaviour (use the existing
    row value). Any positive value updates the row before re-firing
    the runner so the new cap is what the budget check reads.
    """

    max_cost_usd: float | None = None


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

    # First-run guardrail. Inspect the (model, methodology, mode) tuple. If
    # nothing has completed at this combination, force the cap to $1 unless
    # the requester explicitly acknowledges. This is the proactive defense
    # against the May 2026 "spend $8 chasing a Sonnet bug" failure: cheap
    # validation must succeed once before we trust an expensive cap.
    current_model = settings.default_model
    requested_cap = req.max_cost_usd if req.max_cost_usd is not None else settings.default_max_cost_usd
    proven = await _tuple_is_proven(current_model, req.methodology, req.mode)
    if not proven and requested_cap > _UNPROVEN_TUPLE_CAP and not req.acknowledge_unproven_tuple:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This is the first paper at (model={current_model}, "
                f"methodology={req.methodology}, mode={req.mode}). The cost cap "
                f"is limited to ${_UNPROVEN_TUPLE_CAP:.2f} until at least one "
                f"paper with this combination reaches status='completed'. "
                f"You requested ${requested_cap:.2f}. "
                f"Either lower the cap to ${_UNPROVEN_TUPLE_CAP:.2f}, or set "
                f"`acknowledge_unproven_tuple: true` in the request to override."
            ),
        )
    # Cap resolution:
    #   - proven tuple → honour the requested cap, full stop.
    #   - unproven + ack → honour the requested cap (ack IS the override).
    #   - unproven + no ack + low cap → honour the requested cap (it was
    #     already below the floor; nothing to enforce).
    #   - unproven + no ack + high cap → rejected above with 400.
    # Earlier this used min(requested_cap, _UNPROVEN_TUPLE_CAP) even when
    # ack=true, which meant the override only bypassed the 400 but the cap
    # was still forced to $1 — observed May 2026 NFT-paper run #4 hitting
    # BudgetExceededError despite an explicit ack with cap=$5.
    cap = requested_cap
    if not proven:
        # `acknowledge_unproven_tuple=True` means the caller is consenting to
        # run on a (model, methodology, mode) combo that has never reached
        # `completed` — they accept the risk and want their `--max-cost` cap
        # honored instead of being forced to the $1 first-run floor. Phrase
        # the log line so it's obvious which decision is being recorded.
        ack = req.acknowledge_unproven_tuple
        logger.warning(
            "First run at (model=%s, methodology=%s, mode=%s); cap=$%.2f "
            "(user_ack_unproven=%s, first_run_floor=$%.2f%s)",
            current_model,
            req.methodology,
            req.mode,
            cap,
            ack,
            _UNPROVEN_TUPLE_CAP,
            "" if ack else "; user did NOT ack — cap was capped to the floor",
        )

    manifest = {
        "paper_id": paper_id,
        "title": req.title,
        "research_question": req.research_question,
        "datasets": req.datasets,
        "mode": req.mode,
        "methodology": req.methodology,
        "model": current_model,
        "current_stage": "idea",
    }
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
    try:
        await execute(
            """
            INSERT INTO papers (id, title, research_question, status, workspace,
                                mode, methodology, model, max_cost_usd)
            VALUES (%(id)s, %(title)s, %(rq)s, 'idea', %(ws)s,
                    %(mode)s, %(methodology)s, %(model)s, %(cap)s)
            """,
            {
                "id": paper_id,
                "title": req.title,
                "rq": req.research_question,
                "ws": str(workspace),
                "mode": req.mode,
                "methodology": req.methodology,
                "model": current_model,
                "cap": cap,
            },
        )
    except Exception as e:
        logger.warning("Could not persist paper to DB: %s", e)

    if settings.github_enabled:
        background_tasks.add_task(_create_github_repo, paper_id, req.title)

    # Use asyncio.create_task (not BackgroundTasks) so we get a handle for cancel.
    task = asyncio.create_task(_run_pipeline(paper_id, workspace, req.mode, cap, req.methodology))
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
async def get_paper(paper_id: str = Depends(_validate_uuid)) -> dict[str, Any]:
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
        # Tag the cost as a Sonnet-rate estimate when the paper ran on a
        # flat-rate CLI backend so dashboards can label it correctly.
        # `total_cost_usd` itself stays unchanged for budget-cap math.
        backend_used = (row.get("backend") if isinstance(row, dict) else None) or get_settings().llm_backend
        if usage:
            usage["cost_is_estimate"] = backend_used in {"claude_code", "codex_cli", "gemini_cli"}
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


@app.post("/api/papers/{paper_id}/resume", dependencies=[Depends(require_auth)])
async def resume_paper(paper_id: str, req: ResumeRequest | None = None) -> dict[str, Any]:
    """Resume a paper whose runner is not actively running.

    The pipeline runner's PipelineState load logic skips phases that
    already produced their canonical artifacts on disk, so resuming
    picks up at the first incomplete phase — not from idea.

    Eligibility (closes #7):
        - Any status EXCEPT a terminal one (``completed`` / ``cancelled``)
          provided no live runner task exists in ``_RUNNING`` for this paper.
        - Zombies (status=``revision`` / ``in_progress`` / ``designing`` /
          etc. left over after a server restart or SIGTERM) are resumable.
        - Actively-running papers (in ``_RUNNING`` and not ``done()``)
          are rejected with 409.

    Pre-v0.4 this was restricted to {paused, failed}, which forced
    operators to manually ``UPDATE papers SET status='failed'`` every
    time a server restart left zombie rows behind.
    """
    _validate_uuid(paper_id)

    # Reject if a task is genuinely running for this paper — double-spawning
    # would race the shared workspace.
    existing = _RUNNING.get(paper_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="A pipeline task is already running for this paper")

    from ..db.client import fetch_one

    try:
        row = await fetch_one(
            "SELECT id, status, workspace, mode, max_cost_usd, methodology FROM papers WHERE id = %(id)s",
            {"id": paper_id},
        )
    except Exception as e:
        logger.warning("DB lookup failed for resume %s: %s", paper_id, e)
        raise HTTPException(status_code=503, detail="database unavailable") from e

    if row is None:
        raise HTTPException(status_code=404, detail="paper not found")

    current = (row.get("status") or "").lower()
    # Only terminal states (work is done) reject resume. Everything else —
    # including zombies in mid-pipeline statuses (revision, in_progress, …) —
    # is a candidate.
    terminal = {"completed", "cancelled"}
    if current in terminal:
        raise HTTPException(
            status_code=409,
            detail=(
                f"paper status is '{current}' (terminal) — nothing to resume. "
                "Resume only handles in-flight or failed/paused papers."
            ),
        )

    workspace = Path(row["workspace"])
    mode = row.get("mode") or "single_pass"
    cap = float(row.get("max_cost_usd") or 25.0)
    methodology = row.get("methodology") or "empirical"

    # Optional cap raise (v0.5): if the request body provides a new
    # max_cost_usd, persist it before re-firing the runner so the
    # budget check reads the new value. Reject non-positive values —
    # zero/negative caps would re-pause immediately.
    if req is not None and req.max_cost_usd is not None:
        if req.max_cost_usd <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"max_cost_usd must be positive, got {req.max_cost_usd}",
            )
        cap = float(req.max_cost_usd)

    # Reset status to the lowest reasonable resume point. The runner's
    # state-load will detect what's actually on disk and skip ahead.
    # Persist the (possibly updated) cap in the same UPDATE so the
    # row reflects the resume request atomically.
    from ..db.client import execute

    try:
        await execute(
            "UPDATE papers SET status = 'in_progress', last_error = NULL, max_cost_usd = %(cap)s WHERE id = %(id)s",
            {"id": paper_id, "cap": cap},
        )
    except Exception as e:
        logger.warning("Could not update status on resume %s: %s", paper_id, e)

    task = asyncio.create_task(_run_pipeline(paper_id, workspace, mode, cap, methodology))
    _RUNNING[paper_id] = task
    task.add_done_callback(lambda _t: _RUNNING.pop(paper_id, None))

    return {"status": "resuming", "paper_id": paper_id, "from_status": current}


@app.get("/api/papers/{paper_id}/failure-bundle")
async def failure_bundle(paper_id: str) -> dict[str, Any]:
    """Single-call diagnostic for a paused/failed run.

    Returns everything the operator (or /diagnose-run agent) needs to
    understand why a paper stopped, without having to dig through 4
    separate endpoints + the app log:

      - paper status + last_error (untruncated)
      - every pipeline event with full untruncated payload
      - per-specialist drill-down (success/failure/error_msg/turns/cost/tokens)
      - workspace listing: which canonical artifacts are present vs missing
      - data_summary.md content (often the most actionable artifact when
        the data layer is degraded)

    Replaces the 80-char truncation that the cascade detector applies to
    its halting message. Run #14-#18 each had a critical error hidden by
    that truncation; this endpoint surfaces the full text.
    """
    _validate_uuid(paper_id)

    from ..core.specialists.registry import SPECIALIST_ARTIFACTS
    from ..db.client import fetch_all, fetch_one

    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id

    try:
        paper_row = await fetch_one(
            "SELECT id, title, status, last_error, mode, methodology, max_cost_usd, "
            "research_question, workspace, created_at FROM papers WHERE id = %(id)s",
            {"id": paper_id},
        )
    except Exception as e:
        logger.warning("failure-bundle DB lookup failed for %s: %s", paper_id, e)
        raise HTTPException(status_code=503, detail="database unavailable") from e
    if paper_row is None:
        raise HTTPException(status_code=404, detail="paper not found")

    # Events: untruncated payload, sorted oldest → newest. The diagnose-run
    # agent typically scans these tail-to-head for the first failure event.
    try:
        events = await fetch_all(
            """
            SELECT event_type, stage, specialist, payload, created_at
            FROM pipeline_events WHERE paper_id = %(p)s
            ORDER BY created_at
            """,
            {"p": paper_id},
        )
    except Exception as e:
        logger.warning("failure-bundle events fetch failed for %s: %s", paper_id, e)
        events = []

    # Per-specialist drill-down. error_msg is untruncated here — the
    # cascade detector's 400-char clamp only applies to the runtime
    # halting message, not the underlying DB row.
    try:
        contributions = await fetch_all(
            """
            SELECT specialist, output_file, success, error_msg,
                   usage_tokens, cost_usd, duration_sec, created_at
            FROM contributions WHERE paper_id = %(p)s
            ORDER BY created_at
            """,
            {"p": paper_id},
        )
    except Exception as e:
        logger.warning("failure-bundle contributions fetch failed for %s: %s", paper_id, e)
        contributions = []

    # Workspace state: which canonical artifacts are present vs missing.
    # Cascade detection halts on the first missing artifact, so this is
    # the fastest path from "the run failed" to "this specialist didn't
    # write its file".
    artifacts_status: list[dict[str, Any]] = []
    if workspace.exists():
        for specialist, artifact_path in SPECIALIST_ARTIFACTS.items():
            candidate = workspace / artifact_path
            artifacts_status.append(
                {
                    "specialist": specialist,
                    "artifact": artifact_path,
                    "exists": candidate.exists(),
                    "size_bytes": candidate.stat().st_size if candidate.exists() else 0,
                }
            )

    # data_summary.md is often the most actionable file when the data
    # layer is degraded — data_analyst writes a transparent failure
    # report there with API error envelopes intact.
    data_summary_excerpt = ""
    ds_path = workspace / "data_summary.md"
    if ds_path.exists():
        try:
            data_summary_excerpt = ds_path.read_text(encoding="utf-8")[:8000]
        except Exception as e:
            data_summary_excerpt = f"(could not read data_summary.md: {e})"

    return {
        "paper_id": paper_id,
        "status": paper_row.get("status"),
        "last_error": paper_row.get("last_error"),
        "title": paper_row.get("title"),
        "research_question": paper_row.get("research_question"),
        "mode": paper_row.get("mode"),
        "methodology": paper_row.get("methodology"),
        "events": events,
        "specialists": contributions,
        "artifacts": artifacts_status,
        "missing_canonical_artifacts": [a["specialist"] for a in artifacts_status if not a["exists"]],
        "data_summary_excerpt": data_summary_excerpt,
    }


@app.get("/api/papers/{paper_id}/data-queries")
async def data_queries(paper_id: str) -> dict[str, Any]:
    """Return every Allium-style query the paper run submitted.

    The `data_query_records` table captures both SQL Explorer queries
    (`query_allium feasibility/production`) and developer-tier endpoint
    calls when they go through the gatekeeper. Surfacing them in one
    endpoint replaces the manual `cat audit_log.csv | grep ...` workflow.

    Useful when diagnosing a data_analyst run: did the model actually
    submit queries, were they approved, did they return rows, what
    errors did Allium emit?
    """
    _validate_uuid(paper_id)

    from ..db.client import fetch_all

    try:
        queries = await fetch_all(
            """
            SELECT id, specialist, query_sql, query_type, fields_requested,
                   aggregation_level, estimated_rows, actual_rows,
                   validation_status, validation_errors, approval_status,
                   approval_note, executed_at, created_at
            FROM data_query_records
            WHERE paper_id = %(p)s
            ORDER BY created_at
            """,
            {"p": paper_id},
        )
    except Exception as e:
        logger.warning("data-queries fetch failed for %s: %s", paper_id, e)
        # Missing table is not 5xx-worthy — the data module is optional.
        return {"paper_id": paper_id, "queries": [], "summary": {}, "error": str(e)}

    # Roll up an at-a-glance summary so the dashboard / agent doesn't have
    # to count rows itself. Explicit Any annotation because the value type
    # is heterogeneous (ints + nested dicts) — mypy infers `dict[str, object]`
    # otherwise and rejects `.get()` on the bucket dicts at attr-defined.
    summary: dict[str, Any] = {
        "total": len(queries),
        "by_type": {},
        "by_validation_status": {},
        "by_approval_status": {},
        "executed": sum(1 for q in queries if q.get("executed_at") is not None),
        "rows_returned": sum(int(q.get("actual_rows") or 0) for q in queries),
    }
    for q in queries:
        for field, bucket in [
            ("query_type", "by_type"),
            ("validation_status", "by_validation_status"),
            ("approval_status", "by_approval_status"),
        ]:
            key = q.get(field) or "unknown"
            summary[bucket][key] = summary[bucket].get(key, 0) + 1

    return {"paper_id": paper_id, "queries": queries, "summary": summary}


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
async def paper_detail(request: Request, paper_id: str = Depends(_validate_uuid)) -> Any:
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
async def paper_live_fragment(request: Request, paper_id: str = Depends(_validate_uuid)) -> Any:
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
    except Exception as exc:
        logger.warning("live-fragment events fetch failed for %s: %s", paper_id, exc)
        events = []
    for ev in events or []:
        if ev.get("created_at") is not None:
            ev["created_at_short"] = str(ev["created_at"])[11:19]

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


async def _run_pipeline(
    paper_id: str,
    workspace: Path,
    mode: str,
    max_cost_usd: float,
    methodology: str = "empirical",
) -> None:
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
        methodology=methodology,
    )
    await runner.run()


async def _create_github_repo(paper_id: str, title: str) -> None:
    from ..config import get_settings
    from ..modules.github.client import GitHubClient

    settings = get_settings()
    if not settings.github_token or not settings.github_username:
        logger.warning("github_enabled but token/username unset; skipping repo creation for %s", paper_id)
        return
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
