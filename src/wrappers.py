"""The commands specialists run by name: ``e2er-run``, ``e2er-lit``, ``e2er-check-tables``, ``e2er-allium-query``.

They are console entry points of the package (``pyproject.toml``), so an
installed e2er (``pip install``, ``uv tool install``) has them on the PATH the
backends give a specialist (``cli_support.wrapper_path``: the environment's
scripts folder). The ``scripts/e2er-*`` files of a source checkout only call
these functions, so there is one implementation. ``e2er-data`` and
``e2er-fieldmap`` are entry points of their own modules.

Each runs in the specialist's current folder, which is the study's workspace.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

#: Exit codes of e2er-run: a refused call, and a script stopped at the time limit (as coreutils `timeout`).
REFUSED = 2
TIMED_OUT = 124


def _refuse(message: str) -> int:
    print(f"e2er-run: {message}", file=sys.stderr)
    return REFUSED


def run_main(argv: list[str] | None = None) -> int:
    """``e2er-run <script.py>``: run one workspace-relative Python file, with a time limit, and record the run.

    Guarantees (as the shell wrapper had them): exactly one ``.py`` file inside
    the current folder; no absolute path, no ``..``, no link out of the folder,
    no arguments for the script; a hard time limit (``E2ER_RUN_TIMEOUT``,
    default 600 s). The run is recorded in the workspace's script log
    (``.e2er-script-runs.jsonl``), which export reads for the order of
    ``reproduce.json``. The script's exit code is passed on.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: e2er-run <script.py>   (one workspace-relative path, no arguments)", file=sys.stderr)
        return REFUSED
    target = args[0]
    if target.startswith("/") or (len(target) > 1 and target[1] == ":"):
        return _refuse(f"absolute paths are not allowed: {target}")
    if ".." in target:
        return _refuse(f"'..' is not allowed in the path: {target}")
    if not target.endswith(".py"):
        return _refuse(f"only .py files may be run: {target}")
    workspace = Path.cwd().resolve()
    if not (workspace / target).parent.is_dir():
        return _refuse(f"no such directory for {target}")
    resolved = (workspace / target).resolve()
    if not resolved.is_relative_to(workspace) or resolved == workspace:
        return _refuse(f"refusing to run outside the workspace: {resolved}")
    if not resolved.is_file():
        return _refuse(f"not a regular file: {target}")
    try:
        timeout = float(os.environ.get("E2ER_RUN_TIMEOUT") or 600)
    except ValueError:
        timeout = 600.0
    python = os.environ.get("E2ER_PYTHON") or sys.executable
    print(f"e2er-run: executing {target} (timeout {timeout:.0f}s)", file=sys.stderr, flush=True)
    # Plain tracebacks: a model reads them (Python 3.13+ colours them under FORCE_COLOR).
    env = {**os.environ, "PYTHON_COLORS": "0"}
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        code = subprocess.run([python, str(resolved)], cwd=workspace, env=env, timeout=timeout, check=False).returncode
    except subprocess.TimeoutExpired:
        print(f"e2er-run: stopped {target} after {timeout:.0f}s", file=sys.stderr)
        code = TIMED_OUT
    except OSError as e:
        print(f"e2er-run: could not start {python}: {e}", file=sys.stderr)
        return REFUSED
    from .core.script_log import record_script_run

    record_script_run(workspace, resolved.relative_to(workspace).as_posix(), started, code, by="e2er-run")
    return code


def lit_main(argv: list[str] | None = None) -> int:
    """``e2er-lit``: the literature bridge, for the workspace it is called in."""
    os.environ["E2ER_WORKSPACE"] = str(Path.cwd().resolve())
    from .modules.literature.cli import main

    return main(argv)


def check_tables_main(argv: list[str] | None = None) -> int:
    """``e2er-check-tables``: render table_spec.json of the current workspace and report what does not resolve."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print(
            "e2er-check-tables: takes no arguments (checks table_spec.json in the current workspace)",
            file=sys.stderr,
        )
        return REFUSED
    from .core.renderer.check_tables import main

    return main([str(Path.cwd().resolve())])


def allium_query_main(argv: list[str] | None = None) -> int:
    """``e2er-allium-query``: the former name of ``e2er-data allium``."""
    from .modules.data.cli import main

    return main(["allium", *(sys.argv[1:] if argv is None else argv)])


_COMMANDS = {"run": run_main, "lit": lit_main, "check-tables": check_tables_main, "allium-query": allium_query_main}

if __name__ == "__main__":  # the scripts/ wrappers of a source checkout: python -m src.wrappers <command> …
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        print(f"usage: python -m src.wrappers {{{','.join(_COMMANDS)}}} …", file=sys.stderr)
        raise SystemExit(REFUSED)
    raise SystemExit(_COMMANDS[sys.argv[1]](sys.argv[2:]))
