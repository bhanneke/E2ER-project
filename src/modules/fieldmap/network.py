"""The internal citation network of a boundary, and what is missing from it.

Arcs point the way knowledge flows: from the cited paper to the citing paper
(``u -> v`` means v cites u), as in Hummon and Doreian (1989) and Batagelj
(2003). Only citations between two papers of the boundary are kept.

Citation networks are almost acyclic, but not quite: two papers of the same
year can cite each other (working-paper versions), and database errors create
loops. SPC needs an acyclic network. The rule here is deterministic and keeps
every paper:

1. a self-citation (a paper listing itself) is dropped;
2. inside each strongly connected component with more than one paper, the
   papers are ordered by (publication year, publication date, OpenAlex id), and
   an arc is kept only when it runs from an earlier to a later paper in that
   order. Arcs between components are never touched.

Every dropped arc is reported with its reason. Batagelj (2003, section 5)
discusses the alternatives (shrinking a component to one vertex, the preprint
transformation); dropping the backward arcs keeps every paper on the map and
changes only arcs that are inside a cycle.
"""

from __future__ import annotations

import heapq
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

#: Words in a title that mark a notice rather than a paper (erratum, reprint, ...).
_NOTICE_RE = re.compile(
    r"\b(erratum|errata|corrigendum|corrigenda|correction to|retraction|retracted|reprint|editorial note|"
    r"expression of concern|addendum)\b",
    re.I,
)


def short_id(openalex_id: str) -> str:
    """``https://openalex.org/W123`` -> ``W123`` (an id already short is returned as is)."""
    return str(openalex_id or "").rstrip("/").rsplit("/", 1)[-1]


def norm_title(title: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (title or "").lower()).split())


def order_key(paper: dict[str, Any]) -> tuple[int, str, str]:
    """The order papers are listed and ties are broken in: year, date, id."""
    year = paper.get("year")
    return (int(year) if isinstance(year, int) else 9999, str(paper.get("date") or ""), str(paper["id"]))


