"""The field-map steps on a study's workspace.

The template (``pipelines/field-map.toml``) runs these as checks of their own,
and ``e2er-fieldmap`` runs the same functions from a specialist's shell, so
there is one implementation. Each returns a verdict in the shape the runner
records for every check (passed, reasons, notes, stats).

Files, all in the workspace:

- ``field_boundary.json`` (the boundary designer): ``main`` and
  ``alternatives``, each a boundary (query, search_in, sources, from_year,
  to_year, types, exclude, note);
- ``fieldmap/boundaries/<name>.json``: what OpenAlex returned for a boundary;
  ``fieldmap/cache/``: the pages, by address;
- ``field_boundary_counts.json`` / ``.md``: papers per boundary, for the
  researcher's stop;
- ``completeness_report.json`` / ``.md``: the main boundary's network and what
  it is missing;
- ``main_path.json`` / ``.md``: SPC, the global and local main paths, the key
  routes and the heaviest links of the main boundary;
- ``robustness.json`` / ``.md``: the main path of every boundary, paper by paper;
- ``field_lanes.json`` (the lane mapper): lanes as questions with their papers;
- ``figures/field_map.png`` / ``.svg`` / ``.pdf``, ``reading_list.csv`` / ``.json``,
  ``exports/`` (Pajek, GEXF, VOSviewer, CSV), ``tables/field_map_summary.tex``,
  ``tables/main_path_list.tex``;
- ``field_map_results.json``: every number the field review may state, read by
  e2er's number check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import exports
from .credit import METHOD_REFERENCES, method_bibtex
from .mainpath import analyse
from .network import build_network, completeness, order_key
from .openalex import BoundaryError, Client, boundary_hash, normalise_boundary, openalex_filter, retrieve
from .robustness import compare

BOUNDARY_FILE = "field_boundary.json"
LANES_FILE = "field_lanes.json"
COUNTS_FILE = "field_boundary_counts.json"
COMPLETENESS_FILE = "completeness_report.json"
MAIN_PATH_FILE = "main_path.json"
ROBUSTNESS_FILE = "robustness.json"
RESULTS_FILE = "field_map_results.json"
READING_LIST = "reading_list.csv"
FIGURE = "figures/field_map.png"
DIR = "fieldmap"
MIN_ALTERNATIVES, MAX_ALTERNATIVES = 2, 6

OPENALEX_SOURCE = {
    "connector": "openalex",
    "dataset": "OpenAlex",
    "terms_summary": "OpenAlex data are released under CC0: no restriction on use; OpenAlex asks to be cited.",
    "licence": "CC0 1.0 Universal (https://creativecommons.org/publicdomain/zero/1.0/)",
    "terms": "https://creativecommons.org/publicdomain/zero/1.0/",
    "citation": (
        "Priem, J., Piwowar, H., and Orr, R. (2022). OpenAlex: A fully-open index of scholarly works, authors, "
        "venues, institutions, and concepts. arXiv:2205.01833."
    ),
    "citation_by": "source",
    "link": "https://openalex.org",
}


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict, hash=False)
    inputs: tuple[dict[str, Any], ...] = ()

    def detail(self) -> str:
        if self.passed:
            head = "passed: " + ", ".join(f"{k}={v}" for k, v in self.stats.items())
            return "; ".join([head, *self.notes])
        return "; ".join([*self.reasons, *self.notes])


def _fail(*reasons: str) -> Verdict:
    return Verdict(passed=False, reasons=tuple(reasons))


def _read(ws: Path, name: str) -> Any:
    return json.loads((ws / name).read_text(encoding="utf-8"))


# ── boundary ────────────────────────────────────────────────────────────────


def boundary_problems(ws: Path) -> list[str]:
    """What is wrong with field_boundary.json (empty when it can be retrieved)."""
    path = ws / BOUNDARY_FILE
    if not path.is_file():
        return [f"{BOUNDARY_FILE} is missing"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{BOUNDARY_FILE} is not valid JSON: {e}"]
    if not isinstance(raw, dict) or not isinstance(raw.get("main"), dict):
        return [f"{BOUNDARY_FILE} needs a `main` boundary object"]
    problems: list[str] = []
    alts = raw.get("alternatives") or []
    if not isinstance(alts, list) or not MIN_ALTERNATIVES <= len(alts) <= MAX_ALTERNATIVES:
        problems.append(f"`alternatives` must list {MIN_ALTERNATIVES} to {MAX_ALTERNATIVES} alternative boundaries")
        alts = alts if isinstance(alts, list) else []
    names: set[str] = set()
    for i, b in enumerate([{**raw["main"], "name": "main"}, *alts]):
        try:
            nb = normalise_boundary(b)
        except BoundaryError as e:
            problems.append(str(e) if i == 0 else f"alternative {i}: {e}")
            continue
        if nb["name"] in names:
            problems.append(f"boundary name {nb['name']} is used twice")
        names.add(nb["name"])
    return problems


def load_boundaries(ws: Path) -> list[dict[str, Any]]:
    problems = boundary_problems(ws)
    if problems:
        raise BoundaryError("; ".join(problems))
    raw = _read(ws, BOUNDARY_FILE)
    return [normalise_boundary({**raw["main"], "name": "main"})] + [
        normalise_boundary(b) for b in raw.get("alternatives") or []
    ]


def _boundary_path(ws: Path, name: str) -> Path:
    return ws / DIR / "boundaries" / f"{name}.json"


def retrieve_boundaries(
    ws: Path,
    *,
    max_papers: int = 5000,
    max_requests: int = 300,
    client: Client | None = None,
    only: str | None = None,
) -> Verdict:
    """Retrieve every boundary of field_boundary.json that is not retrieved yet (or changed)."""
    from ..data.load_record import now_utc, try_record

    ws = Path(ws)
    try:
        boundaries = load_boundaries(ws)
    except BoundaryError as e:
        return _fail(str(e))
    client = client or Client.from_settings(ws / DIR / "cache", max_requests=max_requests)
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for b in boundaries:
        if only and b["name"] != only:
            continue
        path = _boundary_path(ws, b["name"])
        existing = None
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                existing = None
        if existing and existing.get("hash") == boundary_hash(b):
            data = existing
        else:
            try:
                data = retrieve(client, b, max_papers=max_papers)
            except BoundaryError as e:
                return Verdict(passed=False, reasons=(str(e),), stats={"requests": client.budget.sent})
            data["retrieved_at"] = now_utc()
            exports.write_json(path, data)
            err = try_record(
                ws,
                {
                    **OPENALEX_SOURCE,
                    "series": f"boundary {b['name']}: {data['papers_retrieved']} works",
                    "query": data["filter"],
                    "saved_to": str(path.relative_to(ws)),
                    "retrieved_at": data["retrieved_at"],
                },
            )
            if err:
                notes.append(f"the load of {b['name']} was not recorded in data_sources.json: {err}")
        rows.append(
            {
                "name": b["name"],
                "papers": data["papers_retrieved"],
                "reported_by_openalex": data["count_reported"],
                "filter": data["filter"],
                "note": b.get("note", ""),
                "retrieved_at": data.get("retrieved_at", ""),
            }
        )
    summary = {"boundaries": rows, "requests_sent": client.budget.sent, "pages_from_cache": client.budget.cached}
    exports.write_json(ws / COUNTS_FILE, summary)
    exports.write_text(ws / COUNTS_FILE.replace(".json", ".md"), _counts_md(rows))
    main = next((r for r in rows if r["name"] == "main"), None)
    if main is not None and main["papers"] < 300:
        notes.append(f"the main boundary has {main['papers']} papers; a main path is usually computed on 300 to 2,000")
    if main is not None and main["papers"] > 2000:
        notes.append(f"the main boundary has {main['papers']} papers, more than the usual 300 to 2,000")
    return Verdict(
        passed=True,
        notes=tuple(notes),
        stats={"boundaries": len(rows), "main_papers": main["papers"] if main else 0, "requests": client.budget.sent},
    )


def _counts_md(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Boundaries retrieved from OpenAlex",
        "",
        "The main boundary is the one the map is drawn from; the alternatives test which papers hold when the "
        "boundary changes. Edit `field_boundary.json` to change a boundary; it is retrieved again when the "
        "study continues.",
        "",
        "| Boundary | Papers | OpenAlex filter | Note |",
        "|---|---:|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['name']} | {r['papers']} | `{r['filter']}` | {r['note']} |")
    return "\n".join(lines) + "\n"


# ── network ─────────────────────────────────────────────────────────────────


def _load(ws: Path, name: str) -> dict[str, Any]:
    path = _boundary_path(ws, name)
    if not path.is_file():
        raise BoundaryError(f"boundary {name} has not been retrieved (run `e2er-fieldmap boundary`)")
    return json.loads(path.read_text(encoding="utf-8"))


def network_for(ws: Path, name: str):  # noqa: ANN201 — returns (data, Network)
    data = _load(ws, name)
    net = build_network(data["papers"], exclude=data["boundary"].get("exclude") or [])
    return data, net


def network_step(
    ws: Path,
    *,
    max_isolated_share: float = 0.6,
    max_missing_refs_share: float = 0.25,
    min_papers: int = 100,
) -> Verdict:
    """Build the main boundary's network and report what it is missing; fail when too much is."""
    ws = Path(ws)
    try:
        data, net = network_for(ws, "main")
    except BoundaryError as e:
        return _fail(str(e))
    rep = completeness(net, retrieved=data["papers_retrieved"], reported=data["count_reported"])
    rep["thresholds"] = {
        "max_isolated_share": max_isolated_share,
        "max_missing_refs_share": max_missing_refs_share,
        "min_papers": min_papers,
    }
    reasons: list[str] = []
    if rep["papers"] < min_papers:
        reasons.append(f"the main boundary has {rep['papers']} papers, fewer than {min_papers}")
    if rep["internal_links"] == 0:
        reasons.append("no paper of the main boundary cites another one: there is no network to analyse")
    if rep["share_without_internal_links"] > max_isolated_share:
        reasons.append(
            f"{rep['share_without_internal_links']:.0%} of the papers have no internal citation link (limit "
            f"{max_isolated_share:.0%}): the boundary is probably too broad, or its terms catch other fields"
        )
    if rep["share_without_references"] > max_missing_refs_share:
        reasons.append(
            f"{rep['share_without_references']:.0%} of the papers have no references in OpenAlex (limit "
            f"{max_missing_refs_share:.0%}): the database's coverage of this set is too thin for a main path"
        )
    rep["passed"] = not reasons
    rep["reasons"] = reasons
    exports.write_json(ws / COMPLETENESS_FILE, rep)
    exports.write_text(ws / "completeness_report.md", _completeness_md(rep))
    stats = {
        "papers": rep["papers"],
        "internal_links": rep["internal_links"],
        "without_internal_links": rep["papers_without_internal_links"],
        "cycles": rep["cycles"],
    }
    return Verdict(passed=not reasons, reasons=tuple(reasons), stats=stats)


