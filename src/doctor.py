"""User-facing preflight: ``e2er doctor``.

Tells the user — before they spend a paper run — whether their setup is
ready: backend installed, skills bundled, DB ok, and which configured data
+ literature providers are live. Same engine used by ``scripts/live_check.py``
(the dev harness); ``e2er doctor`` is the polished user surface.

No LLM calls, no paid API calls. Network is used for the configured
provider probes only.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

PASS, SKIP, FAIL = "PASS", "SKIP", "FAIL"


@dataclass
class Check:
    name: str
    status: str  # PASS | SKIP | FAIL
    detail: str = ""


# Map: backend literal → CLI executable name (None means an SDK backend).
_BACKEND_CLI = {
    "claude_code": "claude",
    "codex": "codex",
    "gemini": "gemini",
}


#: Where to install things. One place, so the README, `e2er doctor` and the
#: setup page point to the same instructions.
INSTALL_URL = "https://github.com/bhanneke/E2ER-project#install"
CLAUDE_CODE_SETUP_URL = "https://code.claude.com/docs/en/setup"
DOCKER_URL = "https://docs.docker.com/get-started/get-docker/"

#: How to get each backend, for a person who has none.
BACKEND_HELP: dict[str, dict[str, str]] = {
    "claude_code": {
        "label": "Claude subscription, through Claude Code",
        "how": "Install Claude Code, then run `claude` once and sign in in the browser.",
        "url": CLAUDE_CODE_SETUP_URL,
    },
    "anthropic": {
        "label": "Anthropic API key",
        "how": "Create a key in the Anthropic Console. Billed per use.",
        "url": "https://console.anthropic.com/settings/keys",
    },
    "openrouter": {
        "label": "OpenRouter API key",
        "how": "Create a key on OpenRouter. Billed per use.",
        "url": "https://openrouter.ai/keys",
    },
    "codex": {
        "label": "ChatGPT subscription, through the Codex CLI",
        "how": "Install the Codex CLI (the ChatGPT desktop app includes it), then run `codex login`.",
        "url": "https://github.com/openai/codex",
    },
    "gemini": {
        "label": "Gemini API key, through the Gemini CLI (not tested)",
        "how": (
            "Install the Gemini CLI and set GEMINI_API_KEY to a key from Google AI Studio. "
            "Google ended the Gemini CLI for AI Pro/Ultra plans and free individual accounts on "
            "18 June 2026: only a paid Gemini API key works, and e2er has not been tested with one."
        ),
        "url": "https://github.com/google-gemini/gemini-cli",
        "key_url": "https://aistudio.google.com/apikey",
    },
}

#: Backends e2er offers but has never run a full study on. They are listed
#: apart ("other providers, not tested") and left out of `run-matrix`'s default.
UNTESTED_BACKENDS = frozenset({"gemini"})

#: Why Gemini has no sign-in option, in one sentence for the setup page, doctor and init.
GEMINI_NO_SIGNIN = (
    "Google ended the Gemini CLI for AI Pro/Ultra plans and free individual accounts on 18 June 2026, "
    "so Gemini works only with a paid Gemini API key (GEMINI_API_KEY)"
)

#: The models the setup page offers per backend: (value, label). The first
#: entry marked cheapest is the cheapest; "" means the CLI's own default.
BACKEND_MODELS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "claude_code": (
        "CLAUDE_CODE_MODEL",
        [
            ("haiku", "Haiku: cheapest, uses the least of your plan"),
            ("sonnet", "Sonnet: recommended"),
            ("opus", "Opus: strongest, uses the most of your plan"),
        ],
    ),
    "anthropic": (
        "ANTHROPIC_MODEL",
        [
            ("claude-haiku-4-5", "Haiku 4.5: cheapest"),
            ("claude-sonnet-4-5", "Sonnet 4.5: recommended"),
            ("claude-opus-4-7", "Opus 4.7: strongest, most expensive"),
        ],
    ),
    "openrouter": (
        "OPENROUTER_MODEL",
        [
            ("anthropic/claude-haiku-4-5", "Claude Haiku 4.5: cheapest"),
            ("anthropic/claude-sonnet-4-5", "Claude Sonnet 4.5: recommended"),
        ],
    ),
    # Filled from the CLI's own model list when it has one (see _codex_models).
    "codex": ("CODEX_MODEL", [("", "The Codex CLI's own default")]),
    "gemini": (
        "GEMINI_MODEL",
        [
            ("", "The Gemini CLI's own default"),
            ("gemini-2.5-flash", "Gemini 2.5 Flash: cheapest"),
            ("gemini-2.5-pro", "Gemini 2.5 Pro"),
        ],
    ),
}


def _codex_models() -> list[tuple[str, str]]:
    """The models the signed-in ChatGPT plan offers, as Codex last fetched them.

    Read from the CLI's own cache; a fixed list here went stale within weeks.
    Falls back to the CLI default alone.
    """
    from .modules.llm.codex import codex_models

    listed = codex_models()
    if not listed:
        return BACKEND_MODELS["codex"][1]
    out = [("", f"The Codex CLI's own default ({listed[0]['slug']})")]
    for m in listed:
        desc = str(m.get("description") or "").strip().rstrip(".")
        out.append((str(m["slug"]), f"{m.get('display_name') or m['slug']}: {desc}" if desc else str(m["slug"])))
    return out


#: Shown first in the OpenRouter model list (when OpenRouter lists them), in this order.
_OPENROUTER_SUGGESTED = (
    ("anthropic/claude-sonnet-4.5", "recommended"),
    ("anthropic/claude-haiku-4.5", "cheaper Claude"),
    ("deepseek/deepseek-v4-pro", "open model, low price"),
)


def openrouter_models(current: str = "") -> list[tuple[str, str]]:
    """The OpenRouter models a study can use, with their price, for the setup page.

    Only models that can call tools (every specialist works through tools),
    from OpenRouter's published list: a few suggestions first, then the rest
    by name. Without the list (offline) the fixed suggestions. The model in
    use stays in the list even when OpenRouter no longer offers it.
    """
    from .modules.llm.openrouter_models import canonical_id, tool_models

    listed = tool_models()
    if not listed:
        out = list(BACKEND_MODELS["openrouter"][1])
    else:
        by_id = {m.id: m for m in listed}
        out = []
        for mid, note in _OPENROUTER_SUGGESTED:
            if mid in by_id:
                m = by_id[mid]
                out.append((mid, f"{m.name} ({note}): {m.price_label()}"))
        shown = {mid for mid, _ in out}
        out += [(m.id, f"{m.name}: {m.price_label()}") for m in listed if m.id not in shown]
    if current and current not in {mid for mid, _ in out}:
        # The settings' spelling (claude-sonnet-4-5) of a listed model keeps that model's label.
        same = next((label for mid, label in out if mid == canonical_id(current)), None)
        out.insert(0, (current, same or f"{current} (in use; not in OpenRouter's list of models that can use tools)"))
    return out


def resolve_backend_cli(backend: str, settings: Any = None) -> str | None:
    """Where the backend's CLI is: CLAUDE_CODE_PATH / CODEX_PATH / GEMINI_PATH,
    PATH, and the ChatGPT app's own `codex`. None when not installed."""
    from .modules.llm.cli_support import resolve_cli

    if settings is None:
        try:
            from .config import get_settings

            settings = get_settings()
        except Exception:  # noqa: BLE001 — a broken .env must not hide an installed CLI
            settings = None
    return resolve_cli(backend, settings)


