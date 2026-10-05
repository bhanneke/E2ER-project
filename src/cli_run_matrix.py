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

#: Backends run-matrix knows, in the order it runs them.
_BACKENDS = ("claude_code", "codex", "gemini", "anthropic", "openrouter")


class MatrixArgError(ValueError):
    """A run-matrix argument that cannot be used; reported as one line."""


def available_backends(settings=None) -> list[str]:
    """The backends ready on this computer, as `e2er doctor` finds them.

    The subscription CLIs (Claude Code, Codex, Gemini) that are installed and
    not known to be signed out; if there is none, the API backends with a key.
    The old default named all three CLIs whether or not they were there, so a
    matrix on a machine with one CLI spent two thirds of its runs failing.
    """
    from .doctor import detect_backends

    if settings is None:
        from .config import get_settings

        settings = get_settings()
    rows = detect_backends(settings)
    cli = [b.name for b in rows if b.kind == "cli" and b.ready]
    if cli:
        return cli
    return [b.name for b in rows if b.kind == "api" and b.ready]


def parse_models(spec: str | None, backends: list[str]) -> dict[str, str]:
    """`claude_code=sonnet,codex=gpt-6-luna` → {backend: model}, checked against `backends`."""
    out: dict[str, str] = {}
    if not spec:
        return out
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        backend, sep, model = part.partition("=")
        backend, model = backend.strip(), model.strip()
        if not sep or not backend or not model:
            raise MatrixArgError(f"--models takes backend=model pairs, got {part!r}")
        if backend not in _BACKENDS:
            raise MatrixArgError(f"--models names an unknown backend {backend!r} (known: {', '.join(_BACKENDS)})")
        if backend not in backends:
            raise MatrixArgError(
                f"--models names {backend!r}, which is not among the backends run: {', '.join(backends)}"
            )
        out[backend] = model
    return out


def model_label(backend: str, models: dict[str, str], settings=None) -> str:
    """The model a run on `backend` uses: the --models choice, else the backend's configured one."""
    if backend in models:
        return models[backend]
    if settings is None:
        from .config import get_settings

        settings = get_settings()
    return settings.default_model_for(backend)


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
    template: str | None = None,
    review_stages: list[str] | None = None,
    demonstration: bool = False,
    models: dict[str, str] | None = None,
) -> int:
    """Entry point for `e2er run-matrix`. Returns a shell exit code."""
    from .core.export.structured import slugify

    models = dict(models or {})
    if not backends:
        print(
            "run-matrix: no backends to run — none is ready on this computer (see `e2er doctor`), or pass --backends",
            file=sys.stderr,
        )
        return 2
    unknown = [b for b in backends if b not in _BACKENDS]
    if unknown:
        print(f"run-matrix: unknown backend(s): {', '.join(unknown)} (known: {', '.join(_BACKENDS)})", file=sys.stderr)
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

    labels = {b: model_label(b, models) for b in backends}
    for b in backends:
        print(f"  {b}: {labels[b]}", file=sys.stderr)
    meta = {
        "template": template or "empirical",
        "review_stages": review_stages or [],
        "demonstration": demonstration,
        "models": labels,
    }

    runs: list[dict] = []
    for backend, rep in jobs:
        label = f"{backend}/rep-{rep}"
        print(f"\n── {label} ({labels[backend]}) ──", file=sys.stderr)
        resp = _submit_paper(
            rq,
            methodology,
            mode,
            max_cost,
            backend=backend,
            model=models.get(backend),
            governance=governance,
            review_stages=review_stages,
            title_suffix=f" [{label}]",
            template=template,
            demonstration=demonstration,
        )
        if not resp or not resp.get("paper_id"):
            runs.append(
                {
                    "backend": backend,
                    "model": labels[backend],
                    "repeat": rep,
                    "paper_id": None,
                    "status": "submit_failed",
                    "bundle_path": None,
                }
            )
            _write_matrix(out_dir, rq, methodology, mode, governance, backends, repeats, runs, meta)
            continue
        paper_id = resp["paper_id"]
        status = _poll_status(paper_id, total_seconds=monitor_seconds)
        bundle_path: str | None = None
        if status == "completed":
            bundle = _export_bundle(paper_id, out_dir / f"{backend}-{rep}")
            bundle_path = str(bundle) if bundle else None
        runs.append(
            {
                "backend": backend,
                "model": resp.get("model") or labels[backend],
                "repeat": rep,
                "paper_id": paper_id,
                "status": status,
                "bundle_path": bundle_path,
            }
        )
        # Persist after every run so a long matrix is recoverable if interrupted.
        _write_matrix(out_dir, rq, methodology, mode, governance, backends, repeats, runs, meta)

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
    meta: dict | None = None,
) -> None:
    matrix = {
        "research_question": rq,
        "methodology": methodology,
        "mode": mode,
        "governance": governance,
        "backends": backends,
        "repeats": repeats,
        **(meta or {}),
        "runs": runs,
    }
    (out_dir / "matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
