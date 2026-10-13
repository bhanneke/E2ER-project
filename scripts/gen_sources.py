#!/usr/bin/env python3
"""Write what the connector kit generates from the source definitions (src/modules/data/sources/).

- the README's data source table (the block between ``<!-- sources:start -->`` and ``<!-- sources:end -->``);
- ``skills/files/data/<name>.md`` for a source that has no skill file yet: a stub to edit (never overwritten).

``--check`` writes nothing and exits 1 when the README is out of date or a skill file is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.modules.data.sources import all_sources  # noqa: E402
from src.modules.data.sources.docs import readme_block, replace_block, skill_stub  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="Write nothing; exit 1 when something is out of date.")
    args = ap.parse_args(argv)
    sources = all_sources()
    problems: list[str] = []

    readme = REPO / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = replace_block(text, readme_block(sources))
    if new != text:
        if args.check:
            problems.append("README.md: the data source table is out of date")
        else:
            readme.write_text(new, encoding="utf-8")
            print("README.md: data source table updated")

    for s in sources:
        if not s.skill:
            problems.append(f"{s.name}: the definition names no skill file")
            continue
        path = REPO / "skills" / "files" / f"{s.skill}.md"
        if path.is_file():
            continue
        if args.check:
            problems.append(f"{s.name}: {path.relative_to(REPO)} is missing")
        else:
            path.write_text(skill_stub(s), encoding="utf-8")
            print(f"{path.relative_to(REPO)}: stub written; edit it (the data architect and the data analyst read it)")

    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems and args.check else 0


if __name__ == "__main__":
    sys.exit(main())
