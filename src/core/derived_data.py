"""Data built from a source with terms inherit its terms.

A study that loaded Gaia DR3 rows (whose terms do not allow passing them on)
and cleaned them into ``data/gaia_clean.csv`` holds Gaia data in that file
too. This module finds such files in an exported folder (or a workspace),
without running anything:

- **The roots** are what ``data_sources.json`` records for a source with terms:
  a file a load saved (``saved_to``), and a table it loaded into ``data.db``
  (then ``data.db`` itself).
- **A script reads restricted data** when it names a restricted file (as a
  string, directly or through a module-level constant), or names a restricted
  table and the database.
- **What such a script writes** (``df.to_csv(CLEAN)``, ``open(path, "w")``,
  ``np.savetxt``, ``df.to_sql("table", …)``; paths resolved through
  module-level constants and ``os.path.join``) is restricted too, and so on,
  until nothing new is found.

The reading is deliberately cautious: a script that names a restricted file
in a string counts as reading it. A file wrongly counted stays out of a
package or needs a confirmation at publishing; a file wrongly missed would be
passed on against the source's terms.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Endings of files that hold data (reproduce_recipe.DATA_SUFFIXES).
DATA_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3", ".csv", ".tsv", ".parquet", ".xlsx", ".jsonl", ".dta"})
_WRITE_METHODS = frozenset(
    {"to_csv", "to_parquet", "to_excel", "to_feather", "to_stata", "to_pickle", "to_hdf", "savetxt", "write_csv"}
)
#: Where the scripts of an exported folder are.
_SCRIPT_DIRS = ("code", "replication")


@dataclass
class Script:
    """What one script names and writes (paths as the script names them, relative to the folder it ran in)."""

    rel: str
    strings: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    tables_written: set[str] = field(default_factory=set)


@dataclass
class Derived:
    """A data file holding a restricted source's data that no load wrote: built from it by a script."""

    path: str  # in the folder
    connectors: list[str]
    writers: list[str]  # the scripts (folder paths) that write it
    named: str  # the path as the scripts name it (run-folder path)


def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _resolve(node: ast.AST, consts: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name == "join":
            parts = [_resolve(a, consts) for a in node.args]
            # os.path.join(os.path.dirname(__file__), "data.db"): the resolvable tail is the path.
            tail: list[str] = []
            for part in reversed(parts):
                if part is None:
                    break
                tail.insert(0, part)
            return "/".join(tail) if tail else None
        if name in ("Path", "PurePath") and node.args:
            return _resolve(node.args[0], consts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = _resolve(node.right, consts)
        left = _resolve(node.left, consts)
        if right is None:
            return None
        return f"{left}/{right}" if left else right
    if isinstance(node, ast.JoinedStr):
        return None
    return None


def analyse(rel: str, source: str) -> Script:
    """The strings a script names and the files and tables it writes."""
    out = Script(rel=rel)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Unparseable: every string-looking literal counts as named, nothing as written.
        out.strings = set(re.findall(r"""["']([^"'\n]{1,200})["']""", source))
        return out
    consts: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            value = _resolve(stmt.value, consts)
            if value is not None:
                consts[stmt.targets[0].id] = value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            value = _resolve(stmt.value, consts)
            if value is not None:
                consts[stmt.target.id] = value
    for walked in ast.walk(tree):
        if isinstance(walked, ast.Constant) and isinstance(walked.value, str):
            out.strings.add(walked.value)
        if not isinstance(walked, ast.Call):
            continue
        node = walked
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        target: str | None = None
        if name in _WRITE_METHODS:
            arg = (
                node.args[0]
                if node.args
                else next(
                    (k.value for k in node.keywords if k.arg in ("path_or_buf", "path", "fname", "excel_writer")), None
                )
            )
            # np.savetxt(path, …) is a function call; df.to_csv(path) a method: the first argument is the path.
            target = _resolve(arg, consts) if arg is not None else None
        elif name == "open" and isinstance(func, ast.Name) and node.args:
            mode_node = (
                node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            )
            mode = _resolve(mode_node, consts) if mode_node is not None else "r"
            if mode and any(c in mode for c in "wax"):
                target = _resolve(node.args[0], consts)
        elif name == "to_sql":
            arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "name"), None)
            table = _resolve(arg, consts) if arg is not None else None
            if table:
                out.tables_written.add(table)
        if target:
            out.writes.add(_norm(target))
    for value in consts.values():
        out.strings.add(value)
    # CREATE TABLE x AS … / INSERT INTO x in SQL strings.
    for s in list(out.strings):
        for m in re.finditer(
            r"(?:CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+)"
            r"[\"'`\[]?(\w+)",
            s,
            re.I,
        ):
            out.tables_written.add(m.group(1))
    return out


