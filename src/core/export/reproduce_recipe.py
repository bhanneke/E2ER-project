"""Write ``reproduce.json`` at export, from what the run recorded, so that ``e2er reproduce`` can run any study.

The recipe (format: ``src/core/reproduce.py``) is built without a model and
without running anything:

- **Steps.** The scripts that wrote ``estimation_results.json``: the estimation
  script the runner looks for (``run_estimation.py`` and the other names of
  ``post_execution``), then every script that writes the file and ran after it,
  in the order the run ran them (the workspace's script log, which ``e2er-run``
  and the runner write). Without that log (runs before 0.15.0) the order is the
  one the run last changed the files in, and the recipe says so.
  A specialist that revised the results with a second script (the FOMC study's
  ``revise_estimation.py`` and ``compute_h2_v2.py``) is followed that way.
- **Files and inputs.** Every workspace file a script names in a string
  (``'data.db'``, ``'data/panel.csv'``, the workspace's own full path) is laid
  out in the run folder where the script expects it. A data file is an input,
  listed with the SHA-256 of the run's copy and where it came from
  (``data_sources.json``).
- **Inputs the folder cannot ship.** Data under terms that do not allow passing
  them on (Yahoo Finance, the Global Macro Database) get a ``get_data.py`` that
  loads them again with ``e2er-data``, with the series and dates the run
  recorded, when the folder does not have them.
- **Environment.** ``code/requirements.txt`` pins the packages the scripts
  import, at the versions installed in the Python environment e2er runs in.
- **Compared.** ``results/estimation_results.json`` (and
  ``results/robustness_results.json`` when a script writes it); the tables are
  rendered again from the rerun's results when the study ships them.

A study without an estimation script or without estimation results gets no
recipe; :func:`write_recipe` returns the reason, which the README states.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

RESULTS = "estimation_results.json"
#: Other result files a script may write and the study publishes under results/.
OTHER_RESULTS = ("robustness_results.json",)
#: Files that are data: listed as inputs with their SHA-256.
DATA_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3", ".csv", ".tsv", ".parquet", ".xlsx", ".jsonl", ".dta"})
#: A file larger than this is not copied into the folder for the recipe (export's own limit).
MAX_INPUT_BYTES = 200 * 1024 * 1024
#: Where an exported copy of a workspace file is looked for first.
_PREFERRED = ("data/", "results/", "design/", "code/", "")
#: Yahoo Finance: its reloaded prices can differ (adjusted for every new dividend).
_YAHOO = "yfinance"


def _restricted() -> dict[str, Any]:
    """Sources whose terms do not let the study pass their data on, reloaded by get_data.py (by connector name)."""
    from ...modules.data.sources import all_sources

    return {s.name: s for s in all_sources() if not s.redistribution}


@dataclass
class Outcome:
    """What the writer did: the recipe it wrote, or why there is none."""

    recipe: dict[str, Any] | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


# ── what the run wrote ───────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _populated(path: Path) -> bool:
    from ..specialists.post_execution import _is_populated

    return _is_populated(path)


def _estimation_names() -> tuple[str, ...]:
    from ..specialists.post_execution import EXECUTION_CONVENTIONS

    return EXECUTION_CONVENTIONS["econometrics_specialist"].script_candidates


#: A script changed up to this long after the results were last written still counts as one that wrote them.
_SLACK_NS = 2_000_000_000


#: Where the order of the scripts came from.
ORDER_RECORDED = "script log"
ORDER_FILE_TIMES = "file times"
ORDER_SINGLE = "one script"


@dataclass
class Chain:
    """The scripts to rerun, in order, and where that order comes from."""

    scripts: list[Path]
    order: str
    notes: list[str] = field(default_factory=list)


def _writers(workspace: Path) -> tuple[list[Path], Path | None]:
    writers = sorted(p for p in workspace.glob("*.py") if p.is_file() and RESULTS in _read(p))
    canonical = next((workspace / n for n in _estimation_names() if (workspace / n).is_file()), None)
    return writers, canonical


def _recorded_chain(workspace: Path, writers: list[Path], canonical: Path | None) -> Chain | None:
    """The order the run ran the scripts in (the workspace's script log); None when it recorded none."""
    from ..specialists.post_execution import SCRIPT_RUNS, read_script_runs

    names = {p.name for p in writers} | ({canonical.name} if canonical else set())
    ok = [r for r in read_script_runs(workspace) if r.get("exit_code") == 0 and r["script"] in names]
    ok = [r for r in ok if (workspace / r["script"]).is_file()]
    if not ok:
        return None
    # From the last run of the estimation script on: what ran after it built the final results.
    first = max((i for i, r in enumerate(ok) if canonical and r["script"] == canonical.name), default=0)
    runs = ok[first:]
    seq: list[dict[str, Any]] = []
    for r in runs:
        if not seq or seq[-1]["script"] != r["script"]:
            seq.append(r)
    notes = []
    last_sha = {r["script"]: r.get("sha256") for r in runs}
    changed = [n for n, sha in last_sha.items() if sha and sha != _sha256(workspace / n)]
    if changed:
        notes.append(
            f"{', '.join(changed)} changed after the run last ran it (recorded in {SCRIPT_RUNS}); the rerun uses "
            "the version the study ships."
        )
    return Chain([workspace / r["script"] for r in seq], ORDER_RECORDED, notes)


def chain_of(workspace: Path) -> Chain:
    """The scripts that wrote ``estimation_results.json``, in the order to run them.

    The order is the one the run recorded when it ran them (the script log that
    ``e2er-run`` and the runner write). A run without that record (e2er before
    0.15.0) falls back to the order the run last changed the files, and the
    recipe says so: copies, restores and checkouts reset file times.
    """
    writers, canonical = _writers(workspace)
    recorded = _recorded_chain(workspace, writers, canonical)
    if recorded is not None:
        return recorded
    if canonical is None:
        if not writers:
            return Chain([], ORDER_SINGLE)
        # No script under a known name: the runner would run the latest one that writes the file.
        latest = max(writers, key=lambda p: (p.stat().st_mtime_ns, p.name))
        return Chain([latest], ORDER_SINGLE if len(writers) == 1 else ORDER_FILE_TIMES)
    results = workspace / RESULTS
    start = canonical.stat().st_mtime_ns
    end = results.stat().st_mtime_ns if results.is_file() else None
    later = [
        p
        for p in writers
        if p != canonical and p.stat().st_mtime_ns > start and (end is None or p.stat().st_mtime_ns <= end + _SLACK_NS)
    ]
    later.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
    if not later:
        return Chain([canonical], ORDER_SINGLE)
    return Chain(
        [canonical, *later],
        ORDER_FILE_TIMES,
        [
            "Order taken from file times: the run recorded no script runs (e2er before 0.15.0), so the scripts "
            "run in the order the run last changed them. Copies, restores and checkouts change file times; "
            "if the rerun differs, check the order of the steps first."
        ],
    )


def estimation_chain(workspace: Path) -> list[Path]:
    """The scripts of :func:`chain_of`."""
    return chain_of(workspace).scripts


def no_recipe_reason(workspace: Path) -> str | None:
    """Why the run gets no recipe, in a plain sentence; None when it gets one."""
    if not (workspace / RESULTS).is_file():
        return (
            "the study has no estimation results (estimation_results.json), so there is nothing to compare a rerun with"
        )
    if not _populated(workspace / RESULTS):
        return "the study's estimation_results.json is empty, so there is nothing to compare a rerun with"
    if not estimation_chain(workspace):
        return (
            "the study has no estimation script: no script of the run writes estimation_results.json, "
            "so there is no code to run again"
        )
    return None


def folder_reason(folder: Path) -> str | None:
    """The same question for an exported study folder that has no reproduce.json (``e2er reproduce``)."""
    if not (folder / "provenance.json").is_file():
        return None
    if not (folder / "results" / RESULTS).is_file():
        return (
            "This study has no estimation results (results/estimation_results.json), so there is nothing "
            "to compare a rerun with."
        )
    scripts = [*(folder / "code").glob("*.py"), *(folder / "code" / "scratch").glob("*.py")]
    if not any(RESULTS in _read(p) for p in scripts):
        return (
            "This study has no estimation script: none of its code writes estimation_results.json, so there "
            "is no code to run again."
        )
    return (
        "This folder was exported before e2er wrote reproduce.json at export (0.15.0). Export the study "
        "again with `e2er export <paper_id>` to get one."
    )


def _literals(source: str) -> list[str]:
    """Every string constant of a script (its file names and paths)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return re.findall(r"""['"]([^'"\n]{1,300})['"]""", source)
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


#: A file a script opens for writing, or writes with pandas/matplotlib/numpy: an output of the run, not an input.
_OPEN_WRITE = re.compile(r"""open\(\s*f?["'](?:\./)?([^"'{}]+?)["']\s*,\s*(?:mode\s*=\s*)?["'][wax]""")
_OTHER_WRITE = re.compile(r"""(?:\.to_csv|\.to_json|\.to_parquet|savefig|savetxt)\(\s*f?["'](?:\./)?([^"'{}]+?)["']""")


#: The files the spatial-analysis template's analysis writes for its checks (spatial_checks.py).
_SPATIAL_OUTPUT = re.compile(r"^spatial_(units|weights[A-Za-z0-9_-]*)\.csv$")


def written_files(scripts: list[Path]) -> set[str]:
    """Names the scripts write (``open("x.csv", "w")``, ``df.to_csv("x.csv")``, ...): outputs, never inputs.

    The spatial-analysis template's analysis writes the units and the weights it used
    (spatial_units.csv, spatial_weights.csv); comparing them as inputs would call every
    rerun a difference.
    """
    out: set[str] = set()
    for script in scripts:
        source = _read(script)
        out.update(m.group(1).strip() for m in _OPEN_WRITE.finditer(source))
        out.update(m.group(1).strip() for m in _OTHER_WRITE.finditer(source))
    return out


def referenced_files(workspace: Path, scripts: list[Path]) -> list[str]:
    """Workspace-relative paths of the files the scripts name (relative, by the workspace's full path, or by glob)."""
    roots = {str(workspace), str(workspace.resolve())}
    found: set[str] = set()
    for script in scripts:
        source = _read(script)
        # A script that names the workspace by its full path joins file names to it (WS + "/data.db").
        names_root = any(root in source for root in roots)
        for lit in _literals(source):
            text = lit.strip()
            if not text or len(text) > 300 or "\n" in text:
                continue
            for root in roots:
                if text.startswith(root + "/"):
                    text = text[len(root) + 1 :]
                    break
            else:
                if names_root and text.startswith("/") and (workspace / text[1:]).is_file():
                    text = text[1:]
            if text.startswith("./"):
                text = text[2:]
            if text.startswith("/") or ".." in Path(text).parts or not text:
                continue
            if any(c in text for c in "*?["):
                try:
                    found.update(p.relative_to(workspace).as_posix() for p in workspace.glob(text) if p.is_file())
                except (ValueError, NotImplementedError):
                    pass
                continue
            if (workspace / text).is_file():
                found.add(Path(text).as_posix())
        # `e2er-data query sql|tables` reads the study's data.db without naming it (the estimation
        # skill allows it; in a rerun it reads the rerun's data.db), so data.db is an input then too.
        if _QUERY_TOOL.search(source) and (workspace / "data.db").is_file():
            found.add("data.db")
    names = {s.name for s in scripts}
    return sorted(f for f in found if f not in names)


_QUERY_TOOL = re.compile(r"""e2er-data["']?\s*,?\s*["']?query\b""")


# ── data_sources.json ────────────────────────────────────────────────────────


def _loads(workspace: Path) -> list[dict[str, Any]]:
    try:
        doc = json.loads((workspace / "data_sources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    loads = doc.get("loads") if isinstance(doc, dict) else None
    return [x for x in loads or [] if isinstance(x, dict)]


def _saved(entry: dict[str, Any]) -> str | None:
    """The workspace path a load saved its rows to (``saved_to`` is recorded with or without ``data/``)."""
    s = entry.get("saved_to")
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip().lstrip("./")
    return s if s.startswith("data/") else f"data/{s}"


def _describe(entry: dict[str, Any]) -> str:
    if entry.get("connector") == "data-folder":
        return f"the researcher's data file {entry.get('series')}"
    bits = [str(entry.get("dataset") or entry.get("connector") or "a source")]
    if entry.get("series"):
        bits.append(str(entry["series"]))
    if entry.get("version"):
        bits.append(f"release {entry['version']}")
    when = str(entry.get("retrieved_at") or "")[:10]
    return ", ".join(bits) + (f", loaded {when}" if when else "")


def _load_of(loads: list[dict[str, Any]], rel: str) -> dict[str, Any] | None:
    """The load that saved the workspace file ``rel`` (or recorded it as the researcher's file)."""
    for e in loads:
        paths = [f.get("path") for f in e.get("files") or [] if isinstance(f, dict)]
        if _saved(e) == rel or rel in paths:
            return e
    return None


def _db_tables(db: Path) -> list[str]:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [str(r[0]) for r in rows if not str(r[0]).startswith("sqlite_")]


def _db_source(db: Path, loads: list[dict[str, Any]]) -> str:
    by_table: dict[str, str] = {}
    for e in loads:
        for t in [e.get("table"), *(e.get("tables") or [])]:
            if isinstance(t, str) and t:
                by_table[t] = _describe(e)
    tables = _db_tables(db)
    if not tables:
        return "the study's database"
    parts = [f"{t} ({by_table.get(t, 'made by the study during the run')})" for t in tables]
    return "the study's database, tables: " + "; ".join(parts)


# ── reloading what cannot be shipped ─────────────────────────────────────────


def _reload_args(entry: dict[str, Any]) -> tuple[list[str], str] | None:
    """The e2er-data command that repeats a load of a source with terms (without its target), and a note.

    From the source's definition (its ``reload``, else the recorded request); None if unknown.
    """
    from ...modules.data.sources.runtime import reload_args

    source = _restricted().get(str(entry.get("connector")))
    return reload_args(source, entry) if source is not None else None


def _reloads(workspace: Path, loads: list[dict[str, Any]], inputs: list[str]) -> tuple[list[dict[str, Any]], bool]:
    """The loads get_data.py repeats: loads of sources with terms (Yahoo, the GMD, …) that went into an input.

    Returns (reloads, any without dates).
    """
    out: list[dict[str, Any]] = []
    undated = False
    uses_db = "data.db" in inputs
    restricted = _restricted()
    for e in loads:
        if e.get("connector") not in restricted:
            continue
        made = _reload_args(e)
        if made is None:
            continue
        args, note = made
        undated = undated or note == "dates not recorded"
        table = e.get("table") if isinstance(e.get("table"), str) else None
        saved = _saved(e)
        what = _describe(e)
        if table and uses_db:
            out.append({"table": table, "args": [*args, "--table", table], "what": what})
        if saved and saved in inputs:
            out.append({"file": saved, "args": [*args, "--save-to", saved[len("data/") :]], "what": what})
    return out, undated


GET_DATA = '''"""Load again the inputs this study does not ship, with e2er-data.

Written by e2er at export on {date}, from the loads the run recorded in
data_sources.json. {terms}

An input the folder already has (the study's own copy) is kept; only a missing
one is loaded again, with the command below. A table is loaded into data.db, a
file into data/. The sources revise their data, so a reloaded input can differ
from the study's: `e2er reproduce` compares every input with the study's own
file by SHA-256 and says which differ.

Run it from the run folder (`e2er reproduce` does this for you).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

# What the run loaded and how to load it again (e2er-data arguments).
RELOADS = {reloads}
# The other tables of the study's data.db: they came from elsewhere, and get_data.py cannot load them.
OTHER_TABLES = {other_tables}


def e2er_data() -> str:
    found = os.environ.get("E2ER_DATA") or shutil.which("e2er-data")
    if not found:
        sys.exit("e2er-data was not found. Install e2er (pip install e2er), or run `e2er reproduce` on this folder.")
    return found


def present(here: Path, item: dict) -> bool:
    if item.get("table"):
        db = here / "data.db"
        if not db.is_file():
            return False
        try:
            con = sqlite3.connect(f"file:{{db}}?mode=ro", uri=True)
            try:
                (rows,) = con.execute('SELECT COUNT(*) FROM "' + item["table"].replace('"', '""') + '"').fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            return False
        return rows > 0
    return (here / item["file"]).is_file()


def main() -> int:
    here = Path.cwd().resolve()
    env = {{**os.environ, "E2ER_WORKSPACE_ROOT": str(here.parent)}}
    if OTHER_TABLES and not (here / "data.db").is_file():
        print(
            "data.db is not in the folder. get_data.py can load only the tables listed in it again; "
            "the study also used "
            + ", ".join(OTHER_TABLES)
            + ", which came from other sources. Put the study's data.db in the folder to run it as it ran.",
            file=sys.stderr,
        )
    failed = []
    for item in RELOADS:
        target = item.get("table") or item.get("file")
        if present(here, item):
            print(f"{{target}}: the study's own copy is here, not loaded again")
            continue
        cmd = [e2er_data(), "--paper-id", here.name, "--specialist", "researcher", *item["args"]]
        out = subprocess.run(cmd, env=env, capture_output=True, text=True)
        try:
            result = json.loads(out.stdout)
        except ValueError:
            result = {{"error": (out.stderr or out.stdout).strip()[-300:]}}
        if out.returncode != 0 or result.get("error") or not present(here, item):
            failed.append(f"{{target}} ({{item['what']}}): {{result.get('error') or 'nothing was loaded'}}")
            continue
        print(f"{{target}}: loaded again ({{item['what']}})")
    if failed:
        print("Could not load:", *failed, sep="\\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# ── requirements ─────────────────────────────────────────────────────────────


def _imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", source, re.M))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def pinned_requirements(scripts: list[Path], local: set[str]) -> tuple[list[str], list[str]]:
    """(``name==version`` lines, modules the scripts import that this environment does not have)."""
    import importlib.metadata as md

    modules = set().union(*(_imports(_read(s)) for s in scripts)) if scripts else set()
    modules -= set(sys.stdlib_module_names) | local | {"__future__"}
    dists = md.packages_distributions()
    pins: dict[str, str] = {}
    missing: list[str] = []
    for mod in sorted(modules):
        names = dists.get(mod) or []
        if not names:
            missing.append(mod)
            continue
        for name in names:
            try:
                pins[name] = md.version(name)
            except md.PackageNotFoundError:
                missing.append(mod)
    return [f"{n}=={v}" for n, v in sorted(pins.items(), key=lambda kv: kv[0].lower())], missing


# ── the writer ───────────────────────────────────────────────────────────────


def _exported_copy(out: Path, rel: str, sha: str) -> str | None:
    """Where export put the workspace file ``rel`` (same name and SHA-256), as a path in ``out``."""
    if rel == "data.db" and (out / "data" / "data.db").is_file():
        return "data/data.db"
    name = Path(rel).name
    found = [p for p in out.rglob(name) if p.is_file() and _sha256(p) == sha]
    if not found:
        return None
    rels = [p.relative_to(out).as_posix() for p in found]
    return sorted(rels, key=lambda r: (next(i for i, pre in enumerate(_PREFERRED) if r.startswith(pre)), r))[0]


def _rewrite_workspace_paths(path: Path, workspace: Path) -> bool:
    """Replace the workspace's full path in an exported script by the run folder; True when it named it."""
    text = _read(path)
    new = text
    for root in sorted({str(workspace.resolve()), str(workspace)}, key=len, reverse=True):
        new = new.replace(root + "/", "").replace(root, ".")
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _iso(date_str: str) -> str:
    if re.fullmatch(r"\d{8}", date_str or ""):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str or datetime.now(UTC).date().isoformat()


def write_recipe(workspace: Path, out: Path, *, date_str: str = "") -> Outcome:
    """Write reproduce.json (and code/requirements.txt, code/get_data.py) into the export ``out``."""
    workspace = Path(workspace)
    date_str = _iso(date_str)
    if (out / "reproduce.json").is_file():
        return Outcome(reason="", notes=[])  # the run wrote its own recipe; export copied it
    why = no_recipe_reason(workspace)
    if why:
        return Outcome(reason=why)
    if not (out / "results" / RESULTS).is_file():
        return Outcome(reason="the export has no results/estimation_results.json to compare a rerun with")
    ordered = chain_of(workspace)
    chain = ordered.scripts
    loads = _loads(workspace)
    notes: list[str] = list(ordered.notes)
    files: dict[str, str] = {}
    rewritten: list[str] = []
    for script in chain:
        copy = _exported_copy(out, script.name, _sha256(script))
        if copy is None:
            return Outcome(reason=f"the export does not have the script {script.name}")
        files[script.name] = copy
        if _rewrite_workspace_paths(out / copy, workspace):
            rewritten.append(copy)

    inputs: list[dict[str, Any]] = []
    data_inputs: list[str] = []
    restricted = _restricted()
    unshippable = {s for e in loads if e.get("connector") in restricted and (s := _saved(e))}
    recorded_sha = {
        f.get("path"): f.get("sha256")
        for e in loads
        if e.get("connector") == "data-folder"
        for f in e.get("files") or []
        if isinstance(f, dict)
    }
    outputs = written_files(chain)
    for rel in referenced_files(workspace, chain):
        if rel in (RESULTS, *OTHER_RESULTS):
            continue
        if rel in outputs or _SPATIAL_OUTPUT.match(rel):
            # A file the scripts write: never an input to compare. One they also read first
            # (figure_spec.json, updated in place) is laid out as the study left it.
            copy = _exported_copy(out, rel, _sha256(workspace / rel))
            if copy is not None:
                files[rel] = copy
            continue
        src = workspace / rel
        sha = _sha256(src)
        is_data = Path(rel).suffix.lower() in DATA_SUFFIXES
        copy = None if rel in unshippable else _exported_copy(out, rel, sha)
        if copy is None and rel not in unshippable and rel.startswith("data/"):
            # A data file the export does not ship (a staged file of the researcher, an e2er-data --save-to file):
            # copied in, unless it is a link out of the workspace the run did not record as the researcher's file.
            inside = src.resolve().is_relative_to(workspace.resolve())
            if (inside or recorded_sha.get(rel) == sha) and src.stat().st_size <= MAX_INPUT_BYTES:
                target = out / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, target)
                copy = rel
            else:
                notes.append(f"{rel} is not in the folder (a link out of the study, or larger than 200 MB)")
        if copy is not None:
            files[rel] = copy
        if is_data:
            data_inputs.append(rel)
            if rel == "data.db":
                source = _db_source(src, loads)
            else:
                entry = _load_of(loads, rel)
                source = _describe(entry) if entry else "a file the study's code reads"
            inputs.append({"path": rel, "sha256": sha, "source": source})
        elif copy is None:
            notes.append(f"{rel}, which a script reads, is not in the folder")

    steps: list[dict[str, Any]] = []
    reloads, undated = _reloads(workspace, loads, data_inputs)
    if reloads:
        reloaded = {r.get("file") for r in reloads} | ({"data.db"} if any(r.get("table") for r in reloads) else set())
        for item in inputs:
            if item["path"] in reloaded:
                item["reload"] = "get_data.py"
        from ..data_terms import known

        sources = known()
        used = sorted({a["args"][0] for a in reloads})
        names = {c: sources[c].article + sources[c].name for c in used}
        reloaded_tables = {r["table"] for r in reloads if r.get("table")}
        other_tables = (
            [t for t in _db_tables(workspace / "data.db") if t not in reloaded_tables] if reloaded_tables else []
        )
        terms = " ".join(
            f"{names[c][:1].upper() + names[c][1:]}'s terms {sources[c].limit}, so a published study may leave "
            "its data out."
            for c in used
        )
        (out / "code").mkdir(parents=True, exist_ok=True)
        (out / "code" / "get_data.py").write_text(
            GET_DATA.format(
                date=date_str,
                terms=terms,
                reloads=json.dumps(reloads, indent=4),
                other_tables=json.dumps(other_tables),
            ),
            encoding="utf-8",
        )
        files["get_data.py"] = "code/get_data.py"
        steps.append({"run": ["python", "get_data.py"], "about": "load the inputs the folder does not ship (if any)"})
        revised = (
            " Yahoo Finance revises its history (prices adjusted for dividends change with every new dividend), "
            "so reloaded prices can differ slightly from the study's."
            if _YAHOO in used
            else ""
        )
        notes.append(f"{terms} get_data.py loads these data again with e2er-data when the folder lacks them.{revised}")
        if undated:
            notes.append(
                "The run did not record the dates of its Yahoo Finance loads (e2er before 0.15.0), so get_data.py "
                "loads the full history; the study's own rows are a part of it."
            )
    for i, script in enumerate(chain):
        about = "the estimation script" if i == 0 else f"a later script of the run that writes {RESULTS} again"
        steps.append({"run": ["python", script.name], "about": about})

    if (out / "code" / "requirements.txt").is_file():
        requirements_note = "code/requirements.txt is the run's own."
    else:
        local = {p.stem for p in workspace.glob("*.py")}
        pins, missing = pinned_requirements(chain, local)
        py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        lines = [
            "# The packages the study's scripts import, at the versions of the Python environment",
            f"# e2er ran the study in (Python {py}), written by e2er at export. `e2er reproduce` installs",
            "# them in a new environment.",
        ]
        if missing:
            lines.append(f"# Imported but not installed when the study ran: {', '.join(missing)}")
        (out / "code").mkdir(parents=True, exist_ok=True)
        (out / "code" / "requirements.txt").write_text("\n".join([*lines, *pins]) + "\n", encoding="utf-8")
        requirements_note = f"code/requirements.txt pins {len(pins)} package(s) at the versions the run used."
        if missing:
            notes.append(
                f"The scripts import {', '.join(missing)}, which was not installed when the study ran, so "
                "requirements.txt does not pin it and the rerun does not have it either."
            )
    if rewritten:
        notes.append(
            "The scripts named the run's workspace folder by its full path. The export replaced it with the run "
            f"folder, so they run from any folder ({', '.join(rewritten)}); nothing else in them was changed."
        )

    compare = [{"published": f"results/{RESULTS}", "produced": RESULTS}]
    for name in OTHER_RESULTS:
        if (out / "results" / name).is_file() and any(name in _read(s) for s in chain):
            compare.append({"published": f"results/{name}", "produced": name})

    order_words = {
        ORDER_RECORDED: "in the order the run ran them (its script log)",
        ORDER_FILE_TIMES: "in the order the run last changed them (file times; the run recorded no script runs)",
        ORDER_SINGLE: "in the order the run ran them",
    }[ordered.order]
    recipe: dict[str, Any] = {
        "schema": "e2er-reproduce/1",
        "about": (
            f"Written by e2er at export ({date_str}) from what the run "
            f"recorded: the scripts that wrote {RESULTS}, from the estimation script on, {order_words}; the files "
            f"they read; and the packages they import. {requirements_note}"
        ),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "requirements": "code/requirements.txt",
        "files": files,
        "steps": steps,
        "inputs": inputs,
        "compare": compare,
        "notes": notes,
    }
    (out / "reproduce.json").write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return Outcome(recipe=recipe, notes=notes)
