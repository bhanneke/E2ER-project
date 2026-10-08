"""Studies: repeated runs of one research question, grouped as versions.

A researcher who re-runs a question (a new model, a fixed bug, a second
template) gets a new row in ``papers`` each time. The dashboard used to list
every row, so ten attempts at one question read as ten studies. Here a study is
the group of attempts that share a research question and a template:

* ``papers.study_key`` — derived from the normalised question plus the
  template (pipeline name). Filled for new rows and backfilled for old ones by
  :func:`ensure_study_keys`, which is idempotent.
* ``papers.study_override`` — set when the researcher moves an attempt to
  another study or splits it off. The effective study is
  ``COALESCE(study_override, study_key)``.
* ``papers.archived_at`` — hides an attempt from the default lists. Archiving
  only sets this column: files, workspaces and rows stay as they are.

The version of an attempt (v1, v2, …) is its position in its study by start
time, counted over all attempts, archived or not, so a number never changes
when something is archived.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..core.run_outcome import status_words, workspace_status

#: Statuses an attempt can be archived in: the run is over. An attempt's status
#: is its effective one (core/run_outcome.py): ``stopped`` is a check that
#: stopped the run (stored as ``rejected``).
ARCHIVABLE = ("completed", "failed", "cancelled", "stopped")

#: What the bulk action archives.
BULK_STATUSES = ("failed", "cancelled")

#: Order of the status summary ("2 completed · 5 failed · 2 stopped by a check").
_SUMMARY_ORDER = ("completed", "stopped", "failed", "cancelled", "paused")

_TRAILING = re.compile(r"[\s.?!,;:…。？！、]+$")
_SPACE = re.compile(r"\s+")


class StudyError(Exception):
    """An archive or move that was refused. The message is shown to the researcher."""


# ── the grouping key ─────────────────────────────────────────────────────────


def normalise_question(text: str | None) -> str:
    """Trim, collapse whitespace, case-fold and drop trailing punctuation."""
    s = _SPACE.sub(" ", (text or "").strip()).casefold()
    return _TRAILING.sub("", s)


def study_key(research_question: str | None, pipeline: str | None, title: str | None = None) -> str:
    """The study an attempt belongs to, before any override.

    Two attempts with the same question under different templates are
    different studies. A row without a question falls back to its title.
    """
    question = normalise_question(research_question) or normalise_question(title)
    template = (pipeline or "empirical").strip().casefold()
    return hashlib.sha256(f"{template}\n{question}".encode()).hexdigest()[:10]


def split_key() -> str:
    """A fresh study key for an attempt split off into a study of its own."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:10]


async def ensure_study_keys() -> int:
    """Fill ``study_key`` for rows that have none. Returns the number filled.

    Safe to call on every list: it only touches rows with a NULL key, and it
    does not change ``updated_at`` (the triggers skip bookkeeping columns).
    """
    from . import client

    rows = await client.fetch_all("SELECT id, title, research_question, pipeline FROM papers WHERE study_key IS NULL")
    for r in rows:
        await client.execute(
            "UPDATE papers SET study_key = %(k)s WHERE id = %(id)s AND study_key IS NULL",
            {"k": study_key(r.get("research_question"), r.get("pipeline"), r.get("title")), "id": str(r["id"])},
        )
    return len(rows)


# ── reading ──────────────────────────────────────────────────────────────────


@dataclass
class Study:
    key: str
    title: str
    template: str
    question: str
    attempts: list[dict[str, Any]] = field(default_factory=list)  # oldest first, all of them

    @property
    def visible(self) -> list[dict[str, Any]]:
        return [a for a in self.attempts if not a["archived"]]

    @property
    def archived(self) -> list[dict[str, Any]]:
        return [a for a in self.attempts if a["archived"]]

    def shown(self, show_archived: bool) -> list[dict[str, Any]]:
        return self.attempts if show_archived else self.visible

    def latest(self, show_archived: bool = False) -> dict[str, Any] | None:
        shown = self.shown(show_archived)
        return shown[-1] if shown else None

    def last_activity(self, show_archived: bool = False) -> str:
        return max((a["updated_at"] for a in self.shown(show_archived)), default="")

    def summary(self, show_archived: bool = False) -> str:
        """``2 completed · 5 failed · 2 stopped by a check`` over the shown attempts."""
        counts = Counter(a["status"] for a in self.shown(show_archived))
        order = [s for s in _SUMMARY_ORDER if s in counts] + sorted(s for s in counts if s not in _SUMMARY_ORDER)
        return " · ".join(f"{counts[s]} {status_words(s)}" for s in order)

    def as_dict(self, show_archived: bool = False) -> dict[str, Any]:
        latest = self.latest(show_archived)
        return {
            "key": self.key,
            "title": self.title,
            "template": self.template,
            "question": self.question,
            "attempts": len(self.shown(show_archived)),
            "total": len(self.attempts),
            "archived": len(self.archived),
            "latest_status": latest["status"] if latest else None,
            "latest_date": latest["updated_at"] if latest else None,
            "last_activity": self.last_activity(show_archived),
            "summary": self.summary(show_archived),
        }


