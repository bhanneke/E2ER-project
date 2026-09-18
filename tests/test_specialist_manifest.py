"""docs/SPECIALISTS.md must describe the registry as it is now.

A manifest that drifts is worse than none: it is the file someone consults to
decide whether editing a skill is safe, and a stale answer is a confident wrong
one. Generated from the registry, checked here, on the same principle as the
pipeline figure.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "gen_specialist_manifest.py"
MANIFEST = REPO / "docs" / "SPECIALISTS.md"


def test_manifest_is_current():
    """Fails when a specialist or skill changed and the manifest was not regenerated."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{MANIFEST.relative_to(REPO)} is stale — run scripts/gen_specialist_manifest.py\n{result.stderr}"
    )


def test_every_referenced_skill_exists_on_disk():
    """A specialist asking for a skill file that is not shipped gets silence.

    The loader finds nothing, no error is raised, and the instruction simply
    never reaches the model — the same shape as the literature tool that was
    granted and never called.
    """
    from src.core.specialists.registry import SPECIALIST_SKILLS

    root = REPO / "src" / "skills" / "files"
    if not root.is_dir():
        root = REPO / "skills" / "files"
    if not root.is_dir():
        pytest.skip("no skills/files directory in this checkout")

    on_disk = {p.relative_to(root).with_suffix("").as_posix() for p in root.rglob("*.md")}

    missing: dict[str, list[str]] = {}
    for specialist, skills in SPECIALIST_SKILLS.items():
        absent = [s for s in skills if s not in on_disk]
        if absent:
            missing[specialist] = absent

    assert not missing, f"specialists reference skill files that do not exist: {missing}"


def test_every_specialist_declares_an_artifact():
    """A specialist with no declared artifact cannot have its contract checked,
    which is the mechanism the whole retry loop rests on."""
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SKILLS

    undeclared = sorted(set(SPECIALIST_SKILLS) - set(SPECIALIST_ARTIFACTS))
    assert not undeclared, f"specialists with skills but no declared artifact: {undeclared}"
