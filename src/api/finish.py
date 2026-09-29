"""The finish page: verify a completed study, then publish it to e2er.org.

The page runs the same code as the terminal: `e2er verify` (the five offline
checks) on the study's exported folder, and `e2er publish` with the same
fields — first as a dry run that shows the exact request, then for real.
Signing in uses the command line's device flow; the page shows the code and
the address and waits for the approval.

Everything here reads or writes this computer, so every endpoint needs the
local session (see local_session.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..logging_config import get_logger
from .local_session import local_problem, require_local_session

logger = get_logger(__name__)
router = APIRouter()

# publish() and verify() print their results; capturing stdout swaps a
# process-wide object, so only one capture runs at a time.
_CAPTURE = threading.Lock()


def _capture(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, str]:
    out = io.StringIO()
    with _CAPTURE, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            result = fn(*args, **kwargs)
        except SystemExit as e:  # a CLI function that exits instead of returning
            result = e.code if isinstance(e.code, int) else 1
    return result, out.getvalue()


async def _paper(paper_id: str) -> dict[str, Any]:
    import uuid

    from ..db.client import fetch_one

    try:
        uuid.UUID(paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Study not found") from e
    row = await fetch_one("SELECT * FROM papers WHERE id = %(id)s", {"id": paper_id})
    if not row:
        raise HTTPException(status_code=404, detail="Study not found")
    return dict(row)


def find_export(paper_id: str) -> Path | None:
    """The newest exported folder of this study (its provenance.json names the run)."""
    from ..config import get_settings

    root = get_settings().resolved_output_root()
    if not root.is_dir():
        return None
    found: list[Path] = []
    for d in root.iterdir():
        prov = d / "provenance.json"
        if not prov.is_file():
            continue
        try:
            if (json.loads(prov.read_text(encoding="utf-8")).get("run") or {}).get("paper_id") == paper_id:
                found.append(d)
        except (OSError, ValueError):
            continue
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48].rstrip("-") or "study"


def _platform() -> str:
    from ..core import platform_client as pc

    return pc.base_url()


def _signed_in(base: str) -> bool:
    from ..core import platform_client as pc

    try:
        return bool(pc.load_token(base))
    except Exception:  # noqa: BLE001 — an unreadable keychain means "not signed in"
        return False


@router.get("/papers/{paper_id}/finish", response_class=HTMLResponse)
async def finish_page(request: Request, paper_id: str) -> Any:
    from ..config import get_settings
    from ..core.demonstration import study_purpose
    from .app import templates

    paper = await _paper(paper_id)
    export = find_export(paper_id)
    base = _platform()
    settings = get_settings()
    workspace = Path(str(paper.get("workspace") or ""))
    try:
        demo = study_purpose(workspace) == "demonstration"
    except ValueError:
        demo = False
    return templates.TemplateResponse(
        request,
        "finish.html",
        {
            "paper": paper,
            "export": str(export) if export else "",
            "output_root": str(settings.resolved_output_root()),
            "platform": base,
            "signed_in": _signed_in(base),
            "owner": (settings.github_username or "").lower(),
            "project": _slug(str(paper.get("title") or "")),
            "demonstration": demo,
            "session_ok": not local_problem(request),
            "session_problem": local_problem(request),
        },
    )


@router.post("/api/papers/{paper_id}/export", dependencies=[Depends(require_local_session)])
async def export_study(paper_id: str) -> dict[str, Any]:
    from ..config import get_settings
    from ..core.export.structured import export_paper

    paper = await _paper(paper_id)
    workspace = Path(str(paper.get("workspace") or Path(get_settings().workspace_root) / paper_id))
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"The study's working folder is gone: {workspace}")
    out = await asyncio.to_thread(
        export_paper, workspace, get_settings().resolved_output_root(), date_str=datetime.now().strftime("%Y%m%d")
    )
    return {"path": str(out)}


def _bundle(paper_id: str) -> Path:
    b = find_export(paper_id)
    if b is None:
        raise HTTPException(status_code=404, detail="This study has no exported folder yet. Prepare it first.")
    return b


@router.post("/api/papers/{paper_id}/verify", dependencies=[Depends(require_local_session)])
async def verify_study(paper_id: str) -> dict[str, Any]:
    """`e2er verify` on the study's exported folder: the same checks, the same verdict."""
    from dataclasses import asdict

    from ..cli_verify import _run_checks, _verdict

    await _paper(paper_id)
    bundle = _bundle(paper_id)
    checks = await asyncio.to_thread(_run_checks, bundle, False)
    verdict, code = _verdict(checks)
    return {"bundle": str(bundle), "checks": [asdict(c) for c in checks], "verdict": verdict, "verified": code == 0}


