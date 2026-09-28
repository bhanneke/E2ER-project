"""First-run setup in the browser: AI provider, literature, data, keys.

Everything a first-time researcher used to do in `e2er init` happens on one
page. The page writes the same `.env` that `e2er init` writes (in the folder
e2er was started from, mode 600), then runs the doctor checks.

The folder browser lists folders on this computer, so it and the save endpoint
sit behind :func:`local_session.require_local_session` (token, loopback, local
Host header, same origin). Listing starts at the home folder and never leaves
it (or the extra roots named in ``E2ER_BROWSE_ROOTS``), and does not follow a
symlink that points outside them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..logging_config import get_logger
from ..paths import DATA_EXTS, clean_path_input, inspect_data, inspect_literature
from .local_session import local_problem, require_local_session

logger = get_logger(__name__)
router = APIRouter()

#: Extra folders the browser may show besides the home folder, separated by the
#: OS path separator (e.g. "/Volumes" for external drives).
ROOTS_ENV = "E2ER_BROWSE_ROOTS"

#: Keys connectors need that are not the AI provider's: (setting, what it is for, where to get it).
OPTIONAL_KEYS: list[tuple[str, str, str]] = [
    (
        "FRED_API_KEY",
        "Economic time series from the St. Louis Fed (FRED). Free.",
        "https://fredaccount.stlouisfed.org/apikey",
    ),
    (
        "ALLIUM_API_KEY",
        "On-chain blockchain data from Allium. Most tables need a paid plan.",
        "https://www.allium.so/",
    ),
    (
        "SEMANTIC_SCHOLAR_API_KEY",
        "Higher limits when searching Semantic Scholar for literature. Free.",
        "https://www.semanticscholar.org/product/api#api-key-form",
    ),
]

_API_KEY_SETTINGS = {"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"}
_KNOWN_KEYS = {k for k, _, _ in OPTIONAL_KEYS} | _API_KEY_SETTINGS
_MODEL_SETTINGS = {"CLAUDE_CODE_MODEL", "ANTHROPIC_MODEL", "OPENROUTER_MODEL", "CODEX_MODEL", "GEMINI_MODEL"}


def env_path() -> Path:
    """The settings file: `.env` in the folder e2er was started from (where pydantic-settings reads it)."""
    return Path.cwd() / ".env"


def needs_setup() -> bool:
    """No settings yet: no `.env` here and no LLM_BACKEND in the environment."""
    if os.environ.get("E2ER_SKIP_SETUP_REDIRECT"):
        return False
    return not env_path().is_file() and not os.environ.get("LLM_BACKEND")


def mask(value: str | None) -> str:
    """A key as the page may show it: never in full."""
    if not value:
        return ""
    return "…" + value[-4:] if len(value) > 8 else "set"


def _read_env() -> dict[str, str]:
    p = env_path()
    if not p.is_file():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(p).items() if v is not None}


# ── folder browser ──────────────────────────────────────────────────────────


def allowed_roots() -> list[Path]:
    roots = [Path(os.path.realpath(Path.home()))]
    for raw in (os.environ.get(ROOTS_ENV) or "").split(os.pathsep):
        if raw.strip():
            roots.append(Path(os.path.realpath(os.path.expanduser(raw.strip()))))
    return roots


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def safe_resolve(raw: str | None) -> Path:
    """The real path of what was asked for, if it is inside an allowed root; else 403."""
    roots = allowed_roots()
    s = clean_path_input(raw) if raw else ""
    target = Path(os.path.realpath(s)) if s else roots[0]
    if not _inside(target, roots):
        raise HTTPException(status_code=403, detail="That folder is outside your home folder.")
    return target


def list_folder(path: Path, kind: str) -> dict[str, Any]:
    """Folders plus the files that matter for ``kind`` (literature: .bib/.pdf; data: data files)."""
    roots = allowed_roots()
    exts = {".bib", ".pdf"} if kind == "literature" else set(DATA_EXTS) | {".bib"}
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Not a folder.")
    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    try:
        entries = list(os.scandir(path))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail="macOS did not allow e2er to read this folder.") from e
    for entry in entries:
        if entry.name.startswith("."):
            continue
        full = Path(entry.path)
        try:
            if entry.is_symlink():
                real = Path(os.path.realpath(full))
                if not _inside(real, roots):
                    continue  # never lead out of the allowed roots through a link
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir:
            dirs.append({"name": entry.name, "path": str(full)})
        elif Path(entry.name).suffix.lower() in exts:
            files.append({"name": entry.name, "path": str(full), "ext": Path(entry.name).suffix.lower()[1:]})
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    parent = path.parent if path.parent != path and _inside(path.parent, roots) else None
    crumbs = []
    for p in [*reversed(path.parents), path]:
        if _inside(p, roots):
            crumbs.append({"name": p.name or str(p), "path": str(p)})
    return {
        "path": str(path),
        "parent": str(parent) if parent else None,
        "crumbs": crumbs,
        "dirs": dirs[:2000],
        "files": files[:2000],
        "roots": [str(r) for r in roots],
    }


@router.get("/api/local/browse", dependencies=[Depends(require_local_session)])
async def browse(path: str = "", kind: str = "literature") -> dict[str, Any]:
    return list_folder(safe_resolve(path), kind)


@router.get("/api/local/inspect", dependencies=[Depends(require_local_session)])
async def inspect(path: str, kind: str = "literature") -> dict[str, Any]:
    target = safe_resolve(path)
    if kind == "data":
        d = inspect_data(target)
        return {"path": d.path, "ok": d.ok, "files": d.files, "message": d.message}
    lit = inspect_literature(target)
    return {
        "path": lit.path,
        "kind": lit.kind,
        "ok": lit.usable,
        "bib": lit.bib,
        "bibs": lit.bibs,
        "n_references": lit.n_references,
        "n_pdfs": lit.n_pdfs,
        "message": lit.message,
        "summary": lit.summary(),
    }


# ── the page ────────────────────────────────────────────────────────────────


def setup_view(request: Request, saved: bool = False) -> dict[str, Any]:
    from ..config import get_settings
    from ..doctor import BACKEND_HELP, detect_backends, docker_check

    current = _read_env()
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 — a broken .env must still let the page fix it
        settings = None
    backends = detect_backends(settings)
    chosen = current.get("LLM_BACKEND") or os.environ.get("LLM_BACKEND") or ""
    if not chosen:
        ready = [b for b in backends if b.ready]
        chosen = ready[0].name if ready else "claude_code"
    lit_bib = current.get("LITERATURE_BIBTEX_FILE", "")
    lit_dir = current.get("LITERATURE_DIR", "")
    docker = docker_check()
    return {
        "backends": backends,
        "any_backend": any(b.ready for b in backends),
        "backend_help": BACKEND_HELP,
        "chosen": chosen,
        "current_models": {k: current.get(k, "") for k in _MODEL_SETTINGS},
        "literature": lit_dir or lit_bib,
        "literature_bib": lit_bib,
        "data_dir": current.get("LOCAL_DATA_DIR", ""),
        "optional_keys": [
            {"name": k, "what": what, "url": url, "masked": mask(current.get(k) or os.environ.get(k))}
            for k, what, url in OPTIONAL_KEYS
        ],
        "api_keys": {k: mask(current.get(k) or os.environ.get(k)) for k in _API_KEY_SETTINGS},
        "env_path": str(env_path()),
        "cwd": str(Path.cwd()),
        "exists": env_path().is_file(),
        "home": str(Path.home()),
        "session_ok": not local_problem(request),
        "session_problem": local_problem(request),
        "docker": {"ok": docker.status == "PASS", "detail": docker.detail},
        "saved": saved,
    }


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, saved: int = 0) -> Any:
    from .app import templates

    return templates.TemplateResponse(request, "setup.html", setup_view(request, bool(saved)))


@router.get("/htmx/setup-checks", response_class=HTMLResponse)
async def setup_checks(request: Request) -> Any:
    from .app import _preflight, templates

    return templates.TemplateResponse(request, "_setup_checks.html", await _preflight())


class SaveSetup(BaseModel):
    backend: str
    model: str = ""
    api_key: str = ""  # for the anthropic / openrouter backends; blank keeps the stored one
    literature: str = ""
    data_dir: str = ""
    keys: dict[str, str] = {}  # optional connector keys; blank keeps the stored one
    create_folders: bool = False


def build_env(req: SaveSetup, current: dict[str, str], root: Path) -> tuple[str, list[str]]:
    """The new `.env` body, and notes for the page. Keeps settings it does not manage."""
    from ..cli_init import _env_block, _scaffold_project_dirs
    from ..doctor import BACKEND_MODELS
    from ..modules.llm.registry import BACKENDS

    if req.backend not in BACKENDS:
        raise HTTPException(status_code=422, detail=f"Unknown AI provider {req.backend!r}.")
    notes: list[str] = []
    model_setting, models = BACKEND_MODELS[req.backend]
    allowed_models = {m for m, _ in models}
    if req.model and req.model not in allowed_models:
        raise HTTPException(status_code=422, detail=f"Unknown model {req.model!r} for {req.backend}.")

    keys: dict[str, str] = {}
    for k in sorted(_KNOWN_KEYS):
        new = (req.keys.get(k) or "").strip()
        if k == f"{req.backend.upper()}_API_KEY" and req.api_key.strip():
            new = req.api_key.strip()
        if new and ("\n" in new or "\r" in new):
            raise HTTPException(status_code=422, detail=f"{k} contains a line break.")
        if new:
            keys[k] = new
        elif current.get(k):
            keys[k] = current[k]

    bib, lit_dir, data_dir = "", "", ""
    if req.literature.strip():
        lit = inspect_literature(Path(clean_path_input(req.literature)))
        if not lit.usable:
            raise HTTPException(status_code=422, detail=f"Literature: {lit.message}")
        s = lit.settings()
        bib, lit_dir = s.get("LITERATURE_BIBTEX_FILE", ""), s.get("LITERATURE_DIR", "")
    if req.data_dir.strip():
        d = inspect_data(Path(clean_path_input(req.data_dir)))
        if not d.ok:
            raise HTTPException(status_code=422, detail=f"Data folder: {d.message}")
        data_dir = d.path
    if req.create_folders:
        made_data, made_lit = _scaffold_project_dirs(root)
        data_dir = data_dir or str(made_data)
        lit_dir = lit_dir or (str(made_lit) if not bib else "")
        notes.append(f"Created {made_data} and {made_lit}.")

    body = _env_block(
        backend=req.backend,
        use_data="ALLIUM_API_KEY" in keys,
        bibtex_path=bib,
        database_url=current.get("DATABASE_URL", ""),
        github_token_pat="",
        github_owner=current.get("GITHUB_USERNAME", ""),
        local_data_dir=data_dir,
        literature_dir=lit_dir,
        model=(model_setting, req.model) if req.model else None,
        keys=keys,
        purpose=current.get("E2ER_PURPOSE", ""),
        written_by="the e2er setup page",
    )
    managed = {
        "LLM_BACKEND",
        "LITERATURE_BIBTEX_FILE",
        "LITERATURE_DIR",
        "LOCAL_DATA_DIR",
        "DATABASE_URL",
        "GITHUB_USERNAME",
        "E2ER_PURPOSE",
        *_KNOWN_KEYS,
        *_MODEL_SETTINGS,
    }
    kept = {k: v for k, v in current.items() if k not in managed}
    if kept:
        from ..cli_init import _env_quote

        body += "\n# ── Other settings, kept from the previous file ──────────────────\n"
        body += "".join(f"{k}={_env_quote(v)}\n" for k, v in kept.items())
    return body, notes


@router.post("/api/setup/save", dependencies=[Depends(require_local_session)])
async def save_setup(req: SaveSetup) -> dict[str, Any]:
    from ..cli_init import write_env_file
    from ..config import get_settings

    body, notes = build_env(req, _read_env(), Path.cwd())
    path = env_path()
    write_env_file(path, body)
    get_settings.cache_clear()
    logger.info("setup page wrote %s", path)
    return {"ok": True, "path": str(path), "notes": notes}