def _completeness_md(rep: dict[str, Any]) -> str:
    t = rep["thresholds"]
    out = [
        "# Completeness of the citation network (main boundary)",
        "",
        f"- Papers: {rep['papers']} (OpenAlex reported {rep['papers_reported_by_openalex']})",
        f"- Internal citation links: {rep['internal_links']}",
        f"- Papers without internal links: {rep['papers_without_internal_links']} "
        f"({rep['share_without_internal_links']:.1%}; the check stops above {t['max_isolated_share']:.0%})",
        f"- Papers without references in OpenAlex: {rep['papers_without_references']} "
        f"({rep['share_without_references']:.1%}; the check stops above {t['max_missing_refs_share']:.0%})",
        f"- Unusually short reference lists (under a quarter of the median of {rep['median_reference_count']}): "
        f"{rep['papers_with_short_reference_lists']}",
        f"- Probable duplicates (same title): {rep['probable_duplicates']}; notices (errata, reprints, "
        f"retractions): {rep['notices']}",
        f"- Citation cycles broken: {rep['cycles']} ({rep['arcs_dropped']} arcs dropped, self-citations included)",
        f"- Years: {rep['year_first']} to {rep['year_last']}",
        "",
        "A paper without internal links cannot be on the main path. A short or missing reference list in "
        "OpenAlex drops links that exist in print, so check the papers listed in `completeness_report.json` "
        "under `lists` that you know to be important. Duplicates and notices can be excluded by adding their ids "
        "to `exclude` in `field_boundary.json`.",
    ]
    if rep["reasons"]:
        out += ["", "## Why the check stopped", "", *[f"- {r}" for r in rep["reasons"]]]
    return "\n".join(out) + "\n"