class PublishRequest(BaseModel):
    owner: str
    project: str
    data: str = "private"
    code: str = "private"
    demonstration: bool = False
    dry_run: bool = True


@router.post("/api/papers/{paper_id}/publish", dependencies=[Depends(require_local_session)])
async def publish_study(paper_id: str, req: PublishRequest) -> dict[str, Any]:
    """`e2er publish --to <platform>`: a dry run shows the request; otherwise it is sent."""
    from ..cli_publish import publish

    paper = await _paper(paper_id)
    bundle = _bundle(paper_id)
    if req.data not in {"public", "private"} or req.code not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="Data and code are either public or private.")
    owner, project = req.owner.strip().lower(), req.project.strip().lower()
    if not owner or not project:
        raise HTTPException(status_code=422, detail="Fill in the owner and the project name.")
    base = _platform()
    if not req.dry_run and not _signed_in(base):
        raise HTTPException(status_code=401, detail=f"Sign in to {base} first.")
    code, output = await asyncio.to_thread(
        _capture,
        publish,
        str(bundle),
        dry_run=req.dry_run,
        to_url=base,
        owner=owner,
        project=project,
        github=owner,
        template=str(paper.get("pipeline") or "empirical"),
        data=req.data,
        code=req.code,
        demonstration=req.demonstration,
        out=str(bundle.parent / f"{bundle.name}-registry-entry"),
        site=base,
    )
    request_body = None
    if req.dry_run:
        start = output.find("{")
        if start >= 0:
            try:
                request_body, end = json.JSONDecoder().raw_decode(output[start:])
                output = (output[:start] + output[start + end :]).strip()
            except ValueError:
                request_body = None
    return {"ok": code == 0, "output": output.strip(), "request": request_body, "platform": base}


# ── sign in to e2er.org (device flow, in a background thread) ───────────────

_LOGIN: dict[str, Any] = {"state": "idle"}
_LOGIN_LOCK = threading.Lock()


def _run_login(base: str) -> None:
    from ..core import platform_client as pc

    def announce(verify: str, code: str) -> None:
        with _LOGIN_LOCK:
            _LOGIN.update(state="waiting", verify_url=verify, code=code)

    try:
        t = pc.login(base, announce=announce)
        where = pc.save_token(base, t["token"])
        with _LOGIN_LOCK:
            _LOGIN.update(state="done", message=f"Signed in to {base}. The token is kept in {where}.")
    except Exception as e:  # noqa: BLE001 — shown on the page
        with _LOGIN_LOCK:
            _LOGIN.update(state="error", message=str(e))


@router.post("/api/platform/login", dependencies=[Depends(require_local_session)])
async def start_login() -> dict[str, Any]:
    base = _platform()
    with _LOGIN_LOCK:
        if _LOGIN.get("state") in {"starting", "waiting"}:
            return dict(_LOGIN)
        _LOGIN.clear()
        _LOGIN.update(state="starting", platform=base)
    threading.Thread(target=_run_login, args=(base,), daemon=True).start()
    return {"state": "starting", "platform": base}


@router.get("/api/platform/login", dependencies=[Depends(require_local_session)])
async def login_status() -> dict[str, Any]:
    with _LOGIN_LOCK:
        state = dict(_LOGIN)
    state["signed_in"] = _signed_in(_platform())
    return state
