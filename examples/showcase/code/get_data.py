"""Reload the Yahoo Finance extracts this study read, with e2er-data.

Added to the study on 2026-10-05, after the run, so that the study can be run
again from its folder. It is not part of what the run's specialists wrote.

Yahoo's terms allow personal use of its data only, so the study does not ship
the extracts. This script asks Yahoo for the same tickers and dates with the
command the data analyst used on 2026-09-11 (data_dictionary.json, step
build_01):

    e2er-data yfinance history --ticker <ticker> --start 2020-12-01 --end 2026-09-11 \
        --interval 1d --save-to <file>

Yahoo revises its history, so a file loaded today can differ from the one the
study read. reproduce.json records the SHA-256 of every original extract, and
`e2er reproduce` says which reloaded files are identical and which differ.

Run it from the folder that holds data/ (`e2er reproduce` does this for you).
It writes the files to data/ and records each load in data_sources.json.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

START, END = "2020-12-01", "2026-09-11"

# file in data/ -> Yahoo ticker, as the study named them
EXTRACTS = {
    **{f"px_{c}_USD.csv": f"{c}-USD" for c in (
        "BTC", "ETH", "SOL", "XRP", "LTC", "BNB", "ADA", "DOGE", "BCH", "LINK", "AVAX", "DOT", "XLM")},
    **{f"px_{t}.csv": t for t in ("SPY", "QQQ", "IWM", "ARKK", "XLK", "ACWX", "GLD", "SLV")},
    "px_GSPC.csv": "^GSPC",
    "px_VIX.csv": "^VIX",
    "px_MOVE.csv": "^MOVE",
    "px_TNX.csv": "^TNX",
    "px_DXY.csv": "DX-Y.NYB",
    **{f"etf_{t}.csv": t for t in (
        "IBIT", "FBTC", "GBTC", "ARKB", "BITB", "BTCO", "EZBC", "BRRR", "HODL", "BTCW", "BITO", "DEFI")},
}


def e2er_data() -> str:
    found = os.environ.get("E2ER_DATA") or shutil.which("e2er-data")
    if not found:
        sys.exit("e2er-data was not found. Install e2er (pip install e2er), or run `e2er reproduce` on this folder.")
    return found


def main() -> int:
    here = Path.cwd().resolve()
    data = here / "data"
    data.mkdir(exist_ok=True)
    env = {**os.environ, "E2ER_WORKSPACE_ROOT": str(here.parent)}
    failed, empty = [], []
    for name, ticker in EXTRACTS.items():
        target = data / name
        if target.is_symlink() or target.exists():
            target.unlink()  # e2er-data never overwrites a file; this one is replaced on purpose
        cmd = [e2er_data(), "--paper-id", here.name, "--specialist", "researcher", "yfinance", "history",
               "--ticker", ticker, "--start", START, "--end", END, "--interval", "1d", "--save-to", name]
        out = subprocess.run(cmd, env=env, capture_output=True, text=True)
        try:
            result = json.loads(out.stdout)
        except ValueError:
            result = {"error": (out.stderr or out.stdout).strip()[-300:]}
        if result.get("save_skipped") and not result.get("error"):
            # Yahoo answered without rows (a delisted fund): the study's code copes with a missing file.
            empty.append(f"{name} ({ticker})")
            continue
        if out.returncode != 0 or result.get("error") or not target.is_file():
            failed.append(f"{name} ({ticker}): {result.get('error') or result.get('save_error') or 'no file written'}")
            continue
        print(f"{name:<22} {ticker:<10} {result.get('saved_rows')} rows")
    if empty:
        print("Yahoo returned no rows for:", *empty, sep="\n  ")
    if failed:
        print("Could not load:", *failed, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
