"""The finish page: verify a completed study, then publish it to e2er.org.

The page runs the same code as the terminal: `e2er verify` (its offline
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


def _terms(bundle: Path | None) -> list[dict[str, Any]]:
    """Sources with terms whose data the folder holds (the GMD, Yahoo Finance).

    What the finish page asks the researcher to confirm, and what readers see if the data stay private.
    """
    from ..core import data_terms

    if bundle is None:
        return []
    return [
        {
            "connector": u.terms.connector,
            "label": u.label,
            "the_label": u.the_label,
            "short": u.terms.short,
            "plain": list(u.terms.plain),
            "citation": u.terms.citation,
            "terms_url": u.terms.terms_url,
            "confirm": u.terms.confirm,
            # What readers on e2er.org see if the data stay private (publish's reader note says the same).
            "reader_note": (
                f"If the data stay private, readers on e2er.org see a link to {u.terms.the_short} instead of a "
                f"request button: its terms {u.terms.limit_finish}."
            ),
        }
        for u in data_terms.uses(bundle)
    ]


@router.get("/papers/{paper_id}/finish", response_class=HTMLResponse)
async def finish_page(request: Request, paper_id: str) -> Any:
    from ..config import get_settings
    from ..core.demonstration import study_purpose
    from .app import _with_outcome, templates

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
            "paper": _with_outcome(dict(paper)),
            "export": str(export) if export else "",
            **_folders_view(paper_id),
            "data_terms": _terms(export),
            "output_root": str(settings.resolved_output_root()),
            "platform": base,
            "signed_in": _signed_in(base),
            "owner": (settings.github_username or "").lower(),
            "n_checks": 6,
            "project": _slug(str(paper.get("title") or "")),
            "demonstration": demo,
            "session_ok": not local_problem(request),
            "session_problem": local_problem(request),
        },
    )


@router.post("/api/papers/{paper_id}/export", dependencies=[Depends(require_local_session)])
async def export_study(paper_id: str) -> dict[str, Any]:
    from ..config import get_settings
    from ..core.export.current import export_current

    paper = await _paper(paper_id)
    from .app import _paper_workspace

    workspace = _paper_workspace(paper)
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"The study's working folder is gone: {workspace}")
    out, state = await asyncio.to_thread(
        export_current,
        workspace,
        get_settings().resolved_output_root(),
        paper_id=paper_id,
        date_str=datetime.now().strftime("%Y%m%d"),
        template=paper.get("pipeline") or None,
    )
    return {
        "path": str(out),
        "state": state,
        "note": _EXPORT_NOTES[state],
        "data_terms": _terms(Path(out)),
        **_folders_view(paper_id),
    }


#: What "Prepare the folder" did, in one sentence (export/current.py).
_EXPORT_NOTES = {
    "unchanged": "Nothing changed since the folder was prepared: it is still the current one.",
    "replaced": "The folder now holds the study as it is now (the earlier, unpublished copy was replaced).",
    "new": "This is the current folder. The published version keeps its own folder.",
}


def _folders_view(paper_id: str) -> dict[str, Any]:
    """The run's exported folders for the page: the current one, the published one, the older copies."""
    from ..config import get_settings
    from ..core.export import current as cur

    root = get_settings().resolved_output_root()
    mine = cur.exports_of(root, paper_id)
    published = [d for d in mine if cur.is_published(d)]
    pub = published[-1] if published else None
    link = cur.published_link(pub) if pub else None
    view: dict[str, Any] = {
        "older_copies": len(cur.older_copies(root, paper_id)),
        "published": None,
        "current_published": bool(mine) and cur.is_published(mine[-1]),
    }
    if link:
        base = str(link.get("platform_url") or "").rstrip("/")
        did = str(link.get("dossier_id") or "")
        view["published"] = {
            "owner_project": link.get("owner_project"),
            "version": link.get("version"),
            "study_url": f"{base}/{link.get('owner_project')}" if base else "",
            "dossier_url": f"{base}/d/{did.removeprefix('sha256:')[:16]}" if base and did else "",
            "folder": str(pub),
        }
    return view


@router.post("/api/papers/{paper_id}/exports/remove-older", dependencies=[Depends(require_local_session)])
async def remove_older_exports(paper_id: str) -> dict[str, Any]:
    """Remove the earlier copies of the run's folder: never the current one, never a published one."""
    from ..config import get_settings
    from ..core.export.current import remove_older_copies

    await _paper(paper_id)
    removed = await asyncio.to_thread(remove_older_copies, get_settings().resolved_output_root(), paper_id)
    n = len(removed)
    return {
        "removed": n,
        "note": f"Removed {n} older cop{'y' if n == 1 else 'ies'}. The current folder and the published one stay."
        if n
        else "There were no older copies to remove.",
        **_folders_view(paper_id),
    }


