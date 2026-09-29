"""Which e2er server process owns a running paper.

A run lives inside the server process that started it. Two servers can share
one database (a study server on one port, the everyday dashboard on another),
and each one, when it starts, pauses the papers a stopped server left
"running". Before 0.12.1 it paused all of them, including a paper another live
server was still running.

So a run records its owner in ``papers.run_owner`` when it starts or resumes:
host, PID, the process start time, port and a per-process instance id. While
it runs, the owner refreshes ``papers.heartbeat_at`` every minute. Start-up
recovery then asks :func:`owner_state`:

* ``mine``    — this process (never the case at start-up).
* ``alive``   — the owner process still exists: same host, the PID is alive,
  and the process behind that PID started when the owner said it did. A PID
  whose start time differs was reused by another process after the owner
  died, so it counts as gone.
* ``gone``    — the owner is dead; the paper may be paused.
* ``unknown`` — nothing recorded (a row from an older e2er). Then the last
  sign of life decides: a heartbeat or pipeline event newer than
  :data:`STALE_AFTER` means someone may still be running it.

On another host the PID cannot be checked, so the heartbeat decides there too.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

#: Statuses that mean "work is in flight" in some server process.
IN_FLIGHT = (
    "idea",
    "designing",
    "data_collection",
    "in_progress",
    "ceiling_check",
    "self_attack",
    "polish",
    "review",
    "revision",
)

#: This server process. A new id every time a process starts.
INSTANCE_ID = uuid.uuid4().hex

#: A run without a heartbeat or event for this long counts as abandoned.
STALE_AFTER = timedelta(minutes=10)

#: How often a running paper's heartbeat is refreshed.
HEARTBEAT_SECONDS = 60.0

#: The port this server answers on, learnt from the first request.
PORT: int | None = None

_HOST = socket.gethostname()
_started_cache: dict[int, str | None] = {}


def process_started(pid: int) -> str | None:
    """When process ``pid`` started, as ``ps`` prints it, or None when unknown."""
    if pid == os.getpid() and pid in _started_cache:
        return _started_cache[pid]
    if os.name != "posix":
        return None
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    started = " ".join(out.stdout.split()) or None
    if pid == os.getpid():
        _started_cache[pid] = started
    return started


def pid_alive(pid: int) -> bool | None:
    """Does a process with this PID exist? None when it cannot be told (not POSIX)."""
    if os.name != "posix":
        return None  # os.kill(pid, 0) sends CTRL_C_EVENT on Windows
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, belongs to another user
    except OSError:
        return None
    return True


def this_owner(port: int | None = None) -> dict[str, Any]:
    """The owner record for a run started by this process."""
    pid = os.getpid()
    return {
        "instance": INSTANCE_ID,
        "host": _HOST,
        "pid": pid,
        "started": process_started(pid),
        "port": port or PORT,
    }


def parse_owner(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def parse_ts(value: Any) -> datetime | None:
    """A database timestamp as an aware UTC datetime (SQLite stores UTC text)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _fresh(last_seen: datetime | None, now: datetime) -> bool:
    return last_seen is not None and now - last_seen < STALE_AFTER


def owner_state(owner: dict[str, Any] | None, last_seen: datetime | None, now: datetime | None = None) -> str:
    """``mine`` / ``alive`` / ``gone`` / ``unknown`` — see the module docstring."""
    now = now or datetime.now(UTC)
    if not owner:
        return "unknown"
    if owner.get("instance") == INSTANCE_ID:
        return "mine"
    if owner.get("host") != _HOST:
        return "alive" if _fresh(last_seen, now) else "gone"
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return "alive" if _fresh(last_seen, now) else "gone"
    alive = pid_alive(pid)
    if alive is False:
        return "gone"
    if alive is None:
        return "alive" if _fresh(last_seen, now) else "gone"
    recorded, actual = owner.get("started"), process_started(pid)
    if recorded and actual and recorded != actual:
        return "gone"  # the PID now belongs to a different process
    return "alive"


def describe(owner: dict[str, Any]) -> str:
    """``PID 79092, port 8280`` for messages."""
    bits = [f"PID {owner.get('pid')}"]
    if owner.get("port"):
        bits.append(f"port {owner.get('port')}")
    if owner.get("host") and owner.get("host") != _HOST:
        bits.append(f"on {owner.get('host')}")
    return ", ".join(bits)


# ── database ─────────────────────────────────────────────────────────────────


async def claim(paper_id: str, port: int | None = None) -> None:
    """Record this process as the owner of ``paper_id``'s run, with a fresh heartbeat."""
    from ..db.client import execute

    try:
        await execute(
            "UPDATE papers SET run_owner = %(o)s, heartbeat_at = NOW() WHERE id = %(id)s",
            {"o": json.dumps(this_owner(port)), "id": paper_id},
        )
    except Exception as e:  # noqa: BLE001 — ownership is a safety net, not a reason to fail a run
        logger.warning("could not record the owner of paper %s: %s", paper_id, e)


async def release(paper_id: str) -> None:
    """Forget this process as the owner once its run has ended (leaves other owners alone)."""
    from ..db.client import execute

    try:
        await execute(
            "UPDATE papers SET run_owner = NULL WHERE id = %(id)s AND run_owner LIKE %(me)s",
            {"id": paper_id, "me": f'%"instance": "{INSTANCE_ID}"%'},
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("could not release paper %s: %s", paper_id, e)


async def beat(paper_ids: list[str]) -> None:
    from ..db.client import execute

    for pid in paper_ids:
        try:
            await execute("UPDATE papers SET heartbeat_at = NOW() WHERE id = %(id)s", {"id": pid})
        except Exception as e:  # noqa: BLE001
            logger.debug("heartbeat for %s skipped: %s", pid, e)


async def heartbeat_loop(running: dict[str, Any], interval: float = HEARTBEAT_SECONDS) -> None:
    """Refresh the heartbeat of every paper this process is running, until cancelled."""
    while True:
        await asyncio.sleep(interval)
        live = [pid for pid, task in list(running.items()) if not task.done()]
        if live:
            await beat(live)


async def last_seen(paper_id: str, heartbeat_at: Any = None) -> datetime | None:
    """The latest sign of life: the heartbeat or the newest pipeline event."""
    from ..db.client import fetch_one

    seen = parse_ts(heartbeat_at)
    try:
        row = await fetch_one(
            "SELECT MAX(created_at) AS last FROM pipeline_events WHERE paper_id = %(id)s", {"id": paper_id}
        )
    except Exception:  # noqa: BLE001
        row = None
    event = parse_ts((row or {}).get("last"))
    candidates = [t for t in (seen, event) if t is not None]
    return max(candidates) if candidates else None


async def running_elsewhere(paper: dict[str, Any], running_here: bool) -> dict[str, Any] | None:
    """Owner details when another live process is running this paper, else None.

    Only in-flight statuses count: a paused or finished paper runs nowhere.
    For a row without an owner (an older e2er started it), a sign of life
    within :data:`STALE_AFTER` is treated as running elsewhere.
    """
    if running_here or paper.get("status") not in IN_FLIGHT:
        return None
    owner = parse_owner(paper.get("run_owner"))
    seen = await last_seen(str(paper.get("id")), paper.get("heartbeat_at"))
    state = owner_state(owner, seen)
    if state == "alive" and owner is not None:
        return owner
    if state == "unknown" and seen is not None and _fresh(seen, datetime.now(UTC)):
        minutes = int((datetime.now(UTC) - seen).total_seconds() // 60)
        return {"legacy": True, "minutes": minutes}
    return None
