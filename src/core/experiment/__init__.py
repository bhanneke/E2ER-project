"""Governance experiment driver (WS-F).

Turns the governance switch (WS-B) into the measured result the proposal
rests on: run the SAME RQ under each regime (off / contracts / full) × N
repeats, then harvest how much fabrication each run carried. In off/contracts
the deterministic gates run in SHADOW (compute + log, don't block), so
fabrication is measured, not merely absent.

Fixed metric definitions (identical in every regime):
  * fabrication_count = critical numeric mismatches (number_verification.json)
    + citations missing from the bibliography + unverifiable citations
    (citation_integrity.json). These reports are written in every regime.
  * completed = terminal status == "completed".
  * shadow_gate_failures / enforced_gate_blocks = gate_shadow / gate_enforced
    events with passed=False (what the gates caught, blocking or not).

Outputs results.csv (one row per run) + summary.md (per-regime means +
optional design-choice dispersion via the compare module).

Reuses the run-matrix client machinery — it does not fork it. The
orchestration takes injectable submit/poll/export/events functions so it is
testable without a server; `run_from_config` wires the real ones.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGIMES = ("off", "contracts", "full")

ROW_FIELDS = (
    "rq_idx",
    "regime",
    "backend",
    "repeat",
    "paper_id",
    "status",
    "completed",
    # Contradicted or absent — the draft asserts something the sources refute.
    "critical_mismatches",
    "prose_mismatched",
    "missing_in_bib",
    "fabrication_count",
    # Untraceable — the check could not tie the claim to a source either way.
    # Kept OUT of fabrication_count: a derived quantity and a fabricated one
    # are indistinguishable here, and folding them together is what inflated
    # the validation cell to 315.
    "values_unverifiable",
    "prose_unverifiable",
    "cites_unverifiable",
    "unverified_count",
    "total_cites",
    "checks_skipped",
    "measured",
    "shadow_gate_failures",
    "enforced_gate_blocks",
    "bundle_path",
)

# Report locations. Export bundles nest them; a raw workspace keeps them flat.
# Harvesting must read BOTH — a run that ends `rejected` never gets exported,
# yet it is exactly the run whose fabrication we most want to count.
_NUMBERS_REPORT = ("results/number_verification.json", "number_verification.json")
_CITATIONS_REPORT = ("reviews/citation_integrity.json", "citation_integrity.json")


@dataclass
class ExperimentConfig:
    name: str
    research_questions: list[str]
    regimes: list[str] = field(default_factory=lambda: list(REGIMES))
    repeats: int = 1
    backends: list[str] = field(default_factory=lambda: ["claude_code"])
    max_cost: float = 5.0
    methodology: str = "empirical"
    mode: str = "single_pass"


def _norm_regime(x: Any) -> str:
    """Undo YAML 1.1's off→False / on→True coercion of unquoted regime words."""
    if x is False:
        return "off"
    if x is True:
        return "on"
    return str(x)


def load_config(path: str | Path) -> ExperimentConfig:
    import yaml  # type: ignore[import-untyped]

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if "research_questions" not in raw:
        raise ValueError(f"experiment config {path} has no 'research_questions'")
    return ExperimentConfig(
        name=raw.get("name", Path(path).stem),
        research_questions=list(raw["research_questions"]),
        # YAML 1.1 parses an unquoted `off` as the boolean False (and `on` as
        # True), so `regimes: [off, contracts, full]` would silently drop the
        # off regime. Coerce those back so the config reads naturally.
        regimes=[_norm_regime(x) for x in raw.get("regimes", list(REGIMES))],
        repeats=int(raw.get("repeats", 1)),
        backends=list(raw.get("backends", ["claude_code"])),
        max_cost=float(raw.get("max_cost", 5.0)),
        methodology=raw.get("methodology", "empirical"),
        mode=raw.get("mode", "single_pass"),
    )


# ── harvesting ───────────────────────────────────────────────────────────────


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _find_report(root: Path, candidates: tuple[str, ...]) -> dict | None:
    for rel in candidates:
        d = _load_json(root / rel)
        if isinstance(d, dict):
            return d
    return None


@dataclass
class _NumberStats:
    """What the number check established about one run."""

    critical: int = 0  # table cells contradicting a source
    prose_mismatched: int = 0  # prose numbers contradicting an associated source
    values_unverifiable: int = 0  # table cells traceable to nothing
    prose_unverifiable: int = 0  # prose numbers traceable to nothing
    skipped: bool = True


