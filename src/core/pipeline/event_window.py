"""The event-window check: a financial event study's design, verified before estimation.

An abnormal-return event study stands on three things that can be checked
mechanically before any model is estimated, and that a reviewer otherwise finds
only after the paper is written:

  (a) the estimation window ends before the event window starts, with a gap,
      and is long enough to estimate the market model;
  (b) events of the same firm or asset do not overlap in their event windows,
      or the design says how overlaps are treated (drop, cluster, aggregate);
  (c) every event date is a trading day of the data, and the windows around it
      fit inside the data.
  (d) when the design names the researcher's own event table (`events_source`),
      its event dates are exactly that table's dates, each moved to the next
      trading day when it falls on a day without trading.

The design comes from ``event_design.json``, which the identification
strategist writes next to ``identification_spec.json`` in templates that ask for
it (see ``skills/files/econometrics/event-study.md`` and
``docs/schemas/event_design.schema.json``). Windows
are in trading days relative to the event day 0, counted on the data calendar
the design names: a table and date column in the paper's ``data.db``.

The check returns a verdict with every reason, never raises on a bad design:
a missing or malformed file is a failed check with the reason spelled out, so
the researcher can fix it at the step where the run stopped.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

EVENT_DESIGN_FILE = "event_design.json"

#: Defaults, each overridable in the template (`[steps.settings]` of the gate).
DEFAULTS: dict[str, float] = {
    "min_estimation_days": 120,
    "min_gap_days": 10,
    "max_overlap_share": 0.0,
}

#: Declared treatments that make overlapping events acceptable.
OVERLAP_TREATMENTS: frozenset[str] = frozenset({"drop", "cluster", "aggregate"})

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LISTED = 10  # event ids named per reason; the rest are counted


@dataclass(frozen=True)
class EventWindowResult:
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


def _names(ids: list[str]) -> str:
    shown = ", ".join(ids[:_LISTED])
    return shown + (f" and {len(ids) - _LISTED} more" if len(ids) > _LISTED else "")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _window(raw: Any) -> tuple[int, int] | None:
    if not isinstance(raw, dict):
        return None
    start, end = _int(raw.get("start")), _int(raw.get("end"))
    if start is None or end is None or start > end:
        return None
    return start, end


def _day(value: Any) -> date | None:
    """A calendar date from 'YYYY-MM-DD' or a timestamp string starting with it."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _load_dates(workspace: Path, spec: Any, field_name: str) -> tuple[list[date] | None, str]:
    """The distinct dates in the table and column ``spec`` names, from the paper's data.db."""
    from ...db.paper_data_db import data_db_path

    if not isinstance(spec, dict) or not spec.get("table") or not spec.get("date_column"):
        return None, f"event_design.json names no {field_name}.table and {field_name}.date_column"
    table, column = str(spec["table"]), str(spec["date_column"])
    if not _IDENT.match(table) or not _IDENT.match(column):
        return None, f"{field_name} {table}.{column} is not a plain table and column name"
    db = data_db_path(workspace)
    if not db.is_file():
        return None, "there is no data.db yet, so the event dates cannot be checked against the data"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(f'SELECT DISTINCT "{column}" FROM "{table}"').fetchall()  # noqa: S608 — identifiers checked above
        finally:
            con.close()
    except sqlite3.Error as e:
        return None, f"{field_name} {table}.{column} cannot be read from data.db: {e}"
    days = sorted({d for (v,) in rows if (d := _day(v)) is not None})
    if not days:
        return None, f"{field_name} {table}.{column} holds no dates"
    return days, f"{table}.{column}"


def load_calendar(workspace: Path, spec: Any) -> tuple[list[date] | None, str]:
    """The trading days the design names, from the paper's data.db; (None, why) when unavailable."""
    return _load_dates(workspace, spec, "calendar")


def _event_like_tables(workspace: Path) -> list[str]:
    """Tables in data.db that look like a researcher's event list: 'event' or 'announcement' in
    the name and a column with 'date' in its name. Used only to warn."""
    from ...db.paper_data_db import data_db_path

    db = data_db_path(workspace)
    if not db.is_file():
        return []
    found: list[str] = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            for name in names:
                low = name.lower()
                if ("event" not in low and "announcement" not in low) or not _IDENT.match(name):
                    continue
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{name}")')]
                dated = [c for c in cols if "date" in c.lower()]
                if dated:
                    found.append(f"{name} ({', '.join(dated)})")
        finally:
            con.close()
    except sqlite3.Error:
        return found
    return found


