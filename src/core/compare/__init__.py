"""Design-choice comparison across a set of runs (WS-P3.3).

The payoff of `e2er run-matrix`: given several runs of the SAME research
question (different backends / repeats), diff the machine-readable design
choices each model made — estimator, fixed effects, controls, clustering, the
coefficient of interest — into one overview.

This is measurement, NOT selection. It reports where models agree and where
they diverge (so you can see WHERE the institutions must bind); it never
promotes a run. Promoting one run's estimates would be a p-hacking hazard and
must be a pre-committed decision in the pre-registration, not a side effect of
comparison.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

SCHEMA_ID = "e2er-comparison/1"

PREAMBLE = (
    "These runs are versions of the SAME research question — coverage of the "
    "solution space, not a contest. No run is promoted here. Any decision to "
    "carry one run's estimates forward must be pre-committed in the "
    "pre-registration, never chosen after seeing this comparison."
)

# Field order for the design-choice matrix. Set-valued fields compared as sets.
SET_FIELDS = ("fixed_effects", "controls")
FIELD_ORDER = (
    "estimator",
    "unit_of_analysis",
    "outcome",
    "treatment",
    "fixed_effects",
    "controls",
    "cluster_level",
    "identifying_assumption",
    "n_observations",
    "coef_term",
    "coef_estimate",
    "coef_se",
    "coef_p_value",
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/short file → treated as absent
        return None


def _as_set(v: Any) -> tuple[str, ...] | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple, set)):
        return tuple(sorted(str(x) for x in v))
    return (str(v),)


def _dict(v: Any) -> dict:
    """Coerce a loaded JSON value to a dict (missing / wrong-typed → empty)."""
    return v if isinstance(v, dict) else {}


def _coef_of_interest(primary: dict, main: dict) -> tuple[str | None, dict, bool]:
    """Return (term, {estimate, se, p_value}, fell_back). Uses the spec's
    declared treatment term; falls back to the first non-intercept coefficient
    (flagged) when the treatment term isn't present."""
    coeffs = main.get("coefficients")
    if not isinstance(coeffs, dict) or not coeffs:
        return None, {"estimate": None, "se": None, "p_value": None}, False
    treat = primary.get("treatment")
    fell_back = False
    if treat and treat in coeffs:
        term = treat
    else:
        fell_back = True
        term = next(
            (k for k in coeffs if k.lower() not in ("const", "intercept", "_cons")),
            next(iter(coeffs)),
        )
    c = coeffs.get(term) or {}
    return term, {"estimate": c.get("estimate"), "se": c.get("se"), "p_value": c.get("p_value")}, fell_back


def load_run_record(bundle: Path, label: str, backend_hint: str | None = None) -> dict:
    """Extract one run's design record from an exported bundle dir."""
    bundle = Path(bundle)
    primary = _dict(_dict(_load_json(bundle / "design" / "identification_spec.json")).get("primary"))
    main = _dict(_dict(_load_json(bundle / "results" / "estimation_results.json")).get("main"))
    run_meta = _dict(_dict(_load_json(bundle / "provenance.json")).get("run"))

    term, coef, fell_back = _coef_of_interest(primary, main)

    hyp = None
    plan = bundle / "design" / "paper_plan.md"
    if plan.is_file():
        txt = " ".join(plan.read_text(encoding="utf-8", errors="replace").split())
        hyp = (txt[:150] + "…") if len(txt) > 150 else (txt or None)

    return {
        "label": label,
        "backend": backend_hint or run_meta.get("backend"),
        "model": run_meta.get("model"),
        "governance": run_meta.get("governance"),
        "bundle_path": str(bundle),
        "coef_fallback": fell_back,
        "hypotheses": hyp,
        "fields": {
            "estimator": primary.get("estimator"),
            "unit_of_analysis": primary.get("unit_of_analysis"),
            "outcome": primary.get("outcome"),
            "treatment": primary.get("treatment"),
            "fixed_effects": _as_set(primary.get("fixed_effects")),
            "controls": _as_set(primary.get("controls")),
            "cluster_level": primary.get("cluster_level"),
            "identifying_assumption": primary.get("identifying_assumption"),
            "n_observations": main.get("n_observations"),
            "coef_term": term,
            "coef_estimate": coef["estimate"],
            "coef_se": coef["se"],
            "coef_p_value": coef["p_value"],
        },
    }


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 1.0  # both empty → identical
    return len(a & b) / len(union)


