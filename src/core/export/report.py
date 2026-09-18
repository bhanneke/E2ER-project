"""Write ``report.html`` into an exported bundle — the thing you can send someone.

Until now, seeing what a run produced meant installing Python, installing E2ER
and starting a server. For a project whose claim is that verification should be
cheap, that put the results behind a developer toolchain: a co-author, a
referee or a reviewer could not look without becoming a user first.

This is one file at the bundle root. Double-click it. No install, no server, no
network: the CSS is inline, there are no scripts fetching anything, and every
link is a relative path to a file that travels in the same folder. It opens the
same way off a USB stick, out of a zip, or from a shared drive.

It reports what the run itself recorded — the gate reports, the provenance
graph, the artifacts — rather than recomputing any of it, so it cannot disagree
with ``e2er verify``.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

#: Documents worth a direct link at the top, most-wanted first.
_READABLE: tuple[tuple[str, str], ...] = (
    ("paper/paper.pdf", "The paper (PDF)"),
    ("paper/paper.tex", "LaTeX source"),
    ("paper/abstract.tex", "Abstract"),
    ("design/identification_strategy.md", "Identification strategy"),
    ("results/estimation_results.json", "Estimation results"),
    ("replication/estimation.py", "Replication script"),
)


def _load(bundle: Path, rel: str) -> dict[str, Any] | None:
    path = bundle / rel
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt_size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1000:
        return f"{n // 1000} KB"
    return f"{n} B"


def _verdicts(bundle: Path) -> list[dict[str, Any]]:
    """The run's own gate verdicts, read from the reports it wrote."""
    out: list[dict[str, Any]] = []

    if (d := _load(bundle, "results/table_render_report.json")) is not None:
        unresolved = d.get("unresolved") or []
        errors = d.get("errors") or []
        out.append(
            {
                "name": "Tables",
                "ok": not unresolved and not errors,
                "detail": f"{len(d.get('rendered') or [])} rendered from the result files, "
                f"{len(unresolved)} unresolved",
            }
        )

    if (d := _load(bundle, "results/number_verification.json")) is not None:
        crit = [m for m in (d.get("mismatches") or []) if m.get("severity") == "critical"]
        out.append(
            {
                "name": "Numbers",
                "ok": not crit,
                "detail": f"{d.get('matched', 0)} table cells trace to a source key, {len(crit)} critical mismatches",
            }
        )

    if (d := _load(bundle, "reviews/citation_integrity.json")) is not None:
        out.append(
            {
                "name": "Citations",
                "ok": bool(d.get("passed")),
                "detail": f"{d.get('verified', 0)} of {d.get('total_cites', 0)} verified, "
                f"{d.get('missing_in_bib', 0)} missing from the bibliography",
            }
        )

    if (d := _load(bundle, "reviews/review_aggregation.json")) is not None:
        verdict = str(d.get("verdict", "")).upper() or "—"
        avg = d.get("weighted_avg")
        out.append(
            {
                "name": "Internal review",
                "ok": verdict not in {"REJECT", "MECHANISM_FAIL"},
                "detail": verdict + (f" · {avg:.2f}/10" if isinstance(avg, (int, float)) else ""),
            }
        )

    return out


def _provenance_summary(bundle: Path) -> dict[str, Any]:
    prov = _load(bundle, "provenance.json") or {}
    edges = prov.get("edges") or []
    counts: dict[str, int] = {}
    for e in edges:
        if isinstance(e, dict):
            kind = str(e.get("type", "other"))
            counts[kind] = counts.get(kind, 0) + 1
    return {
        "files": len(prov.get("files") or {}),
        "edges": len(edges),
        "counts": counts,
        "run": prov.get("run") or {},
    }


def _inventory(bundle: Path) -> list[tuple[str, list[tuple[str, int]]]]:
    """Files grouped by their top-level directory, which is the export layout."""
    groups: dict[str, list[tuple[str, int]]] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name == "report.html":
            continue
        rel = path.relative_to(bundle).as_posix()
        top = rel.split("/")[0] if "/" in rel else "(root)"
        groups.setdefault(top, []).append((rel, path.stat().st_size))
    order = ["paper", "results", "design", "code", "data", "replication", "reviews", "misc", "(root)"]
    return [(k, groups[k]) for k in order if k in groups] + [
        (k, v) for k, v in sorted(groups.items()) if k not in order
    ]


