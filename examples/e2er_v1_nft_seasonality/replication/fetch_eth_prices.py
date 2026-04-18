#!/usr/bin/env python3
"""
Fetch daily ETH/USD prices from Yahoo Finance via the internal fetcher service.
Output: eth_daily_prices.csv
"""
import json
import urllib.request
import csv
import sys
import os
from datetime import datetime

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_url(url: str) -> str:
    req = urllib.request.Request(
        "http://fetcher:8000/fetch",
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if result.get("status") == "ok":
        return result["content"]
    raise RuntimeError(result.get("error", "fetch failed"))


def fetch_eth_prices():
    """Fetch ETH/USD daily prices from Yahoo Finance."""
    # Period: 2017-11-01 to 2023-03-01 (covers full sample + buffer)
    period1 = int(datetime(2017, 11, 1).timestamp())
    period2 = int(datetime(2023, 3, 1).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v7/finance/download/ETH-USD"
        f"?period1={period1}&period2={period2}&interval=1d&events=history"
    )

    content = fetch_url(url)
    lines = content.strip().split("\n")
    reader = csv.DictReader(lines)

    rows = []
    for row in reader:
        try:
            close = float(row["Close"])
            if close > 0:
                rows.append({
                    "date": row["Date"],
                    "eth_price_usd": close,
                })
        except (ValueError, KeyError):
            continue

    # Sort and compute log returns
    rows.sort(key=lambda x: x["date"])
    import math
    for i, row in enumerate(rows):
        if i == 0:
            row["r_eth"] = ""
        else:
            row["r_eth"] = math.log(row["eth_price_usd"] / rows[i - 1]["eth_price_usd"])

    # Add month and season
    for row in rows:
        m = int(row["date"].split("-")[1])
        row["month"] = m
        row["season"] = "winter" if m <= 4 or m >= 11 else "summer"

    return rows


def main():
    print("Fetching ETH/USD prices from Yahoo Finance...")
    try:
        rows = fetch_eth_prices()
        outpath = os.path.join(OUT_DIR, "eth_daily_prices.csv")
        with open(outpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "eth_price_usd", "r_eth", "month", "season"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved {len(rows)} rows to {outpath}")
        print(f"Date range: {rows[0]['date']} to {rows[-1]['date']}")
    except Exception as e:
        print(f"ERROR fetching ETH prices: {e}")
        print("Falling back to run_04 ETH prices...")
        # Copy from run_04
        import shutil
        src = os.path.join(OUT_DIR, "..", "run_04", "eth_daily_prices.csv")
        dst = os.path.join(OUT_DIR, "eth_daily_prices.csv")
        shutil.copy2(src, dst)
        print(f"Copied from {src}")


if __name__ == "__main__":
    main()
