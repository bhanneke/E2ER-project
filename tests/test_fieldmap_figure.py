"""The field map figure: labels, layout without overlaps, deterministic files.

Overlaps are checked on the rendered figure: every label's and node's box in
pixels, as matplotlib draws them.
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path
from typing import Any

import pytest

from src.modules.fieldmap.figure import UNASSIGNED, author_year_labels, draw_map, first_author

Box = tuple[float, float, float, float]  # x0, y0, width, height in pixels


def _overlap(a: Box, b: Box, tol: float = 0.5) -> bool:
    return (
        a[0] + a[2] - tol > b[0] and b[0] + b[2] - tol > a[0] and a[1] + a[3] - tol > b[1] and b[1] + b[3] - tol > a[1]
    )


def _inside(a: Box, outer: Box) -> bool:
    return a[0] >= outer[0] - 0.5 and a[1] >= outer[1] - 0.5 and a[0] + a[2] <= outer[0] + outer[2] + 0.5


def _check_layout(r: dict[str, Any]) -> None:
    labels: dict[str, Box] = r["label_boxes"]
    nodes: dict[str, Box] = r["node_boxes"]
    for (p, a), (q, b) in itertools.combinations(labels.items(), 2):
        assert not _overlap(a, b), f"labels of {p} and {q} overlap"
    for p, a in labels.items():
        for q, b in nodes.items():
            assert not _overlap(a, b), f"label of {p} overlaps the node of {q}"
        assert _inside(a, r["plot_box"]), f"label of {p} leaves the plot"
    for (p, a), (q, b) in itertools.combinations(nodes.items(), 2):
        assert not _overlap(a, b, tol=1.0), f"nodes {p} and {q} overlap"
    plot = r["plot_box"]
    for box in r["lane_boxes"]:
        assert box[0] + box[2] <= plot[0], "a lane question runs into the plot"
    for a, b in itertools.combinations(r["lane_boxes"], 2):
        assert not _overlap(a, b)
    assert r["legend_box"][1] + r["legend_box"][3] <= plot[1], "the legend runs into the plot"


def _small() -> tuple[dict[str, dict[str, Any]], list, list, list, list]:
    papers = {
        "A": {"year": 1990, "authors": ["Norman P. Hummon", "Patrick Doreian"]},
        "B": {"year": 1991, "authors": ["Vladimir Batagelj"]},
        "C": {"year": 1992, "authors": ["John S. Liu"]},
        "D": {"year": 1993, "authors": ["John S. Liu"]},
        "E": {"year": 1993, "authors": ["Louis Y. Y. Lu"], "date": "1993-05-01"},
        "F": {"year": 1995, "authors": []},
    }
    main = [("A", "C"), ("C", "E"), ("E", "F")]
    tied = [("B", "C"), ("C", "D"), ("D", "F")]
    key = [("B", "C"), ("C", "D")]
    lanes = [{"id": "m", "question": "How is a main path computed?", "papers": ["A", "B", "C", "D"]}]
    return papers, main, tied, key, lanes


def _demo_size(seed: int = 7) -> tuple[dict[str, dict[str, Any]], list, list, list, list]:
    """About the size of the live check: 4 lanes and unassigned papers, 1989 to 2025, dense recent years."""
    rnd = random.Random(seed)
    names = ["Hummon", "Lucio-Arias", "Liu", "Liu", "Chuang", "Ho", "Yu", "Rejeb", "Rejeb", "Kim", "Xiao", "Batagelj"]
    years = [1989, 1993, 2003, 2008, 2011, 2012, 2012, 2014, 2015, 2016, 2016, 2019, 2020, 2021, 2021]
    years += [2022, 2022, 2022, 2023, 2023, 2023, 2024, 2024, 2024, 2024, 2025, 2025, 2025, 2025, 2025]
    papers = {
        f"P{i:02d}": {"year": y, "authors": [f"Given {rnd.choice(names)}"], "date": f"{y}-0{1 + i % 9}-01"}
        for i, y in enumerate(years)
    }
    ids = sorted(papers, key=lambda p: (papers[p]["year"], papers[p]["date"], p))
    main = list(itertools.pairwise(ids[::2]))
    tied = [(ids[1], ids[4]), (ids[4], ids[6])]
    key = list(itertools.pairwise(ids[1::2])) + [(ids[0], ids[3])]
    lanes = [
        {"id": "a", "question": "How should a main path be computed and read?", "papers": ids[0:30:4]},
        {"id": "b", "question": "How did data envelopment analysis develop?", "papers": ids[1:30:4]},
        {"id": "c", "question": "Where did tourism research go?", "papers": ids[2:30:4]},
        {"id": "d", "question": "Which fields have been traced with main paths since 2020?", "papers": ids[3:22:4]},
    ]
    return papers, main, tied, key, lanes


def test_first_author_surname_in_both_name_orders():
    assert first_author({"authors": ["Norman P. Hummon"]}) == "Hummon"
    assert first_author({"authors": ["Hummon, Norman P."]}) == "Hummon"
    assert first_author({"authors": []}) == "Anonymous"


def test_labels_read_author_year_with_a_and_b_for_twins():
    papers, *_ = _small()
    labels = author_year_labels(papers, list(papers))
    assert labels["A"] == "Hummon 1990"
    assert labels["C"] == "Liu 1992"
    assert labels["D"] == "Liu 1993"  # same surname, other year: no letter
    papers["E"]["authors"] = ["Liu, John S."]
    labels = author_year_labels(papers, list(papers))
    assert (labels["D"], labels["E"]) == ("Liu 1993a", "Liu 1993b")  # ordered by date, then id


@pytest.mark.parametrize("network", [_small, _demo_size], ids=["small", "demo-size"])
def test_the_map_renders_without_overlaps(tmp_path: Path, network):
    papers, main, tied, key, lanes = network()
    numbers = {p: i + 1 for i, p in enumerate(sorted(papers))}
    robust = {main[0][0], main[-1][1]}
    r = draw_map(
        papers, main, key, lanes, tmp_path / "m.png", tmp_path / "m.pdf", numbers=numbers,
        tied_arcs=tied, robust=robust, out_svg=tmp_path / "m.svg", title="A field",
    )  # fmt: skip
    for ext in ("png", "pdf", "svg"):
        assert (tmp_path / f"m.{ext}").stat().st_size > 0
    shown = {p for a in [*main, *tied, *key] for p in a}
    assert r["papers_drawn"] == len(shown) == len(r["label_boxes"])
    if any(p not in {q for lane in lanes for q in lane["papers"]} for p in shown):
        assert r["lanes"][-1] == UNASSIGNED
    _check_layout(r)


def test_without_lanes_every_paper_is_in_one_band(tmp_path: Path):
    papers, main, tied, key, _ = _demo_size()
    r = draw_map(papers, main, key, [], tmp_path / "m.png", tied_arcs=tied)
    assert r["lanes"] == [UNASSIGNED]
    _check_layout(r)


def test_the_files_are_the_same_on_every_run(tmp_path: Path):
    papers, main, tied, key, lanes = _demo_size()
    out = []
    for run in ("one", "two"):
        d = tmp_path / run
        draw_map(
            papers, main, key, lanes, d / "m.png", d / "m.pdf", numbers={p: 1 for p in papers},
            tied_arcs=tied, robust={main[0][0]}, out_svg=d / "m.svg",
        )  # fmt: skip
        out.append([(d / f"m.{e}").read_bytes() for e in ("png", "svg", "pdf")])
    assert out[0] == out[1]
