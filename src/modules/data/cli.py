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
import os
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
    """Workspace path = workspace_root / paper_id.

    `workspace_root` is read from the ``E2ER_WORKSPACE_ROOT`` env var when
    set (the runner injects an absolute path), otherwise from
    ``settings.workspace_root`` (defaults to the relative string ``"workspaces"``).

    Why the env var: the claude_code subprocess runs with cwd = the paper's
    workspace dir. If we resolve a relative ``"workspaces"`` against that cwd
    we get ``<workspace>/workspaces/<id>``, i.e. a nested directory. Live
    test eea5379b on v0.4.4 wrote ``yfinance_SPY_2020_2026.csv`` to
    ``workspaces/<id>/workspaces/<id>/data/`` for exactly this reason — and
    the model dutifully papered over it with a ``_candidate_csv_paths``
    fallback in estimation.py. The env var makes the resolution stable
    regardless of subprocess cwd.
    """
    root = os.environ.get("E2ER_WORKSPACE_ROOT") or get_settings().workspace_root
    return Path(root) / paper_id


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
    """Developer-tier endpoint: token transfers involving a wallet.

    Despite the name, Allium scopes this to one wallet `address`. Use
    for hack-event studies by pointing `--address` at the hacker EOA and
    bounding `--min-timestamp / --max-timestamp` to the window.
    """
    import json as _json

    from .allium_developer import AlliumDeveloperProvider

    settings = get_settings()
    if not settings.allium_api_key:
        return "Allium not configured. Set ALLIUM_API_KEY in .env."
    provider = AlliumDeveloperProvider(settings.allium_api_key, settings.allium_api_base)
    result = await provider.get_token_transfers(
        chain=args.chain,
        address=args.address,
        token=args.token,
        min_timestamp=args.min_timestamp,
        max_timestamp=args.max_timestamp,
        limit=args.limit,
        cursor=args.cursor,
    )
    return _json.dumps(result, indent=2, default=str)


