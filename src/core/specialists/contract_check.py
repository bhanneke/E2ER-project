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
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

#: A check that the pipeline EXECUTED correctly: the file was written, it
#: parses, it is not `{}`. A failure here is a bug in the run, not a property
#: of the paper, so no governance regime may switch it off. The 2026-08-05
#: validation cell is the case in point: `run_estimation.py` crashed, wrote
#: `{}`, and because the regime was `off` nothing flipped the specialist to
#: failure, so the traceback was never fed back and the drafter invented the
#: tables. That is not "an ungoverned paper", it is a broken run.
KIND_RELIABILITY = "reliability"

#: A check on whether the paper's CLAIMS hold: a real regression was run, and
#: it implements the declared specification. These are the verification
#: institutions the governance experiment varies, so a regime may shadow them.
KIND_VERIFICATION = "verification"

# Specialists whose results JSON must contain an actual estimated regression
# (a non-empty ``coefficients`` block), not just descriptive summaries. The
# basic non-empty check passes a ``{"raw_gap": …, "_note": …}`` descriptive
# dump; a real run produced a clean FE regression while another produced only
# descriptives (capping the data/identification review scores). The schema
# (skills/files/econometrics/estimation-results-schema.md) already mandates
# "one entry per estimated specification, each with coefficients and
# diagnostics" — this enforces it deterministically at the boundary.
_REGRESSION_REQUIRED: dict[str, str] = {"econometrics_specialist": "estimation_results.json"}

# Specialists that write `paper_draft.tex`. Their draft may REFERENCE tables
# but may not CONTAIN one: every table has to arrive via `\input{tables/...}`
# from the deterministic renderer.
#
# Without this, "no LLM in the number path" is only true of the path the
# renderer takes. In the 2026-08-05 validation cell the renderer produced
# tables/regime_baseline.tex, tables/regime_break.tex and
# tables/eth_comparison.tex; the draft `\input`-ed none of them and instead
# carried four inline `tabular` blocks under the SAME labels, with numbers the
# model wrote itself. 53 of 110 values traced to nothing. The gate that
# checks numbers ran afterwards and could only report the damage.
_NO_INLINE_TABLES: frozenset[str] = frozenset({"paper_drafter", "section_writer", "latex_formatter", "revisor"})

_TABULAR_RE = re.compile(r"\\begin\{tabular\}")
_TABLE_INPUT_RE = re.compile(r"\\input\{[^}]*\}")


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
    #: What KIND of failure this is, which decides whether governance may
    #: switch it off. See `KIND_RELIABILITY` / `KIND_VERIFICATION`.
    kind: str = KIND_RELIABILITY


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


# ── Identified-spec contract (declared vs estimated) ────────────────────────
#
# The binding quality problem after M5: econometrics rigor was high-variance
# run-to-run — one run estimated the identification strategy's clean
# collection×month TWFE (identification score 8), the next reported a weaker
# spec (score 5) under identical steering. Prompts shift the odds; this
# contract makes it deterministic: the identification strategist DECLARES the
# primary spec machine-readably (identification_spec.json, see the
# identification-spec-schema skill), and the econometrics specialist's
# headline `main` entry must ECHO the declared fixed effects, controls, and
# clustering. Echo fields are self-reported, so this enforces declared-vs-
# reported consistency — it eliminates the "silently substitute a raw gap"
# failure mode, raising the bar from "forgot" to "actively fabricates".

_IDENTIFICATION_SPEC_FILE = "identification_spec.json"


