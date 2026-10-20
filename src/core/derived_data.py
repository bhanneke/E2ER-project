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

Not only data files: a results table, a weights list or the data behind a figure that such a
script writes (OUTPUT_SUFFIXES under results/, misc/, paper/), and the figure spec of a study
that loaded restricted data, are built from it too. Whether a published copy leaves such a
file out is :func:`kept_out`'s answer: every data file under data/, and every other file that
holds the source's rows rather than an aggregate of them (derived_rows.py).

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
#: Endings of every file a script writes that can hold data: the data files, and the results, figure specs
#: and arrays a study writes next to them (results/figure_spec.json). Rendered output (PDF, PNG, LaTeX) is not.
OUTPUT_SUFFIXES = DATA_SUFFIXES | frozenset(
    {
        ".json",
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
    }
)
#: Where in an exported folder a script's outputs are kept (scripts, design and reviews are not outputs).
OUTPUT_DIRS = ("data/", "results/", "misc/", "paper/")
#: Records about the data that are not the data (never left out: they say what was loaded).
DATA_RECORDS = frozenset({"data/data_sources.json", "data/data_dictionary.json", "data/data_summary.md"})
_WRITE_METHODS = frozenset(
    {
        "to_csv",
        "to_parquet",
        "to_excel",
        "to_feather",
        "to_stata",
        "to_pickle",
        "to_hdf",
        "to_json",
        "savetxt",
        "write_csv",
        "write_text",
        "write_bytes",
        "save",
        "savez",
        "savez_compressed",
    }
)
#: Calls that read the file their first argument names (or, for a path's method, the path itself).
_READ_CALLS = frozenset(
    {
        "read_csv",
        "read_table",
        "read_json",
        "read_parquet",
        "read_excel",
        "read_feather",
        "read_stata",
        "read_pickle",
        "read_hdf",
        "loadtxt",
        "genfromtxt",
        "load",
        "connect",
        "read_file",
    }
)
_PATH_READS = frozenset({"read_text", "read_bytes"})
#: Where the scripts of an exported folder are.
_SCRIPT_DIRS = ("code", "replication")


@dataclass
class Script:
    """What one script names and writes (paths as the script names them, relative to the folder it ran in)."""

    rel: str
    strings: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    tables_written: set[str] = field(default_factory=set)
    #: Files the script opens for reading (``pd.read_csv(p)``, ``open(p)``, ``json.load(open(p))``,
    #: ``Path(p).read_text()``): a file it names and writes is read too only when it is in here.
    reads: set[str] = field(default_factory=set)


@dataclass
class Derived:
    """A data file holding a restricted source's data that no load wrote: built from it by a script."""

    path: str  # in the folder
    connectors: list[str]
    writers: list[str]  # the scripts (folder paths) that write it
    named: str  # the path as the scripts name it (run-folder path)
    #: Why the file holds the source's rows (derived_rows.row_level), set by :func:`kept_out`; "" for a
    #: data file under data/, which is left out whatever it holds.
    rows: str = ""
    #: What export recorded (provenance.json run.derived_data ``holds_rows``): whether the file held the
    #: source's rows when the folder had it. None: not recorded (exported before e2er 0.17.2).
    recorded_rows: bool | None = None


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
        if name in ("write_text", "write_bytes") and isinstance(func, ast.Attribute):
            # Path(p).write_text(…), OUT.write_text(…): the path is the object the method is called on.
            target = _resolve(func.value, consts)
        elif name in _PATH_READS and isinstance(func, ast.Attribute):
            read = _resolve(func.value, consts)
            if read:
                out.reads.add(_norm(read))
        elif name in _WRITE_METHODS:
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
            else:
                read = _resolve(node.args[0], consts)
                if read:
                    out.reads.add(_norm(read))
        elif name in _READ_CALLS and node.args:
            read = _resolve(node.args[0], consts)
            if read:
                out.reads.add(_norm(read))
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
    found = _all_in_folder(folder, named, known)
    return found[0] if found else None