@dataclass
class Network:
    """A directed acyclic citation network over the papers of one boundary."""

    papers: dict[str, dict[str, Any]]
    #: arcs cited -> citing, sorted
    arcs: list[tuple[str, str]]
    #: arcs removed to break cycles, with the reason
    dropped: list[dict[str, Any]] = field(default_factory=list)
    #: the strongly connected components (more than one paper) found before breaking them
    cycles: list[list[str]] = field(default_factory=list)

    def successors(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {p: [] for p in self.papers}
        for u, v in self.arcs:
            out[u].append(v)
        return out

    def predecessors(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {p: [] for p in self.papers}
        for u, v in self.arcs:
            out[v].append(u)
        return out

    def connected_ids(self) -> set[str]:
        """Papers with at least one internal link (cited by or citing another paper of the set)."""
        ids: set[str] = set()
        for u, v in self.arcs:
            ids.add(u)
            ids.add(v)
        return ids


def strongly_connected_components(nodes: list[str], succ: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's algorithm, iterative (no recursion limit), deterministic for sorted input."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            nexts = succ.get(v, [])
            if i < len(nexts):
                work.append((v, i + 1))
                w = nexts[i]
                if w not in index:
                    work.append((w, 0))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
                continue
            if low[v] == index[v]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return out


def build_network(papers: list[dict[str, Any]], exclude: list[str] | tuple[str, ...] = ()) -> Network:
    """The internal citation network of ``papers`` (each with ``id`` and ``references``)."""
    skip = {short_id(x) for x in exclude}
    by_id: dict[str, dict[str, Any]] = {}
    for p in papers:
        pid = short_id(p["id"])
        if pid in skip or pid in by_id:
            continue
        by_id[pid] = {**p, "id": pid}
    raw: set[tuple[str, str]] = set()
    dropped: list[dict[str, Any]] = []
    for pid in sorted(by_id):
        for ref in by_id[pid].get("references") or []:
            rid = short_id(ref)
            if rid not in by_id:
                continue
            if rid == pid:
                dropped.append({"cited": rid, "citing": pid, "reason": "self-citation"})
                continue
            raw.add((rid, pid))
    nodes = sorted(by_id, key=lambda i: order_key(by_id[i]))
    succ: dict[str, list[str]] = defaultdict(list)
    for u, v in sorted(raw):
        succ[u].append(v)
    comps = [c for c in strongly_connected_components(nodes, succ) if len(c) > 1]
    comp_of = {pid: n for n, comp in enumerate(comps) for pid in comp}
    rank = {pid: order_key(by_id[pid]) for pid in by_id}
    kept: list[tuple[str, str]] = []
    for u, v in sorted(raw):
        cu, cv = comp_of.get(u), comp_of.get(v)
        if cu is not None and cu == cv and not rank[u] < rank[v]:
            dropped.append({"cited": u, "citing": v, "reason": "breaks a citation cycle (cited paper is not earlier)"})
            continue
        kept.append((u, v))
    cycles = sorted((sorted(c, key=lambda i: rank[i]) for c in comps), key=lambda c: rank[c[0]])
    return Network(papers=by_id, arcs=sorted(kept), dropped=dropped, cycles=cycles)


def topological_order(net: Network) -> list[str]:
    """Kahn's algorithm with ties broken by year, date and id; raises if a cycle is left."""
    indeg = {p: 0 for p in net.papers}
    succ = net.successors()
    for _, v in net.arcs:
        indeg[v] += 1
    heap = [(order_key(net.papers[p]), p) for p, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    out: list[str] = []
    while heap:
        _, u = heapq.heappop(heap)
        out.append(u)
        for v in succ[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                heapq.heappush(heap, (order_key(net.papers[v]), v))
    if len(out) != len(net.papers):
        raise ValueError("the network still has a cycle")
    return out


def completeness(
    net: Network, *, retrieved: int | None = None, reported: int | None = None, short_share: float = 0.25
) -> dict[str, Any]:
    """What the network is missing: papers without internal links, short or empty reference lists,
    probable duplicates and notices, and the cycles that were broken.

    A paper whose reference list is shorter than ``short_share`` times the median of the set is
    reported as unusually short: its missing references are links the network does not have, and
    a paper can fall off the main path for that reason alone.
    """
    papers = net.papers
    n = len(papers)
    linked = net.connected_ids()
    isolated = sorted((p for p in papers if p not in linked), key=lambda i: order_key(papers[i]))
    ref_counts = {p: int(papers[p].get("reference_count") or len(papers[p].get("references") or [])) for p in papers}
    no_refs = sorted((p for p, c in ref_counts.items() if c == 0), key=lambda i: order_key(papers[i]))
    with_refs = [c for c in ref_counts.values() if c > 0]
    median_refs = statistics.median(with_refs) if with_refs else 0
    threshold = median_refs * short_share
    short = sorted(
        (p for p, c in ref_counts.items() if 0 < c < threshold),
        key=lambda i: order_key(papers[i]),
    )
    groups: dict[str, list[str]] = defaultdict(list)
    for p in papers:
        key = norm_title(papers[p].get("title") or "")
        if key:
            groups[key].append(p)
    duplicates = [sorted(ids, key=lambda i: order_key(papers[i])) for _, ids in sorted(groups.items()) if len(ids) > 1]
    notices = sorted(
        (p for p in papers if _NOTICE_RE.search(papers[p].get("title") or "")), key=lambda i: order_key(papers[i])
    )
    in_deg: Counter[str] = Counter(v for _, v in net.arcs)
    out_deg: Counter[str] = Counter(u for u, _ in net.arcs)
    years: Counter[int] = Counter(int(papers[p]["year"]) for p in papers if isinstance(papers[p].get("year"), int))
    journals = Counter(papers[p].get("journal") or "(no source)" for p in papers)

    def listed(ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": i,
                "year": papers[i].get("year"),
                "title": papers[i].get("title"),
                "references": ref_counts[i],
                "internal_cited_by": in_deg.get(i, 0),
                "internal_cites": out_deg.get(i, 0),
            }
            for i in ids
        ]

    return {
        "papers": n,
        "papers_retrieved": retrieved if retrieved is not None else n,
        "papers_reported_by_openalex": reported,
        "internal_links": len(net.arcs),
        "papers_with_internal_links": len(linked),
        "papers_without_internal_links": len(isolated),
        "share_without_internal_links": round(len(isolated) / n, 4) if n else 0.0,
        "papers_without_references": len(no_refs),
        "share_without_references": round(len(no_refs) / n, 4) if n else 0.0,
        "median_reference_count": median_refs,
        "short_reference_threshold": threshold,
        "papers_with_short_reference_lists": len(short),
        "probable_duplicates": len(duplicates),
        "notices": len(notices),
        "cycles": len(net.cycles),
        "arcs_dropped": len(net.dropped),
        "year_first": min(years) if years else None,
        "year_last": max(years) if years else None,
        "papers_by_year": {str(y): years[y] for y in sorted(years)},
        "top_sources": [{"source": j, "papers": c} for j, c in journals.most_common(15)],
        "lists": {
            "without_internal_links": listed(isolated),
            "without_references": listed(no_refs),
            "short_reference_lists": listed(short),
            "probable_duplicates": [listed(g) for g in duplicates],
            "notices": listed(notices),
            "cycles": net.cycles,
            "dropped_arcs": net.dropped,
        },
    }
