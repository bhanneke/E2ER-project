"""Deterministic figure rendering — figure_spec.json → PDF files.

The figure analogue of ``tables.py``. The drafter authors a declarative
``figure_spec.json`` (each entry: a ``figure_type`` plus the real values to
plot — coefficients, event-study paths, channel bars); this module renders each
to ``<filename>.pdf`` at the workspace root, where the draft's
``\\includegraphics{fig_*.pdf}`` references them (bare filename, no path).

Like the table renderer this is first-party deterministic code called by the
runner, NOT an LLM specialist. Design rules mirror ``tables.py``:

- **Never raise.** A bad/unknown figure is skipped with an entry in
  ``figure_render_report.json`` — a *detectable* gap, never a crash.
- **Idempotent.** Re-rendering the same spec yields the same files; the runner
  re-renders before the verify gate and before compile so revisions don't leave
  stale figures.
- **Headless.** matplotlib Agg backend, no display, fonts embedded in the PDF.

Supported ``figure_type`` values: ``coefficient`` (horizontal dot-and-whisker
with CIs), ``event_study`` (point + error-bar path with treatment marker),
``bar`` (category bars), ``time_series`` (one line per ``{label,x,y}`` series),
and ``multi_panel`` (a grid of ``panels``, each itself one of the above).
Unknown types are skipped (reported), not guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class FigureRenderReport:
    rendered: list[str] = field(default_factory=list)  # filenames written
    skipped: list[str] = field(default_factory=list)  # "<filename>: <reason>"
    errors: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)  # missing figs stubbed
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floats(values: Any) -> list[float] | None:
    """Coerce a list to floats, or None if any element isn't numeric."""
    if not isinstance(values, list) or not values:
        return None
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        out.append(float(v))
    return out


def _asymmetric_err(estimates: list[float], lo: list[float], hi: list[float]) -> list[list[float]]:
    """matplotlib yerr/xerr format: [[below...], [above...]], clamped >= 0."""
    below = [max(0.0, e - lo_i) for e, lo_i in zip(estimates, lo, strict=False)]
    above = [max(0.0, hi_i - e) for e, hi_i in zip(estimates, hi, strict=False)]
    return [below, above]


def _render_coefficient(fig_spec: dict[str, Any], ax: Any) -> None:
    coefs = fig_spec.get("coefficients")
    if not isinstance(coefs, list) or not coefs:
        raise ValueError("coefficient figure missing non-empty 'coefficients'")
    names = [str(c.get("name", f"coef {i}")) for i, c in enumerate(coefs)]
    est = _floats([c.get("estimate") for c in coefs])
    lo = _floats([c.get("ci_lower") for c in coefs])
    hi = _floats([c.get("ci_upper") for c in coefs])
    if est is None:
        raise ValueError("coefficient figure has non-numeric estimates")
    ys = list(range(len(coefs)))
    xerr = _asymmetric_err(est, lo, hi) if (lo and hi) else None
    ax.errorbar(est, ys, xerr=xerr, fmt="o", color="#1f4e79", ecolor="#1f4e79", capsize=4, markersize=6, lw=1.5)
    ref = fig_spec.get("reference_line")
    if isinstance(ref, (int, float)) and not isinstance(ref, bool):
        ax.axvline(float(ref), color="0.5", ls="--", lw=1)
    ax.set_yticks(ys)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel(str(fig_spec.get("x_label", "")))
    ax.grid(axis="x", ls=":", alpha=0.4)


def _render_event_study(fig_spec: dict[str, Any], ax: Any) -> None:
    periods = _floats(fig_spec.get("periods"))
    est = _floats(fig_spec.get("estimates"))
    if periods is None or est is None or len(periods) != len(est):
        raise ValueError("event_study needs equal-length numeric 'periods' and 'estimates'")
    lo = _floats(fig_spec.get("ci_lower"))
    hi = _floats(fig_spec.get("ci_upper"))
    yerr = _asymmetric_err(est, lo, hi) if (lo and hi and len(lo) == len(est) == len(hi)) else None
    ax.errorbar(periods, est, yerr=yerr, fmt="o-", color="#1f4e79", ecolor="#1f4e79", capsize=4, markersize=6, lw=1.5)
    ax.axhline(0, color="0.5", ls=":", lw=1)
    treat = fig_spec.get("treatment_period")
    if isinstance(treat, (int, float)) and not isinstance(treat, bool):
        ax.axvline(float(treat), color="#c0392b", ls="--", lw=1, alpha=0.7)
    ax.set_xlabel(str(fig_spec.get("x_label", "")))
    ax.set_ylabel(str(fig_spec.get("y_label", "")))
    ax.grid(ls=":", alpha=0.4)