def _all_in_folder(folder: Path, named: str, known: set[str]) -> list[str]:
    """Every place an exported folder keeps a file a script named: the run's outputs are copied to results/
    and, for some, to misc/ or paper/ as well (each copy holds the same data)."""
    named = _norm(named)
    base = named.rsplit("/", 1)[-1]
    # A path the script named outside the folder (the run's workspace by its full path) is looked for by name.
    inside = not (named.startswith("/") or ".." in named.split("/") or re.match(r"^[A-Za-z]:", named))
    out: list[str] = []
    for cand in (
        named,
        f"data/{base}",
        f"results/{base}",
        f"misc/{base}",
        f"paper/{base}",
        f"results/figures/{base}",
        f"paper/figures/{base}",
    ):
        if cand == named and not inside:
            continue
        if cand in out or cand in DATA_RECORDS or (cand != named and not cand.startswith(OUTPUT_DIRS)):
            continue
        if cand in known or (folder / cand).is_file():
            out.append(cand)
    return out


def is_output(rel: str) -> bool:
    """A file of an exported folder that a script may have written with data in it (OUTPUT_SUFFIXES/DIRS)."""
    return rel.startswith(OUTPUT_DIRS) and rel not in DATA_RECORDS and Path(rel).suffix.lower() in OUTPUT_SUFFIXES


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
                if Path(w).suffix.lower() not in OUTPUT_SUFFIXES:
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
        held = entry.get("holds_rows")
        out.append(
            Derived(
                path=entry["path"],
                connectors=sorted(listed_cs),
                writers=sorted(set(writers_here) | static),
                named=str(entry.get("named") or entry["path"]),
                recorded_rows=held if isinstance(held, bool) else None,
            )
        )
        seen.add(entry["path"])
    # The figure spec holds the data behind the figures: e2er's figure step builds it from the study's data,
    # so in a study that loaded restricted data it counts as built from them, whoever wrote it.
    sources = sorted({c for cs in files.values() for c in cs})
    if sources:
        for cand in ("results/figure_spec.json", "misc/figure_spec.json"):
            if cand not in seen and cand not in {w for n in files for w in _all_in_folder(folder, n, known)}:
                if cand in known or (folder / cand).is_file():
                    out.append(
                        Derived(cand, sources, sorted(writers.get("figure_spec.json", set())), "figure_spec.json")
                    )
                    seen.add(cand)
    for named, cs in sorted(files.items()):
        if named in roots or named == "data.db":
            continue
        for where in _all_in_folder(folder, named, known):
            if where in seen:
                continue  # already recorded
            seen.add(where)
            out.append(
                Derived(
                    path=where,
                    connectors=sorted(cs),
                    writers=sorted(writers.get(named, set())),
                    named=named,
                )
            )
    return out


_SHAPES: dict[tuple[str, frozenset[str], tuple[float, ...]], Any] = {}


def _shape(folder: Path, restricted: set[str]) -> Any:
    """derived_rows.shape, read once per folder state (it reads the restricted sources' rows)."""
    from .derived_rows import shape

    stamps = []
    for rel in ("data/data_sources.json", "data_sources.json", "data/data.db", "data.db"):
        try:
            stamps.append((folder / rel).stat().st_mtime)
        except OSError:
            stamps.append(0.0)
    key = (str(folder.resolve()), frozenset(restricted), tuple(stamps))
    if key not in _SHAPES:
        if len(_SHAPES) > 32:
            _SHAPES.clear()
        # The source's own rows are often not in the folder (export never ships Gaia's raw rows), but the
        # data files built from them are (data/gaia_clean.csv): their identifier columns are the source's.
        extra = [
            (folder / d.path, d.connectors)
            for d in derived(folder, restricted)
            if d.path.startswith("data/") and Path(d.path).suffix.lower() in (".csv", ".tsv")
        ]
        _SHAPES[key] = shape(folder, restricted, extra)
    return _SHAPES[key]


