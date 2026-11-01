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


def _e2er_version() -> str:
    try:
        from .. import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


#: The workspace's record of every script run (by `e2er-run` and by the runner), one JSON line each:
#: ``{script, sha256, started_at, exit_code, by, e2er_version, python, packages, outputs, outputs_unhashed,
#: tables}``; ``e2er_version`` is the e2er that ran it (logs since 0.18.0); ``outputs_unhashed`` lists the
#: files it wrote that were too large to fingerprint; ``tables`` names the tables of data.db the run created,
#: changed or dropped (:func:`written_tables`); ``outputs`` maps every result-type file the run wrote
#: (:data:`OUTPUT_SUFFIXES`) to its SHA-256 after the run, so a results
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


#: Files a script run may write that the log records: results and tables of numbers, and every file that can
#: hold data (derived_data.OUTPUT_SUFFIXES, copied here: this module is standard library only). A script that
#: read a source with terms and wrote ``results/regions.gpkg`` or a parquet file went unrecorded, so the data
#: terms check never saw the file (review of 2026-10-23).
OUTPUT_SUFFIXES = frozenset(
    {
        ".json",
        ".csv",
        ".tsv",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".parquet",
        ".xlsx",
        ".jsonl",
        ".dta",
        ".geojson",
        ".txt",
        ".dat",
        ".npy",
        ".npz",
        ".pkl",
        ".pickle",
        ".feather",
        ".arrow",
        ".h5",
        ".hdf5",
        ".xls",
        ".ods",
        ".gpkg",
        ".shp",
        ".nc",
        ".rds",
        ".rdata",
        ".sav",
        ".joblib",
    }
)
#: Folders never searched for outputs (environments, caches, e2er's own run folders).
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", "node_modules", "sandbox", "literature"})
#: A file larger than this is not fingerprinted (a data export, not a results file); its path is still
#: recorded (``outputs_unhashed``).
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
#: Files of the study's database: its tables are recorded instead (``tables``).
_DATABASE_FILES = frozenset({"data.db", "data.db-wal", "data.db-shm", "data.db-journal"})

#: The study's database, whose tables a run may write (``df.to_sql(name, ...)`` with a name the code computes).
DATABASE = "data.db"
#: e2er's record of the tables of data.db as they were when it last looked: ``{"stat": [...], "tables":
#: {table: digest}}``, so a run's "before" costs nothing when the database has not changed since. A dotfile:
#: internal, never exported.
DB_TABLES_CACHE = ".e2er-db-tables.json"
#: A database larger than this gets a cheap digest per table (its definition, row count and last rowid)
#: instead of one over every row: the record then misses a table rewritten with the same number of rows.
_MAX_DB_DIGEST_BYTES = 2 * 1024 * 1024 * 1024


class Snapshot(dict[str, tuple[int, int]]):
    """(modification time in ns, size) of each candidate output, by workspace-relative path; and the tables of
    the study's database (``db``: table -> digest, None without a database) as they were before the run."""

    db: dict[str, str] | None = None


def _candidates(workspace: Path) -> list[Path]:
    """Result-type files in the workspace and one folder down (dotfiles and environments left out)."""
    out: list[Path] = []
    try:
        top = list(Path(workspace).iterdir())
    except OSError:
        return out
    for p in top:
        if p.name.startswith(".") or p.name in _DATABASE_FILES:
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


def _db_stat(workspace: Path) -> list[int] | None:
    """What changes when the database changes: size and time of data.db and of its write-ahead log."""
    out: list[int] = []
    for name in (DATABASE, DATABASE + "-wal"):
        try:
            st = (Path(workspace) / name).stat()
        except OSError:
            if name == DATABASE:
                return None
            out += [0, 0]
            continue
        out += [st.st_mtime_ns, st.st_size]
    return out


def table_digests(db: Path) -> dict[str, str] | None:
    """{table: digest of its definition and rows} of a SQLite database; None when it cannot be read.

    A digest changes when the table is written: rows added, changed or removed, or the table replaced
    (``to_sql(if_exists="replace")``). Standard library only.
    """
    import sqlite3

    try:
        big = Path(db).stat().st_size > _MAX_DB_DIGEST_BYTES
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except (OSError, sqlite3.Error):
        return None
    try:
        out: dict[str, str] = {}
        rows = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        for name, sql in rows:
            if str(name).startswith("sqlite_"):
                continue
            q = '"' + str(name).replace('"', '""') + '"'
            h = hashlib.sha256(str(sql).encode("utf-8"))
            if big:
                h.update(repr(con.execute(f"SELECT COUNT(*), MAX(rowid) FROM {q}").fetchone()).encode())
            else:
                for row in con.execute(f"SELECT * FROM {q}"):
                    h.update(repr(row).encode("utf-8", "replace"))
            out[str(name)] = h.hexdigest()
        return out
    except sqlite3.Error:
        return None
    finally:
        con.close()


