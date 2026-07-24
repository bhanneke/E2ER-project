"""``e2er run-matrix`` — run the same RQ + data across several LLM backends.

The multi-model half of the human-directed loop: the same research question
and the same bring-your-own data, run k backends × n repeats, produces a set
of labeled sibling papers. `e2er compare` (next) then diffs the design choices
each model made. This is measurement — coverage of the solution space — NOT
selection: no run is promoted here.

Sequential by default (the $0 CLI backends contend for local resources). Each
run is submitted with a per-paper backend override (WS-P3.0), polled to a
terminal state, and — if it completed — exported into
``<out>/<backend>-<rep>/``. A ``matrix.json`` records every run so `compare`
(and the experiment driver) can find the bundles.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from .cli_run import _ensure_api_up, _poll_status, _submit_paper


def _export_bundle(paper_id: str, dest_root: Path) -> Path | None:
    """Export a completed paper's workspace into dest_root; return the bundle
    path (or None if the workspace is missing / export fails). Mirrors
    cli_export.export but returns the path for matrix.json."""
    from .config import get_settings
    from .core.export.structured import export_paper

    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.is_dir():
        return None
    try:
        return export_paper(workspace, dest_root, date_str=datetime.now().strftime("%Y%m%d"))
    except Exception as e:  # noqa: BLE001 — export is best-effort; run still recorded
        print(f"  ! export failed for {paper_id}: {e}", file=sys.stderr)
        return None


def run_matrix(
    rq: str,
    backends: list[str],
    repeats: int = 3,
    methodology: str = "empirical",
    mode: str = "single_pass",
    max_cost: float = 5.0,
    governance: str | None = None,
    out: str | None = None,
    monitor_seconds: float = 3600.0,
) -> int:
    """Entry point for `e2er run-matrix`. Returns a shell exit code."""
    from .core.export.structured import slugify

    if not backends:
        print("run-matrix: no backends given", file=sys.stderr)
        return 2
    if repeats < 1:
        print("run-matrix: --repeats must be >= 1", file=sys.stderr)
        return 2

    ok, err = _ensure_api_up()
    if not ok:
        print(f"e2er run-matrix: {err}", file=sys.stderr)
        return 4

    out_dir = Path(out).expanduser() if out else Path.cwd() / f"matrix-{slugify(rq)}"
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(b, i) for b in backends for i in range(1, repeats + 1)]
    print(
        f"run-matrix: {len(jobs)} paper(s) — {len(backends)} backend(s) × {repeats} repeat(s), "
        f"sequential. Output → {out_dir}",
        file=sys.stderr,
    )

    runs: list[dict] = []
    for backend, rep in jobs:
        label = f"{backend}/rep-{rep}"
        print(f"\n── {label} ──", file=sys.stderr)
        resp = _submit_paper(
            rq,
            methodology,
            mode,
            max_cost,
            backend=backend,
            governance=governance,
            title_suffix=f" [{label}]",
        )
        if not resp or not resp.get("paper_id"):
            runs.append(
                {"backend": backend, "repeat": rep, "paper_id": None, "status": "submit_failed", "bundle_path": None}
            )
            _write_matrix(out_dir, rq, methodology, mode, governance, backends, repeats, runs)
            continue
        paper_id = resp["paper_id"]
        status = _poll_status(paper_id, total_seconds=monitor_seconds)
        bundle_path: str | None = None
        if status == "completed":
            bundle = _export_bundle(paper_id, out_dir / f"{backend}-{rep}")
            bundle_path = str(bundle) if bundle else None
        runs.append(
            {"backend": backend, "repeat": rep, "paper_id": paper_id, "status": status, "bundle_path": bundle_path}
        )
        # Persist after every run so a long matrix is recoverable if interrupted.
        _write_matrix(out_dir, rq, methodology, mode, governance, backends, repeats, runs)

    n_done = sum(r["status"] == "completed" for r in runs)
    print(f"\nrun-matrix: {n_done}/{len(runs)} completed. matrix.json → {out_dir / 'matrix.json'}", file=sys.stderr)
    return 0


def _write_matrix(
    out_dir: Path,
    rq: str,
    methodology: str,
    mode: str,
    governance: str | None,
    backends: list[str],
    repeats: int,
    runs: list[dict],
) -> None:
    matrix = {
        "research_question": rq,
        "methodology": methodology,
        "mode": mode,
        "governance": governance,
        "backends": backends,
        "repeats": repeats,
        "runs": runs,
    }
    (out_dir / "matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