def _number_stats(root: Path) -> _NumberStats:
    """Split the number report into contradicted vs merely untraceable.

    Both halves matter and they are not the same claim. Counting only table
    cells reported zero fabrication on pilot run ab95fcba, which carried 166
    prose mismatches out of 278 prose numbers. Counting every prose mismatch
    then over-corrected: 79% of the validation cell's 284 were matcher
    artifacts. With the matcher fixed (`verify_numbers._check_prose`), a
    mismatch means an associated source value disagrees; everything the check
    could not tie to a source is `*_unverifiable` and is reported apart from
    fabrication.

    `skipped` is true when the check could not actually run. A verifier that
    examined nothing reports `passed: true`; treating that as "clean" is the
    same skipped-is-not-verified error as B-4 in `e2er verify`.
    """
    nv = _find_report(root, _NUMBERS_REPORT)
    if nv is None:
        return _NumberStats()
    examined = int(nv.get("total_values_in_tables", 0) or 0) + int(nv.get("prose_total", 0) or 0)
    return _NumberStats(
        critical=sum(1 for m in nv.get("mismatches", []) if isinstance(m, dict) and m.get("severity") == "critical"),
        prose_mismatched=int(nv.get("prose_mismatched", 0) or 0),
        values_unverifiable=int(nv.get("unverifiable", 0) or 0),
        prose_unverifiable=int(nv.get("prose_unverifiable", 0) or 0),
        skipped=bool(nv.get("skipped_reason")) or examined == 0,
    )


def _citation_stats(root: Path) -> tuple[int, int, int, bool]:
    """(missing_in_bib, unverifiable, total_cites, skipped)."""
    ci = _find_report(root, _CITATIONS_REPORT)
    if ci is None:
        return 0, 0, 0, True
    total = int(ci.get("total_cites", 0) or 0)
    skipped = bool(ci.get("skipped_reason")) or total == 0
    return int(ci.get("missing_in_bib", 0) or 0), int(ci.get("unverifiable", 0) or 0), total, skipped


def _gate_event_stats(events: list[dict]) -> tuple[int, int]:
    shadow_fail = enforced_block = 0
    for e in events or []:
        payload = e.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {}
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("passed") is not False:
            continue
        if e.get("event_type") == "gate_shadow":
            shadow_fail += 1
        elif e.get("event_type") == "gate_enforced":
            enforced_block += 1
    return shadow_fail, enforced_block


def harvest_run(
    *,
    rq_idx: int,
    regime: str,
    backend: str,
    repeat: int,
    paper_id: str | None,
    status: str,
    bundle_path: str | None,
    events: list[dict],
    workspace_path: str | None = None,
) -> dict:
    # Prefer the export bundle; fall back to the raw workspace so runs that end
    # `rejected`/`failed` after producing reports are still measured instead of
    # silently contributing a structural zero.
    root: Path | None = None
    if bundle_path:
        root = Path(bundle_path)
    elif workspace_path and Path(workspace_path).is_dir():
        root = Path(workspace_path)

    if root is None:
        nums = _NumberStats()
        missing = cite_unverif = total = 0
        cite_skipped = True
    else:
        nums = _number_stats(root)
        missing, cite_unverif, total, cite_skipped = _citation_stats(root)

    skipped = [n for n, s in (("numbers", nums.skipped), ("citations", cite_skipped)) if s]
    shadow_fail, enforced_block = _gate_event_stats(events)
    return {
        "rq_idx": rq_idx,
        "regime": regime,
        "backend": backend,
        "repeat": repeat,
        "paper_id": paper_id or "",
        "status": status,
        "completed": int(status == "completed"),
        "critical_mismatches": nums.critical,
        "prose_mismatched": nums.prose_mismatched,
        "missing_in_bib": missing,
        # Positively contradicted or absent. Nothing that merely failed to
        # trace belongs here.
        "fabrication_count": nums.critical + nums.prose_mismatched + missing,
        "values_unverifiable": nums.values_unverifiable,
        "prose_unverifiable": nums.prose_unverifiable,
        "cites_unverifiable": cite_unverif,
        "unverified_count": nums.values_unverifiable + nums.prose_unverifiable + cite_unverif,
        "total_cites": total,
        # A 0 from a check that never ran is not evidence of no fabrication.
        # `measured` marks the rows the per-regime means may legitimately use.
        "checks_skipped": ",".join(skipped),
        "measured": int(len(skipped) < 2),
        "shadow_gate_failures": shadow_fail,
        "enforced_gate_blocks": enforced_block,
        "bundle_path": bundle_path or (str(root) if root else ""),
    }