def db_tables_now(workspace: Path) -> dict[str, str] | None:
    """The tables of the workspace's data.db (table -> digest), from e2er's record when the database has not
    changed since it was made; None without a readable database."""
    workspace = Path(workspace)
    stat = _db_stat(workspace)
    if stat is None:
        return None
    cache = workspace / DB_TABLES_CACHE
    try:
        doc = json.loads(cache.read_text(encoding="utf-8"))
        if doc.get("stat") == stat and isinstance(doc.get("tables"), dict):
            return {str(k): str(v) for k, v in doc["tables"].items()}
    except (OSError, ValueError, AttributeError):
        pass
    tables = table_digests(workspace / DATABASE)
    if tables is not None and _db_stat(workspace) == stat:
        try:
            cache.write_text(json.dumps({"stat": stat, "tables": tables}), encoding="utf-8", newline="\n")
        except OSError:
            pass
    return tables


def written_tables(workspace: Path, before: dict[str, str] | None) -> dict[str, list[str]] | None:
    """{"written": [...], "dropped": [...]}: the tables of data.db a run created or changed, and removed.

    None when the database is unchanged (or absent before and after).
    """
    after = db_tables_now(workspace)
    if after is None and before is None:
        return None
    before = before or {}
    after = after or {}
    written = sorted(t for t, d in after.items() if before.get(t) != d)
    dropped = sorted(t for t in before if t not in after)
    if not written and not dropped:
        return None
    return {"written": written, "dropped": dropped}


def output_snapshot(workspace: Path) -> Snapshot:
    """The candidate outputs, and the tables of data.db, as they are before a script runs (pass it to
    :func:`record_script_run`)."""
    snap = Snapshot()
    snap.db = db_tables_now(workspace)
    for p in _candidates(workspace):
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            snap[p.relative_to(workspace).as_posix()] = (st.st_mtime_ns, st.st_size)
    return snap


def written_outputs(workspace: Path, before: Snapshot, unhashed: list[str] | None = None) -> dict[str, str]:
    """{path: SHA-256} of the candidate outputs created or rewritten since ``before``.

    A file too large to fingerprint (over 64 MB) is not in the answer; its path is appended to ``unhashed``,
    so the log still says the run wrote it (a parquet export of a source with terms is data all the same).
    """
    out: dict[str, str] = {}
    for p in _candidates(workspace):
        try:
            st = p.stat()
            if not p.is_file():
                continue
            rel = p.relative_to(workspace).as_posix()
            if before.get(rel) == (st.st_mtime_ns, st.st_size):
                continue
            if st.st_size > _MAX_OUTPUT_BYTES:
                if unhashed is not None:
                    unhashed.append(rel)
                continue
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    if unhashed is not None:
        unhashed.sort()
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
    also records the files the run wrote, each with its SHA-256 (``outputs``), and the tables of
    data.db it created, changed or removed (``tables``: ``{"written": [...], "dropped": [...]}``),
    found by comparing the tables before and after the run, so a table the code names with a
    variable (``t.to_sql(name, con)``) is traced to its script too.
    """
    try:
        sha = hashlib.sha256((Path(workspace) / rel).read_bytes()).hexdigest()
        line: dict[str, object] = {
            "script": rel,
            "sha256": sha,
            "started_at": started_at,
            "exit_code": exit_code,
            "by": by,
            "e2er_version": _e2er_version(),
        }
        if before is not None:
            unhashed: list[str] = []
            line["outputs"] = written_outputs(Path(workspace), before, unhashed)
            if unhashed:
                # Written but too large to fingerprint: the path counts for the data terms (derived_data.py).
                line["outputs_unhashed"] = unhashed
            tables = written_tables(Path(workspace), before.db) if isinstance(before, Snapshot) else None
            if tables is not None:
                line["tables"] = tables
        if record:  # the interpreter's Python version and the packages the script loaded
            if isinstance(record.get("python"), str):
                line["python"] = record["python"]
            packages = record.get("packages")
            if isinstance(packages, dict):
                line["packages"] = dict(sorted(packages.items()))
        with open(Path(workspace) / SCRIPT_RUNS, "a", encoding="utf-8", newline="\n") as f:
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


def confirm_output(workspace: Path, rel: str, sha: str) -> None:
    """The last run that wrote ``rel`` wrote the same values as the file with SHA-256 ``sha``: record that file.

    A rerun on another platform writes the last digits of some floats differently; the study keeps its own
    file, and the run's line says which bytes the rerun wrote (``confirmed``). Never raises.
    """
    path = Path(workspace) / SCRIPT_RUNS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in range(len(lines) - 1, -1, -1):
            try:
                row = json.loads(lines[i])
            except ValueError:
                continue
            outputs = row.get("outputs") if isinstance(row, dict) else None
            if isinstance(outputs, dict) and rel in outputs:
                row.setdefault("confirmed", {})[rel] = {"same_values_as": sha, "rerun_wrote": outputs[rel]}
                outputs[rel] = sha
                lines[i] = json.dumps(row)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
                return
    except OSError as e:
        logger.warning("script log: %s not confirmed: %s", rel, e)


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


#: The reason :func:`results_from_code` gives for a log from before output records (e2er up to 0.16.0).
PREDATES = "the run predates output records"

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
            return NOT_RECORDED, PREDATES, None
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
