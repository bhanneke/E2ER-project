"""Checks of a descriptive study: the loaded data before the analysis, the figures after it.

A descriptive study stands or falls with its data and its figures: a count
that includes duplicate rows, a mean over a column with half its values
missing, a variable whose unit nobody wrote down, or a figure drawn from
numbers that are not the data all go straight into the paper. The two checks
here are deterministic and run as steps of the descriptive template
(``pipelines/descriptive-study.toml``); the time-series template uses the
figure check too.

``data_quality`` (inside the dispatch, after the data analyst and before the
analysis) reads every table ``data_dictionary.json`` declares from ``data.db``
and writes ``data_quality.json`` and ``data_quality.md``: rows, duplicates,
missing values per column, the unit of every numeric column, and the range of
date and coverage columns. It fails when

- a declared table is not in ``data.db`` or has no rows, or a declared column
  is not in the table;
- a numeric column has no ``unit`` in the dictionary (``"unit": "none"`` for
  counts, codes and identifiers);
- rows repeat: on the table's declared ``key`` (a list of columns), or, without
  a key, as whole rows;
- a column misses more than ``max_missing_share`` (default 0.05) of its values
  and the dictionary does not say why and how the analysis treats it
  (``"missing": "<why, and what the analysis does>"``);
- the table declares a ``coverage`` (``{"column", "from", "to"}``) its data do
  not span.

``figure_data`` (a step after the estimation check) re-reads every figure of
``figure_spec.json`` from the data it names in ``source`` and fails when a
figure names none or its values are not those data:

- ``{"table": "<data.db table>", "columns": {"x": "<column>", ...}, "where": "<condition>"}``:
  the figure's fields (``x``, ``y``, ``groups``, ``values``, ``categories``) are
  the table's columns, row for row (in any order; rows with an empty mapped
  column are left out; ``where`` is a simple condition on the table's columns);
- ``{"results": "<path>", "fields": {"x": "<key>", ...}, "file": "estimation_results.json"}``:
  the fields are the keys of a list of objects in a results file, e.g.
  ``forecasts.ets.points``; a histogram with ``{"results": "distributions.radius.bins"}``
  shows exactly those bins.

Numbers are compared at the precision the figure states (a value written with
three decimals matches the data rounded to three decimals). A time-series
figure names a source per series.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DATA_DICTIONARY_FILE = "data_dictionary.json"
DATA_DB = "data.db"
DATA_QUALITY_JSON = "data_quality.json"
DATA_QUALITY_MD = "data_quality.md"
FIGURE_SPEC_FILE = "figure_spec.json"
FIGURE_CHECK_FILE = "figure_check.json"
DEFAULT_MAX_MISSING_SHARE = 0.05

#: Results files a figure may name as its source (top-level files of the study).
RESULT_FILES = (
    "estimation_results.json",
    "summary_statistics.json",
    "robustness_results.json",
    "data_quality.json",
)
_NUMERIC_TYPES = ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")
_LISTED = 8


@dataclass(frozen=True)
class CheckResult:
    """A check's verdict: the shape every gate records (``gate_enforced`` / ``gate_shadow``)."""

    passed: bool
    reasons: tuple[str, ...] = ()  # why it failed; empty when it passed
    notes: tuple[str, ...] = ()  # what a reader should know even when it passed
    stats: dict[str, Any] = field(default_factory=dict, hash=False)

    def detail(self) -> str:
        """One line per reason and note, for the gate event and the dossier."""
        if self.passed:
            head = "passed: " + ", ".join(f"{k}={v}" for k, v in self.stats.items())
            return "; ".join([head, *self.notes])
        return "; ".join([*self.reasons, *self.notes])


def _names(items: Iterable[str]) -> str:
    items = list(items)
    shown = ", ".join(items[:_LISTED])
    return shown + (f" and {len(items) - _LISTED} more" if len(items) > _LISTED else "")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _connect(workspace: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(workspace) / DATA_DB}?mode=ro", uri=True)


def _is_numeric_type(sql_type: str) -> bool:
    t = (sql_type or "").upper()
    return any(n in t for n in _NUMERIC_TYPES)