def _norm_token(value: Any) -> str:
    """Case/punctuation-insensitive comparison key (``Collection`` ≡
    ``collection``), but not fuzzy: ``month`` != ``year_month``."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _declared_names(primary: dict, key: str) -> list[str]:
    raw = primary.get(key)
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def check_matches_declared_spec(workspace: Path, results_relative: str) -> ContractCheck:
    """Verify the headline estimate implements the DECLARED identification.

    Reads ``identification_spec.json`` (written by identification_strategist);
    when it exists and declares fixed effects / controls / clustering, the
    results JSON must have a ``main`` entry with non-empty coefficients that
    echoes them (``fixed_effects`` / ``controls`` / ``cluster_level`` +
    ``n_clusters``). Degrades to ok when the spec is absent, unparseable, or
    declares nothing checkable — old papers and clean natural experiments
    (no FE, no controls, no clustering) pass untouched.
    """
    spec_path = workspace / _IDENTIFICATION_SPEC_FILE
    if not spec_path.is_file():
        return ContractCheck(results_relative, True, "")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ContractCheck(results_relative, True, "")
    primary = spec.get("primary") if isinstance(spec, dict) else None
    if not isinstance(primary, dict):
        return ContractCheck(results_relative, True, "")

    declared_fe = _declared_names(primary, "fixed_effects")
    declared_controls = _declared_names(primary, "controls")
    declared_cluster = str(primary.get("cluster_level") or "").strip()
    wants_cluster = bool(declared_cluster) and _norm_token(declared_cluster) != "none"
    if not declared_fe and not declared_controls and not wants_cluster:
        return ContractCheck(results_relative, True, "")

    try:
        results = json.loads((workspace / results_relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Parse/read problems are owned by check_artifact_nonempty.
        return ContractCheck(results_relative, True, "")
    if not isinstance(results, dict):
        return ContractCheck(results_relative, True, "")

    problems: list[str] = []
    main = results.get("main")
    coefficients = main.get("coefficients") if isinstance(main, dict) else None
    if not isinstance(main, dict) or not (isinstance(coefficients, dict) and coefficients):
        problems.append(
            "the headline estimate must live under the top-level key 'main' with a non-empty "
            "'coefficients' block (identification_spec.json declares an identified design, so a "
            "'main' entry implementing it is required)"
        )
    else:
        echoed_fe = [str(x) for x in main.get("fixed_effects") or [] if str(x).strip()]
        missing_fe = [f for f in declared_fe if not any(_norm_token(e) == _norm_token(f) for e in echoed_fe)]
        if missing_fe:
            problems.append(
                f"main.fixed_effects {echoed_fe or '(absent)'} does not include the declared "
                f"fixed effects {missing_fe} — estimate WITH those FE absorbed and echo them in "
                "a 'fixed_effects' list on the 'main' entry"
            )
        echoed_controls = [str(x) for x in main.get("controls") or [] if str(x).strip()]
        echoed_controls += list(coefficients.keys())
        missing_controls = [
            c for c in declared_controls if not any(_norm_token(e) == _norm_token(c) for e in echoed_controls)
        ]
        if missing_controls:
            problems.append(
                f"declared controls {missing_controls} appear neither in main.controls nor among "
                "main.coefficients — include them in the estimation and echo them"
            )
        if wants_cluster:
            echoed_cluster = str(main.get("cluster_level") or "").strip()
            if _norm_token(echoed_cluster) != _norm_token(declared_cluster):
                problems.append(
                    f"identification_spec.json declares cluster_level {declared_cluster!r} but main "
                    f"reports {echoed_cluster or 'nothing'!r} — cluster the SEs as declared and echo it"
                )
            n_clusters = main.get("n_clusters")
            if not isinstance(n_clusters, int | float) or isinstance(n_clusters, bool) or n_clusters <= 0:
                problems.append(
                    "clustered SEs are declared but main.n_clusters is missing/invalid — report the "
                    "actual cluster count"
                )

    if not problems:
        return ContractCheck(results_relative, True, "")
    return ContractCheck(
        results_relative,
        False,
        "identified-spec contract: "
        + "; ".join(problems)
        + ". The declared primary design is in identification_spec.json — the headline 'main' entry "
        "must implement and echo it (see the estimation-results-schema skill).",
    )


# ── Contract-violation feedback (self-correction across attempts) ───────────
#
# A contract violation flips the specialist result to failure, but before
# this existed the WHY never reached the next attempt's prompt — the model
# retried blind up to _MAX_SPECIALIST_ATTEMPTS times, then the run PAUSED.
# (read_execution_error can't carry it: it early-returns when the sidecar is
# populated, which is exactly the state after a populated-but-noncompliant
# output.) The violation summary is persisted here and consumed — once — by
# the specialist's next attempt.

_FEEDBACK_DIR = ".contract_feedback"


def write_contract_feedback(workspace: Path, specialist: str, summary: str) -> None:
    """Persist a contract-violation summary for the specialist's next attempt.
    Best-effort: never raises (a lost feedback note must not fail the run)."""
    try:
        feedback_dir = workspace / _FEEDBACK_DIR
        feedback_dir.mkdir(parents=True, exist_ok=True)
        (feedback_dir / f"{specialist}.txt").write_text(summary, encoding="utf-8")
    except OSError as e:
        logger.warning("could not persist contract feedback for %s: %s", specialist, e)


def read_contract_feedback(workspace: Path, specialist: str) -> str | None:
    """Return a ready-to-inject prompt section for a prior contract violation,
    consuming the note (one violation feeds exactly one retry). ``None`` when
    there's nothing to feed back."""
    path = workspace / _FEEDBACK_DIR / f"{specialist}.txt"
    if not path.is_file():
        return None
    try:
        summary = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if not summary:
        return None
    return (
        "## PREVIOUS ATTEMPT REJECTED — OUTPUT-CONTRACT VIOLATION\n\n"
        "Your previous attempt completed, but its output failed a deterministic "
        "contract check and was rejected:\n\n"
        f"{summary}\n\n"
        "Fix exactly this in the current attempt. Keep everything else about your "
        "approach unless the fix requires changing it."
    )


