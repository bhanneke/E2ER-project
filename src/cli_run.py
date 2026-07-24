"""``e2er run`` — one-command submit-a-paper.

Replaces the multi-step "start uvicorn, curl POST, open dashboard, watch
events" flow with a single CLI command. Designed as the FIRST thing a
new user runs after ``pip install e2er``.

Flow:
  1. Check if a local uvicorn is reachable at the configured port.
     If not, start one in the background (detached subprocess).
  2. POST /api/papers with the research question + flags.
  3. Tail the events endpoint until the paper reaches a terminal status
     (completed / failed / cancelled / paused).
  4. Print a final summary with the paper's workspace path and dashboard URL.

The user can ^C at any point — the run keeps going in the background;
they can re-attach by visiting the dashboard URL.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _api_root() -> str:
    """Resolve the API URL from settings; the user can override via E2ER_API_URL."""
    if url := os.environ.get("E2ER_API_URL"):
        return url.rstrip("/")
    return "http://127.0.0.1:8280"


def _api_reachable(timeout: float = 1.5) -> bool:
    import httpx

    try:
        r = httpx.get(f"{_api_root()}/api/papers", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _start_uvicorn_in_background() -> int:
    """Spawn `uvicorn src.api.app:app --port 8280` as a detached subprocess.

    Returns the PID. The caller waits up to ~10s for /api/papers to come up,
    then proceeds.
    """
    log_path = Path.home() / ".e2er" / "uvicorn.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "src.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8280",
        "--log-level",
        "info",
    ]
    with log_path.open("ab") as log_f:
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,  # detach from terminal — survives ^C
        )
    return proc.pid


def _ensure_api_up(deadline_seconds: float = 12.0) -> tuple[bool, str | None]:
    """If API isn't reachable, start uvicorn. Block until it's up or timeout.

    Returns (success, message_to_user_if_failed).
    """
    if _api_reachable():
        return True, None
    print("Starting local E2ER API server (uvicorn on :8280)...", file=sys.stderr)
    pid = _start_uvicorn_in_background()
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if _api_reachable():
            print(f"  ✓ uvicorn ready (PID {pid}). Logs: ~/.e2er/uvicorn.log", file=sys.stderr)
            return True, None
        time.sleep(0.5)
    return False, (f"Failed to bring up uvicorn within {deadline_seconds:.0f}s. Check ~/.e2er/uvicorn.log for errors.")


def _submit_paper(
    rq: str,
    methodology: str,
    mode: str,
    max_cost: float,
    acknowledge: bool = False,
    backend: str | None = None,
    model: str | None = None,
    governance: str | None = None,
    review_stages: list[str] | None = None,
    title_suffix: str = "",
) -> dict | None:
    """POST /api/papers and return the response body."""
    import httpx

    from .config import get_settings

    # Derive a title: first sentence of the RQ, truncated. run-matrix passes a
    # title_suffix like " [claude_code/rep-1]" so sibling runs are labeled.
    title = rq.split("?")[0].split(".")[0].strip()
    if len(title) > 80:
        title = title[:77] + "..."
    if title_suffix:
        title = f"{title}{title_suffix}"

    # The $1 first-run floor protects against a runaway loop on an unvalidated
    # (model, methodology, mode) tuple — but it only matters for metered API
    # backends. The flat-rate CLI backends cost $0/token, so auto-acknowledge
    # there; otherwise enforce the floor unless the user passed --acknowledge.
    # Key the decision on the EFFECTIVE backend (the --backend override wins).
    effective_backend = backend or get_settings().llm_backend
    flat_rate = effective_backend in {"claude_code", "codex", "gemini"}
    acknowledge_unproven = acknowledge or flat_rate

    body = {
        "title": title,
        "research_question": rq,
        "methodology": methodology,
        # Field name on the API side is `mode`. Older callers used
        # `pipeline_mode` (still accepted via Pydantic alias) — see
        # CreatePaperRequest in src/api/app.py. Use the canonical name
        # here so the log line in api/app.py reflects what the user
        # actually passed instead of the default.
        "mode": mode,
        "max_specialists_per_phase": 6,
        "acknowledge_unproven_tuple": acknowledge_unproven,
        "max_cost_usd": max_cost,
    }
    if backend:
        body["backend"] = backend
    if model:
        body["model"] = model
    if governance:
        body["governance"] = governance
    if review_stages:
        body["review_stages"] = review_stages
    headers = {}
    if token := os.environ.get("E2ER_API_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.post(f"{_api_root()}/api/papers", json=body, headers=headers, timeout=30.0)
    except httpx.HTTPError as e:
        print(f"  ✗ POST /api/papers failed: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  ✗ POST /api/papers returned {r.status_code}: {r.text[:300]}", file=sys.stderr)
        return None
    return r.json()


def _poll_status(paper_id: str, total_seconds: float, poll_interval: float = 15.0) -> str:
    """Tail status until terminal. Returns the final status."""
    import httpx

    # `rejected` is a v0.5+ terminal status (review-gate or verify_numbers
    # quality reject, distinct from `failed` which means crash). Pre-fix
    # the tailer kept polling forever on REJECTED papers because they
    # weren't in this set — observed during fresh-install testing.
    terminal = {"completed", "failed", "cancelled", "paused", "rejected"}
    start = time.monotonic()
    last_state = ""
    while time.monotonic() - start < total_seconds:
        try:
            r = httpx.get(f"{_api_root()}/api/papers/{paper_id}", timeout=10.0)
            d = r.json()
        except Exception:
            time.sleep(poll_interval)
            continue
        status = d.get("status") or "?"
        u = d.get("usage") or {}
        line = (
            f"  [{status:12s}] specialists={u.get('specialist_calls') or 0:>3}  "
            f"tokens={u.get('total_tokens') or 0:>10}  "
            f"cost=${u.get('total_cost_usd') or 0}"
        )
        if line != last_state:
            print(line, file=sys.stderr)
            last_state = line
        if status in terminal:
            return status
        time.sleep(poll_interval)
    return "(monitor timed out — paper still in flight)"


def run(
    rq: str,
    methodology: str = "empirical",
    mode: str = "single_pass",
    max_cost: float = 5.0,
    monitor_seconds: float = 1800.0,
    acknowledge: bool = False,
    backend: str | None = None,
    model: str | None = None,
    governance: str | None = None,
    review_stages: list[str] | None = None,
) -> int:
    """Submit a paper and tail it. Entry point for `e2er run "<RQ>"`."""
    ok, err = _ensure_api_up()
    if not ok:
        print(f"e2er run: {err}", file=sys.stderr)
        return 4

    print(f"Submitting paper:\n  {rq[:120]}", file=sys.stderr)
    backend_note = f", backend={backend}" if backend else ""
    model_note = f", model={model}" if model else ""
    gov_note = f", governance={governance}" if governance else ""
    review_note = f", review-at={','.join(review_stages)}" if review_stages else ""
    print(
        f"  methodology={methodology}, mode={mode}, max_cost=${max_cost}"
        f"{backend_note}{model_note}{gov_note}{review_note}",
        file=sys.stderr,
    )
    resp = _submit_paper(
        rq,
        methodology,
        mode,
        max_cost,
        acknowledge=acknowledge,
        backend=backend,
        model=model,
        governance=governance,
        review_stages=review_stages,
    )
    if not resp:
        return 5

    paper_id = resp.get("paper_id")
    workspace = resp.get("workspace")
    if not paper_id:
        # Should never happen given _submit_paper returned successfully, but
        # narrow the type for mypy + give the user a clear error if it does.
        print("  ✗ API returned 200 but no paper_id — cannot tail.", file=sys.stderr)
        return 5
    dashboard_url = f"{_api_root()}/papers/{paper_id}"

    print(f"\n  Paper ID:  {paper_id}", file=sys.stderr)
    print(f"  Workspace: {workspace}", file=sys.stderr)
    print(f"  Dashboard: {dashboard_url}\n", file=sys.stderr)
    print(f"Polling status (max {monitor_seconds:.0f}s, ^C is safe — run continues in background):", file=sys.stderr)

    try:
        final = _poll_status(paper_id, total_seconds=monitor_seconds)
    except KeyboardInterrupt:
        print("\n  ^C received — the run continues in the background.", file=sys.stderr)
        print(f"  Watch progress at: {dashboard_url}", file=sys.stderr)
        return 0

    print(f"\n  Final status: {final}", file=sys.stderr)
    print(f"  Dashboard:    {dashboard_url}", file=sys.stderr)
    if final == "completed":
        print("\n✓ Paper completed. Open the dashboard or read directly from:", file=sys.stderr)
        print(f"  {workspace}/paper_draft.tex", file=sys.stderr)
        print(f"  {workspace}/abstract.tex", file=sys.stderr)
        return 0
    if final in {"failed", "paused"}:
        print(f"\n⚠ Paper {final}. Diagnose with:", file=sys.stderr)
        print(f"  curl -s {_api_root()}/api/papers/{paper_id}/failure-bundle | jq", file=sys.stderr)
        return 1
    return 0
