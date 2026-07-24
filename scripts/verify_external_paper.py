#!/usr/bin/env python
"""Cross-pipeline citation audit (WS-G) — CLI wrapper.

Run E2ER's citation-integrity chain over papers from OTHER pipelines (e.g. the
public papers from Project APE) to report how many of their references resolve
to real works. Offered as infrastructure, not a gotcha — SHARE the results
with the pipeline's authors before any external / submission use.

Each PAPER argument is either a directory containing a `.bib` (plus an optional
`.tex`/`.txt`) or a lone `.bib` file:

    python scripts/verify_external_paper.py ape_paper1/ ape_paper2/ [--out DIR]
    python scripts/verify_external_paper.py refs.bib
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.external_verify import audit_papers, render_summary  # noqa: E402


def _resolve_inputs(path_str: str) -> tuple[str, str, str | None] | None:
    """(name, bib_path, text_path|None) from a dir or a .bib file."""
    p = Path(path_str)
    if p.is_dir():
        bibs = sorted(p.glob("*.bib"))
        if not bibs:
            print(f"  ! {p}: no .bib found, skipping", file=sys.stderr)
            return None
        texts = sorted(p.glob("*.tex")) + sorted(p.glob("*.txt"))
        return (p.name, str(bibs[0]), str(texts[0]) if texts else None)
    if p.is_file() and p.suffix == ".bib":
        return (p.stem, str(p), None)
    print(f"  ! {p}: not a directory or .bib file, skipping", file=sys.stderr)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit external papers' citations against the registries.")
    ap.add_argument("papers", nargs="+", help="Paper dirs (with a .bib) or .bib files.")
    ap.add_argument("--out", default="external_audit", help="Output dir (default: ./external_audit/).")
    args = ap.parse_args()

    resolved = [r for r in (_resolve_inputs(x) for x in args.papers) if r]
    if not resolved:
        print("verify_external_paper: no usable inputs (need a dir with a .bib, or a .bib file).", file=sys.stderr)
        return 2

    out = Path(args.out)
    aggregate = asyncio.run(audit_papers(resolved, out))
    print(render_summary(aggregate))
    print(f"\nWrote per-paper reports + summary.md + aggregate.json → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
