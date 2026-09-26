"""``e2er skills`` — install skill packs from the RISE catalogue.

    e2er skills list                       packs in the catalogue
    e2er skills list --pack theorist-toolbox   skills inside one pack
    e2er skills install theorist-toolbox   fetch it into ~/.e2er/skills/
    e2er skills installed                  what is installed here
    e2er skills remove theorist-toolbox

Not to be confused with `e2er install-skills`, which extracts E2ER's own
bundled skills to ~/.claude/skills for the CLI backends. This installs
*other people's* packs from the catalogue.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .logging_config import get_logger
from .modules import skills_catalogue as cat

logger = get_logger(__name__)


def _out(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _cmd_list(args: argparse.Namespace) -> int:
    packs = cat.read_catalogue(args.catalogue)

    if args.pack:
        pack = next((p for p in packs if p.slug == args.pack), None)
        if pack is None:
            print(f"No pack named {args.pack!r}.", file=sys.stderr)
            return 1
        if args.json:
            _out(pack.to_dict(), as_json=True)
            return 0
        print(f"{pack.name}  ({pack.license})")
        print(f"  {pack.source_url}")
        if pack.maintainers:
            print(f"  by {', '.join(pack.maintainers)}")
        print()
        for s in pack.skills:
            print(f"  {s.slug:<28} {s.description[:70]}")
        print(f"\n{len(pack.skills)} skill(s).")
        return 0

    if args.json:
        _out([p.to_dict() | {"skills": len(p.skills)} for p in packs], as_json=True)
        return 0

    total = 0
    print(f"{'PACK':<26} {'SKILLS':>6}  {'LICENCE':<22} BUNDLEABLE")
    for p in packs:
        total += len(p.skills)
        # "bundleable" answers the question that made this an installer rather
        # than a copy: could E2ER ship this? For most of the catalogue, no.
        print(f"{p.slug:<26} {len(p.skills):>6}  {(p.license or '?')[:22]:<22} {'yes' if p.redistributable else 'no'}")
    print(f"\n{len(packs)} pack(s), {total} skills. Install one with: e2er skills install <pack>")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    pack = cat.find_pack(args.pack, args.catalogue)

    if not args.json:
        print(f"{pack.name} — {len(pack.skills)} skill(s), {pack.license or 'no licence declared'}")
        print(f"  from {pack.source_url}")
        if pack.maintainers:
            print(f"  by {', '.join(pack.maintainers)}")
        print()

    def show(event: str, slug: str, detail: str) -> None:
        if args.json:
            return
        print(f"  {'✓' if event == 'ok' else '✗'}  {slug:<28} {detail[:60]}")

    report = asyncio.run(cat.install_pack(pack, on_event=None if args.json else show))

    _out(report, as_json=args.json)
    if not args.json:
        print(f"\n{report['installed']} installed, {report['failed']} failed → {report['path']}")
        if report["failed"]:
            print("Failures are normal for private or relocated repositories.")
    return 0 if report["installed"] else 1


def _cmd_installed(args: argparse.Namespace) -> int:
    packs = cat.installed_packs()

    if args.json:
        _out(packs, as_json=True)
        return 0
    if not packs:
        print("Nothing installed. Try: e2er skills list")
        return 0
    for p in packs:
        print(f"{p['slug']:<26} {p['files']:>4} files  {p['license'][:24]}")
    print(f"\n{len(packs)} pack(s) in {cat.install_root()}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    removed = cat.remove_pack(args.pack)
    print(f"{'Removed' if removed else 'Not installed'}: {args.pack}")
    return 0 if removed else 1


def _cmd_sync(args) -> int:
    """Push E2ER's own skills out to a headless CLI backend.

    The opposite direction from `install`, which pulls other people's packs in.
    They used to be `e2er skills install` and `e2er install-skills`, which is a
    distinction nobody can hold in their head.
    """
    from .cli_install_skills import install_skills

    return install_skills(backend=args.backend, force=args.force)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="e2er skills",
        description="Skills, in both directions: `install` pulls other projects' "
        "packs in from the RISE catalogue; `sync` pushes e2er's own skills out to "
        "a headless CLI backend so the `claude`/`codex`/`gemini` process can see them.",
    )
    p.add_argument("--catalogue", default=None, help="Path to a RISE checkout (default: RISE_PATH)")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="action", required=True)

    ls = sub.add_parser("list", help="Packs in the catalogue")
    ls.add_argument("--pack", default=None, help="Show the skills inside one pack")
    ls.set_defaults(func=_cmd_list)

    inst = sub.add_parser("install", help="Fetch a pack's skills from its source")
    inst.add_argument("pack")
    inst.set_defaults(func=_cmd_install)

    have = sub.add_parser("installed", help="Packs installed on this machine")
    have.set_defaults(func=_cmd_installed)

    rm = sub.add_parser("remove", help="Delete an installed pack")
    rm.add_argument("pack")
    rm.set_defaults(func=_cmd_remove)

    sync = sub.add_parser(
        "sync",
        help="Copy e2er's own skills to a headless CLI backend's skills dir",
    )
    sync.add_argument(
        "--backend",
        choices=["claude", "codex", "gemini", "all"],
        default="all",
        help="Which backend's skills directory to populate. Default: all installed CLIs.",
    )
    sync.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing skill files. Default: skip files that already exist.",
    )
    sync.set_defaults(func=_cmd_sync)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except cat.CatalogueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
