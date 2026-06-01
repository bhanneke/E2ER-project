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
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

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


def _mask_db_url(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


# ── Preflight: the stuff a real run needs to even start ──────────────────────


async def backend_check(settings) -> Check:
    backend = settings.llm_backend
    if backend in {"anthropic", "openrouter"}:
        key = settings.anthropic_api_key if backend == "anthropic" else settings.openrouter_api_key
        if not key:
            return Check(f"backend.{backend}", FAIL, f"{backend.upper()}_API_KEY not set — `e2er run` will fail")
        return Check(f"backend.{backend}", PASS, "API key configured (metered backend)")
    cli = _BACKEND_CLI.get(backend)
    if cli is None:
        return Check(f"backend.{backend}", FAIL, f"unknown backend literal: {backend!r}")
    path = shutil.which(cli)
    if not path:
        return Check(f"backend.{backend}", FAIL, f"`{cli}` CLI not on PATH — install per the README")
    return Check(f"backend.{backend}", PASS, f"CLI at {path} ($0 flat-rate)")


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


async def fred_check(settings) -> Check:
    if not settings.fred_api_key:
        return Check("data.fred.observations", SKIP, "FRED_API_KEY not set")
    from .modules.data.registry import series_fetchers

    fetchers = {f.name: f for f in series_fetchers(settings)}
    try:
        env = await fetchers["fred"].fetch("observations", {"series_id": "CPIAUCSL", "observation_start": "2024-01-01"})
        n = _len(env.get("items"))
        ok = bool(n) and not env.get("error")
        return Check("data.fred.observations", PASS if ok else FAIL, env.get("error") or f"{n} CPI observations")
    except Exception as e:
        return Check("data.fred.observations", FAIL, repr(e)[:200])


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

        papers = fetch_library(
            settings.zotero_api_key, user_id=settings.zotero_user_id, group_id=settings.zotero_group_id
        )
        with_pdf = sum(1 for p in papers if p.pdf_url)
        note = f"{len(papers)} items, {with_pdf} with API-servable PDFs"
        if papers and with_pdf == 0:
            note += " (PDFs not in Zotero cloud storage — read_reference falls back to OA-by-DOI)"
        return Check("lit.zotero.library", PASS if papers else FAIL, note)
    except Exception as e:
        return Check("lit.zotero.library", FAIL, repr(e)[:200])


# ── Orchestrators ────────────────────────────────────────────────────────────


async def run_provider_checks(settings) -> list[Check]:
    """The provider/network probes — what a paper would have access to.

    Used by both ``e2er doctor`` and ``scripts/live_check.py`` (DRY).
    """
    return [
        await data_catalog_check(settings),
        await yfinance_check(settings),
        await fred_check(settings),
        await allium_check(settings),
        await openalex_check(settings),
        await read_reference_check(settings),
        await zotero_check(settings),
    ]


async def run_doctor(settings) -> list[Check]:
    """Full preflight: setup (backend, skills, DB) + provider probes."""
    return [
        await backend_check(settings),
        await skills_check(settings),
        await db_check(settings),
        *await run_provider_checks(settings),
    ]


# ── Output ───────────────────────────────────────────────────────────────────


_BLOCKERS_PREFIXES = ("backend.", "db", "skills.")


def render_human(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    out = []
    sym = {PASS: "✓", SKIP: "·", FAIL: "✗"}
    for c in checks:
        out.append(f"  {sym[c.status]} [{c.status}] {c.name.ljust(width)}  {c.detail}")
    n_pass = sum(c.status == PASS for c in checks)
    n_skip = sum(c.status == SKIP for c in checks)
    n_fail = sum(c.status == FAIL for c in checks)
    blocker_failed = any(c.status == FAIL and c.name.startswith(_BLOCKERS_PREFIXES) for c in checks)
    if n_fail == 0:
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

    checks = asyncio.run(run_doctor(get_settings()))
    if json_output:
        print(json.dumps({"checks": [asdict(c) for c in checks]}, indent=2))
    else:
        print(render_human(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0
