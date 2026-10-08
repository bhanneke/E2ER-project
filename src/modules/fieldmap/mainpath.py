"""Search path count weights, main paths and key routes.

SPC (Batagelj 2003, section 3.2). The network is put in standard form: a
source ``s`` linked to every paper with no incoming arc (an origin: it cites
no paper of the set), and every paper with no outgoing arc (an end point: no
paper of the set cites it) linked to a sink ``t``. ``N-(v)`` counts the paths
from ``s`` to ``v``, ``N+(v)`` the paths from ``v`` to ``t``, and the weight of
an arc is the number of source-to-sink paths through it:

    SPC(u, v) = N-(u) * N+(v)

computed in one pass in topological order and one in reverse. The counts are
Python integers, so they are exact however large they get. The total flow
``N(t, s)`` (the number of source-to-sink paths) normalises the weights to
shares between 0 and 1. Papers without any internal link are left out of the
weighted network: they would add paths of their own and touch no arc.

Main paths:

- global (Liu and Lu 2012): the source-to-sink path whose arcs have the
  largest total SPC, by dynamic programming over the topological order. When
  several paths tie, every arc on any of them is reported (``network``) and
  one canonical path is chosen by following, from the earliest tied origin,
  the earliest tied successor (year, date, id).
- local, forward (Hummon and Doreian 1989; Batagelj 2003, section 6): start
  at the arcs with the largest SPC among the arcs that leave an origin, and
  from each end point follow the outgoing arcs with the largest SPC until an
  end point is reached; ties are all followed.

Key routes (Liu and Lu 2012): the ``k`` arcs with the largest SPC (all arcs
tied with the k-th are included), each extended backward to an origin and
forward to an end point along the path of largest total SPC (the global
search), with ties kept. The union is the key-route network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from .network import Network, order_key, topological_order


@dataclass
class Weights:
    order: list[str]
    #: arc -> SPC (exact)
    spc: dict[tuple[str, str], int]
    n_minus: dict[str, int]
    n_plus: dict[str, int]
    total_flow: int
    origins: list[str]
    ends: list[str]
    #: papers in the weighted network (at least one internal link)
    nodes: list[str] = field(default_factory=list)

    def share(self, arc: tuple[str, str]) -> float:
        return float(Fraction(self.spc[arc], self.total_flow)) if self.total_flow else 0.0


def spc_weights(net: Network) -> Weights:
    """SPC weight of every arc, with the path counts behind it."""
    linked = net.connected_ids()
    order = [p for p in topological_order(net) if p in linked]
    succ = net.successors()
    pred = net.predecessors()
    origins = [p for p in order if not pred[p]]
    ends = [p for p in order if not succ[p]]
    n_minus: dict[str, int] = {}
    for v in order:
        n_minus[v] = 1 if not pred[v] else sum(n_minus[u] for u in pred[v])
    n_plus: dict[str, int] = {}
    for v in reversed(order):
        n_plus[v] = 1 if not succ[v] else sum(n_plus[w] for w in succ[v])
    spc = {(u, v): n_minus[u] * n_plus[v] for u, v in net.arcs}
    total = sum(n_plus[o] for o in origins)
    return Weights(
        order=order, spc=spc, n_minus=n_minus, n_plus=n_plus, total_flow=total, origins=origins, ends=ends, nodes=order
    )


def _key(net: Network, pid: str) -> tuple[int, str, str]:
    return order_key(net.papers[pid])


@dataclass
class Path:
    """A main path: one canonical chain of papers, and every arc of the tied optimal paths."""

    papers: list[str]
    arcs: list[tuple[str, str]]
    total_spc: int
    #: every arc on any optimal path (equals ``arcs`` when the optimum is unique)
    network_arcs: list[tuple[str, str]]
    #: how many distinct optimal paths there are
    tied_paths: int

    def network_papers(self) -> list[str]:
        out: set[str] = set()
        for u, v in self.network_arcs:
            out.update((u, v))
        return sorted(out)


def _longest(w: Weights, net: Network) -> tuple[dict[str, int], dict[str, int]]:
    """fwd[v]: largest total SPC of a path from an origin to v; bwd[v]: from v to an end point."""
    succ = net.successors()
    pred = net.predecessors()
    fwd: dict[str, int] = {}
    for v in w.order:
        fwd[v] = max((fwd[u] + w.spc[(u, v)] for u in pred[v]), default=0)
    bwd: dict[str, int] = {}
    for v in reversed(w.order):
        bwd[v] = max((w.spc[(v, x)] + bwd[x] for x in succ[v]), default=0)
    return fwd, bwd


def global_main_path(net: Network, w: Weights | None = None) -> Path:
    """The source-to-sink path with the largest total SPC (Liu and Lu 2012), ties reported."""
    w = w or spc_weights(net)
    if not net.arcs:
        return Path(papers=[], arcs=[], total_spc=0, network_arcs=[], tied_paths=0)
    fwd, bwd = _longest(w, net)
    best = max(bwd[o] for o in w.origins)
    tight: list[tuple[str, str]] = []
    on = {v for v in w.order if fwd[v] + bwd[v] == best}
    for (u, v), s in w.spc.items():
        if u in on and v in on and fwd[u] + s + bwd[v] == best and fwd[u] + s == fwd[v]:
            tight.append((u, v))
    tight.sort()
    # Tied origins: on an optimal path and without a predecessor.
    succ_t: dict[str, list[str]] = {}
    for u, v in tight:
        succ_t.setdefault(u, []).append(v)
    starts = sorted((o for o in w.origins if o in on and bwd[o] == best), key=lambda p: _key(net, p))
    # Number of optimal paths: count along the tight arcs.
    count: dict[str, int] = {}
    for v in reversed(w.order):
        if v not in on:
            continue
        nxt = succ_t.get(v, [])
        count[v] = 1 if not nxt else sum(count[x] for x in nxt)
    tied = sum(count[s] for s in starts)
    path = [starts[0]]
    while succ_t.get(path[-1]):
        path.append(min(succ_t[path[-1]], key=lambda p: _key(net, p)))
    arcs = list(zip(path, path[1:], strict=False))
    return Path(papers=path, arcs=arcs, total_spc=best, network_arcs=tight, tied_paths=tied)


def local_main_path(net: Network, w: Weights | None = None) -> Path:
    """Forward local main path (Hummon and Doreian 1989): the heaviest next arc at every step, ties all followed."""
    w = w or spc_weights(net)
    if not net.arcs:
        return Path(papers=[], arcs=[], total_spc=0, network_arcs=[], tied_paths=0)
    succ = net.successors()
    first = [(o, v) for o in w.origins for v in succ[o]]
    top = max(w.spc[a] for a in first)
    frontier = sorted({a for a in first if w.spc[a] == top})
    arcs: set[tuple[str, str]] = set(frontier)
    heads = sorted({v for _, v in frontier})
    seen: set[str] = set()
    while heads:
        nxt: set[str] = set()
        for h in heads:
            if h in seen or not succ[h]:
                continue
            seen.add(h)
            best = max(w.spc[(h, x)] for x in succ[h])
            for x in succ[h]:
                if w.spc[(h, x)] == best:
                    arcs.add((h, x))
                    nxt.add(x)
        heads = sorted(nxt)
    network_arcs = sorted(arcs)
    # Canonical chain: from the earliest start, the earliest tied successor.
    out_t: dict[str, list[str]] = {}
    for u, v in network_arcs:
        out_t.setdefault(u, []).append(v)
    path = [min((u for u, _ in frontier), key=lambda p: _key(net, p))]
    while out_t.get(path[-1]):
        path.append(min(out_t[path[-1]], key=lambda p: _key(net, p)))
    chain = list(zip(path, path[1:], strict=False))
    # Number of chains through the local main path network, from its starts.
    starts = sorted({u for u, _ in frontier})
    order_pos = {p: i for i, p in enumerate(w.order)}
    count: dict[str, int] = {}
    for v in sorted({x for a in network_arcs for x in a}, key=lambda p: -order_pos[p]):
        nxt2 = out_t.get(v, [])
        count[v] = 1 if not nxt2 else sum(count[x] for x in nxt2)
    return Path(
        papers=path,
        arcs=chain,
        total_spc=sum(w.spc[a] for a in chain),
        network_arcs=network_arcs,
        tied_paths=sum(count[s] for s in starts),
    )


def ranked_arcs(w: Weights) -> list[tuple[tuple[str, str], int]]:
    """Every arc by SPC, heaviest first; ties by the two papers' ids."""
    return sorted(w.spc.items(), key=lambda kv: (-kv[1], kv[0]))


