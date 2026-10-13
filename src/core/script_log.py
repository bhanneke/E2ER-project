"""The workspace's script log: every script run by ``e2er-run`` and by the runner.

Standard library only, so ``e2er-run`` records its runs with any Python that
can run the study's script.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: The workspace's record of every script run (by `e2er-run` and by the runner), one JSON line each:
#: ``{script, sha256, started_at, exit_code, by, python, packages}``. Export reads it to rerun the scripts in
#: the order the run ran them (reproduce.json) and to pin the packages they loaded. A dotfile:
#: internal, never exported.
SCRIPT_RUNS = ".e2er-script-runs.jsonl"

#: Where the bootstrap writes the packages the script loaded (a file outside the workspace).
PACKAGES_ENV = "E2ER_PACKAGES_OUT"

#: Runs the script as ``python script.py`` would (``__main__``, ``sys.argv``, ``sys.path[0]``) and,
#: when the interpreter exits, writes its Python version and ``{distribution: version}`` of every
#: installed package a module of which was loaded (``sys.modules``), so a pandas script that read
#: Excel records openpyxl.
#: Standard library only: it runs in whatever Python runs the study's script.
BOOTSTRAP = r"""
import sys
def _e2er_packages():
    import json, os
    out = os.environ.get("E2ER_PACKAGES_OUT")
    if not out:
        return
    try:
        import importlib.metadata as md
        dists = md.packages_distributions()
        std = set(getattr(sys, "stdlib_module_names", ()))
        found = {}
        for top in {m.split(".")[0] for m in list(sys.modules)}:
            if top in std or top.startswith("_"):
                continue
            for name in dists.get(top) or ():
                try:
                    found[name] = md.version(name)
                except Exception:
                    pass
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"python": sys.version.split()[0], "packages": found}, f)
    except Exception:
        pass
import atexit, os, types
atexit.register(_e2er_packages)
del sys.argv[0]
_path = sys.argv[0]
sys.path[0] = os.path.dirname(os.path.abspath(_path))
_main = types.ModuleType("__main__")
_main.__file__ = _path
_main.__builtins__ = __builtins__
sys.modules["__main__"] = _main
with open(_path, "rb") as _f:
    _code = compile(_f.read(), _path, "exec")
del _f, _path
exec(_code, _main.__dict__)
"""


def script_command(python: str, script: str | Path) -> tuple[list[str], dict[str, str], Path]:
    """(argv, extra environment, packages file) that run ``script`` and record the packages it loaded.

    Pass the argv to ``subprocess.run`` with the extra environment, then :func:`script_record`
    on the packages file once the script has exited.
    """
    fd, name = tempfile.mkstemp(prefix="e2er-packages-", suffix=".json")
    os.close(fd)
    os.unlink(name)  # written by the script's interpreter only when it exits
    return [python, "-c", BOOTSTRAP, str(script)], {PACKAGES_ENV: name}, Path(name)


def script_record(path: Path) -> dict[str, object] | None:
    """What the script's interpreter recorded at exit, ``{"python", "packages"}`` (and remove the file).

    None when it wrote nothing (killed at the time limit, or it never started).
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        Path(path).unlink(missing_ok=True)
    if not isinstance(data, dict) or not isinstance(data.get("packages"), dict):
        return None
    out: dict[str, object] = {
        "packages": {str(k): str(v) for k, v in data["packages"].items() if isinstance(v, str)},
    }
    if isinstance(data.get("python"), str):
        out["python"] = data["python"]
    return out


def record_script_run(
    workspace: Path,
    rel: str,
    started_at: str,
    exit_code: int,
    *,
    by: str,
    record: dict[str, object] | None = None,
) -> None:
    """Append one run to the workspace's script log; never raises."""
    try:
        sha = hashlib.sha256((Path(workspace) / rel).read_bytes()).hexdigest()
        line: dict[str, object] = {
            "script": rel,
            "sha256": sha,
            "started_at": started_at,
            "exit_code": exit_code,
            "by": by,
        }
        if record:  # the interpreter's Python version and the packages the script loaded
            if isinstance(record.get("python"), str):
                line["python"] = record["python"]
            packages = record.get("packages")
            if isinstance(packages, dict):
                line["packages"] = dict(sorted(packages.items()))
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