def cli_signed_in(backend: str, home: Path | None = None) -> tuple[bool | None, str]:
    """Is the backend's CLI signed in? (True, False, or None when it cannot be told.)

    Read from the files each CLI keeps, without starting it: starting a CLI
    can open a browser or a permission prompt, which a status check must not.
    """
    h = home or Path.home()
    if backend == "claude_code":
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return True, "signed in with a key from the environment"
        if (h / ".claude" / ".credentials.json").is_file():
            return True, "signed in"
        try:
            data = json.loads((h / ".claude.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            if data.get("oauthAccount"):
                return True, "signed in"
            return False, "not signed in: run `claude` once and sign in in the browser"
        return None, "could not tell whether it is signed in: run `claude` once to check"
    if backend == "codex":
        codex_home = Path(os.environ.get("CODEX_HOME") or h / ".codex")
        if os.environ.get("OPENAI_API_KEY") or (codex_home / "auth.json").is_file():
            return True, "signed in"
        return False, "not signed in: run `codex login`"
    if backend == "gemini":
        # Only a key counts: Google ended the Gemini CLI for AI Pro/Ultra plans and
        # free individual accounts on 18 June 2026 (gemini 0.63.0 refuses them), so a sign-in
        # file left from before no longer lets a study run.
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _env_file_has("GEMINI_API_KEY"):
            return True, "a Gemini API key is set"
        return False, f"no Gemini API key: {GEMINI_NO_SIGNIN}"
    return None, ""


def _env_file_has(setting: str) -> bool:
    """Whether the settings file (`.env`) sets `setting`; the setup page writes keys there."""
    try:
        from dotenv import dotenv_values

        from .home import env_file

        return bool((dotenv_values(env_file()).get(setting) or "").strip())
    except Exception:  # noqa: BLE001 — a missing or unreadable .env is normal
        return False


def signin_command(backend: str, path: str | None) -> str:
    """The command that signs a CLI in, ready to paste into a terminal.

    The bare name when the terminal finds that same program; otherwise the full
    path (the Codex inside the ChatGPT app is not on PATH).
    """
    import shlex
    import shutil

    exe = _BACKEND_CLI.get(backend)
    if not exe or not path or backend in UNTESTED_BACKENDS:
        # Gemini: no sign-in to offer, only a key (GEMINI_NO_SIGNIN).
        return ""
    on_path = shutil.which(exe)
    try:
        same = on_path is not None and Path(on_path).resolve() == Path(path).resolve()
    except OSError:
        same = False
    prog = exe if same else shlex.quote(str(path))
    return f"{prog} login" if backend == "codex" else prog


@dataclass
class BackendStatus:
    name: str
    label: str
    kind: str  # "cli" (a CLI on this computer) | "api" (billed per use)
    installed: bool
    signed_in: bool | None
    detail: str
    ready: bool
    help: dict[str, str] = field(default_factory=dict)
    model_setting: str = ""
    models: list[tuple[str, str]] = field(default_factory=list)
    key_setting: str = ""
    #: The command that signs this CLI in, as the researcher types it (full path when not on PATH).
    signin_command: str = ""
    #: False for a backend no full study has run on (UNTESTED_BACKENDS).
    tested: bool = True


def detect_backends(settings: Any = None) -> list[BackendStatus]:
    """Every AI backend e2er can use, and whether this computer has it ready."""
    out: list[BackendStatus] = []
    for name in ("claude_code", "codex", "gemini", "anthropic", "openrouter"):
        model_setting, models = BACKEND_MODELS[name]
        if name == "codex":
            models = _codex_models()
        elif name == "openrouter":
            models = openrouter_models(str(getattr(settings, "openrouter_model", "") or ""))
        info = BACKEND_HELP[name]
        if name in _BACKEND_CLI:
            path = resolve_backend_cli(name, settings)
            if path:
                signed, note = cli_signed_in(name)
                detail = f"`{_BACKEND_CLI[name]}` found; {note}"
            else:
                signed, detail = None, f"`{_BACKEND_CLI[name]}` is not installed"
            out.append(
                BackendStatus(
                    name,
                    info["label"],
                    "cli",
                    bool(path),
                    signed,
                    detail,
                    bool(path) and signed is not False,
                    info,
                    model_setting,
                    models,
                    key_setting="GEMINI_API_KEY" if name == "gemini" else "",
                    signin_command=signin_command(name, path) if path else "",
                    tested=name not in UNTESTED_BACKENDS,
                )
            )
        else:
            key_setting = f"{name.upper()}_API_KEY"
            key = getattr(settings, f"{name}_api_key", None) if settings is not None else None
            key = key or os.environ.get(key_setting)
            out.append(
                BackendStatus(
                    name,
                    info["label"],
                    "api",
                    bool(key),
                    None,
                    "key found" if key else "no key yet",
                    bool(key),
                    info,
                    model_setting,
                    models,
                    key_setting,
                )
            )
    return out


def python_check() -> Check:
    major, minor, micro = tuple(sys.version_info)[:3]
    if (major, minor) < (3, 11):
        return Check("python", FAIL, f"Python {major}.{minor} is too old; e2er needs 3.11 or newer. See {INSTALL_URL}")
    return Check("python", PASS, f"Python {major}.{minor}.{micro}")


def docker_check() -> Check:
    """Docker runs the replication template's sandbox; nothing else needs it.

    Installed is not enough: the daemon must answer.
    """
    import subprocess

    path = shutil.which("docker")
    if not path:
        return Check("docker", SKIP, f"Docker is not installed; only the replication template needs it ({DOCKER_URL})")
    try:
        cp = subprocess.run([path, "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        cp = None
    if cp is None or cp.returncode != 0:
        return Check(
            "docker",
            SKIP,
            f"docker at {path}, but Docker is not running; start Docker Desktop before a replication "
            "(only the replication template needs it)",
        )
    return Check("docker", PASS, f"Docker is running (docker at {path}; used by the replication template)")


def _mask_db_url(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


# ── Preflight: the stuff a real run needs to even start ──────────────────────


async def backend_check(settings) -> Check:
    backend = settings.llm_backend
    if backend in {"anthropic", "openrouter"}:
        key = settings.anthropic_api_key if backend == "anthropic" else settings.openrouter_api_key
        if not key and backend == "anthropic" and not _raw_setting("LLM_BACKEND"):
            # Nothing chosen yet: the Anthropic value is only the settings' fallback,
            # so naming its key would send the person after the wrong thing.
            claude = resolve_backend_cli("claude_code", settings)
            found = f" Claude Code is installed at {claude};" if claude else ""
            return Check(
                "backend",
                FAIL,
                f"no AI access is set up in this folder (no LLM_BACKEND here or in .env).{found} "
                "run `e2er` and use the setup page, or `e2er init --defaults` for Claude Code",
            )
        if not key:
            return Check(f"backend.{backend}", FAIL, f"{backend.upper()}_API_KEY not set — `e2er run` will fail")
        return Check(f"backend.{backend}", PASS, "API key configured (metered backend)")
    cli = _BACKEND_CLI.get(backend)
    if cli is None:
        return Check(f"backend.{backend}", FAIL, f"unknown backend literal: {backend!r}")
    path = resolve_backend_cli(backend, settings)
    if not path:
        where = CLAUDE_CODE_SETUP_URL if backend == "claude_code" else BACKEND_HELP[backend]["url"]
        setting = {"claude_code": "CLAUDE_CODE_PATH", "codex": "CODEX_PATH", "gemini": "GEMINI_PATH"}[backend]
        return Check(
            f"backend.{backend}",
            FAIL,
            f"`{cli}` CLI not found on PATH or at {setting} — install it ({where}), or see {INSTALL_URL}",
        )
    signed, note = cli_signed_in(backend)
    if signed is False:
        return Check(f"backend.{backend}", FAIL, f"CLI at {path}, but {note}")
    if signed is None:
        return Check(f"backend.{backend}", SKIP, f"CLI at {path}; {note}")
    if backend in UNTESTED_BACKENDS:
        return Check(
            f"backend.{backend}",
            PASS,
            f"CLI at {path}; {note}. Gemini is not tested: full runs are tested on Claude Code and Codex",
        )
    return Check(f"backend.{backend}", PASS, f"CLI at {path} ($0 on the subscription); {note}")


async def skills_check(_settings) -> Check:
    # Skill files ship inside the package; the loader importing is the
    # canonical "are skills present" signal.
    try:
        # Just verify the module loads — its content is the bundled skill files
        # under src/skills/files/, which we count below.
        from .skills import loader  # noqa: F401
    except Exception as e:
        return Check("skills.installed", FAIL, repr(e)[:200])
    on_disk = Path(__file__).resolve().parent / "skills" / "files"
    if on_disk.is_dir():
        n = sum(1 for _ in on_disk.rglob("*.md"))
        return Check("skills.installed", PASS, f"{n} skill files under src/skills/files/")
    return Check("skills.installed", PASS, "skill loader importable (package data)")


async def db_check(settings) -> Check:
    url = settings.resolved_database_url
    if not url:
        sqlite = Path.home() / ".e2er" / "papers.db"
        return Check("db", PASS, f"SQLite default (auto-created at {sqlite})")
    if url.startswith("postgres"):
        # Direct short-timeout connect — bypasses the runtime pool's 30s
        # default + retry-spam so the preflight stays snappy.
        try:
            import psycopg

            async with await psycopg.AsyncConnection.connect(url, connect_timeout=5) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
            return Check("db", PASS, f"Postgres reachable ({_mask_db_url(url)})")
        except Exception as e:
            return Check(
                "db",
                FAIL,
                f"Postgres unreachable: {repr(e)[:140]} — "
                "if you didn't intend Postgres, unset DATABASE_URL / POSTGRES_URL to use the SQLite default",
            )
    return Check("db", PASS, f"resolved: {_mask_db_url(url)}")


# ── BYOD corpus checks — the researcher's own data + papers (pure-local) ─────
# No network. These validate what `create_paper` will actually stage into the
# workspace, so a misconfigured LOCAL_DATA_DIR / LITERATURE_DIR surfaces here
# instead of as a silent empty-corpus run.

_DATA_EXTS = {".csv", ".tsv", ".jsonl", ".parquet", ".xlsx", ".txt"}


def _iter_files(root: Path, recursive: bool):
    globber = root.rglob("*") if recursive else root.glob("*")
    return (p for p in globber if p.is_file())


async def byod_local_data_check(settings) -> Check:
    """Enumerate the researcher's BYOD dataset folder (LOCAL_DATA_DIR)."""
    raw = settings.local_data_dir
    if not raw:
        return Check("byod.local_data_dir", SKIP, "LOCAL_DATA_DIR not set (no bring-your-own datasets)")
    root = Path(raw).expanduser()
    if not root.is_dir():
        return Check("byod.local_data_dir", FAIL, f"LOCAL_DATA_DIR={raw} is not a directory")
    counts: dict[str, int] = {}
    for f in _iter_files(root, settings.local_data_dir_recursive):
        ext = f.suffix.lower()
        if ext in _DATA_EXTS or ext == ".bib":
            counts[ext] = counts.get(ext, 0) + 1
    n_data = sum(v for k, v in counts.items() if k in _DATA_EXTS)
    if n_data == 0 and ".bib" not in counts:
        return Check(
            "byod.local_data_dir",
            SKIP,
            f"{root} has no data files ({'/'.join(sorted(e[1:] for e in _DATA_EXTS))})",
        )
    summary = ", ".join(f"{v} {k[1:]}" for k, v in sorted(counts.items()))
    mode = "recursive" if settings.local_data_dir_recursive else "top-level"
    return Check("byod.local_data_dir", PASS, f"{summary} ({mode} scan of {root})")


def _bib_entry_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("@"))


async def byod_literature_check(settings) -> Check:
    """Report the active literature mode + corpus size (bibtex / PDFs / Zotero)."""
    modes: list[str] = []

    bib = settings.literature_bibtex_file
    if bib:
        bib_path = Path(bib).expanduser()
        if bib_path.is_file():
            modes.append(f"bibtex ({_bib_entry_count(bib_path)} entries)")
        else:
            return Check("byod.literature", FAIL, f"LITERATURE_BIBTEX_FILE={bib} not found")

    dirs = settings.resolved_literature_dirs()
    explicit = bool(getattr(settings, "literature_dir", None))
    empty: list[str] = []
    if dirs:
        for raw in (d.strip() for d in dirs.split(",") if d.strip()):
            root = Path(raw).expanduser()
            if not root.is_dir():
                return Check("byod.literature", FAIL, f"literature dir {raw} is not a directory")
            if (root / "zotero.sqlite").is_file():
                modes.append(f"Zotero library at {root}")
            else:
                n_pdf = sum(1 for _ in root.rglob("*.pdf"))
                n_bib = sum(1 for _ in root.glob("*.bib"))
                parts = []
                if n_pdf:
                    parts.append(f"{n_pdf} PDFs")
                if n_bib:
                    parts.append(f"{n_bib} .bib")
                # An empty directory is not a literature mode. resolved_literature_dirs()
                # falls back to LOCAL_DATA_DIR, so a user who configured only a .bib would
                # otherwise see their data folder reported as a miss on a passing check.
                if parts:
                    modes.append(f"{root}: {', '.join(parts)}")
                elif explicit:
                    # LITERATURE_DIR itself is set: say so, rather than "not set".
                    empty.append(f"LITERATURE_DIR {root}: set, empty (no PDFs or .bib files yet)")

    if not modes and empty:
        return Check("byod.literature", SKIP, "; ".join(empty) + " — OpenAlex-only until it has some")
    if not modes:
        return Check(
            "byod.literature",
            SKIP,
            "no LITERATURE_BIBTEX_FILE / LITERATURE_DIR / LOCAL_DATA_DIR — OpenAlex-only",
        )
    return Check("byod.literature", PASS, "; ".join(modes))


# ── Provider probes — what would this paper actually have access to? ─────────


async def data_catalog_check(_settings) -> Check:
    from .modules.data.discovery_tools import SeriesDataToolHandler

    try:
        raw = await SeriesDataToolHandler().handle("list_data_sources", {})
        names = [s["name"] for s in json.loads(raw).get("sources", [])]
        return Check("data.list_data_sources", PASS, f"catalog: {', '.join(names) or '(empty)'}")
    except Exception as e:
        return Check("data.list_data_sources", FAIL, repr(e)[:200])


def _len(rows: object) -> int:
    return len(rows) if isinstance(rows, list) else 0


async def yfinance_check(settings) -> Check:
    from .modules.data.registry import series_fetchers

    fetchers = {f.name: f for f in series_fetchers(settings)}
    if "yfinance" not in fetchers:
        return Check("data.yfinance.history", FAIL, "yfinance provider not registered")
    try:
        env = await fetchers["yfinance"].fetch(
            "history", {"ticker": "SPY", "interval": "1mo", "start": "2024-01-01", "end": "2024-04-01"}
        )
        n = _len(env.get("items"))
        ok = bool(n) and not env.get("error")
        return Check("data.yfinance.history", PASS if ok else FAIL, env.get("error") or f"{n} rows for SPY")
    except Exception as e:
        return Check("data.yfinance.history", FAIL, repr(e)[:200])


#: A FRED API key: 32 lower-case letters and digits.
FRED_KEY_FORMAT = re.compile(r"[a-z0-9]{32}")


def _raw_setting(name: str) -> str | None:
    """A setting as written, before Settings strips it: the environment, else `.env` here."""
    if name in os.environ:
        return os.environ[name]
    env = Path.cwd() / ".env"
    if not env.is_file():
        return None
    try:
        from dotenv import dotenv_values

        return dotenv_values(env).get(name)
    except Exception:  # noqa: BLE001 — an unreadable .env is reported by other checks
        return None


def fred_key_check(settings) -> Check:
    """The FRED key's format, before any request: FRED rejects anything but 32 lower-case alphanumerics."""
    key = settings.fred_api_key
    if not key:
        return Check("data.fred.key", SKIP, "FRED_API_KEY not set")
    raw = _raw_setting("FRED_API_KEY")
    padded = raw is not None and raw != raw.strip()
    note = " (it had spaces or line breaks around it in the settings; e2er strips them)" if padded else ""
    if not FRED_KEY_FORMAT.fullmatch(key):
        problem = f"{len(key)} characters" if len(key) != 32 else "not only lower-case letters and digits"
        return Check(
            "data.fred.key",
            FAIL,
            f"FRED_API_KEY is not a FRED key: FRED keys are 32 lower-case letters and digits, this one is {problem}"
            f"{note}. Copy it again from https://fredaccount.stlouisfed.org/apikey",
        )
    return Check("data.fred.key", PASS, f"FRED_API_KEY has the format of a FRED key (…{key[-4:]}){note}")


async def fred_check(settings) -> Check:
    if not settings.fred_api_key:
        return Check("data.fred.observations", SKIP, "FRED_API_KEY not set")
    if not FRED_KEY_FORMAT.fullmatch(settings.fred_api_key):
        return Check("data.fred.observations", SKIP, "not requested: the key has the wrong format (data.fred.key)")
    from .modules.data.registry import series_fetchers

    fetchers = {f.name: f for f in series_fetchers(settings)}
    try:
        env = await fetchers["fred"].fetch("observations", {"series_id": "CPIAUCSL", "observation_start": "2024-01-01"})
        n = _len(env.get("items"))
        ok = bool(n) and not env.get("error")
        return Check("data.fred.observations", PASS if ok else FAIL, env.get("error") or f"{n} CPI observations")
    except Exception as e:
        return Check("data.fred.observations", FAIL, repr(e)[:200])


async def gmd_check(_settings) -> Check:
    """The GMD release list is reachable (a small CSV; no release panel is downloaded)."""
    from .modules.data.gmd_provider import GMDProvider

    try:
        env = await GMDProvider().versions()
    except Exception as e:  # noqa: BLE001 — reported as the check's result
        return Check("data.gmd.versions", FAIL, repr(e)[:200])
    if env.get("error"):
        return Check("data.gmd.versions", FAIL, str(env["error"])[:300])
    return Check("data.gmd.versions", PASS, f"newest release {env['latest']} ({env['row_count']} releases)")


def _source_jobs() -> list[tuple[str, Any]]:
    """(check name, source) for every connector-kit source whose check is the kit's generic one."""
    from .modules.data.sources import all_sources

    return [
        (source.doctor.check, source)
        for source in all_sources()
        if source.doctor is not None and source.doctor.run is None  # yfinance, FRED, GMD: own checks above
    ]


async def _source_check(source: Any, settings: Any) -> Check | None:
    from .modules.data.sources.runtime import doctor_check

    try:
        return await doctor_check(source, settings)
    except Exception as e:  # noqa: BLE001 — reported as the check's result
        return Check(source.doctor.check, FAIL, repr(e)[:200])


async def source_checks(settings) -> list[Check]:
    """The reachability check of every connector-kit source that has no check of its own above.

    Each is one cheap request declared in the source's definition (``Source.doctor``), run side by
    side with the others (at most ``MAX_CONCURRENT_CHECKS`` at once, each within ``CHECK_TIMEOUT``).
    """
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    with _reachability():
        results = await asyncio.gather(
            *(
                _bounded(sem, name, partial(_source_check, source, settings), CHECK_TIMEOUT)
                for name, source in _source_jobs()
            )
        )
    return [c for c in results if c is not None]


async def allium_check(settings) -> Check:
    if not settings.allium_api_key:
        return Check("data.allium.list_tables", SKIP, "ALLIUM_API_KEY not set")
    try:
        from .modules.data.allium import AlliumProvider

        tables = await AlliumProvider(settings.allium_api_key, settings.allium_api_base).list_tables()
        return Check(
            "data.allium.list_tables",
            PASS if tables else FAIL,
            f"{len(tables)} tables" if tables else "no tables returned (credits / tier?)",
        )
    except Exception as e:
        return Check("data.allium.list_tables", FAIL, repr(e)[:200])


async def openalex_check(_settings) -> Check:
    from .modules.literature.tools import LiteratureToolHandler

    handler = LiteratureToolHandler(Path("/tmp"))
    try:
        raw = await handler.handle(
            "search_papers", {"query": "concentrated liquidity automated market makers", "limit": 3}
        )
        out = json.loads(raw)
        n = out.get("count", 0)
        return Check(
            "lit.search_papers", PASS if n > 0 else FAIL, out.get("error") or f"{n} papers via {out.get('source')}"
        )
    except Exception as e:
        return Check("lit.search_papers", FAIL, repr(e)[:200])


async def read_reference_check(_settings) -> Check:
    from .modules.literature.tools import LiteratureToolHandler

    handler = LiteratureToolHandler(Path("/tmp"))
    try:
        raw = await handler.handle("read_reference", {"pdf_url": "https://arxiv.org/pdf/1706.03762"})
        out = json.loads(raw)
        chars = out.get("chars", 0)
        ok = chars and chars > 500
        return Check(
            "lit.read_reference (OA PDF)", PASS if ok else FAIL, out.get("error") or f"{chars} chars extracted"
        )
    except Exception as e:
        return Check("lit.read_reference (OA PDF)", FAIL, repr(e)[:200])


async def zotero_check(settings) -> Check:
    if not settings.zotero_enabled:
        return Check("lit.zotero.library", SKIP, "ZOTERO_API_KEY + user/group id not set")
    try:
        from .modules.literature.zotero import fetch_library

        papers = await asyncio.to_thread(  # a synchronous client: off the event loop, so the others run meanwhile
            fetch_library, settings.zotero_api_key, user_id=settings.zotero_user_id, group_id=settings.zotero_group_id
        )
        with_pdf = sum(1 for p in papers if p.pdf_url)
        note = f"{len(papers)} items, {with_pdf} with API-servable PDFs"
        if papers and with_pdf == 0:
            note += " (PDFs not in Zotero cloud storage — read_reference falls back to OA-by-DOI)"
        return Check("lit.zotero.library", PASS if papers else FAIL, note)
    except Exception as e:
        return Check("lit.zotero.library", FAIL, repr(e)[:200])


# ── Orchestrators ────────────────────────────────────────────────────────────


#: How long one service may take to accept the connection, and to answer, in a preflight (seconds).
CONNECT_TIMEOUT = 3.0
#: How long one reachability check may take in all; then it fails as "timed out".
CHECK_TIMEOUT = 5.0
#: The checks that do a little more than one small request: the literature search (OpenAlex, then
#: arXiv), the PDF download, Yahoo Finance (its own client), the GMD's release list, Allium, Zotero.
SLOW_CHECK_TIMEOUT = 6.0
#: The most checks that run at the same time.
MAX_CONCURRENT_CHECKS = 16


def _reachability() -> Any:
    from .modules.data.sources.http import reachability

    return reachability(connect=CONNECT_TIMEOUT, read=CHECK_TIMEOUT)


async def _bounded(
    sem: asyncio.Semaphore, name: str, run: Callable[[], Awaitable[Check | None]], budget: float
) -> Check | None:
    """Run one check when a slot is free; a check that takes longer than ``budget`` fails as timed out."""
    async with sem:
        try:
            return await asyncio.wait_for(run(), timeout=budget)
        except TimeoutError:
            return Check(name, FAIL, f"timed out: no answer within {budget:g} s")
        except Exception as e:  # noqa: BLE001 — a broken check is its own result, never the preflight's end
            return Check(name, FAIL, repr(e)[:200])


async def run_provider_checks(settings) -> list[Check]:
    """The provider/network probes — what a paper would have access to.

    They run side by side (at most ``MAX_CONCURRENT_CHECKS`` at once), each within its time budget,
    with short timeouts and no retries, so a computer that is offline learns it in seconds. The
    order of the result is the order below, whatever finishes first.

    Used by both ``e2er doctor`` and ``scripts/live_check.py`` (DRY).
    """
    jobs: list[tuple[str, Callable[[], Awaitable[Check | None]], float]] = [
        ("data.list_data_sources", partial(data_catalog_check, settings), CHECK_TIMEOUT),
        ("data.yfinance.history", partial(yfinance_check, settings), SLOW_CHECK_TIMEOUT),
        ("data.fred.observations", partial(fred_check, settings), CHECK_TIMEOUT),
        ("data.gmd.versions", partial(gmd_check, settings), SLOW_CHECK_TIMEOUT),
        *((name, partial(_source_check, source, settings), CHECK_TIMEOUT) for name, source in _source_jobs()),
        ("data.allium.list_tables", partial(allium_check, settings), SLOW_CHECK_TIMEOUT),
        ("lit.search_papers", partial(openalex_check, settings), SLOW_CHECK_TIMEOUT),
        ("lit.read_reference (OA PDF)", partial(read_reference_check, settings), SLOW_CHECK_TIMEOUT),
        ("lit.zotero.library", partial(zotero_check, settings), SLOW_CHECK_TIMEOUT),
    ]
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    with _reachability():
        results = await asyncio.gather(*(_bounded(sem, name, run, budget) for name, run, budget in jobs))
    checks = [c for c in results if c is not None]
    # The key's format is checked without a request; it stands before the request it decides on.
    key = fred_key_check(settings)
    at = next((i for i, c in enumerate(checks) if c.name == "data.fred.observations"), len(checks))
    return [*checks[:at], key, *checks[at:]]


#: Config trees the CLI backends refuse to write into. The Claude Code CLI
#: rejects its own directory outright; the others are listed for the same
#: reason and cost nothing to check.
_BACKEND_SENSITIVE_DIRS = {
    "claude_code": (".claude",),
    "codex": (".codex",),
    "gemini": (".gemini",),
}


def workspace_writable_check(settings) -> Check:
    """Can the selected backend write into the workspace root?

    A CLI backend runs as a subprocess with its own permission system, and
    Claude Code refuses any path under ~/.claude. The pipeline process can
    write there, so nothing looks wrong until every specialist fails its
    contract with "file not written" — the same message a model that simply
    ignored its contract would produce.
    """
    backend = getattr(settings, "llm_backend", "")
    sensitive = _BACKEND_SENSITIVE_DIRS.get(backend)
    root = Path(getattr(settings, "workspace_root", "workspaces")).expanduser().resolve()

    if not sensitive:
        return Check("workspace.writable", PASS, f"{root} (SDK backend — no CLI permission rules)")

    home = Path.home().resolve()
    for name in sensitive:
        blocked = home / name
        if root == blocked or blocked in root.parents:
            return Check(
                "workspace.writable",
                FAIL,
                f"{root} is inside {blocked} — the {backend} CLI refuses writes to its own "
                "config tree, so every specialist will fail with 'file not written'. "
                "Run from a directory outside it.",
            )
    return Check("workspace.writable", PASS, f"{root} is outside the {backend} config tree")


async def run_doctor(settings) -> list[Check]:
    """Full preflight: setup (backend, skills, DB) + BYOD corpus + provider probes.

    Docker (a subprocess that may take seconds) and the network probes run at the same time.
    """
    docker = asyncio.create_task(asyncio.to_thread(docker_check))
    setup = [
        python_check(),
        await backend_check(settings),
        await skills_check(settings),
        await db_check(settings),
        workspace_writable_check(settings),
        await byod_local_data_check(settings),
        await byod_literature_check(settings),
    ]
    providers = await run_provider_checks(settings)
    return [*setup, await docker, *providers]


# ── Output ───────────────────────────────────────────────────────────────────


_BLOCKERS_PREFIXES = ("python", "backend.", "db", "skills.", "workspace.")


def render_human(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    out = []
    sym = {PASS: "✓", SKIP: "·", FAIL: "✗"}
    for c in checks:
        out.append(f"  {sym[c.status]} [{c.status}] {c.name.ljust(width)}  {c.detail}")
    n_pass = sum(c.status == PASS for c in checks)
    n_skip = sum(c.status == SKIP for c in checks)
    n_fail = sum(c.status == FAIL for c in checks)
    blocker_failed = any(
        c.status == FAIL and (c.name == "backend" or c.name.startswith(_BLOCKERS_PREFIXES)) for c in checks
    )
    backend_unknown = any(c.status == SKIP and c.name.startswith("backend.") for c in checks)
    if n_fail == 0 and backend_unknown:
        verdict = "⚠️  Couldn't check — the AI access is installed, but whether it is signed in is unknown (see above)."
    elif n_fail == 0:
        verdict = '✅ Ready — `e2er run "<your research question>"` should work.'
    elif blocker_failed:
        verdict = "❌ Blocked — fix the backend / DB / skills failure above before running a paper."
    else:
        verdict = "⚠️  Partial — paper runs will work, but some providers/sources are unavailable (see fails above)."
    out.append(f"\n{verdict}\n   {n_pass} passed, {n_skip} skipped, {n_fail} failed")
    return "\n".join(out)


def main_doctor(json_output: bool = False) -> int:
    """Entry point for `e2er doctor`. Exit 0 if no failures, 1 otherwise."""
    from .config import get_settings

    # Not asyncio.run: it waits for every worker thread, and a check that timed out may leave one
    # waiting on the network (yfinance's own client). The answer is printed first; the thread ends on its own.
    loop = asyncio.new_event_loop()
    try:
        checks = loop.run_until_complete(run_doctor(get_settings()))
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()
    if json_output:
        print(json.dumps({"checks": [asdict(c) for c in checks]}, indent=2))
    else:
        print(render_human(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0
