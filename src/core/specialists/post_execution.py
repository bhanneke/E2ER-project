"""Runner-side post-specialist execution — make the right thing happen.

Specialists run on a deliberately locked-down tool set: on every backend
they get Read/Write/Edit/Glob/Grep plus the guarded ``e2er-data`` /
``e2er-allium-query`` wrappers, and **no general code execution** (see
``src/modules/llm/claude_code.py`` — "Specialists that need execution get
their tools wired through Python at the runner level, not via Bash from
the model"). So an econometrics specialist can write a perfectly correct
``run_estimation.py`` and then has no tool to run it — it falls through to
writing ``estimation_results.json = "{}"`` as the documented honest
signal. The M4 paper ran this failure mode end to end. Diagnosis:
``docs/M4_DIAGNOSIS.md``.

The M4.3 contract check catches the empty sidecar at the boundary and
flips the specialist to ``success=False``. That's the negative path:
*refuse the wrong thing*. This module is the positive path — *make the
right thing happen* — by having the runner shell out and execute the
script itself.

Why this exists at the runner level (not the skill file): the model
genuinely cannot execute code, so a skill instruction "run your script"
would be unactionable. Execution has to happen here.

Robustness (the M5 re-run lesson, ``docs/M4_RERUN_FINDINGS.md``): the
first version keyed on a single hardcoded script filename
(``run_estimation.py``) and sidecar (``estimation_results.json``). The
re-run's specialist named its script ``analyze.py`` writing
``analysis_output.json``, so the runner found nothing and no-op'd. The
brittleness had just moved from "did the model *run* the script?" to "did
the model *name* it the canonical name?". This version therefore:

- **Discovers** the script: tries an ordered list of canonical candidate
  names, then falls back to globbing ``*.py`` and picking the one whose
  source actually references the target sidecar (or a declared alternate
  output) — i.e. the script that claims to write what we need.
- **Normalizes** the output: if the discovered script writes a populated
  JSON under an alternate name (``analysis_output.json``) rather than the
  canonical sidecar, the runner copies it onto the canonical sidecar so
  the M4.3 contract check (which keys on the canonical name) sees it.

Properties:

- **Backend-agnostic** — runs via ``subprocess.run``, not the model's
  tool call. Works on every backend, including ones that expose no
  code-execution tool to the model at all (i.e. all of them, by design).
- **Idempotent** — if the specialist already populated the sidecar, no-op.
- **Auditable** — writes a per-convention log (``run_estimation.log``)
  with the discovered script, subprocess exit code, full stdout/stderr,
  and any normalization performed.
- **Composes with M4.3** — runs *before* the contract check. If the
  script also fails (import error, data shape mismatch, timeout), the
  sidecar stays empty and M4.3 fires.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


# Per-specialist execution convention. Keys are specialist names; each
# value declares how to find the script the specialist was supposed to
# run, the canonical sidecar that script must end up populating (the same
# path M4.3 checks), and alternate output names to normalize from.
#
# Add an entry here to extend runner-side execution coverage.
@dataclass(frozen=True)
class ExecutionConvention:
    sidecar: str  # canonical workspace-relative path M4.3 checks for "populated"
    log: str  # workspace-relative path the runner writes
    # Ordered preferred script names, canonical first. Tried in order.
    script_candidates: tuple[str, ...] = ()
    # Alternate JSON outputs the script might write instead of `sidecar`.
    # If one of these is populated after the run and `sidecar` is not, the
    # runner copies it onto `sidecar`. The canonical sidecar is always an
    # implicit member (listed first by `_output_targets`).
    output_candidates: tuple[str, ...] = ()
    timeout_seconds: int = 600

    def _output_targets(self) -> tuple[str, ...]:
        # Canonical sidecar first, then declared alternates, de-duplicated.
        seen: dict[str, None] = {self.sidecar: None}
        for c in self.output_candidates:
            seen.setdefault(c, None)
        return tuple(seen)


EXECUTION_CONVENTIONS: dict[str, ExecutionConvention] = {
    "econometrics_specialist": ExecutionConvention(
        sidecar="estimation_results.json",
        log="run_estimation.log",
        script_candidates=(
            "run_estimation.py",
            "estimation.py",
            "estimate.py",
            "run_analysis.py",
            "analyze.py",
            "analysis.py",
        ),
        output_candidates=(
            "analysis_output.json",
            "estimation_output.json",
            "results.json",
        ),
        timeout_seconds=600,
    ),
    "data_analyst": ExecutionConvention(
        sidecar="summary_statistics.json",
        log="build_panel.log",
        script_candidates=(
            "build_panel.py",
            "build_gw_panel.py",
            "compute_summary.py",
            "summary_statistics.py",
            "build_data.py",
        ),
        output_candidates=(
            "summary_stats.json",
            "summary_output.json",
        ),
        timeout_seconds=600,
    ),
}


@dataclass(frozen=True)
class ExecutionAttempt:
    """Audit record for a single post-specialist execution attempt."""

    specialist: str
    script: str  # the script the runner actually found/ran ("" if none)
    ran: bool  # True if the runner actually invoked the subprocess
    returncode: int | None  # None if not run; subprocess exit code otherwise
    populated_sidecar: bool  # True if the canonical sidecar is non-trivial after the attempt
    reason: str = ""  # human-readable explanation
    normalized_from: str = ""  # alt output copied onto the sidecar, if any
    discovered: bool = False  # True if the script was found by glob, not a canonical name


def _is_populated(path: Path) -> bool:
    """Return True if a JSON file exists and is non-trivial.

    Mirrors :func:`contract_check.check_artifact_nonempty`'s JSON rules:
    must parse, must not be ``{}`` / ``[]`` / ``null`` / whitespace-only.
    """
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if text.strip() in ("", "{}", "[]", "null"):
        return False
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    if isinstance(parsed, dict | list) and len(parsed) == 0:
        return False
    if parsed is None:
        return False
    return True


def _discover_script(workspace: Path, convention: ExecutionConvention) -> tuple[Path | None, bool]:
    """Find the script to run. Returns (path, discovered_by_glob).

    1. Try the ordered canonical candidate names; first hit wins.
    2. Fall back to globbing ``*.py`` and keeping scripts whose source
       references the canonical sidecar or any declared alternate output
       (i.e. the script claims to write what we need). Pick the most
       recently modified — the specialist's latest attempt.
    """
    for name in convention.script_candidates:
        p = workspace / name
        if p.is_file():
            return p, False

    targets = convention._output_targets()
    matches: list[Path] = []
    for py in workspace.glob("*.py"):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(t in src for t in targets):
            matches.append(py)
    if not matches:
        return None, False
    # Most recently modified = the specialist's latest script.
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0], True


def _normalize_output(workspace: Path, convention: ExecutionConvention) -> str:
    """If the canonical sidecar is empty but an alternate output is
    populated, copy the alternate onto the sidecar. Returns the alternate
    filename copied from, or "" if nothing was normalized.
    """
    sidecar_path = workspace / convention.sidecar
    if _is_populated(sidecar_path):
        return ""
    for alt in convention.output_candidates:
        if alt == convention.sidecar:
            continue
        alt_path = workspace / alt
        if _is_populated(alt_path):
            try:
                sidecar_path.write_text(alt_path.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError as e:
                logger.warning("post-specialist exec: could not normalize %s -> %s: %s", alt, convention.sidecar, e)
                return ""
            logger.info("post-specialist exec: normalized %s -> %s", alt, convention.sidecar)
            return alt
    return ""


def maybe_execute_specialist_script(workspace: Path, specialist: str) -> ExecutionAttempt:
    """Execute the specialist's analysis script if one can be found and
    the canonical sidecar isn't already populated.

    Returns an ``ExecutionAttempt`` recording what happened. Never raises
    — every error path returns a populated record so the caller can log
    it without try/except.
    """
    # The runner passes a workspace path relative to its cwd (e.g.
    # ``Tests/workspaces/<id>``). Resolve to absolute up front: otherwise
    # the subprocess below runs with ``cwd=workspace`` AND a
    # workspace-relative script path, doubling the prefix
    # (``<ws>/<ws>/run_estimation.py``) and failing with "No such file".
    workspace = Path(workspace).resolve()
    convention = EXECUTION_CONVENTIONS.get(specialist)
    if convention is None:
        return ExecutionAttempt(
            specialist=specialist,
            script="",
            ran=False,
            returncode=None,
            populated_sidecar=False,
            reason="no execution convention for this specialist",
        )

    sidecar_path = workspace / convention.sidecar

    if _is_populated(sidecar_path):
        # The specialist (somehow) produced it. Nothing to do.
        return ExecutionAttempt(
            specialist=specialist,
            script="",
            ran=False,
            returncode=None,
            populated_sidecar=True,
            reason="sidecar already populated by specialist",
        )

    script_path, discovered = _discover_script(workspace, convention)
    if script_path is None:
        return ExecutionAttempt(
            specialist=specialist,
            script="",
            ran=False,
            returncode=None,
            populated_sidecar=False,
            reason="no runnable script found in workspace",
        )

    rel_script = script_path.name
    logger.info(
        "post-specialist exec: %s sidecar empty — running %s%s (timeout=%ds)",
        specialist,
        rel_script,
        " [discovered]" if discovered else "",
        convention.timeout_seconds,
    )
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=convention.timeout_seconds,
            check=False,
        )
        rc = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as e:
        # TimeoutExpired.stdout/stderr widen to bytes | str in the stub even
        # though we passed text=True. Coerce to str for the log writer.
        rc = None
        raw_out: object = e.stdout or ""
        raw_err: object = e.stderr or ""
        stdout = raw_out.decode("utf-8", errors="replace") if isinstance(raw_out, bytes) else str(raw_out)
        stderr = raw_err.decode("utf-8", errors="replace") if isinstance(raw_err, bytes) else str(raw_err)
        stderr = stderr + f"\n[TIMEOUT after {convention.timeout_seconds}s]"
        logger.warning("post-specialist exec: %s timed out after %ds", rel_script, convention.timeout_seconds)
    except Exception as e:  # noqa: BLE001 — defensive, log + record
        logger.warning("post-specialist exec: %s failed: %s", rel_script, e)
        return ExecutionAttempt(
            specialist=specialist,
            script=rel_script,
            ran=False,
            returncode=None,
            populated_sidecar=False,
            reason=f"subprocess launch failed: {e!r}",
            discovered=discovered,
        )

    # If the script wrote a populated alternate output but not the canonical
    # sidecar, copy it across so M4.3 (which keys on the canonical name) sees it.
    normalized_from = _normalize_output(workspace, convention)

    # Always write the audit log, even on non-zero exit. The next reviewer
    # (or the M4.3 error message) points here.
    log_path = workspace / convention.log
    try:
        log_path.write_text(
            f"# post-specialist exec for {specialist}\n"
            f"# script: {rel_script}{' (discovered by glob)' if discovered else ''}\n"
            f"# returncode: {rc}\n"
            f"# normalized_from: {normalized_from or '(none)'}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}\n",
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("post-specialist exec: could not write %s: %s", convention.log, e)

    populated = _is_populated(sidecar_path)
    if rc == 0 and populated:
        logger.info("post-specialist exec: %s succeeded; %s populated", rel_script, convention.sidecar)
        reason = "script executed; sidecar populated"
        if normalized_from:
            reason += f" (normalized from {normalized_from})"
    elif rc == 0 and not populated:
        logger.warning("post-specialist exec: %s exited 0 but %s still empty", rel_script, convention.sidecar)
        reason = "script exited 0 but sidecar not populated"
    else:
        logger.warning("post-specialist exec: %s exited %s", rel_script, rc)
        reason = f"script exited with code {rc}"

    return ExecutionAttempt(
        specialist=specialist,
        script=rel_script,
        ran=True,
        returncode=rc,
        populated_sidecar=populated,
        reason=reason,
        normalized_from=normalized_from,
        discovered=discovered,
    )
