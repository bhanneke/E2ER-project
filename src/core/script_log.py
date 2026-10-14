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
#: ``{script, sha256, started_at, exit_code, by, python, packages, outputs}``; ``outputs`` maps every
#: result-type file the run wrote (:data:`OUTPUT_SUFFIXES`) to its SHA-256 after the run, so a results
#: file can be traced to the run of the script that wrote it (:func:`results_writer`). Export reads it
#: to rerun the scripts in the order the run ran them (reproduce.json) and to pin the packages they
#: loaded. A dotfile: internal, never exported.
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


#: Files a script run may write that the log fingerprints (results, tables of numbers).
OUTPUT_SUFFIXES = frozenset({".json", ".csv", ".tsv"})
#: Folders never searched for outputs (environments, caches, e2er's own run folders).
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", "node_modules", "sandbox", "literature"})
#: A file larger than this is not fingerprinted (a data export, not a results file).
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024

#: (modification time in ns, size) of each candidate output, by workspace-relative path.
Snapshot = dict[str, tuple[int, int]]


def _candidates(workspace: Path) -> list[Path]:
    """Result-type files in the workspace and one folder down (dotfiles and environments left out)."""
    out: list[Path] = []
    try:
        top = list(Path(workspace).iterdir())
    except OSError:
        return out
    for p in top:
        if p.name.startswith("."):
            continue
        if p.is_dir():
            if p.name in _SKIP_DIRS:
                continue
            try:
                out.extend(c for c in p.iterdir() if not c.name.startswith(".") and c.suffix.lower() in OUTPUT_SUFFIXES)
            except OSError:
                continue
        elif p.suffix.lower() in OUTPUT_SUFFIXES:
            out.append(p)
    return out


def output_snapshot(workspace: Path) -> Snapshot:
    """The candidate outputs as they are before a script runs (pass it to :func:`record_script_run`)."""
    snap: Snapshot = {}
    for p in _candidates(workspace):
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            snap[p.relative_to(workspace).as_posix()] = (st.st_mtime_ns, st.st_size)
    return snap


def written_outputs(workspace: Path, before: Snapshot) -> dict[str, str]:
    """{path: SHA-256} of the candidate outputs created or rewritten since ``before``."""
    out: dict[str, str] = {}
    for p in _candidates(workspace):
        try:
            st = p.stat()
            if not p.is_file() or st.st_size > _MAX_OUTPUT_BYTES:
                continue
            rel = p.relative_to(workspace).as_posix()
            if before.get(rel) == (st.st_mtime_ns, st.st_size):
                continue
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return dict(sorted(out.items()))


def record_script_run(
    workspace: Path,
    rel: str,
    started_at: str,
    exit_code: int,
    *,
    by: str,
    record: dict[str, object] | None = None,
    before: Snapshot | None = None,
) -> None:
    """Append one run to the workspace's script log; never raises.

    With ``before`` (:func:`output_snapshot` taken before the script ran) the line
    also records the files the run wrote, each with its SHA-256 (``outputs``).
    """
    try:
        sha = hashlib.sha256((Path(workspace) / rel).read_bytes()).hexdigest()
        line: dict[str, object] = {
            "script": rel,
            "sha256": sha,
            "started_at": started_at,
            "exit_code": exit_code,
            "by": by,
        }
        if before is not None:
            line["outputs"] = written_outputs(Path(workspace), before)
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


def _file_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def records_outputs(runs: list[dict]) -> bool:
    """Whether the log records the files its runs wrote (after e2er 0.16.0); older logs do not."""
    return any(isinstance(r.get("outputs"), dict) for r in runs)


def results_writer(workspace: Path, rel: str, runs: list[dict] | None = None) -> dict | None:
    """The last recorded run that wrote ``rel`` (any exit code), or None."""
    runs = read_script_runs(workspace) if runs is None else runs
    for row in reversed(runs):
        outputs = row.get("outputs")
        if isinstance(outputs, dict) and rel in outputs:
            return row
    return None


#: Outcomes of :func:`results_from_code`.
FROM_CODE = "from_code"
NOT_FROM_CODE = "not_from_code"
NOT_RECORDED = "not_recorded"


def results_from_code(workspace: Path, rel: str) -> tuple[str, str, dict | None]:
    """Was ``rel`` written, as it is now, by the last run of a script the study ships unchanged?

    (outcome, plain reason, the writing run): :data:`FROM_CODE` when the file's
    SHA-256 is the one the last run that wrote it recorded, that run succeeded
    and its script is still the one that ran; :data:`NOT_RECORDED` when the log
    records no run at all, or no run with an output record wrote it but the log
    has runs from before e2er recorded outputs (nothing can be said); else
    :data:`NOT_FROM_CODE` with the reason.
    """
    workspace = Path(workspace)
    runs = read_script_runs(workspace)
    current = _file_sha(workspace / rel)
    if current is None:
        return NOT_FROM_CODE, f"{rel} is missing", None
    if not runs:
        # Nothing ran through the log yet (a CLI that ran `python script.py` itself, or files written
        # outside a run): the runner's rerun after the specialist (post_execution) makes the record.
        return NOT_RECORDED, f"the script log ({SCRIPT_RUNS}) records no run", None
    writer = results_writer(workspace, rel, runs)
    if writer is None:
        if any(not isinstance(r.get("outputs"), dict) for r in runs):
            # Runs from before e2er recorded output files (a study resumed after an update): one of them may
            # have written it, and nothing can be said.
            return NOT_RECORDED, f"the script log ({SCRIPT_RUNS}) has runs that record no output files", None
        return NOT_FROM_CODE, f"no recorded run of the study's scripts wrote {rel}", None
    script = str(writer.get("script"))
    if writer["outputs"].get(rel) != current:
        return NOT_FROM_CODE, f"{rel} changed after {script} last wrote it", writer
    if writer.get("exit_code") != 0:
        return (
            NOT_FROM_CODE,
            f"{rel} was written by a run of {script} that failed (exit {writer.get('exit_code')})",
            writer,
        )
    if _file_sha(workspace / script) != writer.get("sha256"):
        return NOT_FROM_CODE, f"{script} changed after the run that wrote {rel}", writer
    return FROM_CODE, f"written by {script} (run {writer.get('started_at', '?')})", writer