def _bundle(paper_id: str) -> Path:
    b = find_export(paper_id)
    if b is None:
        raise HTTPException(status_code=404, detail="This study has no exported folder yet. Prepare it first.")
    return b


class VerifyRequest(BaseModel):
    #: Also check the citations against the live registries (`e2er verify --online`).
    online: bool = False


@router.post("/api/papers/{paper_id}/verify", dependencies=[Depends(require_local_session)])
async def verify_study(paper_id: str, req: VerifyRequest | None = None) -> dict[str, Any]:
    """`e2er verify` on the study's exported folder: the same checks, the same verdict."""
    from dataclasses import asdict

    from ..cli_verify import _run_checks, _verdict

    await _paper(paper_id)
    bundle = _bundle(paper_id)
    checks = await asyncio.to_thread(_run_checks, bundle, bool(req and req.online))
    verdict, code = _verdict(checks)
    from ..core.labels import verify_check

    return {
        "bundle": str(bundle),
        "checks": [{**asdict(c), "label": verify_check(c.name)} for c in checks],
        "verdict": verdict,
        "verdict_plain": _plain_verdict(checks, code == 0),
        "verified": code == 0,
    }


def _plain_verdict(checks: list[Any], verified: bool) -> str:
    """The verdict in one sentence, with the checks by their plain names."""
    from ..core.labels import verify_check

    failed = [verify_check(c.name) for c in checks if c.status == "FAIL"]
    passed = sum(1 for c in checks if c.status == "PASS")
    skipped = sum(1 for c in checks if c.status == "SKIP")
    if failed:
        return f"Not verified: {len(failed)} check{'s' if len(failed) != 1 else ''} did not pass ({'; '.join(failed)})."
    if not verified:
        return "Not verified: too few checks could run on this folder. Prepare the folder again after the run finished."
    tail = f", {skipped} did not apply" if skipped else ""
    return f"Verified: {passed} checks passed{tail}."


def _server_db() -> str | None:
    """This server's own run database (SQLite), where the study's steps are recorded."""
    from ..config import get_settings
    from ..db.client import _sqlite_path

    url = get_settings().resolved_database_url
    if url and not url.startswith("sqlite"):
        return None
    try:
        return _sqlite_path(url)
    except ValueError:
        return None


class PublishRequest(BaseModel):
    owner: str
    project: str
    data: str = "private"
    code: str = "private"
    data_url: str | None = None
    code_url: str | None = None
    #: The paper (`--paper`): public with the https address of its PDF (`--paper-url`), or private.
    paper: str = "private"
    paper_url: str | None = None
    zenodo: bool = False
    #: Sources whose terms the researcher confirmed (`--accept-data-terms`), e.g. ["gmd"].
    accept_data_terms: list[str] = []
    name: str | None = None
    orcid: str | None = None
    #: CRediT roles (`--role`, repeatable).
    roles: list[str] = []
    license_id: str | None = None
    #: The repository that holds the folder, the commit that pins it, the folder's path in it.
    repo: str | None = None
    commit: str | None = None
    path: str | None = None
    #: owner/project of research objects this one builds on (`--derived-from`).
    derived_from: list[str] = []
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
    if req.paper not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="The paper is either public or private.")
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
        template=paper.get("pipeline") or None,
        data=req.data,
        code=req.code,
        data_url=(req.data_url or "").strip() or None,
        code_url=(req.code_url or "").strip() or None,
        paper=req.paper,
        paper_url=(req.paper_url or "").strip() or None,
        zenodo=req.zenodo,
        accept_data_terms=[a for a in req.accept_data_terms if a.strip()] or None,
        name=(req.name or "").strip() or None,
        orcid=(req.orcid or "").strip() or None,
        license_id=(req.license_id or "").strip() or None,
        roles=[r.strip() for r in req.roles if r.strip()] or None,
        repo=(req.repo or "").strip() or None,
        commit=(req.commit or "").strip() or None,
        path=(req.path or "").strip() or None,
        derived_from=[d.strip() for d in req.derived_from if d.strip()] or None,
        demonstration=req.demonstration,
        interactive=False,
        out=None,
        site=base,
        db=_server_db(),
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
    missing = _terms_missing(bundle, req) if code != 0 else []
    return {
        "ok": code == 0,
        # What `e2er publish` printed, with this computer's paths and full ids shortened (Technical details).
        "output": shorten(output.strip()),
        # A refusal in one plain sentence, shown first.
        **({} if code == 0 else {"reason": plain_failure(output, missing, base)}),
        "request": request_body,
        "platform": base,
        # The terms boxes still unticked while the data are public: the page marks them.
        "terms_missing": missing,
        **({} if req.dry_run or code != 0 else _published_links(output)),
        **({} if req.dry_run or code != 0 else _folders_view(paper_id)),
    }


