"""``e2er status`` / ``e2er cancel`` / ``e2er resume`` —
re-attach / stop / restart commands.

Closes the post-`e2er run` gap: when the run-tailer times out (or
the user ^C's it), they need a way to come back to the paper from
the terminal without opening the dashboard.

  e2er status <paper_id>          one-shot snapshot
  e2er status <paper_id> --tail   re-attach the tailer
  e2er cancel <paper_id>          stop a running paper
  e2er resume <paper_id>          restart a paused / failed paper
  e2er resume <paper_id> --max-cost 15   raise the cap while resuming

`status` and `cancel` talk to the local API server (or whatever
``E2ER_API_URL`` resolves to). They do NOT auto-start uvicorn —
"the server isn't running" is a different problem from "the paper
is in a weird state".

`resume` is different: the user is actively asking the paper to
start running again, so we DO auto-start uvicorn (same behaviour
as `e2er run`).
"""

from __future__ import annotations

import sys
import time

# Reused from cli_run to avoid duplicating connection logic. These
# helpers are also used by tests; importing here keeps the module
# graph flat.
from .cli_run import _api_reachable, _api_root, _poll_status


def _truncate(text: str, max_len: int) -> str:
    """Truncate with a trailing ellipsis when text exceeds max_len."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _format_money(value) -> str:
    """Format a dollar amount with 2 decimals (or `?` when unknown).

    The API returns cost as a float / Decimal / string depending on
    code path; coerce defensively. `$8.462921999999999` reads as
    floating-point noise to a user; `$8.46` is readable.
    """
    if value is None or value == "":
        return "?"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_status_summary(d: dict) -> str:
    """Build a human-readable status block from the GET /api/papers/{id} payload.

    Compact (≤ 12 lines) so it fits in a terminal window. The
    most important field — `status` — is on its own line at top.
    `last_error` is printed verbatim when present so the user can
    diagnose REJECTED / PAUSED / FAILED without parsing the events
    log.
    """
    status = d.get("status", "?")
    title = d.get("title") or "(untitled)"
    rq = d.get("research_question") or ""
    methodology = d.get("methodology") or "empirical"
    mode = d.get("mode") or "single_pass"
    workspace = d.get("workspace") or ""
    cap = d.get("max_cost_usd")
    last_error = d.get("last_error")
    usage = d.get("usage") or {}
    spent = usage.get("total_cost_usd")
    calls = usage.get("specialist_calls") or 0
    tokens = usage.get("total_tokens") or 0
    cost_is_estimate = usage.get("cost_is_estimate")

    lines = [
        f"Status:     {status}",
        f"Title:      {_truncate(title, 90)}",
        f"RQ:         {_truncate(rq, 90)}",
        f"Mode:       {mode} / {methodology}",
        f"Cost:       ${_format_money(spent)} / ${_format_money(cap)} cap"
        + (" (estimate — CLI backend)" if cost_is_estimate else ""),
        f"Specialists: {calls} calls, {tokens:,} tokens",
        f"Workspace:  {workspace}",
        f"Dashboard:  {_api_root()}/papers/{d.get('id', '')}",
    ]
    if last_error:
        lines.append(f"Last error: {_truncate(str(last_error), 120)}")
    return "\n".join(lines)


def _format_unreachable_error() -> str:
    """User-facing message when the API isn't running. Tells them what
    to try without making them guess at uvicorn syntax."""
    return (
        f"e2er: API server unreachable at {_api_root()}.\n"
        f"\n"
        f"  - If you just ran `e2er run`, the server may have shut down. "
        f'Submit a new paper with `e2er run "<RQ>"` to restart it.\n'
        f"  - Or start it manually:  e2er serve\n"
        f"  - To check a paper from another machine, set "
        f"E2ER_API_URL=http://<host>:8280 in your shell env."
    )


# ---------------------------------------------------------------------------
# e2er status
# ---------------------------------------------------------------------------


def status(paper_id: str, tail: bool = False, monitor_seconds: float = 1800.0) -> int:
    """Print the current status of a paper.

    With ``--tail``, reuse the same polling loop ``e2er run`` uses
    so the user can re-attach after ^C-ing the original tail.
    Returns shell exit code.
    """
    import httpx

    if not _api_reachable():
        print(_format_unreachable_error(), file=sys.stderr)
        return 3

    try:
        r = httpx.get(f"{_api_root()}/api/papers/{paper_id}", timeout=10.0)
    except Exception as e:
        print(f"e2er status: request failed: {e}", file=sys.stderr)
        return 3

    if r.status_code == 404:
        print(f"e2er status: paper {paper_id} not found", file=sys.stderr)
        return 4
    if r.status_code != 200:
        print(
            f"e2er status: GET /api/papers/{paper_id} returned {r.status_code}: {r.text[:300]}",
            file=sys.stderr,
        )
        return 5

    payload = r.json()
    print(_format_status_summary(payload))

    if tail:
        current_status = payload.get("status", "")
        terminal = {"completed", "failed", "cancelled", "paused", "rejected"}
        if current_status in terminal:
            # Already done — no point polling. Print a hint and exit clean.
            print(f"\n(Paper is already at terminal status {current_status!r}; --tail has nothing to wait for.)")
            return 0
        print()
        print(f"Polling status (max {monitor_seconds:.0f}s, ^C is safe):")
        try:
            final = _poll_status(paper_id, total_seconds=monitor_seconds)
        except KeyboardInterrupt:
            print("\n  ^C — paper continues in the background.", file=sys.stderr)
            return 0
        print(f"\n  Final status: {final}")
    return 0


# ---------------------------------------------------------------------------
# e2er cancel
# ---------------------------------------------------------------------------


def cancel(paper_id: str, yes: bool = False) -> int:
    """Cancel an in-flight paper via POST /api/papers/{id}/cancel.

    The runner's `asyncio.CancelledError` handler saves state.json
    and transitions the paper to CANCELLED with the reason
    "cancelled by user". The paper's workspace + completed-phase
    artifacts are preserved — a resume via `/api/papers/{id}/resume`
    would pick up where it left off.

    Without ``--yes``, prompts for confirmation first; CANCELLED is
    a terminal status (only IDEA can be reached from it) and the
    user doesn't usually want to discard the run by accident.
    """
    import httpx

    if not _api_reachable():
        print(_format_unreachable_error(), file=sys.stderr)
        return 3

    # Fetch first so we can show the user what they're about to cancel.
    try:
        r = httpx.get(f"{_api_root()}/api/papers/{paper_id}", timeout=10.0)
    except Exception as e:
        print(f"e2er cancel: lookup failed: {e}", file=sys.stderr)
        return 3
    if r.status_code == 404:
        print(f"e2er cancel: paper {paper_id} not found", file=sys.stderr)
        return 4

    payload = r.json()
    current_status = payload.get("status", "?")
    terminal = {"completed", "failed", "cancelled", "rejected"}
    if current_status in terminal:
        print(f"e2er cancel: paper is already at terminal status {current_status!r}; nothing to cancel.")
        return 0

    title = payload.get("title") or "(untitled)"
    print(f"About to cancel: {title[:80]}")
    print(f"  Paper ID: {paper_id}")
    print(f"  Current status: {current_status}")
    usage = payload.get("usage") or {}
    if usage:
        print(
            f"  Spent so far: ${usage.get('total_cost_usd') or 0} "
            f"across {usage.get('specialist_calls') or 0} specialist call(s)"
        )

    if not yes:
        try:
            answer = input("Cancel this paper? [y/N]: ").strip().lower()
        except EOFError:
            answer = "n"
        if answer not in {"y", "yes"}:
            print("Cancellation aborted; paper continues to run.")
            return 0

    try:
        r = httpx.post(f"{_api_root()}/api/papers/{paper_id}/cancel", timeout=10.0)
    except Exception as e:
        print(f"e2er cancel: POST failed: {e}", file=sys.stderr)
        return 3

    if r.status_code == 404:
        # Race: was running when we looked it up, then finished or got
        # cleared before we POSTed. Treat as success — the paper is no
        # longer in flight, which is what the user wanted.
        print(f"e2er cancel: paper {paper_id} no longer in flight.")
        return 0
    if r.status_code not in (200, 202):
        print(
            f"e2er cancel: POST returned {r.status_code}: {r.text[:300]}",
            file=sys.stderr,
        )
        return 5

    print("  ✓ Cancellation requested. Paper will transition to CANCELLED shortly.")
    print(f"  Dashboard: {_api_root()}/papers/{paper_id}")
    # Brief poll so the user sees the transition land before the shell
    # returns. The runner usually takes a few seconds to save state +
    # update the DB row.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        time.sleep(1.0)
        try:
            r = httpx.get(f"{_api_root()}/api/papers/{paper_id}", timeout=5.0)
            new_status = r.json().get("status", "?")
            if new_status in {"cancelled", "completed", "failed", "rejected"}:
                print(f"  ✓ Final status: {new_status}")
                return 0
        except Exception:
            continue
    print(
        "  (Status hasn't transitioned to `cancelled` yet — give it a few seconds, then `e2er status <id>` to confirm.)"
    )
    return 0


# ---------------------------------------------------------------------------
# e2er resume
# ---------------------------------------------------------------------------


def resume(
    paper_id: str,
    max_cost: float | None = None,
    tail: bool = False,
    monitor_seconds: float = 1800.0,
) -> int:
    """Resume a paused / failed / zombie paper.

    Unlike ``status`` and ``cancel``, this command auto-starts the
    local uvicorn if it isn't already up — the user is actively
    asking the paper to start running again, so they expect the
    server up. Same UX as ``e2er run``.

    Optional ``--max-cost`` raises the per-paper cap atomically
    with the resume request (v0.5+ ``ResumeRequest`` body support).
    The most common use case: a paper PAUSED on
    ``BudgetExceededError`` and the operator wants to give it
    more budget without two-step ``UPDATE`` + POST.

    With ``--tail``, re-uses ``_poll_status`` so the operator can
    watch the resumed paper to completion.
    """
    import httpx

    from .cli_run import _ensure_api_up

    ok, err = _ensure_api_up()
    if not ok:
        print(f"e2er resume: {err}", file=sys.stderr)
        return 3

    # Look up first so the prompt + log can show what's being resumed.
    try:
        r = httpx.get(f"{_api_root()}/api/papers/{paper_id}", timeout=10.0)
    except Exception as e:
        print(f"e2er resume: lookup failed: {e}", file=sys.stderr)
        return 3
    if r.status_code == 404:
        print(f"e2er resume: paper {paper_id} not found", file=sys.stderr)
        return 4

    payload = r.json()
    current_status = payload.get("status", "?")
    if current_status == "completed":
        # Genuinely done — no point resuming. Different from cancelled
        # (which IS resumable per the v0.4 state-machine softening).
        print("e2er resume: paper is already completed; nothing to resume.")
        return 0

    title = payload.get("title") or "(untitled)"
    current_cap = payload.get("max_cost_usd")
    print(f"Resuming: {_truncate(title, 80)}")
    print(f"  Paper ID: {paper_id}")
    print(f"  Current status: {current_status}")
    if max_cost is not None:
        print(f"  Cap: ${_format_money(current_cap)} → ${_format_money(max_cost)}")
    else:
        print(f"  Cap: ${_format_money(current_cap)} (unchanged)")
    last_error = payload.get("last_error")
    if last_error:
        print(f"  Was: {_truncate(str(last_error), 120)}")

    # POST /resume with the optional cap raise
    body: dict = {}
    if max_cost is not None:
        body["max_cost_usd"] = max_cost
    try:
        r = httpx.post(
            f"{_api_root()}/api/papers/{paper_id}/resume",
            json=body,
            timeout=10.0,
        )
    except Exception as e:
        print(f"e2er resume: POST failed: {e}", file=sys.stderr)
        return 3

    if r.status_code == 400:
        # Validation error (e.g. non-positive cap from the v0.5
        # ResumeRequest validator). Surface the detail directly.
        try:
            detail = r.json().get("detail") or r.text
        except Exception:
            detail = r.text
        print(f"e2er resume: {detail}", file=sys.stderr)
        return 5
    if r.status_code == 409:
        # Already running (the runner refuses to double-spawn). The user
        # should `e2er cancel` first if they want to restart.
        try:
            detail = r.json().get("detail") or r.text
        except Exception:
            detail = r.text
        print(
            f"e2er resume: {detail}\n  Hint: `e2er cancel {paper_id}` first if you want to stop the running task.",
            file=sys.stderr,
        )
        return 5
    if r.status_code not in (200, 202):
        print(
            f"e2er resume: POST returned {r.status_code}: {r.text[:300]}",
            file=sys.stderr,
        )
        return 5

    try:
        body_response = r.json()
    except Exception:
        body_response = {}
    new_status = body_response.get("status", "resuming")
    print(f"  ✓ Resumed. {new_status}")
    print(f"  Dashboard: {_api_root()}/papers/{paper_id}")

    if tail:
        print()
        print(f"Polling status (max {monitor_seconds:.0f}s, ^C is safe):")
        try:
            final = _poll_status(paper_id, total_seconds=monitor_seconds)
        except KeyboardInterrupt:
            print("\n  ^C — paper continues in the background.", file=sys.stderr)
            return 0
        print(f"\n  Final status: {final}")
    return 0
