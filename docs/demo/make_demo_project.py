"""Build the throwaway project the demo GIFs walk through.

Everything in it is real: prices pulled through the same yfinance library the
pipeline uses, and a bibliography of genuine published references taken from
this repo's own examples. Nothing is mocked — a demo for a project whose claim
is that outputs trace back to something cannot itself be staged.

    python docs/demo/make_demo_project.py [destination]

Destination defaults to /tmp/e2er-demo and is rebuilt from scratch each time.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BIB_SRC = REPO / "examples" / "e2er_v1_bitcoin_institutionalization" / "references.bib"

TICKERS = {"SPY": "spy_daily.csv", "BTC-USD": "btc_daily.csv"}


def main() -> int:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/e2er-demo")
    if dest.exists():
        shutil.rmtree(dest)
    data, lit = dest / "data", dest / "literature"
    data.mkdir(parents=True)
    lit.mkdir(parents=True)

    try:
        import yfinance as yf
    except ImportError:
        print("yfinance is required: pip install -e '.[dev]'", file=sys.stderr)
        return 1

    for ticker, fname in TICKERS.items():
        df = yf.Ticker(ticker).history(period="2y", interval="1d")
        if df.empty:
            print(f"no rows returned for {ticker} — is the network up?", file=sys.stderr)
            return 1
        df = df.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df.to_csv(data / fname, index=False)
        print(f"  data/{fname}: {len(df)} rows")

    shutil.copy(BIB_SRC, lit / "references.bib")
    entries = sum(
        1
        for line in (lit / "references.bib").read_text(encoding="utf-8", errors="replace").splitlines()
        if line.lstrip().startswith("@")
    )
    print(f"  literature/references.bib: {entries} entries")

    # Relative paths keep the recorded .env readable on screen.
    (dest / ".env").write_text(
        "LLM_BACKEND=claude_code\nLOCAL_DATA_DIR=./data\nLITERATURE_BIBTEX_FILE=./literature/references.bib\n",
        encoding="utf-8",
    )
    print(f"built {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
