"""First-run setup in the browser: AI provider, literature, data, keys.

Everything a first-time researcher used to do in `e2er init` happens on one
page. The page writes the same `.env` that `e2er init` writes (in the studies
folder, mode 600; see src/home.py), then runs the doctor checks. The first time
it asks for the studies folder (it offers the folder e2er was started in, else
``~/e2er-studies``; see home.launch_folder) and remembers it.

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
    (
        "ZENODO_TOKEN",
        "Deposits on Zenodo with your own account (a pre-registration, public data and code). "
        "Create a personal token with the scopes deposit:write and deposit:actions.",
        "https://zenodo.org/account/settings/applications/tokens/new/",
    ),
]

#: Plain names for the keys on the setup page (the setting names stay in the file).
KEY_LABELS = {
    "FRED_API_KEY": "FRED key",
    "ALLIUM_API_KEY": "Allium key",
    "SEMANTIC_SCHOLAR_API_KEY": "Semantic Scholar key",
    "ZENODO_TOKEN": "Zenodo key",
    "ANTHROPIC_API_KEY": "Anthropic API key",
    "OPENROUTER_API_KEY": "OpenRouter API key",
    "GEMINI_API_KEY": "Gemini API key",
}

#: The AI providers' keys the setup page saves. GEMINI_API_KEY belongs to the
#: Gemini CLI backend, which since 18 June 2026 runs with a paid key only.
_API_KEY_SETTINGS = {"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"}
_KNOWN_KEYS = {k for k, _, _ in OPTIONAL_KEYS} | _API_KEY_SETTINGS
_MODEL_SETTINGS = {"CLAUDE_CODE_MODEL", "ANTHROPIC_MODEL", "OPENROUTER_MODEL", "CODEX_MODEL", "GEMINI_MODEL"}


def env_path() -> Path:
    """The settings file: `.env` in the studies folder, or in a project folder of its own (src/home.py)."""
    from ..home import env_file

    return env_file()


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
    exts = {".bib", ".pdf"} if kind == "literature" else set() if kind == "folder" else set(DATA_EXTS) | {".bib"}
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
        ready = [b for b in backends if b.ready and b.tested]
        chosen = ready[0].name if ready else "claude_code"
    lit_bib = current.get("LITERATURE_BIBTEX_FILE", "")
    lit_dir = current.get("LITERATURE_DIR", "")
    docker = docker_check()
    return {
        "backends": [b for b in backends if b.tested],
        # Listed apart, under "Other providers (not tested)".
        "other_backends": [b for b in backends if not b.tested],
        "any_backend": any(b.ready for b in backends),
        "backend_help": BACKEND_HELP,
        "chosen": chosen,
        "current_models": {k: current.get(k, "") for k in _MODEL_SETTINGS},
        "literature": lit_dir or lit_bib,
        "literature_bib": lit_bib,
        "data_dir": current.get("LOCAL_DATA_DIR", ""),
        "optional_keys": [
            {
                "name": k,
                "label": KEY_LABELS.get(k, k),
                "what": what,
                "url": url,
                "masked": mask(current.get(k) or os.environ.get(k)),
            }
            for k, what, url in OPTIONAL_KEYS
        ],
        "key_labels": KEY_LABELS,
        "github_login": current.get("GITHUB_USERNAME", ""),
        **_folder_view(),
        "api_keys": {k: mask(current.get(k) or os.environ.get(k)) for k in _API_KEY_SETTINGS},
        "env_path": str(env_path()),
        "cwd": str(env_path().parent),
        "exists": env_path().is_file(),
        "home": str(Path.home()),
        "session_ok": not local_problem(request),
        "session_problem": local_problem(request),
        "docker": {"ok": docker.status == "PASS", "detail": docker.detail},
        "saved": saved,
    }


def _folder_view() -> dict[str, Any]:
    """Which folder holds the settings and studies, for the Studies folder card."""
    from .. import home

    remembered = home.remembered_studies_folder()
    kind = home.kind()
    launch = home.launch_folder()
    # Nothing set up: the folder e2er was started in, when started there on purpose; else the default.
    proposed = launch if kind == "none" and launch is not None else home.default_studies_folder()
    offered = home.offered_launch_folder() if kind == "studies" else None
    return {
        "folder_kind": kind,
        "folder": str(home.project_dir()),
        "studies_folder": str(remembered) if remembered else "",
        "default_studies_folder": str(home.default_studies_folder()),
        "proposed_studies_folder": str(proposed),
        "proposed_is_launch": kind == "none" and launch is not None,
        # Started in another folder of its own while the studies folder is in use: named, and offered.
        "launch_folder": str(offered) if offered else "",
    }


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, saved: int = 0) -> Any:
    from .app import templates

    return templates.TemplateResponse(request, "setup.html", setup_view(request, bool(saved)))


@router.get("/htmx/setup-checks", response_class=HTMLResponse)
async def setup_checks(request: Request) -> Any:
    from .app import _preflight, templates

    return templates.TemplateResponse(request, "_setup_checks.html", await _preflight(fresh=True))


class SaveSetup(BaseModel):
    backend: str
    model: str = ""
    api_key: str = ""  # for the anthropic / openrouter / gemini backends; blank keeps the stored one
    literature: str = ""
    data_dir: str = ""
    keys: dict[str, str] = {}  # optional connector keys; blank keeps the stored one
    create_folders: bool = False
    #: The studies folder, the first time (blank: ~/e2er-studies), or a new one.
    studies_folder: str = ""
    #: A project folder with its own settings becomes the studies folder.
    make_studies_folder: bool = False
    #: Keep the settings and studies in the folder e2er was started in (a project folder of its own).
    use_launch_folder: bool = False
    #: The GitHub login used as the owner when publishing (GITHUB_USERNAME).
    github_login: str = ""


def _github_login(raw: str) -> str:
    """A GitHub login as typed (``@Kim-Dash`` → ``kim-dash``); refuses anything that cannot be one."""
    import re

    login = raw.strip().lstrip("@").lower()
    if login and not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38})", login):
        # GitHub's own rule: letters, digits and hyphens, up to 39 characters; `_` and `.` are never
        # part of a GitHub login (a display name or an e-mail address may have them).
        raise HTTPException(
            status_code=422,
            detail=(
                f"GitHub login: {raw.strip()!r} is not a GitHub login. A GitHub login has only letters, digits "
                "and hyphens (no _ or .); yours is the name in the address of your GitHub profile, "
                "github.com/<login>. Leave the field empty to save the other settings without it."
            ),
        )
    return login


def _unchanged(chosen: str, *saved: str) -> bool:
    """Is ``chosen`` the path already in the settings (as saved, or the same folder)?"""
    for s in saved:
        if s and (s == chosen or _same_folder(Path(s).expanduser(), Path(chosen).expanduser())):
            return True
    return False


def _literature_settings(raw: str, current: dict[str, str], notes: list[str]) -> tuple[str, str]:
    """LITERATURE_BIBTEX_FILE and LITERATURE_DIR for the literature chosen on the page.

    Only a new choice that cannot be literature (no such path, a file that is not .bib, several
    .bib files to pick from) stops the save. The saved choice is kept as it is, and an empty
    folder is saved with a note: "Create folders" makes an empty literature folder, and it used
    to refuse every later save, so the AI provider, GitHub login and keys were lost with it
    (tester report, 2026-10-27).
    """
    chosen = clean_path_input(raw)
    lit = inspect_literature(Path(chosen))
    if lit.usable:
        s = lit.settings()
        return s.get("LITERATURE_BIBTEX_FILE", ""), s.get("LITERATURE_DIR", "")
    saved_bib, saved_dir = current.get("LITERATURE_BIBTEX_FILE", ""), current.get("LITERATURE_DIR", "")
    if _unchanged(chosen, saved_bib, saved_dir):
        notes.append(f"Literature: {lit.message} The saved choice {chosen} is kept; add files to it later.")
        return saved_bib, saved_dir
    if lit.kind == "empty":
        notes.append(f"Literature: {lit.path} has no .bib file and no PDFs yet. It is saved; add files to it later.")
        return "", lit.path
    raise HTTPException(status_code=422, detail=f"Literature: {lit.message}")


def _data_setting(raw: str, current: dict[str, str], notes: list[str]) -> str:
    """LOCAL_DATA_DIR for the data folder chosen on the page; the saved one never stops a save."""
    chosen = clean_path_input(raw)
    d = inspect_data(Path(chosen))
    if d.ok:
        return d.path
    saved = current.get("LOCAL_DATA_DIR", "")
    if _unchanged(chosen, saved):
        notes.append(f"Data folder: {d.message} The saved choice {chosen} is kept.")
        return saved
    raise HTTPException(status_code=422, detail=f"Data folder: {d.message}")


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
    if req.backend == "openrouter":
        from ..doctor import openrouter_models

        allowed_models |= {m for m, _ in openrouter_models(current.get("OPENROUTER_MODEL", ""))}
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
        elif (current.get(k) or "").strip():
            # A key kept from the previous file loses the whitespace it was pasted with.
            keys[k] = current[k].strip()

    bib, lit_dir, data_dir = "", "", ""
    if req.literature.strip():
        bib, lit_dir = _literature_settings(req.literature, current, notes)
    if req.data_dir.strip():
        data_dir = _data_setting(req.data_dir, current, notes)
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
        github_owner=_github_login(req.github_login) or current.get("GITHUB_USERNAME", ""),
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
    from ..config import is_secret_setting

    kept = {k: (v.strip() if is_secret_setting(k) else v) for k, v in current.items() if k not in managed}
    if kept:
        from ..cli_init import _env_quote

        body += "\n# ── Other settings, kept from the previous file ──────────────────\n"
        body += "".join(f"{k}={_env_quote(v)}\n" for k, v in kept.items())
    return body, notes


@router.post("/api/setup/save", dependencies=[Depends(require_local_session)])
async def save_setup(req: SaveSetup) -> dict[str, Any]:
    from ..cli_init import write_env_file
    from ..config import get_settings

    before = _read_env()  # the settings in use now: kept when the studies folder is chosen or changed
    before_root = env_path().parent
    root, folder_note = _choose_folder(req)
    current = _read_env_at(root / ".env") or before
    body, notes = build_env(req, current, root)
    path = root / ".env"
    write_env_file(path, body)
    if req.use_launch_folder and not _same_folder(root, before_root):
        # The researcher's own settings, copied from the studies folder by this page: the lines
        # that choose a program or a sandbox stay in use there (src/env_trust.py).
        from ..env_trust import remember, risky_lines

        if lines := risky_lines(path):
            remember(path, lines)
    get_settings.cache_clear()
    from .app import forget_preflight

    forget_preflight()  # new settings: Preflight checks again
    logger.info("setup page wrote %s", path)
    return {"ok": True, "path": str(path), "notes": ([folder_note] if folder_note else []) + notes}


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _read_env_at(p: Path) -> dict[str, str]:
    if not p.is_file():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(p).items() if v is not None}


def _choose_folder(req: SaveSetup) -> tuple[Path, str]:
    """Where the settings go, and a note for the page when the studies folder changed.

    The first time: the studies folder asked for (default ``~/e2er-studies``),
    remembered for every later start. A folder with its own settings stays
    where it is, unless the researcher makes it the studies folder.
    """
    from .. import home

    kind = home.kind()
    asked = clean_path_input(req.studies_folder) if req.studies_folder.strip() else ""
    launch = home.offered_launch_folder() if req.use_launch_folder else None
    if launch is not None:
        # A project folder of its own: e2er started here uses it (home.project_dir, rule 2); the
        # studies folder stays what e2er uses from every other folder.
        if os.environ.get(home.ENV_PROJECT):
            os.environ[home.ENV_PROJECT] = str(launch.resolve())
        return launch, (
            f"e2er keeps the settings and studies of {launch} in that folder; started from any other folder "
            "it uses your studies folder."
        )
    if kind == "project" and not req.make_studies_folder:
        return home.project_dir(), ""
    if kind == "project":
        target = home.project_dir()
    elif kind == "studies" and not asked:
        return home.project_dir(), ""
    else:
        target = Path(asked) if asked else home.default_studies_folder()
    if not target.is_absolute():
        raise HTTPException(status_code=422, detail="Give the studies folder as a full path, such as ~/e2er-studies.")
    if target.exists() and not target.is_dir():
        raise HTTPException(status_code=422, detail=f"{target} is a file. Choose a folder for your studies.")
    try:
        target = home.remember_studies_folder(target)
    except OSError as e:
        raise HTTPException(status_code=422, detail=f"e2er could not create {target}: {e.strerror or e}") from e
    if os.environ.get(home.ENV_PROJECT):
        # This server was started for the folder it was in; from now on it uses the studies folder.
        os.environ[home.ENV_PROJECT] = str(target)
    note = f"Your studies folder is {target}. e2er uses it from any folder you start it in."
    notice = home.temporary_notice(target, "this folder,")
    if notice:
        note += f" Warning: {notice}"
    return target, note