def _is_date_like(name: str, sql_type: str) -> bool:
    from ..specialists.contract_check import _is_date_column

    return _is_date_column(name, sql_type)


def _table_columns(con: sqlite3.Connection, table: str) -> dict[str, str]:
    """column -> declared SQL type of a data.db table ({} when there is no such table)."""
    return {str(r[1]): str(r[2] or "") for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _empty(column: str) -> str:
    """SQL for 'this value is missing': NULL, an empty string, or a NaN stored as text."""
    c = _quote(column)
    return f"({c} IS NULL OR (typeof({c}) = 'text' AND trim({c}) IN ('', 'NA', 'NaN', 'nan', 'null', 'None')))"


# ── data quality ────────────────────────────────────────────────────────────


def _column_unit(col: dict[str, Any]) -> str:
    return str(col.get("unit") or col.get("units") or "").strip()


def check_data_quality(workspace: Path, *, max_missing_share: float = DEFAULT_MAX_MISSING_SHARE) -> CheckResult:
    """The loaded data, table by table: units, duplicates, missing values, coverage (module docstring)."""
    ws = Path(workspace)
    try:
        dictionary = _read_json(ws / DATA_DICTIONARY_FILE)
    except (OSError, ValueError) as e:
        return CheckResult(False, (f"{DATA_DICTIONARY_FILE} is missing or not valid JSON ({e})",))
    tables = [
        t for t in (dictionary.get("tables") if isinstance(dictionary, dict) else None) or [] if isinstance(t, dict)
    ]
    if not tables:
        return CheckResult(False, (f"{DATA_DICTIONARY_FILE} declares no tables (a 'tables' list with columns)",))
    if not (ws / DATA_DB).is_file():
        return CheckResult(False, (f"there is no {DATA_DB}: the data analyst has not loaded the declared tables",))

    reasons: list[str] = []
    notes: list[str] = []
    report: dict[str, Any] = {"max_missing_share": max_missing_share, "tables": {}}
    con = _connect(ws)
    try:
        for t in tables:
            name = str(t.get("name") or "").strip()
            if not name:
                reasons.append(f"a table in {DATA_DICTIONARY_FILE} has no name")
                continue
            actual = _table_columns(con, name)
            if not actual:
                reasons.append(f"table {name} is declared but not in {DATA_DB}")
                continue
            n_rows = int(con.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0])  # noqa: S608
            entry: dict[str, Any] = {"rows": n_rows, "columns": {}}
            report["tables"][name] = entry
            if n_rows == 0:
                reasons.append(f"table {name} has no rows")
                continue

            declared = {str(c.get("name")): c for c in t.get("columns") or [] if isinstance(c, dict) and c.get("name")}
            if not declared:
                reasons.append(
                    f"table {name}: {DATA_DICTIONARY_FILE} lists no 'columns'; declare each column with its type "
                    "and, for numbers, its unit"
                )
            absent = [c for c in declared if c not in actual]
            if absent:
                reasons.append(f"table {name}: declared column(s) {_names(absent)} are not in the table")

            # Units: every numeric column the dictionary declares names its unit.
            no_unit = []
            for col_name, col in declared.items():
                sql_type = str(col.get("type") or actual.get(col_name, ""))
                if col_name in actual and _is_numeric_type(sql_type) and not _is_date_like(col_name, sql_type):
                    if not _column_unit(col):
                        no_unit.append(col_name)
            if no_unit:
                reasons.append(
                    f"table {name}: numeric column(s) {_names(no_unit)} have no unit in {DATA_DICTIONARY_FILE} "
                    '(write "unit": e.g. "days", "Earth radii", "degrees C"; "none" for counts, codes and ids)'
                )

            # Duplicates: on the declared key, or whole rows.
            key = t.get("key")
            key_cols = [str(k) for k in key] if isinstance(key, list) and key else []
            bad_key = [k for k in key_cols if k not in actual]
            if bad_key:
                reasons.append(f"table {name}: key column(s) {_names(bad_key)} are not in the table")
                key_cols = []
            cols_sql = ", ".join(_quote(c) for c in (key_cols or list(actual)))
            distinct = int(
                con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {cols_sql} FROM {_quote(name)})").fetchone()[0]  # noqa: S608
            )
            dups = n_rows - distinct
            entry["key"] = key_cols or None
            entry["duplicate_rows"] = dups
            if dups:
                on = f"on the key ({', '.join(key_cols)})" if key_cols else "as whole rows"
                reasons.append(
                    f"table {name}: {dups} of {n_rows} rows repeat {on}; remove the duplicates when loading, "
                    "or declare the key that identifies a row"
                )

            # Missing values, per column of the table.
            over = []
            for col_name, sql_type in actual.items():
                missing = int(
                    con.execute(f"SELECT COUNT(*) FROM {_quote(name)} WHERE {_empty(col_name)}").fetchone()[0]  # noqa: S608
                )
                share = missing / n_rows
                col = declared.get(col_name, {})
                col_entry: dict[str, Any] = {
                    "type": str(col.get("type") or sql_type),
                    "missing": missing,
                    "missing_share": round(share, 4),
                }
                if _column_unit(col):
                    col_entry["unit"] = _column_unit(col)
                why = str(col.get("missing") or "").strip()
                if why:
                    col_entry["missing_note"] = why
                if share > max_missing_share and not why and col_name in declared:
                    # Only the columns the study declares (uses) must explain their gaps.
                    over.append(f"{col_name} ({missing} of {n_rows}, {share:.0%})")
                elif share > max_missing_share and why:
                    notes.append(f"{name}.{col_name}: {share:.0%} missing ({why})")
                # Range of date-like columns, for the coverage report.
                if _is_date_like(col_name, sql_type) and missing < n_rows:
                    lo, hi = con.execute(
                        f"SELECT MIN({_quote(col_name)}), MAX({_quote(col_name)}) FROM {_quote(name)} "  # noqa: S608
                        f"WHERE NOT {_empty(col_name)}"
                    ).fetchone()
                    col_entry["range"] = [lo, hi]
                entry["columns"][col_name] = col_entry
            if over:
                reasons.append(
                    f"table {name}: column(s) {_names(over)} miss more than {max_missing_share:.0%} of their values; "
                    f'say in {DATA_DICTIONARY_FILE} why and how the analysis treats them ("missing": "...")'
                )

            # Coverage the dictionary declares.
            cov = t.get("coverage")
            if isinstance(cov, dict) and cov.get("column"):
                col_name = str(cov["column"])
                if col_name not in actual:
                    reasons.append(f"table {name}: coverage column {col_name} is not in the table")
                else:
                    lo, hi = con.execute(
                        f"SELECT MIN({_quote(col_name)}), MAX({_quote(col_name)}) FROM {_quote(name)} "  # noqa: S608
                        f"WHERE NOT {_empty(col_name)}"
                    ).fetchone()
                    entry["coverage"] = {
                        "column": col_name,
                        "declared": [cov.get("from"), cov.get("to")],
                        "found": [lo, hi],
                    }
                    if cov.get("from") is not None and (lo is None or _before(cov["from"], lo)):
                        reasons.append(
                            f"table {name}: {col_name} starts at {lo}, after the declared coverage from {cov['from']}"
                        )
                    if cov.get("to") is not None and (hi is None or _before(hi, cov["to"])):
                        reasons.append(
                            f"table {name}: {col_name} ends at {hi}, before the declared coverage to {cov['to']}"
                        )
    except sqlite3.Error as e:
        reasons.append(f"{DATA_DB} could not be read: {e}")
    finally:
        con.close()

    _write_report(ws, report, reasons, notes)
    stats = {
        "tables": len(report["tables"]),
        "rows": sum(int(e.get("rows") or 0) for e in report["tables"].values()),
    }
    return CheckResult(not reasons, tuple(reasons), tuple(notes), stats)


