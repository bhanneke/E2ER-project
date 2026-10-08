"""The network and the reading list in formats other tools read.

- Pajek ``.net``: ``*Vertices`` with labels, ``*Arcs`` with the SPC weight
  (Pajek is where SPC and main paths were first implemented, Batagelj 2003).
- GEXF 1.3 (Gephi): directed edges weighted by SPC, with the exact count, the
  share of the total flow, and whether the arc is on the main path or a key
  route as attributes; nodes carry year, title, DOI, journal and lane.
- VOSviewer: a map file and a network file (tab-separated; VOSviewer treats
  the network as undirected).
- CSV edge list.
- The reading list (CSV and JSON): the papers of the main path and the key
  routes, by year.
- LaTeX tables whose numbers are copied from the results file, so the field
  review can include them and e2er's number check can trace every cell.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr


def _label(p: dict[str, Any]) -> str:
    first = (p.get("authors") or ["?"])[0].split()[-1] if p.get("authors") else "?"
    return f"{first} {p.get('year') or ''}".strip()


def pajek(papers: dict[str, dict[str, Any]], arcs: list[dict[str, Any]]) -> str:
    ids = sorted(papers)
    num = {pid: i + 1 for i, pid in enumerate(ids)}
    lines = [f"*Vertices {len(ids)}"]
    for pid in ids:
        lab = f"{_label(papers[pid])} {pid}".replace('"', "'")
        lines.append(f'{num[pid]} "{lab}"')
    lines.append("*Arcs")
    for a in arcs:
        lines.append(f"{num[a['cited']]} {num[a['citing']]} {a['spc']}")
    return "\n".join(lines) + "\n"


def gexf(
    papers: dict[str, dict[str, Any]],
    arcs: list[dict[str, Any]],
    main_arcs: set[tuple[str, str]],
    key_arcs: set[tuple[str, str]],
    lanes: dict[str, str],
) -> str:
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write('<gexf xmlns="http://gexf.net/1.3" version="1.3">\n')
    out.write(
        "  <meta><creator>e2er field map</creator><description>Citation network, arcs from cited to citing "
        "paper, weighted by search path count (SPC)</description></meta>\n"
    )
    out.write('  <graph defaultedgetype="directed" mode="static">\n')
    out.write('    <attributes class="node">\n')
    for i, (name, typ) in enumerate(
        [("year", "integer"), ("title", "string"), ("doi", "string"), ("journal", "string"), ("lane", "string")]
    ):
        out.write(f'      <attribute id="n{i}" title="{name}" type="{typ}"/>\n')
    out.write("    </attributes>\n")
    out.write('    <attributes class="edge">\n')
    for i, (name, typ) in enumerate(
        [("spc", "string"), ("share", "double"), ("main_path", "boolean"), ("key_route", "boolean")]
    ):
        out.write(f'      <attribute id="e{i}" title="{name}" type="{typ}"/>\n')
    out.write("    </attributes>\n    <nodes>\n")
    for pid in sorted(papers):
        p = papers[pid]
        out.write(f"      <node id={quoteattr(pid)} label={quoteattr(_label(p))}><attvalues>")
        vals = [
            p.get("year") or "",
            p.get("title") or "",
            p.get("doi") or "",
            p.get("journal") or "",
            lanes.get(pid, ""),
        ]
        for i, v in enumerate(vals):
            out.write(f'<attvalue for="n{i}" value={quoteattr(str(v))}/>')
        out.write("</attvalues></node>\n")
    out.write("    </nodes>\n    <edges>\n")
    for n, a in enumerate(arcs):
        key = (a["cited"], a["citing"])
        out.write(
            f'      <edge id="{n}" source={quoteattr(a["cited"])} target={quoteattr(a["citing"])} '
            f'weight="{float(a["spc"])!r}"><attvalues>'
            f'<attvalue for="e0" value="{a["spc"]}"/><attvalue for="e1" value="{a["share"]}"/>'
            f'<attvalue for="e2" value="{str(key in main_arcs).lower()}"/>'
            f'<attvalue for="e3" value="{str(key in key_arcs).lower()}"/></attvalues></edge>\n'
        )
    out.write("    </edges>\n  </graph>\n</gexf>\n")
    return out.getvalue()


def vosviewer(papers: dict[str, dict[str, Any]], arcs: list[dict[str, Any]]) -> tuple[str, str]:
    ids = sorted(papers)
    num = {pid: i + 1 for i, pid in enumerate(ids)}
    m = io.StringIO()
    w = csv.writer(m, delimiter="\t", lineterminator="\n")
    w.writerow(["id", "label", "description", "score<Year>"])
    for pid in ids:
        p = papers[pid]
        w.writerow([num[pid], f"{_label(p)} {pid}", escape(p.get("title") or ""), p.get("year") or ""])
    net = "".join(f"{num[a['cited']]}\t{num[a['citing']]}\t{a['spc']}\n" for a in arcs)
    return m.getvalue(), net


def edge_csv(arcs: list[dict[str, Any]], main_arcs: set[tuple[str, str]], key_arcs: set[tuple[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["cited", "citing", "spc", "share", "main_path", "key_route"])
    for a in arcs:
        k = (a["cited"], a["citing"])
        w.writerow([a["cited"], a["citing"], a["spc"], a["share"], int(k in main_arcs), int(k in key_arcs)])
    return buf.getvalue()


READING_COLUMNS = (
    "order",
    "year",
    "authors",
    "title",
    "journal",
    "doi",
    "openalex_id",
    "on_main_path",
    "on_key_route",
    "main_paths_across_boundaries",
    "lane",
)


def reading_list(
    papers: dict[str, dict[str, Any]],
    main_ids: list[str],
    key_ids: list[str],
    robust_counts: dict[str, int],
    lanes: dict[str, str],
) -> list[dict[str, Any]]:
    ids = sorted(
        set(main_ids) | set(key_ids), key=lambda p: (papers[p].get("year") or 9999, papers[p].get("date") or "", p)
    )
    rows = []
    for n, pid in enumerate(ids, start=1):
        p = papers[pid]
        rows.append(
            {
                "order": n,
                "year": p.get("year"),
                "authors": "; ".join(p.get("authors") or []),
                "title": p.get("title") or "",
                "journal": p.get("journal") or "",
                "doi": p.get("doi") or "",
                "openalex_id": pid,
                "on_main_path": pid in main_ids,
                "on_key_route": pid in key_ids,
                "main_paths_across_boundaries": robust_counts.get(pid, 0),
                "lane": lanes.get(pid, ""),
            }
        )
    return rows


def reading_list_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(READING_COLUMNS), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({**r, "on_main_path": int(r["on_main_path"]), "on_key_route": int(r["on_key_route"])})
    return buf.getvalue()


def _tex(s: str) -> str:
    rep = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(rep.get(c, c) for c in s)


def summary_table(results: dict[str, Any]) -> str:
    """Boundary, network and main path in numbers; every cell is a value of field_map_results.json."""
    rows = [
        ("Papers in the boundary", results["boundary"]["papers"]),
        ("Internal citation links", results["network"]["internal_links"]),
        ("Papers without internal links", results["network"]["papers_without_internal_links"]),
        ("Papers without references in OpenAlex", results["network"]["papers_without_references"]),
        ("Papers on the global main path", results["main_path"]["length"]),
        ("Papers in the key-route network", results["key_routes"]["papers"]),
        ("Boundaries compared", results["robustness"]["boundary_count"]),
        ("Papers on the main path of every boundary", results["robustness"]["robust_papers"]),
    ]
    body = "\n".join(f"{_tex(label)} & {value} \\\\" for label, value in rows)
    return (
        "\\begin{table}[ht]\n\\centering\n\\caption{The field map in numbers}\n\\label{tab:fieldmap-summary}\n"
        "\\begin{tabular}{lr}\n\\hline\n & Count \\\\\n\\hline\n" + body + "\n\\hline\n\\end{tabular}\n\\end{table}\n"
    )


def main_path_table(rows: list[dict[str, Any]]) -> str:
    """The global main path, paper by paper (year, first author, title, journal)."""
    lines = []
    for r in rows:
        if not r["on_main_path"]:
            continue
        first = (r["authors"].split("; ")[0] if r["authors"] else "").split(" ")[-1]
        title = r["title"] if len(r["title"]) <= 70 else r["title"][:67].rstrip() + "..."
        lines.append(f"{r['year']} & {_tex(first)} & {_tex(title)} & {_tex(r['journal'][:30])} \\\\")
    return (
        "\\begin{table}[ht]\n\\centering\n\\small\n\\caption{The global main path}\n\\label{tab:fieldmap-mainpath}\n"
        "\\begin{tabular}{llp{7cm}l}\n\\hline\nYear & First author & Title & Journal \\\\\n\\hline\n"
        + "\n".join(lines)
        + "\n\\hline\n\\end{tabular}\n\\end{table}\n"
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
