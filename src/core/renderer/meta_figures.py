"""The figures of a systematic review and meta-analysis: forest plot, funnel plot, PRISMA 2020 flow diagram.

Figure types of ``figure_spec.json`` (see ``skills/files/data/figure-spec.md``),
drawn with matplotlib from the values the entry holds, which the synthesis
step copies from ``estimation_results.json``:

- ``forest``: one row per study (estimate and confidence interval, the marker
  sized by its weight), the pooled estimate as a diamond, the prediction
  interval as a line under it, and the line of no effect (``null_value``);
  ``log_x`` for ratios.
- ``funnel``: each study's estimate against its standard error (inverted
  axis), the pooled estimate and the 95% pseudo-confidence region around it,
  and the studies trim and fill added (``filled``) as open markers.
- ``prisma``: the PRISMA 2020 flow of records (Page et al. 2021): identified,
  duplicates removed, screened, excluded, sought, not retrieved, assessed,
  excluded with reasons, included in the review and in the meta-analysis.
"""

from __future__ import annotations

from typing import Any


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    return float(x)


def build_forest(plt: Any, spec: dict[str, Any]) -> Any:
    studies = [s for s in spec.get("studies") or [] if isinstance(s, dict)]
    if not studies:
        raise ValueError("a forest plot needs 'studies' (label, estimate, lower, upper)")
    rows = len(studies) + 3
    fig, ax = plt.subplots(figsize=(7.0, max(3.0, 0.32 * rows + 1.2)))
    weights = [_num(s.get("weight")) or 0.0 for s in studies]
    wmax = max(weights) or 1.0
    for i, s in enumerate(studies):
        yv = rows - 1 - i
        est, lo, hi = _num(s.get("estimate")), _num(s.get("lower")), _num(s.get("upper"))
        if est is None or lo is None or hi is None:
            raise ValueError(f"study {s.get('label')!r} needs estimate, lower and upper")
        ax.plot([lo, hi], [yv, yv], color="0.25", lw=1)
        size = 20 + 120 * (weights[i] / wmax) if weights[i] else 30
        ax.scatter([est], [yv], marker="s", s=size, color="0.25", zorder=3)
    labels = [str(s.get("label") or "") for s in studies]
    ticks: list[float] = [float(rows - 1 - i) for i in range(len(studies))]
    pooled = spec.get("pooled") if isinstance(spec.get("pooled"), dict) else None
    if pooled:
        est, lo, hi = (_num(pooled.get(k)) for k in ("estimate", "lower", "upper"))
        if est is not None and lo is not None and hi is not None:
            yp = 1.0
            ax.fill([lo, est, hi, est], [yp, yp + 0.3, yp, yp - 0.3], color="#1f4e79", zorder=3)
            ticks.append(yp)
            labels.append(str(pooled.get("label") or "Pooled"))
    pred = spec.get("prediction") if isinstance(spec.get("prediction"), dict) else None
    if pred and _num(pred.get("lower")) is not None and _num(pred.get("upper")) is not None:
        ax.plot([pred["lower"], pred["upper"]], [0.3, 0.3], color="#1f4e79", lw=2.5, alpha=0.5)
        ticks.append(0.3)
        labels.append("Prediction interval")
    null = _num(spec.get("null_value"))
    if null is not None:
        ax.axvline(null, color="0.5", ls="--", lw=0.8)
    if spec.get("log_x"):
        ax.set_xscale("log")
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_ylim(-0.3, rows - 0.4)
    ax.set_xlabel(str(spec.get("x_label") or "Effect"))
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    if spec.get("title"):
        ax.set_title(str(spec["title"]), fontsize=10)
    fig.tight_layout()
    return fig


