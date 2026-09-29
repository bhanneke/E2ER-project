"""``e2er list`` / ``e2er archive`` / ``e2er unarchive`` — studies from the terminal.

  e2er list                        one entry per study, newest activity first
  e2er list --attempts             …with each study's attempts (v1, v2, …)
  e2er list --archived             …including archived attempts
  e2er archive <paper_id>          archive one attempt
  e2er archive --study <key|id>    archive every attempt of a study
  e2er archive --failed            show the failed and cancelled attempts it would archive
  e2er archive --failed --yes      archive them
  e2er unarchive <paper_id>        bring an attempt back (or --study <key|id>)

These read and write the database directly (the same one the dashboard uses),
so they work without a running server. Archiving hides attempts; it never
deletes a row, a file or a workspace, and it refuses running or paused ones.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from .db import studies as st


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def format_list(studies: list[st.Study], n_archived: int, *, attempts: bool, archived: bool) -> str:
    """The text `e2er list` prints. Pure, for tests."""
    if not studies:
        if n_archived:
            return f"No studies to show ({n_archived} archived; --archived shows them).\n"
        return "No studies yet.\n"
    n_attempts = sum(len(s.shown(archived)) for s in studies)
    head = f"{len(studies)} stud{'y' if len(studies) == 1 else 'ies'} · {_plural(n_attempts, 'attempt')}"
    if n_archived and not archived:
        head += f" ({n_archived} archived not shown; --archived shows them)"
    lines = [head, ""]
    for s in studies:
        d = s.as_dict(archived)
        lines.append(s.title)
        latest = f"{d['latest_status']} {str(d['latest_date'] or '')[:16]}" if d["latest_status"] else "—"
        extra = f" · {d['archived']} archived" if d["archived"] and not archived else ""
        lines.append(f"  {s.key} · {s.template} · {_plural(d['attempts'], 'attempt')}{extra} · latest: {latest}")
        lines.append(f"  {d['summary']}")
        if attempts:
            for a in reversed(s.shown(archived)):
                model = "/".join(x for x in (a["backend"], a["model"]) if x) or "default"
                flag = "  [archived]" if a["archived"] else ""
                lines.append(
                    f"    v{a['version']:<3} {a['short_id']}  {a['status']:<10} {a['created_at'][:16]}  {model}{flag}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def list_studies(*, attempts: bool = False, archived: bool = False, q: str = "") -> int:
    studies, n_archived = _run(st.list_studies(q, show_archived=archived))
    print(format_list(studies, n_archived, attempts=attempts, archived=archived), end="")
    return 0


def archive(paper_id: str | None = None, *, study: str | None = None, failed: bool = False, yes: bool = False) -> int:
    try:
        if failed:
            return _archive_failed(yes)
        if study:
            s, n = _run(st.archive_study(study))
            print(f"Archived {_plural(n, 'attempt')} of “{s.title}” ({s.key}). Nothing was deleted.")
            return 0
        if not paper_id:
            print("Give a paper id, --study <key|id>, or --failed.", file=sys.stderr)
            return 2
        a = _run(st.archive_attempt(paper_id))
        print(
            f"Archived v{a['version']} ({a['short_id']}). "
            f"Nothing was deleted; `e2er unarchive {a['short_id']}` undoes it."
        )
        return 0
    except st.StudyError as e:
        print(str(e), file=sys.stderr)
        return 1


def _archive_failed(yes: bool) -> int:
    items = _run(st.failed_candidates())
    if not items:
        print("There are no failed or cancelled attempts to archive.")
        return 0
    verb = "Archiving" if yes else "Would archive"
    print(f"{verb} {_plural(len(items), 'failed or cancelled attempt')}:")
    for a in items:
        print(f"  {a['short_id']}  v{a['version']:<3} {a['status']:<10} {a['study_title'][:70]}")
    if not yes:
        print("\nThis was a dry run. Add --yes to archive them. Nothing is deleted either way.")
        return 0
    done = _run(st.archive_failed([a["id"] for a in items]))
    print(f"\nArchived {_plural(len(done), 'attempt')}. Nothing was deleted; `e2er list --archived` shows them.")
    return 0


def unarchive(paper_id: str | None = None, *, study: str | None = None) -> int:
    try:
        if study:
            s, n = _run(st.unarchive_study(study))
            print(f"Unarchived {_plural(n, 'attempt')} of “{s.title}” ({s.key}).")
            return 0
        if not paper_id:
            print("Give a paper id or --study <key|id>.", file=sys.stderr)
            return 2
        a = _run(st.unarchive_attempt(paper_id))
        print(f"Unarchived v{a['version']} ({a['short_id']}).")
        return 0
    except st.StudyError as e:
        print(str(e), file=sys.stderr)
        return 1
