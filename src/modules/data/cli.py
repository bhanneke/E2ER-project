"""Allium-via-CLI gatekeeper: same guardrails, subprocess entry point.

Why this exists:
  When `LLM_BACKEND=claude_code`, specialists run inside the Claude Code CLI
  subprocess. The CLI's tool dispatch is internal, so the in-process
  `AlliumToolHandler` (which validates the 5 Allium guardrails on every
  query) cannot intercept anything. Without this gatekeeper, CLI users
  would have to disable the data module entirely.

How it works:
  This module is invoked as `python -m src.modules.data.cli <subcommand>`
  via the `scripts/e2er-allium-query` bash wrapper. The Claude Code CLI is
  configured with `--allowedTools=Bash(e2er-allium-query:*)` — that bash
  pattern is the *only* path to Allium for the specialist. Direct HTTP
  to Allium and other bash invocations are denied at the CLI's tool layer.

  Internally we construct the existing `AlliumToolHandler` and call its
  methods. The 5 guardrails (no SELECT *, fields in dictionary, time-bound
  WHERE, granularity justification, feasibility-first), the audit log, and
  the human-approval flow all use the SAME code as the SDK backends.

Subcommands:
  feasibility    Run a 1000-row sample query (auto-approved).
  production     Submit a full query for human approval.
  check-approval Poll for the approval status of a production query.
  list-tables    List available Allium dataset schemas/tables.

stdout contains the same text `AlliumToolHandler.handle()` returns to the
LLM in API mode — guardrail rejections, query_ids, sample rows, status.
The CLI subprocess sees this as bash command output. Exit code is always
0 (the model reads the output regardless); fatal errors print to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from ...config import get_settings
from ...logging_config import get_logger

logger = get_logger(__name__)


def _build_handler(paper_id: str, specialist: str, workspace: Path) -> Any:
    """Build the same AlliumToolHandler used in API-backend mode.

    Reads `data_dictionary.json` from the workspace (the paper's
    pre-declared minimal data footprint). If absent, the dictionary
    guardrails (fields-in-dict, granularity) are skipped — the SQL/time/
    feasibility guardrails still fire.
    """
    from .dictionary import DataDictionary
    from .tools import AlliumToolHandler

    dictionary: DataDictionary | None = None
    dict_path = workspace / "data_dictionary.json"
    if dict_path.exists():
        try:
            dictionary = DataDictionary.model_validate_json(dict_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(
                f"Warning: data_dictionary.json present but invalid ({e}). "
                "Dictionary-dependent guardrails will be skipped.",
                file=sys.stderr,
            )

    return AlliumToolHandler(
        paper_id=paper_id,
        specialist=specialist,
        dictionary=dictionary,
    )


def _resolve_workspace(paper_id: str) -> Path:
    """Workspace path = settings.workspace_root / paper_id."""
    return Path(get_settings().workspace_root) / paper_id


async def _run_feasibility(args: argparse.Namespace) -> str:
    handler = _build_handler(args.paper_id, args.specialist, _resolve_workspace(args.paper_id))
    return await handler.handle(
        "query_allium",
        {
            "sql": args.sql,
            "query_type": "feasibility",
            "fields_requested": [f.strip() for f in args.fields.split(",") if f.strip()] if args.fields else [],
            "aggregation_level": args.aggregation,
            "rationale": args.rationale or "",
            "primary_table": args.primary_table or "",
            "estimated_rows": args.estimated_rows,
        },
    )


async def _run_production(args: argparse.Namespace) -> str:
    handler = _build_handler(args.paper_id, args.specialist, _resolve_workspace(args.paper_id))
    return await handler.handle(
        "query_allium",
        {
            "sql": args.sql,
            "query_type": "production",
            "fields_requested": [f.strip() for f in args.fields.split(",") if f.strip()] if args.fields else [],
            "aggregation_level": args.aggregation,
            "rationale": args.rationale or "",
            "primary_table": args.primary_table or "",
            "estimated_rows": args.estimated_rows,
        },
    )


async def _run_check_approval(args: argparse.Namespace) -> str:
    handler = _build_handler(args.paper_id, args.specialist, _resolve_workspace(args.paper_id))
    return await handler.handle("check_approval", {"query_id": args.query_id})


async def _run_list_tables(args: argparse.Namespace) -> str:
    handler = _build_handler(args.paper_id, args.specialist, _resolve_workspace(args.paper_id))
    return await handler.handle("list_allium_tables", {})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2er-allium-query",
        description=(
            "Gatekeeper for Allium queries from the Claude Code CLI backend. "
            "Same 5 guardrails, same audit log, same approval flow as the in-process tool."
        ),
    )

    # All subcommands need paper_id (drives workspace + audit log).
    parser.add_argument("--paper-id", required=True, help="Paper UUID this query belongs to.")
    parser.add_argument(
        "--specialist",
        default="data_analyst",
        help="Specialist invoking this query (for audit log).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # --- feasibility / production share the same query options
    for name, help_text in [
        ("feasibility", "Sample query (1000-row LIMIT, auto-approved)."),
        ("production", "Full query, requires prior feasibility + human approval."),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--sql", required=True, help="SQL query string.")
        p.add_argument(
            "--fields",
            default="",
            help="Comma-separated list of column names selected (must match data_dictionary.json).",
        )
        p.add_argument(
            "--aggregation",
            required=True,
            choices=["transaction", "event", "daily", "weekly", "custom"],
            help="Granularity of result rows.",
        )
        p.add_argument(
            "--rationale", default="", help="Why this query is needed (also justifies transaction/event granularity)."
        )
        p.add_argument("--primary-table", default="", help="Main table being queried (for feasibility-first check).")
        p.add_argument("--estimated-rows", type=int, default=None, help="Your estimate of result-set size.")

    # --- check-approval
    p = sub.add_parser("check-approval", help="Poll a production query's approval status.")
    p.add_argument("--query-id", required=True, help="query_id returned when production query was submitted.")

    # --- list-tables
    sub.add_parser("list-tables", help="List Allium dataset schemas and tables.")

    return parser


_DISPATCH = {
    "feasibility": _run_feasibility,
    "production": _run_production,
    "check-approval": _run_check_approval,
    "list-tables": _run_list_tables,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    runner = _DISPATCH.get(args.command)
    if runner is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(runner(args))
    except Exception as e:
        # Fatal infrastructure error (DB unavailable, no Allium key, etc.).
        # Guardrail rejections come back as a string from handler.handle()
        # — those are NOT exceptions and reach the print() below.
        print(f"e2er-allium-query failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