def render_funnel(spec: dict[str, Any], ax: Any) -> None:
    pts = [p for p in spec.get("points") or [] if isinstance(p, dict)]
    xs = [_num(p.get("estimate")) for p in pts]
    ses = [_num(p.get("se")) for p in pts]
    if not pts or any(v is None for v in xs + ses):
        raise ValueError("a funnel plot needs 'points' (estimate, se)")
    ax.scatter(xs, ses, color="0.2", s=22, zorder=3, label="Studies")
    filled = [p for p in spec.get("filled") or [] if isinstance(p, dict)]
    if filled:
        ax.scatter(
            [p["estimate"] for p in filled],
            [p["se"] for p in filled],
            facecolors="white",
            edgecolors="0.2",
            s=22,
            zorder=3,
            label="Added by trim and fill",
        )
    pooled = _num(spec.get("pooled"))
    top = max(s for s in ses if s is not None) * 1.1
    if pooled is not None:
        ax.axvline(pooled, color="#1f4e79", lw=1)
        ax.plot([pooled - 1.96 * top, pooled, pooled + 1.96 * top], [top, 0, top], color="0.5", ls="--", lw=0.8)
    ax.set_ylim(top, 0)
    ax.set_xlabel(str(spec.get("x_label") or "Effect"))
    ax.set_ylabel("Standard error")
    if filled:
        ax.legend(fontsize=7, frameon=False)
    if spec.get("title"):
        ax.set_title(str(spec["title"]), fontsize=10)


def build_prisma(plt: Any, spec: dict[str, Any]) -> Any:
    c = spec.get("counts")
    if not isinstance(c, dict):
        raise ValueError("a PRISMA flow diagram needs 'counts'")
    ident = c.get("identified") or {}
    by_db = ident.get("by_database") or {}
    db_text = "; ".join(f"{k}: {v}" for k, v in by_db.items())

    def reasons(d: Any) -> str:
        if not isinstance(d, dict) or not d:
            return ""
        return "\n" + "\n".join(f"  {k}: {v}" for k, v in d.items())

    left = [
        (f"Records identified (n = {ident.get('total')})" + (f"\n{db_text}" if db_text else ""), "Identification"),
        (f"Records screened (n = {c.get('screened')})", "Screening"),
        (f"Reports sought for retrieval (n = {c.get('sought_for_full_text')})", ""),
        (f"Reports assessed for eligibility (n = {c.get('sought_for_full_text')})", ""),
        (
            f"Studies included in the review (n = {c.get('included_in_review')})\n"
            f"in the meta-analysis (n = {c.get('included_in_meta_analysis')})",
            "Included",
        ),
    ]
    right = [
        f"Duplicates removed (n = {c.get('duplicates_removed')})",
        f"Records excluded (n = {c.get('excluded_on_title_abstract')})"
        + reasons(c.get("excluded_on_title_abstract_by_criterion")),
        f"Reports not retrieved (n = {c.get('full_text_not_retrieved')})\nassessed on the abstract",
        f"Reports excluded (n = {c.get('excluded_at_eligibility')})"
        + reasons(c.get("excluded_at_eligibility_by_criterion")),
        "",
    ]
    fig, ax = plt.subplots(figsize=(7.5, 8.0))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ys = [9.0, 7.0, 5.2, 3.4, 1.2]
    box = {"boxstyle": "square,pad=0.4", "fc": "white", "ec": "0.2", "lw": 0.8}
    for i, ((text, stage), y) in enumerate(zip(left, ys, strict=True)):
        ax.text(3.0, y, text, ha="center", va="center", fontsize=8, bbox=box)
        if stage:
            ax.text(0.15, y, stage, ha="left", va="center", fontsize=8, rotation=90, color="0.3")
        if i < len(left) - 1:
            ax.annotate("", xy=(3.0, ys[i + 1] + 0.45), xytext=(3.0, y - 0.45), arrowprops={"arrowstyle": "->"})
        if right[i]:
            ax.text(7.4, y, right[i], ha="center", va="center", fontsize=7.5, bbox=box)
            ax.annotate("", xy=(5.6, y), xytext=(4.9, y), arrowprops={"arrowstyle": "->"})
    if spec.get("title"):
        ax.set_title(str(spec["title"]), fontsize=10)
    return fig


#: figure_type -> a function (plt, spec) -> Figure, for figures that size their own canvas.
BUILDERS = {"forest": build_forest, "prisma": build_prisma}
#: figure_type -> a single-axes renderer (spec, ax).
RENDERERS = {"funnel": render_funnel}
