"""Compare Allium's published OpenAPI specs with the fixtures in tests/data/fixtures/.

Used by the nightly schema-drift workflow. Three outcomes, written to
$GITHUB_OUTPUT (or printed):

  status=match        every spec equals its fixture
  status=drift        a spec was fetched and differs; ``fingerprint`` is a
                      SHA-256 of the drifted specs, so the workflow comments on
                      the drift issue only when the drift itself changed
  status=unavailable  a spec could not be fetched as JSON. Since mid-2026
                      docs.allium.so answers with a redirect to its login page,
                      which the old check counted as drift and reported every
                      night. That is not a change in the API, so it opens no
                      issue and adds no comment.

Unified diffs of drifted specs go to --diff-dir.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

ENDPOINTS = ("tokens-api", "wallet-api", "balances-api", "prices-api")
URL = "https://docs.allium.so/_openapi/{}.json"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "e2er-schema-drift"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URL
        return bytes(resp.read())


def compare(fixtures: Path, fetch: Callable[[str], bytes] = _fetch) -> dict:
    """{"status", "drifted", "unavailable", "fingerprint", "diffs"} for the four endpoints."""
    drifted: list[str] = []
    unavailable: list[str] = []
    diffs: dict[str, str] = {}
    digest = hashlib.sha256()
    for name in ENDPOINTS:
        cached = json.loads((fixtures / f"{name}.json").read_text(encoding="utf-8"))
        try:
            latest = json.loads(fetch(URL.format(name)))
        except Exception as e:  # noqa: BLE001 - network error, login page, not JSON: all the same here
            unavailable.append(f"{name} ({type(e).__name__})")
            continue
        if not isinstance(latest, dict) or "paths" not in latest:
            unavailable.append(f"{name} (not an OpenAPI document)")
            continue
        if latest != cached:
            drifted.append(name)
            a = json.dumps(cached, indent=2, sort_keys=True).splitlines()
            b = json.dumps(latest, indent=2, sort_keys=True).splitlines()
            diffs[name] = "\n".join(
                difflib.unified_diff(a, b, f"fixtures/{name}.json", f"live/{name}.json", lineterm="")
            )
            digest.update(name.encode() + b"\0" + json.dumps(latest, sort_keys=True).encode())
    status = "drift" if drifted else ("unavailable" if unavailable else "match")
    return {
        "status": status,
        "drifted": drifted,
        "unavailable": unavailable,
        "fingerprint": digest.hexdigest()[:16] if drifted else "",
        "diffs": diffs,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixtures", default="tests/data/fixtures")
    ap.add_argument("--diff-dir", default=None)
    args = ap.parse_args(argv)
    result = compare(Path(args.fixtures))
    if args.diff_dir and result["diffs"]:
        out = Path(args.diff_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, text in result["diffs"].items():
            (out / f"{name}.diff").write_text(text + "\n", encoding="utf-8")
    lines = [
        f"status={result['status']}",
        f"fingerprint={result['fingerprint']}",
        f"drifted={' '.join(result['drifted'])}",
        f"unavailable={'; '.join(result['unavailable'])}",
    ]
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
