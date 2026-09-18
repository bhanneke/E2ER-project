"""Literature-via-CLI bridge: the same providers, a subprocess entry point.

WHY THIS EXISTS

`ClaudeCodeBackend.tool_loop` says it plainly: "`tool_handler` and `tools` are
ignored — the CLI uses its native tool set, allowed via `--allowedTools`". So on
every CLI backend (claude_code, codex, gemini) the LITERATURE_TOOLS registered
in `api/app.py` — search_papers, fetch_paper, save_bibtex, read_reference — are
unreachable. The data module got a bash bridge (`e2er-data`), Allium got one
(`e2er-allium-query`), script execution got `e2er-run`, table specs got
`e2er-check-tables`. Literature never did.

The 2026-09-01 repeats cell is the cost. No run produced a bibliography of any
kind: `assemble_refs_bib` returned None, the citation gate found nothing to
check, and both reviewed drafts cited real papers from model memory that no
`.bib` backed — 14 keys in paper 7274dddc, 19 in ee229dca. LaTeX then had an
undefined reference for every one, which is the likeliest reason no run
compiled a PDF.

TWO DELIBERATE DIFFERENCES FROM THE SDK TOOLS

1. `search` PERSISTS. Every hit is written to the workspace's literature.bib,
   deduped by key. In the SDK path searching and saving are separate calls and
   the model has to remember the second one; that is precisely the step that
   never happened. A bibliography with some uncited entries is a warning
   (`bibbed_uncited`); a draft with no bibliography does not compile. Pass
   `--no-save` to search without recording.

2. Budgets PERSIST ACROSS INVOCATIONS. The handler's caps
   (_MAX_SEARCHES etc.) live on the instance, and one bash call is one process,
   so they would reset every time — defeating the cap added after a single
   literature_scanner run burned 522K tokens on 36 tool calls. Counts are kept
   in `<workspace>/.lit_budget.json`, keyed by specialist.

Everything else — the provider chain, the local-library shortcut, the OA
resolvers — is the same code the SDK backends use.

Subcommands:
  search <query>   Search and record the hits in literature.bib.
  list             Show what literature.bib currently holds.
  save             Record one paper by --doi or --entry.
  read             Extract text from a reference (--path/--pdf-url/--doi).

stdout is what the model reads. Exit code is 0 whenever the model should read
the output; 2 for usage errors.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

_BUDGET_FILE = ".lit_budget.json"


def _budget_path(workspace: Path) -> Path:
    return workspace / _BUDGET_FILE


def _load_budget(workspace: Path, specialist: str) -> dict[str, int]:
    try:
        data = json.loads(_budget_path(workspace).read_text(encoding="utf-8"))
        counts = data.get(specialist)
        return dict(counts) if isinstance(counts, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_budget(workspace: Path, specialist: str, counts: dict[str, int]) -> None:
    path = _budget_path(workspace)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[specialist] = counts
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("could not persist literature budget: %s", e)


def _handler(workspace: Path, specialist: str):
    """The same LiteratureToolHandler the SDK backends use, with its call
    counters restored from disk so budgets survive across bash invocations."""
    from .tools import LiteratureToolHandler

    h = LiteratureToolHandler(workspace)
    counts = _load_budget(workspace, specialist)
    h._search_calls = counts.get("search", 0)
    h._fetch_calls = counts.get("fetch", 0)
    h._save_calls = counts.get("save", 0)
    h._read_calls = counts.get("read", 0)
    return h


def _persist(workspace: Path, specialist: str, h: Any) -> None:
    _save_budget(
        workspace,
        specialist,
        {
            "search": h._search_calls,
            "fetch": h._fetch_calls,
            "save": h._save_calls,
            "read": h._read_calls,
        },
    )


def _bib_keys(workspace: Path) -> list[str]:
    import re

    path = workspace / "literature.bib"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r"^@\w+\s*\{\s*([^,\s]+)", text, re.MULTILINE)))


async def _cmd_search(args, workspace: Path, specialist: str) -> int:
    from .discovery import _write_literature_bib
    from .registry import search_sources

    h = _handler(workspace, specialist)
    raw = await h.handle("search_papers", {"query": args.query, "limit": args.limit})
    _persist(workspace, specialist, h)

    payload = json.loads(raw)
    if payload.get("error"):
        print(payload["error"])
        return 0

    # Re-run the provider chain to get PaperMetadata objects for persistence.
    # `handle` returns dicts, and `_write_literature_bib` (the same writer the
    # BYOD path uses) needs the models. The providers cache upstream, and this
    # keeps one code path for bib writing rather than a second serializer.
    items: list = []
    if args.save and payload.get("source") != "local_library":
        from ...config import get_settings

        for source in search_sources(get_settings()):
            try:
                result = await source.search(args.query, args.limit)
            except Exception as e:  # noqa: BLE001
                logger.info("%s search failed (%s) — trying next source", source.name, e)
                continue
            if result.papers:
                items = list(result.papers)
                break
        if items:
            _write_literature_bib(workspace, items)

    papers = payload.get("papers") or []
    print(f"{len(papers)} result(s) from {payload.get('source', 'unknown')} for: {args.query}")
    if args.save and items:
        print("Recorded in literature.bib. Cite these with the key shown — no other key exists.\n")
    # Index rather than zip: a provider that returns a different number of
    # models than dicts must not silently truncate the listing.
    for i, p in enumerate(papers):
        meta = items[i] if i < len(items) else None
        key = getattr(meta, "bibtex_key", None) or "(not recorded)"
        title = (p.get("title") or "")[:100]
        print(f"  \\cite{{{key}}}  {p.get('year') or '????'}  {title}")
        if p.get("doi"):
            print(f"      doi: {p['doi']}")
    if not args.save:
        print("\n(--no-save: nothing was recorded, so these keys are NOT citable yet)")
    return 0


async def _cmd_list(args, workspace: Path, specialist: str) -> int:
    keys = _bib_keys(workspace)
    if not keys:
        print("literature.bib is empty or absent — nothing is citable yet. Run `e2er-lit search` first.")
        return 0
    print(f"{len(keys)} entry/entries in literature.bib. These are the ONLY citable keys:")
    for k in keys:
        print(f"  \\cite{{{k}}}")
    return 0


async def _cmd_save(args, workspace: Path, specialist: str) -> int:
    if not args.doi and not args.entry:
        print("e2er-lit save: pass --doi or --entry", file=sys.stderr)
        return 2
    h = _handler(workspace, specialist)
    inp: dict[str, Any] = {}
    if args.doi:
        inp["doi"] = args.doi
    if args.entry:
        inp["bibtex_entry"] = args.entry
    print(await h.handle("save_bibtex", inp))
    _persist(workspace, specialist, h)
    return 0


async def _cmd_read(args, workspace: Path, specialist: str) -> int:
    if not (args.path or args.pdf_url or args.doi):
        print("e2er-lit read: pass --path, --pdf-url or --doi", file=sys.stderr)
        return 2
    h = _handler(workspace, specialist)
    inp = {k: v for k, v in (("path", args.path), ("pdf_url", args.pdf_url), ("doi", args.doi)) if v}
    print(await h.handle("read_reference", inp))
    _persist(workspace, specialist, h)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e2er-lit", description="Literature search and bibliography for E2ER specialists.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search the literature and record hits in literature.bib")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--no-save", dest="save", action="store_false", default=True)
    s.set_defaults(fn=_cmd_search)

    ls = sub.add_parser("list", help="list the citable keys in literature.bib")
    ls.set_defaults(fn=_cmd_list)

    sv = sub.add_parser("save", help="record one paper by DOI or BibTeX entry")
    sv.add_argument("--doi")
    sv.add_argument("--entry")
    sv.set_defaults(fn=_cmd_save)

    rd = sub.add_parser("read", help="extract text from a reference PDF")
    rd.add_argument("--path")
    rd.add_argument("--pdf-url", dest="pdf_url")
    rd.add_argument("--doi")
    rd.set_defaults(fn=_cmd_read)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # The wrapper runs us from the project root, so the workspace is passed
    # through the env the runner already injects rather than inferred from cwd.
    workspace = Path(os.environ.get("E2ER_WORKSPACE") or Path.cwd())
    specialist = os.environ.get("E2ER_SPECIALIST") or "unknown"
    return asyncio.run(args.fn(args, workspace, specialist))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