def _match_events_source(
    design_dates: list[date], source: list[date], calendar: list[date] | None
) -> tuple[list[str], list[str]]:
    """Rule (d): the design's event dates against the researcher's own event table.

    Returns (reasons, notes). A source date that is not a trading day maps to the
    next trading day of the calendar; each such mapping is a note. Missing, extra
    and shifted dates are each a reason.
    """
    mapped: dict[date, date] = {}
    notes: list[str] = []
    if calendar:
        for s in source:
            nxt = next((c for c in calendar if c >= s), None)
            mapped[s] = nxt if nxt is not None else s
        moved = [f"{s.isoformat()} → {t.isoformat()}" for s, t in mapped.items() if s != t]
        if moved:
            notes.append(f"(d) announcement dates moved to the next trading day: {', '.join(moved)}")
    else:
        mapped = {s: s for s in source}
    expected = set(mapped.values())
    got = set(design_dates)
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    # A design date close to a missing one is the same event on a shifted day.
    shifted: list[tuple[date, date]] = []
    for m in list(missing):
        near = sorted((abs((e - m).days), e) for e in extra if abs((e - m).days) <= 7)
        if near:
            e = near[0][1]
            shifted.append((m, e))
            missing.remove(m)
            extra.remove(e)
    reasons: list[str] = []
    if missing:
        reasons.append(
            f"(d) {len(missing)} event(s) of the researcher's table are missing from the design: "
            + _names([d.isoformat() for d in missing])
        )
    if extra:
        reasons.append(
            f"(d) {len(extra)} event(s) in the design are not in the researcher's table: "
            + _names([d.isoformat() for d in extra])
        )
    if shifted:
        reasons.append(
            f"(d) {len(shifted)} event(s) are on a different day than in the researcher's table: "
            + _names([f"{m.isoformat()} in the table, {e.isoformat()} in the design" for m, e in shifted])
        )
    return reasons, notes