_CSS = """
:root{--paper:#faf9f6;--card:#fff;--ink:#1b1f2b;--muted:#5f6676;--line:#e3ded4;
--ok:#2c7a54;--bad:#ab392f;--accent:#ad5a29;--okbg:#e6f2ea;--badbg:#fbe9e7}
@media(prefers-color-scheme:dark){:root{--paper:#14161c;--card:#1b1e26;--ink:#e9e7e1;
--muted:#98a0af;--line:#2c313b;--ok:#56b483;--bad:#e07a6d;--accent:#e0884d;
--okbg:#16302a;--badbg:#3a201d}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);line-height:1.6;
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:40px 20px 72px}
h1{font-size:30px;line-height:1.15;margin:0 0 8px}
h2{font-size:20px;margin:44px 0 12px}
h3{font-size:15px;margin:0}
p{margin:0 0 12px;max-width:70ch}
.muted{color:var(--muted)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
a{color:var(--accent)}
.lede{border-bottom:2px solid var(--ink);padding-bottom:22px;margin-bottom:8px}
.abstract{background:var(--card);border:1px solid var(--line);padding:18px 20px;margin:18px 0}
.reads{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 6px}
.reads a{display:block;padding:10px 14px;border:1px solid var(--line);background:var(--card);
border-radius:4px;text-decoration:none;color:var(--ink);font-size:14px}
.reads a.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.reads a .p{display:block;font-size:11px;color:var(--muted);font-family:ui-monospace,Menlo,monospace}
.reads a.primary .p{color:rgba(255,255,255,.85)}
.v{display:grid;grid-template-columns:26px 150px 1fr;gap:12px;padding:12px 16px;
border-bottom:1px solid var(--line);align-items:start}
.v:last-child{border-bottom:none}
.vs{border:1px solid var(--line);background:var(--card)}
.mark{font-weight:700}
.ok{color:var(--ok)}.bad{color:var(--bad)}
.pill{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;
text-transform:uppercase;letter-spacing:.06em}
.pill.ok{background:var(--okbg)}.pill.bad{background:var(--badbg)}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line)}
th{text-align:left;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
color:var(--muted);padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:7px 10px;border-bottom:1px solid var(--paper);font-size:13.5px;vertical-align:top}
td.n{text-align:right;font-family:ui-monospace,Menlo,monospace;white-space:nowrap;color:var(--muted)}
details{border:1px solid var(--line);background:var(--card);margin-bottom:6px}
summary{cursor:pointer;padding:10px 14px;font-weight:600;display:flex;
justify-content:space-between;gap:12px;list-style:none}
summary::-webkit-details-marker{display:none}
details ul{margin:0;padding:0 0 8px;list-style:none;border-top:1px solid var(--line)}
details li{display:flex;justify-content:space-between;gap:12px;padding:5px 14px}
footer{margin-top:48px;padding-top:18px;border-top:1px solid var(--line);
color:var(--muted);font-size:13px}
@media(max-width:620px){.v{grid-template-columns:26px 1fr}.v div:last-child{grid-column:2}}
"""