def _render_bar(fig_spec: dict[str, Any], ax: Any) -> None:
    cats = fig_spec.get("categories")
    vals = _floats(fig_spec.get("values"))
    if not isinstance(cats, list) or vals is None or len(cats) != len(vals):
        raise ValueError("bar figure needs equal-length 'categories' and numeric 'values'")
    labels = [str(c) for c in cats]
    bars = ax.bar(labels, vals, color="#1f4e79")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    ax.set_ylabel(str(fig_spec.get("y_label", "")))
    ax.margins(y=0.15)
    if any(len(label) > 8 for label in labels):
        for tick in ax.get_xticklabels():
            tick.set_rotation(20)
            tick.set_ha("right")


def _render_time_series(fig_spec: dict[str, Any], ax: Any) -> None:
    series = fig_spec.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("time_series needs a non-empty 'series' list")
    plotted = 0
    have_labels = False
    for s in series:
        if not isinstance(s, dict):
            continue
        x = s.get("x")
        y = _floats(s.get("y"))
        if not isinstance(x, list) or y is None or len(x) != len(y):
            continue
        label = str(s.get("label", "")) or None
        ax.plot(x, y, marker="o", markersize=3, linewidth=1.5, label=label)
        have_labels = have_labels or label is not None
        plotted += 1
    if plotted == 0:
        raise ValueError("time_series had no plottable {label,x,y} series")
    ax.set_xlabel(str(fig_spec.get("x_label", "")))
    ax.set_ylabel(str(fig_spec.get("y_label", "")))
    if have_labels:
        ax.legend(fontsize=8)
    ax.grid(ls=":", alpha=0.4)


# Single-axes renderers, dispatched by figure_type. multi_panel is composed
# from these onto subplots (it needs the figure, not one axes — handled in
# render_figures).
_RENDERERS = {
    "coefficient": _render_coefficient,
    "event_study": _render_event_study,
    "bar": _render_bar,
    "time_series": _render_time_series,
}


