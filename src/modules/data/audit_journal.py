"""The audit journal: how the e2er-* wrappers record their audit rows without writing the run database.

Why it exists. The wrappers (``e2er-data``, ``e2er-allium-query``) run in the AI CLI's
shell, inside a specialist's call. Under Codex that shell sits in a sandbox that may
write the study's workspace and nothing else. Up to 0.20 e2er gave Codex one more
writable folder, the run database's (``--add-dir ~/.e2er``), so the wrappers could
write their audit rows there; on Windows that extra folder made Codex refuse every
file edit (openai/codex#30009, tester report 2026-11-02). Now no CLI gets an extra
folder. Inside a call (``cli_support.run_env`` sets ``E2ER_AUDIT_JOURNAL``) the
wrappers append each audit write as one JSON line to a journal in the workspace,
``.e2er-audit-journal-<call>.jsonl``; e2er reads the journal while the call runs
(so a production query reaches the dashboard's approval list within seconds) and
once more after it, checks every line, writes the rows into the run database with
its own fixed SQL, and removes the journal. Claude Code, Codex and Gemini, on
macOS, Linux and Windows, all take this one path.

Security. The model can write this file: it lies in its workspace. With the extra
folder it could write the run database itself, every table of it; now it can only
put journal lines in front of :class:`JournalImporter`, which

* takes the four operations of :data:`OPERATIONS` with their fixed fields and types,
  and skips (and logs) every other line;
* writes every row under the call's own paper id, never the one a line names;
* never takes SQL, a table name or a path from a line: ``query_sql`` is stored as the
  audit record's text and never run, the statements are the fixed ones in audit.py;
* records an approval only as the automatic one of a feasibility query of the same
  paper; a production query still needs the researcher's approval in the dashboard,
  sealed over its id and SQL (approval_seal.py), which no journal line can give;
* reads at most :data:`MAX_BYTES` and :data:`MAX_LINES` per call.

Each call has its own journal file: specialists of one batch run side by side in one
workspace, and one call's clean-up must not remove another's lines.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

#: The environment variable that switches the wrappers to the journal: the absolute path of this call's journal.
ENV = "E2ER_AUDIT_JOURNAL"
#: A journal's file name: a dotfile in the workspace root (never exported, see export/bundle_files.py).
_NAME = re.compile(r"^\.e2er-audit-journal-[0-9a-f]{16}\.jsonl$")

#: What one call's journal may hold; the rest is skipped with a warning.
MAX_BYTES = 8 * 1024 * 1024
MAX_LINES = 5000
MAX_LINE_BYTES = 512 * 1024
#: How often e2er reads the journal while a call runs, in seconds.
FOLLOW_INTERVAL = 2.0

_MAX_TEXT = 200
_MAX_SQL = 200_000
_MAX_FIELDS = 1000
_MAX_ROWS = 10**15
_QUERY_TYPES = frozenset({"feasibility", "production"})
#: The only approval a wrapper records itself: the automatic one of a feasibility query (data/tools.py).
AUTO_APPROVAL = "auto_feasibility"


def new_journal_path(workspace: Path) -> Path:
    """A fresh journal path for one call in ``workspace`` (the file is created by the first wrapper write)."""
    return Path(workspace) / f".e2er-audit-journal-{secrets.token_hex(8)}.jsonl"


def active_journal() -> Path | None:
    """This process's journal when it runs inside a specialist's call, else None (write the database)."""
    raw = os.environ.get(ENV, "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not _NAME.match(path.name):
        # Not a name e2er gives: write nowhere rather than into a file someone else chose.
        raise RuntimeError(f"{ENV} does not name an e2er audit journal: {path.name!r}")
    return path


def append(op: str, **fields: Any) -> None:
    """Record one audit write in this call's journal (the wrapper side)."""
    path = active_journal()
    if path is None:
        raise RuntimeError(f"{ENV} is not set")
    line = json.dumps({"op": op, **fields}, ensure_ascii=False, default=str)
    # One write call per line in append mode, so lines of wrappers running side by side do not interleave.
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def _read_lines(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_BYTES]
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for raw in text.splitlines()[:MAX_LINES]:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def journal_has_approved_feasibility(paper_id: str, table: str) -> bool:
    """Whether this call's journal holds an auto-approved feasibility query of ``paper_id`` on ``table``.

    The feasibility-first guardrail reads the run database; a feasibility query run earlier in the
    same call may still sit in the journal (e2er imports it every few seconds). Same match as the
    guardrail's SQL: ``query_sql ILIKE '%table%'``.
    """
    path = active_journal()
    if path is None or not table:
        return False
    rows = _read_lines(path)
    needle = table.lower()
    feasibility = {
        r.get("id")
        for r in rows
        if r.get("op") == "query"
        and r.get("paper_id") == paper_id
        and r.get("query_type") == "feasibility"
        and needle in str(r.get("query_sql") or "").lower()
    }
    return any(r.get("op") == "approved" and r.get("id") in feasibility for r in rows)


