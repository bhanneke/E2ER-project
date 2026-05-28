#!/usr/bin/env python3
"""Live smoke check — exercises real provider paths against real services.

Complements the mocked suite (`make smoke`). Where that runs offline with
no keys, this hits the network and uses whatever BYOK credentials are
configured, auto-skipping providers that aren't set up. It makes **no LLM
calls**, so it's free and fast — it validates the data/literature
integration layer (the providers, the discovery/fetch tools, PDF
extraction), not a full paper pipeline run (use `make smoke-paid` for that).

Run:
    python scripts/live_check.py            # all available paths
    python scripts/live_check.py --json     # machine-readable report to stdout

Exit code: 0 if nothing FAILED (skips are fine), 1 if any check failed.
A report is also written to ``live_check_report.json``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Make `src` importable no matter where this is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS, SKIP, FAIL = "PASS", "SKIP", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def _ok(rows: object) -> int:
    return len(rows) if isinstance(rows, list) else 0


async def run_checks() -> list[Check]:
    from src.config import get_settings
    from src.modules.data.discovery_tools import SeriesDataToolHandler
    from src.modules.data.registry import series_fetchers
    from src.modules.literature.tools import LiteratureToolHandler

    settings = get_settings()
    checks: list[Check] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append(Check(name, status, detail))

    # ── Data: catalog / discovery ────────────────────────────────────────
    try:
        raw = await SeriesDataToolHandler().handle("list_data_sources", {})
        names = [s["name"] for s in json.loads(raw).get("sources", [])]
        add("data.list_data_sources", PASS, f"catalog: {', '.join(names) or '(empty)'}")
    except Exception as e:
        add("data.list_data_sources", FAIL, repr(e)[:200])

    fetchers = {f.name: f for f in series_fetchers(settings)}

    # ── Data: yfinance (keyless) ─────────────────────────────────────────
    try:
        env = await fetchers["yfinance"].fetch(
            "history", {"ticker": "SPY", "interval": "1mo", "start": "2024-01-01", "end": "2024-04-01"}
        )
        n = _ok(env.get("items"))
        add(
            "data.yfinance.history",
            PASS if n > 0 and not env.get("error") else FAIL,
            env.get("error") or f"{n} rows for SPY",
        )
    except Exception as e:
        add("data.yfinance.history", FAIL, repr(e)[:200])

    # ── Data: FRED (needs key) ───────────────────────────────────────────
    if "fred" in fetchers:
        try:
            env = await fetchers["fred"].fetch(
                "observations", {"series_id": "CPIAUCSL", "observation_start": "2024-01-01"}
            )
            n = _ok(env.get("items"))
            add(
                "data.fred.observations",
                PASS if n > 0 and not env.get("error") else FAIL,
                env.get("error") or f"{n} CPI observations",
            )
        except Exception as e:
            add("data.fred.observations", FAIL, repr(e)[:200])
    else:
        add("data.fred.observations", SKIP, "FRED_API_KEY not set")

    # ── Data: Allium connectivity (needs key; light — list tables only) ──
    if settings.allium_api_key:
        try:
            from src.modules.data.allium import AlliumProvider

            tables = await AlliumProvider(settings.allium_api_key, settings.allium_api_base).list_tables()
            add(
                "data.allium.list_tables",
                PASS if tables else FAIL,
                f"{len(tables)} tables" if tables else "no tables returned (tier/rate limit?)",
            )
        except Exception as e:
            add("data.allium.list_tables", FAIL, repr(e)[:200])
    else:
        add("data.allium.list_tables", SKIP, "ALLIUM_API_KEY not set")

    # ── Literature: search (keyless, OpenAlex) ───────────────────────────
    lit = LiteratureToolHandler(Path("/tmp"))
    try:
        raw = await lit.handle("search_papers", {"query": "concentrated liquidity automated market makers", "limit": 3})
        out = json.loads(raw)
        n = out.get("count", 0)
        add("lit.search_papers", PASS if n > 0 else FAIL, out.get("error") or f"{n} papers via {out.get('source')}")
    except Exception as e:
        add("lit.search_papers", FAIL, repr(e)[:200])

    # ── Literature: read_reference on a stable open-access PDF ───────────
    try:
        raw = await lit.handle("read_reference", {"pdf_url": "https://arxiv.org/pdf/1706.03762"})
        out = json.loads(raw)
        chars = out.get("chars", 0)
        add(
            "lit.read_reference (OA PDF)",
            PASS if chars and chars > 500 else FAIL,
            out.get("error") or f"{chars} chars extracted",
        )
    except Exception as e:
        add("lit.read_reference (OA PDF)", FAIL, repr(e)[:200])

    # ── Literature: Zotero library (needs key) ───────────────────────────
    if settings.zotero_enabled:
        try:
            from src.modules.literature.zotero import fetch_library

            papers = fetch_library(
                settings.zotero_api_key, user_id=settings.zotero_user_id, group_id=settings.zotero_group_id
            )
            with_pdf = sum(1 for p in papers if p.pdf_url)
            note = f"{len(papers)} items, {with_pdf} with API-servable PDFs"
            if papers and with_pdf == 0:
                note += " (PDFs not in Zotero cloud storage — read_reference falls back to OA-by-DOI)"
            add("lit.zotero.library", PASS if papers else FAIL, note)
        except Exception as e:
            add("lit.zotero.library", FAIL, repr(e)[:200])
    else:
        add("lit.zotero.library", SKIP, "ZOTERO_API_KEY + user/group id not set")

    return checks


def main() -> int:
    checks = asyncio.run(run_checks())
    report = {"checks": [asdict(c) for c in checks]}
    Path("live_check_report.json").write_text(json.dumps(report, indent=2))

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        width = max(len(c.name) for c in checks)
        for c in checks:
            print(f"  [{c.status}] {c.name.ljust(width)}  {c.detail}")
        n_fail = sum(c.status == FAIL for c in checks)
        n_skip = sum(c.status == SKIP for c in checks)
        n_pass = sum(c.status == PASS for c in checks)
        print(f"\n=== live check: {n_pass} passed, {n_skip} skipped, {n_fail} failed ===")

    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