def _names_file(script: Script, path: str) -> bool:
    """Does the script name ``path`` (as the run named it), directly or by a path ending in it?"""
    path = _norm(path)
    base = path.rsplit("/", 1)[-1]
    for s in script.strings:
        s = _norm(s.strip())
        if not s:
            continue
        if s == path or s.endswith("/" + path) or path.endswith("/" + s) and "/" in s:
            return True
        if s == base and "." in base:
            return True
    return False


def _names_table(script: Script, table: str) -> bool:
    pattern = re.compile(rf"(?<![\w]){re.escape(table)}(?![\w])")
    names_db = any(_norm(s).rsplit("/", 1)[-1].endswith((".db", ".sqlite", ".sqlite3")) for s in script.strings)
    return names_db and any(pattern.search(s) for s in script.strings)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _loads(folder: Path) -> list[dict[str, Any]]:
    for rel in ("data/data_sources.json", "data_sources.json"):
        doc = _read_json(folder / rel)
        if isinstance(doc, dict) and isinstance(doc.get("loads"), list):
            return [e for e in doc["loads"] if isinstance(e, dict)]
    return []


def scripts_of(folder: Path) -> list[Script]:
    """Every Python script of an exported folder (code/, code/scratch/, replication/) or a workspace's top level."""
    folder = Path(folder)
    found: list[Path] = []
    if not (folder / "code").is_dir():  # a workspace: its scripts sit at the top
        found = sorted(p for p in folder.glob("*.py") if p.is_file() and not p.is_symlink())
    for d in _SCRIPT_DIRS:
        if (folder / d).is_dir():
            found += sorted(p for p in (folder / d).rglob("*.py") if p.is_file() and not p.is_symlink())
    out = []
    for p in found:
        if p.name == "get_data.py":
            continue  # loads the roots again through e2er-data; writes nothing of its own
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append(analyse(p.relative_to(folder).as_posix(), source))
    return out


def _in_folder(folder: Path, named: str, known: set[str]) -> str | None:
    """Where the folder keeps a file a script named (``data/x.csv``; ``x.csv`` → ``results/x.csv``), or None."""
    named = _norm(named)
    base = named.rsplit("/", 1)[-1]
    for cand in (named, f"data/{base}", f"results/{base}"):
        if cand in known or (folder / cand).is_file():
            return cand
    return None


