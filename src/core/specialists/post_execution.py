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
``docs/internal/M4_DIAGNOSIS.md``.

The M4.3 contract check catches the empty sidecar at the boundary and
flips the specialist to ``success=False``. That's the negative path:
*refuse the wrong thing*. This module is the positive path — *make the
right thing happen* — by having the runner shell out and execute the
script itself.

Why this exists at the runner level (not the skill file): the model
genuinely cannot execute code, so a skill instruction "run your script"
would be unactionable. Execution has to happen here.

Robustness (the M5 re-run lesson, ``docs/internal/M4_RERUN_FINDINGS.md``): the
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
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


# The script log (one implementation for e2er-run and the runner): src/core/script_log.py.
from ..script_log import (  # noqa: E402,F401
    SCRIPT_RUNS,
    confirm_output,
    output_snapshot,
    read_script_runs,
    record_script_run,
    script_command,
    script_record,
)


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
    # Another specialist's scripts are never run on this one's behalf: the
    # 2026-09-28 event study had the data analyst's `run_estimation.py` (which
    # wrote summary_statistics.json among its results) discovered here and
    # executed, so estimates existed before the pre-registration was frozen.
    foreign = _foreign_scripts(convention)
    matches: list[Path] = []
    for py in workspace.glob("*.py"):
        if py.name in foreign:
            continue
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