def _before(a: Any, b: Any) -> bool:
    """a < b, numerically when both are numbers, else as text (ISO dates and periods sort as text)."""
    try:
        return float(a) < float(b)
    except (TypeError, ValueError):
        return str(a) < str(b)


def _write_report(ws: Path, report: dict[str, Any], reasons: list[str], notes: list[str]) -> None:
    report["passed"] = not reasons
    report["problems"] = list(reasons)
    (ws / DATA_QUALITY_JSON).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Data quality",
        "",
        "Written by e2er's data check from data.db and data_dictionary.json, before the analysis. "
        f"A column may miss up to {report['max_missing_share']:.0%} of its values without a note.",
        "",
    ]
    for name, e in report["tables"].items():
        lines += [f"## {name}", "", f"- Rows: {e.get('rows')}"]
        if "duplicate_rows" in e:
            on = f"on the key ({', '.join(e['key'])})" if e.get("key") else "as whole rows"
            lines.append(f"- Duplicate rows {on}: {e['duplicate_rows']}")
        if e.get("coverage"):
            c = e["coverage"]
            lines.append(
                f"- Coverage of {c['column']}: {c['found'][0]} to {c['found'][1]} "
                f"(declared {c['declared'][0]} to {c['declared'][1]})"
            )
        if e.get("columns"):
            lines += ["", "| Column | Type | Unit | Missing | Share | Range |", "|---|---|---|---:|---:|---|"]
            for col, c in e["columns"].items():
                rng = " to ".join(str(v) for v in c["range"]) if c.get("range") else ""
                lines.append(
                    f"| {col} | {c.get('type', '')} | {c.get('unit', '')} | {c['missing']} "
                    f"| {c['missing_share']:.1%} | {rng} |"
                )
            noted = [(col, c["missing_note"]) for col, c in e["columns"].items() if c.get("missing_note")]
            for col, why in noted:
                lines.append(f"\n{col}, missing values: {why}")
        lines.append("")
    if reasons:
        lines += ["## Problems", ""] + [f"- {r}" for r in reasons] + [""]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    (ws / DATA_QUALITY_MD).write_text("\n".join(lines), encoding="utf-8")