def key_routes(net: Network, k: int = 10, w: Weights | None = None) -> dict[str, Any]:
    """Key-route main paths (Liu and Lu 2012), global search, from the top-k arcs (ties at the k-th included)."""
    w = w or spc_weights(net)
    if not net.arcs or k <= 0:
        return {"k": k, "key_arcs": [], "arcs": [], "papers": []}
    ranked = ranked_arcs(w)
    cutoff = ranked[min(k, len(ranked)) - 1][1]
    key_arcs = [a for a, s in ranked if s >= cutoff]
    fwd, bwd = _longest(w, net)
    pred = net.predecessors()
    succ = net.successors()
    arcs: set[tuple[str, str]] = set()
    for u, v in key_arcs:
        arcs.add((u, v))
        # Backward from u to an origin along every heaviest path.
        stack = [u]
        seen: set[str] = set()
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            for p in pred[x]:
                if fwd[p] + w.spc[(p, x)] == fwd[x]:
                    arcs.add((p, x))
                    stack.append(p)
        stack = [v]
        seen = set()
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            for q in succ[x]:
                if w.spc[(x, q)] + bwd[q] == bwd[x]:
                    arcs.add((x, q))
                    stack.append(q)
    papers = sorted({p for a in arcs for p in a}, key=lambda p: _key(net, p))
    return {"k": k, "cutoff_spc": cutoff, "key_arcs": key_arcs, "arcs": sorted(arcs), "papers": papers}


