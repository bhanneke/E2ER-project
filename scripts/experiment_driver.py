#!/usr/bin/env python
"""Governance experiment driver (WS-F) — CLI wrapper.

Runs the same RQ under each governance regime (off / contracts / full) × N
repeats and harvests fabrication metrics into results.csv + summary.md. The
logic lives in the importable, tested `src.core.experiment`; this is only the
YAML-config front door (kept out of the shipped package — it is a research
instrument, not a product feature).

    python scripts/experiment_driver.py experiments/governance_pilot.yaml [--out DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.experiment import load_config, run_from_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the governance experiment from a YAML config.")
    ap.add_argument("config", help="Path to an experiments/<name>.yaml config.")
    ap.add_argument("--out", default=None, help="Output dir (default: experiments/<name>/).")
    ap.add_argument("--monitor-seconds", type=float, default=3600.0, help="Max time to poll each paper.")
    args = ap.parse_args()

    config = load_config(args.config)
    out = args.out or f"experiments/{config.name}"
    rows = run_from_config(config, out, monitor_seconds=args.monitor_seconds)
    completed = sum(r["completed"] for r in rows)
    print(f"experiment '{config.name}': {len(rows)} runs, {completed} completed → {out}/results.csv + summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
