"""The e2er server: the dashboard (HTML pages) and the API the pages and the `e2er` commands use."""

from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import secrets
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import AliasChoices, BaseModel, Field

from .. import __version__ as _version
from ..config import get_settings
from ..core.run_owner import IN_FLIGHT
from ..db.studies import study_key
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


def require_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Who may start, steer, stop or change a run: the e2er that runs this server.

    A request passes with this server's session token (the dashboard's cookie,
    set from the link `e2er` opened, or the ``X-E2ER-Token`` header the `e2er`
    commands send; see local_session.py) or, when ``API_AUTH_TOKEN`` is set,
    with ``Authorization: Bearer <token>``. Before 0.13.8 these endpoints were
    open to anything on this computer without ``API_AUTH_TOKEN``, the shell
    commands of a run's own AI model included; those never get the token.
    """
    from . import local_session as ls

    # getattr keeps test stubs of get_settings() that omit this field working.
    expected = getattr(get_settings(), "api_auth_token", None)
    if authorization and authorization.startswith("Bearer ") and expected:
        if secrets.compare_digest(authorization[len("Bearer ") :].strip(), expected):
            return
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    if ls.has_session(request):
        return
    if expected:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    raise HTTPException(
        status_code=403,
        detail=(
            "This browser tab is not signed in to e2er. Run `e2er` in a terminal: it opens the dashboard "
            "signed in. Scripts use the e2er commands."
        ),
    )


_API_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _API_DIR / "static"
_TEMPLATES_DIR = _API_DIR / "templates"

logger = get_logger(__name__)
app = FastAPI(title="e2er", version=_version, description="The API of the local e2er dashboard.")

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


def _ticks(text: object) -> Any:
    """`name` in a message (as the terminal writes it) → <code>name</code>, everything else escaped."""
    import re as _re

    from markupsafe import Markup, escape

    return Markup(_re.sub(r"`([^`]+)`", r'<code class="tick">\1</code>', str(escape(str(text)))))


templates.env.filters["ticks"] = _ticks


def _check_detail(detail: object, name: str) -> str:
    """`e2er doctor`'s text for a check, said plainly (no setting names); the terminal keeps the original."""
    from ..core.labels import check_detail

    return check_detail(name, str(detail or ""))


templates.env.filters["check_detail"] = _check_detail


def _status_words(value: object) -> str:
    """The status as shown: ``stopped`` → ``stopped by a check`` (core/run_outcome.py)."""
    from ..core.labels import status

    return status(str(value or ""))


templates.env.filters["status_words"] = _status_words


def _active_folder() -> dict[str, str]:
    """The folder whose settings and studies this dashboard uses, for the line at the foot of every page."""
    from .. import home

    return {"path": str(home.project_dir()), "kind": home.kind()}


from ..core import labels as _labels  # noqa: E402

_labels.register(templates.env)


def _filesize(n: object) -> str:
    """``1234`` → ``1.2 KB``; a file under a kilobyte is ``under 1 KB``, an empty one ``empty``."""
    try:
        b = int(n)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return ""
    if b == 0:
        return "empty"
    if b < 1000:
        return "under 1 KB"
    if b < 1_000_000:
        return f"{b / 1000:.0f} KB"
    return f"{b / 1_000_000:.1f} MB"


templates.env.filters["filesize"] = _filesize
templates.env.globals["active_folder"] = _active_folder


# ── error pages ──────────────────────────────────────────────────────────────
# A page or a form that fails shows a page with one plain sentence and the way
# back, never a JSON body. The API (/api/…) keeps answering JSON: the pages'
# scripts and the `e2er` commands read its `detail`.

_ERROR_HEADINGS = {
    401: "Not signed in",
    403: "Not signed in",
    404: "Not found",
    409: "Not possible right now",
    422: "Could not use what was sent",
    400: "Could not use what was sent",
}

_ERROR_SENTENCES = {
    404: "There is nothing at this address. The study may have been removed, or the link is incomplete.",
    500: "Something went wrong inside e2er. The terminal window where e2er runs shows the details.",
}


def _wants_page(request: Request) -> bool:
    path = request.url.path
    return not (path.startswith("/api/") or path in {"/health", "/openapi.json"} or path.startswith("/static/"))


def _error_response(request: Request, status_code: int, detail: Any) -> Any:
    detail_text = detail if isinstance(detail, str) else ""
    if status_code in (401, 403):
        from . import local_session as ls

        sentence = ls.local_problem(request) or detail_text or "This browser tab is not signed in to e2er."
    elif status_code in _ERROR_SENTENCES:
        sentence = _ERROR_SENTENCES[status_code]
    elif detail_text:
        sentence = detail_text
    else:
        sentence = "That did not work. Go back and try again."
    context = {
        "heading": _ERROR_HEADINGS.get(status_code, "Something went wrong"),
        "sentence": sentence,
        "detail": detail_text if detail_text != sentence else "",
        "status_code": status_code,
        "path": request.url.path,
    }
    name = "_error_fragment.html" if request.headers.get("hx-request") else "error.html"
    return templates.TemplateResponse(request, name, context, status_code=status_code)


from fastapi.exception_handlers import (  # noqa: E402
    http_exception_handler as _default_http_handler,
)
from fastapi.exception_handlers import (  # noqa: E402
    request_validation_exception_handler as _default_validation_handler,
)
from fastapi.exceptions import RequestValidationError  # noqa: E402
from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402


@app.exception_handler(_StarletteHTTPException)
async def _http_error(request: Request, exc: _StarletteHTTPException) -> Any:
    if _wants_page(request):
        return _error_response(request, exc.status_code, exc.detail)
    return await _default_http_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> Any:
    if _wants_page(request):
        return _error_response(request, 422, "Some of the form was missing or not readable. Go back and try again.")
    return await _default_validation_handler(request, exc)


@app.exception_handler(Exception)
async def _unexpected_error(request: Request, exc: Exception) -> Any:
    logger.exception("unexpected error on %s %s", request.method, request.url.path)
    if _wants_page(request):
        return _error_response(request, 500, "")
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": _ERROR_SENTENCES[500]}, status_code=500)


def _paper_workspace(paper: dict[str, Any]) -> Path:
    if paper.get("workspace"):
        return Path(str(paper["workspace"]))
    return _workspace_of(str(paper.get("id") or ""))


def _visible_files(workspace: Path) -> list[str]:
    """The run's files a researcher sees: no hidden files or folders (saved state, .history), no backups."""
    from ..core.export.bundle_files import is_leftover

    out = []
    for f in workspace.rglob("*"):
        rel = f.relative_to(workspace)
        if f.is_file() and not any(p.startswith(".") for p in rel.parts) and not is_leftover(f.name):
            out.append(rel.as_posix())
    return sorted(out)


def _workspace_of(paper_id: str) -> Path:
    """A run's folder when only its id is at hand (src/home.py finds folders named after the title)."""
    from ..home import find_workspace

    return find_workspace(paper_id, get_settings().workspace_root)


def _with_outcome(paper: dict[str, Any]) -> dict[str, Any]:
    """The paper row plus ``shown_status`` (whether the run finished, never a review result)
    and ``internal_review`` (e2er's internal quality review score, when the run has one).

    ``status`` stays the stored internal code: the resume, cancel and archive
    rules read it. Pages show ``shown_status``.
    """
    from ..core.run_outcome import internal_review, read_aggregation, run_notes, workspace_status

    ws = _paper_workspace(paper)
    return {
        **paper,
        "shown_status": workspace_status(paper.get("status"), ws),
        "internal_review": internal_review(read_aggregation(ws)),
        "notes": run_notes(ws),
    }


@app.middleware("http")
async def _session_from_launch_url(request: Request, call_next):
    """Trade the token in the launch URL (`/?t=…`) for a session cookie.

    `e2er` opens the browser at that URL; the cookie then unlocks the parts of
    the dashboard that touch this computer (see local_session.py). The redirect
    drops the token from the address bar and the history.
    """
    from ..core import run_owner
    from . import local_session as ls

    if run_owner.PORT is None and request.url.port:
        run_owner.PORT = request.url.port  # recorded with each run this process owns
    canonical = _canonical_url(request)
    if canonical is not None:
        return RedirectResponse(url=canonical, status_code=307)
    token = request.query_params.get(ls.QUERY)
    if request.method == "GET" and token is not None:
        import secrets

        from starlette.datastructures import URL

        clean = URL(str(request.url)).remove_query_params(ls.QUERY)
        target = clean.path + (f"?{clean.query}" if clean.query else "")
        resp = RedirectResponse(url=target, status_code=303)
        if secrets.compare_digest(token, ls.session_token()):
            ls.set_session_cookies(resp, request, token)
        return resp
    return await call_next(request)


def _canonical_url(request: Request) -> str | None:
    """``localhost`` → ``127.0.0.1`` for a page request, so one tab never holds two sessions.

    Cookies belong to a host name: a tab on ``localhost`` and the link e2er
    opened (``127.0.0.1``) carried different cookies, and every button on the
    ``localhost`` tab failed. Only GET and HEAD are redirected; a form or an
    API call is answered where it was sent.
    """
    if request.method not in {"GET", "HEAD"} or not _wants_page(request):
        return None
    host = (request.headers.get("host") or "").strip().lower()
    name, _, port = host.partition(":")
    if name != "localhost":
        return None
    return str(request.url.replace(netloc=f"127.0.0.1:{port}" if port else "127.0.0.1"))


from .finish import router as _finish_router  # noqa: E402 — needs `templates` above
from .inputs import router as _inputs_router  # noqa: E402
from .setup import router as _setup_router  # noqa: E402
from .studies import router as _studies_router  # noqa: E402

app.include_router(_setup_router)
app.include_router(_finish_router)
app.include_router(_studies_router)
app.include_router(_inputs_router)

# Registry of running pipeline tasks, keyed by paper_id.
# Used by POST /api/papers/{id}/cancel to cancel an in-flight run.
_RUNNING: dict[str, asyncio.Task] = {}
_HEARTBEAT: list[asyncio.Task] = []


async def _track_run(paper_id: str, task: asyncio.Task) -> None:
    """Register a run task and record this process as its owner in the database.

    The owner record is what lets another e2er server on the same database
    tell that this paper is running here (src/core/run_owner.py).
    """
    from ..core import run_owner

    _RUNNING[paper_id] = task

    def _done(_t: asyncio.Task) -> None:
        _RUNNING.pop(paper_id, None)
        try:
            asyncio.get_running_loop().create_task(run_owner.release(paper_id))
        except RuntimeError:  # loop already closed at shutdown
            pass

    task.add_done_callback(_done)
    await run_owner.claim(paper_id)
    if not _HEARTBEAT or _HEARTBEAT[0].done():
        _HEARTBEAT[:] = [asyncio.get_running_loop().create_task(run_owner.heartbeat_loop(_RUNNING))]


# First-run guardrail: until a paper at the same (model, methodology, mode)
# tuple has reached `completed`, cap is forced to $1.00 unless the requester
# acknowledges. Caps blast radius on the first-of-anything to roughly the
# cost of one Haiku run.
_UNPROVEN_TUPLE_CAP = 1.0


# File extensions the paper-creation symlinker treats as "data" — these
# get staged into `workspace/<id>/data/` so the existing _list_user_data
# context builder picks them up. Extensions outside this set are
# silently skipped (notably .bib, which is handled by
# _load_reference_summary directly). Keep this list narrow: anything
# linked here is auto-listed to every specialist's prompt, so a noisy
# corpus would balloon the context.
def _stage_corpus_files(
    workspace: Path,
    local_data_dir: str | None,
    recursive: bool,
    suffixes,
    dest_subdir: str,
    label: str,
) -> int:
    """Symlink files from the LOCAL_DATA_DIR corpus into a workspace subdir.

    Idempotent. Skips silently when ``local_data_dir`` is unset, no root
    exists, or no matching files are found — misconfig must not break paper
    creation. When ``recursive`` is True the destination path preserves the
    relative path from the source root, so a corpus with structure (e.g.
    ``data/raw/x.csv``) stays organized inside the workspace.

    ``LOCAL_DATA_DIR`` accepts a comma-separated list of paths.
    """
    from ..modules.local_corpus import iter_corpus_files, link_or_copy, parse_corpus_roots

    if not local_data_dir:
        return 0
    roots = parse_corpus_roots(local_data_dir)
    if not roots:
        logger.warning(
            "LOCAL_DATA_DIR=%s is not a directory (or all comma-separated paths are missing); "
            "skipping %s-link step (paper creation continues normally)",
            local_data_dir,
            label,
        )
        return 0

    dest = workspace / dest_subdir
    dest.mkdir(parents=True, exist_ok=True)

    linked = 0
    for root, file_path in iter_corpus_files(roots, suffixes, recursive):
        # Preserve relative path under recursion; otherwise just the basename
        # (matches the pre-v0.8.1 behaviour).
        rel = file_path.relative_to(root) if recursive else Path(file_path.name)
        target = dest / rel
        if target.exists() or target.is_symlink():
            continue  # defensive: never overwrite a workspace file
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            link_or_copy(file_path, target)
            linked += 1
        except OSError as e:
            logger.warning("could not symlink %s → %s: %s (paper creation continues)", file_path, target, e)
    if linked:
        logger.info("Staged %d %s file(s) from LOCAL_DATA_DIR=%s into %s", linked, label, local_data_dir, dest)
    return linked