# ── main path ───────────────────────────────────────────────────────────────


def mainpath_step(ws: Path, *, key_routes: int = 10) -> Verdict:
    ws = Path(ws)
    try:
        data, net = network_for(ws, "main")
    except BoundaryError as e:
        return _fail(str(e))
    if not net.arcs:
        return _fail("the main boundary's network has no internal links")
    res = analyse(net, k=key_routes)
    res["boundary"] = "main"
    shown = (
        set(res["global_main_path"]["network_papers"])
        | set(res["key_routes"]["papers"])
        | set(res["local_main_path"]["network_papers"])
        | {x for a in res["ranked_arcs"][:15] for x in (a["cited"], a["citing"])}
    )
    res["papers"] = {p: _brief(net.papers[p]) for p in sorted(shown)}
    res["ranked_arcs"] = res["ranked_arcs"][:200]
    exports.write_json(ws / MAIN_PATH_FILE, res)
    exports.write_text(ws / "main_path.md", _mainpath_md(res))
    g = res["global_main_path"]
    return Verdict(
        passed=True,
        stats={
            "main_path_length": g["length"],
            "tied_paths": g["tied_paths"],
            "key_route_papers": len(res["key_routes"]["papers"]),
        },
        notes=(f"{g['tied_paths']} paths share the largest total SPC; all of them are in the main path network",)
        if g["tied_paths"] > 1
        else (),
    )


