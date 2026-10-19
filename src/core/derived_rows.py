"""Does a file built from restricted data hold those data row by row, or only an aggregate of them?

derived_data.py finds the files a study's scripts wrote from data a source's
terms keep out (Gaia rows, GISCO boundaries). Under ``data/`` such a file is
always left out of a published folder. Elsewhere (``results/``, ``misc/``,
``paper/``) a study also writes what a paper publishes: a table of estimates,
summary statistics, the data behind a figure. This module decides, without
running anything, which of those files pass the source's rows on.

**An aggregate** is a file that is all of:

- a format e2er can read here: CSV/TSV (and ``.txt``/``.dat`` columns), JSON
  (``.json``, ``.geojson``, ``.jsonl``), or a SQLite database; any other data
  format (Parquet, Excel, NumPy, pickle, …) counts as row-level, since its
  rows cannot be counted;
- small against the source: a table has at most ``row_limit`` rows; no array
  in a JSON document holds more than ``point_limit`` numbers (or coordinate
  pairs) or more than ``row_limit`` records (objects), and no JSON object is
  a set of more than ``row_limit`` records (objects of the same keys). A
  list of labels (region codes of a cluster, group names) is not a point
  array: what it names is checked against the source's identifiers;
- free of the source's identifiers: no cell, string, key or long integer is
  a value of an identifier column of the restricted source (a column whose
  values are all distinct: Gaia's ``source_id``, a region's name). Values the
  study also loaded from a source without such terms (a NUTS code Eurostat's
  own tables carry too) are not the restricted source's.

The limits follow the source's size (``rows`` of its loads): ``row_limit``
is a tenth of the source's rows, at most 50; ``point_limit`` is 1% of the
source's rows, at least 10 and at most 50, and never above ``row_limit``.
Gaia's 14,066 rows give 50 and 50, GISCO's 299 regions 29 rows and 10
points. A source whose rows were not recorded gets 10 for both. Anything else is **row-level** and is
left out with the source's own data: a figure spec with 9,970 proper-motion
pairs, a units table of 244 regions, a weights list.

Rendered output (PDF, PNG, SVG, LaTeX tables) is never classified here: a
paper's scatter plot is what publications show; the arrays behind it are not.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The largest a point array may be, and its least (when the source is small).
MAX_POINTS = 50
MIN_POINTS = 10
#: Rows read from a source to find its identifier columns (a larger source is read up to this).
_SOURCE_ROWS_READ = 500_000
#: An integer identifier must have at least this many digits to count (a row number 1..n is no identifier).
_ID_INT_DIGITS = 5
_ID_INT_NAME = re.compile(r"(^|_)(id|key|code)$|^id_|_id_", re.I)
#: Formats whose rows e2er counts here; any other data format counts as row-level.
TABLE_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".dat"})
JSON_SUFFIXES = frozenset({".json", ".geojson"})
DB_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})


@dataclass
class Shape:
    """What e2er knows of the restricted sources of a folder: rows loaded and identifier values, by connector."""

    rows: dict[str, int] = field(default_factory=dict)
    ids: dict[str, set[str]] = field(default_factory=dict)

    def limits(self, connectors: list[str]) -> tuple[int, int]:
        """(point_limit, row_limit) for a file built from these sources: the smallest source sets them."""
        known = [self.rows[c] for c in connectors if self.rows.get(c)]
        if not known:
            return MIN_POINTS, MIN_POINTS
        n = min(known)
        rows = max(1, min(MAX_POINTS, n // 10))
        return min(rows, MAX_POINTS, max(MIN_POINTS, math.ceil(n / 100))), rows

    def identifiers(self, connectors: list[str]) -> set[str]:
        out: set[str] = set()
        for c in connectors:
            out |= self.ids.get(c, set())
        return out


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


def _norm_value(v: Any) -> str | None:
    """A value as an identifier is compared: a stripped string, an integer's digits; None for anything else."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return str(v) if len(str(abs(v))) >= _ID_INT_DIGITS else None
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and len(str(abs(int(v)))) >= _ID_INT_DIGITS else None
    s = str(v).strip()
    return s or None