def _foreign_scripts(convention: ExecutionConvention) -> frozenset[str]:
    """Script names that belong to another specialist's convention."""
    return frozenset(
        name for other in EXECUTION_CONVENTIONS.values() if other is not convention for name in other.script_candidates
    )


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
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Through the script log's bootstrap, which records the packages the script loaded (reproduce.json pins them).
    argv, extra, packages_file = script_command(sys.executable, script_path)
    before = output_snapshot(workspace)  # the script log records what the run wrote
    try:
        completed = subprocess.run(
            argv,
            cwd=str(workspace),
            # Plain tracebacks for the model that reads them (Python 3.13+ colours them under FORCE_COLOR).
            env={**os.environ, "PYTHON_COLORS": "0", **extra},
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
        script_record(packages_file)
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
    # Recorded after the copy: the sidecar it made is an output of this run.
    record_script_run(
        workspace,
        rel_script,
        started,
        -1 if rc is None else rc,
        by="runner",
        record=script_record(packages_file),
        before=before,
    )

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

    # A failed script must leave NO usable sidecar. `{}` on disk is worse than
    # nothing, because every `.exists()` check downstream passes and the hole
    # only surfaces later as unresolved table references — or, in the
    # 2026-08-05 cell, as four hand-written tables. Quarantine rather than
    # delete, so the evidence survives for the audit trail.
    if not populated and sidecar_path.exists():
        quarantine = sidecar_path.with_suffix(f".rejected{sidecar_path.suffix}")
        try:
            sidecar_path.replace(quarantine)
            logger.warning(
                "post-specialist exec: quarantined unpopulated %s -> %s",
                convention.sidecar,
                quarantine.name,
            )
            reason += f"; unpopulated sidecar quarantined as {quarantine.name}"
        except OSError as e:
            logger.warning("post-specialist exec: could not quarantine %s: %s", convention.sidecar, e)

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


_RC_RE = re.compile(r"^# returncode: (\S+)", re.MULTILINE)


def read_execution_error(workspace: Path, specialist: str) -> str | None:
    """Recover v1's self-debugging loop without giving the model a code tool.

    Specialists can't run their own code (sandboxed tool set), so the runner
    executes their script post-hoc. When that script CRASHES, the bug (a bad
    pandas/numpy idiom, etc.) is invisible to the model — it wrote the script
    blind. This reads the crash captured in the convention's audit log
    (``run_estimation.log``) so the runner can feed it back into the
    specialist's NEXT attempt, turning "write blind → crash → fail" into
    "write → see the traceback → fix → succeed".

    Returns a ready-to-inject prompt section, or ``None`` when there's nothing
    to feed back (no convention, sidecar already populated, no log, or the last
    run exited cleanly).
    """
    convention = EXECUTION_CONVENTIONS.get(specialist)
    if convention is None:
        return None
    workspace = Path(workspace).resolve()
    if _is_populated(workspace / convention.sidecar):
        return None  # the script already produced output — nothing to fix
    log_path = workspace / convention.log
    if not log_path.is_file():
        return None
    try:
        log = log_path.read_text(encoding="utf-8")
    except OSError:
        return None

    m = _RC_RE.search(log)
    if not m or m.group(1) == "0":
        # No recorded run, or it exited cleanly — an empty sidecar then isn't a
        # crash we can coach the model out of.
        return None
    rc = m.group(1)

    # The traceback lives in the stderr section; the tail is the informative part.
    stderr = log.split("--- stderr ---", 1)[-1].strip()
    tail = "\n".join(stderr.splitlines()[-30:]) if stderr else "(no stderr captured)"

    script_name = convention.script_candidates[0] if convention.script_candidates else "your script"

    return (
        "## Your previous script FAILED — fix it and rewrite\n"
        "You do not have a tool to run code yourself; the runner executes the script "
        f"you write (saved as `{script_name}`) and reports the result here. On the last "
        f"attempt the runner ran it and it **crashed (exit code {rc})**, so "
        f"`{convention.sidecar}` is still empty. Read the error below, fix the specific "
        "bug, and rewrite the script so it runs cleanly and writes a populated "
        f"`{convention.sidecar}`. Do not write `{{}}` — fix the code.\n\n"
        f"```\n{tail}\n```"
    )


# ── results come from the code ───────────────────────────────────────────────
#
# A specialist that can edit files can edit its results file after its script
# wrote it. A DeepSeek run on OpenRouter (2026-10-14, the earthquake demo) did:
# `estimation_results.json` was written at 02:01, the script last changed at
# 01:18, and a rerun of the shipped script gave 289 different values. Nothing
# noticed before `e2er reproduce`. The script log records the SHA-256 of every
# file each run wrote (script_log.results_from_code); a results file that is
# not the output of the last run of the script as shipped is run again here,
# and the contract check (contract_check.check_results_from_code) fails the
# specialist when the rerun does not write it.

#: Result files whose content must come from the study's own code, per specialist.
RESULTS_FROM_CODE: dict[str, tuple[str, ...]] = {
    "econometrics_specialist": ("estimation_results.json", "robustness_results.json"),
}

#: What the last confirming rerun found, read by the contract check for its feedback (internal).
RERUN_RECORD = ".e2er-results-rerun.json"


def results_files(workspace: Path, specialist: str) -> list[str]:
    """The specialist's result files that exist in the workspace."""
    return [n for n in RESULTS_FROM_CODE.get(specialist, ()) if (Path(workspace) / n).is_file()]


def _sha(path: Path) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def results_script(workspace: Path, specialist: str, rel: str) -> str | None:
    """The script that should write ``rel``: its last recorded writer if the study still has it, else the
    specialist's estimation script by its conventional name."""
    from ..script_log import results_writer

    workspace = Path(workspace)
    writer = results_writer(workspace, rel)
    if writer is not None and (workspace / str(writer.get("script"))).is_file():
        return str(writer["script"])
    convention = EXECUTION_CONVENTIONS.get(specialist)
    if convention is None:
        return None
    path, _ = _discover_script(workspace, convention)
    return path.name if path is not None else None


def rerun_chain(workspace: Path, specialist: str, pending: list[str]) -> list[str]:
    """The scripts to run again for the pending results files, in order.

    For the estimation results the chain `e2er reproduce` runs (the order the
    script log recorded, else file times: the estimation script and the later
    scripts that write the results again); a further results file's recorded
    writer is added when the chain does not have it.
    """
    from ..export.reproduce_recipe import RESULTS, chain_of

    workspace = Path(workspace)
    names: list[str] = []
    if RESULTS in pending or not pending:
        names = [p.name for p in chain_of(workspace).scripts]
    for n in pending:
        script = results_script(workspace, specialist, n)
        if script and script not in names:
            names.append(script)
    return names


def confirm_results_from_code(workspace: Path, specialist: str) -> dict[str, dict]:
    """Run the shipped script again when a results file is not the recorded output of its last run.

    A file that the rerun writes with the same values (identical, or the same at
    the precision the file holds) is from the code: the rerun's output stays and
    is recorded. Otherwise the file is put back as the specialist left it and
    what the rerun found is kept in :data:`RERUN_RECORD`, for the contract
    check's feedback. Returns that record ({file: {...}}); empty when nothing
    needed a rerun. Never raises.
    """
    from ..script_log import FROM_CODE, results_from_code

    workspace = Path(workspace).resolve()
    record: dict[str, dict] = {}
    try:
        pending = [n for n in results_files(workspace, specialist) if results_from_code(workspace, n)[0] != FROM_CODE]
        if not pending:
            return record
        scripts = rerun_chain(workspace, specialist, pending)
        if not scripts:
            return record  # no script at all: the contract check says so
        script = " then ".join(scripts)
        originals = {n: (workspace / n).read_bytes() for n in pending}
        logger.info(
            "results check: %s %s not traced to the last run of the study's code — running %s again",
            ", ".join(pending),
            "are" if len(pending) > 1 else "is",
            script,
        )
        convention = EXECUTION_CONVENTIONS.get(specialist)
        timeout = convention.timeout_seconds if convention else 600
        n_runs = len(read_script_runs(workspace))
        rc: int | None = 0
        for name in scripts:  # in the order the run ran them; stop at the first that fails
            rc = _run_recorded(workspace, workspace / name, timeout, by="runner (results check)")
            if rc != 0:
                break
        from ..reproduce import compare_json

        wrote: set[str] = set()
        for row in read_script_runs(workspace)[n_runs:]:
            wrote.update((row.get("outputs") or {}).keys())
        for n in pending:
            new = workspace / n
            entry: dict = {"script": script, "exit_code": rc, "sha256": _sha_bytes(originals[n])}
            if rc == 0 and n in wrote and new.is_file():
                tmp = workspace / f".e2er-results-before-{n}"
                tmp.write_bytes(originals[n])
                try:
                    fc = compare_json(tmp, new, n, n)
                finally:
                    tmp.unlink(missing_ok=True)
                differ = _values_that_differ(fc)
                entry["values"] = fc.total
                entry["differ"] = differ
                if fc.problem is None and differ == 0:
                    # The script writes these values (a platform's last float digits aside): the file stays
                    # as the specialist's run left it, and the log records that the rerun confirmed it.
                    new.write_bytes(originals[n])
                    confirm_output(workspace, n, _sha_bytes(originals[n]))
                    entry["same"] = True
                    record[n] = entry
                    continue
            elif rc == 0:
                entry["not_written"] = True
            entry["same"] = False
            new.write_bytes(originals[n])  # as the specialist left it; the contract check reports it
            record[n] = entry
        (workspace / RERUN_RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — a check that cannot run must not break the step
        logger.warning("results check: could not run the script again: %s", e)
    return record


#: Two values agree when their relative difference is at most this: the last digits of a float differ between
#: platforms' numerical libraries (CI on Linux and macOS), never a value someone wrote by hand.
FLOAT_NOISE = 1e-9


def _values_that_differ(fc: Any) -> int:
    """Values of a rerun comparison that do not agree: identical, the same at the file's precision, or within
    float noise of each other agree; a missing, new, changed or text value does not."""
    from ..reproduce import MATCHING, MINOR

    noise = sum(1 for rel, *_rest in fc.differences if rel is not None and rel <= FLOAT_NOISE)
    bad = sum(n for label, n in fc.counts.items() if label not in MATCHING and label != MINOR)
    minor = fc.counts.get(MINOR, 0)
    return bad + max(minor - noise, 0)


def _sha_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _run_recorded(workspace: Path, script_path: Path, timeout: int, *, by: str) -> int | None:
    """Run a workspace script through the script log (packages and outputs recorded); its exit code."""
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    argv, extra, packages_file = script_command(sys.executable, script_path)
    before = output_snapshot(workspace)
    try:
        rc: int | None = subprocess.run(
            argv,
            cwd=str(workspace),
            env={**os.environ, "PYTHON_COLORS": "0", **extra},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        rc = None
    except OSError as e:
        script_record(packages_file)
        logger.warning("results check: %s could not start: %s", script_path.name, e)
        return None
    record_script_run(
        workspace,
        script_path.relative_to(workspace).as_posix(),
        started,
        -1 if rc is None else rc,
        by=by,
        record=script_record(packages_file),
        before=before,
    )
    return rc