def _ts(value: Any) -> str:
    return str(value)[:19].replace("T", " ") if value is not None else ""


def group(rows: list[dict[str, Any]]) -> dict[str, Study]:
    """Group attempt rows into studies and number the versions. Pure; used by tests."""
    studies: dict[str, Study] = {}
    ordered = sorted(rows, key=lambda r: (_ts(r.get("created_at")), str(r.get("id"))))
    for r in ordered:
        key = (
            r.get("study_override")
            or r.get("study_key")
            or study_key(r.get("research_question"), r.get("pipeline"), r.get("title"))
        )
        st = studies.get(key)
        if st is None:
            st = studies[key] = Study(key=key, title="", template="", question="")
        attempt: dict[str, Any] = {
            "id": str(r["id"]),
            "short_id": str(r["id"])[:8],
            "title": r.get("title") or "",
            "research_question": r.get("research_question") or "",
            # Whether the run finished, never a review result (run_outcome.py).
            "status": workspace_status(r.get("status"), r.get("workspace")),
            "template": r.get("pipeline") or "empirical",
            "backend": r.get("backend") or "",
            "model": r.get("model") or "",
            "created_at": _ts(r.get("created_at")),
            "updated_at": _ts(r.get("updated_at")),
            "archived": r.get("archived_at") is not None,
            "archived_at": _ts(r.get("archived_at")),
            "moved": bool(r.get("study_override")),
            "version": len(st.attempts) + 1,
        }
        st.attempts.append(attempt)
        # The latest attempt names the study.
        st.title = attempt["title"]
        st.template = attempt["template"]
        st.question = attempt["research_question"] or st.question
    return studies


_ATTEMPT_COLUMNS = (
    "id, title, research_question, status, pipeline, backend, model, created_at, updated_at, "
    "archived_at, study_key, study_override, workspace"
)


async def load() -> dict[str, Study]:
    """Every study, with all its attempts (archived ones included)."""
    from . import client

    await ensure_study_keys()
    rows = await client.fetch_all(f"SELECT {_ATTEMPT_COLUMNS} FROM papers")
    return group(rows)


def _matches(st: Study, q: str) -> bool:
    q = q.strip().casefold()
    if not q:
        return True
    if st.key.startswith(q):
        return True
    for a in st.attempts:
        if q in a["title"].casefold() or q in a["research_question"].casefold() or a["id"].startswith(q):
            return True
    return False


async def list_studies(q: str = "", show_archived: bool = False) -> tuple[list[Study], int]:
    """Studies to show, most recent activity first, and the number of archived attempts."""
    studies = await load()
    archived = sum(len(s.archived) for s in studies.values())
    shown = [s for s in studies.values() if (show_archived or s.visible) and _matches(s, q)]
    shown.sort(key=lambda s: s.last_activity(show_archived), reverse=True)
    return shown, archived


async def resolve_study(ref: str) -> Study:
    """A study by key, or the study of an attempt (full id or unique id prefix)."""
    studies = await load()
    ref = ref.strip().casefold()
    if ref in studies:
        return studies[ref]
    attempt = _find_attempt(studies, ref)
    for st in studies.values():
        if any(a["id"] == attempt["id"] for a in st.attempts):
            return st
    raise StudyError(f"No study {ref!r}.")  # pragma: no cover — _find_attempt raised first


def _find_attempt(studies: dict[str, Study], ref: str) -> dict[str, Any]:
    ref = ref.strip().casefold()
    hits = [
        a
        for st in studies.values()
        for a in st.attempts
        if a["id"] == ref or (len(ref) >= 4 and a["id"].startswith(ref))
    ]
    if not hits:
        raise StudyError(f"No study or run matches {ref!r}.")
    if len(hits) > 1:
        raise StudyError(f"{ref!r} matches {len(hits)} runs; give more of the id.")
    return hits[0]


