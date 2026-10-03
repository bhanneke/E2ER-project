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
  - **Best-effort** — exports whatever artifacts exist, so a stopped/failed run
    still yields its reviews + draft. Missing files are simply skipped.
"""

from __future__ import annotations

import glob
import json
import re
import shutil
from pathlib import Path

from ...logging_config import get_logger
from ..run_outcome import review_detail

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
        # what e2er-data recorded per external-source load (release, URLs, SHA-256)
        ("data_sources.json", None),
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
        # The machine-readable pre-registration sidecar — belongs with the
        # design docs, not the misc/ catch-all. It is what `e2er verify`
        # re-checks the estimation against.
        ("identification_spec.json", None),
        # An event study's design is a pre-registered plan file too: the lock
        # fingerprints it, so `e2er verify` looks for it here.
        ("event_design.json", None),
        ("econometric_spec.md", None),
        ("model_spec.md", None),
        # The frozen pre-registration and its fingerprints (researcher step),
        # and the instructions the researcher gave during the run.
        ("preregistration.md", None),
        ("preregistration.lock.json", None),
        ("researcher_instructions.md", None),
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


def create_versioned_folder(dest_root: Path, title: str, date_str: str) -> Path:
    """Create ``<slug>-<YYYYMMDD>-<NN>`` with the smallest free ``NN``, atomically.

    ``mkdir`` without ``exist_ok`` either creates the folder or fails because
    it exists; two exports started at the same moment therefore never share
    one folder (the second takes the next number).
    """
    base = f"{slugify(title)}-{date_str}"
    n = 1
    while True:
        out = dest_root / f"{base}-{n:02d}"
        try:
            out.mkdir()
            return out
        except FileExistsError:
            n += 1


def _leaves_workspace(path: Path, workspace: Path) -> bool:
    """A symbolic link (at ``path`` or above it) that resolves outside the workspace."""
    try:
        return not path.resolve().is_relative_to(workspace.resolve())
    except OSError:
        return True


def _skip(src: Path, workspace: Path) -> str | None:
    """Why ``src`` is not exported, or None. Never exported: OS clutter, dotfiles
    (``.env`` holds keys), key files, and links that lead out of the workspace."""
    from .bundle_files import never_exported

    if never_exported(src.name):
        return "a dotfile, key file or operating-system file"
    if _leaves_workspace(src, workspace):
        return "a link to something outside the workspace"
    return None


def _copytree(src: Path, dst: Path, workspace: Path) -> None:
    """``shutil.copytree`` minus what export never copies (see :func:`_skip`)."""

    def ignore(folder: str, names: list[str]) -> set[str]:
        out = set()
        for name in names:
            why = _skip(Path(folder) / name, workspace)
            if why:
                logger.warning("export: left out %s: %s", Path(folder, name), why)
                out.add(name)
        return out

    why = _skip(src, workspace)
    if why:
        logger.warning("export: left out %s: %s", src.name, why)
        return
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


def _copy_matches(
    workspace: Path,
    dest_dir: Path,
    pattern: str,
    rename: str | None,
    already: set[str],
    notes: list[str] | None = None,
) -> None:
    """Copy top-level files matching ``pattern`` into ``dest_dir``, skipping any
    basename already claimed by an earlier (more specific) mapping entry.

    A file whose target is already taken (``paper_draft.pdf`` and ``paper.pdf``
    both map to ``paper/paper.pdf``) never overwrites it: the earlier entry
    wins, the later file stays unclaimed and lands in ``misc/``, and ``notes``
    says so (the README lists it).
    """
    for src in sorted(workspace.glob(pattern)):
        if not src.is_file() or src.name in already:
            continue
        why = _skip(src, workspace)
        if why:
            logger.warning("export: left out %s: %s", src.name, why)
            already.add(src.name)
            continue
        # Rename only when the pattern is an exact (glob-free) single file.
        out_name = rename if (rename and not any(c in pattern for c in "*?[")) else src.name
        target = dest_dir / out_name
        if target.exists():
            msg = (
                f"`{dest_dir.name}/{out_name}` is the workspace file listed first for it; "
                f"the workspace's `{src.name}` is in `misc/{src.name}`"
            )
            logger.warning("export: %s", msg)
            if notes is not None:
                notes.append(msg)
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, target)
            already.add(src.name)
        except OSError as e:  # noqa: PERF203 — per-file tolerance
            logger.warning("export: could not copy %s: %s", src.name, e)


#: A rebuilt output larger than this is left out of the bundle (and logged).
MAX_OUTPUT_BYTES = 200 * 1024 * 1024


def _copy_reproduction_outputs(workspace: Path, out: Path) -> None:
    """Copy the sandbox's logs and the output files its run wrote into the bundle.

    ``sandbox/logs/`` goes in whole. From the run folder (``sandbox_log.json``
    → ``run_dir``) go the files the entry points wrote (``outputs`` with
    ``written_by_run``) and every file ``reproduction_report.json`` reads a
    number from, at the same relative paths, so the bundle has the workspace's
    layout and ``e2er verify`` re-reads each compared number from its file.
    Nothing from the package itself is copied: those files are not results of
    the run. ``reproduction_check.json`` and the report go to misc/ with the
    other top-level files; provenance.json hashes all of it.
    """
    logs = workspace / "sandbox" / "logs"
    if logs.is_dir():
        _copytree(logs, out / "sandbox" / "logs", workspace)
    log = _read_json(workspace / "sandbox_log.json")
    log = log if isinstance(log, dict) else {}
    run_rel = str(log.get("run_dir") or "sandbox/run")
    run_dir = (workspace / run_rel).resolve()
    if not run_dir.is_relative_to(workspace.resolve()) or not run_dir.is_dir():
        return
    dest_run = out / run_dir.relative_to(workspace.resolve())
    wanted = {str(o.get("path")) for o in log.get("outputs") or [] if isinstance(o, dict) and o.get("written_by_run")}
    report = _read_json(workspace / "reproduction_report.json")
    for res in (report.get("results") if isinstance(report, dict) else None) or []:
        for comp in (res.get("comparisons") or []) if isinstance(res, dict) else []:
            src = comp.get("source") if isinstance(comp, dict) else None
            if isinstance(src, dict) and isinstance(src.get("file"), str):
                wanted.add(src["file"])
    for rel in sorted(wanted):
        src_path = (run_dir / rel).resolve()
        if not rel or not src_path.is_relative_to(run_dir) or not src_path.is_file():
            continue
        if _skip(run_dir / rel, workspace):
            continue
        if src_path.stat().st_size > MAX_OUTPUT_BYTES:
            logger.warning("export: %s is larger than %d bytes; left out of the bundle", rel, MAX_OUTPUT_BYTES)
            continue
        dest = dest_run / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _render_readme(workspace: Path, manifest: dict, slug: str, notes: list[str] | None = None) -> str:
    title = manifest.get("title") or "Untitled"
    rq = manifest.get("research_question") or "—"
    review = review_detail(_read_json(workspace / "review_aggregation.json"))

    lines = [
        f"# {title}",
        "",
        f"**Research question:** {rq}",
    ]
    if review:
        # A score, nothing else: six reviewer specialists each score the draft
        # from one angle; the score is their weighted average.
        lines += ["", f"**e2er's internal quality review:** {review}"]

    # Run provenance disclosure — the governance regime this paper ran under
    # is load-bearing: under `contracts`/`off` the deterministic gates ran in
    # SHADOW (computed + logged, but did not block), so numbers/citations may
    # not have been enforced. Backend/model disclosed alongside.
    regime = manifest.get("governance") or "full"
    backend = manifest.get("backend")
    model = manifest.get("model")
    run_bits = [f"governance=`{regime}`"]
    if backend:
        run_bits.append(f"backend=`{backend}`")
    if model:
        run_bits.append(f"model=`{model}`")
    lines += ["", "**Run:** " + ", ".join(run_bits)]
    if regime != "full":
        lines += [
            "",
            f"> ⚠️ Ran under the `{regime}` governance regime: the deterministic "
            "verification gates ran in shadow (logged, not enforced). See the "
            "`gate_shadow` events for what a full-governance run would have caught.",
        ]

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
        "- `reviews/` — the six reviewer reports and the combined score (`review_aggregation.json`)",
        "",
    ]
    if notes:
        lines += ["## Export notes", ""] + [f"- {n}" for n in notes] + [""]
    lines += [
        "## Reproduce",
        "",
        "```bash",
        "cd code && python run_estimation.py   # reads ../data/ (or the original data files)",
        "```",
        "",
        f"_Exported as `{slug}` from e2er._",
    ]
    return "\n".join(lines) + "\n"


def export_paper(
    workspace: Path, dest_root: Path, *, date_str: str, slug: str | None = None, template: str | None = None
) -> Path:
    """Assemble the structured project folder. Returns the created directory.

    Best-effort: copies whatever artifacts exist; missing ones are skipped.
    ``template`` is the template the study was run with (the papers row's
    ``pipeline``); without it, the one manifest.json records. It is written to
    provenance.json (``run.template``), where ``e2er publish`` reads it.
    """
    workspace = Path(workspace)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    manifest = _read_json(workspace / "manifest.json")
    if template:
        manifest = {**manifest, "pipeline": template}
    title = manifest.get("title") or workspace.name
    if slug:
        out = dest_root / slug
        out.mkdir()  # an explicit folder must be new: export never writes into an earlier one
    else:
        out = create_versioned_folder(dest_root, title, date_str)
        slug = out.name

    copied_names: set[str] = set()
    notes: list[str] = []
    for subdir, patterns in EXPORT_MAP.items():
        dest_dir = out / subdir
        for pattern, rename in patterns:
            _copy_matches(workspace, dest_dir, pattern, rename, copied_names, notes)
    # literature.bib is shipped as refs.bib; point the paper at it so the
    # bundle compiles on its own (otherwise every citation becomes "?").
    paper_tex = out / "paper" / "paper.tex"
    if paper_tex.is_file():
        from ..bibliography import point_bibliography

        text = paper_tex.read_text(encoding="utf-8")
        fixed = point_bibliography(text, paper_tex.parent)
        if fixed != text:
            paper_tex.write_text(fixed, encoding="utf-8")

    # Figures: copy a figures/ dir if the renderer produced one.
    fig_src = workspace / "figures"
    if fig_src.is_dir():
        _copytree(fig_src, out / "results" / "figures", workspace)

    # Tables: the deterministic renderer writes one .tex per table into
    # tables/, and paper.tex includes each with \input{tables/<name>.tex}.
    # They must land under paper/ because \input resolves relative to the
    # including file. Without this the bundle carries two .tex files and fails
    # to compile on the first pass — and `e2er verify` does not notice, because
    # it only scans the main .tex for inline tabulars.
    tbl_src = workspace / "tables"
    if tbl_src.is_dir():
        _copytree(tbl_src, out / "paper" / "tables", workspace)

    # Replication: the audit log + query SQL + replication estimation script
    # (audit_log.csv, data_queries.sql, estimation.py). Previously dropped
    # entirely — it is the backbone of a reproducible bundle.
    repl_src = workspace / "replication"
    if repl_src.is_dir():
        _copytree(repl_src, out / "replication", workspace)

    # A reproduction: what the sandbox run wrote, so `e2er verify` can re-read
    # every compared number offline (see _copy_reproduction_outputs).
    if (workspace / "reproduction_report.json").is_file():
        _copy_reproduction_outputs(workspace, out)

    # misc/ — top-level files we didn't map (no silent loss), minus internal ones.
    for src in sorted(workspace.iterdir()):
        if not src.is_file() or src.name in copied_names or src.name in _MISC_EXCLUDE or src.name.startswith("."):
            continue
        _copy_matches(workspace, out / "misc", glob.escape(src.name), None, copied_names, notes)

    (out / "README.md").write_text(_render_readme(workspace, manifest, slug, notes), encoding="utf-8")

    # The shareable view, rendered from the provenance about to be written, so
    # that provenance.json (written LAST, after every other file exists)
    # fingerprints it like every other file: an edited report.html fails verify.
    from .provenance import build_provenance, write_provenance
    from .report import write_report

    write_report(out, manifest, build_provenance(out, manifest, exported_at=date_str))
    write_provenance(out, manifest, exported_at=date_str)

    logger.info("Exported paper %s → %s", workspace.name, out)
    return out