def kept_out(folder: Path, restricted: set[str] | None = None, known: set[str] | None = None) -> list[Derived]:
    """The derived files a published copy of the folder leaves out (pack, publish --github), each with why.

    Every derived data file under data/; every other derived output (a results table, a figure spec) that
    holds the source's rows (derived_rows.row_level: not an aggregate); and every derived file that is not
    in the folder, since what it holds cannot be read. A derived aggregate is not in the list: it goes up.
    """
    folder = Path(folder)
    if restricted is None:
        from .data_terms import known as known_terms

        restricted = set(known_terms())
    return [d for d in derived(folder, restricted, known) if holds_rows(folder, d, restricted)]


def holds_rows(folder: Path, d: Derived, restricted: set[str]) -> bool:
    """Does a published copy leave the derived file out (kept_out)? Sets ``d.rows`` to why, for an output."""
    p = Path(folder) / d.path
    if d.path.startswith("data/") and Path(d.path).suffix.lower() in DATA_SUFFIXES:
        return True
    if not p.is_file():
        # Not here (a published copy left it out): what export recorded of it, else kept out to be safe.
        if d.recorded_rows is False:
            return False
        d.rows = "not in the folder, so what it holds cannot be read"
        return True
    if not is_output(d.path):
        return True  # not a format or place e2er reads for rows: kept out
    from .derived_rows import row_level

    why = row_level(p, d.connectors, _shape(Path(folder), restricted))
    if why:
        d.rows = why
    return bool(why)


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


