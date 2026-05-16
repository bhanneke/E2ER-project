#!/usr/bin/env python3
"""Pre-release audit for the dev → main cutover.

Prints a checklist of things that must be true before tagging a release.
No action is taken — this script only reads. Safe to run repeatedly.

Usage:
    python3 scripts/release_audit.py
    make release-audit            # same, via Makefile

Exit codes:
    0 — every gate passed; safe to cut release
    1 — at least one hard gate failed (version mismatch, dirty tree, etc.)
    2 — warnings only (CHANGELOG empty, TODO markers, CI yellow) — operator
        decides whether to proceed
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------- helpers ----------


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd or REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


# ---------- gates ----------


def gate_version_match() -> tuple[bool, str]:
    """pyproject.toml [project].version must match src/__init__.py __version__."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not m:
        return False, "pyproject.toml has no [project].version line"
    pyproject_version = m.group(1)

    init_path = REPO_ROOT / "src" / "__init__.py"
    if not init_path.exists():
        return False, f"src/__init__.py does not exist (looked at {init_path})"
    init_text = init_path.read_text(encoding="utf-8")
    m2 = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not m2:
        return False, "src/__init__.py has no __version__ = '...' line"
    init_version = m2.group(1)

    if pyproject_version != init_version:
        return False, (f"version mismatch — pyproject.toml={pyproject_version!r} vs src/__init__.py={init_version!r}")
    return True, f"version={pyproject_version}"


def gate_clean_tree() -> tuple[bool, str]:
    """No uncommitted changes."""
    rc, out, _ = _run(["git", "status", "--porcelain"])
    if rc != 0:
        return False, "git status failed"
    dirty = [line for line in out.splitlines() if line.strip()]
    if dirty:
        return False, f"{len(dirty)} uncommitted file(s): " + ", ".join(d[3:] for d in dirty[:5])
    return True, "tree clean"


def gate_on_main() -> tuple[bool, str]:
    """Releases should be cut from `main`, not `dev` or a feature branch.

    Warning, not hard fail — sometimes you audit from `dev` before the
    release PR merges.
    """
    rc, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = out.strip()
    if branch != "main":
        return False, f"on branch {branch!r}, not main (warning — fine for audit-from-dev)"
    return True, "on main"


def gate_changelog_has_unreleased() -> tuple[bool, str]:
    """Releasing means moving entries OUT of ## Unreleased.

    If ## Unreleased is empty, there's nothing to release.
    """
    p = REPO_ROOT / "CHANGELOG.md"
    if not p.exists():
        return False, "CHANGELOG.md missing"
    text = p.read_text(encoding="utf-8")
    # Find the Unreleased section. Accept both `## Unreleased` and
    # `## [Unreleased]` (Keep-a-Changelog style).
    m = re.search(r"^##\s+\[?Unreleased\]?\s*\n(.*?)(?=^##\s+|\Z)", text, re.M | re.S)
    if not m:
        return False, "CHANGELOG.md has no '## Unreleased' section"
    body = m.group(1).strip()
    # Strip out lane sub-headings (### Lane X) and empty bullets
    content_lines = [
        line
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("###") and not line.strip().startswith("<!--")
    ]
    if not content_lines:
        return False, "## Unreleased section is empty — nothing to release"
    return True, f"{len(content_lines)} entry/entries under ## Unreleased"


def gate_no_release_todos() -> tuple[bool, str]:
    """TODO(release) markers in source code must be resolved before tagging.

    Only scans `src/` so meta-mentions of the marker pattern in docs,
    slash commands, and this very script don't false-trip the gate.
    """
    rc, out, _ = _run(["git", "grep", "-l", "-E", "TODO\\(release\\)|FIXME\\(release\\)", "--", "src/"])
    if rc != 0 and not out.strip():
        return True, "no TODO(release) markers in src/"
    files = [line for line in out.splitlines() if line.strip()]
    if not files:
        return True, "no TODO(release) markers in src/"
    return False, f"{len(files)} file(s) in src/ have TODO(release): " + ", ".join(files[:5])


def gate_ci_green() -> tuple[bool, str]:
    """Latest CI run on current branch should be green."""
    rc, out, _ = _run(["gh", "run", "list", "-L", "1", "--json", "conclusion,workflowName,headBranch"])
    if rc != 0:
        return False, "gh CLI failed or not authenticated (warning)"
    import json

    try:
        data = json.loads(out)
    except Exception:
        return False, "gh returned non-JSON (warning)"
    if not data:
        return False, "no CI runs found (warning)"
    latest = data[0]
    if latest["conclusion"] == "success":
        return True, f"{latest['workflowName']} green on {latest['headBranch']}"
    return False, (f"{latest['workflowName']} = {latest['conclusion']} on {latest['headBranch']} (warning)")


def gate_tests_pass() -> tuple[bool, str]:
    """pytest must pass."""
    rc, out, err = _run([sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--no-header"])
    if rc != 0:
        # Last 3 lines of output usually capture the failure summary
        tail = "\n".join((out + err).strip().splitlines()[-3:])
        return False, f"pytest failed:\n  {tail}"
    last_line = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    return True, f"pytest passed — {last_line}"


# ---------- orchestrator ----------


HARD_GATES = (
    ("version match", gate_version_match),
    ("clean tree", gate_clean_tree),
    ("changelog has entries", gate_changelog_has_unreleased),
    ("no TODO(release)", gate_no_release_todos),
    ("tests pass", gate_tests_pass),
)

WARN_GATES = (
    ("on main", gate_on_main),
    ("CI green", gate_ci_green),
)


def main() -> int:
    print("Release audit\n=============\n")

    hard_failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    print("Hard gates (must pass):")
    for name, fn in HARD_GATES:
        ok, msg = fn()
        symbol = _green("✓") if ok else _red("✗")
        print(f"  {symbol} {name}: {msg}")
        if not ok:
            hard_failures.append((name, msg))

    print("\nSoft gates (warnings only):")
    for name, fn in WARN_GATES:
        ok, msg = fn()
        symbol = _green("✓") if ok else _yellow("⚠")
        print(f"  {symbol} {name}: {msg}")
        if not ok:
            warnings.append((name, msg))

    print()
    if hard_failures:
        print(_red(f"FAIL — {len(hard_failures)} hard gate(s) failed. Do NOT cut release."))
        return 1
    if warnings:
        print(_yellow(f"PASS WITH WARNINGS — {len(warnings)} soft gate(s) flagged."))
        print("Operator decides whether to proceed.")
        return 2
    print(_green("PASS — all gates green. Safe to tag release."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
