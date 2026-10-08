"""The map: papers by year (x) in topic lanes (y), the main path drawn over the key routes.

Lanes come from ``field_lanes.json`` (a specialist proposes them as
questions, the researcher approves them). Papers no lane names go in a lane
"Not assigned to a lane". Within a lane, papers of the same year are spread
vertically in a fixed order (year, date, id), so the figure is the same on
every run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

#: Colours (validated reference palette, light surface): main path, key routes, ink.
MAIN = "#2a78d6"
KEY = "#eb6834"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
UNASSIGNED = "Not assigned to a lane"


def draw_map(
    papers: dict[str, dict[str, Any]],
    main_arcs: list[tuple[str, str]],
    key_arcs: list[tuple[str, str]],
    lanes: list[dict[str, Any]],
    out_png: Path,
    out_pdf: Path | None = None,
    title: str = "",
    numbers: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Draw the map. ``numbers`` (paper -> its number in the reading list) labels each paper with its
    number, which keeps a dense map legible; without it papers are labelled "Author year"."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shown = sorted({p for a in [*main_arcs, *key_arcs] for p in a})
    lane_of: dict[str, int] = {}
    names: list[str] = []
    for i, lane in enumerate(lanes):
        names.append(str(lane.get("question") or lane.get("id") or f"Lane {i + 1}"))
        for pid in lane.get("papers") or []:
            lane_of.setdefault(pid, i)
    if any(p not in lane_of for p in shown):
        names.append(UNASSIGNED)
        for p in shown:
            lane_of.setdefault(p, len(names) - 1)
    n_lanes = max(len(names), 1)

    def k(p: str) -> tuple[int, str, str]:
        q = papers[p]
        return (q.get("year") or 9999, q.get("date") or "", p)

    # Position: lane centre, spread within a lane by year.
    pos: dict[str, tuple[float, float]] = {}
    groups: dict[tuple[int, Any], list[str]] = {}
    for p in sorted(shown, key=k):
        groups.setdefault((lane_of[p], papers[p].get("year")), []).append(p)
    for (lane_i, year), members in groups.items():
        m = len(members)
        for j, pid in enumerate(members):
            off = 0.0 if m == 1 else (j / (m - 1) - 0.5) * 0.7
            jitter = (j % 3) * 0.12 if m > 1 else 0.0
            pos[pid] = (float(year or 0) + jitter, n_lanes - 1 - lane_i + off)

    shown_years = [int(papers[x].get("year") or 0) for x in shown]
    span = max(shown_years) - min(shown_years) if shown_years else 10
    width = min(max(12.0, 0.42 * span + 4.0), 24.0)
    height = max(3.2, 1.25 * n_lanes + 1.4)
    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for i in range(n_lanes):
        y = n_lanes - 1 - i
        if i % 2 == 0:
            ax.axhspan(y - 0.5, y + 0.5, color="#f4f3f0", zorder=0, lw=0)
    main_set = set(main_arcs)
    for u, v in key_arcs:
        if (u, v) in main_set:
            continue
        (x1, y1), (x2, y2) = pos[u], pos[v]
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops={"arrowstyle": "-|>", "color": KEY, "lw": 1.0, "alpha": 0.8, "shrinkA": 4, "shrinkB": 4},
            zorder=2,
        )
    for u, v in main_arcs:
        (x1, y1), (x2, y2) = pos[u], pos[v]
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops={"arrowstyle": "-|>", "color": MAIN, "lw": 2.2, "shrinkA": 5, "shrinkB": 5},
            zorder=3,
        )
    main_nodes = {p for a in main_arcs for p in a}
    for p in shown:
        x, y_pos = pos[p]
        on_main = p in main_nodes
        ax.scatter(
            [x],
            [y_pos],
            s=46 if on_main else 26,
            color=MAIN if on_main else KEY,
            edgecolors="white",
            linewidths=1.2,
            zorder=4,
        )
        authors = papers[p].get("authors") or []
        first = authors[0].split()[-1] if authors else "?"
        label = str(numbers[p]) if numbers and p in numbers else f"{first} {papers[p].get('year') or ''}"
        ax.annotate(
            label,
            (x, y_pos),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=7 if on_main else 6.5,
            color=INK if on_main else INK_2,
            zorder=5,
        )
    ax.set_yticks([n_lanes - 1 - i for i in range(n_lanes)])
    ax.set_yticklabels([textwrap.fill(nm, 34) for nm in names], fontsize=8, color=INK)
    ax.set_ylim(-0.6, n_lanes - 0.4)
    years = [int(papers[p]["year"]) for p in shown if papers[p].get("year")]
    if years:
        ax.set_xlim(min(years) - 1, max(years) + 1.5)
    ax.set_xlabel("Publication year", fontsize=9, color=INK_2)
    ax.tick_params(axis="x", labelsize=8, colors=INK_2)
    ax.grid(axis="x", color=GRID, lw=0.6, zorder=1)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    from matplotlib.lines import Line2D

    handles = [
        Line2D([0], [0], color=MAIN, lw=2.2, marker="o", markersize=6, label="Global main path (largest total SPC)"),
        Line2D([0], [0], color=KEY, lw=1.0, marker="o", markersize=5, label="Key routes"),
    ]
    ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0, -0.12 if n_lanes > 2 else -0.2),
        ncol=2,
        frameon=False,
        fontsize=8,
    )
    if title:
        ax.set_title(title, fontsize=11, color=INK, loc="left")
    if numbers:
        ax.text(
            1.0,
            -0.12 if n_lanes > 2 else -0.2,
            "Numbers: position in the reading list",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color=INK_2,
        )
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, facecolor="white")
    if out_pdf is not None:
        fig.savefig(out_pdf, facecolor="white")
    plt.close(fig)
    return {"papers_drawn": len(shown), "lanes": names}