def _link_local_data_dir_into_workspace(
    workspace: Path,
    local_data_dir: str | None,
    recursive: bool = False,
    *,
    data: bool = True,
    pdfs: bool = True,
) -> None:
    """Stage the whole LOCAL_DATA_DIR corpus into the paper's workspace (a study with no choice made).

    Data files (csv/tsv/jsonl/parquet/xlsx) land in ``workspace/data/``
    so specialists ``read_file`` them through the standard sandbox. PDFs
    land in ``workspace/literature/`` so the ``read_reference`` tool can
    extract them by local path. ``.bib`` files are written into the study's
    ``literature.bib`` by ``study_inputs.prepare_papers`` and are not linked here.
    A study whose data (``data=False``) or papers (``pdfs=False``) were chosen
    stages those by the choice instead.
    """
    from ..modules.local_corpus import DATA_EXTENSIONS, PDF_EXTENSIONS

    if data:
        _stage_corpus_files(workspace, local_data_dir, recursive, DATA_EXTENSIONS, "data", "data")
    if pdfs:
        _stage_corpus_files(workspace, local_data_dir, recursive, PDF_EXTENSIONS, "literature", "PDF")


async def _prepare_papers(paper_id: str, workspace: Path, settings, research_question: str, title: str) -> None:
    """Put the study's bibliography on disk BEFORE any specialist runs.

    The researcher's papers first (the ones chosen on New study, or without a
    choice every paper of their literature folder, .bib files and Zotero
    libraries), written into ``literature.bib`` with the keys the writers are
    shown; then the web search for the research question, in addition unless
    the researcher ticked "Use only my papers". See
    :func:`src.core.study_inputs.prepare_papers` and
    :func:`src.modules.literature.discovery.acquire_literature` (why this is a
    stage rather than a tool the drafter may choose to call).
    """
    from ..core.study_inputs import prepare_papers

    await prepare_papers(workspace, paper_id, settings, [research_question, title])


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


#: Statuses that mean "work is in flight". After a restart a paper in one of
#: them is stranded, unless another live e2er process owns its run.
_ORPHANABLE = IN_FLIGHT


