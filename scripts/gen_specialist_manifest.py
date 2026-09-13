#!/usr/bin/env python3
"""Generate ``docs/SPECIALISTS.md`` — every specialist, its skills, its outputs.

There was no single place to see which specialists exist, which skill files each
is given, and which shipped skills nothing loads. That last group is the reason
this exists: a skill on disk that no specialist references is either dead weight
or a wiring bug, and finding one meant reading the registry by hand.

Generated from ``src/core/specialists/registry.py`` rather than written, on the
same principle as ``gen_pipeline_figure.py``: rename a specialist or add a skill
and this file follows on the next run. ``tests/test_specialist_manifest.py``
fails when it drifts.

    python scripts/gen_specialist_manifest.py          # rewrite the manifest
    python scripts/gen_specialist_manifest.py --check  # exit 1 if out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.core.specialists.registry import (  # noqa: E402
    SPECIALIST_ARTIFACTS,
    SPECIALIST_OPTIONAL_SIDECARS,
    SPECIALIST_SIDECAR_ARTIFACTS,
    SPECIALIST_SKILLS,
)

OUT = REPO / "docs" / "SPECIALISTS.md"


def _skill_root() -> Path:
    for candidate in (REPO / "src" / "skills" / "files", REPO / "skills" / "files"):
        if candidate.is_dir():
            return candidate
    raise SystemExit("no skills/files directory found")


def build() -> str:
    root = _skill_root()
    on_disk = sorted(p.relative_to(root).with_suffix("").as_posix() for p in root.rglob("*.md"))

    used: set[str] = set()
    for skills in SPECIALIST_SKILLS.values():
        used.update(skills)

    names = sorted(set(SPECIALIST_ARTIFACTS) | set(SPECIALIST_SKILLS))
    unused = [s for s in on_disk if s not in used]
    missing = sorted(s for s in used if s not in on_disk)

    # Which specialists load each skill — the reverse index is what you want
    # when deciding whether editing a skill file is safe.
    users: dict[str, list[str]] = {}
    for name in names:
        for skill in SPECIALIST_SKILLS.get(name, []):
            users.setdefault(skill, []).append(name)

    L: list[str] = []
    L.append("# Specialists and skills")
    L.append("")
    L.append("**Generated — do not edit.** `python scripts/gen_specialist_manifest.py`")
    L.append("")
    L.append("Every specialist the strategist can dispatch, the skill files it is given, and")
    L.append("the artifacts it must produce. A specialist that does not write its declared")
    L.append("artifact fails its contract and is retried with the violation fed back.")
    L.append("")
    L.append(f"- **{len(names)}** specialists")
    L.append(f"- **{len(on_disk)}** skill files on disk")
    L.append(f"- **{len(used)}** referenced by at least one specialist")
    L.append(f"- **{len(unused)}** never referenced")
    if missing:
        L.append(f"- **{len(missing)}** referenced but missing from disk")
    L.append("")

    if missing:
        L.append("## Referenced but missing")
        L.append("")
        L.append("A specialist asks for these and they are not on disk. The loader will not")
        L.append("find them, so the instruction silently never reaches the model.")
        L.append("")
        for s in missing:
            L.append(f"- `{s}` — wanted by {', '.join(f'`{u}`' for u in users.get(s, []))}")
        L.append("")

    L.append("## Shipped but never loaded")
    L.append("")
    L.append("These skill files are packaged and no specialist references them. Each is")
    L.append("either a capability that was written and never wired up, or dead weight.")
    L.append("`econometrics/rdd` and `econometrics/time-series` are the striking ones: the")
    L.append("methodology guidance exists, and no specialist is given it.")
    L.append("")
    for s in unused:
        L.append(f"- `{s}`")
    L.append("")

    L.append("## Specialists")
    L.append("")
    for name in names:
        artifact = SPECIALIST_ARTIFACTS.get(name, "")
        sidecars = list(SPECIALIST_SIDECAR_ARTIFACTS.get(name, []))
        optional = set(SPECIALIST_OPTIONAL_SIDECARS.get(name, frozenset()))
        skills = SPECIALIST_SKILLS.get(name, [])

        L.append(f"### `{name}`")
        L.append("")
        L.append(f"- **Writes:** `{artifact}`" if artifact else "- **Writes:** _(no declared artifact)_")
        if sidecars:
            rendered = ", ".join(f"`{s}`" + (" _(optional)_" if s in optional else "") for s in sidecars)
            L.append(f"- **Sidecars:** {rendered}")
        if skills:
            L.append(f"- **Skills ({len(skills)}):** " + ", ".join(f"`{s}`" for s in skills))
        else:
            L.append("- **Skills:** _(none — runs on the base prompt alone)_")
        L.append("")

    L.append("## Skill → specialists")
    L.append("")
    L.append("The reverse index: who is affected if you edit a skill file.")
    L.append("")
    L.append("| Skill | Loaded by |")
    L.append("|---|---|")
    for skill in sorted(used):
        L.append(f"| `{skill}` | {', '.join(f'`{u}`' for u in sorted(users.get(skill, [])))} |")
    L.append("")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if the manifest is out of date")
    args = ap.parse_args()

    content = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != content:
            print(f"{OUT.relative_to(REPO)} is out of date — run scripts/gen_specialist_manifest.py", file=sys.stderr)
            return 1
        print("manifest is current")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