def _brief(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p.get(k) for k in ("year", "date", "title", "authors", "journal", "doi", "cited_by_count")}


def _cite(p: dict[str, Any]) -> str:
    authors = p.get("authors") or []
    first = authors[0] if authors else "?"
    more = " et al." if len(authors) > 2 else (f" and {authors[1]}" if len(authors) == 2 else "")
    return f"{first}{more} ({p.get('year')}). {p.get('title')}. {p.get('journal') or ''}"


def _mainpath_md(res: dict[str, Any]) -> str:
    P = res["papers"]
    g = res["global_main_path"]
    lines = [
        "# Main path of the main boundary",
        "",
        f"SPC weights on {res['arcs']} internal links between {res['papers_weighted']} papers; "
        f"{res['origins']} origins, {res['end_points']} end points, {res['total_flow']} source-to-sink paths.",
        "",
        f"## Global main path ({g['length']} papers, total SPC {g['total_spc']})",
        "",
    ]
    lines += [f"{i}. {_cite(P[p])} [{p}]" for i, p in enumerate(g["papers"], start=1)]
    if g["tied_paths"] > 1:
        lines += ["", f"{g['tied_paths']} paths tie for the largest total SPC; the list shows the earliest one."]
    loc = res["local_main_path"]
    lines += ["", f"## Local (forward) main path ({loc['length']} papers)", ""]
    lines += [f"{i}. {_cite(P[p])} [{p}]" for i, p in enumerate(loc["papers"], start=1)]
    kr = res["key_routes"]
    lines += ["", f"## Key routes (top {kr['k']} links): {len(kr['papers'])} papers", ""]
    lines += [f"- {_cite(P[p])} [{p}]" for p in kr["papers"]]
    lines += ["", "## Heaviest links", "", "| Cited | Citing | SPC | Share of all paths |", "|---|---|---:|---:|"]

    def short(pid: str) -> str:
        q = P.get(pid, {})
        first = (q.get("authors") or ["?"])[0].split()[-1]
        return f"{first} {q.get('year')} [{pid}]"

    for a in res["ranked_arcs"][:15]:
        lines.append(f"| {short(a['cited'])} | {short(a['citing'])} | {a['spc']} | {a['share']:.4f} |")
    return "\n".join(lines) + "\n"


# ── robustness ──────────────────────────────────────────────────────────────