def _weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def check_event_window(
    workspace: Path,
    *,
    min_estimation_days: int = int(DEFAULTS["min_estimation_days"]),
    min_gap_days: int = int(DEFAULTS["min_gap_days"]),
    max_overlap_share: float = DEFAULTS["max_overlap_share"],
    calendar: Iterable[date] | None = None,
) -> EventWindowResult:
    """Check ``event_design.json`` in ``workspace`` against rules (a) to (d).

    ``calendar`` replaces the data calendar the design names (tests, or a caller
    that already holds the trading days).
    """
    path = Path(workspace) / EVENT_DESIGN_FILE
    if not path.is_file():
        return EventWindowResult(
            False,
            (f"{EVENT_DESIGN_FILE} is missing: the identification strategist must declare the events and windows",),
        )
    try:
        design = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return EventWindowResult(False, (f"{EVENT_DESIGN_FILE} is not valid JSON: {e}",))
    if not isinstance(design, dict):
        return EventWindowResult(False, (f"{EVENT_DESIGN_FILE} must be a JSON object",))

    reasons: list[str] = []
    notes: list[str] = []
    stats: dict[str, Any] = {}

    # ── (a) the windows ─────────────────────────────────────────────────────
    est = _window(design.get("estimation_window"))
    raw_windows = design.get("event_windows")
    raw_windows = raw_windows if isinstance(raw_windows, list) else []
    evt_windows = [w for w in (_window(r) for r in raw_windows) if w is not None]
    if est is None:
        reasons.append("(a) estimation_window needs integer start <= end, in trading days relative to the event")
    if not evt_windows or len(evt_windows) != len(raw_windows):
        reasons.append("(a) event_windows needs at least one window, each with integer start <= end")
    first_evt = min(w[0] for w in evt_windows) if evt_windows else None
    last_evt = max(w[1] for w in evt_windows) if evt_windows else None
    if est is not None:
        length = est[1] - est[0] + 1
        stats["estimation_days"] = length
        if length < min_estimation_days:
            reasons.append(
                f"(a) the estimation window [{est[0]}, {est[1]}] has {length} trading days; "
                f"at least {min_estimation_days} are required"
            )
    if est is not None and first_evt is not None:
        gap = first_evt - est[1] - 1
        stats["gap_days"] = gap
        if est[1] >= first_evt:
            reasons.append(
                f"(a) the estimation window ends at {est[1]}, inside or after the event window starting at {first_evt}"
            )
        elif gap < min_gap_days:
            reasons.append(
                f"(a) {gap} trading day(s) between the estimation window (ends {est[1]}) and the event window "
                f"(starts {first_evt}); at least {min_gap_days} are required"
            )

    # ── the events ──────────────────────────────────────────────────────────
    raw_events = design.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        reasons.append("event_design.json declares no events")
        raw_events = []
    events: list[tuple[str, date, str]] = []
    undated: list[str] = []
    for i, ev in enumerate(raw_events):
        ev = ev if isinstance(ev, dict) else {}
        eid = str(ev.get("id") or f"event {i + 1}")
        d = _day(ev.get("date"))
        if d is None:
            undated.append(eid)
            continue
        # An event without an asset applies to every asset of the study, so it
        # can overlap with every other event: they share one key.
        events.append((eid, d, str(ev.get("asset") or ev.get("firm") or "*")))
    if undated:
        reasons.append(f"(c) {len(undated)} event(s) have no date in YYYY-MM-DD form: {_names(undated)}")
    stats["events"] = len(raw_events)

    # ── (c) the data calendar ───────────────────────────────────────────────
    if calendar is not None:
        days = sorted(set(calendar))
        source = "given calendar"
    else:
        days, source = load_calendar(Path(workspace), design.get("calendar"))  # type: ignore[assignment]
    exact = days is not None
    if not exact:
        reasons.append(f"(c) {source}")
        if events:
            # Overlap is still worth reporting; count on weekdays and say so.
            span = sorted(d for _e, d, _a in events)
            days = _weekdays(span[0] - timedelta(days=400), span[-1] + timedelta(days=60))
            notes.append("overlaps counted on a Monday-to-Friday calendar, since the data calendar is unavailable")
    else:
        stats["calendar"] = source
    position = {d: i for i, d in enumerate(days or [])}

    placed: list[tuple[str, int, str]] = []
    missing: list[str] = []
    for eid, d, asset in events:
        pos = position.get(d)
        if pos is None:
            missing.append(f"{eid} ({d.isoformat()})")
        else:
            placed.append((eid, pos, asset))
    if exact and missing:
        reasons.append(f"(c) {len(missing)} event date(s) are not trading days in {source}: {_names(missing)}")
    if exact and est is not None and last_evt is not None and days:
        short = [eid for eid, pos, _a in placed if pos + min(est[0], first_evt or 0) < 0 or pos + last_evt >= len(days)]
        if short:
            reasons.append(
                f"(c) {len(short)} event(s) have windows that run past the data "
                f"({days[0]} to {days[-1]}): {_names(short)}"
            )

    # ── (b) overlapping events ──────────────────────────────────────────────
    if first_evt is not None and last_evt is not None and placed:
        by_asset: dict[str, list[tuple[int, str]]] = {}
        for eid, pos, asset in placed:
            by_asset.setdefault(asset, []).append((pos, eid))
        # Market-wide events ("*") overlap with every asset's events.
        common = by_asset.pop("*", [])
        groups = [sorted(evs + common) for evs in by_asset.values()] or [sorted(common)]
        flagged: set[str] = set()
        for group in groups:
            for (p1, e1), (p2, e2) in zip(group, group[1:], strict=False):
                if p2 + first_evt <= p1 + last_evt:  # the later window starts before the earlier one ends
                    flagged.update({e1, e2})
        share = len(flagged) / len(placed)
        stats["overlapping"] = len(flagged)
        treatment = str(design.get("overlap_treatment") or "none").lower()
        if share > max_overlap_share:
            listed = _names(sorted(flagged))
            if treatment in OVERLAP_TREATMENTS:
                notes.append(
                    f"(b) {len(flagged)} of {len(placed)} events overlap ({listed}); "
                    f"the design treats them by {treatment!r}"
                )
            else:
                reasons.append(
                    f"(b) {len(flagged)} of {len(placed)} events ({share:.0%}) overlap in their event windows for the "
                    f"same asset: {listed}; the limit is {max_overlap_share:.0%} unless overlap_treatment is "
                    f"one of {', '.join(sorted(OVERLAP_TREATMENTS))}"
                )

    # ── (d) the researcher's own event table ────────────────────────────────
    source_spec = design.get("events_source")
    if source_spec:
        source_dates, where = _load_dates(Path(workspace), source_spec, "events_source")
        if source_dates is None:
            reasons.append(f"(d) {where}")
        else:
            stats["events_source"] = where
            r, n = _match_events_source([d for _e, d, _a in events], source_dates, days if exact else None)
            reasons += r
            notes += n
    else:
        candidates = _event_like_tables(Path(workspace))
        if candidates:
            notes.append(
                "(d) warning: the data holds a table that looks like the researcher's event list ("
                + ", ".join(candidates)
                + ") but event_design.json declares no events_source, so the events were not compared with it"
            )

    return EventWindowResult(not reasons, tuple(reasons), tuple(notes), stats)