def check_no_inline_tables(workspace: Path, relative: str = "paper_draft.tex") -> ContractCheck:
    """The draft may reference tables but must not contain them.

    A `\\begin{tabular}` in `paper_draft.tex` is a table the model typed rather
    than one the renderer filled from result files, so its numbers bypass the
    provenance chain entirely. Tables belong in `tables/*.tex`, pulled in with
    `\\input`.
    """
    target = workspace / relative
    if not target.is_file():
        # Absence is the non-empty check's business, not ours.
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ContractCheck(relative, False, f"read failed: {e}", kind=KIND_VERIFICATION)

    inline = len(_TABULAR_RE.findall(text))
    if not inline:
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    inputs = len(_TABLE_INPUT_RE.findall(text))
    return ContractCheck(
        relative,
        False,
        f"{inline} inline tabular environment(s) in the draft "
        f"({inputs} \\input reference(s)) — tables must come from tables/*.tex "
        "via \\input so their numbers trace to result files, not from the draft itself",
        kind=KIND_VERIFICATION,
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
            # These two are VERIFICATION, not reliability: the file exists and
            # parses (reliability is satisfied), and we are now asking whether
            # what it contains supports the paper's claims. Governance may
            # shadow them; it may not shadow the checks above.
            regression_check = replace(check_has_regression(workspace, regression_file), kind=KIND_VERIFICATION)
            checks.append(regression_check)
            # Identified-spec contract: only meaningful once a regression
            # exists at all ("estimate SOMETHING" precedes "estimate the
            # DECLARED thing"), and layering both failures would muddy the
            # retry feedback.
            if regression_check.ok:
                checks.append(replace(check_matches_declared_spec(workspace, regression_file), kind=KIND_VERIFICATION))

    # Draft-writing specialists may reference tables, never contain them.
    if specialist in _NO_INLINE_TABLES:
        draft = SPECIALIST_ARTIFACTS.get(specialist, "paper_draft.tex")
        if draft.endswith(".tex") and not any(c.artifact == draft and not c.ok for c in checks):
            checks.append(check_no_inline_tables(workspace, draft))
    return checks
