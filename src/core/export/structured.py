"""Assemble a clean, portable project folder from a finished run's workspace.

The workspace (``Tests/workspaces/<uuid>/``) is a flat scratch dir the pipeline
writes by hardcoded filename. This module *copies* those artifacts into a
navigable tree the human actually wants — without touching the workspace:

    <dest_root>/<title>-<YYYYMMDD>-<NN>/
    ├── README.md   ├── paper/   ├── code/(+scratch/)   ├── data/
    ├── results/    ├── design/   └── reviews/

Design points (see docs/STRUCTURED_EXPORT_SPEC.md):
  - **Copy, never symlink** — the folder must survive being moved/shared.
  - **Versioned slug** — ``NN`` auto-increments, so re-export never overwrites.
  - **Best-effort** — exports whatever artifacts exist, so a rejected/failed run
    still yields its reviews + draft. Missing files are simply skipped.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)

# Destination subdir → list of (source pattern, optional rename). Patterns are
# matched against top-level workspace files via glob; the first capture of a
# rename applies only to a single exact match.
EXPORT_MAP: dict[str, list[tuple[str, str | None]]] = {
    "paper": [
        ("paper_draft.tex", "paper.tex"),
        ("abstract.tex", None),
        ("literature.bib", "refs.bib"),
        ("paper_draft.pdf", "paper.pdf"),
        ("paper.pdf", None),
    ],
    "code": [
        ("run_estimation.py", None),
        ("*.do", None),  # stata, if a specialist ever writes one
    ],
    "data": [
        ("data.db", None),
        ("data_summary.md", None),
        ("data_dictionary.json", None),
    ],
    "results": [
        ("estimation_results.json", None),
        ("robustness_results.json", None),
        ("summary_statistics.json", None),
        ("number_verification.json", None),
        ("figure_spec.json", None),
        ("table_spec.json", None),
        ("table_render_report.json", None),
        ("*.csv", None),  # model-generated intermediate outputs at workspace root
    ],
    "design": [
        ("paper_plan.md", None),
        ("literature_review.md", None),
        ("identification_strategy.md", None),
        ("econometric_spec.md", None),
        ("model_spec.md", None),
    ],
    # Loose exploration scripts + logs the model writes (analysis.py, explore.py,
    # q.py, run_estimation.log, …). The broad globs run last so canonical files
    # (run_estimation.py) are already claimed and skipped via `already`.
    "code/scratch": [
        ("*.py", None),
        ("*.log", None),
    ],
    "reviews": [
        ("review_*.md", None),
        ("review_aggregation.json", None),
        ("self_attack_report.json", None),
        ("polish_*.md", None),
        ("citation_integrity.json", None),
    ],
}

# Top-level files we never copy into misc/ (internal/bookkeeping or already
# consumed into README).
_MISC_EXCLUDE = {"manifest.json"}


def slugify(title: str, max_len: int = 60) -> str:
    """Title → kebab-case slug. Empty/garbage titles fall back to ``paper``."""
    s = re.sub(r"[^0-9a-zA-Z]+", "-", (title or "").lower()).strip("-")
    s = re.sub(r"-+", "-", s)[:max_len].strip("-")
    return s or "paper"


def resolve_versioned_slug(dest_root: Path, title: str, date_str: str) -> str:
    """``<slug>-<YYYYMMDD>-<NN>`` with the smallest unused 2-digit ``NN`` for
    that ``<slug>-<date>`` prefix in ``dest_root``."""
    base = f"{slugify(title)}-{date_str}"
    n = 1
    existing = {p.name for p in dest_root.iterdir()} if dest_root.is_dir() else set()
    while f"{base}-{n:02d}" in existing:
        n += 1
    return f"{base}-{n:02d}"


def _copy_matches(workspace: Path, dest_dir: Path, pattern: str, rename: str | None, already: set[str]) -> None:
    """Copy top-level files matching ``pattern`` into ``dest_dir``, skipping any
    basename already claimed by an earlier (more specific) mapping entry."""
    for src in sorted(workspace.glob(pattern)):
        if not src.is_file() or src.name in already:
            continue
        # Rename only when the pattern is an exact (glob-free) single file.
        out_name = rename if (rename and not any(c in pattern for c in "*?[")) else src.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest_dir / out_name)
            already.add(src.name)
        except OSError as e:  # noqa: PERF203 — per-file tolerance
            logger.warning("export: could not copy %s: %s", src.name, e)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _render_readme(workspace: Path, manifest: dict, slug: str) -> str:
    title = manifest.get("title") or "Untitled"
    rq = manifest.get("research_question") or "—"
    agg = _read_json(workspace / "review_aggregation.json")
    verdict = agg.get("verdict") or "—"
    avg = agg.get("weighted_avg")
    rationale = agg.get("rationale") or ""

    lines = [
        f"# {title}",
        "",
        f"**Research question:** {rq}",
        "",
        f"**Verdict:** `{verdict}`" + (f" (weighted avg {avg}/10)" if isinstance(avg, (int, float)) else ""),
    ]
    if rationale:
        lines += ["", f"> {rationale}"]

    # Headline coefficients, if an estimation ran.
    est = _read_json(workspace / "estimation_results.json")
    coefs = (est.get("main") or {}).get("coefficients") or {}
    if coefs:
        lines += ["", "## Headline estimates", "", "| term | estimate | p-value |", "| --- | --- | --- |"]
        for term, c in list(coefs.items())[:8]:
            est_v = c.get("estimate")
            p_v = c.get("p_value")
            est_s = f"{est_v:.4g}" if isinstance(est_v, (int, float)) else "—"
            p_s = f"{p_v:.3g}" if isinstance(p_v, (int, float)) else "—"
            lines.append(f"| `{term}` | {est_s} | {p_s} |")

    lines += [
        "",
        "## Folder guide",
        "",
        "- `paper/` — the manuscript (`paper.tex`, `abstract.tex`, `refs.bib`, compiled `paper.pdf`)",
        "- `code/` — the estimation script (`code/scratch/` holds exploratory probes + logs)",
        "- `data/` — the SQLite data warehouse (`data.db`) + data summary & dictionary",
        "- `results/` — estimation/robustness JSON + figures",
        "- `design/` — research plan, identification strategy, econometric spec",
        "- `reviews/` — referee reports + the aggregated verdict",
        "",
        "## Reproduce",
        "",
        "```bash",
        "cd code && python run_estimation.py   # reads ../data/ (or the original data files)",
        "```",
        "",
        f"_Exported as `{slug}` from E2ER._",
    ]
    return "\n".join(lines) + "\n"


def export_paper(workspace: Path, dest_root: Path, *, date_str: str, slug: str | None = None) -> Path:
    """Assemble the structured project folder. Returns the created directory.

    Best-effort: copies whatever artifacts exist; missing ones are skipped.
    """
    workspace = Path(workspace)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    manifest = _read_json(workspace / "manifest.json")
    title = manifest.get("title") or workspace.name
    slug = slug or resolve_versioned_slug(dest_root, title, date_str)
    out = dest_root / slug
    out.mkdir(parents=True, exist_ok=True)

    copied_names: set[str] = set()
    for subdir, patterns in EXPORT_MAP.items():
        dest_dir = out / subdir
        for pattern, rename in patterns:
            _copy_matches(workspace, dest_dir, pattern, rename, copied_names)

    # Figures: copy a figures/ dir if the renderer produced one.
    fig_src = workspace / "figures"
    if fig_src.is_dir():
        shutil.copytree(fig_src, out / "results" / "figures", dirs_exist_ok=True)

    # misc/ — top-level files we didn't map (no silent loss), minus internal ones.
    for src in sorted(workspace.iterdir()):
        if not src.is_file() or src.name in copied_names or src.name in _MISC_EXCLUDE or src.name.startswith("."):
            continue
        _copy_matches(workspace, out / "misc", src.name, None, copied_names)

    (out / "README.md").write_text(_render_readme(workspace, manifest, slug), encoding="utf-8")
    logger.info("Exported paper %s → %s", workspace.name, out)
    return out