def derived(folder: Path, restricted: set[str] | None = None, known: set[str] | None = None) -> list[Derived]:
    """The data files of ``folder`` built from restricted data, transitively (see the module docstring).

    ``restricted``: the connectors whose data may not be passed on (default: data_terms.known()).
    ``known``: paths the folder lists (provenance.json), so a file that is not on disk is found too.
    """
    folder = Path(folder)
    if restricted is None:
        from .data_terms import known as known_terms

        restricted = set(known_terms())
    if known is None:
        prov = _read_json(folder / "provenance.json")
        listed = prov.get("files") if isinstance(prov, dict) else None
        known = set(listed) if isinstance(listed, dict) else set()
    # Roots: restricted file paths and tables as the run named them, each with its connector.
    files: dict[str, set[str]] = {}
    tables: dict[str, set[str]] = {}
    for e in _loads(folder):
        c = e.get("connector")
        if c not in restricted:
            continue
        if isinstance(e.get("saved_to"), str):
            files.setdefault(_norm(e["saved_to"]), set()).add(str(c))
        for t in [e.get("table"), *(e.get("tables") or [])]:
            if isinstance(t, str) and t:
                tables.setdefault(t, set()).add(str(c))
                files.setdefault("data.db", set()).add(str(c))
    roots = set(files)
    scripts = scripts_of(folder)
    # A workspace's script log records the files each run wrote (e2er after 0.16.0): those count as written.
    from .script_log import read_script_runs

    for run in read_script_runs(folder):
        outputs = run.get("outputs")
        if not isinstance(outputs, dict):
            continue
        for s in scripts:
            if s.rel == run.get("script"):
                s.writes |= {_norm(str(p)) for p in outputs}
    writers: dict[str, set[str]] = {}
    changed = True
    while changed:
        changed = False
        for s in scripts:
            reads: set[str] = set()
            for f, cs in list(files.items()):
                if _names_file(s, f):
                    reads |= cs
            for t, cs in list(tables.items()):
                if _names_table(s, t):
                    reads |= cs
            if not reads:
                continue
            for w in s.writes:
                if Path(w).suffix.lower() not in DATA_SUFFIXES:
                    continue
                writers.setdefault(w, set()).add(s.rel)
                before = files.get(w, set())
                if not reads <= before:
                    files[w] = before | reads
                    changed = True
            for t in s.tables_written:
                before = tables.get(t, set())
                if not reads <= before:
                    tables[t] = before | reads
                    files.setdefault("data.db", set()).update(reads)
                    changed = True
    out: list[Derived] = []
    # What export recorded from the run (provenance.json run.derived_data): also files whose script is not shipped.
    prov_doc = _read_json(folder / "provenance.json")
    run_doc = prov_doc.get("run") if isinstance(prov_doc, dict) else None
    recorded = run_doc.get("derived_data") if isinstance(run_doc, dict) else None
    seen: set[str] = set()
    for entry in recorded if isinstance(recorded, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        listed_cs = [str(c) for c in entry.get("connectors") or [] if c in restricted]
        if not listed_cs or not (entry["path"] in known or (folder / entry["path"]).is_file()):
            continue
        writers_here = [w for w in entry.get("writers") or [] if isinstance(w, str) and (folder / w).is_file()]
        static = writers.get(str(entry.get("named") or entry["path"]), set())
        out.append(
            Derived(
                path=entry["path"],
                connectors=sorted(listed_cs),
                writers=sorted(set(writers_here) | static),
                named=str(entry.get("named") or entry["path"]),
            )
        )
        seen.add(entry["path"])
    for named, cs in sorted(files.items()):
        if named in roots or named == "data.db":
            continue
        where = _in_folder(folder, named, known)
        if where is None or where in seen:
            continue  # written by a run, not in the folder (or already recorded)
        out.append(
            Derived(
                path=where,
                connectors=sorted(cs),
                writers=sorted(writers.get(named, set())),
                named=named,
            )
        )
    return out


def restricted_reads(script: Script, folder: Path) -> tuple[set[str], set[str]]:
    """The restricted root files and tables a script reads (as the run named them)."""
    from .data_terms import known as known_terms

    restricted = set(known_terms())
    files: set[str] = set()
    tables: set[str] = set()
    for e in _loads(folder):
        if e.get("connector") not in restricted:
            continue
        if isinstance(e.get("saved_to"), str) and _names_file(script, e["saved_to"]):
            files.add(_norm(e["saved_to"]))
        for t in [e.get("table"), *(e.get("tables") or [])]:
            if isinstance(t, str) and t and _names_table(script, t):
                tables.add(t)
    return files, tables


def rebuild_plan(folder: Path, recipe: dict[str, Any], derived_files: list[Derived]) -> list[dict[str, Any]]:
    """How a rerun builds each derived input again: the script that writes it from data the rerun reloads.

    Returns ``[{"path": run-folder path, "script": run name, "from": folder path of the script}]`` for the
    derived files the recipe lists as inputs and has no way yet to get back. A writer qualifies when every
    restricted file or table it reads is loaded again by the recipe (``"reload"``) or built by another
    planned step; among several, the first in the order of the folder. Inputs with no such writer are left
    out of the plan (the caller says that they cannot be rebuilt).
    """
    folder = Path(folder)
    files_map = recipe.get("files") or {}
    by_source = {str(src): str(dst) for dst, src in files_map.items()}
    inputs = {str(i.get("path")): i for i in recipe.get("inputs") or [] if isinstance(i, dict)}
    reloaded = {p for p, i in inputs.items() if i.get("reload")}
    reloaded_tables: set[str] = set()
    if "data.db" in reloaded:
        reloaded_tables = {
            str(t)
            for e in _loads(folder)
            for t in [e.get("table"), *(e.get("tables") or [])]
            if isinstance(t, str) and t
        }
    scripts = {s.rel: s for s in scripts_of(folder)}
    steps = {Path(a).name for st in recipe.get("steps") or [] if isinstance(st, dict) for a in _argv(st)}
    plan: list[dict[str, Any]] = []
    available = set(reloaded)
    pending = [d for d in derived_files if by_source.get(d.path, d.named) in inputs or d.named in inputs]
    progress = True
    while pending and progress:
        progress = False
        for d in list(pending):
            run_path = by_source.get(d.path) or d.named
            item = inputs.get(run_path) or inputs.get(d.named)
            if item is None or item.get("reload") or item.get("rebuild"):
                pending.remove(d)
                continue
            for w in d.writers:
                s = scripts.get(w)
                if s is None:
                    continue
                rfiles, rtables = restricted_reads(s, folder)
                derived_reads = {x.named for x in derived_files if x is not d and _names_file(s, x.named)}
                ok = all(any(_norm(f) == _norm(a) or a.endswith("/" + _norm(f)) for a in available) for f in rfiles)
                ok = ok and rtables <= reloaded_tables
                ok = ok and all(x in available for x in derived_reads)
                if not ok:
                    continue
                name = Path(w).name
                if name not in steps and name in files_map and files_map[name] != w:
                    continue  # another file already runs under that name
                plan.append({"path": str(item["path"]), "script": name, "from": w})
                available.add(str(item["path"]))
                pending.remove(d)
                progress = True
                break
    return plan


def _argv(step: dict[str, Any]) -> list[str]:
    run = step.get("run")
    if isinstance(run, list):
        return [str(a) for a in run]
    return str(run or "").split()


def cannot_rebuild(folder: Path) -> list[Derived]:
    """Derived files the study's code reads that no recorded step builds again (a rerun without them fails)."""
    folder = Path(folder)
    recipe = _read_json(folder / "reproduce.json")
    if not isinstance(recipe, dict):
        return []
    files_map = recipe.get("files") or {}
    inputs = {str(i.get("path")): i for i in recipe.get("inputs") or [] if isinstance(i, dict)}
    out = []
    found = [d for d in derived(folder) if (folder / d.path).is_file()]
    for d in found:
        run_paths = {dst for dst, src in files_map.items() if src == d.path} or {d.path}
        items = [inputs[p] for p in run_paths if p in inputs]
        if not items or any(i.get("reload") or i.get("rebuild") for i in items):
            continue
        if not rebuild_plan(folder, recipe, [d]):
            out.append(d)
    return out


def export_record(workspace: Path, out: Path) -> list[dict[str, Any]]:
    """The derived data files of a run, as the export ``out`` holds them (for provenance.json run.derived_data).

    Read from the workspace (every script of the run and its script log), so the record holds also when the
    script that built a file is not shipped.
    """
    workspace, out = Path(workspace), Path(out)
    copies = (
        {p.name: p.relative_to(out).as_posix() for p in sorted((out / "code").rglob("*.py"))}
        if (out / "code").is_dir()
        else {}
    )
    record = []
    for d in derived(workspace, known=set()):
        base = d.path.rsplit("/", 1)[-1]
        where = next((c for c in (d.path, f"data/{base}", f"results/{base}") if (out / c).is_file()), None)
        if where is None:
            continue
        record.append(
            {
                "path": where,
                "named": d.named,
                "connectors": d.connectors,
                "writers": sorted({copies[Path(w).name] for w in d.writers if Path(w).name in copies}),
            }
        )
    return record