async def _run_dev_wallet_tx(args: argparse.Namespace) -> str:
    """Developer-tier endpoint: tx history for any address.

    Allium does NOT support date filters on this endpoint. Returns the
    most recent transactions; page back through history with `--cursor`.
    For older events, prefer `get-transfers` which DOES support
    min_timestamp/max_timestamp.
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
        limit=args.limit,
        cursor=args.cursor,
        transaction_hash=args.transaction_hash,
        activity_type=args.activity_type,
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


# ---------------------------------------------------------------------------
# Raw-data persistence — every public-source handler routes its result
# through _maybe_save_csv. When the caller passes --save-to <path>, the
# items list is written to workspace/data/<path>.csv (path is relative;
# absolute paths are rejected to keep extractions confined to the
# workspace and replication-package-friendly).
# ---------------------------------------------------------------------------


def _maybe_save_csv(result: dict, args: argparse.Namespace) -> None:
    """If `--save-to <rel/path>` was passed, dump result['items'] to a CSV
    under ``workspace/data/<rel/path>``. The summary text and `error` are
    still returned as the bash output (model still sees what happened);
    the CSV is the persisted artifact.
    """
    save_to = getattr(args, "save_to", None)
    if not save_to:
        return
    items = (result or {}).get("items") or []
    if not items:
        # Nothing to save — but record the skip in the result envelope so
        # the model sees it and doesn't keep retrying.
        result["save_skipped"] = "no items to persist"
        return

    # Resolve target path: <workspace>/data/<save_to>. Reject absolute
    # paths + paths trying to escape the workspace (no `../` shenanigans).
    if save_to.startswith("/") or ".." in Path(save_to).parts:
        result["save_error"] = f"--save-to must be a relative path within workspace/data/; got {save_to!r}"
        return

    workspace = _resolve_workspace(args.paper_id)
    target = workspace / "data" / save_to
    target.parent.mkdir(parents=True, exist_ok=True)

    # Lazy import — avoid pulling pandas into the hot path for callers
    # that don't use --save-to.
    try:
        import pandas as pd

        df = pd.DataFrame(items)
        df.to_csv(target, index=False)
        result["saved_to"] = str(target.relative_to(workspace))
        result["saved_rows"] = len(df)
    except Exception as e:
        result["save_error"] = f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# yfinance handlers — public Yahoo Finance data, no API key.
# ---------------------------------------------------------------------------


async def _run_yf_history(args: argparse.Namespace) -> str:
    """OHLCV time series for a single ticker."""
    import json as _json

    from .yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    result = await provider.history(
        ticker=args.ticker,
        start=args.start,
        end=args.end,
        interval=args.interval,
        auto_adjust=not args.raw,
    )
    _maybe_save_csv(result, args)
    return _json.dumps(result, indent=2, default=str)


async def _run_yf_ticker_info(args: argparse.Namespace) -> str:
    """Current snapshot for a ticker (price, market cap, sector, beta, ...)."""
    import json as _json

    from .yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    result = await provider.ticker_info(ticker=args.ticker)
    return _json.dumps(result, indent=2, default=str)


async def _run_yf_fundamentals(args: argparse.Namespace) -> str:
    """Annual financial statements: income, balance_sheet, or cash_flow."""
    import json as _json

    from .yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    result = await provider.fundamentals(ticker=args.ticker, statement=args.statement)
    _maybe_save_csv(result, args)
    return _json.dumps(result, indent=2, default=str)


async def _run_yf_dividends(args: argparse.Namespace) -> str:
    """Full dividend history for a ticker."""
    import json as _json

    from .yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    result = await provider.dividends(ticker=args.ticker)
    _maybe_save_csv(result, args)
    return _json.dumps(result, indent=2, default=str)


async def _run_yf_search(args: argparse.Namespace) -> str:
    """Name-to-ticker lookup."""
    import json as _json

    from .yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    result = await provider.search(query=args.query, max_results=args.max_results)
    return _json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# FRED handlers — Federal Reserve Economic Data, free key.
# ---------------------------------------------------------------------------


def _fred_provider_or_error_envelope() -> tuple[Any, str | None]:
    """Build FredProvider from settings; return (provider, None) or (None, json_error_str)."""
    import json as _json

    settings = get_settings()
    if not settings.fred_api_key:
        msg = _json.dumps(
            {
                "source": "fred",
                "items": [],
                "error": (
                    "FRED_API_KEY not configured. Set it in .env. "
                    "Get a free key (~30s) at https://fredaccount.stlouisfed.org/apikey"
                ),
            },
            indent=2,
        )
        return None, msg
    from .fred_provider import FredProvider

    return FredProvider(settings.fred_api_key), None


async def _run_fred_series(args: argparse.Namespace) -> str:
    """Pull a FRED series time series."""
    import json as _json

    provider, err = _fred_provider_or_error_envelope()
    if provider is None:
        return err or ""
    result = await provider.get_series_observations(
        series_id=args.series_id,
        observation_start=args.start,
        observation_end=args.end,
        frequency=args.frequency,
        units=args.units,
        limit=args.limit,
    )
    _maybe_save_csv(result, args)
    return _json.dumps(result, indent=2, default=str)


async def _run_fred_series_info(args: argparse.Namespace) -> str:
    """Metadata for a FRED series — units, frequency, etc."""
    import json as _json

    provider, err = _fred_provider_or_error_envelope()
    if provider is None:
        return err or ""
    result = await provider.get_series_info(series_id=args.series_id)
    return _json.dumps(result, indent=2, default=str)


async def _run_fred_search(args: argparse.Namespace) -> str:
    """Free-text search for FRED series."""
    import json as _json

    provider, err = _fred_provider_or_error_envelope()
    if provider is None:
        return err or ""
    result = await provider.search_series(
        query=args.query,
        limit=args.limit,
        order_by=args.order_by,
    )
    return _json.dumps(result, indent=2, default=str)


async def _run_fred_releases(args: argparse.Namespace) -> str:
    """List FRED releases."""
    import json as _json

    provider, err = _fred_provider_or_error_envelope()
    if provider is None:
        return err or ""
    result = await provider.get_releases(limit=args.limit)
    return _json.dumps(result, indent=2, default=str)


def _add_save_to(p: argparse.ArgumentParser) -> None:
    """Add the `--save-to <rel/path.csv>` flag to a data-pulling subcommand.

    When passed, the wrapper writes ``result['items']`` to
    ``workspace/data/<rel/path>`` after the call. Specialists should use
    this on every meaningful extraction so the replication package is
    runnable offline.
    """
    p.add_argument(
        "--save-to",
        dest="save_to",
        default=None,
        help=(
            "Persist the response rows as a CSV under workspace/data/<rel/path>. "
            "Use this whenever the data will be referenced in the paper — replication "
            "scripts re-read from disk, not from re-running the API call. Path is "
            "relative to workspace/data/; absolute paths are rejected."
        ),
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

    # Top-level: dispatch by data source. Each source (allium, yfinance, …)
    # gets its own nested subparser group. The invocation shape is:
    #   e2er-data <source> <command> [options]
    # e.g.
    #   e2er-data allium feasibility --sql "..." --aggregation daily ...
    #   e2er-data yfinance history --ticker AAPL --from 2020-01-01 ...
    #
    # Allium-specific guardrails (no SELECT *, time-bound WHERE, dictionary
    # fields, granularity, feasibility-first) only run for the `allium`
    # source. Public sources (yfinance, FRED, …) just get rate-limit
    # handling and audit logging — different cost model.
    sources = parser.add_subparsers(dest="source", required=True)

    allium_parser = sources.add_parser("allium", help="Allium blockchain data (with the 5-rule guardrails)")
    sub = allium_parser.add_subparsers(dest="command", required=True)

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
        help=(
            "Token transfers involving a wallet over an optional date window "
            "(developer tier). Wallet-oriented despite the path name."
        ),
    )
    p.add_argument("--chain", required=True, help="e.g. ethereum, polygon, arbitrum, base")
    p.add_argument(
        "--address",
        required=True,
        help="0x-prefixed WALLET address (e.g. hacker EOA). Not a token contract.",
    )
    p.add_argument(
        "--token",
        default=None,
        help="Optional 0x-prefixed token contract to restrict transfers to.",
    )
    p.add_argument(
        "--min-timestamp",
        dest="min_timestamp",
        default=None,
        help="ISO timestamp (e.g. 2022-03-22T00:00:00Z) or YYYY-MM-DD",
    )
    p.add_argument(
        "--max-timestamp",
        dest="max_timestamp",
        default=None,
        help="ISO timestamp or YYYY-MM-DD",
    )
    p.add_argument("--limit", type=int, default=100, help="Max rows per page (default 100)")
    p.add_argument(
        "--cursor",
        default=None,
        help="Pagination cursor from a previous response, if continuing.",
    )

    p = sub.add_parser(
        "get-wallet-tx",
        help=(
            "Transaction history for an address (developer tier). NO date filter — pages back from now via --cursor."
        ),
    )
    p.add_argument("--chain", required=True)
    p.add_argument("--address", required=True, help="0x-prefixed address")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument(
        "--cursor",
        default=None,
        help="Pagination cursor; page back through older transactions.",
    )
    p.add_argument(
        "--transaction-hash",
        dest="transaction_hash",
        default=None,
        help="Filter to a single tx hash (e.g. the documented drain tx of a hack).",
    )
    p.add_argument(
        "--activity-type",
        dest="activity_type",
        default=None,
        help="Filter by activity type (e.g. 'transfer', 'swap', 'mint').",
    )

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

    # ── yfinance source — public Yahoo Finance data, no API key. ────────────
    yf_parser = sources.add_parser(
        "yfinance",
        help="Yahoo Finance market data (equities, ETFs, crypto, FX). No API key.",
    )
    yf_sub = yf_parser.add_subparsers(dest="command", required=True)

    p = yf_sub.add_parser(
        "history",
        help="OHLCV time series for a ticker over a date window.",
    )
    p.add_argument("--ticker", required=True, help="Ticker symbol (e.g. AAPL, BTC-USD, SPY).")
    p.add_argument("--start", default=None, help="ISO date e.g. 2020-01-01. Omit for max history.")
    p.add_argument("--end", default=None, help="ISO date e.g. 2024-12-31. Omit for today.")
    p.add_argument(
        "--interval",
        default="1d",
        help="Bar size: 1m, 5m, 15m, 30m, 60m, 1d (default), 5d, 1wk, 1mo. "
        "Intraday intervals are rate-limited to ~60 days back.",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="Disable split/dividend adjustment (default auto-adjusts; you almost always want adjusted).",
    )
    _add_save_to(p)

    p = yf_sub.add_parser(
        "ticker-info",
        help="Current snapshot for a ticker (price, market cap, sector, beta, P/E, ...).",
    )
    p.add_argument("--ticker", required=True)

    p = yf_sub.add_parser(
        "fundamentals",
        help="Annual financial statements (income / balance_sheet / cash_flow). ~4 years of history.",
    )
    p.add_argument("--ticker", required=True)
    p.add_argument(
        "--statement",
        choices=["income", "balance_sheet", "cash_flow"],
        default="income",
        help="Which statement to pull. Default: income.",
    )
    _add_save_to(p)

    p = yf_sub.add_parser("dividends", help="Full dividend history (ex-date + amount).")
    p.add_argument("--ticker", required=True)
    _add_save_to(p)

    p = yf_sub.add_parser(
        "search",
        help="Name-to-ticker lookup. Use when you know the company name but not the symbol.",
    )
    p.add_argument("--query", required=True, help="Company / asset name to search for.")
    p.add_argument(
        "--max-results",
        dest="max_results",
        type=int,
        default=10,
        help="Maximum number of candidates to return (default 10).",
    )

    # ── FRED source — Federal Reserve Economic Data (US macro). ─────────────
    fred_parser = sources.add_parser(
        "fred",
        help="Federal Reserve Economic Data (CPI, unemployment, rates, GDP, …). Free key.",
    )
    fred_sub = fred_parser.add_subparsers(dest="command", required=True)

    p = fred_sub.add_parser(
        "series",
        help="Pull a FRED time series. e.g. CPIAUCSL (CPI), UNRATE (unemployment), DGS10 (10y yield).",
    )
    p.add_argument("--series-id", dest="series_id", required=True, help="FRED series id, e.g. CPIAUCSL.")
    p.add_argument("--start", default=None, help="Observation start date (YYYY-MM-DD).")
    p.add_argument("--end", default=None, help="Observation end date (YYYY-MM-DD).")
    p.add_argument(
        "--frequency",
        default=None,
        help="Resample frequency: d, w, m, q, sa, a. Omit to use the series' native frequency.",
    )
    p.add_argument(
        "--units",
        default=None,
        help="Transformation: lin (raw, default), chg (level change), ch1 (yoy change), pch (% change), log.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=100000,
        help="Max observations (default 100000 = FRED's max).",
    )
    _add_save_to(p)

    p = fred_sub.add_parser(
        "series-info",
        help="Metadata for a series: title, units, frequency. Use BEFORE pulling observations to sanity-check.",
    )
    p.add_argument("--series-id", dest="series_id", required=True)

    p = fred_sub.add_parser(
        "search",
        help="Free-text search across FRED series titles + notes. Returns up to --limit hits.",
    )
    p.add_argument("--query", required=True, help="Search text, e.g. 'core CPI' or 'unemployment'.")
    p.add_argument("--limit", type=int, default=20, help="Max hits (default 20).")
    p.add_argument(
        "--order-by",
        dest="order_by",
        default="popularity",
        help="Sort order: popularity (default), observation_start, observation_end, search_rank.",
    )

    p = fred_sub.add_parser(
        "releases",
        help="List FRED releases (Consumer Price Index, Employment Situation, …).",
    )
    p.add_argument("--limit", type=int, default=100, help="Max releases returned (default 100).")

    return parser


# Per-source dispatch table. Top-level key is the data source; nested key
# is the subcommand within that source. New sources (FRED, EDGAR, …) get
# their own entries here.
_DISPATCH: dict[str, dict[str, Any]] = {
    "allium": {
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
    },
    "yfinance": {
        "history": _run_yf_history,
        "ticker-info": _run_yf_ticker_info,
        "fundamentals": _run_yf_fundamentals,
        "dividends": _run_yf_dividends,
        "search": _run_yf_search,
    },
    "fred": {
        "series": _run_fred_series,
        "series-info": _run_fred_series_info,
        "search": _run_fred_search,
        "releases": _run_fred_releases,
    },
}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    import os

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Resolve paper_id / specialist: explicit flag wins, then env var, then
    # default. Without paper_id we cannot route the query (workspace lookup
    # + audit log both need it). Public sources don't strictly need paper_id
    # for authorisation, but we still record it on the audit row so the
    # reproducibility chain isn't broken.
    args.paper_id = args.paper_id or os.environ.get("E2ER_PAPER_ID")
    args.specialist = args.specialist or os.environ.get("E2ER_SPECIALIST") or "data_analyst"
    if not args.paper_id:
        print(
            "e2er-data: paper_id missing. Pass --paper-id <uuid> or set "
            "E2ER_PAPER_ID in the environment. (Normally the runner injects this "
            "automatically; this error means the wrapper is being called outside a "
            "specialist run.)",
            file=sys.stderr,
        )
        return 2

    source_dispatch = _DISPATCH.get(args.source)
    if source_dispatch is None:
        print(f"Unknown source: {args.source!r}. Known: {sorted(_DISPATCH.keys())}", file=sys.stderr)
        return 2
    runner = source_dispatch.get(args.command)
    if runner is None:
        print(
            f"Unknown {args.source} command: {args.command!r}. Known: {sorted(source_dispatch.keys())}",
            file=sys.stderr,
        )
        return 2
    try:
        result = asyncio.run(runner(args))
    except Exception as e:
        # Fatal infrastructure error (DB unavailable, no Allium key, etc.).
        # Guardrail rejections come back as a string from handler.handle()
        # — those are NOT exceptions and reach the print() below.
        print(f"e2er-data {args.source} {args.command} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