@app.on_event("startup")
async def _reconcile_orphans() -> None:
    """Mark papers stranded by a stopped server as paused rather than running.

    Only papers whose owner is gone: another e2er process on the same database
    may be running a paper right now, and pausing it under that process would
    be wrong (the other server keeps running it, and a resume here would run it
    twice). See src/core/run_owner.py.

    Best-effort: a database that is not reachable at boot must not stop the
    server from starting, and a paper wrongly left alone is a smaller problem
    than a dashboard that will not load.
    """
    from ..core import run_owner
    from ..db.client import execute, fetch_all
    from ..db.events import log_event

    try:
        placeholders = ", ".join(f"%(s{i})s" for i in range(len(_ORPHANABLE)))
        params = {f"s{i}": s for i, s in enumerate(_ORPHANABLE)}
        rows = await fetch_all(
            f"SELECT id, status, run_owner, heartbeat_at FROM papers WHERE status IN ({placeholders})", params
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("orphan reconciliation skipped (%s)", e)
        return

    if not rows:
        return

    paused = 0
    for row in rows:
        paper_id = str(row.get("id") or "")
        was = str(row.get("status") or "")
        if not paper_id:
            continue
        owner = run_owner.parse_owner(row.get("run_owner"))
        seen = await run_owner.last_seen(paper_id, row.get("heartbeat_at"))
        state = run_owner.owner_state(owner, seen)
        if state in ("alive", "mine") and owner is not None:
            logger.info(
                "Left paper %s alone: running on another e2er process (%s)", paper_id, run_owner.describe(owner)
            )
            continue
        if state == "unknown" and seen is not None and datetime.now(UTC) - seen < run_owner.STALE_AFTER:
            minutes = int((datetime.now(UTC) - seen).total_seconds() // 60)
            logger.info(
                "Left paper %s alone: its last activity was %d min ago, so another e2er process may be "
                "running it (it was started by an older e2er that did not record its owner)",
                paper_id,
                minutes,
            )
            continue
        try:
            await execute(
                "UPDATE papers SET status = %(new)s WHERE id = %(id)s",
                {"new": "paused", "id": paper_id},
            )
            await execute("UPDATE papers SET run_owner = NULL WHERE id = %(id)s", {"id": paper_id})
            await log_event(
                paper_id,
                "paper_paused",
                stage=was,
                payload={
                    "reason": "interrupted — the server stopped while this paper was running",
                    "previous_status": was,
                },
            )
            paused += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("could not reconcile paper %s: %s", paper_id, e)

    if paused:
        logger.info(
            "Reconciled %d interrupted paper(s) to paused — resume from the dashboard or `e2er resume <id>`",
            paused,
        )


@app.on_event("startup")
async def _log_config() -> None:
    s = get_settings()
    # Capture identity NOW, at boot, so the cached SHA is the one this process
    # actually loaded. Capturing lazily on first run would record whatever the
    # tree had drifted to by then — the stale-server hazard, one level up.
    from ..core.run_identity import identity_summary

    logger.info("Run identity: %s", identity_summary())
    logger.info(
        "e2er %s starting | backend=%s model=%s data=%s lit_kb=%s github=%s default_cap=$%.2f",
        _version,
        s.llm_backend,
        s.default_model,
        "on" if s.data_module_enabled else "off",
        "on" if s.literature_kb_enabled else "off",
        "on" if s.github_enabled else "off",
        s.default_max_cost_usd,
    )
    # CLI backends (Claude Code, Codex CLI, Gemini CLI) run on the person's
    # subscription: compute_cost records $0 for them, so the spending limit
    # never trips; the subscription's own usage limits apply instead.
    if s.llm_backend in {"claude_code", "codex", "gemini"}:
        logger.info(
            "Backend %s runs on the subscription: costs are recorded as $0 and the spending limit "
            "does not apply; the subscription's own usage limits do.",
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
    for hb in _HEARTBEAT:
        hb.cancel()
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

    for paper_id in paper_ids:
        try:
            workspace = _workspace_of(paper_id)
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
            from ..core import run_owner

            await run_owner.release(paper_id)
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
    # Which pipeline file to run: a name resolved against ./pipelines,
    # ~/.e2er/pipelines, then the builtins. Not an enum, because pipelines are
    # files users add — the set of legal values is whatever is on disk, and it
    # is validated against that rather than against a list in the code.
    pipeline: str = "empirical"
    bibtex_path: str | None = None
    # Per-paper LLM backend + model override. Both default to None → the
    # process-global settings.llm_backend / settings.default_model. Set them
    # to run this paper on a specific backend (multi-model runs, the
    # governance experiment) without restarting the server on a new env.
    backend: str | None = None
    model: str | None = None
    # Governance regime: off | contracts | full. None → settings.governance
    # (default "full"). The experiment's treatment variable — selects which
    # gates block; non-blocking gates still compute + log (shadow mode).
    governance: str | None = None
    # Human-in-the-loop: pipeline stages after which the run pauses for the
    # researcher to inspect/edit the workspace before continuing. Empty = no
    # checkpoints (unattended, current behaviour). Validated against the real
    # stage names (PIPELINE_STAGES).
    review_stages: list[str] = []
    max_cost_usd: float | None = None  # falls back to settings.default_max_cost_usd
    # First-run guardrail: when no paper at the current (model, methodology, mode)
    # tuple has ever reached `completed`, the cap is forced to $1.00 unless the
    # requester explicitly acknowledges. Defaults to False so the cheap path
    # is the easy path. See `_UNPROVEN_TUPLE_CAP`.
    acknowledge_unproven_tuple: bool = False
    # "demonstration" marks a study made only to show e2er (E2ER_PURPOSE for
    # this one study): recorded in manifest.json, and the replication report
    # and a later `e2er publish` carry the disclaimer.
    purpose: str | None = None
    # What the study uses (src/core/study_inputs.py). None: no choice was made, the study
    # takes every data file of the data folder and every paper of the researcher's folders
    # and libraries (as before 0.15.0). A list: exactly these. Data files are full paths;
    # papers are ids (pdf:<path>, bib:<path>#<key>, bibfile:<path>, zotero:<folder>#<key>,
    # library:<key>) or paths of .pdf and .bib files.
    data_files: list[str] | None = None
    papers: list[str] | None = None
    # The web literature search runs in addition to the researcher's papers; False: "Use only my papers".
    web_search: bool = True


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

    from ..core import study_inputs
    from ..db.client import execute
    from ..home import new_workspace

    paper_id = str(uuid.uuid4())
    settings = get_settings()
    # The chosen data files and papers are checked before anything is made: a missing
    # file or a .txt among the data is refused in one sentence, with no study left behind.
    try:
        chosen_data = study_inputs.check_data_files(req.data_files) if req.data_files is not None else None
        chosen_papers = study_inputs.check_paper_ids(req.papers) if req.papers is not None else None
    except study_inputs.InputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # A readable folder name (date and title); the id is in its manifest.json.
    workspace = new_workspace(Path(settings.workspace_root).expanduser(), req.title, paper_id)

    # Stage what the study uses into its folder. Without a choice, every data file (and PDF)
    # of LOCAL_DATA_DIR is linked in, as since v0.8; with one, exactly the chosen files. From
    # here on the study reads only its own folder (data/, literature/), never the live folders.
    _link_local_data_dir_into_workspace(
        workspace,
        settings.local_data_dir,
        settings.local_data_dir_recursive,
        data=chosen_data is None,
        pdfs=chosen_papers is None,
    )
    staged = (
        study_inputs.stage_chosen_data(workspace, chosen_data, settings)
        if chosen_data is not None
        else study_inputs.staged_data_files(workspace)
    )
    requested = study_inputs.copy_uploaded_papers(workspace, chosen_papers) if chosen_papers is not None else []
    study_inputs.write_record(
        workspace,
        {
            "data": {"chosen": chosen_data is not None, "files": staged},
            "papers": {"chosen": chosen_papers is not None, "web_search": req.web_search, "requested": requested},
        },
    )

    # NB: the heavy BYOD work — importing staged files into data.db and
    # discovering/ingesting the literature corpus — runs in the background
    # task (`_prepare_and_run`), NOT here. A multi-GB import + Zotero ingest
    # took longer than the CLI's HTTP timeout and made `e2er run`'s POST time
    # out (the paper still ran, but the client errored). Keeping create_paper
    # fast lets the POST return immediately with the paper_id.

    if req.methodology not in {"empirical", "theoretical", "mixed"}:
        raise HTTPException(
            status_code=400,
            detail=f"methodology must be one of empirical|theoretical|mixed, got {req.methodology!r}",
        )

    # Per-paper backend override. None → the process-global default.
    from ..modules.llm.registry import BACKENDS

    if req.backend is not None and req.backend not in BACKENDS:
        raise HTTPException(
            status_code=422,
            detail=f"backend must be one of {'|'.join(BACKENDS)}, got {req.backend!r}",
        )
    effective_backend = req.backend or settings.llm_backend

    # Per-paper governance regime override. None → the process-global default.
    _GOVERNANCE_REGIMES = {"off", "contracts", "full"}
    if req.governance is not None and req.governance not in _GOVERNANCE_REGIMES:
        raise HTTPException(
            status_code=422,
            detail=f"governance must be one of {'|'.join(sorted(_GOVERNANCE_REGIMES))}, got {req.governance!r}",
        )
    effective_governance = req.governance or settings.governance

    # The pipeline must resolve to a real file NOW, not when the background task
    # gets there. find_spec raises inside the runner, and a task that dies on its
    # first line leaves a paper row sitting at 'idea' with nothing to explain it.
    # Validated against the files on disk rather than a list in the code, because
    # users add pipelines.
    from ..core.pipeline.spec import PipelineError, find_spec

    try:
        find_spec(req.pipeline)
    except PipelineError as e:
        from ..core.pipeline.spec import available

        raise HTTPException(
            status_code=422,
            detail=f"unknown pipeline {req.pipeline!r}. Available: {', '.join(sorted(available())) or 'none'}",
        ) from e

    # Human-in-the-loop review points: steps of this template (src/core/strategist/runner.py
    # stops after any step it runs under its own name).
    allowed_stops = _review_at_choices(find_spec(req.pipeline))
    bad_stages = [s for s in req.review_stages if s not in allowed_stops]
    if bad_stages:
        raise HTTPException(
            status_code=422,
            detail=f"review_stages must be from {'|'.join(allowed_stops)}; unknown: {', '.join(bad_stages)}",
        )

    # First-run guardrail. Inspect the (model, methodology, mode) tuple. If
    # nothing has completed at this combination, force the cap to $1 unless
    # the requester explicitly acknowledges. This is the proactive defense
    # against the May 2026 "spend $8 chasing a Sonnet bug" failure: cheap
    # validation must succeed once before we trust an expensive cap.
    # Resolve against the EFFECTIVE backend, not the global one — a paper on
    # `--backend openrouter` must not inherit the anthropic model id.
    current_model = req.model or settings.default_model_for(effective_backend)
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

    if req.purpose is not None and req.purpose not in {"", "demonstration"}:
        raise HTTPException(status_code=422, detail=f"purpose must be 'demonstration' or empty, got {req.purpose!r}")

    manifest = {
        "paper_id": paper_id,
        "title": req.title,
        "research_question": req.research_question,
        # The study's data files, named in every specialist's context ("Data Available").
        "datasets": req.datasets or [f["name"] for f in staged],
        "mode": req.mode,
        "methodology": req.methodology,
        "model": current_model,
        "backend": effective_backend,
        "governance": effective_governance,
        "review_stages": req.review_stages,
        "current_stage": "idea",
        "pipeline": req.pipeline,
        **({"purpose": req.purpose} if req.purpose else {}),
    }
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
    try:
        await execute(
            """
            INSERT INTO papers (id, title, research_question, status, workspace,
                                mode, methodology, model, backend, governance,
                                review_stages, max_cost_usd, pipeline, study_key)
            VALUES (%(id)s, %(title)s, %(rq)s, 'idea', %(ws)s,
                    %(mode)s, %(methodology)s, %(model)s, %(backend)s, %(governance)s,
                    %(review_stages)s, %(cap)s, %(pipeline)s, %(study_key)s)
            """,
            {
                "id": paper_id,
                "title": req.title,
                "rq": req.research_question,
                # Absolute, so `e2er export` finds it from any folder.
                "ws": str(workspace.resolve()),
                "mode": req.mode,
                "methodology": req.methodology,
                "model": current_model,
                "backend": effective_backend,
                "governance": effective_governance,
                "review_stages": json.dumps(req.review_stages),
                "cap": cap,
                "pipeline": req.pipeline,
                "study_key": study_key(req.research_question, req.pipeline, req.title),
            },
        )
    except Exception as e:
        logger.warning("Could not persist paper to DB: %s", e)

    if settings.github_enabled:
        background_tasks.add_task(_create_github_repo, paper_id, req.title)

    # Use asyncio.create_task (not BackgroundTasks) so we get a handle for cancel.
    # _prepare_and_run does the heavy BYOD import + literature ingest FIRST (off
    # the request path), then runs the pipeline — so the POST returns now.
    task = asyncio.create_task(
        _prepare_and_run(
            paper_id,
            workspace,
            settings,
            req.mode,
            cap,
            req.methodology,
            effective_backend,
            current_model,
            effective_governance,
            req.review_stages,
            req.research_question,
            req.title,
            pipeline=req.pipeline,
        )
    )
    await _track_run(paper_id, task)

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
            usage["cost_is_estimate"] = backend_used in {"claude_code", "codex", "gemini"}
        return {**_with_outcome(dict(row)), **_how_to_continue(dict(row)), "usage": usage or {}}
    except Exception as e:
        logger.warning("get_paper usage fetch failed for paper_id=%s: %s", paper_id, e)
        return {**_with_outcome(dict(row)), **_how_to_continue(dict(row)), "usage": {}}


def _how_to_continue(row: dict[str, Any]) -> dict[str, Any]:
    """For scripts: how a paused run continues (the page says it in words, last_error stays plain)."""
    if row.get("status") != "paused":
        return {}
    pid = row.get("id")
    return {"resume_endpoint": f"POST /api/papers/{pid}/resume", "review_endpoint": f"/api/papers/{pid}/review"}


@app.get("/api/papers/{paper_id}/artifacts")
async def list_artifacts(paper_id: str) -> dict[str, Any]:

    workspace = _workspace_of(paper_id)
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    files = _visible_files(workspace)
    return {"paper_id": paper_id, "files": files}


async def _running_elsewhere(paper: dict[str, Any]) -> dict[str, Any] | None:
    """The owner, when another live e2er process is running this paper."""
    from ..core import run_owner

    task = _RUNNING.get(str(paper.get("id")))
    try:
        return await run_owner.running_elsewhere(paper, running_here=task is not None and not task.done())
    except Exception as e:  # noqa: BLE001 — never block the page on this check
        logger.debug("running-elsewhere check failed: %s", e)
        return None


def _elsewhere_text(owner: dict[str, Any]) -> str:
    from ..core import run_owner

    if owner.get("legacy"):
        return (
            f"This run was active {owner.get('minutes', 0)} min ago and may be working in another e2er window. "
            "Follow or stop it there. If that e2er is closed, you can resume the run here after "
            f"{int(run_owner.STALE_AFTER.total_seconds() // 60)} min without activity."
        )
    where = f"the dashboard on port {owner['port']}" if owner.get("port") else "another e2er window"
    return f"This run is working in {where} ({run_owner.describe(owner)}). Follow or stop it there."


@app.post("/api/papers/{paper_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_paper(paper_id: str) -> dict[str, Any]:
    """Cancel an in-flight pipeline run. The runner's CancelledError handler
    will save state and mark the paper as cancelled in the DB."""
    task = _RUNNING.get(paper_id)
    if not task or task.done():
        from ..db.client import fetch_one

        try:
            row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
        except Exception:  # noqa: BLE001
            row = None
        elsewhere = await _running_elsewhere(dict(row)) if isinstance(row, dict) else None
        if elsewhere:
            raise HTTPException(status_code=409, detail=_elsewhere_text(elsewhere))
        raise HTTPException(status_code=404, detail="No running task for this paper")
    task.cancel()
    return {"status": "cancelling", "paper_id": paper_id}


class ReviewAction(BaseModel):
    """Body for POST /api/papers/{id}/review: one researcher action at a researcher step."""

    action: str  # approve | edit | instruction | send_back
    file: str | None = None
    content: str | None = None
    text: str | None = None
    step: str | None = None
    remark: str | None = None
    resume: bool = True  # approve / send_back continue the run right away


async def _review_context(paper_id: str) -> tuple[dict[str, Any], Path, Any, Any]:
    from ..core.pipeline.researcher import pending_review
    from ..core.pipeline.spec import find_spec
    from ..core.pipeline.state import PipelineState
    from ..db.client import fetch_one

    row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if row is None:
        raise HTTPException(status_code=404, detail="paper not found")
    workspace = Path(row["workspace"])
    state = PipelineState.load(workspace, paper_id, row.get("mode") or "single_pass")
    pending = pending_review(workspace, state)
    try:
        spec = find_spec(row.get("pipeline") or "empirical")
    except Exception:  # noqa: BLE001 — the review still works without the template
        spec = None
    return row, workspace, state, (pending, spec)


def _step_outputs(workspace: Path, step: str, events: list[dict[str, Any]], spec: Any) -> list[str]:
    """The text files a step wrote: the outputs of the specialists that finished in it."""
    from ..core.pipeline.researcher import _EDITABLE_SUFFIXES
    from ..core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SIDECAR_ARTIFACTS

    who: list[str] = []
    inside = False  # between the step's phase_start and phase_end (the last time it ran)
    for e in events:  # oldest first, as fetch_events returns them
        et, stage = e.get("event_type"), e.get("stage")
        if et == "phase_start" and stage == step:
            inside, who = True, []
        elif et == "phase_end" and stage == step:
            inside = False
        elif et == "specialist_end" and e.get("specialist") and (inside or stage == step):
            who.append(str(e["specialist"]))
    if not who and spec is not None and spec.step(step) is not None:
        who = list(spec.step(step).run)
    out: list[str] = []
    for sp in dict.fromkeys(who):
        for rel in [SPECIALIST_ARTIFACTS.get(sp, ""), *SPECIALIST_SIDECAR_ARTIFACTS.get(sp, [])]:
            if rel and "/" not in rel and rel.endswith(_EDITABLE_SUFFIXES) and (workspace / rel).is_file():
                out.append(rel)
    return list(dict.fromkeys(out))


def _sendable(workspace: Path, state: Any, pending: Any, spec: Any) -> list[str]:
    """What a researcher can send back from here: earlier template steps and specialists with output."""
    from ..core.specialists.registry import SPECIALIST_ARTIFACTS

    steps: list[str] = []
    # The number check runs inside the review step: what can go back is before it.
    stop_at = "review" if pending.kind == "numbers" else pending.stage
    if spec is not None:
        for s in spec.steps:
            if s.name == stop_at:
                break
            if s.kind not in ("researcher", "preregister") and s.name in state.completed_stages:
                steps.append(s.name)
    specialists = sorted(sp for sp, out in SPECIALIST_ARTIFACTS.items() if (workspace / out).is_file())
    if pending.kind == "contract":
        # The specialists whose output failed can always be sent back, written or not.
        failed = [f.get("specialist") for f in (state.metadata.get("contract_pause") or {}).get("failed") or []]
        specialists = sorted(set(specialists) | {f for f in failed if f})
    if pending.kind == "numbers":
        from ..core.pipeline.researcher import NUMBERS_SENDABLE

        specialists = sorted(set(specialists) | set(NUMBERS_SENDABLE))
    return steps + specialists


@app.get("/api/papers/{paper_id}/review")
async def get_review(paper_id: str = Depends(_validate_uuid)) -> dict[str, Any]:
    """The researcher step a paused run is waiting at: its files, what can be sent back, past actions."""
    from ..db.events import fetch_events

    _row, workspace, state, (pending, spec) = await _review_context(paper_id)
    past = [e for e in await fetch_events(paper_id) if e.get("event_type") == "researcher_action"]
    for e in past:  # SQLite hands the payload back as JSON text
        if isinstance(e.get("payload"), str):
            try:
                e["payload"] = json.loads(e["payload"])
            except ValueError:
                e["payload"] = {}
    if pending is None:
        return {"pending": None, "actions": past}
    shown_files = list(pending.files)
    if pending.kind == "review_at" and not (state.metadata.get("review") or {}).get("files"):
        # A stop you asked for: the files this step wrote, not every text file of the study.
        shown_files = _step_outputs(workspace, pending.stage, await fetch_events(paper_id), spec)
    files = []
    for name in shown_files:
        p = workspace / name
        files.append(
            {
                "name": name,
                "exists": p.is_file(),
                "content": p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "",
            }
        )
    reasons = list(state.metadata.get("review", {}).get("reasons") or [])
    extra: dict[str, Any] = {}
    if pending.kind == "numbers":
        # Per mismatch: the table cell, the value in the table, in the results, and the source key.
        check = state.metadata.get("number_check") or {}
        extra["mismatches"] = [
            {k: m.get(k) for k in ("cell", "in_table", "in_results", "source_key")}
            for m in check.get("mismatches") or []
        ]
        if check.get("auto_patch"):
            extra["auto_patch"] = check["auto_patch"]
        if isinstance(check.get("untraced"), dict):
            # No table cell was traced at all: the reason names the tables.
            extra["untraced"] = check["untraced"].get("reason", "")
    if pending.kind == "contract":
        # Per specialist: each attempt with its violations, and the files involved.
        extra["failures"] = [
            {"specialist": f.get("specialist"), "attempts": f.get("attempts") or [], "files": f.get("files") or []}
            for f in (state.metadata.get("contract_pause") or {}).get("failed") or []
        ]
    return {
        # A halted check says why, so the researcher knows what to fix.
        "pending": {
            "stage": pending.stage,
            "stage_label": _step_label(pending.stage, spec),
            "kind": pending.kind,
            **({"reasons": reasons} if reasons else {}),
            **extra,
        },
        "files": files,
        "sendable": _sendable(workspace, state, pending, spec),
        "actions": past,
    }


@app.post("/api/papers/{paper_id}/review", dependencies=[Depends(require_auth)])
async def post_review(req: ReviewAction, paper_id: str = Depends(_validate_uuid)) -> dict[str, Any]:
    """Apply one researcher action; approve and send back continue the run unless resume=false."""
    from ..core.pipeline.researcher import ResearcherActionError, apply_action
    from ..db.events import log_event

    existing = _RUNNING.get(paper_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="the run is working; wait until it stops at a researcher step")
    _row, workspace, state, (pending, spec) = await _review_context(paper_id)
    if pending is None:
        raise HTTPException(status_code=409, detail="the run is not stopped at a researcher step")
    try:
        payload = apply_action(
            workspace,
            state,
            req.model_dump(exclude={"resume"}),
            sendable=_sendable(workspace, state, pending, spec) if req.action == "send_back" else None,
        )
    except ResearcherActionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state.save(workspace)
    await log_event(paper_id, "researcher_action", stage=pending.stage, payload=payload)
    out: dict[str, Any] = {"recorded": payload}
    if req.action in ("approve", "send_back") and req.resume:
        out["resumed"] = await resume_paper(paper_id)
    return out


class RerunRequest(BaseModel):
    """Body for POST /api/papers/{id}/rerun: the step to run again from, and the researcher's remark."""

    step: str
    remark: str


@app.post("/api/papers/{paper_id}/rerun", dependencies=[Depends(require_auth)])
async def rerun_paper(req: RerunRequest, paper_id: str = Depends(_validate_uuid)) -> dict[str, Any]:
    """Send a study back to one of its steps: that step and every later one run again.

    For a study that is not running: completed, stopped by a check, failed,
    cancelled, or paused (by an error, the spending limit, or at a researcher
    step, whose stop the rerun then replaces). The action is recorded
    (``researcher_action``, action ``rerun``) for the dossier, and the run stops
    again at the next researcher step. The dashboard's study page and
    ``e2er rerun`` both come here.
    """
    from ..core.pipeline.researcher import ResearcherActionError, apply_rerun
    from ..core.pipeline.spec import find_spec
    from ..core.pipeline.state import PipelineState
    from ..db.client import execute, fetch_one
    from ..db.events import log_event

    existing = _RUNNING.get(paper_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="the study is running; stop it or wait for it to stop")
    row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if row is None:
        raise HTTPException(status_code=404, detail="paper not found")
    elsewhere = await _running_elsewhere(dict(row))
    if elsewhere:
        raise HTTPException(status_code=409, detail=_elsewhere_text(elsewhere))
    workspace = Path(row["workspace"])
    try:
        spec = find_spec(row.get("pipeline") or "empirical")
    except Exception as e:  # noqa: BLE001 — without its template the steps are unknown
        raise HTTPException(status_code=409, detail=f"the study's template cannot be loaded: {e}") from e
    state = PipelineState.load(workspace, paper_id, row.get("mode") or "single_pass")
    try:
        payload = apply_rerun(workspace, state, spec, req.step, req.remark)
    except ResearcherActionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state.save(workspace)
    await log_event(paper_id, "researcher_action", stage=req.step, payload=payload)
    # A completed study is terminal for resume; the rerun makes it resumable.
    await execute(
        "UPDATE papers SET status = 'paused', last_error = NULL, updated_at = NOW() WHERE id = %(id)s",
        {"id": paper_id},
    )
    shown = {**payload, "rerun_labels": [_step_label(n, spec) for n in payload.get("reruns") or []]}
    return {"recorded": shown, "resumed": await resume_paper(paper_id)}


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
            "SELECT id, status, workspace, mode, max_cost_usd, methodology, backend, model, governance, "
            "review_stages, pipeline, run_owner, heartbeat_at FROM papers WHERE id = %(id)s",
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

    elsewhere = await _running_elsewhere({**row, "id": paper_id})
    if elsewhere:
        raise HTTPException(status_code=409, detail=_elsewhere_text(elsewhere))

    workspace = Path(row["workspace"])
    mode = row.get("mode") or "single_pass"
    cap = float(row.get("max_cost_usd") or get_settings().default_max_cost_usd)
    methodology = row.get("methodology") or "empirical"
    # Read from the row, never re-chosen: half a run's state on disk was
    # produced by one DAG, and resuming under a different one would skip or
    # repeat stages depending on which steps the two pipelines happen to share.
    pipeline = row.get("pipeline") or "empirical"
    backend_name = row.get("backend")  # None → server default at run time
    model = row.get("model")
    governance = row.get("governance")  # None → server default at run time
    try:
        review_stages = json.loads(row.get("review_stages") or "[]")
    except (TypeError, ValueError):
        review_stages = []

    # If this pause was a human-review checkpoint, approve the pending stage so
    # the resumed run continues past it instead of immediately re-pausing.
    try:
        from ..core.pipeline.state import PipelineState

        pstate = PipelineState.load(workspace, paper_id, mode)
        # After a send-back the researcher wants to see the redone step, so the
        # pending researcher step stays unapproved and the run stops there again.
        # A stop for output that failed its contract is never approved by a plain
        # resume: approving it is the researcher's decision (e2er review --approve);
        # a resume gives the failed specialists fresh attempts.
        contract_stop = (pstate.metadata.get("review") or {}).get("kind") == "contract"
        # Nor is the number check: continuing with mismatches is the researcher's
        # decision too; a plain resume runs the check again.
        numbers_stop = (pstate.metadata.get("review") or {}).get("kind") == "numbers"
        if (
            pstate.pending_review_stage
            and not pstate.metadata.get("sent_back")
            and not contract_stop
            and not numbers_stop
        ):
            pstate.approve(pstate.pending_review_stage)
            pstate.save(workspace)
    except Exception as e:  # noqa: BLE001 — approval is best-effort; resume proceeds
        logger.warning("Could not clear review checkpoint on resume %s: %s", paper_id, e)

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

    task = asyncio.create_task(
        _run_pipeline(
            paper_id,
            workspace,
            mode,
            cap,
            methodology,
            backend_name,
            model,
            governance,
            review_stages,
            pipeline=pipeline,
        )
    )
    await _track_run(paper_id, task)

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

    workspace = _workspace_of(paper_id)

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
    """ "Download all files": every file of the run's folder, and its records from the database
    (manifest.json, contributions.json, events.json, usage.json).
    """
    from ..db.client import fetch_all, fetch_one
    from ..modules.tracking.usage import get_paper_usage as _get_usage

    paper_row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not paper_row:
        raise HTTPException(status_code=404, detail="Paper not found")
    workspace = _paper_workspace(dict(paper_row))
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

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

        # Every file of the run's folder ("Download all files"), without hidden files: the
        # run's saved state, earlier versions of outputs (.history) and lock files.
        records = {"manifest.json", "contributions.json", "events.json", "usage.json"}
        for arc in _visible_files(workspace):
            tar.add(workspace / arc, arcname=f"run-{arc}" if arc in records else arc)

    buf.seek(0)
    from ..home import slug

    name = f"e2er-{slug(str(paper_row.get('title') or 'study'))}-files.tar.gz"
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
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
    """Health plus the identity of THIS process — the authoritative answer to
    "which code is the server actually running?". The server does not reload on
    edit, so a client must ask rather than assume."""
    import os as _os

    from ..core.run_identity import run_identity

    return {
        "status": "ok",
        "service": "e2er-v3",  # an id scripts check, kept
        "identity": run_identity(),
        # Lets `e2er` tell its own server from another one on the same port (session file).
        "process": {"pid": _os.getpid(), "ppid": _os.getppid()},
    }


# --- Dashboard (Jinja2 + HTMX) ---

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@app.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request, q: str = "", archived: str | None = None) -> Any:
    """Studies list — landing page. The first time, the setup page instead."""
    from .setup import needs_setup
    from .studies import studies_page

    if needs_setup():
        return RedirectResponse(url="/setup", status_code=303)
    return await studies_page(request, q=q, archived=archived)


def _workflow_inventory() -> dict[str, Any]:
    """The specialist roster and skill wiring of this install.

    Read from the registry at request time rather than from a checked-in
    document, so the page cannot describe a different version than the one
    serving it.
    """
    from ..core.specialists.registry import (
        SPECIALIST_ARTIFACTS,
        SPECIALIST_SIDECAR_ARTIFACTS,
        SPECIALIST_SKILLS,
    )

    # The loader searches two locations (installed package, development
    # checkout). Reuse its list so this page cannot describe a directory the
    # loader does not read.
    from ..skills.loader import _SKILLS_DIRS

    found: set[str] = set()
    for root in _SKILLS_DIRS:
        if root.is_dir():
            found.update(p.relative_to(root).with_suffix("").as_posix() for p in root.rglob("*.md"))
    on_disk = sorted(found)

    used: set[str] = set()
    users: dict[str, list[str]] = {}
    names = sorted(set(SPECIALIST_ARTIFACTS) | set(SPECIALIST_SKILLS))
    for name in names:
        for skill in SPECIALIST_SKILLS.get(name, []):
            used.add(skill)
            users.setdefault(skill, []).append(name)

    specialists = [
        {
            "name": name,
            "artifact": SPECIALIST_ARTIFACTS.get(name, ""),
            "sidecars": list(SPECIALIST_SIDECAR_ARTIFACTS.get(name, [])),
            "skills": SPECIALIST_SKILLS.get(name, []),
        }
        for name in names
    ]
    unused = [s for s in on_disk if s not in used]
    missing = sorted(s for s in used if s not in on_disk)

    return {
        "specialists": specialists,
        "unused": unused,
        "missing": missing,
        "s_users": users,
        "counts": {
            "specialists": len(specialists),
            "on_disk": len(on_disk),
            "referenced": len(used),
            "unused": len(unused),
            "missing": len(missing),
        },
    }


async def _preflight() -> dict[str, Any]:
    """Run the same checks `e2er doctor` runs."""
    from ..doctor import _BLOCKERS_PREFIXES, FAIL, PASS, SKIP, run_doctor

    try:
        checks = await run_doctor(get_settings())
    except Exception as e:  # noqa: BLE001 — a broken check must not break the page
        logger.warning("preflight failed to run: %s", e)
        return {"checks": [], "ready": False, "error": str(e)[:200], "n_fail": 0}

    rows = [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks]
    blockers = [c for c in checks if c.status == FAIL and c.name.startswith(_BLOCKERS_PREFIXES)]
    return {
        "checks": rows,
        "ready": not blockers,
        "blockers": [c.name for c in blockers],
        "n_pass": sum(1 for c in checks if c.status == PASS),
        "n_skip": sum(1 for c in checks if c.status == SKIP),
        "n_fail": sum(1 for c in checks if c.status == FAIL),
        "error": "",
    }


@app.get("/preflight", response_class=HTMLResponse)
async def dashboard_preflight(request: Request) -> Any:
    """Is this machine able to run a paper?"""
    return templates.TemplateResponse(request, "preflight.html", await _preflight())


@app.get("/htmx/preflight-banner", response_class=HTMLResponse)
async def preflight_banner(request: Request) -> Any:
    """Small banner for the new-paper form, so the answer arrives before the ask."""
    return templates.TemplateResponse(request, "_preflight_banner.html", await _preflight())


@app.get("/workflow", response_class=HTMLResponse)
async def dashboard_workflow(request: Request) -> Any:
    """Which specialists exist, what they are told, and what nothing loads."""
    return templates.TemplateResponse(request, "workflow.html", _workflow_inventory())


def _library_view(query: str = "", limit: int = 25) -> dict[str, Any]:
    """The corpus, for the browser.

    Everything the corpus does was terminal-only, which meant that for anyone
    who reaches E2ER by typing `e2er` and getting a dashboard — the normal
    case — it did not exist. Searching your own library by claim is the thing
    E2ER does that nothing else does, and it was invisible.

    Degrades to an empty page rather than an error when no corpus has been
    built: that is a first-run state, not a fault.
    """
    from ..modules.literature import corpus as corpus_mod

    view: dict[str, Any] = {
        "query": query,
        "hits": [],
        "papers": [],
        "stats": None,
        "path": str(corpus_mod.corpus_path()),
        "exists": corpus_mod.corpus_path().is_file(),
        "error": "",
    }
    if not view["exists"]:
        return view

    try:
        with corpus_mod.connect() as conn:
            stats = corpus_mod.stats(conn)
            view["stats"] = stats.to_dict()
            if query.strip():
                view["hits"] = [h.to_dict() for h in corpus_mod.search_claims(conn, query, limit=limit)]
            else:
                view["papers"] = [p.to_dict() for p in corpus_mod.list_papers(conn, limit=limit)]
    except Exception as e:  # noqa: BLE001 — a broken corpus must not break the dashboard
        logger.warning("library page: corpus unreadable: %s", e)
        view["error"] = str(e)[:300]
    return view


@app.get("/library", response_class=HTMLResponse)
async def dashboard_library(request: Request, q: str = "", message: str = "") -> Any:
    """Search what the papers you have read actually claim; add papers to the Library."""
    from .inputs import _ADDING
    from .local_session import local_problem

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            **_library_view(q),
            "message": message,
            "adding": dict(_ADDING),
            "session_problem": local_problem(request),
        },
    )


def _skills_view(message: str = "") -> dict[str, Any]:
    """The RISE catalogue, and what is installed from it.

    358 skills published by a dozen research projects, previously reachable only
    by knowing that `e2er skills` exists. A catalogue nobody can browse is a
    catalogue nobody uses.
    """
    from ..modules import skills_catalogue as sc

    view: dict[str, Any] = {
        "packs": [],
        "installed": {p["slug"]: p for p in sc.installed_packs()},
        "catalogue_path": str(sc.catalogue_path()),
        "install_root": str(sc.install_root()),
        "error": "",
        "message": message,
        "totals": {"packs": 0, "skills": 0},
    }
    try:
        packs = sc.read_catalogue()
    except sc.CatalogueError as e:
        from ..core.labels import NETWORK_ERROR

        # A network error in words; what went wrong stays under Technical details.
        view["error"] = (
            "The skills catalogue (RISE, on GitHub) could not be reached. Check the internet connection and open "
            "this page again. Without the internet, copy the catalogue once and point e2er to it:"
            if NETWORK_ERROR.search(str(e))
            else str(e)
        )
        view["error_detail"] = str(e)
        return view

    view["packs"] = [
        {
            "slug": p.slug,
            "name": p.name,
            "license": p.license,
            "source_url": p.source_url,
            "maintainers": list(p.maintainers),
            "notes": p.notes,
            "count": len(p.skills),
            "redistributable": p.redistributable,
        }
        for p in packs
    ]
    view["totals"] = {"packs": len(packs), "skills": sum(len(p.skills) for p in packs)}
    return view


@app.get("/skills", response_class=HTMLResponse)
async def dashboard_skills(request: Request, message: str = "") -> Any:
    """Browse the RISE catalogue and install a pack."""
    return templates.TemplateResponse(request, "skills.html", _skills_view(message))


@app.post("/skills/install", dependencies=[Depends(require_auth)])
async def install_skill_pack(pack: str = Form(...)) -> Any:
    """Fetch one pack from its own source.

    A POST that redirects, rather than an API the page polls: installing is a
    handful of small file fetches, and a spinner would be more machinery than
    the operation deserves.
    """
    from ..modules import skills_catalogue as sc

    try:
        found = sc.find_pack(pack)
        report = await sc.install_pack(found)
        note = f"{found.name}: {report['installed']} installed, {report['failed']} failed."
    except sc.CatalogueError as e:
        from ..core.labels import NETWORK_ERROR

        note = (
            f"Could not install {pack}: GitHub could not be reached. Check the internet connection and try again."
            if NETWORK_ERROR.search(str(e))
            else f"Could not install {pack}: {e}"
        )
    except Exception as e:  # noqa: BLE001 — a bad pack must not 500 the dashboard
        logger.warning("skill pack install failed for %s: %s", pack, e)
        note = f"Could not install {pack}: {e}"

    return RedirectResponse(url=f"/skills?message={quote_plus(note)}", status_code=303)


#: The order the built-in templates are offered in; others follow by name.
_TEMPLATE_ORDER = ("empirical", "empirical-preregistered", "event-study-finance", "replication")


def _step_label(name: str, spec: Any = None) -> str:
    return _labels.step(name, spec)


def _new_form_context(
    values: dict[str, Any] | None = None, error: str = "", request: Request | None = None
) -> dict[str, Any]:
    from ..core.study_inputs import data_options
    from ..modules.local_corpus import DATA_EXTENSIONS, DATA_EXTENSIONS_TEXT
    from .local_session import local_problem
    from .setup import needs_setup

    settings = get_settings()
    v = {
        "research_question": "",
        "title": "",
        "pipeline": "empirical",
        "mode": "single_pass",
        "methodology": "empirical",
        "max_cost_usd": settings.default_max_cost_usd,
        "demonstration": False,
        "review_at": [],
        # None: nothing chosen yet, so every file of the data folder is ticked (what a study took before 0.15.0).
        "data_files": None,
        "papers": None,
        "only_my_papers": False,
        **(values or {}),
    }
    problem = local_problem(request) if request is not None else ""
    try:
        files = [] if problem else data_options(settings)
    except OSError as e:  # a data folder that cannot be read must not break the page
        logger.warning("New study: the data folder could not be listed: %s", e)
        files = []
    chosen = v["data_files"]
    data_rows = [{**f.__dict__, "ticked": chosen is None or f.path in chosen} for f in files]
    return {
        "data_rows": data_rows,
        "data_dir": getattr(settings, "local_data_dir", None) or "",
        "data_accept": ",".join(sorted(DATA_EXTENSIONS)),
        "data_types": DATA_EXTENSIONS_TEXT,
        "files_problem": problem,
        "papers_query": "picked=1&" + "&".join(f"chosen={quote_plus(x)}" for x in v["papers"])
        if v["papers"] is not None
        else "",
        "default_cap": settings.default_max_cost_usd,
        "pipelines": _pipeline_choices(),
        "values": v,
        "error": error,
        "backend": getattr(settings, "llm_backend", ""),
        "billed": getattr(settings, "llm_backend", "") in {"anthropic", "openrouter"},
        # Gemini (not tested) runs on a Gemini API key that e2er does not count.
        "uncounted_key": getattr(settings, "llm_backend", "") == "gemini",
        "needs_setup": needs_setup(),
    }


@app.get("/papers/new", response_class=HTMLResponse)
async def new_paper_form(request: Request) -> Any:
    return templates.TemplateResponse(request, "new.html", _new_form_context(request=request))


def _pipeline_choices() -> list[dict[str, Any]]:
    """Every pipeline the runner could resolve, with its own description and pauses.

    The names come from the files on disk, so a pipeline someone drops into
    ./pipelines or ~/.e2er/pipelines appears in the form without E2ER being
    changed — which is the whole reason pipelines are files.

    A spec that will not parse is listed by name rather than dropped. Hiding it
    would mean a typo in a TOML file presents as "my pipeline vanished", with
    nowhere to look; listing it means the error surfaces at submit time, where
    it names the file and the problem.
    """
    from ..core.pipeline.spec import PipelineError, available, load_spec

    out: list[dict[str, Any]] = []
    found = available()
    names = [n for n in _TEMPLATE_ORDER if n in found] + sorted(n for n in found if n not in _TEMPLATE_ORDER)
    for name in names:
        path = found[name]
        try:
            spec = load_spec(path)
            out.append(
                {
                    "name": name,
                    "label": _labels.template(name, spec),
                    "description": spec.description,
                    "pauses": [_step_label(st.name, spec) for st in spec.steps if _is_stop(st)],
                    # "Also stop for you after these steps": this template's own steps.
                    "review_choices": [{"name": n, "label": _step_label(n, spec)} for n in _review_at_choices(spec)],
                }
            )
        except (PipelineError, OSError) as e:
            logger.warning("pipeline %s at %s did not parse: %s", name, path, e)
            out.append(
                {
                    "name": name,
                    "label": _labels.template(name),
                    "description": "(this file did not parse)",
                    "pauses": [],
                    "review_choices": [],
                }
            )
    return out


def _is_stop(st: Any) -> bool:
    from ..core.pipeline.spec import RESEARCHER_KINDS

    return st.kind in RESEARCHER_KINDS


def _review_at_choices(spec: Any) -> list[str]:
    """Steps a researcher may ask the run to stop after: the template's own, not its stops or inner checks."""
    return [st.name for st in spec.steps if not _is_stop(st) and not st.after]


#: The largest file New study accepts (each file).
_UPLOAD_MAX_BYTES = 200 * 1024 * 1024


async def _save_uploads(files: list[Any], folder: Path, allowed: set[str], what: str) -> list[Path]:
    """Save the files added on New study into ``folder``; a wrong type or a file too large is refused in a sentence."""
    from ..core.study_inputs import InputError

    saved: list[Path] = []
    for f in files:
        name = Path(str(getattr(f, "filename", "") or "")).name
        if not name:
            continue  # an empty "Add files" field
        if Path(name).suffix.lower() not in allowed:
            raise InputError(f"{name} is not {what}.")
        target = folder / name
        n = 2
        while target.exists():
            target = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
            n += 1
        written = 0
        with target.open("wb") as out:
            while chunk := await f.read(1024 * 1024):
                written += len(chunk)
                if written > _UPLOAD_MAX_BYTES:
                    raise InputError(f"{name} is larger than {_UPLOAD_MAX_BYTES // (1024 * 1024)} MB.")
                out.write(chunk)
        saved.append(target.resolve())
    return saved


@app.post("/papers", dependencies=[Depends(require_auth)])
async def submit_new_paper(
    request: Request,
    research_question: str = Form(...),
    title: str = Form(""),
    mode: str = Form("single_pass"),
    methodology: str = Form("empirical"),
    pipeline: str = Form("empirical"),
    max_cost_usd: float | None = Form(None),
    demonstration: str = Form(""),
    review_at: list[str] = Form([]),
    data_choice: str = Form(""),
    data_file: list[str] = Form([]),
    paper_choice: str = Form(""),
    paper: list[str] = Form([]),
    only_my_papers: str = Form(""),
) -> Any:
    """Form-encoded handler that mirrors POST /api/papers. Redirects to the progress page.

    A refusal (a first run over the $1 floor, an unknown template, a file that
    cannot be read) is shown on the form, with what was typed kept. The form
    needs the dashboard's session cookie (require_auth), as the JSON /api/papers
    does; a tab without it gets the "not signed in" page.

    The data files and papers ticked on the form are what the study uses
    (``data_choice``/``paper_choice`` say the form offered the choice); files
    added with "Add files" come with the form and are copied into the study.
    """
    from ..cli_run import derive_title
    from ..core.demonstration import DEMONSTRATION
    from ..core.study_inputs import InputError, new_upload_folder
    from ..modules.local_corpus import DATA_EXTENSIONS, DATA_EXTENSIONS_TEXT

    rq = research_question.strip()
    values = {
        "research_question": research_question,
        "title": title,
        "pipeline": pipeline,
        "mode": mode,
        "methodology": methodology,
        "max_cost_usd": max_cost_usd,
        "demonstration": bool(demonstration),
        "review_at": list(review_at),
        "data_files": list(data_file) if data_choice else None,
        "papers": list(paper) if paper_choice else None,
        "only_my_papers": bool(only_my_papers),
    }

    def refuse(message: str, status: int = 422) -> Any:
        return templates.TemplateResponse(
            request, "new.html", _new_form_context(values, message, request), status_code=status
        )

    if not rq:
        return refuse("Write the research question first.")
    form = await request.form()
    folder = new_upload_folder()
    try:
        try:
            added_data = await _save_uploads(
                form.getlist("data_upload"),
                folder,
                set(DATA_EXTENSIONS),
                f"a data file e2er can read ({DATA_EXTENSIONS_TEXT})",
            )
            added_papers = await _save_uploads(
                form.getlist("paper_upload"), folder, {".pdf", ".bib"}, "a paper e2er can read (.pdf or .bib)"
            )
        except InputError as e:
            return refuse(f"{e} Nothing was started; add the files again.")
        backend = get_settings().llm_backend
        data_files = [*data_file, *map(str, added_data)] if (data_choice or added_data) else None
        papers = [*paper, *map(str, added_papers)] if (paper_choice or added_papers) else None
        req = CreatePaperRequest(
            title=title.strip() or derive_title(rq),
            research_question=rq,
            mode=mode,
            methodology=methodology,
            pipeline=pipeline,
            max_cost_usd=max_cost_usd,
            # The CLI backends run on the researcher's subscription at $0, so the
            # $1 first-run floor protects nothing there (as `e2er run` does).
            acknowledge_unproven_tuple=backend in {"claude_code", "codex", "gemini"},
            purpose=DEMONSTRATION if demonstration else None,
            review_stages=list(dict.fromkeys(review_at)),
            data_files=data_files,
            papers=papers,
            web_search=not only_my_papers,
        )
        bg = BackgroundTasks()
        try:
            resp = await create_paper(req, bg)
        except HTTPException as e:
            return refuse(
                str(e.detail) + (" Add the files again." if (added_data or added_papers) else ""), e.status_code
            )
    finally:
        # The added files are in the study now (copied when it started); the waiting folder goes.
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
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
    workspace = _paper_workspace(dict(paper))
    if workspace.exists():
        artifacts = _visible_files(workspace)
    else:
        artifacts = []

    from ..db.studies import attempt_context

    return templates.TemplateResponse(
        request,
        "paper.html",
        {
            "paper": _with_outcome(dict(paper)),
            **_study_actions(dict(paper), workspace),
            "study": await attempt_context(paper_id),
            "artifacts": artifacts,
            "reading": _reading_list(artifacts),
            # The "Data and papers" panel follows a run that is preparing or working.
            "inputs_live": str(paper.get("status") or "") in IN_FLIGHT or paper_id in _RUNNING,
            "groups": _artifact_groups(
                workspace,
                artifacts,
                str(paper.get("mode") or ""),
                str(paper.get("methodology") or ""),
                unfinished=str(paper.get("status") or "")
                not in {"completed", "failed", "cancelled", "rejected", "stopped"},
            )
            if workspace.exists()
            else [],
        },
    )


def _study_actions(paper: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """What the study page offers beside the live panel: rerun steps, the purpose, the pre-registration."""
    from ..core.demonstration import study_purpose
    from ..core.pipeline.preregistration import load_lock
    from ..core.pipeline.researcher import rerunnable_steps
    from ..core.pipeline.spec import find_spec

    mode = str(paper.get("mode") or "single_pass")
    try:
        spec = find_spec(str(paper.get("pipeline") or "empirical"))
        names = rerunnable_steps(spec, mode)
    except Exception:  # noqa: BLE001 — without its template there is nothing to choose from
        spec, names = None, []
    try:
        demonstration = study_purpose(workspace if workspace.is_dir() else None) == "demonstration"
    except ValueError:
        demonstration = False
    lock = None
    if workspace.is_dir():
        try:
            lock = load_lock(workspace / "design") or load_lock(workspace)
        except (OSError, ValueError):
            lock = None
    return {
        "rerun_steps": [{"name": n, "label": _step_label(n, spec)} for n in names],
        "demonstration": demonstration,
        "prereg": lock,
        "suggested_cap": round(float(paper.get("max_cost_usd") or get_settings().default_max_cost_usd) * 2, 2),
        "template_label": _labels.template(str(paper.get("pipeline") or "empirical"), spec),
        # The live panel corrects this every few seconds (a run that starts or stops).
        "rerun_open": paper.get("status") in _RERUN_STATUSES and str(paper.get("id")) not in _RUNNING,
    }


#: Pipeline phases in execution order, and the specialists that belong to each.
#: Artifact attribution itself comes from the registry; this only says when.
_PHASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Design", ("idea_developer", "literature_scanner", "identification_strategist", "theory_specialist")),
    ("Data", ("data_architect", "data_analyst")),
    ("Estimation", ("econometrics_specialist",)),
    ("Drafting", ("paper_drafter", "section_writer", "abstract_writer", "latex_formatter")),
    (
        "Self-critique and polish",
        (
            "self_attacker",
            "polish_formula",
            "polish_numerics",
            "polish_institutions",
            "polish_equilibria",
            "polish_bibliography",
        ),
    ),
    (
        "Review",
        (
            "mechanism_reviewer",
            "technical_reviewer",
            "literature_reviewer",
            "data_reviewer",
            "identification_reviewer",
            "writing_reviewer",
        ),
    ),
    ("Revision", ("revisor", "patch_revisor")),
    ("Replication", ("replication_packager",)),
)


def _gate_verdicts(workspace: Path) -> list[dict[str, Any]]:
    """Read the deterministic gate reports the run already wrote.

    These are the run's own verdicts. Recomputing them here would let the page
    disagree with the pipeline about what happened.
    """
    import json as _json

    out: list[dict[str, Any]] = []

    def _load(name: str) -> dict[str, Any] | None:
        path = workspace / name
        if not path.is_file():
            return None
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    if (d := _load("table_render_report.json")) is not None:
        bad = bool(d.get("unresolved")) or bool(d.get("errors"))
        n = len(d.get("rendered") or [])
        out.append(
            {
                "name": "table_render_report.json",
                "label": "Tables",
                "ok": not bad,
                "note": f"{n} rendered, {len(d.get('unresolved') or [])} unresolved",
            }
        )

    if (d := _load("number_verification.json")) is not None:
        crit = [m for m in (d.get("mismatches") or []) if m.get("severity") == "critical"]
        traced = d.get("matched", 0)
        out.append(
            {
                "name": "number_verification.json",
                "label": "Numbers",
                "ok": not crit,
                "note": f"{traced} cells trace, {len(crit)} critical",
            }
        )

    if (d := _load("citation_integrity.json")) is not None:
        out.append(
            {
                "name": "citation_integrity.json",
                "label": "Citations",
                "ok": bool(d.get("passed")),
                "note": f"{d.get('verified', 0)}/{d.get('total_cites', 0)} verified, "
                f"{d.get('missing_in_bib', 0)} missing",
            }
        )

    if (d := _load("review_aggregation.json")) is not None:
        from ..core.run_outcome import review_detail

        if detail := review_detail(d):
            # A score, not a check: neither passed nor failed.
            out.append(
                {
                    "name": "review_aggregation.json",
                    "label": "Internal quality review",
                    "ok": None,
                    "note": detail,
                }
            )

    return out


#: The outputs a person actually wants to read, most-wanted first.
_READABLE: tuple[tuple[str, str, bool], ...] = (
    ("paper_draft.pdf", "Read the paper", True),
    ("paper_draft.tex", "LaTeX source", False),
    ("abstract.tex", "Abstract", False),
    ("data_summary.md", "Data summary", False),
    ("identification_strategy.md", "Identification strategy", False),
    ("review_aggregation.json", "Internal quality review score", False),
)


def _reading_list(artifacts: list[str]) -> list[dict[str, Any]]:
    """Surface the paper and the few documents worth opening directly."""
    present = set(artifacts)
    return [{"path": path, "label": label, "primary": primary} for path, label, primary in _READABLE if path in present]


def _artifact_groups(
    workspace: Path,
    artifacts: list[str],
    mode: str = "",
    methodology: str = "",
    unfinished: bool = False,
) -> list[dict[str, Any]]:
    """Sort a paper's files under the phase that produced them, with a status.

    While the run is still going (``unfinished``: working, or waiting at a stop), a part
    with none of its files yet has not run: it is shown as "not run yet", not in red.

    A declared artifact that is absent is reported as a missing row rather than
    left out, because "the drafter never wrote paper_draft.tex" is the single
    most useful thing this page can tell you.
    """
    from ..core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SIDECAR_ARTIFACTS

    present = set(artifacts)
    sizes: dict[str, int] = {}
    for rel in artifacts:
        try:
            sizes[rel] = (workspace / rel).stat().st_size
        except OSError:
            sizes[rel] = 0

    claimed: set[str] = set()
    groups: list[dict[str, Any]] = []

    # single_pass skips the iterative loop entirely; an empirical paper never
    # dispatches the theory specialist. Phases that were never meant to run are
    # reported as such rather than as missing output.
    iterative = (mode or "").lower() == "iterative"
    empirical = (methodology or "empirical").lower() == "empirical"
    skipped_phases = set() if iterative else {"Self-critique and polish"}
    skipped_specialists = {"theory_specialist"} if empirical else set()

    for phase_name, specialists in _PHASES:
        declared: list[str] = []
        for sp in specialists:
            if sp in skipped_specialists:
                continue
            if art := SPECIALIST_ARTIFACTS.get(sp):
                declared.append(art)
            declared.extend(SPECIALIST_SIDECAR_ARTIFACTS.get(sp, []))

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rel in declared:
            if rel in seen:
                continue
            seen.add(rel)
            if rel in present:
                claimed.add(rel)
                empty = sizes.get(rel, 0) == 0
                rows.append(
                    {
                        "p": rel,
                        "b": sizes.get(rel, 0),
                        "status": "fail" if empty else "pass",
                        "note": "written but empty" if empty else "",
                    }
                )
            else:
                rows.append({"p": rel, "b": 0, "status": "missing", "note": "not written"})

        if not rows:
            continue
        if phase_name in skipped_phases:
            groups.append(
                {
                    "name": phase_name,
                    "status": "none",
                    "note": "only in the longer, iterative run",
                    "files": [dict(r, status="none", note="") for r in rows],
                }
            )
            continue
        if unfinished and all(r["status"] == "missing" for r in rows):
            groups.append(
                {
                    "name": phase_name,
                    "status": "none",
                    "note": "not run yet",
                    "files": [dict(r, status="none", note="") for r in rows],
                }
            )
            continue
        failed = [r for r in rows if r["status"] != "pass"]
        groups.append(
            {
                "name": phase_name,
                "status": "fail" if failed else "pass",
                "note": f"{len(rows) - len(failed)}/{len(rows)} produced",
                "files": rows,
            }
        )

    gates = _gate_verdicts(workspace)
    if gates:
        rows = []
        for g in gates:
            claimed.add(g["name"])
            rows.append(
                {
                    "p": g["name"],
                    "b": sizes.get(g["name"], 0),
                    "status": "none" if g["ok"] is None else "pass" if g["ok"] else "fail",
                    "note": f"{g['label']}: {g['note']}",
                }
            )
        checked = [r for r in rows if r["status"] != "none"]
        groups.append(
            {
                "name": "Checks",
                "status": "fail" if any(r["status"] == "fail" for r in rows) else "pass",
                "note": f"{sum(1 for r in checked if r['status'] == 'pass')}/{len(checked)} passed",
                "files": rows,
            }
        )

    rest = sorted(present - claimed)
    if rest:
        groups.append(
            {
                "name": "Working files",
                "status": "none",
                "note": f"{len(rest)} files",
                "files": [{"p": r, "b": sizes.get(r, 0), "status": "none", "note": ""} for r in rest],
            }
        )

    return groups


#: Phases in the order the runner executes them, for the progress strip.
_PHASE_ORDER = (
    "initial",
    "iterative",
    "estimation_gate",
    "self_attack",
    "polish",
    "review",
    "revision",
    "replication",
)


def _progress(events: list[dict[str, Any]], paper: dict[str, Any]) -> dict[str, Any]:
    """What is running now, for how long, and which phases are done.

    `events` arrives newest-first. A specialist with a start and no matching
    end is still working; the same holds for phases.
    """
    from datetime import datetime

    def _ts(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None

    now = datetime.now(UTC)
    ordered = list(reversed(events))  # oldest first

    running: dict[str, datetime | None] = {}
    finished_phases: list[str] = []
    open_phases: list[str] = []
    first_ts: datetime | None = None

    for e in ordered:
        ts = _ts(e.get("created_at"))
        if first_ts is None and ts is not None:
            first_ts = ts
        etype = str(e.get("event_type") or "")
        who = e.get("specialist")
        stage = str(e.get("stage") or "")

        if etype == "specialist_start" and who:
            running[str(who)] = ts
        elif etype in {"specialist_end", "specialist_failed"} and who:
            running.pop(str(who), None)
        elif etype == "phase_start" and stage:
            if stage not in open_phases:
                open_phases.append(stage)
        elif etype == "phase_end" and stage:
            if stage in open_phases:
                open_phases.remove(stage)
            if stage not in finished_phases:
                finished_phases.append(stage)

    def _mins(since: datetime | None) -> int | None:
        if since is None:
            return None
        return max(0, int((now - since).total_seconds() // 60))

    active = [{"name": name, "minutes": _mins(started)} for name, started in sorted(running.items())]

    terminal = str(paper.get("status") or "") in {"completed", "failed", "cancelled", "rejected", "paused"}

    phases = [
        {
            "name": p,
            "state": "done" if p in finished_phases else ("running" if p in open_phases else "pending"),
        }
        for p in _PHASE_ORDER
        if p in finished_phases or p in open_phases or not terminal
    ]

    return {
        "active": active,
        "elapsed_min": _mins(first_ts),
        "phases": phases,
        "terminal": terminal,
    }


def _template_progress(paper: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """The study's template steps with their state, the specialists done, and the checks.

    Read from the template file, the run's saved state and its event log, so the
    page shows the steps this study's template has rather than a fixed list.
    """
    from ..core.pipeline.spec import find_spec
    from ..core.pipeline.state import PipelineState

    name = str(paper.get("pipeline") or "empirical")
    mode = str(paper.get("mode") or "single_pass")
    status = str(paper.get("status") or "")
    workspace = _paper_workspace(paper)
    try:
        spec = find_spec(name)
    except Exception:  # noqa: BLE001 — a missing template must not break the page
        spec = None
    try:
        state = PipelineState.load(workspace, str(paper.get("id")), mode)
    except Exception:  # noqa: BLE001
        state = None
    completed = set(state.completed_stages if state else []) | set(state.approved_stages if state else [])
    pending = state.pending_review_stage if state else None

    opened: list[str] = []
    finished: set[str] = set()
    halted: set[str] = set()
    done_specialists: list[str] = []
    failed_specialists: list[str] = []
    for e in reversed(events):  # oldest first
        et, stage, who = str(e.get("event_type") or ""), str(e.get("stage") or ""), e.get("specialist")
        if et == "phase_start" and stage:
            opened.append(stage)
        elif et == "phase_end" and stage:
            finished.add(stage)
        elif et == "gate_halted" and stage:
            halted.add(stage)
        elif et == "specialist_end" and who and who not in done_specialists:
            done_specialists.append(str(who))
            if who in failed_specialists:
                failed_specialists.remove(str(who))
        elif et == "specialist_failed" and who and who not in failed_specialists and who not in done_specialists:
            failed_specialists.append(str(who))

    if pending == "number_check":
        # The number check runs inside the review step: show its stop on that row.
        halted.add("review")
        pending = "review"
    steps: list[dict[str, Any]] = []
    if spec is not None:
        inner = [st for st in spec.steps if st.after]
        for st in spec.steps:
            if st.after:
                continue
            steps.append(
                _step_row(st, mode, status, completed, pending, opened, finished, halted, sub=False, spec=spec)
            )
            if st.kind == "strategist" and st.name == "initial":
                steps.extend(
                    _step_row(x, mode, status, completed, pending, opened, finished, halted, sub=True, spec=spec)
                    for x in inner
                )
    rounds = _labels.round_summary(events)
    critique = _self_critique(events)
    polish = _polish_note(events)
    for row in steps:
        if row["name"] == "iterative" and rounds and row["state"] in {"done", "running"}:
            n = len(rounds)
            note = f"{n} round{'s' if n != 1 else ''}"
            if any(r.get("pivot") for r in rounds):
                note += ", then a change of approach"
            row["note"] = note if row["state"] == "done" else f"{note} so far; running now"
        if row["name"] == "self_attack" and critique and row["state"] == "done":
            row["note"] = critique["note"]
        if row["name"] == "polish" and polish and row["state"] == "done":
            row["note"] = polish
    current = next((s["label"] for s in steps if s["state"] in {"waiting", "running"}), "")
    return {
        "rounds": rounds,
        "self_critique": critique,
        "polish": polish,
        "template": name,
        "template_label": _labels.template(name, spec),
        "steps": steps,
        "current": current,
        "specialists_done": done_specialists,
        "specialists_failed": failed_specialists,
        "checks": _gate_verdicts(workspace) if workspace.is_dir() else [],
    }


def _self_critique(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The last self-critique of the run in plain words (the ``self_critique`` event), or None."""
    for e in events:  # most recent first
        if str(e.get("event_type") or "") != "self_critique":
            continue
        data = e.get("payload")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        if not isinstance(data, dict):
            return None
        n, serious = int(data.get("findings") or 0), int(data.get("serious") or 0)
        if not n:
            note = "no findings"
        else:
            note = f"{n} finding{'s' if n != 1 else ''}, {serious} serious"
            if "corrections_made" in data:
                made = int(data.get("corrections_made") or 0)
                note += f"; {made} correction{'s' if made != 1 else ''} made in the draft"
        return {"findings": n, "serious": serious, "note": note}
    return None


def _polish_note(events: list[dict[str, Any]]) -> str:
    """What became of the polish notes (the ``polish_applied`` event), in plain words; empty when not recorded."""
    for e in events:  # most recent first
        if str(e.get("event_type") or "") != "polish_applied":
            continue
        data = e.get("payload")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        if not isinstance(data, dict):
            return ""
        n = len(data.get("notes") or [])
        made = int(data.get("changes_made") or 0)
        notes = f"{n} note{'s' if n != 1 else ''}"
        if made:
            return f"{notes}; {made} change{'s' if made != 1 else ''} made in the draft"
        return f"{notes}; {data.get('decision') or 'no change'}"
    return ""


def _step_row(
    st, mode, status, completed, pending, opened, finished, halted, *, sub: bool, spec=None
) -> dict[str, Any]:
    label = _step_label(st.name, spec)
    kind = _labels.step_kind(st.kind)
    if not st.applies_to(mode):
        state, note = "skipped", "only in the longer, iterative run" if mode == "single_pass" else "not in this run"
    elif pending == st.name and status == "paused":
        state, note = ("failed", "failed; waiting for you") if st.name in halted else ("waiting", "waiting for you")
    elif st.name in completed or (st.name in finished and st.name != pending):
        state, note = "done", ""
    elif st.name in halted and status in {"paused", "rejected", "failed"}:
        state, note = "failed", "failed"
    elif st.name in opened and status not in {"completed", "failed", "cancelled", "rejected", "paused"}:
        state, note = "running", "running now"
    else:
        state, note = "pending", ""
    return {"name": st.name, "label": label, "kind": kind, "state": state, "note": note, "sub": sub}


def _plain_error(raw: str) -> str:
    """The first sentence of a stored error, without the Python class name in front.

    ``BudgetExceededError: spent $0.52 …`` → ``The spending limit was reached.``;
    ``RuntimeError: All specialists failed …; …`` → ``All specialists failed …``.
    The stored text stays available under "Technical details".
    """
    import re as _re

    text = raw.strip()
    if text.startswith("BudgetExceededError"):
        return "The spending limit was reached."
    if text.startswith("Server shutdown while in-flight") or "the server stopped while" in text:
        return "e2er was stopped while the run was working."
    text = _re.sub(r"^[A-Z][A-Za-z]*(Error|Exception)\s*:\s*", "", text)
    text = text.split(";")[0].strip()
    for name in sorted(_labels.SPECIALISTS, key=len, reverse=True):
        text = _re.sub(rf"\b{name}\b", _labels.SPECIALISTS[name], text)
    return text


def _failure_detail(workspace: Path, paper: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble a readable account of why a run stopped.

    Everything here is read from the run's own record — the error column, the
    per-specialist contract feedback, and the event log. Nothing is inferred
    about what the model was thinking, only about what it did not produce.
    """
    from ..core.run_outcome import workspace_status

    # "stopped" (stored as `rejected`) is a check that stopped the run; an older
    # run stored `rejected` after its internal quality review, and that run
    # completed (run_outcome.effective_status).
    status = workspace_status(paper.get("status"), workspace)
    if status not in {"failed", "stopped", "paused"}:
        return {"failed": False}

    raw = str(paper.get("last_error") or "").strip()
    headline = _plain_error(raw)

    attempts: dict[str, int] = {}
    for e in events:
        if str(e.get("event_type")) == "specialist_start" and e.get("specialist"):
            name = str(e["specialist"])
            attempts[name] = attempts.get(name, 0) + 1

    specialists: list[dict[str, Any]] = []
    feedback_dir = workspace / ".contract_feedback"
    if feedback_dir.is_dir():
        for f in sorted(feedback_dir.glob("*.txt")):
            try:
                violation = f.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            name = f.stem
            specialists.append(
                {
                    "name": name,
                    "label": _labels.specialist(name),
                    "violation": violation[:400],
                    "attempts": attempts.get(name, 0),
                }
            )

    # A recognisable pattern worth naming rather than leaving to be rediscovered.
    hints: list[str] = []
    unwritten = [s for s in specialists if "file not written" in s["violation"]]
    if unwritten and len(unwritten) == len(specialists) and len(specialists) > 1:
        hints.append(
            "None of the specialists wrote anything. This usually means the AI provider is installed but not "
            "signed in, or cannot write to the studies folder. Preflight shows which."
        )
    if status == "stopped":
        hints.append(
            "A check stopped the run. Fix what the check names, then resume: the run stops at the same check "
            "until it passes."
        )
    if status == "paused":
        hints.append(
            "The run is paused and its files are kept. Resume picks up at the first step that has not finished."
        )

    return {
        "failed": True,
        "status": status,
        "headline": headline or "The run stopped without recording a reason.",
        "raw": raw,
        "specialists": specialists,
        "hints": hints,
    }


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
    cap = float(paper.get("max_cost_usd") or get_settings().default_max_cost_usd)
    cost_pct = min(100.0, (cost_spent / cap * 100.0) if cap > 0 else 0.0)

    try:
        events = await fetch_all(
            """
            SELECT event_type, stage, specialist, payload, created_at
            FROM pipeline_events
            WHERE paper_id = %(id)s
            ORDER BY created_at DESC
            LIMIT 1000
            """,
            {"id": paper_id},
        )
    except Exception as exc:
        logger.warning("live-fragment events fetch failed for %s: %s", paper_id, exc)
        events = []
    for ev in events or []:
        if ev.get("created_at") is not None:
            ev["created_at_short"] = str(ev["created_at"])[11:19]
    elsewhere = await _running_elsewhere(dict(paper))
    task = _RUNNING.get(paper_id)
    running_here = task is not None and not task.done()

    return templates.TemplateResponse(
        request,
        "_live.html",
        {
            "paper": _with_outcome(dict(paper)),
            "progress": _progress(list(events or []), dict(paper)),
            "tp": _template_progress(dict(paper), list(events or [])),
            "failure": _failure_detail(_paper_workspace(dict(paper)), dict(paper), list(events or [])),
            "cost_spent": cost_spent,
            "cost_pct": cost_pct,
            "cost_cap": cap,
            # Claude Code and Codex run on the researcher's subscription: no spending limit applies.
            # Gemini runs on a Gemini API key whose cost e2er does not count: no limit either.
            "subscription": str(paper.get("backend") or get_settings().llm_backend) in _SUBSCRIPTION_BACKENDS,
            "uncounted_key": str(paper.get("backend") or get_settings().llm_backend) == "gemini",
            "events": (events or [])[:50],
            "can_cancel": (paper.get("status") not in _TERMINAL_STATUSES) and (paper_id in _RUNNING),
            # `e2er resume` takes a paused, failed or stopped study; so does the button.
            "can_resume": (paper.get("status") in _RESUMABLE_STATUSES) and not running_here and not elsewhere,
            "running": running_here or bool(elsewhere),
            "rerun_open": paper.get("status") in _RERUN_STATUSES and not running_here and not elsewhere,
            "budget_paused": paper.get("status") == "paused"
            and str(paper.get("last_error") or "").startswith("BudgetExceededError"),
            "pending_queries": await _pending_queries_or_none(paper_id),
            "awaiting_review": None if elsewhere else _awaiting_review(paper),
            "can_cancel_attempt": (paper.get("status") == "paused") and (paper_id not in _RUNNING) and not elsewhere,
            "elsewhere": elsewhere,
            "elsewhere_text": _elsewhere_text(elsewhere) if elsewhere else "",
        },
    )


#: Providers whose cost e2er records as $0, so no spending limit applies: Claude Code and Codex run
#: on the researcher's subscription; Gemini (not tested) on a Gemini API key that Google bills.
_SUBSCRIPTION_BACKENDS = {"claude_code", "codex", "gemini"}

#: What `e2er resume` (and the Resume button) takes: a paused, failed or stopped study.
_RESUMABLE_STATUSES = {"paused", "failed", "rejected"}
#: What `e2er rerun` (and the study page's rerun) takes: a study that is not running.
_RERUN_STATUSES = _RESUMABLE_STATUSES | {"completed", "cancelled"}


async def _pending_queries_or_none(paper_id: str) -> list[dict[str, Any]]:
    """Data queries waiting for the researcher's approval; none when the table cannot be read."""
    try:
        return list(await get_pending_queries(paper_id))
    except Exception:  # noqa: BLE001 — the live panel must render regardless
        return []


def _awaiting_review(paper: Any) -> str | None:
    """The researcher step a paused run waits at, for the dashboard's review link."""
    if paper.get("status") != "paused" or not paper.get("workspace"):
        return None
    # The status turns to paused a moment before the run task has wound down;
    # a review offered in that moment is refused (409) when approved.
    task = _RUNNING.get(str(paper.get("id")))
    if task is not None and not task.done():
        return None
    try:
        from ..core.pipeline.state import PipelineState

        st = PipelineState.load(Path(paper["workspace"]), str(paper["id"]), paper.get("mode") or "single_pass")
        return st.pending_review_stage
    except Exception:  # noqa: BLE001 — the live panel must render regardless
        return None


@app.get("/papers/{paper_id}/review", response_class=HTMLResponse)
async def review_page(request: Request, paper_id: str = Depends(_validate_uuid)) -> Any:
    """The researcher step in the dashboard: files in an editor, an instruction, send back, approve."""
    from ..core.pipeline.spec import find_spec
    from ..db.client import fetch_one

    data = await get_review(paper_id)
    row = await fetch_one("SELECT title, pipeline FROM papers WHERE id = %(id)s", {"id": paper_id}) or {}
    try:
        spec = find_spec(str(row.get("pipeline") or "empirical"))
    except Exception:  # noqa: BLE001 — the page still works with the plain names
        spec = None
    stage = (data.get("pending") or {}).get("stage") or ""
    for f in data.get("files") or []:
        f.update(_file_view(f["name"], f.get("content") or ""))
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "paper_id": paper_id,
            "title": row.get("title") or "",
            "step_label": _step_label(stage, spec) if stage else "",
            "sendable_choices": [
                {"name": n, "label": _labels.step_or_specialist(n, spec)} for n in data.get("sendable") or []
            ],
            **data,
        },
    )


def _file_view(name: str, content: str) -> dict[str, Any]:
    """How the review page shows a file: what it is, and what editing it means."""
    suffix = Path(name).suffix.lower()
    kinds = {
        ".md": ("text", "You are editing the text (Markdown)."),
        ".txt": ("text", "You are editing the text."),
        ".tex": ("LaTeX source", "You are editing the LaTeX source the paper is compiled from."),
        ".json": ("data file (JSON)", "You are editing the source of this data file (JSON). Keep it valid JSON."),
        ".bib": ("bibliography (BibTeX)", "You are editing the BibTeX source of the bibliography."),
    }
    what, note = kinds.get(suffix, ("file", "You are editing the file as it is stored."))
    pretty = content
    if suffix == ".json":
        try:
            pretty = json.dumps(json.loads(content), indent=2, ensure_ascii=False)
        except ValueError:
            pretty = content
    return {"what": what, "edit_note": note, "preview": pretty, "lines": content.count("\n") + 1}


@app.get("/api/papers/{paper_id}/events")
async def list_events(paper_id: str, since: str | None = None) -> list[dict[str, Any]]:
    """JSON event log. Optional `since=<iso8601>` filter for incremental polling."""
    from ..db.events import fetch_events

    return await fetch_events(paper_id, since=since)


@app.get("/api/papers/{paper_id}/artifacts/{path:path}")
async def stream_artifact(paper_id: str, path: str) -> FileResponse:
    """Serve a single artifact file from the paper workspace, mimetype-aware."""
    workspace = _workspace_of(paper_id)
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
    # Show what a browser can show. Without this every artifact downloads,
    # including the compiled paper — which made the paper unreadable from the
    # page that lists it.
    #
    # HTML and SVG are deliberately absent: both execute script in this origin,
    # and artifacts are written by a model from untrusted inputs.
    inline_types = {
        "application/pdf",
        "application/json",
        "text/plain",
        "text/markdown",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
    disposition = "inline" if mtype in inline_types else "attachment"
    return FileResponse(
        str(target),
        media_type=mtype or "application/octet-stream",
        filename=target.name,
        content_disposition_type=disposition,
    )


# Accepted BYOD file extensions: the one list (local_corpus.DATA_EXTENSIONS). 200 MB per upload.
_DATA_FILE_MAX_BYTES = _UPLOAD_MAX_BYTES


@app.post("/api/papers/{paper_id}/files", dependencies=[Depends(require_auth)])
async def upload_data_file(paper_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a researcher-supplied data file into the paper's workspace/data/.

    Specialists running with `DATA_MODULE_ENABLED=false` (no Allium key) can
    use these files via the standard read_file tool — see the byod skill.
    """
    workspace = _workspace_of(paper_id)
    if not workspace.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    name = Path(file.filename or "").name  # strip any path components
    if not name:
        raise HTTPException(status_code=400, detail="filename is required")
    from ..modules.local_corpus import not_a_data_file

    if why := not_a_data_file(name):
        raise HTTPException(status_code=400, detail=why)

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


async def _prepare_and_run(
    paper_id: str,
    workspace: Path,
    settings,
    mode: str,
    max_cost_usd: float,
    methodology: str = "empirical",
    backend_name: str | None = None,
    model: str | None = None,
    governance: str | None = None,
    review_stages: list[str] | None = None,
    research_question: str = "",
    title: str = "",
    pipeline: str = "empirical",
) -> None:
    """Background entry: do the heavy BYOD prep (data.db import + literature
    ingest + literature acquisition) off the request path, THEN run the pipeline.

    Kept out of create_paper so the POST returns immediately — a multi-GB import
    + Zotero ingest otherwise blocks past the client's HTTP timeout. Each step is
    best-effort and never raises; the import runs before the pipeline's data
    specialists need data.db, and the literature steps run after the papers row
    exists (FK) but before any specialist can cite anything.
    """
    from ..modules.data.byod_import import import_corpus_into_data_db

    try:
        try:
            await import_corpus_into_data_db(workspace, settings.max_rows_per_paper)
        except Exception as e:  # noqa: BLE001 — best-effort; pipeline still runs
            logger.warning("BYOD import failed for %s: %s (pipeline continues)", paper_id, e)
        # The researcher's papers, then the web search. Must precede _run_pipeline: the
        # drafter reads literature.bib from the prompt, and a cite with no bib entry is a
        # hard fail at the citation gate and an undefined reference at compile time.
        try:
            await _prepare_papers(paper_id, workspace, settings, research_question, title)
        except Exception as e:  # noqa: BLE001
            logger.warning("literature preparation failed for %s: %s (pipeline continues)", paper_id, e)
    except asyncio.CancelledError:
        # Cancel pressed in the first seconds, before the run itself started: the runner's own
        # handler never ran, and the run would stay "idea" for good with nothing to resume.
        await _mark_cancelled_before_start(paper_id)
        raise
    await _run_pipeline(
        paper_id,
        workspace,
        mode,
        max_cost_usd,
        methodology,
        backend_name,
        model,
        governance,
        review_stages,
        pipeline=pipeline,
    )


async def _mark_cancelled_before_start(paper_id: str) -> None:
    """A run cancelled while its data and literature were being prepared: cancelled, as the runner marks it."""
    from ..db.client import execute
    from ..db.events import log_event

    logger.warning("Run %s cancelled before it started (while preparing data and literature)", paper_id)
    try:
        await log_event(paper_id, "cancelled", payload={"before_start": True})
        await execute(
            "UPDATE papers SET status = 'cancelled', last_error = %(e)s, updated_at = NOW() WHERE id = %(id)s",
            {"e": "cancelled by user", "id": paper_id},
        )
    except Exception as e:  # noqa: BLE001 — the cancel itself must still go through
        logger.warning("Could not mark run %s as cancelled: %s", paper_id, e)


def model_override(settings: Any, backend_name: str, model: str | None) -> str | None:
    """The per-paper model to hand the backend, or None to let it use its own setting.

    Only a model that differs from the backend's configured default is an
    override. A resumed run passes the label stored on its row, which for an
    unpinned CLI backend is a placeholder ("codex-cli-default") or, on Claude
    Code, the API model id; neither may reach the CLI as `-m`/`--model`.
    """
    if not model or model in {"codex-cli-default", "gemini-cli-default"}:
        return None
    if model == settings.default_model_for(backend_name):
        return None
    return model


async def _run_pipeline(
    paper_id: str,
    workspace: Path,
    mode: str,
    max_cost_usd: float,
    methodology: str = "empirical",
    backend_name: str | None = None,
    model: str | None = None,
    governance: str | None = None,
    review_stages: list[str] | None = None,
    pipeline: str = "empirical",
) -> None:
    from ..config import get_settings
    from ..core.strategist.runner import PipelineRunner
    from ..modules.data.discovery_tools import DATA_DISCOVERY_TOOLS, SeriesDataToolHandler
    from ..modules.data.query_tools import QUERY_DATA_TOOLS, QueryDataToolHandler
    from ..modules.data.registry import warehouses
    from ..modules.literature.tools import LITERATURE_TOOLS, LiteratureToolHandler
    from ..modules.llm.registry import get_backend

    settings = get_settings()
    # Per-paper overrides (multi-model runs / experiment); fall back to the
    # process-global config when unset.
    effective_backend_name = backend_name or settings.llm_backend
    effective_governance = governance or settings.governance
    # The per-paper model reaches the backend itself, not just the label.
    # (The override is passed only when set: test doubles and replay backends take name= alone.)
    override = model_override(settings, effective_backend_name, model)
    backend = get_backend(settings, name=effective_backend_name, **({"model": override} if override else {}))
    effective_model = model or getattr(backend, "model", "") or settings.default_model_for(effective_backend_name)

    # Tools are unioned across all enabled providers; specialists' skill files
    # determine which they actually invoke.
    extra_tools: list[dict] = []
    extra_handlers: list = []

    # Warehouses (Allium) — each contributes its own guarded tools + handler
    # (query_allium keeps the 5-rule validator + approval flow). Present only
    # when configured (Allium key), matching the prior behaviour exactly.
    for warehouse in warehouses(settings):
        extra_tools.extend(warehouse.tools())
        extra_handlers.append(warehouse.handler(paper_id, workspace))

    # Series data (FRED/yfinance) + discovery — always on (yfinance needs no
    # key). Agents call list_data_sources, in light of the RQ, then fetch_data.
    # The handler takes the workspace so fetch_data can optionally materialize
    # a pulled series into the paper's data.db (queryable via query_data).
    extra_tools.extend(DATA_DISCOVERY_TOOLS)
    extra_handlers.append(SeriesDataToolHandler(workspace))

    # query_data — read-only SQL over the paper's data.db (BYOD imports +
    # materialized external series). Always on; specialists use it via skills.
    extra_tools.extend(QUERY_DATA_TOOLS)
    extra_handlers.append(QueryDataToolHandler(paper_id, workspace))

    # Literature tools are always on — OpenAlex needs no API key.
    extra_tools.extend(LITERATURE_TOOLS)
    extra_handlers.append(LiteratureToolHandler(workspace))

    runner = PipelineRunner(
        paper_id=paper_id,
        workspace=workspace,
        backend=backend,
        model=effective_model,
        mode=mode,
        extra_tools=extra_tools,
        extra_handlers=extra_handlers,
        backend_name=effective_backend_name,
        max_cost_usd=max_cost_usd,
        methodology=methodology,
        governance=effective_governance,
        review_stages=review_stages,
        pipeline=pipeline,
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
