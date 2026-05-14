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


async def _run_describe_table(args: argparse.Namespace) -> str:
    """Discovery primitive: list columns + types for a table.

    Goes directly through AlliumProvider rather than the tool handler —
    no guardrail validation needed (read-only INFORMATION_SCHEMA query).
    """
    import json as _json

    from ...config import get_settings
    from .allium import AlliumProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumProvider(settings.allium_api_key, settings.allium_api_base)
    cols = await provider.describe_table(args.schema, args.table)
    if not cols:
        return (
            f"No columns found for {args.schema}.{args.table}. Either the table "
            f"doesn't exist, or it's outside your Allium plan tier, or "
            f"INFORMATION_SCHEMA access is restricted. Try `list-tables` to see "
            f"what's available."
        )
    return _json.dumps({"schema": args.schema, "table": args.table, "columns": cols}, indent=2, default=str)


async def _run_dev_transfers(args: argparse.Namespace) -> str:
    """Developer-tier endpoint: ERC-20 Transfer events for a token over a window.

    Use for transfer-flow event studies — pull transfers of the affected
    token ±N days around an exploit timestamp.
    """
    import json as _json

    from .allium_developer import AlliumDeveloperProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumDeveloperProvider(settings.allium_api_key, settings.allium_api_base)
    result = await provider.get_token_transfers(
        chain=args.chain,
        token_address=args.token_address,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        limit=args.limit,
        next_token=args.next_token,
    )
    return _json.dumps(result, indent=2, default=str)


async def _run_dev_wallet_tx(args: argparse.Namespace) -> str:
    """Developer-tier endpoint: tx history for any address.

    Use this on documented hacker addresses to capture drain transactions
    and the laundering timeline.
    """
    import json as _json

    from .allium_developer import AlliumDeveloperProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumDeveloperProvider(settings.allium_api_key, settings.allium_api_base)
    result = await provider.get_wallet_transactions(
        chain=args.chain,
        address=args.address,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        limit=args.limit,
    )
    return _json.dumps(result, indent=2, default=str)