async def find_attempt(ref: str) -> tuple[Study, dict[str, Any]]:
    """An attempt and its study, by full id or unique prefix (4+ characters)."""
    studies = await load()
    attempt = _find_attempt(studies, ref)
    for st in studies.values():
        if attempt in st.attempts:
            return st, attempt
    raise StudyError(f"No run {ref!r}.")  # pragma: no cover


# ── archiving ────────────────────────────────────────────────────────────────


def _blocker(attempt: dict[str, Any]) -> str:
    """Why an attempt cannot be archived, as a short phrase ("" when it can)."""
    status = attempt["status"]
    if status in ARCHIVABLE:
        return ""
    if status == "paused":
        return "paused and can still be resumed"
    if status == "data_approval":
        return "waiting for your data approval"
    return f"still running ({status.replace('_', ' ')})"


def _label(attempt: dict[str, Any]) -> str:
    return f"Run {attempt['version']}"


_ONLY_ENDED = "Only runs that have ended can be archived."


def refusal(attempt: dict[str, Any]) -> str:
    """Why this attempt may not be archived ("" when it may)."""
    why = _blocker(attempt)
    return f"{_label(attempt)} is {why}. {_ONLY_ENDED}" if why else ""


def study_refusal(attempts: list[dict[str, Any]]) -> str:
    """Why a whole study may not be archived ("" when it may)."""
    by_reason: dict[str, list[str]] = {}
    for a in attempts:
        why = _blocker(a)
        if why:
            by_reason.setdefault(why, []).append(_label(a))
    if not by_reason:
        return ""
    parts = []
    for why, labels in by_reason.items():
        names = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
        verb = "is" if len(labels) == 1 else "are"
        parts.append(f"{names} {verb} {why}")
    tail = " You can archive the others one by one." if any(not _blocker(a) for a in attempts) else ""
    return f"Nothing was archived: {'; '.join(parts)}. {_ONLY_ENDED}{tail}"


async def _set_archived(ids: list[str], archived: bool) -> None:
    from . import client

    for pid in ids:
        if archived:
            await client.execute(
                "UPDATE papers SET archived_at = NOW() WHERE id = %(id)s AND archived_at IS NULL",
                {"id": pid},
            )
        else:
            await client.execute("UPDATE papers SET archived_at = NULL WHERE id = %(id)s", {"id": pid})


async def archive_attempt(ref: str) -> dict[str, Any]:
    """Archive one attempt. Refuses a running or paused one."""
    _st, attempt = await find_attempt(ref)
    why = refusal(attempt)
    if why:
        raise StudyError(why)
    await _set_archived([attempt["id"]], True)
    return attempt


async def unarchive_attempt(ref: str) -> dict[str, Any]:
    _st, attempt = await find_attempt(ref)
    await _set_archived([attempt["id"]], False)
    return attempt


async def archive_study(ref: str) -> tuple[Study, int]:
    """Archive every attempt of a study. Refuses the whole study if one is running or paused."""
    st = await resolve_study(ref)
    why = study_refusal(st.attempts)
    if why:
        raise StudyError(why)
    ids = [a["id"] for a in st.visible]
    await _set_archived(ids, True)
    return st, len(ids)


async def unarchive_study(ref: str) -> tuple[Study, int]:
    st = await resolve_study(ref)
    ids = [a["id"] for a in st.archived]
    await _set_archived(ids, False)
    return st, len(ids)


async def failed_candidates() -> list[dict[str, Any]]:
    """Failed and cancelled attempts that are not archived yet, with their study titles."""
    studies = await load()
    out = []
    for st in studies.values():
        for a in st.visible:
            if a["status"] in BULK_STATUSES:
                out.append({**a, "study_key": st.key, "study_title": st.title})
    out.sort(key=lambda a: a["created_at"])
    return out


async def archive_failed(only: list[str] | None = None) -> list[dict[str, Any]]:
    """Archive failed and cancelled attempts; returns what was archived.

    ``only`` limits it to the ids the researcher saw and confirmed, so an
    attempt that failed after the count was shown is not swept in with them.
    """
    candidates = await failed_candidates()
    if only is not None:
        wanted = set(only)
        candidates = [a for a in candidates if a["id"] in wanted]
    await _set_archived([a["id"] for a in candidates], True)
    return candidates


# ── cancelling a stopped attempt ─────────────────────────────────────────────

#: Statuses a researcher can cancel from here: the run has stopped and waits.
CANCELLABLE = ("paused",)


