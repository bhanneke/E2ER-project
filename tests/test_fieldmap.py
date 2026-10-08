"""The field map's computation: network, SPC, main paths, key routes, robustness, exports, OpenAlex.

Every expected number below is computed by hand in the comments, from the
definitions in Batagelj (2003) and Liu and Lu (2012). No network: OpenAlex is
a fake ``fetch`` that serves pages from memory.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from src.modules.fieldmap import exports
from src.modules.fieldmap.mainpath import analyse, global_main_path, key_routes, local_main_path, spc_weights
from src.modules.fieldmap.network import build_network, completeness, topological_order
from src.modules.fieldmap.openalex import (
    BoundaryError,
    Budget,
    Client,
    HTTPError,
    count,
    normalise_boundary,
    openalex_filter,
    retrieve,
)
from src.modules.fieldmap.robustness import compare


def paper(pid: str, year: int, refs: list[str] = (), **kw: Any) -> dict[str, Any]:  # type: ignore[assignment]
    return {"id": pid, "year": year, "title": kw.pop("title", f"Paper {pid}"), "references": list(refs), **kw}


# ── a hand-computed network ─────────────────────────────────────────────────
#
#   A(1990)   B(1991)
#      \     /   \
#       C(1992)    \
#      /    \       \
#   D(1993)  E(1994)-'      (E cites C and B)
#      \    /
#      F(1995)
#
# Arcs cited -> citing: A>C, B>C, B>E, C>D, C>E, D>F, E>F.
# N-: A=1 B=1 C=2 D=2 E=3 F=5.  N+: F=1 D=1 E=1 C=2 A=2 B=3.
# SPC = N-(u) * N+(v): A>C 2, B>C 2, B>E 1, C>D 2, C>E 2, D>F 2, E>F 3; total flow N+(A)+N+(B) = 5.
# Source-to-sink paths and their totals: ACDF 6, ACEF 7, BCDF 6, BCEF 7, BEF 4 -> global optimum 7, two tied.

HAND = [
    paper("A", 1990),
    paper("B", 1991),
    paper("C", 1992, ["A", "B"]),
    paper("D", 1993, ["C"]),
    paper("E", 1994, ["C", "B"]),
    paper("F", 1995, ["D", "E"]),
]


def test_spc_on_the_hand_network():
    net = build_network(HAND)
    w = spc_weights(net)
    assert w.spc == {
        ("A", "C"): 2,
        ("B", "C"): 2,
        ("B", "E"): 1,
        ("C", "D"): 2,
        ("C", "E"): 2,
        ("D", "F"): 2,
        ("E", "F"): 3,
    }
    assert w.n_minus == {"A": 1, "B": 1, "C": 2, "D": 2, "E": 3, "F": 5}
    assert w.n_plus == {"A": 2, "B": 3, "C": 2, "D": 1, "E": 1, "F": 1}
    assert w.total_flow == 5
    assert w.origins == ["A", "B"] and w.ends == ["F"]
    assert w.share(("E", "F")) == pytest.approx(0.6)


def test_kirchhoff_node_law_holds():
    """Batagelj (2003, 4.3): at every inner node, inflow = outflow = N-(v) * N+(v)."""
    net = build_network(HAND)
    w = spc_weights(net)
    for v in ("C", "D", "E"):
        inflow = sum(s for (a, b), s in w.spc.items() if b == v)
        outflow = sum(s for (a, b), s in w.spc.items() if a == v)
        assert inflow == outflow == w.n_minus[v] * w.n_plus[v]
    # The arcs into the single end point carry the total flow.
    assert sum(s for (a, b), s in w.spc.items() if b == "F") == w.total_flow


def test_global_main_path_with_a_tie():
    g = global_main_path(build_network(HAND))
    assert g.total_spc == 7 and g.tied_paths == 2
    assert g.papers == ["A", "C", "E", "F"]  # the earliest tied origin, then the earliest tied successor
    assert g.network_arcs == [("A", "C"), ("B", "C"), ("C", "E"), ("E", "F")]
    assert g.network_papers() == ["A", "B", "C", "E", "F"]


def test_local_main_path_follows_every_tie():
    loc = local_main_path(build_network(HAND))
    # Origin arcs: A>C 2, B>C 2, B>E 1 -> A>C and B>C; from C: C>D 2 = C>E 2, both; then D>F, E>F.
    assert loc.network_arcs == [("A", "C"), ("B", "C"), ("C", "D"), ("C", "E"), ("D", "F"), ("E", "F")]
    assert loc.papers == ["A", "C", "D", "F"] and loc.total_spc == 6
    assert loc.tied_paths == 4  # {A,B} x {D,E}


def test_key_routes_from_the_heaviest_arc():
    kr = key_routes(build_network(HAND), k=1)
    # Top arc E>F (3); backward from E along the heaviest: fwd(E) = max(fwd(C)+2, fwd(B)+1) = 4 via C,
    # fwd(C) = 2 via A or B (tie) -> A>C, B>C, C>E, E>F.
    assert kr["key_arcs"] == [("E", "F")] and kr["cutoff_spc"] == 3
    assert kr["arcs"] == [("A", "C"), ("B", "C"), ("C", "E"), ("E", "F")]


def test_key_routes_include_every_arc_tied_with_the_kth():
    kr = key_routes(build_network(HAND), k=2)
    # Ranked: E>F 3, then five arcs of 2: all tied with the 2nd are key arcs.
    assert kr["cutoff_spc"] == 2 and len(kr["key_arcs"]) == 6
    assert ("B", "E") not in kr["key_arcs"]


def test_complete_acyclic_network_has_the_closed_form():
    """K_n, every earlier paper cited by every later one. Paths s..i: 2^(i-2) (i>=2), 1 for i=1;
    paths j..t: 2^(n-j-1) (j<n), 1 for j=n; so SPC(i,j) = 2^max(i-2,0) * 2^max(n-j-1,0) and the
    total flow (paths from paper 1 to paper n) is 2^(n-2)."""
    n = 7
    papers = [paper(f"P{i}", 2000 + i, [f"P{j}" for j in range(1, i)]) for i in range(1, n + 1)]
    w = spc_weights(build_network(papers))
    assert w.total_flow == 2 ** (n - 2)
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            assert w.spc[(f"P{i}", f"P{j}")] == 2 ** max(i - 2, 0) * 2 ** max(n - j - 1, 0)
    g = global_main_path(build_network(papers))
    # Every arc on a path adds weight, so the heaviest chain visits every paper.
    assert g.papers == [f"P{i}" for i in range(1, n + 1)] and g.tied_paths == 1


def test_global_and_local_disagree_where_greedy_fails():
    """O>P carries 3 (P has three continuations) but the chain Q..W is heavier in total.

    O>P 3, P>a1/a2/a3 1 each: best total from O = 4. Q>R>S>T>U>V>W: six arcs of 1 = 6.
    Local starts at the heaviest origin arc (O>P) and ends at P's continuations; global takes the chain.
    """
    papers = [paper("O", 2000), paper("P", 2001, ["O"])]
    papers += [paper(f"a{i}", 2002, ["P"]) for i in (1, 2, 3)]
    chain = ["Q", "R", "S", "T", "U", "V", "W"]
    papers += [paper(c, 2000 + i, [chain[i - 1]] if i else []) for i, c in enumerate(chain)]
    net = build_network(papers)
    g = global_main_path(net)
    loc = local_main_path(net)
    assert g.papers == chain and g.total_spc == 6
    assert loc.papers[:2] == ["O", "P"] and loc.total_spc == 4 and loc.tied_paths == 3


def test_adding_a_component_keeps_the_weights_of_the_other():
    """Batagelj (2003, 4.1): another component changes no weight inside the first (only the total)."""
    other = [paper("X", 1990), paper("Y", 1991, ["X"]), paper("Z", 1992, ["X", "Y"])]
    alone = spc_weights(build_network(HAND))
    both = spc_weights(build_network(HAND + other))
    for arc, s in alone.spc.items():
        assert both.spc[arc] == s
    assert both.total_flow == alone.total_flow + 2  # X>Y>Z and X>Z
    assert both.origins == ["A", "X", "B"]  # ordered by year (A and X: 1990), then id


def test_a_citation_cycle_is_broken_deterministically_and_reported():
    """G and H (same year) cite each other; I cites both. Inside the cycle only the arc from the
    earlier (by date, then id) to the later paper is kept."""
    papers = [
        paper("G", 2010, ["H"], date="2010-03-01"),
        paper("H", 2010, ["G"], date="2010-01-15"),
        paper("I", 2012, ["G", "H"]),
        paper("J", 2009),
        paper("K", 2011, ["J", "K"]),  # cites itself
    ]
    net = build_network(papers)
    assert ("H", "G") in net.arcs and ("G", "H") not in net.arcs  # H is earlier (January)
    assert net.cycles == [["H", "G"]]
    reasons = {(d["cited"], d["citing"]): d["reason"] for d in net.dropped}
    assert reasons[("G", "H")].startswith("breaks a citation cycle")
    assert reasons[("K", "K")] == "self-citation"
    topological_order(net)  # acyclic now
    assert build_network(list(reversed(papers))).arcs == net.arcs  # input order does not matter


def test_completeness_report_counts_what_is_missing():
    papers = HAND + [
        paper("L", 1996, [], reference_count=0),  # no references at all, no links
        paper("M", 1997, ["Q1"], reference_count=40),  # references outside the set only
        paper("N", 1998, ["A"], reference_count=2, title="Erratum to: Paper A"),  # short list, a notice
        paper("N2", 1998, ["A"], reference_count=30, title="paper  a"),  # same normalised title as A
    ]
    for p in papers:
        p.setdefault("reference_count", 30)
    rep = completeness(build_network(papers), retrieved=10, reported=11)
    assert rep["papers"] == 10 and rep["papers_reported_by_openalex"] == 11
    assert rep["internal_links"] == 9
    assert rep["papers_without_internal_links"] == 2  # L and M
    assert rep["papers_without_references"] == 1
    assert rep["papers_with_short_reference_lists"] == 1  # N: 2 < 30 / 4
    assert rep["notices"] == 1 and rep["probable_duplicates"] == 1
    assert [p["id"] for p in rep["lists"]["without_internal_links"]] == ["L", "M"]


def test_excluded_papers_leave_the_network():
    net = build_network(HAND, exclude=["https://openalex.org/E"])
    assert "E" not in net.papers and ("B", "E") not in net.arcs


def test_analyse_returns_plain_data():
    res = analyse(build_network(HAND), k=1)
    json.dumps(res)
    assert res["global_main_path"]["length"] == 4 and res["total_flow"] == 5
    assert res["ranked_arcs"][0] == {"cited": "E", "citing": "F", "spc": 3, "share": 0.6}


def test_robustness_counts_papers_on_every_main_path():
    a = analyse(build_network(HAND))
    b = analyse(build_network([p for p in HAND if p["id"] != "A"]))  # the alternative drops A
    rep = compare(
        {
            "main": {"ids": [p["id"] for p in HAND], "analysis": a},
            "alt": {"ids": ["B", "C", "D", "E", "F"], "analysis": b},
        },
        {p["id"]: p for p in HAND},
    )
    # Without A: SPC B>C 2, B>E 1, C>D 1, C>E 1, D>F 1, E>F 2; paths BCDF 4, BCEF 5, BEF 3 -> B C E F.
    assert b["global_main_path"]["papers"] == ["B", "C", "E", "F"]
    assert rep["boundary_count"] == 2 and sorted(rep["robust_ids"]) == ["C", "E", "F"]
    row = {r["id"]: r for r in rep["papers"]}
    assert row["A"]["main_paths"] == 1 and not row["A"]["robust"] and row["C"]["robust"]


# ── exports ─────────────────────────────────────────────────────────────────


def _arcs():
    w = spc_weights(build_network(HAND))
    return [
        {"cited": u, "citing": v, "spc": s, "share": round(w.share((u, v)), 6)} for (u, v), s in sorted(w.spc.items())
    ]


def _papers():
    return {p["id"]: {**p, "authors": ["Ann Author"], "doi": f"10.1/{p['id']}", "journal": "J & Co"} for p in HAND}


def test_pajek_parses_back():
    text = exports.pajek(_papers(), _arcs())
    lines = text.splitlines()
    assert lines[0] == "*Vertices 6"
    ids = {int(ln.split()[0]): ln.split('"')[1].split()[-1] for ln in lines[1:7]}
    arcs_at = lines.index("*Arcs")
    parsed = {(ids[int(a)], ids[int(b)]): int(s) for a, b, s in (ln.split() for ln in lines[arcs_at + 1 :])}
    assert parsed == {(a["cited"], a["citing"]): a["spc"] for a in _arcs()}


def test_gexf_parses_back_with_weights_and_flags():
    text = exports.gexf(_papers(), _arcs(), {("A", "C")}, {("E", "F")}, {"A": "Why?"})
    root = ET.fromstring(text)
    ns = {"g": "http://gexf.net/1.3"}
    nodes = root.findall(".//g:node", ns)
    edges = root.findall(".//g:edge", ns)
    assert len(nodes) == 6 and len(edges) == 7
    ef = next(e for e in edges if e.get("source") == "E" and e.get("target") == "F")
    assert float(ef.get("weight")) == 3.0
    vals = {v.get("for"): v.get("value") for v in ef.iter("{http://gexf.net/1.3}attvalue")}
    assert vals["e0"] == "3" and vals["e3"] == "true" and vals["e2"] == "false"


def test_vosviewer_csv_and_reading_list_parse_back():
    vmap, vnet = exports.vosviewer(_papers(), _arcs())
    rows = list(csv.reader(io.StringIO(vmap), delimiter="\t"))
    assert rows[0][:2] == ["id", "label"] and len(rows) == 7
    assert len(vnet.strip().splitlines()) == 7
    edges = list(csv.DictReader(io.StringIO(exports.edge_csv(_arcs(), {("A", "C")}, set()))))
    assert {(e["cited"], e["citing"]): int(e["spc"]) for e in edges}[("E", "F")] == 3
    rl = exports.reading_list(_papers(), ["A", "C"], ["C", "E"], {"C": 2}, {"A": "Why?"})
    assert [r["openalex_id"] for r in rl] == ["A", "C", "E"] and rl[1]["main_paths_across_boundaries"] == 2
    back = list(csv.DictReader(io.StringIO(exports.reading_list_csv(rl))))
    assert back[0]["doi"] == "10.1/A" and back[0]["on_main_path"] == "1" and back[0]["lane"] == "Why?"


# ── OpenAlex (fake) ─────────────────────────────────────────────────────────


def _work(i: int, refs: list[int], year: int) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/W{i}",
        "doi": f"https://doi.org/10.9/{i}",
        "title": f"Work {i}",
        "publication_year": year,
        "publication_date": f"{year}-01-01",
        "type": "article",
        "primary_location": {"source": {"id": "https://openalex.org/S1", "display_name": "Journal One"}},
        "authorships": [{"author": {"display_name": f"Author {i}"}}],
        "referenced_works": [f"https://openalex.org/W{r}" for r in refs],
        "referenced_works_count": len(refs) + 5,
        "cited_by_count": 3,
        "abstract_inverted_index": {"main": [0], "path": [1]},
        "keywords": [{"display_name": "citation"}],
    }


class FakeOpenAlex:
    """Serves works by filter, cursor-paged; records every request."""

    def __init__(self, sets: dict[str, list[dict[str, Any]]], page: int = 3) -> None:
        self.sets = sets
        self.page = page
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> str:
        self.calls.append((url, headers))
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        works = next((v for k, v in self.sets.items() if k in q.get("filter", "")), [])
        if q.get("per-page") == "1":
            return json.dumps({"meta": {"count": len(works)}, "results": works[:1]})
        start = 0 if q.get("cursor") == "*" else int(q["cursor"])
        chunk = works[start : start + self.page]
        nxt = str(start + self.page) if start + self.page < len(works) else None
        return json.dumps({"meta": {"count": len(works), "next_cursor": nxt}, "results": chunk})


def _client(fake: FakeOpenAlex, tmp: Path | None = None, **kw: Any) -> Client:
    return Client(cache_dir=tmp, fetch=fake, pause_s=0, mailto="research@example.org", **kw)


WORKS = [
    _work(1, [], 2001),
    _work(2, [1], 2002),
    _work(3, [1, 2, 99], 2003),
    _work(4, [3], 2004),
    _work(5, [2, 3], 2005),
    _work(6, [4, 5], 2006),
    _work(7, [], 2007),
]


def test_retrieval_pages_with_the_cursor_and_parses_works(tmp_path: Path):
    fake = FakeOpenAlex({"main path": WORKS})
    b = normalise_boundary({"name": "main", "query": '"main path"', "from_year": 2000, "to_year": 2010})
    data = retrieve(_client(fake, tmp_path), b)
    assert data["papers_retrieved"] == 7 and data["count_reported"] == 7
    assert len(fake.calls) == 1 + 3  # count, then pages of 3, 3, 1
    w3 = next(p for p in data["papers"] if p["id"] == "W3")
    assert w3["references"] == ["W1", "W2", "W99"] and w3["doi"] == "10.9/3" and w3["journal"] == "Journal One"
    assert w3["abstract"] == "main path" and w3["authors"] == ["Author 3"]
    url = fake.calls[1][0]
    plain = urllib.parse.unquote_plus(url)
    assert "mailto=research@example.org" in plain and "cursor=*" in plain
    assert 'title_and_abstract.search:"main path"' in plain and "publication_year:2000-2010" in plain


def test_a_second_retrieval_is_served_from_the_cache(tmp_path: Path):
    fake = FakeOpenAlex({"main path": WORKS})
    b = normalise_boundary({"name": "main", "query": "main path"})
    retrieve(_client(fake, tmp_path), b)
    sent = len(fake.calls)
    c = _client(fake, tmp_path)
    retrieve(c, b)
    assert len(fake.calls) == sent and c.budget.sent == 0 and c.budget.cached == 4


def test_a_boundary_above_the_limit_costs_one_request(tmp_path: Path):
    fake = FakeOpenAlex({"main path": WORKS})
    with pytest.raises(BoundaryError, match="selects 7 papers, above the limit of 5"):
        retrieve(_client(fake), normalise_boundary({"name": "main", "query": "main path"}), max_papers=5)
    assert len(fake.calls) == 1


def test_the_request_ceiling_stops_retrieval():
    fake = FakeOpenAlex({"main path": WORKS})
    with pytest.raises(BoundaryError, match="ceiling of 2"):
        retrieve(_client(fake, budget=Budget(limit=2)), normalise_boundary({"name": "main", "query": "main path"}))
    assert len(fake.calls) == 2


def test_the_key_goes_in_a_header_never_in_the_address():
    fake = FakeOpenAlex({"main path": WORKS})
    count(_client(fake, api_key="secret-key"), normalise_boundary({"name": "m", "query": "main path"}))
    url, headers = fake.calls[0]
    assert headers == {"Authorization": "Bearer secret-key"} and "secret" not in url


def test_a_spent_budget_is_reported_and_not_retried():
    calls = []

    def spent(url: str, headers: dict[str, str]) -> str:
        calls.append(url)
        raise HTTPError(429, '{"error": "Insufficient budget. This request has no API key"}')

    with pytest.raises(BoundaryError, match="daily budget"):
        count(_client(spent), normalise_boundary({"name": "m", "query": "x"}))  # type: ignore[arg-type]
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"name": "m"}, "needs a query"),
        ({"name": "m", "query": "a, b"}, "commas"),
        ({"name": "m", "query": "a", "sources": ["Journal of X"]}, "not an OpenAlex source id"),
        ({"name": "m", "query": "a", "from_year": 2020, "to_year": 2010}, "after"),
        ({"name": "m", "query": "a", "search_in": "body"}, "search_in"),
        ({"name": "bad name", "query": "a"}, "letters"),
    ],
)
def test_bad_boundaries_are_refused(raw, match):
    with pytest.raises(BoundaryError, match=match):
        normalise_boundary(raw)


def test_the_filter_combines_query_journals_years_and_types():
    b = normalise_boundary(
        {
            "name": "j",
            "query": "x OR y",
            "sources": ["https://openalex.org/s2", "S1"],
            "from_year": 1990,
            "search_in": "title",
            "types": ["article"],
        }
    )
    assert openalex_filter(b) == (
        "title.search:x OR y,primary_location.source.id:S1|S2,publication_year:>1989,type:article,is_paratext:false"
    )
