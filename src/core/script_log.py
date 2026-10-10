"""The workspace's script log: every script run by ``e2er-run`` and by the runner.

Standard library only, so ``e2er-run`` records its runs with any Python that
can run the study's script.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: The workspace's record of every script run (by `e2er-run` and by the runner), one JSON line each:
#: ``{script, sha256, started_at, exit_code, by}``. Export reads it to rerun the scripts in the
#: order the run ran them (reproduce.json). A dotfile: internal, never exported.
SCRIPT_RUNS = ".e2er-script-runs.jsonl"


def record_script_run(workspace: Path, rel: str, started_at: str, exit_code: int, *, by: str) -> None:
    """Append one run to the workspace's script log; never raises."""
    try:
        sha = hashlib.sha256((Path(workspace) / rel).read_bytes()).hexdigest()
        line = {"script": rel, "sha256": sha, "started_at": started_at, "exit_code": exit_code, "by": by}
        with open(Path(workspace) / SCRIPT_RUNS, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError as e:
        logger.warning("script log: %s not recorded: %s", rel, e)


def read_script_runs(workspace: Path) -> list[dict]:
    """The recorded script runs, in the order they ran (unreadable lines are skipped)."""
    out: list[dict] = []
    try:
        lines = (Path(workspace) / SCRIPT_RUNS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("script"), str):
            out.append(row)
    return out