def _is_number(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _columns_of_rows(header: list[str], rows: list[list[Any]]) -> dict[str, list[Any]]:
    return {str(h): [r[i] if i < len(r) else None for r in rows] for i, h in enumerate(header)}


def _csv_columns(p: Path) -> dict[str, list[Any]] | None:
    try:
        with p.open(newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter="\t" if p.suffix.lower() == ".tsv" else ",")
            header = next(reader, [])
            rows = [r for _, r in zip(range(_SOURCE_ROWS_READ), reader, strict=False)]
    except (OSError, csv.Error):
        return None
    return _columns_of_rows(header, rows)


def _source_columns(folder: Path, load: dict[str, Any]) -> list[dict[str, list[Any]]]:
    """The columns of what one load brought in, read from the folder (its saved file, its tables in data.db)."""
    out: list[dict[str, list[Any]]] = []
    saved = load.get("saved_to")
    if isinstance(saved, str):
        for p in (folder / saved, folder / "data" / Path(saved).name, folder / Path(saved).name):
            if p.is_file() and p.suffix.lower() in (".csv", ".tsv"):
                cols = _csv_columns(p)
                if cols is not None:
                    out.append(cols)
                break
    tables = [t for t in [load.get("table"), *(load.get("tables") or [])] if isinstance(t, str) and t]
    if tables:
        for db in (folder / "data" / "data.db", folder / "data.db"):
            if not db.is_file():
                continue
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            except sqlite3.Error:
                continue
            try:
                for t in tables:
                    try:
                        cur = con.execute(
                            f'SELECT * FROM "{t.replace(chr(34), chr(34) * 2)}" LIMIT {_SOURCE_ROWS_READ}'
                        )
                    except sqlite3.Error:
                        continue
                    header = [d[0] for d in cur.description or ()]
                    out.append(_columns_of_rows(header, [list(r) for r in cur.fetchall()]))
            finally:
                con.close()
            break
    return out


def _identifier_values(name: str, values: list[Any]) -> set[str]:
    """The values of a column that identifies its rows (all distinct, two or more), else none."""
    present = [v for v in values if v is not None and str(v).strip() != ""]
    if len(present) < 2:
        return set()
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present) or (
        all(isinstance(v, str) for v in present) and all(re.fullmatch(r"-?\d+", v.strip()) for v in present)
    ):
        ints = [int(str(v).strip()) for v in present]
        if len(set(ints)) != len(ints) or not _ID_INT_NAME.search(name):
            return set()
        return {s for s in (_norm_value(i) for i in ints) if s}
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return set()
    strings = [str(v).strip() for v in present]
    if len(set(strings)) != len(strings) or any(_is_number(s) for s in strings):
        return set()
    return {s for s in strings if len(s) >= 2}


def _all_values(columns: list[dict[str, list[Any]]]) -> set[str]:
    out: set[str] = set()
    for cols in columns:
        for values in cols.values():
            for v in values:
                s = _norm_value(v) if not isinstance(v, str) else v.strip()
                if s:
                    out.add(s)
    return out


def shape(folder: Path, restricted: set[str], extra: list[tuple[Path, list[str]]] | None = None) -> Shape:
    """Rows and identifier values of the folder's restricted sources (read from what the folder holds).

    ``extra``: data files built from those sources, with their connectors (data/gaia_clean.csv): their
    identifier columns count as the sources' too, for a folder that does not hold the sources' own rows.
    """
    folder = Path(folder)
    out = Shape()
    open_values: set[str] | None = None
    open_loads = [e for e in _loads(folder) if e.get("connector") not in restricted]
    pending: list[tuple[str, list[dict[str, list[Any]]]]] = []
    for e in _loads(folder):
        c = e.get("connector")
        if c not in restricted:
            continue
        c = str(c)
        rows = e.get("rows") if isinstance(e.get("rows"), int) else e.get("table_rows")
        if isinstance(rows, int) and rows > 0:
            out.rows[c] = out.rows.get(c, 0) + rows
        pending.append((c, _source_columns(folder, e)))
    for path, connectors in extra or []:
        cols = _csv_columns(path) if path.is_file() else None
        if cols:
            pending += [(c, [cols]) for c in connectors if c in restricted]
    for c, tables in pending:
        ids: set[str] = set()
        for cols in tables:
            for name, values in cols.items():
                ids |= _identifier_values(name, values)
        if ids:
            if open_values is None:
                open_values = set()
                for o in open_loads:
                    open_values |= _all_values(_source_columns(folder, o))
            out.ids.setdefault(c, set()).update(ids - open_values)
    return out


# ── one file ─────────────────────────────────────────────────────────────────


def _id_hit(value: Any, ids: set[str]) -> str | None:
    if not ids:
        return None
    s = value.strip() if isinstance(value, str) else _norm_value(value)
    return s if s and s in ids else None


