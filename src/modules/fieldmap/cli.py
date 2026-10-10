"""``e2er-fieldmap``: the field map's steps from a specialist's shell (or a researcher's).

Same functions the field-map template runs as checks (``workflow.py``), so a
specialist that looks at counts or papers sees exactly what the run will
compute. The workspace is the directory the command is called from (the
wrapper passes it as ``E2ER_WORKSPACE``), or ``--workspace``.

    e2er-fieldmap count --query '"main path analysis" OR "main path"' --from 1989 --to 2026
    e2er-fieldmap sources "Scientometrics"
    e2er-fieldmap boundary              # retrieve every boundary of field_boundary.json
    e2er-fieldmap network               # completeness report of the main boundary
    e2er-fieldmap mainpath --key-routes 10
    e2er-fieldmap robustness
    e2er-fieldmap papers [--all] [--abstracts]
    e2er-fieldmap map                   # needs field_lanes.json
    e2er-fieldmap export                # map in one lane, exports, reading list, results
    e2er-fieldmap all                   # boundary, network, mainpath, robustness

stdout is what the reader sees; the exit code is 0 when a step passed, 1 when
it did not (its reasons are printed), 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import workflow as wf
from .openalex import BoundaryError, Client, count, find_sources, normalise_boundary, openalex_filter


def _workspace(arg: str | None) -> Path:
    return Path(arg or os.environ.get("E2ER_WORKSPACE") or Path.cwd()).resolve()


def _print_verdict(name: str, v: wf.Verdict) -> int:
    if v.passed:
        print(f"{name}: passed. " + ", ".join(f"{k}={val}" for k, val in v.stats.items()))
        for n in v.notes:
            print(f"  note: {n}")
        return 0
    print(f"{name}: did not pass.")
    for r in v.reasons:
        print(f"  - {r}")
    for n in v.notes:
        print(f"  note: {n}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="e2er-fieldmap", description="Main path analysis of a research field (OpenAlex).")
    ap.add_argument("--workspace", help="the study's folder (default: the current folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("count", help="how many papers a boundary selects (one OpenAlex request)")
    c.add_argument("--query", default="")
    c.add_argument("--search-in", default="title_abstract", choices=["title_abstract", "title", "all"])
    c.add_argument("--sources", default="", help="comma-separated OpenAlex source ids (S...)")
    c.add_argument("--from", dest="from_year", type=int)
    c.add_argument("--to", dest="to_year", type=int)
    c.add_argument("--types", default="article,review")

    s = sub.add_parser("sources", help="find a journal's OpenAlex source id (one request)")
    s.add_argument("name")

    b = sub.add_parser("boundary", help="retrieve the boundaries of field_boundary.json")
    b.add_argument("--name", help="only this boundary")
    b.add_argument("--max-papers", type=int, default=5000)
    b.add_argument("--max-requests", type=int, default=300)

    n = sub.add_parser("network", help="the main boundary's network and its completeness report")
    n.add_argument("--max-isolated-share", type=float, default=0.5)
    n.add_argument("--max-missing-refs-share", type=float, default=0.4)
    n.add_argument("--min-papers", type=int, default=100)

    m = sub.add_parser("mainpath", help="SPC, main paths and key routes of the main boundary")
    m.add_argument("--key-routes", type=int, default=10)

    r = sub.add_parser("robustness", help="the main path of every boundary, compared")
    r.add_argument("--key-routes", type=int)

    p = sub.add_parser("papers", help="list the mapped papers (or --all of the main boundary) as JSON lines")
    p.add_argument("--all", action="store_true")
    p.add_argument("--abstracts", action="store_true")
    p.add_argument("--limit", type=int, default=0)

    sub.add_parser("map", help="map, reading list, exports and results (needs field_lanes.json)")
    sub.add_parser("export", help="as map, but field_lanes.json is optional")
    a = sub.add_parser("all", help="boundary, network, mainpath and robustness in one go")
    a.add_argument("--key-routes", type=int, default=10)
    a.add_argument("--max-requests", type=int, default=300)

    args = ap.parse_args(argv)
    ws = _workspace(args.workspace)
    try:
        return _run(args, ws)
    except BoundaryError as e:
        print(f"e2er-fieldmap: {e}")
        return 1


def _run(args: Any, ws: Path) -> int:
    if args.cmd == "count":
        b = normalise_boundary(
            {
                "name": "count",
                "query": args.query,
                "search_in": args.search_in,
                "sources": [x for x in args.sources.split(",") if x.strip()],
                "from_year": args.from_year,
                "to_year": args.to_year,
                "types": [t for t in args.types.split(",") if t.strip()],
            }
        )
        client = Client.from_settings(ws / wf.DIR / "cache", max_requests=2)
        print(json.dumps({"papers": count(client, b), "filter": openalex_filter(b)}, ensure_ascii=False))
        return 0
    if args.cmd == "sources":
        client = Client.from_settings(ws / wf.DIR / "cache", max_requests=2)
        for row in find_sources(client, args.name):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.cmd == "boundary":
        return _print_verdict(
            "boundary",
            wf.retrieve_boundaries(ws, max_papers=args.max_papers, max_requests=args.max_requests, only=args.name),
        )
    if args.cmd == "network":
        return _print_verdict(
            "network",
            wf.network_step(
                ws,
                max_isolated_share=args.max_isolated_share,
                max_missing_refs_share=args.max_missing_refs_share,
                min_papers=args.min_papers,
            ),
        )
    if args.cmd == "mainpath":
        return _print_verdict("mainpath", wf.mainpath_step(ws, key_routes=args.key_routes))
    if args.cmd == "robustness":
        return _print_verdict("robustness", wf.robustness_step(ws, key_routes=args.key_routes))
    if args.cmd == "papers":
        rows = wf.papers_listing(ws, which="all" if args.all else "mapped", abstracts=args.abstracts)
        for row in rows[: args.limit or None]:
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.cmd == "map":
        return _print_verdict("map", wf.map_step(ws))
    if args.cmd == "export":
        return _print_verdict("export", wf.map_step(ws, require_lanes=False))
    if args.cmd == "all":
        steps = [
            ("boundary", lambda: wf.retrieve_boundaries(ws, max_requests=args.max_requests)),
            ("network", lambda: wf.network_step(ws)),
            ("mainpath", lambda: wf.mainpath_step(ws, key_routes=args.key_routes)),
            ("robustness", lambda: wf.robustness_step(ws, key_routes=args.key_routes)),
        ]
        for name, fn in steps:
            code = _print_verdict(name, fn())
            if code:
                return code
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
