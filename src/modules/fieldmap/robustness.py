"""Which papers hold when the boundary changes.

The main path depends on the boundary: another journal set or another year
range gives another network and possibly another path. The same analysis is
run on each alternative boundary, and each paper is counted: in how many
boundaries it appears at all, on how many global main paths, on how many
key-route networks. A paper on the global main path of every boundary is
robust; one on the main path of the main boundary only is not.
"""

from __future__ import annotations

from typing import Any


def compare(
    results: dict[str, dict[str, Any]], papers: dict[str, dict[str, Any]], main: str = "main"
) -> dict[str, Any]:
    """``results``: boundary name -> {"ids": [...all papers...], "analysis": mainpath.analyse(...)}.

    ``papers``: id -> metadata (any boundary), for the listing.
    """
    names = sorted(results, key=lambda n: (n != main, n))
    n = len(names)
    on_main: dict[str, list[str]] = {}
    on_key: dict[str, list[str]] = {}
    present: dict[str, list[str]] = {}
    for name in names:
        r = results[name]
        for pid in r["ids"]:
            present.setdefault(pid, []).append(name)
        for pid in r["analysis"]["global_main_path"]["papers"]:
            on_main.setdefault(pid, []).append(name)
        for pid in r["analysis"]["key_routes"]["papers"]:
            on_key.setdefault(pid, []).append(name)
    listed = sorted(
        set(on_main) | set(on_key),
        key=lambda p: (-len(on_main.get(p, [])), -len(on_key.get(p, [])), papers.get(p, {}).get("year") or 9999, p),
    )
    rows = [
        {
            "id": p,
            "year": papers.get(p, {}).get("year"),
            "title": papers.get(p, {}).get("title"),
            "boundaries_present": len(present.get(p, [])),
            "main_paths": len(on_main.get(p, [])),
            "key_routes": len(on_key.get(p, [])),
            "on_main_path_in": on_main.get(p, []),
            "robust": len(on_main.get(p, [])) == n,
        }
        for p in listed
    ]
    main_ids = results[main]["analysis"]["global_main_path"]["papers"] if main in results else []
    robust = [r["id"] for r in rows if r["robust"]]
    return {
        "boundaries": [
            {
                "name": name,
                "papers": len(results[name]["ids"]),
                "internal_links": results[name]["analysis"]["arcs"],
                "main_path_length": results[name]["analysis"]["global_main_path"]["length"],
                "key_route_papers": len(results[name]["analysis"]["key_routes"]["papers"]),
            }
            for name in names
        ],
        "boundary_count": n,
        "main_path_papers_main_boundary": len(main_ids),
        "robust_papers": len(robust),
        "robust_ids": robust,
        "main_path_papers_robust_share": round(len([p for p in main_ids if p in robust]) / len(main_ids), 4)
        if main_ids
        else 0.0,
        "papers": rows,
    }
