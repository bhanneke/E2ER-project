"""Yahoo Finance through yfinance: market data, no key; personal-use terms (data not passed on).

A connector written before the kit: its fetching (yfinance_provider.py), its
``e2er-data`` handlers (cli.py) and its ``fetch_data`` fetcher (providers.py)
are its own. The definition below is the one place for everything else: the
arguments of its subcommands, the terms, the labels, the planning entry, the
doctor check and how get_data.py repeats a load.
"""

from __future__ import annotations

from typing import Any

from .base import Arg, Doctor, Operation, Restricted, Source
from .legacy import cli_handler as _cli
from .legacy import doctor_check


def _fetcher(settings: Any) -> Any:
    from ..providers import YFinanceFetcher

    return YFinanceFetcher()


def reload(entry: dict[str, Any]) -> tuple[list[str], str] | None:
    """The e2er-data command that repeats a Yahoo load (without its target), and a note; None if unknown."""
    raw = entry.get("request")
    req: dict[str, Any] = raw if isinstance(raw, dict) else {}
    ticker = req.get("ticker")
    if not ticker:
        link = str(entry.get("link") or "")
        ticker = link.rstrip("/").rsplit("/", 1)[-1] if "/quote/" in link else None
    if not ticker:
        return None
    command = req.get("command") or ("dividends" if "dividends" in str(entry.get("series") or "") else "history")
    if command == "fundamentals":
        statement = str(req.get("statement") or "income")
        return ["yfinance", "fundamentals", "--ticker", ticker, "--statement", statement], ""
    if command == "dividends":
        return ["yfinance", "dividends", "--ticker", ticker], ""
    args = ["yfinance", "history", "--ticker", ticker, "--interval", str(req.get("interval") or "1d")]
    note = ""
    if req:
        for key in ("start", "end"):
            if req.get(key):
                args += [f"--{key}", str(req[key])]
        if req.get("adjusted") is False:
            args.append("--raw")
    else:
        note = "dates not recorded"
    return args, note


TERMS_SUMMARY = (
    "Yahoo's terms of use apply. The yfinance project notes that Yahoo's finance data are intended "
    "for personal use only; yfinance is not affiliated with Yahoo."
)

SOURCE = Source(
    name="yfinance",
    label="Yahoo Finance",
    dataset="Yahoo Finance (through yfinance)",
    website="https://finance.yahoo.com",
    terms_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    terms_summary=TERMS_SUMMARY,
    licence=(
        "Yahoo terms of service (https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html). The data are "
        "read through yfinance, which is not affiliated with Yahoo; its documentation refers users to "
        "Yahoo's terms for their rights to use the data and notes that the data are intended for personal use only."
    ),
    # Each load names its ticker and date (load_record.yfinance_load); there is no citation of the source as such.
    citation="",
    citation_by="e2er",
    use=(
        "Equity / ETF / FX / crypto market data — OHLCV prices, company "
        "fundamentals, dividends. Good for asset returns and firm-level variables."
    ),
    coverage="Equities, ETFs, crypto, FX, indices",
    help="Yahoo Finance market data (equities, ETFs, crypto, FX). No API key.",
    operations=(
        Operation(
            "history",
            "OHLCV time series for a ticker over a date window.",
            args=(
                Arg("ticker", "Ticker symbol (e.g. AAPL, BTC-USD, SPY).", required=True),
                Arg("start", "ISO date e.g. 2020-01-01. Omit for max history."),
                Arg("end", "ISO date e.g. 2024-12-31. Omit for today."),
                Arg(
                    "interval",
                    "Bar size: 1m, 5m, 15m, 30m, 60m, 1d (default), 5d, 1wk, 1mo. "
                    "Intraday intervals are rate-limited to ~60 days back.",
                    default="1d",
                ),
                Arg(
                    "raw",
                    "Disable split/dividend adjustment (default auto-adjusts; you almost always want adjusted).",
                    type="flag",
                ),
            ),
            run=_cli("_run_yf_history"),
        ),
        Operation(
            "ticker-info",
            "Current snapshot for a ticker (price, market cap, sector, beta, P/E, ...).",
            args=(Arg("ticker", "", required=True),),
            loads=False,
            run=_cli("_run_yf_ticker_info"),
        ),
        Operation(
            "fundamentals",
            "Annual financial statements (income / balance_sheet / cash_flow). ~4 years of history.",
            args=(
                Arg("ticker", "", required=True),
                Arg(
                    "statement",
                    "Which statement to pull. Default: income.",
                    default="income",
                    choices=("income", "balance_sheet", "cash_flow"),
                ),
            ),
            run=_cli("_run_yf_fundamentals"),
        ),
        Operation(
            "dividends",
            "Full dividend history (ex-date + amount).",
            args=(Arg("ticker", "", required=True),),
            run=_cli("_run_yf_dividends"),
        ),
        Operation(
            "search",
            "Name-to-ticker lookup. Use when you know the company name but not the symbol.",
            args=(
                Arg("query", "Company / asset name to search for.", required=True),
                Arg("max-results", "Maximum number of candidates to return (default 10).", type=int, default=10),
            ),
            loads=False,
            run=_cli("_run_yf_search"),
        ),
    ),
    redistribution=False,
    restricted=Restricted(
        short="Yahoo Finance",
        name="Yahoo Finance",
        # Verbatim from the load record's terms summary, one sentence per line.
        plain=tuple(s.strip() if s.strip().endswith(".") else s.strip() + "." for s in TERMS_SUMMARY.split(". ")),
        zenodo_licence=None,
        no_zenodo_why=(
            "Yahoo's terms allow personal use only, and a Zenodo deposit republishes the data for anyone to reuse"
        ),
        limit="allow personal use only",
        limit_finish="allow personal use only",
        confirm="although Yahoo's terms allow personal use only",
        warn="Yahoo's terms allow personal use only.",
        article="",
        cite_required=False,
    ),
    aliases=("yahoo", "yahoo_finance"),
    skill="data/yfinance",
    doctor=Doctor("data.yfinance.history", run=doctor_check("yfinance_check")),
    reload=reload,
    fetcher=_fetcher,
)
