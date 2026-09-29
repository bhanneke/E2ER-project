"""Check an installed e2er (from a wheel) can start a study: templates and skills ship.

Run with the Python of a fresh virtualenv that has only the wheel installed,
from a directory outside the repository (so no ./pipelines is found):

    python check_installed_package.py <repo root>

The repository root is used only to count the skill files the wheel must
contain. Exits 1 with the list of problems.
"""

from __future__ import annotations

import sys
from pathlib import Path

TEMPLATES = ("empirical", "empirical-preregistered", "event-study-finance", "replication")


def main(repo: Path) -> int:
    import src
    from src.core.pipeline.spec import find_spec
    from src.core.specialists.registry import SPECIALIST_SKILLS
    from src.skills.loader import skill_exists

    problems: list[str] = []
    installed = Path(src.__file__).resolve().parent
    if repo.resolve() in installed.parents:
        problems.append(f"src is imported from the checkout ({installed}), not from the installed wheel")
    if (Path.cwd() / "pipelines").exists():
        problems.append(f"run from a directory without ./pipelines (cwd {Path.cwd()})")

    for name in TEMPLATES:
        try:
            spec = find_spec(name)
        except Exception as exc:  # noqa: BLE001 — report every failure
            problems.append(f"template {name!r} not found: {str(exc).splitlines()[0]}")
            continue
        print(f"ok  template {name}: {len(spec.steps)} steps")

    shipped = sorted(
        p.relative_to(installed.parent / "skills" / "files").as_posix()
        for p in (installed.parent / "skills" / "files").rglob("*.md")
    )
    expected = sorted(
        p.relative_to(repo / "skills" / "files").as_posix() for p in (repo / "skills" / "files").rglob("*.md")
    )
    missing = sorted(set(expected) - set(shipped))
    if missing:
        problems.append(f"{len(missing)} skill files missing from the package, e.g. {', '.join(missing[:5])}")
    else:
        print(f"ok  skills: {len(shipped)} skill files")
    unresolved = sorted({s for skills in SPECIALIST_SKILLS.values() for s in skills if not skill_exists(s)})
    if unresolved:
        problems.append(f"skills referenced by specialists but not installed: {', '.join(unresolved[:8])}")

    for p in problems:
        print(f"FAIL {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