def _same_path(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return a == b or a.endswith("/" + b) or b.endswith("/" + a) or (a.rsplit("/", 1)[-1] == b and "/" not in b)


def writes_file(script: Script, path: str) -> bool:
    """Does the script write ``path`` (as the run named it)?"""
    return any(_same_path(w, path) for w in script.writes)


def reads_file(script: Script, path: str) -> bool:
    """Does the script read ``path``: it opens it for reading, or names it without writing it."""
    if any(_same_path(r, path) for r in script.reads):
        return True
    return _names_file(script, path) and not writes_file(script, path)


def rebuild_plan(folder: Path, recipe: dict[str, Any], derived_files: list[Derived]) -> list[dict[str, Any]]:
    """How a rerun gets back each derived file a published folder leaves out: the script that writes it from
    data the rerun loads again.

    Returns a list of steps, each ``{"path": run-folder path, "script": run name, "from": folder path of the
    script}``:

    - **an input** the recipe lists and cannot yet get back: a writer qualifies when every restricted file
      or table it reads is loaded again by the recipe (``"reload"``) or built by another planned step, and
      every other left-out file it reads is planned before it; the first in the order of the folder;
    - **an output** (``"output": true``) that no input lists: a result, a figure's data. A file one of the
      recipe's steps writes needs nothing more (``"written": true``, the step's script), unless an earlier
      step reads it: then a writer that does not read it builds it after the data are loaded again. A file
      no step writes is built by such a writer, after the last step that writes a file it reads
      (``"after"``: that step's script).

    Files with no such writer are left out of the plan (the caller says that they cannot be rebuilt).
    """
    folder = Path(folder)
    files_map = recipe.get("files") or {}
    by_source = {str(src): str(dst) for dst, src in files_map.items()}
    inputs = {str(i.get("path")): i for i in recipe.get("inputs") or [] if isinstance(i, dict)}
    reloaded = {p for p, i in inputs.items() if i.get("reload")}
    # What the rerun has before any planned step: inputs loaded again, and inputs a step of the recipe
    # already builds again (``"rebuild"``).
    rebuilt = {p for p, i in inputs.items() if i.get("rebuild")}
    reloaded_tables: set[str] = set()
    if "data.db" in reloaded:
        reloaded_tables = {
            str(t)
            for e in _loads(folder)
            for t in [e.get("table"), *(e.get("tables") or [])]
            if isinstance(t, str) and t
        }
    scripts = {s.rel: s for s in scripts_of(folder)}
    steps = [Path(a).name for st in recipe.get("steps") or [] if isinstance(st, dict) for a in _argv(st)]
    steps = [n for n in dict.fromkeys(steps) if n.endswith(".py")]
    by_name = {s.rel.rsplit("/", 1)[-1]: s for s in scripts.values()}
    step_scripts = [(n, scripts.get(str(files_map.get(n, ""))) or by_name.get(n)) for n in steps]
    plan: list[dict[str, Any]] = []
    available = reloaded | rebuilt
    left = {d.path for d in derived_files}

    def run_path(d: Derived) -> str:
        return by_source.get(d.path) or d.named

    def reads_ok(s: Script, d: Derived) -> bool:
        rfiles, rtables = restricted_reads(s, folder)
        if not all(any(_norm(f) == _norm(a) or a.endswith("/" + _norm(f)) for a in available) for f in rfiles):
            return False
        if not rtables <= reloaded_tables:
            return False
        others = [x for x in derived_files if x is not d and x.path in left and reads_file(s, x.named)]
        return all(run_path(x) in available or x.named in available for x in others)

    def qualifies(w: str) -> str | None:
        name = Path(w).name
        if name not in steps and name in files_map and files_map[name] != w:
            return None  # another file already runs under that name
        return name

    inputs_pending = [d for d in derived_files if run_path(d) in inputs or d.named in inputs]
    outputs_pending = [d for d in derived_files if d not in inputs_pending]
    progress, fallback = True, False
    while (inputs_pending or outputs_pending) and progress:
        progress = False
        for d in list(inputs_pending):
            item = inputs.get(run_path(d)) or inputs.get(d.named)
            if item is None or item.get("reload") or item.get("rebuild"):
                inputs_pending.remove(d)
                continue
            for w in d.writers:
                s = scripts.get(w)
                name = qualifies(w)
                if s is None or name is None or _reads(s, d, d.named):
                    continue
                if not reads_ok(s, d):
                    continue
                plan.append({"path": str(item["path"]), "script": name, "from": w})
                available.add(str(item["path"]))
                inputs_pending.remove(d)
                progress = True
                break
        for d in list(outputs_pending):
            rp_ = run_path(d)
            readers = [i for i, (_n, s) in enumerate(step_scripts) if s is not None and _reads(s, d, rp_)]
            writers = [i for i, (_n, s) in enumerate(step_scripts) if s is not None and _writes(s, d, rp_)]
            first_reader = min(readers) if readers else None
            if writers and not readers:
                n = step_scripts[writers[0]][0]
                plan.append(_written(rp_, n, files_map, d))
                available.add(rp_)
                outputs_pending.remove(d)
                progress = True
                continue
            built = False
            for w in d.writers:
                s = scripts.get(w)
                name = qualifies(w)
                if s is None or name is None or name in steps or _reads(s, d, rp_):
                    continue
                if not reads_ok(s, d):
                    continue
                # After the last step that writes something it reads (a result it reads), before the first reader.
                needs = [i for i, (_n, st) in enumerate(step_scripts) if st is not None and _feeds(st, s)]
                after = max(needs) if needs else None
                if first_reader is not None and after is not None and after >= first_reader:
                    continue
                entry: dict[str, Any] = {"path": rp_, "script": name, "from": w, "output": True, "folder": d.path}
                if after is not None:
                    entry["after"] = step_scripts[after][0]
                plan.append(entry)
                built = True
                break
            if not built and fallback and writers and all(i in writers for i in readers):
                # Only steps that read the file and write it again (a script updating its own output): it
                # copes without it or fails, which the rerun reports.
                plan.append(_written(rp_, step_scripts[writers[0]][0], files_map, d))
                built = True
            if built:
                available.add(rp_)
                outputs_pending.remove(d)
                progress = True
        if not progress and not fallback and outputs_pending:
            fallback = progress = True  # once nothing else is found: the steps that update their own output
    return plan


def _written(path: str, name: str, files_map: dict[str, Any], d: Derived) -> dict[str, Any]:
    return {
        "path": path,
        "script": name,
        "from": str(files_map.get(name, name)),
        "output": True,
        "written": True,
        "folder": d.path,
    }


def _writes(script: Script, d: Derived, path: str) -> bool:
    """Does the script write the derived file: as its code reads, or as the run's record of it says."""
    return script.rel in d.writers or writes_file(script, path)


def _reads(script: Script, d: Derived, path: str) -> bool:
    """Does the script read the derived file (one the run recorded it writing reads it only by opening it)."""
    if any(_same_path(r, path) for r in script.reads):
        return True
    return _names_file(script, path) and not _writes(script, d, path)


def _feeds(step: Script, script: Script) -> bool:
    """Does ``step`` write a file ``script`` reads?"""
    return any(reads_file(script, w) for w in step.writes)


def _argv(step: dict[str, Any]) -> list[str]:
    run = step.get("run")
    if isinstance(run, list):
        return [str(a) for a in run]
    return str(run or "").split()


#: What produced each kind of file a study's step only updates, when the run's own record does not say.
_PRODUCED_BY = {"figure_spec.json": "the figure step"}


def not_produced_by_step(folder: Path, recipe: dict[str, Any]) -> dict[str, str]:
    """Left-out outputs a step of the recipe writes but did not produce: run path → why the rerun's copy is not
    compared with the study's.

    A step that reads the file before writing it (``json.load(open(p))`` … ``json.dump(…, open(p, "w"))``) only
    updates the copy it finds: the study's copy was produced earlier in the run (``figure_spec.json`` by the
    figure step) and maybe changed by other scripts after, so the rerun's copy differs for that reason alone.
    The same holds when another script of the folder, not run by the recipe, writes the file as well.
    """
    folder = Path(folder)
    files_map = recipe.get("files") or {}
    scripts = {s.rel: s for s in scripts_of(folder)}
    ran = {Path(a).name for st in recipe.get("steps") or [] if isinstance(st, dict) for a in _argv(st)}
    out: dict[str, str] = {}
    for item in recipe.get("inputs") or []:
        if not (isinstance(item, dict) and item.get("output") and isinstance(item.get("rebuild"), str)):
            continue
        path, name = str(item["path"]), str(item["rebuild"])
        step = scripts.get(str(files_map.get(name, ""))) or next(
            (s for s in scripts.values() if s.rel.rsplit("/", 1)[-1] == name), None
        )
        if step is None:
            continue
        updates = any(_same_path(r, path) for r in step.reads)
        others = sorted(
            s.rel
            for s in scripts.values()
            # replication/ holds export's copy of the estimation script, not a script of the run of its own.
            if s is not step
            and not s.rel.startswith("replication/")
            and s.rel.rsplit("/", 1)[-1] not in ran
            and writes_file(s, path)
        )
        if not (updates or others):
            continue
        base = path.rsplit("/", 1)[-1]
        source = _PRODUCED_BY.get(base, "an earlier step of the run")
        why = f"not compared: the study's copy comes from {source}"
        if others:
            why += f" and was changed by {', '.join(others)}"
        if updates:
            why += f"; {name} only updates the copy it finds, so the rerun's copy is derived from {source}'s output"
        else:
            why += f"; the rerun's copy is the one {name} writes"
        out[path] = why
    return out


def cannot_rebuild(folder: Path) -> list[Derived]:
    """Derived files the study's code reads that no recorded step builds again (a rerun without them fails)."""
    folder = Path(folder)
    recipe = _read_json(folder / "reproduce.json")
    if not isinstance(recipe, dict):
        return []
    files_map = recipe.get("files") or {}
    inputs = {str(i.get("path")): i for i in recipe.get("inputs") or [] if isinstance(i, dict)}
    out = []
    found = [d for d in kept_out(folder) if (folder / d.path).is_file()]
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
    from .data_terms import known as known_terms

    restricted = set(known_terms())
    record = []
    seen: set[str] = set()
    for d in derived(workspace, restricted, known=set()):
        for where in _all_in_folder(out, d.path, set()):
            if where in seen:
                continue
            seen.add(where)
            copy = Derived(where, d.connectors, d.writers, d.named)
            record.append(
                {
                    "path": where,
                    "named": d.named,
                    "connectors": d.connectors,
                    "writers": sorted({copies[Path(w).name] for w in d.writers if Path(w).name in copies}),
                    # Whether it holds the source's rows (derived_rows.py), so a copy without it can tell an
                    # aggregate that must be there from rows that were left out.
                    "holds_rows": holds_rows(out, copy, restricted),
                }
            )
    return record