def _is_point(v: Any) -> bool:
    """A value of a point array: a number, or a short list of numbers (a coordinate pair)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    return (
        isinstance(v, list)
        and 0 < len(v) <= 4
        and all((isinstance(x, (int, float)) and not isinstance(x, bool)) or x is None for x in v)
    )


def _json_row_level(doc: Any, points: int, ids: set[str], rows_max: int | None = None) -> str | None:
    """Why a JSON document holds rows (a long array, a large set of records, an identifier), or None."""
    rows_max = points if rows_max is None else rows_max
    stack: list[tuple[str, Any]] = [("", doc)]
    while stack:
        where, node = stack.pop()
        if isinstance(node, list):
            if len(node) > points:
                numbers = sum(1 for v in node if _is_point(v))
                records = sum(1 for v in node if isinstance(v, dict))
                if numbers > points:
                    return f"an array of {len(node):,} values at {where or 'the top'}"
                if records > rows_max:
                    return f"a list of {records:,} records at {where or 'the top'}"
            stack.extend((f"{where}[{i}]", v) for i, v in enumerate(node))
        elif isinstance(node, dict):
            if len(node) > rows_max:
                kinds = {frozenset(v) if isinstance(v, dict) else type(v).__name__ for v in node.values()}
                if len(kinds) == 1 and isinstance(next(iter(kinds)), frozenset) and next(iter(kinds)):
                    return f"{len(node):,} records of the same fields at {where or 'the top'}"
            for k, v in node.items():
                hit = _id_hit(k, ids)
                if hit:
                    return f"an identifier of the source, {hit}"
                stack.append((f"{where}.{k}" if where else str(k), v))
        else:
            hit = _id_hit(node, ids)
            if hit:
                return f"an identifier of the source, {hit}"
    return None


def _table_row_level(path: Path, rows_max: int, ids: set[str]) -> str | None:
    suffix = path.suffix.lower()
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            if suffix in (".txt", ".dat"):
                lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
                if len(lines) > rows_max:
                    return f"{len(lines):,} rows"
                cells = [c for ln in lines for c in re.split(r"[\s,;]+", ln.strip()) if c]
            else:
                reader = csv.reader(f, delimiter="\t" if suffix == ".tsv" else ",")
                next(reader, None)
                rows = list(reader)
                rows = [r for r in rows if any(c.strip() for c in r)]
                if len(rows) > rows_max:
                    return f"{len(rows):,} rows"
                cells = [c for r in rows for c in r]
    except (OSError, csv.Error) as e:
        return f"unreadable ({e})"
    for c in cells:
        hit = _id_hit(c, ids)
        if hit:
            return f"an identifier of the source, {hit}"
    return None


def _jsonl_row_level(path: Path, points: int, rows_max: int, ids: set[str]) -> str | None:
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError as e:
        return f"unreadable ({e})"
    if len(lines) > rows_max:
        return f"{len(lines):,} rows"
    for ln in lines:
        try:
            why = _json_row_level(json.loads(ln), points, ids, rows_max)
        except ValueError:
            return "a line that is not JSON"
        if why:
            return why
    return None


def _db_row_level(path: Path, rows_max: int, ids: set[str]) -> str | None:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return f"unreadable ({e})"
    try:
        names = [str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for name in names:
            cur = con.execute(f'SELECT * FROM "{name.replace(chr(34), chr(34) * 2)}" LIMIT {rows_max + 1}')
            rows = cur.fetchall()
            if len(rows) > rows_max:
                return f"a table {name} of more than {rows_max} rows"
            for r in rows:
                for v in r:
                    hit = _id_hit(v, ids)
                    if hit:
                        return f"an identifier of the source, {hit}"
    except sqlite3.Error as e:
        return f"unreadable ({e})"
    finally:
        con.close()
    return None


def row_level(path: Path, connectors: list[str], known: Shape) -> str | None:
    """Why ``path`` holds the sources' rows (in a few words), or None when it is an aggregate (module docstring)."""
    points, rows_max = known.limits(connectors)
    ids = known.identifiers(connectors)
    suffix = path.suffix.lower()
    if not path.is_file():
        return "not in the folder, so it cannot be read"
    if suffix in TABLE_SUFFIXES:
        return _table_row_level(path, rows_max, ids)
    if suffix == ".jsonl":
        return _jsonl_row_level(path, points, rows_max, ids)
    if suffix in JSON_SUFFIXES:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return "a JSON file that cannot be read"
        return _json_row_level(doc, points, ids, rows_max)
    if suffix in DB_SUFFIXES:
        return _db_row_level(path, rows_max, ids)
    return f"a {suffix or 'data'} file, whose rows e2er does not count"


def limits_words(connectors: list[str], known: Shape) -> str:
    points, rows_max = known.limits(connectors)
    return f"at most {rows_max} rows, arrays of at most {points} values, no identifier of the source"