def robustness_step(ws: Path, *, key_routes: int | None = None) -> Verdict:
    ws = Path(ws)
    try:
        boundaries = load_boundaries(ws)
    except BoundaryError as e:
        return _fail(str(e))
    if key_routes is None:
        try:
            key_routes = int(_read(ws, MAIN_PATH_FILE)["key_routes"]["k"])
        except (OSError, ValueError, KeyError):
            key_routes = 10
    results: dict[str, dict[str, Any]] = {}
    papers: dict[str, dict[str, Any]] = {}
    empty: list[str] = []
    for b in boundaries:
        try:
            _, net = network_for(ws, b["name"])
        except BoundaryError as e:
            return _fail(str(e))
        papers.update({p: _brief(v) for p, v in net.papers.items()})
        if not net.arcs:
            empty.append(b["name"])
            continue
        results[b["name"]] = {"ids": sorted(net.papers), "analysis": analyse(net, k=key_routes)}
    if "main" not in results:
        return _fail("the main boundary's network has no internal links")
    rep = compare(results, papers)
    rep["key_routes_k"] = key_routes
    rep["boundaries_without_links"] = empty
    exports.write_json(ws / ROBUSTNESS_FILE, rep)
    exports.write_text(ws / "robustness.md", _robustness_md(rep))
    notes = tuple(f"boundary {n} has no internal links and was left out" for n in empty)
    return Verdict(
        passed=True, notes=notes, stats={"boundaries": rep["boundary_count"], "robust_papers": rep["robust_papers"]}
    )


