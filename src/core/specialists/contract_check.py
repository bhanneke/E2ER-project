"""Specialist output-contract enforcement — v0.9 M4.3.

A specialist's tool_loop can return ``success=True`` while its
declared output artifact is logically empty (the literal ``{}`` was
written, a one-byte ``.md`` was written, the file is whitespace-only).
The M4 paper run surfaced this: ``econometrics_specialist`` returned
``success=True`` but ``estimation_results.json`` was literally
``{}``. The pipeline then burned ~13.7M tokens / 29 specialist calls
writing a paper around an empty result before the mechanism reviewer
caught it.

This module is the cheap, deterministic gate that catches that class
of failure at the specialist boundary, *before* the rest of the
pipeline runs on a hollow contract.

Rules per file extension (intentionally generous — we're catching
``{}`` not "is this a good paper"):

- ``.json`` — must parse, and parsed value must not be ``{}`` / ``[]``
  / ``null``. Empty dicts/lists are the M4 failure mode.
- ``.md`` / ``.tex`` / ``.py`` — > 100 non-whitespace characters.
  A real specialist output is always at least a paragraph.
- Any other file — exists with size > 0.

Coverage:

- The specialist's PRIMARY artifact (``SPECIALIST_ARTIFACTS[name]``)
  is always checked.
- Listed sidecars (``SPECIALIST_SIDECAR_ARTIFACTS[name]``) are
  required and checked too. Optional sidecars not in the registry
  (e.g., ``robustness_results.json`` for ``econometrics_specialist``)
  are not checked — they're "produce if you ran the analysis".
- Specialists not in ``SPECIALIST_ARTIFACTS`` (none today, but if any
  appear) get no contract check — better to be silent than to false-
  trip on undeclared outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


# Minimum non-whitespace character count for prose / code artifacts.
# 100 is generous (a real specialist output is always at least a
# paragraph, usually 1k+ chars) and easily exceeds the failure modes
# we're catching: empty file (0), single-line stub (~20), placeholder
# comment (~50).
_MIN_PROSE_CHARS = 100

# File extensions that get the prose-character check.
_PROSE_EXTS = frozenset({".md", ".tex", ".py", ".txt"})


@dataclass(frozen=True)
class ContractCheck:
    """One specialist output's contract verification result."""

    artifact: str  # workspace-relative path
    ok: bool
    reason: str = ""  # one-liner explanation when not ok


def check_artifact_nonempty(workspace: Path, relative: str) -> ContractCheck:
    """Verify a single declared artifact has non-trivial content.

    ``relative`` is the workspace-relative path (matches the values
    in ``SPECIALIST_ARTIFACTS``). Returns a ``ContractCheck`` — never
    raises, even for permission errors or missing parents (those
    surface as ``ok=False`` with the OS error in ``reason``).
    """
    target = workspace / relative
    if not target.exists():
        return ContractCheck(relative, False, "file not written")
    try:
        size = target.stat().st_size
    except OSError as e:
        return ContractCheck(relative, False, f"stat failed: {e}")
    if size == 0:
        return ContractCheck(relative, False, "file is empty (0 bytes)")

    ext = target.suffix.lower()
    if ext == ".json":
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as e:
            return ContractCheck(relative, False, f"read failed: {e}")
        # Cheap up-front: trim whitespace and check for the literal
        # empty containers before paying for a parse.
        stripped = text.strip()
        if stripped in ("{}", "[]", "null", ""):
            return ContractCheck(relative, False, f"empty JSON ({stripped or 'whitespace-only'!r})")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            return ContractCheck(relative, False, f"invalid JSON: {e.msg}")
        if isinstance(parsed, dict | list) and len(parsed) == 0:
            return ContractCheck(relative, False, "empty JSON (parsed to empty container)")
        if parsed is None:
            return ContractCheck(relative, False, "JSON parsed to null")
        return ContractCheck(relative, True, "")

    if ext in _PROSE_EXTS:
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ContractCheck(relative, False, f"read failed: {e}")
        non_ws = sum(1 for c in text if not c.isspace())
        if non_ws < _MIN_PROSE_CHARS:
            return ContractCheck(relative, False, f"only {non_ws} non-whitespace chars (min {_MIN_PROSE_CHARS})")
        return ContractCheck(relative, True, "")

    # Unknown extension — accept any non-zero file size.
    return ContractCheck(relative, True, "")


def check_specialist_artifacts(workspace: Path, specialist: str) -> list[ContractCheck]:
    """Check every required artifact for ``specialist`` — the primary
    plus any declared sidecars. Returns one ``ContractCheck`` per
    declared path, in order. Empty list when the specialist has no
    declared artifacts (no check applies).
    """
    # Imported lazily so this module stays dependency-light and can
    # be unit-tested without the registry side effects.
    from .registry import SPECIALIST_ARTIFACTS, SPECIALIST_SIDECAR_ARTIFACTS

    checks: list[ContractCheck] = []
    primary = SPECIALIST_ARTIFACTS.get(specialist)
    if primary:
        checks.append(check_artifact_nonempty(workspace, primary))
    for sidecar in SPECIALIST_SIDECAR_ARTIFACTS.get(specialist, []):
        checks.append(check_artifact_nonempty(workspace, sidecar))
    return checks