_UUID = re.compile(r"\b([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_SHA = re.compile(r"\bsha256:([0-9a-f]{12})[0-9a-f]{52}\b")


def shorten(text: str) -> str:
    """Paths on this computer cut to their last part, full ids and fingerprints to their first characters."""
    from ..core.secret_scan import strip_local_paths

    out = str(strip_local_paths(text))
    out = _UUID.sub(lambda m: f"{m.group(1)}…", out)
    return _SHA.sub(lambda m: f"sha256:{m.group(1)}…", out)


def plain_failure(output: str, terms_missing: list[str], base: str) -> str:
    """Why `e2er publish` refused, in one sentence for the page (the full output stays folded)."""
    from ..cli_publish import LATEX_OFFLINE

    if terms_missing:
        return (
            "The data are set to public, but the terms of a source are not confirmed: tick the box under its "
            "terms, or keep the data private."
        )
    if LATEX_OFFLINE in output:
        return LATEX_OFFLINE
    first = next(
        (ln.strip()[len("error:") :].strip() for ln in output.splitlines() if ln.strip().startswith("error:")), ""
    )
    low = first.lower()
    if "not signed in" in low:
        return f"Sign in to {base} first (the button below)."
    if low.startswith("could not reach"):
        return f"{base} could not be reached. Check the internet connection and try again."
    if not first:
        return "e2er could not publish the study. The technical details below say why."
    sentence = shorten(first)
    sentence = sentence[0].upper() + sentence[1:]
    return sentence if sentence.endswith((".", "!", "?")) else sentence + "."


def _terms_missing(bundle: Path, req: PublishRequest) -> list[str]:
    from ..core import data_terms

    if req.data != "public":
        return []
    accepted = [a for a in req.accept_data_terms if a.strip()]
    try:
        return [u.terms.connector for u in data_terms.missing_confirmation(data_terms.uses(bundle), accepted)]
    except Exception:  # noqa: BLE001 - the page then shows the output alone
        return []


def _published_links(output: str) -> dict[str, Any]:
    """Where the published study can be read, from what `e2er publish` printed: its page and its dossier."""
    links: dict[str, Any] = {}
    page = re.search(r"published as [^:]+: (https?://\S+)", output)
    dossier = re.search(r"^\s*dossier (https?://\S+)", output, re.MULTILINE)
    if page:
        links["study_url"] = page.group(1)
    if dossier:
        links["dossier_url"] = dossier.group(1)
    return links


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


# ── deposit the frozen pre-registration (as `e2er preregister deposit --zenodo`) ──


class DepositRequest(BaseModel):
    sandbox: bool = False


@router.post("/api/papers/{paper_id}/preregistration/deposit", dependencies=[Depends(require_local_session)])
async def deposit_preregistration(paper_id: str, req: DepositRequest) -> dict[str, Any]:
    """Deposit the study's frozen pre-registration on Zenodo with the researcher's own token."""
    from ..core.pipeline.preregistration import ZENODO_SANDBOX_URL, ZENODO_URL, deposit_zenodo, load_lock

    paper = await _paper(paper_id)
    folder = Path(str(paper.get("workspace") or ""))
    if (folder / "design").is_dir() and load_lock(folder / "design"):
        folder = folder / "design"
    lock = load_lock(folder) if folder.is_dir() else None
    if lock is None:
        raise HTTPException(
            status_code=409, detail="No frozen pre-registration here; approve it at its researcher step first."
        )
    if lock.get("deposit"):
        raise HTTPException(status_code=409, detail=f"Already deposited: doi {lock['deposit'].get('doi')}.")
    from ..core.zenodo import load_token

    token = load_token(sandbox=req.sandbox)
    if not token:
        where = "Zenodo test site key" if req.sandbox else "Zenodo key"
        raise HTTPException(
            status_code=422, detail=f"No {where} is saved yet. Add it under Settings, then deposit again."
        )
    try:
        dep = await asyncio.to_thread(
            deposit_zenodo, folder, token, base_url=ZENODO_SANDBOX_URL if req.sandbox else ZENODO_URL
        )
    except Exception as e:  # noqa: BLE001 — shown on the page
        raise HTTPException(status_code=502, detail=f"The deposit did not go through: {e}") from e
    return {"doi": dep.get("doi"), "url": dep.get("url"), "service": dep.get("service")}