def _render_multi_panel(plt: Any, fig_spec: dict[str, Any]) -> Any:
    """Compose a grid of sub-panels, each itself a single-axes figure_type.
    Returns the matplotlib Figure. Raises if there are no usable panels."""
    panels = fig_spec.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("multi_panel needs a non-empty 'panels' list")
    ncols = max(1, int(fig_spec.get("ncols") or 1))
    nrows = -(-len(panels) // ncols)  # ceil division
    fig, axes = plt.subplots(nrows, ncols, figsize=(6.0 * ncols, 4.0 * nrows), squeeze=False)
    flat = [ax for row in axes for ax in row]
    for i, panel in enumerate(panels):
        ax = flat[i]
        renderer = _RENDERERS.get(str(panel.get("figure_type", ""))) if isinstance(panel, dict) else None
        if renderer is None:
            ax.text(0.5, 0.5, "[unsupported panel]", ha="center", va="center", color="0.5")
            ax.axis("off")
            continue
        try:
            renderer(panel, ax)
        except Exception:  # noqa: BLE001 — one bad panel must not abort the grid
            ax.clear()
            ax.text(0.5, 0.5, "[panel render error]", ha="center", va="center", color="0.5")
            ax.axis("off")
        title = panel.get("title")
        if title:
            ax.set_title(str(title), fontsize=10)
    for j in range(len(panels), len(flat)):  # hide unused cells
        flat[j].axis("off")
    return fig


def render_figures(workspace: Path) -> FigureRenderReport:
    """Render every figure in ``figure_spec.json`` to ``<filename>.pdf`` at the
    workspace root. Idempotent, never raises; writes ``figure_render_report.json``."""
    workspace = Path(workspace)
    spec_path = workspace / "figure_spec.json"
    if not spec_path.is_file():
        return FigureRenderReport(skipped_reason="no figure_spec.json in workspace")

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        report = FigureRenderReport(skipped_reason=f"figure_spec.json unparseable: {e}")
        _save_report(workspace, report)
        return report
    figures = spec.get("figures") if isinstance(spec, dict) else None
    if not isinstance(figures, list):
        report = FigureRenderReport(skipped_reason="figure_spec.json has no 'figures' list")
        _save_report(workspace, report)
        return report

    # Headless backend; import lazily so a missing matplotlib degrades to a
    # reported skip (the compiler tolerates missing figures) rather than an
    # import error at module load.
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        report = FigureRenderReport(skipped_reason=f"matplotlib unavailable: {e}")
        _save_report(workspace, report)
        return report

    report = FigureRenderReport()
    for fig_spec in figures:
        if not isinstance(fig_spec, dict):
            report.errors.append("non-object entry in figures list")
            continue
        filename = str(fig_spec.get("filename", "")).strip()
        if not filename or "/" in filename or not filename.endswith(".pdf"):
            report.errors.append(f"invalid figure filename: {filename!r}")
            continue
        ftype = str(fig_spec.get("figure_type", ""))
        if ftype == "multi_panel":
            try:
                fig = _render_multi_panel(plt, fig_spec)
                fig.tight_layout()
                fig.savefig(workspace / filename, format="pdf", bbox_inches="tight")
                plt.close(fig)
                report.rendered.append(filename)
            except Exception as e:  # noqa: BLE001
                logger.warning("render_figures: failed to render %s: %s", filename, e)
                report.skipped.append(f"{filename}: {e}")
                try:
                    plt.close("all")
                except Exception:  # noqa: BLE001
                    pass
            continue
        renderer = _RENDERERS.get(ftype)
        if renderer is None:
            report.skipped.append(f"{filename}: unknown figure_type {ftype!r}")
            continue
        try:
            fig, ax = plt.subplots(figsize=(6.0, 4.0))
            renderer(fig_spec, ax)
            fig.tight_layout()
            fig.savefig(workspace / filename, format="pdf", bbox_inches="tight")
            plt.close(fig)
            report.rendered.append(filename)
        except Exception as e:  # noqa: BLE001 — one bad figure must not abort the rest
            logger.warning("render_figures: failed to render %s: %s", filename, e)
            report.skipped.append(f"{filename}: {e}")
            try:
                plt.close("all")
            except Exception:  # noqa: BLE001
                pass

    logger.info("render_figures: wrote %d figure(s) to %s", len(report.rendered), workspace)
    _save_report(workspace, report)
    return report


def _save_report(workspace: Path, report: FigureRenderReport) -> None:
    try:
        (workspace / "figure_render_report.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("render_figures: could not write figure_render_report.json: %s", e)


_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")


def ensure_figure_placeholders(workspace: Path) -> list[str]:
    """Emit a tiny placeholder PDF for any ``\\includegraphics{...}`` in the
    draft with no file on disk, so a missing figure can never break the build
    even on engines without continue-on-errors. Returns the names stubbed.

    Mirrors ``tables.ensure_input_stubs``. Best-effort; needs matplotlib (the
    same dep the real figures use) — degrades to a no-op without it.
    """
    workspace = Path(workspace)
    draft = workspace / "paper_draft.tex"
    if not draft.is_file():
        return []
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return []

    text = draft.read_text(encoding="utf-8", errors="replace")
    created: list[str] = []
    for m in _GRAPHICS_RE.finditer(text):
        ref = m.group(1).strip()
        # LaTeX adds an extension when omitted; placeholders are PDFs.
        name = ref if "." in Path(ref).name else ref + ".pdf"
        if "/" in name:  # only stub workspace-root figures the draft references bare
            continue
        target = workspace / name
        if target.exists():
            continue
        try:
            fig, ax = plt.subplots(figsize=(6.0, 4.0))
            ax.text(0.5, 0.5, f"[figure not generated]\n{name}", ha="center", va="center", fontsize=11, color="0.5")
            ax.axis("off")
            fig.savefig(target, format="pdf")
            plt.close(fig)
            created.append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("ensure_figure_placeholders: could not stub %s: %s", name, e)
    if created:
        logger.warning("ensure_figure_placeholders: stubbed %d missing figure(s): %s", len(created), created)
    return created