# ── orchestration ────────────────────────────────────────────────────────────

SubmitFn = Callable[..., "str | None"]
PollFn = Callable[[str, float], str]
ExportFn = Callable[[str, Path], "Path | None"]
EventsFn = Callable[[str], list]
WorkspaceFn = Callable[[str], "str | None"]


def run_experiment(
    config: ExperimentConfig,
    out_dir: str | Path,
    *,
    submit_fn: SubmitFn,
    poll_fn: PollFn,
    export_fn: ExportFn,
    events_fn: EventsFn,
    workspace_fn: WorkspaceFn | None = None,
    monitor_seconds: float = 3600.0,
) -> list[dict]:
    """RQs × regimes × backends × repeats → results.csv + summary.md. Rows are
    re-written after each run so a long experiment is recoverable."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for rq_idx, rq in enumerate(config.research_questions):
        for regime in config.regimes:
            for backend in config.backends:
                for rep in range(1, config.repeats + 1):
                    label = f"exp/{regime}/rep-{rep}"
                    paper_id = submit_fn(
                        rq=rq,
                        regime=regime,
                        backend=backend,
                        methodology=config.methodology,
                        mode=config.mode,
                        max_cost=config.max_cost,
                        label=label,
                    )
                    if not paper_id:
                        rows.append(
                            harvest_run(
                                rq_idx=rq_idx,
                                regime=regime,
                                backend=backend,
                                repeat=rep,
                                paper_id=None,
                                status="submit_failed",
                                bundle_path=None,
                                events=[],
                            )
                        )
                    else:
                        status = poll_fn(paper_id, monitor_seconds)
                        bundle = None
                        if status == "completed":
                            bundle = export_fn(paper_id, out / f"rq{rq_idx}-{regime}-{backend}-{rep}")
                        rows.append(
                            harvest_run(
                                rq_idx=rq_idx,
                                regime=regime,
                                backend=backend,
                                repeat=rep,
                                paper_id=paper_id,
                                status=status,
                                bundle_path=str(bundle) if bundle else None,
                                events=events_fn(paper_id),
                                workspace_path=workspace_fn(paper_id) if workspace_fn else None,
                            )
                        )
                    write_results(out, rows)
    write_summary(out, rows, config)
    return rows


def write_results(out_dir: Path, rows: list[dict]) -> None:
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(ROW_FIELDS))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in ROW_FIELDS})


def _mean(rows: list[dict], key: str) -> float:
    return statistics.mean(r[key] for r in rows) if rows else 0.0


def write_summary(out_dir: Path, rows: list[dict], config: ExperimentConfig) -> None:
    lines = [
        f"# Governance experiment: {config.name}",
        "",
        "Fabrication is measured identically in every regime; under `off`/`contracts` "
        "the deterministic gates ran in shadow (computed + logged, did not block), so a "
        "higher fabrication_count there is the fabrication the full stack would have caught.",
        "",
        f"{len(rows)} runs — {len(config.research_questions)} RQ(s) × {len(config.regimes)} "
        f"regime(s) × {len(config.backends)} backend(s) × {config.repeats} repeat(s).",
        "",
        "Means are taken over MEASURED runs only — runs where at least one "
        "content check actually examined something. A run whose checks were skipped "
        "(no bibliography, no table values) reports 0, and averaging that 0 in would "
        "read as 'no fabrication' when it means 'not looked at'.",
        "",
        "`fabrication` counts claims the sources positively contradict or lack: table "
        "cells disagreeing with a source value, prose numbers disagreeing with a source "
        "value named in the same sentence, and citations with no bibliography entry. "
        "`unverified` counts claims the check could not trace either way — a derived "
        "quantity and a fabricated one look identical there, so the two are reported "
        "separately and never summed.",
        "",
        "## Per-regime means",
        "",
        "| regime | n | measured | completion | mean fabrication | mean critical mismatches | "
        "mean prose mismatches | mean missing_in_bib | mean unverified | mean shadow gate failures |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_regime[r["regime"]].append(r)
    for regime in config.regimes:
        rs = by_regime.get(regime, [])
        if not rs:
            continue
        ms = [r for r in rs if r.get("measured")]
        fab = f"{_mean(ms, 'fabrication_count'):.2f}" if ms else "n/a"
        crit = f"{_mean(ms, 'critical_mismatches'):.2f}" if ms else "n/a"
        prose = f"{_mean(ms, 'prose_mismatched'):.2f}" if ms else "n/a"
        miss = f"{_mean(ms, 'missing_in_bib'):.2f}" if ms else "n/a"
        unv = f"{_mean(ms, 'unverified_count'):.2f}" if ms else "n/a"
        lines.append(
            f"| {regime} | {len(rs)} | {len(ms)} | {_mean(rs, 'completed'):.2f} | {fab} | "
            f"{crit} | {prose} | {miss} | {unv} | {_mean(rs, 'shadow_gate_failures'):.2f} |"
        )
    lines.append("")
    unmeasured = [r for r in rows if not r.get("measured")]
    if unmeasured:
        lines += [
            f"**{len(unmeasured)}/{len(rows)} runs were not measurable** "
            "(no content check examined anything): "
            + ", ".join(f"{r['regime']}/rep{r['repeat']} ({r['status']})" for r in unmeasured),
            "",
        ]

    variance = _design_dispersion(rows, config)
    if variance:
        lines += ["## Design-choice dispersion by regime (coefficient of interest)", ""]
        lines += ["| regime | n bundles | between-run variance of estimate |", "| --- | --- | --- |"]
        lines += variance
        lines.append("")

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _design_dispersion(rows: list[dict], config: ExperimentConfig) -> list[str]:
    """Best-effort: per regime, variance of the coefficient of interest across
    that cell's completed bundles (via the compare module). Empty on any error."""
    try:
        from ..compare import _variance_decomposition, load_run_record
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    by_regime: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r["completed"] and r["bundle_path"]:
            by_regime[r["regime"]].append(r["bundle_path"])
    for regime in config.regimes:
        bundles = by_regime.get(regime, [])
        if len(bundles) < 2:
            continue
        try:
            recs = [load_run_record(Path(b), f"{regime}-{i}") for i, b in enumerate(bundles)]
            v = _variance_decomposition(recs)
            overall = v.get("overall") if v.get("available") else None
            out.append(f"| {regime} | {len(bundles)} | {overall if overall is not None else 'n/a'} |")
        except Exception:  # noqa: BLE001
            continue
    return out


