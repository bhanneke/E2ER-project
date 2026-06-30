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
  required and checked too — EXCEPT those in
  ``SPECIALIST_OPTIONAL_SIDECARS[name]`` (e.g. ``figure_spec.json`` for
  ``data_analyst``), which are best-effort: still prompted and checked
  by verify_numbers when present, but not hard-gated here because they
  have no deterministic producer at the specialist boundary.
- Optional sidecars not in the registry at all (e.g.,
  ``robustness_results.json`` for ``econometrics_specialist``) are not
  checked — they're "produce if you ran the analysis".
- Specialists not in ``SPECIALIST_ARTIFACTS`` (none today, but if any
  appear) get no contract check — better to be silent than to false-
  trip on undeclared outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

# Specialists whose results JSON must contain an actual estimated regression
# (a non-empty ``coefficients`` block), not just descriptive summaries. The
# basic non-empty check passes a ``{"raw_gap": …, "_note": …}`` descriptive
# dump; a real run produced a clean FE regression while another produced only
# descriptives (capping the data/identification review scores). The schema
# (skills/files/econometrics/estimation-results-schema.md) already mandates
# "one entry per estimated specification, each with coefficients and
# diagnostics" — this enforces it deterministically at the boundary.
_REGRESSION_REQUIRED: dict[str, str] = {"econometrics_specialist": "estimation_results.json"}


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


def _has_coefficients(obj: Any) -> bool:
    """True if ``obj`` contains any non-empty ``coefficients`` dict, anywhere in
    its nested structure (specs may be top-level or nested, e.g. ``main_level``)."""
    if isinstance(obj, dict):
        coeffs = obj.get("coefficients")
        if isinstance(coeffs, dict) and coeffs:
            return True
        return any(_has_coefficients(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_coefficients(v) for v in obj)
    return False


def check_has_regression(workspace: Path, relative: str) -> ContractCheck:
    """Verify a results JSON holds at least one estimated specification (a
    non-empty ``coefficients`` block) — not a descriptive-only dump. Assumes the
    basic non-empty/parse check already passed; degrades to ok on read error so
    it never double-reports a problem the non-empty check already flagged."""
    target = workspace / relative
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ContractCheck(relative, True, "")
    if _has_coefficients(parsed):
        return ContractCheck(relative, True, "")
    return ContractCheck(
        relative,
        False,
        "no estimated regression: estimation_results.json has no non-empty 'coefficients' block "
        "(descriptive-only output). Estimate at least one identified specification and write its "
        "coefficients/SEs/p-values per the estimation-results-schema — descriptive summaries do not "
        "substitute for the estimation.",
    )


def check_specialist_artifacts(workspace: Path, specialist: str) -> list[ContractCheck]:
    """Check every required artifact for ``specialist`` — the primary
    plus any declared sidecars. Returns one ``ContractCheck`` per
    declared path, in order. Empty list when the specialist has no
    declared artifacts (no check applies).
    """
    # Imported lazily so this module stays dependency-light and can
    # be unit-tested without the registry side effects.
    from .registry import (
        SPECIALIST_ARTIFACTS,
        SPECIALIST_OPTIONAL_SIDECARS,
        SPECIALIST_SIDECAR_ARTIFACTS,
    )

    checks: list[ContractCheck] = []
    primary = SPECIALIST_ARTIFACTS.get(specialist)
    if primary:
        checks.append(check_artifact_nonempty(workspace, primary))
    # Best-effort sidecars are prompted + verify_numbers-checked when
    # present, but not hard-gated here (no deterministic producer).
    optional = SPECIALIST_OPTIONAL_SIDECARS.get(specialist, frozenset())
    for sidecar in SPECIALIST_SIDECAR_ARTIFACTS.get(specialist, []):
        if sidecar in optional:
            continue
        checks.append(check_artifact_nonempty(workspace, sidecar))

    # Deterministic "an actual regression was run" gate. Only applied once the
    # basic non-empty check for that file passed, so we don't pile a second
    # failure on top of an already-flagged empty/invalid file.
    regression_file = _REGRESSION_REQUIRED.get(specialist)
    if regression_file:
        base_failed = any(c.artifact == regression_file and not c.ok for c in checks)
        if not base_failed:
            checks.append(check_has_regression(workspace, regression_file))
    return checks