def _agreement(records: list[dict], field: str) -> dict:
    values = [r["fields"].get(field) for r in records]
    present = [v for v in values if v is not None]
    if not present:
        return {"kind": "set" if field in SET_FIELDS else "scalar", "score": None, "modal": None}
    if field in SET_FIELDS:
        sets = [set(v) for v in present]
        pairs = list(combinations(range(len(sets)), 2))
        score = statistics.mean(_jaccard(sets[i], sets[j]) for i, j in pairs) if pairs else 1.0
        modal_key = Counter(frozenset(s) for s in sets).most_common(1)[0][0]
        return {"kind": "set", "score": score, "modal": sorted(modal_key)}
    counts = Counter(present)
    modal, cnt = counts.most_common(1)[0]
    return {"kind": "scalar", "score": cnt / len(present), "modal": modal}


def _variance_decomposition(records: list[dict]) -> dict:
    """Descriptive within- vs between-backend variance of the coefficient of
    interest. No significance tests — this describes dispersion, nothing more."""
    data = [
        (r["backend"] or "unknown", float(r["fields"]["coef_estimate"]))
        for r in records
        if isinstance(r["fields"]["coef_estimate"], (int, float)) and not isinstance(r["fields"]["coef_estimate"], bool)
    ]
    if len(data) < 2:
        return {"available": False, "reason": "need >= 2 numeric coefficient estimates"}
    groups: dict[str, list[float]] = defaultdict(list)
    for backend, est in data:
        groups[backend].append(est)
    within_parts = [statistics.pvariance(v) for v in groups.values() if len(v) >= 2]
    backend_means = [statistics.mean(v) for v in groups.values()]
    return {
        "available": True,
        "n_estimates": len(data),
        "n_backends": len(groups),
        "overall": statistics.pvariance([e for _, e in data]),
        "within_backend": statistics.mean(within_parts) if within_parts else None,
        "between_backend": statistics.pvariance(backend_means) if len(backend_means) >= 2 else None,
    }


def build_comparison(records: list[dict], research_question: str | None = None) -> dict:
    agreement = {f: _agreement(records, f) for f in FIELD_ORDER}
    design_matrix = {f: {r["label"]: r["fields"].get(f) for r in records} for f in FIELD_ORDER}
    divergent = [f for f in FIELD_ORDER if (agreement[f]["score"] is not None and agreement[f]["score"] < 1.0)]
    return {
        "schema": SCHEMA_ID,
        "research_question": research_question,
        "note": PREAMBLE,
        "n_runs": len(records),
        "runs": [
            {k: r[k] for k in ("label", "backend", "model", "governance", "bundle_path", "coef_fallback")}
            for r in records
        ],
        "fields": list(FIELD_ORDER),
        "design_matrix": design_matrix,
        "agreement": agreement,
        "variance": _variance_decomposition(records),
        "divergent_fields": divergent,
        "hypotheses": {r["label"]: r["hypotheses"] for r in records},
    }


# ── report rendering ─────────────────────────────────────────────────────────


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, (list, tuple)):
        return "{" + ", ".join(str(x) for x in v) + "}" if v else "∅"
    if isinstance(v, float):
        return f"{v:.4g}"
    s = str(v)
    return s if len(s) <= 40 else s[:37] + "…"