def analyse(net: Network, *, k: int = 10) -> dict[str, Any]:
    """SPC, both main paths and the key routes of one network, as plain data."""
    w = spc_weights(net)
    g = global_main_path(net, w)
    loc = local_main_path(net, w)
    kr = key_routes(net, k, w)

    def arc_rows(arcs: list[tuple[str, str]]) -> list[dict[str, Any]]:
        return [{"cited": u, "citing": v, "spc": w.spc[(u, v)], "share": round(w.share((u, v)), 6)} for u, v in arcs]

    def path_dict(p: Path) -> dict[str, Any]:
        return {
            "papers": p.papers,
            "length": len(p.papers),
            "arcs": arc_rows(p.arcs),
            "total_spc": p.total_spc,
            "tied_paths": p.tied_paths,
            "network_papers": p.network_papers(),
            "network_arcs": arc_rows(p.network_arcs),
        }

    return {
        "weights": "SPC",
        "papers_weighted": len(w.nodes),
        "arcs": len(w.spc),
        "origins": len(w.origins),
        "end_points": len(w.ends),
        "total_flow": w.total_flow,
        "global_main_path": path_dict(g),
        "local_main_path": path_dict(loc),
        "key_routes": {**kr, "key_arcs": arc_rows(kr["key_arcs"]), "arcs": arc_rows(kr["arcs"])},
        "ranked_arcs": arc_rows([a for a, _ in ranked_arcs(w)]),
    }