# ── the e2er side: checking and importing ────────────────────────────────────


class _SkipLineError(ValueError):
    """A journal line that is not imported, with the reason."""


def _uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise _SkipLineError(f"{name} is not a string")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise _SkipLineError(f"{name} is not a UUID") from None


def _text(value: Any, name: str, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _SkipLineError(f"{name} is not a string of at most {limit} characters")
    return value


def _count(value: Any, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not -_MAX_ROWS < value < _MAX_ROWS:
        raise _SkipLineError(f"{name} is not a whole number")
    return value


def _fields(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > _MAX_FIELDS:
        raise _SkipLineError("fields_requested is not a list")
    return [_text(v, "fields_requested[]", 500) for v in value]


#: The operations a journal line may carry, with their fields. Anything else is skipped.
OPERATIONS: dict[str, frozenset[str]] = {
    "query": frozenset(
        {
            "id",
            "paper_id",
            "specialist",
            "query_sql",
            "query_type",
            "fields_requested",
            "aggregation_level",
            "estimated_rows",
        }
    ),  # fmt: skip
    "approved": frozenset({"id", "approved_by"}),
    "executed": frozenset({"id", "actual_rows"}),
    "approval_request": frozenset({"id", "query_record_id", "paper_id"}),
}


async def _query_of(record_id: str, paper_id: str) -> dict[str, Any] | None:
    from ...db.client import fetch_one

    return await fetch_one(
        "SELECT id, query_type FROM data_query_records WHERE id = %(id)s AND paper_id = %(pid)s",
        {"id": record_id, "pid": paper_id},
    )


async def _apply(row: dict[str, Any], paper_id: str) -> None:
    """Check one journal line and write it with audit.py's fixed statements; raises _SkipLineError to skip it."""
    from . import audit

    op = row.get("op")
    allowed = OPERATIONS.get(op) if isinstance(op, str) else None
    if allowed is None:
        raise _SkipLineError(f"unknown operation {op!r}")
    extra = set(row) - allowed - {"op"}
    if extra:
        raise _SkipLineError(f"unknown fields {sorted(extra)}")
    if "paper_id" in allowed and row.get("paper_id") != paper_id:
        raise _SkipLineError("names another paper than this call's")

    if op == "query":
        record_id = _uuid(row.get("id"), "id")
        query_type = row.get("query_type")
        if query_type not in _QUERY_TYPES:
            raise _SkipLineError("query_type is neither feasibility nor production")
        if await _query_of(record_id, paper_id) is not None:
            return  # imported already (the call's last read repeats lines the follower took)
        await audit._insert_query_record(
            record_id=record_id,
            paper_id=paper_id,
            specialist=_text(row.get("specialist"), "specialist"),
            query_sql=_text(row.get("query_sql"), "query_sql", _MAX_SQL),
            query_type=str(query_type),
            fields_requested=_fields(row.get("fields_requested", [])),
            aggregation_level=_text(row.get("aggregation_level"), "aggregation_level"),
            estimated_rows=_count(row.get("estimated_rows"), "estimated_rows", optional=True),
        )
    elif op == "approved":
        record_id = _uuid(row.get("id"), "id")
        if row.get("approved_by") != AUTO_APPROVAL:
            raise _SkipLineError("a wrapper records only the automatic approval of a feasibility query")
        found = await _query_of(record_id, paper_id)
        if found is None or found.get("query_type") != "feasibility":
            raise _SkipLineError("no feasibility query of this paper with this id")
        await audit._update_approved(record_id, AUTO_APPROVAL)
    elif op == "executed":
        record_id = _uuid(row.get("id"), "id")
        rows = _count(row.get("actual_rows"), "actual_rows")
        if rows is None or rows < 0:
            raise _SkipLineError("actual_rows is negative")
        if await _query_of(record_id, paper_id) is None:
            raise _SkipLineError("no query of this paper with this id")
        await audit._update_executed(record_id, rows)
    elif op == "approval_request":
        request_id = _uuid(row.get("id"), "id")
        record_id = _uuid(row.get("query_record_id"), "query_record_id")
        found = await _query_of(record_id, paper_id)
        if found is None or found.get("query_type") != "production":
            raise _SkipLineError("no production query of this paper with this id")
        from ...db.client import fetch_one

        if await fetch_one("SELECT id FROM data_approval_requests WHERE id = %(id)s", {"id": request_id}):
            return
        await audit._insert_approval_request(request_id, record_id, paper_id)


class JournalImporter:
    """Imports one call's journal into the run database: while the call runs, and once after it."""

    def __init__(self, path: Path, paper_id: str) -> None:
        self.path = Path(path)
        self.paper_id = paper_id
        self._offset = 0
        self._lines = 0
        self._capped = False
        self.imported = 0
        self.skipped = 0

    async def import_new(self) -> int:
        """Import the complete lines added since the last read; returns how many were imported."""
        if self._capped:
            return 0
        try:
            size = self.path.stat().st_size
        except OSError:
            return 0
        if size <= self._offset:
            return 0
        end = min(size, MAX_BYTES)
        try:
            with open(self.path, "rb") as f:
                f.seek(self._offset)
                chunk = f.read(end - self._offset)
        except OSError as e:
            logger.warning("audit journal %s not read: %s", self.path.name, e)
            return 0
        # Only complete lines: a wrapper may be writing the next one right now.
        cut = chunk.rfind(b"\n")
        if cut < 0:
            if end >= MAX_BYTES:
                self._cap(size)
            return 0
        done = 0
        for raw in chunk[: cut + 1].splitlines():
            self._lines += 1
            if self._lines > MAX_LINES:
                self._cap(size)
                break
            done += await self._import_line(raw)
        self._offset += cut + 1
        if end >= MAX_BYTES and size > self._offset:
            self._cap(size)
        return done

    def _cap(self, size: int) -> None:
        self._capped = True
        logger.warning(
            "audit journal %s: more than %d lines or %d bytes (%d bytes); the rest is not imported",
            self.path.name,
            MAX_LINES,
            MAX_BYTES,
            size,
        )

    async def _import_line(self, raw: bytes) -> int:
        if not raw.strip():
            return 0
        reason = ""
        if len(raw) > MAX_LINE_BYTES:
            reason = "line too long"
        else:
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                reason = "not a JSON line"
            else:
                if not isinstance(row, dict):
                    reason = "not a JSON object"
                else:
                    try:
                        await _apply(row, self.paper_id)
                    except _SkipLineError as e:
                        reason = str(e)
                    except Exception as e:  # noqa: BLE001 — the database's refusal skips the line, never the call
                        reason = f"{type(e).__name__}: {e}"
        if reason:
            self.skipped += 1
            logger.warning("audit journal %s line %d skipped: %s", self.path.name, self._lines, reason[:200])
            return 0
        self.imported += 1
        return 1

    async def follow(self, interval: float = FOLLOW_INTERVAL) -> None:
        """Import new lines every ``interval`` seconds until cancelled."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.import_new()
            except Exception as e:  # noqa: BLE001
                logger.warning("audit journal %s: %s", self.path.name, e)

    async def finish(self) -> None:
        """The call has ended: import what is left and remove the journal."""
        try:
            await self.import_new()
        except Exception as e:  # noqa: BLE001
            logger.warning("audit journal %s: %s", self.path.name, e)
        with suppress(OSError):
            self.path.unlink()
        if self.imported or self.skipped:
            logger.info("audit journal %s: %d row(s) imported, %d skipped", self.path.name, self.imported, self.skipped)
