"""Contract tests for Lane A — specialist registry integrity.

Every specialist has a canonical artifact filename (in SPECIALIST_ARTIFACTS)
and a skill bundle (in SPECIALIST_SKILLS). These tests guarantee that the
two registries stay aligned and that every referenced skill file actually
exists on disk.

Why this exists: live paper runs frequently die with "specialist X
succeeded but canonical artifact Y is missing", which is caused by
mismatch between what the runner expects, what the registry advertises,
and what's in the prompt. Cascade detection halts the pipeline cleanly,
but you'd rather catch the misconfiguration at PR time.
"""

from __future__ import annotations

from pathlib import Path

from src.core.specialists.registry import (
    POLISH_SPECIALISTS,
    REVIEWER_SPECIALISTS,
    SPECIALIST_ARTIFACTS,
    SPECIALIST_SKILLS,
)
from src.skills.loader import load_skills_for_specialist

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills" / "files"


def test_every_artifact_specialist_has_skills():
    """Every specialist with a canonical artifact must have skills registered.

    Otherwise the LLM prompt for that specialist is missing its domain
    instructions and the canonical artifact is unlikely to land in the
    expected shape.
    """
    missing = [s for s in SPECIALIST_ARTIFACTS if s not in SPECIALIST_SKILLS]
    assert not missing, (
        f"Specialists with artifacts but no skills: {missing}. "
        "Add a SPECIALIST_SKILLS entry pointing at the relevant skill files."
    )


def test_every_skill_specialist_has_artifact():
    """Every specialist with skills must have a canonical artifact filename.

    Without an artifact entry, the dispatcher can't enforce cascade
    detection — a specialist could "succeed" without writing anything and
    the pipeline would advance with no upstream output.
    """
    missing = [s for s in SPECIALIST_SKILLS if s not in SPECIALIST_ARTIFACTS]
    assert not missing, (
        f"Specialists with skills but no artifact: {missing}. "
        "Add a SPECIALIST_ARTIFACTS entry naming the canonical output file."
    )


def test_skill_paths_resolve_to_files():
    """Every skill path in SPECIALIST_SKILLS must point to a real .md file.

    Catches the failure mode where someone references e.g.
    `data/allium-developer-api` before creating
    `skills/files/data/allium-developer-api.md`.
    """
    missing: list[tuple[str, str]] = []  # (specialist, missing_path)
    for specialist, skill_paths in SPECIALIST_SKILLS.items():
        for path in skill_paths:
            candidate = SKILLS_DIR / f"{path}.md"
            if not candidate.exists():
                missing.append((specialist, path))
    assert not missing, "Skill paths that don't resolve to a .md file on disk:\n" + "\n".join(
        f"  {s} -> skills/files/{p}.md" for s, p in missing
    )


def test_loader_produces_nonempty_for_all_specialists():
    """load_skills_for_specialist() must return at least one paragraph for every
    registered specialist.

    Different from test_skill_paths_resolve_to_files — this exercises the
    actual loader code path, catching bugs in the search-dir logic, ref
    resolution, etc.
    """
    empties: list[str] = []
    for specialist in SPECIALIST_SKILLS:
        text = load_skills_for_specialist(specialist).strip()
        if not text:
            empties.append(specialist)
    assert not empties, f"Specialists whose skill bundle loaded as empty: {empties}"


def test_reviewer_specialists_are_all_registered():
    """Every reviewer in REVIEWER_SPECIALISTS must be in both registries.

    REVIEWER_SPECIALISTS controls cascade-tolerance — if a reviewer name
    is misspelled here, the dispatcher will treat that specialist as
    non-tolerant and halt the pipeline on its (often non-blocking)
    failure.
    """
    missing_artifacts = [r for r in REVIEWER_SPECIALISTS if r not in SPECIALIST_ARTIFACTS]
    assert not missing_artifacts, f"Reviewers not in SPECIALIST_ARTIFACTS: {missing_artifacts}"
    missing_skills = [r for r in REVIEWER_SPECIALISTS if r not in SPECIALIST_SKILLS]
    assert not missing_skills, f"Reviewers not in SPECIALIST_SKILLS: {missing_skills}"


def test_polish_specialists_are_all_registered():
    """Every polish specialist must be in both registries (same reason as reviewers)."""
    missing_artifacts = [p for p in POLISH_SPECIALISTS if p not in SPECIALIST_ARTIFACTS]
    assert not missing_artifacts, f"Polish specialists not in SPECIALIST_ARTIFACTS: {missing_artifacts}"
    missing_skills = [p for p in POLISH_SPECIALISTS if p not in SPECIALIST_SKILLS]
    assert not missing_skills, f"Polish specialists not in SPECIALIST_SKILLS: {missing_skills}"


def test_artifact_paths_are_relative():
    """SPECIALIST_ARTIFACTS values are workspace-relative paths, not absolute.

    The dispatcher resolves them against the paper workspace. An absolute
    path (starting with '/' or 'C:\\') would write outside the workspace
    and break cascade detection.
    """
    bad = {
        s: a
        for s, a in SPECIALIST_ARTIFACTS.items()
        if a.startswith("/") or a.startswith("\\") or (len(a) > 2 and a[1] == ":")
    }
    assert not bad, f"Absolute artifact paths (must be workspace-relative): {bad}"


def test_artifact_filenames_have_extensions():
    """Every artifact must have a file extension so the renderer / reader knows
    how to handle it.

    Catches typos like ``"paper_draft"`` (no extension) that would cause
    the cascade detector to look for the wrong filename.
    """
    bad = {s: a for s, a in SPECIALIST_ARTIFACTS.items() if "." not in Path(a).name}
    assert not bad, f"Artifact filenames without extensions: {bad}"