async def cancel_attempt(ref: str, via: str = "dashboard") -> dict[str, Any]:
    """Cancel a paused attempt (budget pause, circuit breaker, or waiting at a researcher step).

    Sets the status to ``cancelled`` and records a ``researcher_action`` event
    (who, when, how), which the dossier lists as a researcher step. The
    workspace is left as it is. Refused when another live e2er process owns
    the attempt (src/core/run_owner.py), and for attempts that are running or
    already over. A run in progress in the current server is cancelled with
    the dashboard's Cancel button (``POST /api/papers/{id}/cancel``) instead.
    """
    from datetime import UTC, datetime

    from ..core import run_owner
    from . import client
    from .events import log_event

    _st, attempt = await find_attempt(ref)
    label = _label(attempt)
    row = await client.fetch_one(
        "SELECT status, run_owner, heartbeat_at, workspace, mode FROM papers WHERE id = %(id)s", {"id": attempt["id"]}
    )
    status = workspace_status((row or {}).get("status"), (row or {}).get("workspace"))
    if status in ARCHIVABLE:
        raise StudyError(f"{label} is already {status_words(status)}; there is nothing to cancel.")
    if status not in CANCELLABLE:
        raise StudyError(
            f"{label} is still running ({status.replace('_', ' ')}). Stop it with Cancel on its page, "
            "in the e2er that runs it."
        )
    owner = run_owner.parse_owner((row or {}).get("run_owner"))
    if owner:
        seen = await run_owner.last_seen(attempt["id"], (row or {}).get("heartbeat_at"))
        state = run_owner.owner_state(owner, seen)
        if state == "alive":
            raise StudyError(
                f"{label} is working in another e2er window ({run_owner.describe(owner)}). Cancel it there."
            )
        if state == "mine":
            raise StudyError(f"{label} is still winding down in this e2er. Try again in a moment.")

    step = _pending_step((row or {}).get("workspace"), attempt["id"], (row or {}).get("mode"))
    await client.execute(
        "UPDATE papers SET status = 'cancelled', last_error = %(e)s, run_owner = NULL "
        "WHERE id = %(id)s AND status = 'paused'",
        {"id": attempt["id"], "e": "Cancelled by the researcher."},
    )
    after = await client.fetch_one("SELECT status FROM papers WHERE id = %(id)s", {"id": attempt["id"]})
    if (after or {}).get("status") != "cancelled":
        raise StudyError(f"{label} changed status while cancelling; nothing was done. Reload and try again.")
    payload = {
        "action": "cancel",
        "step": step,
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by": "researcher",
        "via": via,
        "remark": "cancelled by the researcher",
        "previous_status": status,
    }
    await log_event(attempt["id"], "researcher_action", stage=step, payload=payload)
    return {**attempt, "status": "cancelled", "event": payload}


def _pending_step(workspace: Any, paper_id: str, mode: Any) -> str | None:
    """The researcher step a paused run waits at, if any (for the event record)."""
    if not workspace:
        return None
    try:
        from pathlib import Path

        from ..core.pipeline.state import PipelineState

        return PipelineState.load(Path(str(workspace)), paper_id, str(mode or "single_pass")).pending_review_stage
    except Exception:  # noqa: BLE001 — the record is useful without it
        return None


# ── moving ───────────────────────────────────────────────────────────────────


async def move_attempt(ref: str, target: str) -> str:
    """Move an attempt to another study (a key or an attempt id), or ``"new"`` to split it off.

    Returns the key of the study it now belongs to.
    """
    from . import client

    studies = await load()
    attempt = _find_attempt(studies, ref)
    row = await client.fetch_one(
        "SELECT study_key, research_question, pipeline, title FROM papers WHERE id = %(id)s", {"id": attempt["id"]}
    )
    own = (row or {}).get("study_key") or study_key(
        (row or {}).get("research_question"), (row or {}).get("pipeline"), (row or {}).get("title")
    )
    target = target.strip().casefold()
    if target == "new":
        dest = split_key()
    elif target in studies:
        dest = target
    else:  # an attempt id: move next to that attempt
        hit = _find_attempt(studies, target)
        dest = next(st.key for st in studies.values() if hit in st.attempts)
    override = None if dest == own else dest
    await client.execute(
        "UPDATE papers SET study_override = %(o)s WHERE id = %(id)s", {"o": override, "id": attempt["id"]}
    )
    return dest


async def attempt_context(paper_id: str) -> dict[str, Any] | None:
    """Study title, key, version and count for one attempt (for the paper page)."""
    try:
        studies = await load()
    except Exception:  # noqa: BLE001 — the paper page must render regardless
        return None
    for st in studies.values():
        for a in st.attempts:
            if a["id"] == paper_id:
                return {"key": st.key, "title": st.title, "version": a["version"], "of": len(st.attempts), **a}
    return None