async def _run_dev_balances_history(args: argparse.Namespace) -> str:
    """Developer-tier endpoint: daily balance snapshots for an address."""
    import json as _json

    from .allium_developer import AlliumDeveloperProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumDeveloperProvider(settings.allium_api_key, settings.allium_api_base)
    result = await provider.get_wallet_balances_history(
        chain=args.chain,
        address=args.address,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
    return _json.dumps(result, indent=2, default=str)


async def _run_dev_prices_history(args: argparse.Namespace) -> str:
    """Developer-tier endpoint: OHLC price history for a fungible token.

    Returns empty for NFT contracts. Sanity-check with get-price first if
    unsure whether a contract is indexed.
    """
    import json as _json

    from .allium_developer import AlliumDeveloperProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumDeveloperProvider(settings.allium_api_key, settings.allium_api_base)
    result = await provider.get_token_prices_history(
        chain=args.chain,
        token_address=args.token_address,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
    return _json.dumps(result, indent=2, default=str)


async def _run_dev_get_price(args: argparse.Namespace) -> str:
    """Developer-tier endpoint: latest spot price for a token (sanity check)."""
    import json as _json

    from .allium_developer import AlliumDeveloperProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumDeveloperProvider(settings.allium_api_key, settings.allium_api_base)
    result = await provider.get_token_latest_price(chain=args.chain, token_address=args.token_address)
    return _json.dumps(result, indent=2, default=str)


async def _run_distinct_values(args: argparse.Namespace) -> str:
    """Discovery primitive: show actual literal values + frequency for a column.

    Use this BEFORE composing `WHERE col IN (...)` filters — Allium may
    store marketplace names as 'OpenSea', 'opensea', or contract
    addresses; this returns the real values so the model uses what's
    there, not what it guessed.
    """
    import json as _json

    from ...config import get_settings
    from .allium import AlliumProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumProvider(settings.allium_api_key, settings.allium_api_base)
    values = await provider.distinct_values(args.schema, args.table, args.column, limit=args.limit)
    if not values:
        return (
            f"No distinct values returned for {args.schema}.{args.table}.{args.column}. "
            f"Either the column is empty, doesn't exist, or the discovery query "
            f"was rejected. Try `describe-table --schema {args.schema} --table "
            f"{args.table}` to confirm the column name."
        )
    return _json.dumps(
        {"schema": args.schema, "table": args.table, "column": args.column, "values": values},
        indent=2,
        default=str,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2er-allium-query",
        description=(
            "Gatekeeper for Allium queries from the Claude Code CLI backend. "
            "Same 5 guardrails, same audit log, same approval flow as the in-process tool."
        ),
    )

    # paper_id and specialist are runner-supplied context — they're the same
    # for every call within a specialist invocation. The runner sets them
    # via E2ER_PAPER_ID / E2ER_SPECIALIST env vars; the bash wrapper or this
    # parser pick them up. CLI flags override env so devs can still test
    # invocations manually.
    parser.add_argument(
        "--paper-id",
        default=None,
        help="Paper UUID. Defaults to $E2ER_PAPER_ID; required if neither is set.",
    )
    parser.add_argument(
        "--specialist",
        default=None,
        help="Specialist name (audit log). Defaults to $E2ER_SPECIALIST or 'data_analyst'.",
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

    # --- describe-table (discovery)
    p = sub.add_parser(
        "describe-table",
        help="List columns + types for a table (no guardrail needed; read-only).",
    )
    p.add_argument("--schema", required=True, help="e.g. ethereum, polygon, base")
    p.add_argument("--table", required=True, help="e.g. nft_trades, transactions")

    # --- distinct-values (discovery)
    p = sub.add_parser(
        "distinct-values",
        help="Show actual values + frequency for a column. Use this BEFORE WHERE col IN (...).",
    )
    p.add_argument("--schema", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--column", required=True, help="e.g. marketplace, currency_symbol, chain")
    p.add_argument("--limit", type=int, default=100, help="Max distinct values returned (default 100).")

    # --- Developer-tier REST endpoints (works when Explorer SQL doesn't) ---
    p = sub.add_parser(
        "get-transfers",
        help="ERC-20 Transfer events for a token over a time window (developer tier).",
    )
    p.add_argument("--chain", required=True, help="e.g. ethereum, polygon, arbitrum, base")
    p.add_argument("--token-address", required=True, help="0x-prefixed contract address")
    p.add_argument(
        "--from-ts",
        dest="from_ts",
        default=None,
        help="ISO timestamp (e.g. 2022-03-22T00:00:00Z) or YYYY-MM-DD",
    )
    p.add_argument("--to-ts", dest="to_ts", default=None, help="ISO timestamp or YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=100, help="Max rows per page (default 100)")
    p.add_argument(
        "--next-token",
        dest="next_token",
        default=None,
        help="Pagination token from a previous response, if continuing.",
    )

    p = sub.add_parser(
        "get-wallet-tx",
        help="Transaction history for an address (developer tier). Use on hacker EOAs.",
    )
    p.add_argument("--chain", required=True)
    p.add_argument("--address", required=True, help="0x-prefixed address")
    p.add_argument("--from-ts", dest="from_ts", default=None)
    p.add_argument("--to-ts", dest="to_ts", default=None)
    p.add_argument("--limit", type=int, default=100)

    p = sub.add_parser(
        "get-balances-history",
        help="Daily balance snapshots for an address (developer tier).",
    )
    p.add_argument("--chain", required=True)
    p.add_argument("--address", required=True)
    p.add_argument("--from-ts", dest="from_ts", required=True, help="Required: YYYY-MM-DD")
    p.add_argument("--to-ts", dest="to_ts", required=True, help="Required: YYYY-MM-DD")

    p = sub.add_parser(
        "get-prices-history",
        help="OHLC price history for a fungible token (developer tier). Empty for NFTs.",
    )
    p.add_argument("--chain", required=True)
    p.add_argument("--token-address", required=True)
    p.add_argument("--from-ts", dest="from_ts", required=True)
    p.add_argument("--to-ts", dest="to_ts", required=True)

    p = sub.add_parser(
        "get-price",
        help="Latest spot price for a token (developer tier). Sanity check.",
    )
    p.add_argument("--chain", required=True)
    p.add_argument("--token-address", required=True)

    return parser


_DISPATCH = {
    "feasibility": _run_feasibility,
    "production": _run_production,
    "check-approval": _run_check_approval,
    "describe-table": _run_describe_table,
    "distinct-values": _run_distinct_values,
    "list-tables": _run_list_tables,
    "get-transfers": _run_dev_transfers,
    "get-wallet-tx": _run_dev_wallet_tx,
    "get-balances-history": _run_dev_balances_history,
    "get-prices-history": _run_dev_prices_history,
    "get-price": _run_dev_get_price,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    import os

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Resolve paper_id / specialist: explicit flag wins, then env var, then
    # default. Without paper_id we cannot route the query (workspace lookup
    # + audit log both need it).
    args.paper_id = args.paper_id or os.environ.get("E2ER_PAPER_ID")
    args.specialist = args.specialist or os.environ.get("E2ER_SPECIALIST") or "data_analyst"
    if not args.paper_id:
        print(
            "e2er-allium-query: paper_id missing. Pass --paper-id <uuid> or set "
            "E2ER_PAPER_ID in the environment. (Normally the runner injects this "
            "automatically; this error means the wrapper is being called outside a "
            "specialist run.)",
            file=sys.stderr,
        )
        return 2

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