def _robustness_md(rep: dict[str, Any]) -> str:
    lines = [
        "# Robustness across boundaries",
        "",
        "| Boundary | Papers | Internal links | Main path length | Key-route papers |",
        "|---|---:|---:|---:|---:|",
    ]
    for b in rep["boundaries"]:
        lines.append(
            f"| {b['name']} | {b['papers']} | {b['internal_links']} | {b['main_path_length']} "
            f"| {b['key_route_papers']} |"
        )
    lines += [
        "",
        f"{rep['robust_papers']} papers are on the global main path of all {rep['boundary_count']} boundaries.",
        "",
        "| Paper | Year | On main path in | On key routes in | In boundary |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in rep["papers"][:40]:
        title = (r["title"] or "")[:80]
        lines.append(
            f"| {title} [{r['id']}] | {r['year']} | {r['main_paths']} | {r['key_routes']} | {r['boundaries_present']} |"
        )
    return "\n".join(lines) + "\n"


# ── lanes ───────────────────────────────────────────────────────────────────


def mapped_ids(ws: Path) -> list[str]:
    """The papers the map draws: the main path network and the key routes of the main boundary."""
    res = _read(ws, MAIN_PATH_FILE)
    return sorted(set(res["global_main_path"]["network_papers"]) | set(res["key_routes"]["papers"]))


def lanes_problems(ws: Path) -> list[str]:
    path = ws / LANES_FILE
    if not path.is_file():
        return [f"{LANES_FILE} is missing"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{LANES_FILE} is not valid JSON: {e}"]
    lanes = raw.get("lanes") if isinstance(raw, dict) else None
    if not isinstance(lanes, list) or not 2 <= len(lanes) <= 8:
        return [f"{LANES_FILE} needs `lanes`: a list of 2 to 8 lanes"]
    try:
        known = set(mapped_ids(ws))
    except (OSError, ValueError, KeyError):
        known = set()
    problems: list[str] = []
    seen: dict[str, str] = {}
    for i, lane in enumerate(lanes, start=1):
        if not isinstance(lane, dict):
            problems.append(f"lane {i} is not an object")
            continue
        q = str(lane.get("question") or "").strip()
        if not q.endswith("?"):
            problems.append(f"lane {i}: `question` must be a question ending with '?'")
        ids = lane.get("papers") or []
        if not isinstance(ids, list) or not ids:
            problems.append(f"lane {i}: `papers` must list the OpenAlex ids of its papers")
            continue
        for pid in ids:
            if known and pid not in known:
                problems.append(f"lane {i}: {pid} is not on the main path or a key route")
            if pid in seen:
                problems.append(f"{pid} is in two lanes ({seen[pid]} and {i})")
            seen[pid] = str(i)
    if known:
        missing = sorted(known - set(seen))
        if len(missing) > len(known) // 4:
            problems.append(
                f"{len(missing)} of the {len(known)} mapped papers are in no lane (at most a quarter may be)"
            )
    return problems


# ── map, exports, results ───────────────────────────────────────────────────


def map_step(ws: Path, *, require_lanes: bool = True) -> Verdict:
    """Draw the map and write the reading list, the exports, the tables and the results file.

    Without ``field_lanes.json`` (``require_lanes=False``, the ``export`` command) every paper is
    drawn in one lane.
    """
    ws = Path(ws)
    for name in (MAIN_PATH_FILE, ROBUSTNESS_FILE, COMPLETENESS_FILE):
        if not (ws / name).is_file():
            return _fail(f"{name} is missing: run the earlier field-map steps first")
    has_lanes = (ws / LANES_FILE).is_file()
    if require_lanes or has_lanes:
        problems = lanes_problems(ws)
        if problems:
            return _fail(*problems)
    try:
        data, net = network_for(ws, "main")
    except BoundaryError as e:
        return _fail(str(e))
    res = _read(ws, MAIN_PATH_FILE)
    rob = _read(ws, ROBUSTNESS_FILE)
    comp = _read(ws, COMPLETENESS_FILE)
    lanes = _read(ws, LANES_FILE)["lanes"] if has_lanes else []
    lane_of = {pid: lane["question"] for lane in lanes for pid in lane.get("papers") or []}
    papers = net.papers
    from .mainpath import spc_weights

    w = spc_weights(net)
    arcs = [
        {"cited": u, "citing": v, "spc": s, "share": round(w.share((u, v)), 6)} for (u, v), s in sorted(w.spc.items())
    ]
    # The map draws one main path; the other paths of the same weight (if any) are drawn lighter.
    main_arcs = [(a["cited"], a["citing"]) for a in res["global_main_path"]["network_arcs"]]
    chain_arcs = [(a["cited"], a["citing"]) for a in res["global_main_path"]["arcs"]]
    key_arcs = [(a["cited"], a["citing"]) for a in res["key_routes"]["arcs"]]
    # Every paper on any of the tied heaviest paths counts as on the main path (usually one path).
    main_ids = res["global_main_path"]["network_papers"]
    key_ids = res["key_routes"]["papers"]
    counts = {r["id"]: r["main_paths"] for r in rob["papers"]}
    from .figure import draw_map

    rows = exports.reading_list(papers, main_ids, key_ids, counts, lane_of)
    fig = draw_map(
        papers,
        chain_arcs,
        key_arcs,
        lanes,
        ws / FIGURE,
        ws / FIGURE.replace(".png", ".pdf"),
        numbers={r["openalex_id"]: r["order"] for r in rows},
        tied_arcs=main_arcs,
        robust=set(rob.get("robust_ids") or []),
        out_svg=ws / FIGURE.replace(".png", ".svg"),
    )
    exports.write_text(ws / READING_LIST, exports.reading_list_csv(rows))
    exports.write_json(ws / "reading_list.json", rows)
    exports.write_text(ws / "exports/field_network.net", exports.pajek(papers, arcs))
    exports.write_text(
        ws / "exports/field_network.gexf", exports.gexf(papers, arcs, set(main_arcs), set(key_arcs), lane_of)
    )
    vmap, vnet = exports.vosviewer(papers, arcs)
    exports.write_text(ws / "exports/vosviewer_map.txt", vmap)
    exports.write_text(ws / "exports/vosviewer_network.txt", vnet)
    exports.write_text(ws / "exports/edges.csv", exports.edge_csv(arcs, set(main_arcs), set(key_arcs)))
    results = build_results(data, comp, res, rob, lanes, rows)
    exports.write_json(ws / RESULTS_FILE, results)
    exports.write_text(ws / "tables/field_map_summary.tex", exports.summary_table(results))
    exports.write_text(ws / "tables/main_path_list.tex", _main_path_list_tex(rows, papers))
    added = add_method_references(ws)
    return Verdict(
        passed=True,
        stats={"papers_drawn": fig["papers_drawn"], "lanes": len(lanes), "reading_list": len(rows)},
        notes=(f"{added} method references added to literature.bib",) if added else (),
    )


def _main_path_list_tex(rows: list[dict[str, Any]], papers: dict[str, dict[str, Any]]) -> str:
    items = []
    for r in rows:
        if not r["on_main_path"]:
            continue
        p = papers[r["openalex_id"]]
        items.append(
            "  \\item "
            + exports._tex(_cite(p).strip())
            + (f" \\texttt{{doi:{exports._tex(p['doi'])}}}" if p.get("doi") else "")
        )
    return "\\begin{enumerate}\n" + "\n".join(items) + "\n\\end{enumerate}\n"


def build_results(
    data: dict[str, Any],
    comp: dict[str, Any],
    res: dict[str, Any],
    rob: dict[str, Any],
    lanes: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Every number the field review may state, in one file (read by e2er's number check)."""
    g = res["global_main_path"]
    return {
        "$comment": "Written by e2er's field map; every number the field review states comes from this file.",
        "boundary": {
            "papers": comp["papers"],
            "papers_reported_by_openalex": data["count_reported"],
            "year_first": comp["year_first"],
            "year_last": comp["year_last"],
            "filter": data["filter"],
        },
        "network": {
            "internal_links": comp["internal_links"],
            "papers_with_internal_links": comp["papers_with_internal_links"],
            "papers_without_internal_links": comp["papers_without_internal_links"],
            "share_without_internal_links": comp["share_without_internal_links"],
            "papers_without_references": comp["papers_without_references"],
            "share_without_references": comp["share_without_references"],
            "papers_with_short_reference_lists": comp["papers_with_short_reference_lists"],
            "probable_duplicates": comp["probable_duplicates"],
            "cycles_broken": comp["cycles"],
            "arcs_dropped": comp["arcs_dropped"],
        },
        "spc": {
            "papers_weighted": res["papers_weighted"],
            "origins": res["origins"],
            "end_points": res["end_points"],
            "total_paths": res["total_flow"],
        },
        "main_path": {
            "length": g["length"],
            "total_spc": g["total_spc"],
            "tied_paths": g["tied_paths"],
            "papers_on_tied_paths": len(g["network_papers"]),
            "first_year": min((r["year"] for r in rows if r["on_main_path"] and r["year"]), default=None),
            "last_year": max((r["year"] for r in rows if r["on_main_path"] and r["year"]), default=None),
            "papers": list(g["papers"]),
        },
        "local_main_path": {"length": res["local_main_path"]["length"]},
        "key_routes": {
            "k": res["key_routes"]["k"],
            "papers": len(res["key_routes"]["papers"]),
            "links": len(res["key_routes"]["arcs"]),
        },
        "robustness": {
            "boundary_count": rob["boundary_count"],
            "robust_papers": rob["robust_papers"],
            "main_path_papers_robust_share": rob["main_path_papers_robust_share"],
            "boundaries": rob["boundaries"],
        },
        "lanes": {
            "count": len(lanes),
            "papers_per_lane": {lane["question"]: len(lane.get("papers") or []) for lane in lanes},
        },
        "reading_list": {"papers": len(rows)},
    }


def add_method_references(ws: Path) -> int:
    """Append the methods' verified entries to literature.bib (once each)."""
    bib = ws / "literature.bib"
    text = bib.read_text(encoding="utf-8") if bib.is_file() else ""
    missing = [k for k in METHOD_REFERENCES if f"{{{k}," not in text]
    if not missing:
        return 0
    from .credit import bibtex

    add = "\n".join(bibtex(k, METHOD_REFERENCES[k]) for k in missing)
    bib.write_text((text.rstrip() + "\n\n" if text.strip() else "") + add, encoding="utf-8")
    return len(missing)


def papers_listing(ws: Path, *, which: str = "mapped", abstracts: bool = False) -> list[dict[str, Any]]:
    """Papers for a specialist to read: the mapped ones (main path and key routes) or a whole boundary."""
    data, net = network_for(ws, "main")
    ids = mapped_ids(ws) if which == "mapped" else sorted(net.papers, key=lambda p: order_key(net.papers[p]))
    out = []
    for p in ids:
        q = net.papers[p]
        row = {
            "id": p,
            "year": q.get("year"),
            "title": q.get("title"),
            "authors": q.get("authors", [])[:3],
            "journal": q.get("journal"),
            "keywords": q.get("keywords", []),
        }
        if abstracts:
            row["abstract"] = q.get("abstract", "")
        out.append(row)
    return out


__all__ = [
    "BOUNDARY_FILE",
    "LANES_FILE",
    "RESULTS_FILE",
    "Verdict",
    "boundary_problems",
    "lanes_problems",
    "map_step",
    "mainpath_step",
    "method_bibtex",
    "network_step",
    "openalex_filter",
    "papers_listing",
    "retrieve_boundaries",
    "robustness_step",
]