# ── real (server-backed) function wiring ─────────────────────────────────────


def _default_submit(*, rq, regime, backend, methodology, mode, max_cost, label) -> str | None:
    from ...cli_run import _submit_paper

    resp = _submit_paper(
        rq, methodology, mode, max_cost, backend=backend, governance=regime, title_suffix=f" [{label}]"
    )
    return resp.get("paper_id") if resp else None


def _default_poll(paper_id: str, monitor_seconds: float) -> str:
    from ...cli_run import _poll_status

    return _poll_status(paper_id, total_seconds=monitor_seconds)


def _default_export(paper_id: str, dest: Path) -> Path | None:
    from ...cli_run_matrix import _export_bundle

    return _export_bundle(paper_id, dest)


def _default_workspace(paper_id: str) -> str | None:
    """The paper's workspace dir, so a non-completed run is still measurable."""
    import httpx

    from ...cli_run import _api_root

    try:
        r = httpx.get(f"{_api_root()}/api/papers/{paper_id}", timeout=15.0)
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("workspace") or None
    except httpx.HTTPError:
        return None


def _default_events(paper_id: str) -> list:
    import httpx

    from ...cli_run import _api_root

    try:
        r = httpx.get(f"{_api_root()}/api/papers/{paper_id}/events", timeout=15.0)
        return r.json() if r.status_code == 200 else []
    except httpx.HTTPError:
        return []


def run_from_config(config: ExperimentConfig, out_dir: str | Path, monitor_seconds: float = 3600.0) -> list[dict]:
    """Run the experiment against a live (or auto-started) API server."""
    from ...cli_run import _ensure_api_up

    ok, err = _ensure_api_up()
    if not ok:
        raise RuntimeError(f"experiment driver: API not reachable: {err}")
    return run_experiment(
        config,
        out_dir,
        submit_fn=_default_submit,
        poll_fn=_default_poll,
        export_fn=_default_export,
        events_fn=_default_events,
        workspace_fn=_default_workspace,
        monitor_seconds=monitor_seconds,
    )
