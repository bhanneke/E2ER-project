"""Runner-side post-specialist execution — make the right thing happen.

A specialist can write a perfectly correct estimation script and then
choose, per its skill file's *"don't fabricate"* rule, not to execute
it — falling through to writing ``estimation_results.json = "{}"`` as
the documented honest signal. The M4 paper ran this failure mode end
to end. Diagnosis: ``docs/M4_DIAGNOSIS.md``.

The M4.3 contract check catches the empty sidecar at the boundary and
flips the specialist to ``success=False``. That's the negative path:
*refuse the wrong thing*. This module is the positive path: *make the
right thing happen* by having the runner shell out and execute the
script itself.

Properties:

- **Backend-agnostic** — runs via ``subprocess.run``, not via the
  model's tool call. Works on every backend (SDK or CLI), including
  ones that don't expose a code-execution tool to the model at all.
- **Idempotent** — if the specialist already populated the sidecar,
  this is a no-op.
- **Auditable** — writes ``run_estimation.log`` (or the analogous
  log per convention) with the subprocess exit code and full
  stdout/stderr so the next reviewer can read it.
- **Composes with M4.3** — runs *before* the contract check. If the
  script also fails (import error, data shape mismatch, timeout),
  the sidecar stays empty and M4.3 fires.

Scope: starts narrow on ``econometrics_specialist`` + the
``run_estimation.py`` / ``estimation_results.json`` convention.
The registry below lets us add more specialist→script→sidecar tuples
as we generalise.
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
# value declares the script the specialist is expected to produce, the
# sidecar that script populates, and the audit log filename.
#
# Add an entry here to extend the runner-side execution coverage. The
# current narrow scope is intentional — the M4 failure mode was
# specifically `econometrics_specialist` writing `{}` while having a
# correct script on disk. data_analyst's `build_panel.py` and
# replication_packager's `replication/estimation.py` are candidates
# for a follow-up extension after the first re-run validates the
# convention.
@dataclass(frozen=True)
class ExecutionConvention:
    script: str  # workspace-relative path
    sidecar: str  # workspace-relative path checked for "populated"
    log: str  # workspace-relative path the runner writes
    timeout_seconds: int = 600


EXECUTION_CONVENTIONS: dict[str, ExecutionConvention] = {
    "econometrics_specialist": ExecutionConvention(
        script="run_estimation.py",
        sidecar="estimation_results.json",
        log="run_estimation.log",
        timeout_seconds=600,
    ),
}


@dataclass(frozen=True)
class ExecutionAttempt:
    """Audit record for a single post-specialist execution attempt."""

    specialist: str
    script: str
    ran: bool  # True if the runner actually invoked the subprocess
    returncode: int | None  # None if not run; subprocess exit code otherwise
    populated_sidecar: bool  # True if the sidecar is non-trivial post-attempt
    reason: str = ""  # human-readable explanation for skipped / failed runs


def _is_sidecar_populated(path: Path) -> bool:
    """Return True if the sidecar file exists and is non-trivial.

    Mirrors :func:`contract_check.check_artifact_nonempty`'s JSON
    rules: must parse, must not be ``{}`` / ``[]`` / ``null`` /
    whitespace-only, must not be an empty container after parse.
    """
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    stripped = text.strip()
    if stripped in ("", "{}", "[]", "null"):
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


def maybe_execute_specialist_script(workspace: Path, specialist: str) -> ExecutionAttempt:
    """Execute the specialist's declared script if it exists and the
    sidecar isn't already populated.

    Returns an ``ExecutionAttempt`` recording what happened. Never
    raises — every error path returns a populated record so the
    caller can log it without try/except.
    """
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

    script_path = workspace / convention.script
    sidecar_path = workspace / convention.sidecar

    if not script_path.is_file():
        return ExecutionAttempt(
            specialist=specialist,
            script=convention.script,
            ran=False,
            returncode=None,
            populated_sidecar=_is_sidecar_populated(sidecar_path),
            reason=f"{convention.script} not present in workspace",
        )

    if _is_sidecar_populated(sidecar_path):
        # The specialist did the right thing. Nothing to do.
        return ExecutionAttempt(
            specialist=specialist,
            script=convention.script,
            ran=False,
            returncode=None,
            populated_sidecar=True,
            reason="sidecar already populated by specialist",
        )

    logger.info(
        "post-specialist exec: %s sidecar empty — running %s (timeout=%ds)",
        specialist,
        convention.script,
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
        # TimeoutExpired.stdout/stderr are typed bytes | str (depend on
        # whether the call passed text=True — we did, but the type stub
        # still widens). Coerce to str for the log writer.
        rc = None
        raw_out: object = e.stdout or ""
        raw_err: object = e.stderr or ""
        stdout = raw_out.decode("utf-8", errors="replace") if isinstance(raw_out, bytes) else str(raw_out)
        stderr = raw_err.decode("utf-8", errors="replace") if isinstance(raw_err, bytes) else str(raw_err)
        stderr = stderr + f"\n[TIMEOUT after {convention.timeout_seconds}s]"
        logger.warning("post-specialist exec: %s timed out after %ds", convention.script, convention.timeout_seconds)
    except Exception as e:  # noqa: BLE001 — defensive, log + record
        logger.warning("post-specialist exec: %s failed: %s", convention.script, e)
        return ExecutionAttempt(
            specialist=specialist,
            script=convention.script,
            ran=False,
            returncode=None,
            populated_sidecar=False,
            reason=f"subprocess launch failed: {e!r}",
        )

    # Always write the audit log, even on non-zero exit. The next
    # reviewer (or the M4.3 error message) points here.
    log_path = workspace / convention.log
    try:
        log_path.write_text(
            f"# post-specialist exec for {specialist}\n"
            f"# script: {convention.script}\n"
            f"# returncode: {rc}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}\n",
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("post-specialist exec: could not write %s: %s", convention.log, e)

    populated = _is_sidecar_populated(sidecar_path)
    if rc == 0 and populated:
        logger.info("post-specialist exec: %s succeeded; %s populated", convention.script, convention.sidecar)
        reason = "script executed; sidecar populated"
    elif rc == 0 and not populated:
        logger.warning("post-specialist exec: %s exited 0 but %s still empty", convention.script, convention.sidecar)
        reason = "script exited 0 but sidecar not populated"
    else:
        logger.warning("post-specialist exec: %s exited %s", convention.script, rc)
        reason = f"script exited with code {rc}"

    return ExecutionAttempt(
        specialist=specialist,
        script=convention.script,
        ran=True,
        returncode=rc,
        populated_sidecar=populated,
        reason=reason,
    )
