#!/usr/bin/env python3
"""Live smoke check — exercises real provider paths against real services.

Dev harness equivalent to `e2er doctor` minus the backend / skills / DB
preflight. Same engine; this entry point is for the developer making sure
providers stay healthy across changes. End users should prefer
``e2er doctor``.

Run:
    python scripts/live_check.py            # human-readable
    python scripts/live_check.py --json     # machine-readable
Exit code: 0 if no failures.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Make ``src`` importable no matter where this is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.doctor import FAIL, render_human, run_provider_checks  # noqa: E402


async def _amain() -> int:
    checks = await run_provider_checks(get_settings())
    report = {"checks": [asdict(c) for c in checks]}
    Path("live_check_report.json").write_text(json.dumps(report, indent=2))

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print(render_human(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_amain()))
