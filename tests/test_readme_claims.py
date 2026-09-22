"""The README's factual claims, checked against the code.

The layering diagram cites counts: how many skill files, how many specialist
roles. Those are the first thing a reader uses to judge whether the project
knows itself, and they rot silently — nobody updates a number in a README when
they add a file.

Written after nearly shipping "133 skill files" into the opening paragraph. The
figure came from a different repository's CLAUDE.md; the real count is 58. A
wrong number in the first screen is worse than no number.

Tolerant of drift by design: the counts are rounded down to a floor, so adding
skills does not fail the build. Only a claim that has become an overstatement
does.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_the_skill_count_is_not_an_overstatement():
    claimed = int(re.search(r"\((\d+) files\)", _readme()).group(1))
    actual = len(list((ROOT / "skills" / "files").rglob("*.md")))

    assert claimed <= actual, f"README claims {claimed} skill files; there are {actual}"


def test_the_specialist_count_is_not_an_overstatement():
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS

    claimed = int(re.search(r"\((\d+) roles\)", _readme()).group(1))

    assert claimed <= len(SPECIALIST_ARTIFACTS), (
        f"README claims {claimed} specialist roles; the registry has {len(SPECIALIST_ARTIFACTS)}"
    )


def test_the_layering_the_readme_describes_exists():
    """Each layer named in the diagram should be locatable, not aspirational."""
    assert (ROOT / "skills" / "files").is_dir(), "skills layer"
    assert (ROOT / "src" / "core" / "specialists" / "registry.py").is_file(), "specialists layer"
    assert (ROOT / "pipelines").is_dir(), "pipelines layer"
    assert (ROOT / "src" / "core" / "governance.py").is_file(), "gates layer"


def test_the_shipped_pipeline_is_real():
    """The README says a pipeline is a .toml file. It has to actually load."""
    from src.core.pipeline.spec import available, find_spec

    assert "empirical" in available()
    assert find_spec("empirical").steps


def test_the_floor_claim_is_true():
    """"The pipeline is yours; these are not" is a promise about the code."""
    from src.core.pipeline.spec import MANDATORY_CHECKS, spec_from_dict

    bare = spec_from_dict({"name": "bare", "steps": [{"kind": "strategist", "name": "initial"}]})

    assert bare.declared_checks() == []
    assert set(bare.checks()) >= MANDATORY_CHECKS, "a pipeline that declares nothing still carries the floor"


def test_the_readme_does_not_promise_specialists_as_files_yet():
    """Pipelines are files; specialists are still Python.

    Worth a test because it is the obvious next thing to claim and the claim
    would currently be false — registry.py is where a new role is added. If that
    changes, delete this test in the same commit that makes it wrong.
    """
    from src.core.specialists import registry

    assert isinstance(registry.SPECIALIST_ARTIFACTS, dict)
    assert not (ROOT / "specialists").is_dir(), (
        "specialists/ now exists — update the README, which still says only pipelines are files"
    )