def render_report(bundle: Path, manifest: dict[str, Any]) -> str:
    """Build the standalone HTML. Pure — takes a bundle, returns a document."""
    title = str(manifest.get("title") or bundle.name)
    rq = str(manifest.get("research_question") or "")

    prov = _provenance_summary(bundle)
    run = prov["run"]
    verdicts = _verdicts(bundle)

    abstract = ""
    abs_path = bundle / "paper" / "abstract.tex"
    if abs_path.is_file():
        try:
            raw = abs_path.read_text(encoding="utf-8", errors="replace")
            for marker in ("\\begin{abstract}", "\\end{abstract}"):
                raw = raw.replace(marker, "")
            abstract = " ".join(raw.split())[:2200]
        except OSError:
            abstract = ""

    reads = [(rel, label) for rel, label in _READABLE if (bundle / rel).is_file()]

    P: list[str] = []
    P.append("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    P.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    P.append(f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body><div class='wrap'>")

    P.append("<div class='lede'>")
    P.append(f"<h1>{_esc(title)}</h1>")
    if rq:
        P.append(f"<p class='muted'>{_esc(rq)}</p>")
    bits = [f"{_esc(k)}: {_esc(v)}" for k, v in run.items() if k in ("backend", "model", "governance", "exported_at")]
    if bits:
        P.append(f"<p class='mono muted'>{' · '.join(bits)}</p>")
    P.append("</div>")

    if reads:
        P.append("<div class='reads'>")
        for i, (rel, label) in enumerate(reads):
            cls = " class='primary'" if i == 0 else ""
            P.append(f"<a href='{_esc(rel)}'{cls}>{_esc(label)}<span class='p'>{_esc(rel)}</span></a>")
        P.append("</div>")

    if abstract:
        P.append(f"<div class='abstract'><h3>Abstract</h3><p>{_esc(abstract)}</p></div>")

    P.append("<h2>What was checked</h2>")
    if verdicts:
        P.append("<div class='vs'>")
        for v in verdicts:
            mark = "✓" if v["ok"] else "✗"
            cls = "ok" if v["ok"] else "bad"
            P.append(
                f"<div class='v'><div class='mark {cls}'>{mark}</div>"
                f"<div><strong>{_esc(v['name'])}</strong></div>"
                f"<div class='muted'>{_esc(v['detail'])}</div></div>"
            )
        P.append("</div>")
    else:
        P.append("<p class='muted'>This bundle carries no gate reports.</p>")

    P.append(
        "<p class='muted' style='margin-top:14px'>These are the verdicts the run recorded, not a "
        "re-check. To verify the bundle independently — re-hash every file, recompute the numbers, "
        "re-render the tables and resolve every citation — run "
        "<span class='mono'>e2er verify</span> on this folder.</p>"
    )

    P.append("<h2>Provenance</h2>")
    P.append(
        f"<p><strong>{prov['files']}</strong> files inventoried by SHA-256, "
        f"<strong>{prov['edges']}</strong> derivation edges recording where each output came from.</p>"
    )
    if prov["counts"]:
        P.append("<table><thead><tr><th>Edge</th><th style='text-align:right'>Count</th></tr></thead><tbody>")
        for kind, n in sorted(prov["counts"].items(), key=lambda kv: -kv[1]):
            P.append(f"<tr><td class='mono'>{_esc(kind)}</td><td class='n'>{n}</td></tr>")
        P.append("</tbody></table>")

    P.append("<h2>Everything in this folder</h2>")
    for top, files in _inventory(bundle):
        total = sum(size for _, size in files)
        P.append(
            f"<details><summary><span>{_esc(top)}</span>"
            f"<span class='mono muted'>{len(files)} files · {_fmt_size(total)}</span></summary><ul>"
        )
        for rel, size in files:
            P.append(
                f"<li><a class='mono' href='{_esc(rel)}'>{_esc(rel)}</a>"
                f"<span class='mono muted'>{_fmt_size(size)}</span></li>"
            )
        P.append("</ul></details>")

    P.append(
        "<footer>Generated by E2ER at export. Everything above is read from this bundle — "
        "open any file beside this one to check it. Verification establishes that the paper's "
        "claims trace to the artifacts that produced them; whether the analysis was a good idea "
        "is a separate question, and still the reader's.</footer>"
    )
    P.append("</div></body></html>")
    return "\n".join(P)


def write_report(bundle: Path, manifest: dict[str, Any]) -> Path | None:
    """Write ``report.html`` into the bundle. Best-effort — never fails an export.

    A bundle without its report is still a valid bundle; an export that dies
    while writing a convenience file is not.
    """
    try:
        target = bundle / "report.html"
        target.write_text(render_report(bundle, manifest), encoding="utf-8")
        logger.info("Wrote %s", target.name)
        return target
    except Exception as e:  # noqa: BLE001
        logger.warning("could not write report.html: %s", e)
        return None
