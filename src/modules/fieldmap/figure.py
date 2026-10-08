"""The map: papers by year (x) in topic lanes (y), the main path drawn over the key routes.

Lanes come from ``field_lanes.json`` (a specialist proposes them as
questions, the researcher approves them). Papers no lane names go in a band
"Not assigned to a lane" at the bottom.

Layout, all of it computed before drawing so the figure is the same on every run:

- a paper sits at its publication year; its number in the reading list is
  printed in the node and "Author Year" to its right;
- within a lane, papers are put on rows: a paper takes the free row nearest
  to the row of the paper it follows on the main path, where a row is free
  when no node or label on it reaches the paper's node. Labels therefore never
  overlap, and a lane band is as tall as its rows;
- arcs are curves with horizontal tangents, drawn in inches so their ends stop
  at the node's edge.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

#: Colours (validated reference palette, light surface): main path, key routes, ink.
MAIN = "#2a78d6"
MAIN_LIGHT = "#9cc0ea"
KEY = "#eb6834"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BAND = "#f4f3f0"
UNASSIGNED = "Not assigned to a lane"

# Geometry in inches and points.
LEFT_IN = 2.5  # margin for the lane questions
RIGHT_IN = 0.25
TOP_IN = 0.2
TITLE_IN = 0.35
BOTTOM_IN = 1.0  # year axis and legend
ROW_IN = 0.27
BAND_PAD_IN = 0.1
NODE_PT = 12.0  # node diameter
LABEL_GAP_PT = 3.0
ROW_GAP_PT = 6.0  # free space required after a label before the next node on the row
LABEL_PT = 7.5
NUMBER_PT = 5.5
LANE_PT = 8.0
LANE_WRAP = 32
PER_YEAR_IN = 0.26
PLOT_MIN_IN, PLOT_MAX_IN = 6.5, 11.0


def first_author(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") or []
    name = str(authors[0]).strip() if authors else ""
    if not name:
        return "Anonymous"
    if "," in name:  # "Surname, Given"
        return name.split(",", 1)[0].strip()
    return name.split()[-1]


def author_year_labels(papers: dict[str, dict[str, Any]], ids: list[str]) -> dict[str, str]:
    """``"Surname Year"`` for each paper, with a, b, ... where two would read the same."""

    def key(p: str) -> tuple[int, str, str]:
        q = papers[p]
        return (int(q.get("year") or 9999), str(q.get("date") or ""), p)

    base = {p: f"{first_author(papers[p])} {papers[p].get('year') or 'n.d.'}" for p in ids}
    groups: dict[str, list[str]] = {}
    for p in sorted(ids, key=key):
        groups.setdefault(base[p], []).append(p)
    out: dict[str, str] = {}
    for lab, members in groups.items():
        if len(members) == 1:
            out[members[0]] = lab
        else:
            for j, p in enumerate(members):
                out[p] = lab + _suffix(j)
    return out


def _suffix(j: int) -> str:
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(ord("a") + r) + s
    return s


def _bezier(
    p0: tuple[float, float], p3: tuple[float, float], lift: float = 0.0, n: int = 48
) -> list[tuple[float, float]]:
    (x0, y0), (x3, y3) = p0, p3
    dx = x3 - x0
    if abs(dx) < 0.05:  # same year: bow to the left, away from the labels
        c1, c2 = (x0 - 0.22, y0), (x3 - 0.22, y3)
    elif lift:  # same row: arch over the label of the citing paper's predecessor
        c1, c2 = (x0 + 0.15, y0 + lift), (x3 - 0.15, y3 + lift)
    else:
        c1, c2 = (x0 + 0.5 * dx, y0), (x3 - 0.5 * dx, y3)
    pts = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t**2, t**3
        pts.append((a * x0 + b * c1[0] + c * c2[0] + d * x3, a * y0 + b * c1[1] + c * c2[1] + d * y3))
    return pts


def _trim(pts: list[tuple[float, float]], r0: float, r1: float) -> list[tuple[float, float]]:
    (sx, sy), (ex, ey) = pts[0], pts[-1]
    kept = [
        q
        for q in pts
        if ((q[0] - sx) ** 2 + (q[1] - sy) ** 2) ** 0.5 > r0 and ((q[0] - ex) ** 2 + (q[1] - ey) ** 2) ** 0.5 > r1
    ]
    return kept if len(kept) >= 2 else [pts[0], pts[-1]]


def draw_map(
    papers: dict[str, dict[str, Any]],
    main_arcs: list[tuple[str, str]],
    key_arcs: list[tuple[str, str]],
    lanes: list[dict[str, Any]],
    out_png: Path,
    out_pdf: Path | None = None,
    title: str = "",
    numbers: dict[str, int] | None = None,
    *,
    tied_arcs: list[tuple[str, str]] | None = None,
    robust: set[str] | list[str] | None = None,
    out_svg: Path | None = None,
) -> dict[str, Any]:
    """Draw the map.

    ``main_arcs`` is the main path (one chain), ``tied_arcs`` the arcs of the other main paths with
    the same total weight (drawn lighter), ``key_arcs`` the key routes. ``numbers`` (paper -> its
    number in the reading list) are printed in the nodes; ``robust`` papers (on the main path of
    every boundary) get a ring and a bold label. Returns what was drawn, with the boxes of every
    label and node in pixels (used by the tests to check that nothing overlaps).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyArrowPatch
    from matplotlib.path import Path as MPath
    from matplotlib.ticker import MultipleLocator

    tied_arcs = [a for a in (tied_arcs or []) if a not in set(main_arcs)]
    robust_set = set(robust or [])
    shown = sorted({p for a in [*main_arcs, *tied_arcs, *key_arcs] for p in a})

    def k(p: str) -> tuple[int, str, str]:
        q = papers[p]
        return (int(q.get("year") or 9999), str(q.get("date") or ""), p)

    shown.sort(key=k)
    lane_of: dict[str, int] = {}
    names: list[str] = []
    for i, lane in enumerate(lanes):
        names.append(str(lane.get("question") or lane.get("id") or f"Lane {i + 1}"))
        for pid in lane.get("papers") or []:
            lane_of.setdefault(pid, i)
    if not names or any(p not in lane_of for p in shown):
        names.append(UNASSIGNED)
        for p in shown:
            lane_of.setdefault(p, len(names) - 1)
    n_lanes = len(names)
    labels = author_year_labels(papers, shown)
    main_nodes = {p for a in main_arcs for p in a}
    tied_nodes = {p for a in tied_arcs for p in a} - main_nodes

    # ── horizontal scale: years -> inches ────────────────────────────────────
    years = [int(papers[p].get("year") or 0) for p in shown] or [2000]
    x_min = min(years) - 1.0
    x_last = max(years)
    plot_w = min(max(PER_YEAR_IN * (x_last - x_min + 4), PLOT_MIN_IN), PLOT_MAX_IN)
    width = LEFT_IN + plot_w + RIGHT_IN

    fig = plt.figure(figsize=(width, 4.0), dpi=150)
    renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]

    def text_w_in(s: str, size: float, bold: bool = False) -> float:
        t = fig.text(0, 0, s, fontsize=size, fontweight="bold" if bold else "normal")
        w = t.get_window_extent(renderer).width / fig.dpi
        t.remove()
        return float(w)

    node_r_in = NODE_PT / 2 / 72
    label_w = {p: text_w_in(labels[p], LABEL_PT, p in robust_set) for p in shown}
    reach_in = {p: node_r_in + LABEL_GAP_PT / 72 + label_w[p] + ROW_GAP_PT / 72 for p in shown}
    # Inches per year: the last label must end inside the plot.
    per_year = min(
        [plot_w / (x_last + 1.0 - x_min)]
        + [(plot_w - reach_in[p]) / max(int(papers[p].get("year") or 0) - x_min, 0.5) for p in shown]
    )
    per_year = max(per_year, 0.05)
    x_max = x_min + plot_w / per_year

    def xin(year: float) -> float:
        return (year - x_min) * per_year

    # ── rows within each lane ────────────────────────────────────────────────
    pred: dict[str, str] = {}
    for u, v in [*main_arcs, *tied_arcs, *key_arcs]:
        pred.setdefault(v, u)
    row_of: dict[str, int] = {}
    row_end: dict[int, list[float]] = {i: [] for i in range(n_lanes)}  # inches where each row is free again
    for p in shown:
        lane_i = lane_of[p]
        x0 = xin(int(papers[p].get("year") or 0)) - node_r_in - 1 / 72
        ends = row_end[lane_i]
        q = pred.get(p)
        want = row_of[q] if q is not None and q in row_of and lane_of[q] == lane_i else 0
        free = [r for r, e in enumerate(ends) if e <= x0]
        candidates = [*free, len(ends)]
        r = min(candidates, key=lambda c: (abs(c - want), c))
        if r == len(ends):
            ends.append(0.0)
        ends[r] = xin(int(papers[p].get("year") or 0)) + reach_in[p]
        row_of[p] = r
    n_rows = [max(len(row_end[i]), 1) for i in range(n_lanes)]
    wrapped = [textwrap.fill(nm, LANE_WRAP) for nm in names]
    line_in = LANE_PT * 1.25 / 72
    band_h = [
        max(n_rows[i] * ROW_IN + 2 * BAND_PAD_IN, (wrapped[i].count("\n") + 1) * line_in + 2 * BAND_PAD_IN)
        for i in range(n_lanes)
    ]
    plot_h = sum(band_h)
    top = TOP_IN + (TITLE_IN if title else 0.0)
    height = top + plot_h + BOTTOM_IN
    fig.set_size_inches(width, height)
    ax = fig.add_axes((LEFT_IN / width, BOTTOM_IN / height, plot_w / width, plot_h / height))
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, plot_h)  # y in inches from the bottom of the plot
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    band_top: list[float] = []
    y_cursor = plot_h
    for i in range(n_lanes):
        band_top.append(y_cursor)
        if i % 2 == 0:
            ax.axhspan(y_cursor - band_h[i], y_cursor, color=BAND, zorder=0, lw=0)
        y_cursor -= band_h[i]
    pos_in: dict[str, tuple[float, float]] = {}
    for p in shown:
        i = lane_of[p]
        y = band_top[i] - BAND_PAD_IN - (row_of[p] + 0.5) * ROW_IN
        # Centre the rows in a band made taller by its question.
        y -= (band_h[i] - 2 * BAND_PAD_IN - n_rows[i] * ROW_IN) / 2
        pos_in[p] = (xin(int(papers[p].get("year") or 0)), y)

    # ── arcs ─────────────────────────────────────────────────────────────────
    def draw_arc(u: str, v: str, color: str, lw: float, z: int, alpha: float = 1.0) -> None:
        same_row = lane_of[u] == lane_of[v] and row_of[u] == row_of[v]
        pts = _bezier(pos_in[u], pos_in[v], lift=0.42 * ROW_IN * 4 / 3 if same_row else 0.0)
        r_end = node_r_in + (2.5 / 72 if v in robust_set else 0.5 / 72)
        r_start = node_r_in + (2.5 / 72 if u in robust_set else 0.5 / 72)
        pts = _trim(pts, r_start, r_end)
        verts = [(x / per_year + x_min, y) for x, y in pts]
        ax.add_patch(
            FancyArrowPatch(
                path=MPath(verts),
                arrowstyle="-|>,head_length=4,head_width=2",
                mutation_scale=1,
                color=color,
                lw=lw,
                alpha=alpha,
                zorder=z,
                shrinkA=0,
                shrinkB=0,
            )
        )

    drawn = set(main_arcs) | set(tied_arcs)
    for u, v in sorted(set(key_arcs) - drawn, key=lambda a: (k(a[0]), k(a[1]))):
        draw_arc(u, v, KEY, 0.8, 2, 0.85)
    for u, v in sorted(tied_arcs, key=lambda a: (k(a[0]), k(a[1]))):
        draw_arc(u, v, MAIN_LIGHT, 1.0, 3)
    for u, v in main_arcs:
        draw_arc(u, v, MAIN, 1.6, 4)

    # ── nodes and labels ─────────────────────────────────────────────────────
    texts = []
    nodes: list[tuple[float, float, float]] = []
    for p in shown:
        x_in, y = pos_in[p]
        x = x_in / per_year + x_min
        colour = MAIN if p in main_nodes else MAIN_LIGHT if p in tied_nodes else KEY
        if p in robust_set:
            ax.scatter([x], [y], s=(NODE_PT + 5) ** 2, facecolor="none", edgecolors=INK, linewidths=1.0, zorder=5)
        ax.scatter([x], [y], s=NODE_PT**2, color=colour, edgecolors="white", linewidths=0.8, zorder=6)
        nodes.append((x, y, NODE_PT + (5.0 if p in robust_set else 0.0)))
        if numbers and p in numbers:
            ax.text(
                x, y, str(numbers[p]), fontsize=NUMBER_PT, color="white", ha="center", va="center",
                fontweight="bold", zorder=7,
            )  # fmt: skip
        texts.append(
            ax.annotate(
                labels[p],
                (x, y),
                xytext=(NODE_PT / 2 + LABEL_GAP_PT, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=LABEL_PT,
                fontweight="bold" if p in robust_set else "normal",
                color=INK if p in main_nodes else INK_2,
                zorder=7,
                # Arcs pass behind a label, not through it.
                bbox={
                    "boxstyle": "square,pad=0.08",
                    "fc": BAND if lane_of[p] % 2 == 0 else "white",
                    "ec": "none",
                    "alpha": 0.9,
                },
            )
        )

    # ── lanes, axis, legend ──────────────────────────────────────────────────
    lane_texts = []
    for i in range(n_lanes):
        if i:
            ax.axhline(band_top[i], color=GRID, lw=0.6, zorder=1)
        lane_texts.append(
            fig.text(
                0.12 / width,
                (BOTTOM_IN + band_top[i] - band_h[i] / 2) / height,
                wrapped[i],
                fontsize=LANE_PT,
                color=INK if names[i] != UNASSIGNED else INK_2,
                style="italic" if names[i] == UNASSIGNED else "normal",
                ha="left",
                va="center",
                linespacing=1.25,
            )
        )
    ax.set_yticks([])
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    ax.tick_params(axis="x", which="major", labelsize=8, colors=INK_2, length=4)
    ax.tick_params(axis="x", which="minor", length=2, colors=GRID)
    ax.grid(axis="x", which="major", color=GRID, lw=0.6, zorder=1)
    ax.set_xlabel("Publication year", fontsize=8.5, color=INK_2)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    handles = [Line2D([0], [0], color=MAIN, lw=1.6, marker="o", markersize=6, label="Main path")]
    if tied_arcs:
        handles.append(
            Line2D(
                [0], [0], color=MAIN_LIGHT, lw=1.0, marker="o", markersize=6, label="Other main paths of equal weight"
            )
        )
    if set(key_arcs) - drawn:
        handles.append(Line2D([0], [0], color=KEY, lw=0.8, marker="o", markersize=6, label="Key routes"))
    if robust_set & set(shown):
        handles.append(
            Line2D(
                [0], [0], lw=0, marker="o", markersize=8, markerfacecolor="none", markeredgecolor=INK,
                label="On the main path of every boundary (bold)",
            )
        )  # fmt: skip
    if numbers:
        handles.append(Line2D([0], [0], lw=0, label="Numbers: position in the reading list"))
    legend = fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(LEFT_IN / width, 0.08 / height),
        ncol=min(len(handles), 3),
        frameon=False,
        fontsize=8,
        handlelength=2.2,
        columnspacing=1.6,
    )
    if title:
        fig.text(LEFT_IN / width, 1 - (TOP_IN + 0.05) / height, title, fontsize=11, color=INK, ha="left", va="top")

    fig.canvas.draw()
    label_boxes = [tuple(t.get_window_extent(renderer).bounds) for t in texts]
    node_boxes = []
    for x, y, diameter in nodes:
        cx, cy = ax.transData.transform((x, y))
        r_px = diameter / 2 / 72 * fig.dpi
        node_boxes.append((float(cx - r_px), float(cy - r_px), 2 * r_px, 2 * r_px))
    lane_boxes = [tuple(t.get_window_extent(renderer).bounds) for t in lane_texts]
    legend_box = tuple(legend.get_window_extent(renderer).bounds)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, facecolor="white", metadata={"Software": None})
    if out_svg is not None:
        with matplotlib.rc_context({"svg.hashsalt": "e2er-field-map"}):
            fig.savefig(out_svg, facecolor="white", metadata={"Date": None, "Creator": None})
    if out_pdf is not None:
        fig.savefig(out_pdf, facecolor="white", metadata={"CreationDate": None, "Creator": None, "Producer": None})
    plt.close(fig)
    return {
        "papers_drawn": len(shown),
        "lanes": names,
        "size_in": (round(width, 2), round(height, 2)),
        "label_boxes": dict(zip(shown, label_boxes, strict=True)),
        "node_boxes": dict(zip(shown, node_boxes, strict=True)),
        "lane_boxes": lane_boxes,
        "legend_box": legend_box,
        "plot_box": tuple(ax.get_window_extent(renderer).bounds),
    }