def render_report(comparison: dict) -> str:
    runs = comparison["runs"]
    labels = [r["label"] for r in runs]
    out: list[str] = ["# Design-choice comparison", ""]
    if comparison.get("research_question"):
        out += [f"**Research question:** {comparison['research_question']}", ""]
    out += [f"> {comparison['note']}", "", f"**{comparison['n_runs']} runs compared.**", ""]

    out += ["## Runs", "", "| label | backend | model | governance |", "| --- | --- | --- | --- |"]
    for r in runs:
        out.append(f"| {r['label']} | {_fmt(r['backend'])} | {_fmt(r['model'])} | {_fmt(r['governance'])} |")
    out.append("")

    # Design-choice matrix: fields × runs.
    out += ["## Design-choice matrix", ""]
    out.append("| field | agreement | " + " | ".join(labels) + " |")
    out.append("| --- | --- | " + " | ".join("---" for _ in labels) + " |")
    for f in comparison["fields"]:
        agr = comparison["agreement"][f]
        score = "n/a" if agr["score"] is None else f"{agr['score']:.2f}"
        cells = " | ".join(_fmt(comparison["design_matrix"][f][lbl]) for lbl in labels)
        flag = " ⚠️" if (agr["score"] is not None and agr["score"] < 1.0) else ""
        out.append(f"| `{f}`{flag} | {score} | {cells} |")
    out.append("")
    out += [
        "Agreement = share of runs sharing the modal value (scalars) or mean "
        "pairwise Jaccard (set-valued `fixed_effects` / `controls`). ⚠️ marks a "
        "field where the models diverged.",
        "",
    ]

    if comparison["divergent_fields"]:
        out += ["**Divergent fields:** " + ", ".join(f"`{f}`" for f in comparison["divergent_fields"]), ""]
    else:
        out += ["All compared design fields agree across runs.", ""]

    # Variance decomposition.
    v = comparison["variance"]
    out += ["## Coefficient of interest — dispersion", ""]
    if not v.get("available"):
        out += [f"_Not available: {v.get('reason', 'insufficient data')}._", ""]
    else:
        out += [
            f"Across {v['n_estimates']} numeric estimate(s) over {v['n_backends']} backend(s) "
            "(descriptive variance of the point estimate; no significance tests):",
            "",
            f"- overall: {_fmt(v['overall'])}",
            f"- within-backend (mean): {_fmt(v['within_backend'])}",
            f"- between-backend: {_fmt(v['between_backend'])}",
            "",
        ]

    # Hypotheses — prose, not diffed.
    if any(comparison["hypotheses"].values()):
        out += ["## Hypotheses (prose, not diffed)", ""]
        for lbl in labels:
            h = comparison["hypotheses"].get(lbl)
            if h:
                out.append(f"- **{lbl}:** {h}")
        out.append("")

    return "\n".join(out)


# ── input resolution + CLI entry ─────────────────────────────────────────────


def _resolve_records(paths: list[str]) -> tuple[list[dict], str | None, Path]:
    """From a single matrix.json, or 2+ bundle dirs, build run records +
    (research_question, default output dir)."""
    if len(paths) == 1 and Path(paths[0]).is_file():
        mpath = Path(paths[0])
        matrix = _load_json(mpath) or {}
        rq = matrix.get("research_question")
        records = []
        for run in matrix.get("runs", []):
            bp = run.get("bundle_path")
            if run.get("status") == "completed" and bp and Path(bp).is_dir():
                label = f"{run.get('backend')}/rep-{run.get('repeat')}"
                records.append(load_run_record(Path(bp), label, backend_hint=run.get("backend")))
        return records, rq, mpath.parent
    records = [load_run_record(Path(p), label=Path(p).name) for p in paths if Path(p).is_dir()]
    return records, None, Path.cwd()


def compare(paths: list[str], out: str | None = None, json_output: bool = False) -> int:
    """Entry point for `e2er compare`. Exit 0 on success, 2 on bad input."""
    import sys

    records, rq, default_out = _resolve_records(paths)
    if len(records) < 2:
        print(
            "compare: need >= 2 completed runs — pass a matrix.json (with 2+ completed runs) "
            "or 2+ exported bundle directories.",
            file=sys.stderr,
        )
        return 2

    comparison = build_comparison(records, research_question=rq)
    report = render_report(comparison)

    out_dir = Path(out).expanduser() if out else default_out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (out_dir / "comparison_report.md").write_text(report, encoding="utf-8")

    if json_output:
        print(json.dumps(comparison, indent=2))
    else:
        print(report)
        print(f"\nWrote {out_dir / 'comparison.json'} and {out_dir / 'comparison_report.md'}", file=sys.stderr)
    return 0