# ── figures from saved data ─────────────────────────────────────────────────

_WHERE_TOKEN = re.compile(
    r"\s*(?:(?P<num>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(?P<str>'[^']*')|(?P<op><>|!=|<=|>=|=|<|>|\(|\)|,)"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*))"
)
_WHERE_WORDS = frozenset({"AND", "OR", "NOT", "IS", "NULL", "IN", "BETWEEN", "LIKE"})


def _safe_where(where: str, columns: set[str]) -> str | None:
    """The condition when it uses only the table's columns, numbers, quoted text and comparisons; else None."""
    pos, out = 0, []
    text = where.strip()
    while pos < len(text):
        m = _WHERE_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            return None
        word = m.group("word")
        if word is not None:
            if word.upper() in _WHERE_WORDS:
                out.append(word.upper())
            elif word in columns:
                out.append(_quote(word))
            else:
                return None
        else:
            out.append(m.group(0).strip())
        pos = m.end()
    return " ".join(out) if out else None


def _decimals(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return 0
    if isinstance(v, int):
        return 0
    try:
        exp = Decimal(repr(v)).as_tuple().exponent
    except InvalidOperation:
        return 6
    return max(0, -int(exp)) if isinstance(exp, int) else 6


def _norm(value: Any, places: int | None) -> Any:
    """A value as the figure states it: numbers rounded to the figure's decimals, the rest as text."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        x = float(value)
        if not math.isfinite(x):
            return str(value)
        return round(x, places) if places is not None else x
    if isinstance(value, str):
        try:
            x = float(value)
        except ValueError:
            return value
        return round(x, places) if places is not None and math.isfinite(x) else value
    return "" if value is None else str(value)


def _numeric_field(values: list[Any]) -> bool:
    return bool(values) and all(isinstance(v, int | float) and not isinstance(v, bool) for v in values)


def _compare(
    figure_rows: list[tuple], data_rows: list[tuple], fields: list[str], numeric: list[bool], places: list[int]
) -> str | None:
    """None when the figure's rows are the data's rows (as multisets), else what differs."""
    if len(figure_rows) != len(data_rows):
        return f"the figure has {len(figure_rows)} points, the data {len(data_rows)}"

    def key(row: tuple) -> tuple:
        return tuple((0, v) if isinstance(v, float | int) else (1, str(v)) for v in row)

    fig = sorted(
        ([_norm(v, places[i] if numeric[i] else None) for i, v in enumerate(r)] for r in figure_rows),
        key=lambda r: key(tuple(r)),
    )
    dat = sorted(
        ([_norm(v, places[i] if numeric[i] else None) for i, v in enumerate(r)] for r in data_rows),
        key=lambda r: key(tuple(r)),
    )
    for a, b in zip(fig, dat, strict=True):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            if numeric[i] and isinstance(x, float) and isinstance(y, float):
                if abs(x - y) > 0.5 * 10 ** (-places[i]) + 1e-9 * max(1.0, abs(y)):
                    return f"{fields[i]}: the figure shows {x} where the data have {y}"
            elif str(x) != str(y):
                return f"{fields[i]}: the figure shows {x!r} where the data have {y!r}"
    return None


def _resolve(doc: Any, path: str) -> Any:
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _figure_rows(spec: dict[str, Any], fields: list[str]) -> tuple[list[tuple], str | None]:
    lists = []
    for f in fields:
        v = spec.get(f)
        if not isinstance(v, list):
            return [], f"the figure has no list '{f}'"
        lists.append(v)
    if len({len(v) for v in lists}) > 1:
        return [], f"the figure's lists {', '.join(fields)} differ in length"
    return list(zip(*lists, strict=True)), None


def _check_source(ws: Path, spec: dict[str, Any], where: str, con_holder: dict[str, Any]) -> str | None:
    """None when this figure (or series) shows the data its ``source`` names, else the problem."""
    source = spec.get("source")
    if not isinstance(source, dict):
        return f"{where} names no 'source' (a data.db table and columns, or a results path)"

    if source.get("table"):
        table = str(source["table"])
        cols = source.get("columns")
        if not isinstance(cols, dict) or not cols:
            return f"{where}: source.columns must map the figure's fields to the table's columns"
        if con_holder.get("con") is None:
            if not (ws / DATA_DB).is_file():
                return f"{where}: there is no {DATA_DB} to read {table} from"
            con_holder["con"] = _connect(ws)
        con: sqlite3.Connection = con_holder["con"]
        actual = _table_columns(con, table)
        if not actual:
            return f"{where}: table {table} is not in {DATA_DB}"
        fields = [str(f) for f in cols]
        columns = [str(cols[f]) for f in fields]
        missing = [c for c in columns if c not in actual]
        if missing:
            return f"{where}: column(s) {_names(missing)} are not in table {table}"
        conds = [f"NOT {_empty(c)}" for c in columns]
        if source.get("where"):
            safe = _safe_where(str(source["where"]), set(actual))
            if safe is None:
                return (
                    f"{where}: source.where must be a simple condition on {table}'s columns "
                    "(comparisons, AND/OR/NOT, IN, BETWEEN, LIKE, IS NULL)"
                )
            conds.append(f"({safe})")
        sql = f"SELECT {', '.join(_quote(c) for c in columns)} FROM {_quote(table)} WHERE {' AND '.join(conds)}"  # noqa: S608
        try:
            data_rows = [tuple(r) for r in con.execute(sql).fetchall()]
        except sqlite3.Error as e:
            return f"{where}: reading {table} failed ({e})"
        fig_rows, err = _figure_rows(spec, fields)
        if err:
            return f"{where}: {err}"
        numeric = [_numeric_field([r[i] for r in fig_rows]) for i in range(len(fields))]
        places = [max((_decimals(r[i]) for r in fig_rows), default=0) for i in range(len(fields))]
        diff = _compare(fig_rows, data_rows, fields, numeric, places)
        return f"{where}: not the data of {table} ({diff})" if diff else None

    if source.get("results"):
        name = str(source.get("file") or "estimation_results.json")
        if name not in RESULT_FILES:
            return f"{where}: source.file must be one of {', '.join(RESULT_FILES)}"
        try:
            doc = _read_json(ws / name)
        except (OSError, ValueError):
            return f"{where}: {name} is missing or not valid JSON"
        path = str(source["results"])
        items = _resolve(doc, path)
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            return f"{where}: {name} has no list of entries at {path}"
        mapping = source.get("fields")
        if not mapping:
            if spec.get("figure_type") == "histogram":
                mapping = {"lower": "lower", "upper": "upper", "count": "count"}
                raw_bins = spec.get("bins")
                bins: list[Any] = raw_bins if isinstance(raw_bins, list) else []
                spec = {
                    "lower": [b.get("lower") for b in bins if isinstance(b, dict)],
                    "upper": [b.get("upper") for b in bins if isinstance(b, dict)],
                    "count": [b.get("count") for b in bins if isinstance(b, dict)],
                }
            else:
                return f"{where}: source.fields must map the figure's fields to the keys of {path}"
        if not isinstance(mapping, dict):
            return f"{where}: source.fields must be an object"
        fields = [str(f) for f in mapping]
        keys = [str(mapping[f]) for f in fields]
        data_rows = []
        for i, item in enumerate(items):
            if any(k not in item for k in keys):
                return f"{where}: {path}[{i}] lacks {', '.join(k for k in keys if k not in item)}"
            data_rows.append(tuple(item[k] for k in keys))
        fig_rows, err = _figure_rows(spec, fields)
        if err:
            return f"{where}: {err}"
        numeric = [_numeric_field([r[i] for r in fig_rows]) for i in range(len(fields))]
        places = [max((_decimals(r[i]) for r in fig_rows), default=0) for i in range(len(fields))]
        diff = _compare(fig_rows, data_rows, fields, numeric, places)
        return f"{where}: not the values of {name} {path} ({diff})" if diff else None

    return f"{where}: source must name a data.db 'table' or a 'results' path"


def _parts(fig: dict[str, Any], name: str) -> list[tuple[str, dict[str, Any]]]:
    """(where, spec) for each part a source belongs to: the figure, each series, each panel."""
    ftype = str(fig.get("figure_type") or "")
    if ftype == "multi_panel":
        out = []
        for i, p in enumerate(fig.get("panels") or []):
            if isinstance(p, dict):
                out += _parts(p, f"{name} panel {i + 1}")
        return out
    if ftype == "time_series":
        return [
            (f"{name} series {s.get('label') or i + 1}", s)
            for i, s in enumerate(fig.get("series") or [])
            if isinstance(s, dict)
        ]
    return [(name, fig)]


def check_figure_data(workspace: Path) -> CheckResult:
    """Every figure of figure_spec.json against the data or results it names (module docstring)."""
    ws = Path(workspace)
    path = ws / FIGURE_SPEC_FILE
    if not path.is_file():
        return CheckResult(False, (f"there is no {FIGURE_SPEC_FILE}: the study shows no figure",))
    try:
        spec = _read_json(path)
    except ValueError as e:
        return CheckResult(False, (f"{FIGURE_SPEC_FILE} is not valid JSON: {e}",))
    figures = [f for f in (spec.get("figures") if isinstance(spec, dict) else None) or [] if isinstance(f, dict)]
    if not figures:
        return CheckResult(False, (f"{FIGURE_SPEC_FILE} lists no figures",))
    reasons: list[str] = []
    checked: list[dict[str, Any]] = []
    holder: dict[str, Any] = {"con": None}
    try:
        for i, fig in enumerate(figures):
            name = str(fig.get("filename") or f"figure {i + 1}")
            parts = _parts(fig, name)
            if not parts:
                reasons.append(f"{name} has nothing to check (no series or panels)")
            for where, part in parts:
                problem = _check_source(ws, part, where, holder)
                checked.append({"figure": where, "source": part.get("source"), "matches": problem is None})
                if problem:
                    reasons.append(problem)
    finally:
        if holder.get("con") is not None:
            holder["con"].close()
    (ws / FIGURE_CHECK_FILE).write_text(
        json.dumps({"passed": not reasons, "figures": checked, "problems": reasons}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return CheckResult(not reasons, tuple(reasons), (), {"figures": len(figures), "parts": len(checked)})
