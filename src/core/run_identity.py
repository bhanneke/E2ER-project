"""Identity of the process that produced a run.

Answers one question after the fact: *which code produced this result?*

That question has already been answered wrongly once. The API server runs
without ``--reload``, so a live server executes the code it imported at boot —
edit the tree, and the server keeps running the old code while `git log` in the
same directory advertises the new. A canary was measured against pre-fix code
that way on 2026-08-20, and nothing in the run record contradicted it.

The fix is to capture identity **once, from the running process**, and cache it:

* Captured at process start (the API startup hook calls :func:`run_identity`),
  so the SHA is the one that was checked out when this interpreter loaded its
  modules — not whatever the tree drifted to afterwards.
* Cached for the process lifetime. If someone commits while the server runs,
  the stamp keeps saying what this process is running, which is the true and
  useful answer.
* Includes ``source_root`` and ``git_dirty``. A SHA alone is a claim about a
  clean tree at a known path; without both, it is not checkable.

A client-side stamp cannot do this job — the driver would record the tree's
current SHA regardless of what the server loaded, which is exactly the
misleading measurement this exists to prevent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

# The repo root as seen from THIS file: src/core/run_identity.py -> ../../
_SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent


def _git(*args: str) -> str | None:
    """Run a git command in the source tree. None if git/the repo is unavailable
    (a pip-installed copy has no .git, and that is not an error)."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_SOURCE_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("run_identity: git %s unavailable: %s", " ".join(args), e)
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("e2er")
    except Exception:  # noqa: BLE001 — an uninstalled source checkout is normal
        return "unknown"


@lru_cache(maxsize=1)
def run_identity() -> dict[str, Any]:
    """Identity of this process, captured once and cached.

    Never raises: an unidentifiable run should still run, it just records
    ``None``/``"unknown"`` and says so. Losing the stamp must not lose the run.
    """
    sha = _git("rev-parse", "HEAD")
    # --porcelain is empty exactly when the tree matches the SHA. Anything else
    # means the SHA does not fully describe the code that is loaded.
    status = _git("status", "--porcelain")

    identity: dict[str, Any] = {
        "git_sha": sha,
        "git_short_sha": sha[:7] if sha else None,
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        # None (not False) when git could not be consulted — "clean" and
        # "unknown" are different claims and must not collapse.
        "git_dirty": (bool(status) if status is not None else None),
        "source_root": str(_SOURCE_ROOT),
        "package_version": _package_version(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "pid": os.getpid(),
        "captured_at": datetime.now(UTC).isoformat(),
    }

    # Process-level settings. Per-paper backend/model/governance are recorded on
    # the paper row; these are the process defaults and the concurrency that
    # actually shaped dispatch, which lives nowhere else.
    try:
        from ..config import get_settings

        s = get_settings()
        identity.update(
            {
                "backend": s.llm_backend,
                "model": s.default_model,
                "max_concurrent_specialists": s.max_concurrent_specialists,
            }
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("run_identity: settings unavailable: %s", e)
        identity.update({"backend": None, "model": None, "max_concurrent_specialists": None})

    return identity


def identity_summary() -> str:
    """One-line human form, for logs."""
    i = run_identity()
    sha = i.get("git_short_sha") or "unknown-sha"
    dirty = i.get("git_dirty")
    mark = "+dirty" if dirty else ("" if dirty is False else "+unknown")
    return (
        f"{sha}{mark} on {i.get('git_branch') or '?'} | "
        f"py{i.get('python_version')} @ {i.get('python_executable')} | "
        f"backend={i.get('backend')} model={i.get('model')} "
        f"concurrency={i.get('max_concurrent_specialists')}"
    )
