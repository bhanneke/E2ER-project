"""What the method checks of a template share: their verdict and how they read the study's data.

The difference-in-differences checks (``did_checks.py``) and the spatial checks
(``spatial_checks.py``) read a design file the specialists write, the tables
of the study's ``data.db`` and the files the analysis script writes. Each
returns a :class:`Verdict` and never raises on bad input: a missing or
malformed file is a failed check with the reason spelled out, so the
researcher can fix it at the step where the run stopped.
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

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: Ids named per reason; the rest are counted.
LISTED = 10


@dataclass(frozen=True)
class Verdict:
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


def names(ids: list[str]) -> str:
    """The first ids, and how many more."""
    shown = ", ".join(ids[:LISTED])
    return shown + (f" and {len(ids) - LISTED} more" if len(ids) > LISTED else "")


def num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def read_json(path: Path) -> tuple[Any, str | None]:
    """(parsed, None), or (None, why) when the file is missing or not JSON."""
    if not path.is_file():
        return None, f"{path.name} is missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"{path.name} is not valid JSON: {e}"


def write_json(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def plain_name(value: Any) -> str | None:
    """A table or column name that is safe to quote in SQL, else None."""
    s = str(value or "").strip()
    return s if _IDENT.match(s) else None


def read_columns(workspace: Path, table: Any, columns: list[Any]) -> tuple[list[tuple[Any, ...]] | None, str]:
    """The rows of ``columns`` in ``table`` of the study's data.db; (None, why) when they cannot be read."""
    from ...db.paper_data_db import data_db_path

    t = plain_name(table)
    cols = [plain_name(c) for c in columns]
    if t is None or any(c is None for c in cols):
        shown = ", ".join(str(c) for c in columns)
        return None, f"{table}.({shown}) is not a plain table and column name"
    db = data_db_path(workspace)
    if not db.is_file():
        return None, "there is no data.db yet"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            have = {r[1] for r in con.execute(f'PRAGMA table_info("{t}")').fetchall()}
            if not have:
                tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                return None, f"data.db has no table {t} (it has: {', '.join(tables) or 'none'})"
            missing = [c for c in cols if c not in have]
            if missing:
                return (
                    None,
                    f"table {t} has no column {', '.join(str(m) for m in missing)} (it has: {', '.join(sorted(have))})",
                )
            quoted = ", ".join(f'"{c}"' for c in cols)
            rows = con.execute(f'SELECT {quoted} FROM "{t}"').fetchall()  # noqa: S608 — identifiers checked above
        finally:
            con.close()
    except sqlite3.Error as e:
        return None, f"{t} cannot be read from data.db: {e}"
    return rows, ""


def read_csv(path: Path) -> tuple[list[dict[str, str]] | None, str]:
    """The rows of a CSV file as dicts; (None, why) when it cannot be read."""
    if not path.is_file():
        return None, f"{path.name} is missing"
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f)), ""
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        return None, f"{path.name} cannot be read: {e}"


def to_float(v: Any) -> float | None:
    """A number from a cell (text or number), else None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def close(a: float, b: float, rel: float = 0.01, abs_: float = 1e-6) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def obj(v: Any) -> dict[str, Any]:
    """``v`` when it is a JSON object, else an empty one."""
    return v if isinstance(v, dict) else {}


def lst(v: Any) -> list[Any]:
    """``v`` when it is a JSON array, else an empty one."""
    return v if isinstance(v, list) else []
