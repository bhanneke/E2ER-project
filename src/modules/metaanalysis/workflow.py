"""The meta-analysis steps on a study's workspace, each returning a verdict the runner records.

- ``search_step``: every search of the protocol on OpenAlex (and Crossref when
  named), deduplicated into ``records.json``; counts for the researcher.
- ``screening_step``: the screener's decisions checked (every record decided,
  every exclusion with a criterion and a reason); the sample the researcher reads.
- ``fulltext_step``: open-access full texts of the records that passed
  screening, page by page, or why there is none.
- ``extraction_step``: the extraction checked and every extracted number read
  back from its source; ``meta_studies.csv``, ``risk_of_bias.csv``, the flow counts.
- ``synthesis_step``: ``run_estimation.py`` (e2er's code) written and run; the
  results held to the meta-analysis contract; forest, funnel and PRISMA flow
  figures; tables; the methods' and the included studies' references.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..fieldmap.exports import _tex, write_json, write_text
from ..fieldmap.openalex import BoundaryError
from ..fieldmap.workflow import Verdict
from . import extraction as ex
from . import fulltext as ft
from . import screening as sc
from . import search as se
from .credit import METHOD_REFERENCES, bibtex
from .protocol import PROTOCOL_FILE, ProtocolError, load_protocol, synthesis_settings
from .script import SCRIPT, build
from .stats import RATIO_MEASURES

RESULTS = "estimation_results.json"
REFERENCES_FILE = "meta_references.json"
TABLE_STUDIES = "tables/meta_studies.tex"
TABLE_RESULTS = "tables/meta_results.tex"
TABLE_FLOW = "tables/meta_flow.tex"
FIG_FOREST, FIG_FUNNEL, FIG_PRISMA = "fig_forest.pdf", "fig_funnel.pdf", "fig_prisma.pdf"


def _fail(*reasons: str, **stats: Any) -> Verdict:
    return Verdict(passed=False, reasons=tuple(reasons), stats=stats)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── search ──────────────────────────────────────────────────────────────────


def search_step(ws: Path, *, max_records: int = 600, max_requests: int = 40, max_crossref: int = 100) -> Verdict:
    from ..data.load_record import try_record

    ws = Path(ws)
    try:
        protocol = load_protocol(ws)
    except ProtocolError as e:
        return _fail(str(e))
    cl = se.client(ws, max_requests)
    found: list[tuple[str, dict[str, Any]]] = []
    searches: list[dict[str, Any]] = []
    notes: list[str] = []
    by_db: dict[str, int] = {}
    for s in protocol["searches"]:
        for db in protocol.get("databases") or ["openalex"]:
            try:
                got = (
                    se.run_openalex(cl, s, max_records=max_records)
                    if db == "openalex"
                    else se.run_crossref(cl, ws, s, rows=max_crossref)
                )
            except BoundaryError as e:
                return _fail(str(e), requests=cl.budget.sent)
            except Exception as e:  # noqa: BLE001 — a database that cannot be reached stops the search, reported
                return _fail(f"search {s['name']} on {db} failed: {str(e)[:300]}", requests=cl.budget.sent)
            where = f"{db}:{s['name']}"
            found.extend((where, r) for r in got["records"])
            by_db[db] = by_db.get(db, 0) + len(got["records"])
            entry = {
                "name": s["name"],
                "database": db,
                "query": got["query"],
                "count_reported": got["count_reported"],
                "records_read": len(got["records"]),
                "retrieved_at": _now(),
            }
            if got.get("note"):
                entry["note"] = got["note"]
                notes.append(f"{where}: {got['note']}")
            searches.append(entry)
            err = try_record(
                ws,
                {
                    **(se.OPENALEX_SOURCE if db == "openalex" else se.CROSSREF_SOURCE),
                    "series": f"search {s['name']}: {len(got['records'])} records",
                    "query": got["query"],
                    "saved_to": se.RECORDS_FILE,
                    "retrieved_at": entry["retrieved_at"],
                },
            )
            if err:
                notes.append(f"the load of search {s['name']} was not recorded in data_sources.json: {err}")
    records, dups = se.deduplicate(found)
    if not records:
        return _fail("the searches found no records; widen the query or the years", requests=cl.budget.sent)
    if len(records) > max_records:
        return _fail(
            f"the searches find {len(records)} records together, above the limit of {max_records}; narrow them",
            requests=cl.budget.sent,
        )
    log = {
        "searches": searches,
        "identified": len(found),
        "identified_by_database": by_db,
        "duplicates_removed": dups,
        "records": len(records),
        "with_abstract": sum(1 for r in records if r.get("abstract")),
        "open_access": sum(1 for r in records if r.get("is_oa")),
        "requests_sent": cl.budget.sent,
        "pages_from_cache": cl.budget.cached,
        "notes": notes,
    }
    write_json(ws / se.RECORDS_FILE, {"records": records})
    write_text(ws / se.RECORDS_CSV, se.records_csv(records))
    write_json(ws / se.SEARCH_LOG, log)
    write_text(ws / se.COUNTS_MD, se.counts_md(log))
    missing_abs = len(records) - int(log["with_abstract"])  # type: ignore[call-overload]
    if missing_abs:
        notes.append(f"{missing_abs} record(s) have no abstract in the index; they are screened on the title")
    return Verdict(
        passed=True,
        notes=tuple(notes),
        stats={"records": len(records), "duplicates_removed": dups, "requests": cl.budget.sent},
    )


# ── screening ───────────────────────────────────────────────────────────────


def screening_step(ws: Path, *, sample_size: int = 20) -> Verdict:
    ws = Path(ws)
    problems = sc.screening_problems(ws)
    if problems:
        return _fail(*problems)
    records = sc.load_records(ws)
    decisions = sc.screened(ws)
    picked = sc.sample(records, decisions, sample_size)
    counts = {k: sum(1 for d in decisions.values() if d.get("decision") == k) for k in sc.DECISIONS}
    write_json(ws / sc.CHECK_FILE, {"counts": counts, "records": len(records), "sample": picked})
    write_text(ws / sc.SAMPLE_MD, sc.sample_md(records, decisions, picked))
    notes = []
    if counts["include"] + counts["unsure"] == 0:
        notes.append("no record passed screening: the review will include no study")
    return Verdict(passed=True, notes=tuple(notes), stats={"records": len(records), **counts})


# ── full texts ──────────────────────────────────────────────────────────────


def fulltext_step(ws: Path, *, max_downloads: int = 150) -> Verdict:
    ws = Path(ws)
    problems = sc.screening_problems(ws)
    if problems:
        return _fail(*problems)
    by_id = {r["id"]: r for r in sc.load_records(ws)}
    candidates = [by_id[i] for i in sc.to_full_text(ws)]
    log = ft.fulltext_step(ws, candidates, max_downloads=max_downloads)
    c = log["counts"]
    notes = []
    if c["not_retrieved"]:
        notes.append(
            f"{c['not_retrieved']} of {c['sought']} full text(s) not available (fulltext_log.json says why); "
            "those studies are assessed on their abstracts. A PDF saved as data/fulltext/<id>.pdf is used at the "
            "next start."
        )
    return Verdict(passed=True, notes=tuple(notes), stats=c)


# ── extraction ──────────────────────────────────────────────────────────────


def extraction_step(ws: Path) -> Verdict:
    ws = Path(ws)
    problems = ex.structure_problems(ws)
    if problems:
        return _fail(*problems)
    report = ex.trace(ws)
    write_json(ws / ex.CHECK_FILE, report)
    write_text(ws / ex.CHECK_MD, _trace_md(report))
    traced = ex.trace_problems(report)
    if traced:
        return _fail(*traced, numbers=report["numbers"], traced=report["traced"])
    protocol = load_protocol(ws)
    raw = ex.load_extraction(ws)
    write_text(ws / ex.STUDIES_CSV, ex.studies_csv(raw, protocol["effect_measure"]))
    write_text(ws / ex.ROB_CSV, ex.rob_csv(raw, [str(d) for d in protocol["risk_of_bias"]["domains"]]))
    counts = ex.prisma_counts(ws, raw)
    write_json(ws / ex.PRISMA_FILE, counts)
    notes = [r["note"] for r in report["rows"] if r.get("note")]
    abstract_only = sum(1 for s in ex.included(raw) if s.get("source_text") == "abstract")
    if abstract_only:
        notes.append(f"{abstract_only} included stud(ies) extracted from the abstract only")
    return Verdict(
        passed=True,
        notes=tuple(dict.fromkeys(notes)),
        stats={
            "numbers": report["numbers"],
            "traced": report["traced"],
            "included": counts["included_in_review"],
            "pooled": counts["included_in_meta_analysis"],
        },
    )


def _trace_md(report: dict[str, Any]) -> str:
    lines = [
        "# Extracted numbers and their sources",
        "",
        f"{report['traced']} of {report['numbers']} extracted numbers traced to the text they cite.",
        "",
        "| Study | Field | Value | Status | Where | Quote |",
        "|---|---|---:|---|---|---|",
    ]
    for r in report["rows"]:
        quote = (r.get("quote") or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {r['study']} | {r['field']} | {r['value']:g} | {r['status']} | {r.get('where', '')} | {quote[:160]} |"
        )
    return "\n".join(lines) + "\n"


# ── synthesis ───────────────────────────────────────────────────────────────


def run_script(ws: Path, *, timeout: int = 300) -> tuple[int, str]:
    from ...core.script_log import record_script_run

    started = _now()
    proc = subprocess.run(
        [sys.executable, SCRIPT], cwd=ws, capture_output=True, text=True, timeout=timeout, check=False
    )
    record_script_run(ws, SCRIPT, started, proc.returncode, by="e2er")
    return proc.returncode, (proc.stderr or proc.stdout)[-1500:]


def synthesis_step(ws: Path) -> Verdict:
    """Write and run run_estimation.py, hold the results to the contract, draw figures and tables."""
    from ...core.pipeline.result_kinds import check_results

    ws = Path(ws)
    for name in (PROTOCOL_FILE, ex.STUDIES_CSV, ex.PRISMA_FILE):
        if not (ws / name).is_file():
            return _fail(f"{name} is missing: run the extraction check first")
    protocol = load_protocol(ws)
    from ...core.pipeline.preregistration import describe_deviation, deviation_details, load_lock

    lock = load_lock(ws)
    if lock is not None:
        changed = [d for d in deviation_details(ws, lock) if not d["approved"]]
        if changed:
            return _fail(
                "the protocol changed after it was frozen in the pre-registration: "
                + "; ".join(describe_deviation(d) for d in changed)
                + ". Put review_protocol.json back as preregistration.md records it, or start a new study"
            )
    write_text(ws / SCRIPT, build())
    code, tail = run_script(ws)
    if code != 0:
        return _fail(f"{SCRIPT} failed (exit {code}): {tail}")
    results = json.loads((ws / RESULTS).read_text(encoding="utf-8"))
    refs = add_references(ws)
    write_figure_spec(ws, results, protocol)
    from ...core.renderer.figures import render_figures

    report = render_figures(ws)
    write_tables(ws, results, protocol)
    problems = check_results("metaanalysis", results, ws)
    if problems:
        return _fail(*problems)
    missing = [f for f in results["figures"] if f not in report.rendered]
    if missing:
        return _fail(f"figure(s) not drawn: {', '.join(missing)} ({'; '.join(report.skipped + report.errors)[:400]})")
    notes = []
    settings = synthesis_settings(protocol)
    if results.get("narrative_only"):
        notes.append(results["narrative_reason"])
    else:
        e = (results.get("small_study_effects") or {}).get("egger") or {}
        if e.get("low_power"):
            notes.append(f"Egger's test on {results['k']} studies has little power (fewer than 10)")
        h = results["heterogeneity"]
        if h["i2"] >= 75:
            notes.append(f"I^2 = {h['i2']:.0f}%: most of the variation between studies is heterogeneity")
    if refs:
        notes.append(f"{refs} reference(s) added to literature.bib")
    return Verdict(
        passed=True,
        notes=tuple(notes),
        stats={
            "k": results["k"],
            "pooled": not results.get("narrative_only"),
            "min_studies": settings["min_studies"],
            "estimate": round(results["pooled"]["estimate"], 4) if results.get("pooled") else None,
        },
    )


# ── references ──────────────────────────────────────────────────────────────


def _family(author: str) -> str:
    parts = author.replace(",", " ").split()
    return parts[-1] if parts else ""


def study_entry(rec: dict[str, Any]) -> dict[str, str]:
    authors = " and ".join(
        f"{_family(a)}, {' '.join(a.split()[:-1])}".strip(", ") for a in rec.get("authors") or [] if a.strip()
    )
    entry = {
        "type": "article",
        "author": authors or "Anonymous",
        "title": "{" + (rec.get("title") or "").replace("{", "").replace("}", "") + "}",
        "journal": rec.get("journal") or "",
        "year": str(rec.get("year") or ""),
        "volume": str(rec.get("volume") or ""),
        "number": str(rec.get("issue") or ""),
        "pages": str(rec.get("pages") or "").replace("-", "--"),
        "doi": rec.get("doi") or "",
    }
    return entry


def _ascii(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def cite_key(rec: dict[str, Any], taken: set[str]) -> str:
    fam = re.sub(r"[^a-z]", "", _ascii(_family((rec.get("authors") or ["anon"])[0])).lower()) or "anon"
    word = next(
        (w for w in re.findall(r"[a-z]+", _ascii(rec.get("title") or "").lower()) if len(w) > 3 and w not in _STOP),
        "study",
    )
    base = f"{fam}{rec.get('year') or 'nd'}{word}"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}{chr(ord('a') + n - 2)}"
    taken.add(key)
    return key


_STOP = {"with", "from", "their", "between", "among", "about", "into", "this", "that", "does", "what", "when"}


def add_references(ws: Path) -> int:
    """The methods' and the included studies' entries into literature.bib (once each); keys in meta_references.json."""
    ws = Path(ws)
    raw = ex.load_extraction(ws)
    records = {r["id"]: r for r in sc.load_records(ws)}
    bib = ws / "literature.bib"
    text = bib.read_text(encoding="utf-8") if bib.is_file() else ""
    existing = set(re.findall(r"@\w+\{([^,\s]+),", text))
    keys_path = ws / REFERENCES_FILE
    keys = json.loads(keys_path.read_text(encoding="utf-8")) if keys_path.is_file() else {"methods": {}, "studies": {}}
    add: list[str] = []
    for k, entry in METHOD_REFERENCES.items():
        keys["methods"][k] = entry["doi"]
        if k not in existing:
            add.append(bibtex(k, entry))
            existing.add(k)
    for s in ex.included(raw):
        rec = records.get(s["id"])
        if rec is None:
            continue
        key = keys["studies"].get(s["id"]) or cite_key(rec, set(existing))
        keys["studies"][s["id"]] = key
        if key not in existing:
            add.append(bibtex(key, study_entry(rec)))
            existing.add(key)
    write_json(keys_path, keys)
    if add:
        bib.write_text((text.rstrip() + "\n\n" if text.strip() else "") + "\n".join(add), encoding="utf-8")
    return len(add)


# ── figures and tables ──────────────────────────────────────────────────────


def _ratio(protocol: dict[str, Any]) -> bool:
    return protocol["effect_measure"] in RATIO_MEASURES


def write_figure_spec(ws: Path, results: dict[str, Any], protocol: dict[str, Any]) -> None:
    """figure_spec.json entries for the forest, funnel and PRISMA figures (others kept as they are)."""
    path = ws / "figure_spec.json"
    spec = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"figures": []}
    own = {FIG_FOREST, FIG_FUNNEL, FIG_PRISMA}
    figures = [f for f in spec.get("figures") or [] if isinstance(f, dict) and f.get("filename") not in own]
    measure = results["effect_measure"]
    p = results["prisma"]
    figures.append(
        {
            "filename": FIG_PRISMA,
            "figure_type": "prisma",
            "title": "PRISMA 2020 flow of records",
            "counts": p,
        }
    )
    if not results.get("narrative_only"):
        pooled = results["pooled"]
        pi = results.get("prediction_interval")
        figures.append(
            {
                "filename": FIG_FOREST,
                "figure_type": "forest",
                "title": "Forest plot",
                "x_label": measure if measure not in ("r",) else "correlation r",
                "log_x": _ratio(protocol),
                "null_value": 1.0 if _ratio(protocol) else 0.0,
                "studies": [
                    {
                        "label": s["label"],
                        "estimate": s["estimate_reported_scale"],
                        "lower": s["ci_lower_reported_scale"],
                        "upper": s["ci_upper_reported_scale"],
                        "weight": s.get("weight_percent"),
                    }
                    for s in results["studies"]
                ],
                "pooled": {
                    "label": f"Random effects ({results['model']['tau2_method']})",
                    "estimate": pooled["estimate_reported_scale"],
                    "lower": pooled["ci_lower_reported_scale"],
                    "upper": pooled["ci_upper_reported_scale"],
                },
                "prediction": (
                    {"lower": pi["lower_reported_scale"], "upper": pi["upper_reported_scale"]} if pi else None
                ),
            }
        )
        tf = (results.get("small_study_effects") or {}).get("trim_and_fill") or {}
        figures.append(
            {
                "filename": FIG_FUNNEL,
                "figure_type": "funnel",
                "title": "Funnel plot",
                "x_label": results["analysis_scale"],
                "points": [{"estimate": s["yi"], "se": s["se"]} for s in results["studies"]],
                "pooled": pooled["estimate"],
                "filled": [
                    {"estimate": y, "se": s}
                    for y, s in zip(tf.get("filled") or [], tf.get("filled_se") or [], strict=False)
                ],
            }
        )
    spec["figures"] = figures
    write_json(path, spec)


def _f(x: Any, d: int = 2) -> str:
    return "---" if x is None else f"{x:.{d}f}"


def _p(x: Any) -> str:
    if x is None:
        return "---"
    return "$<$0.001" if x < 0.001 else f"{x:.3f}"


def _tabular(cols: str, header: str, rows: list[str]) -> str:
    return (
        f"\\begin{{tabular}}{{{cols}}}\n\\toprule\n{header} \\\\\n\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )


def write_tables(ws: Path, results: dict[str, Any], protocol: dict[str, Any]) -> None:
    """The studies, the pooled results and the flow counts as LaTeX tables; every number from the results file."""
    level = int(round(100 * results["model"]["ci_level"]))
    rows = []
    for s in results["studies"]:
        rows.append(
            f"{_tex(s['label'])} & {s['n'] if s.get('n') is not None else '---'} & "
            f"{_f(s['estimate_reported_scale'])} & [{_f(s['ci_lower_reported_scale'])}, "
            f"{_f(s['ci_upper_reported_scale'])}] & {_f(s.get('weight_percent'), 1)} & "
            f"{_tex(s.get('risk_of_bias') or '---')} \\\\"
        )
    header = f"Study & $n$ & {_tex(results['effect_measure'])} & {level}\\% CI & Weight (\\%) & Risk of bias"
    write_text(ws / TABLE_STUDIES, _tabular("lrrcrl", header, rows or ["\\multicolumn{6}{l}{No study} \\\\"]))

    p = results["prisma"]
    flow = [
        ("Records identified", p["identified"]["total"]),
        ("Duplicates removed", p["duplicates_removed"]),
        ("Records screened on title and abstract", p["screened"]),
        ("Records excluded on title and abstract", p["excluded_on_title_abstract"]),
        ("Reports sought for retrieval", p["sought_for_full_text"]),
        ("Full texts not retrieved (assessed on the abstract)", p["full_text_not_retrieved"]),
        ("Reports excluded at eligibility", p["excluded_at_eligibility"]),
        ("Studies included in the review", p["included_in_review"]),
        ("Studies included in the meta-analysis", p["included_in_meta_analysis"]),
    ]
    write_text(ws / TABLE_FLOW, _tabular("lr", "Stage & Records", [f"{_tex(a)} & {b} \\\\" for a, b in flow]))

    if results.get("narrative_only"):
        (ws / TABLE_RESULTS).unlink(missing_ok=True)
        return
    pooled, h = results["pooled"], results["heterogeneity"]
    pi = results.get("prediction_interval")
    fe = results["fixed_effect"]
    e = (results.get("small_study_effects") or {}).get("egger") or {}
    tf = (results.get("small_study_effects") or {}).get("trim_and_fill") or {}
    scale = results["analysis_scale"]
    same = scale == results["effect_measure"]
    out = [f"Studies pooled ($k$) & {results['k']} \\\\"]
    out.append(
        f"Pooled {_tex(results['effect_measure'])} [{level}\\% CI] & {_f(pooled['estimate_reported_scale'])} "
        f"[{_f(pooled['ci_lower_reported_scale'])}, {_f(pooled['ci_upper_reported_scale'])}] \\\\"
    )
    if not same:
        out.append(
            f"Pooled on the analysis scale ({_tex(scale)}) & {_f(pooled['estimate'], 3)} "
            f"[{_f(pooled['ci_lower'], 3)}, {_f(pooled['ci_upper'], 3)}] \\\\"
        )
    out.append(f"$z$; $p$ & {_f(pooled['z'])}; {_p(pooled['p_value'])} \\\\")
    if pi:
        out.append(
            f"{level}\\% prediction interval & "
            f"[{_f(pi['lower_reported_scale'])}, {_f(pi['upper_reported_scale'])}] \\\\"
        )
    out.append(f"$\\tau^2$ ({_tex(h['tau2_method'])}); $\\tau$ & {_f(h['tau2'], 3)}; {_f(h['tau'], 3)} \\\\")
    out.append(f"$I^2$ (\\%) & {_f(h['i2'], 1)} \\\\")
    out.append(f"$Q$ (df); $p$ & {_f(h['q'])} ({h['q_df']}); {_p(h['q_p_value'])} \\\\")
    out.append(
        f"Common-effect estimate ({_tex(scale)}) [{level}\\% CI] & {_f(fe['estimate'], 3)} "
        f"[{_f(fe['ci_lower'], 3)}, {_f(fe['ci_upper'], 3)}] \\\\"
    )
    if "skipped" not in e and e:
        out.append(f"Egger intercept (SE); $p$ & {_f(e['intercept'])} ({_f(e['se'])}); {_p(e['p_value'])} \\\\")
    if "skipped" not in tf and tf:
        out.append(
            f"Trim and fill: studies filled; estimate ({_tex(scale)}) & {tf['k0']}; {_f(tf['estimate'], 3)} "
            f"[{_f(tf['ci_lower'], 3)}, {_f(tf['ci_upper'], 3)}] \\\\"
        )
    write_text(ws / TABLE_RESULTS, _tabular("lr", "Statistic & Value", out))


# ── the draft ───────────────────────────────────────────────────────────────

_INPUT = re.compile(r"\\input\{([^}]+)\}")
_GRAPHIC = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_CITE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]+)\}")


def draft_problems(ws: Path) -> list[str]:
    """The review's draft includes the computed tables and figures and cites every included study."""
    ws = Path(ws)
    draft = ws / "paper_draft.tex"
    if not draft.is_file():
        return ["paper_draft.tex is missing"]
    text = re.sub(r"(?<!\\)%[^\n]*", "", draft.read_text(encoding="utf-8", errors="replace"))
    try:
        results = json.loads((ws / RESULTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{RESULTS} is missing: the synthesis has not run"]
    inputs = {Path(m.strip()).with_suffix(".tex").as_posix() for m in _INPUT.findall(text)}
    graphics = {Path(m.strip()).name for m in _GRAPHIC.findall(text)}
    graphics |= {g + ".pdf" for g in list(graphics) if not g.endswith(".pdf")}
    want_tables = [TABLE_FLOW, TABLE_STUDIES] + ([] if results.get("narrative_only") else [TABLE_RESULTS])
    want_figs = [FIG_PRISMA] + ([] if results.get("narrative_only") else [FIG_FOREST, FIG_FUNNEL])
    problems = []
    missing_t = [t for t in want_tables if t not in inputs]
    if missing_t:
        problems.append("the draft must include " + ", ".join(f"\\input{{{t}}}" for t in missing_t))
    missing_f = [f for f in want_figs if f not in graphics]
    if missing_f:
        problems.append("the draft must include the figure(s) " + ", ".join(missing_f))
    if results.get("narrative_only") and TABLE_RESULTS in inputs:
        problems.append("the studies were not pooled (too few): the draft cannot include a pooled-results table")
    try:
        keys = json.loads((ws / REFERENCES_FILE).read_text(encoding="utf-8")).get("studies", {})
    except (OSError, ValueError):
        keys = {}
    cited = {k.strip() for m in _CITE.findall(text) for k in m.split(",")}
    uncited = [k for sid, k in keys.items() if k not in cited]
    if uncited:
        problems.append(f"the draft must cite every included study; not cited: {', '.join(uncited[:10])}")
    return problems


# ── the exported study (e2er verify) ────────────────────────────────────────


def export_check(ws: Path) -> Verdict:
    """The method checks again on an exported study (full texts are not exported).

    The effects in meta_studies.csv are the extraction's, every extracted number
    is printed in the quote that cites it (a quote from an abstract is in the
    record's abstract), the extraction check traced every number, and each
    study's yi and vi follow from its extracted statistics.
    """
    import csv

    from .stats import EffectError, effect_on_scale

    ws = Path(ws)
    try:
        protocol = load_protocol(ws)
        results = json.loads((ws / RESULTS).read_text(encoding="utf-8"))
        raw = ex.load_extraction(ws)
        with (ws / ex.STUDIES_CSV).open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except (ProtocolError, OSError, ValueError) as e:
        return _fail(f"the exported study cannot be checked: {e}")
    problems: list[str] = []
    measure = protocol["effect_measure"]
    by_id = {s["id"]: s for s in ex.included(raw)}
    studies = {s["id"]: s for s in results.get("studies") or []}
    abstracts: dict[str, str] = {}
    if (ws / se.RECORDS_FILE).is_file():
        abstracts = {r["id"]: r.get("abstract") or "" for r in sc.load_records(ws)}
    for row in rows:
        sid = row["id"]
        effect = {k: float(row[k]) for k in (*ex.EFFECT_NUMBERS, "ci_level") if (row.get(k) or "").strip()}
        extracted = (by_id.get(sid) or {}).get("effect") or {}
        for k, v in effect.items():
            if k != "ci_level" and ex._num(extracted.get(k)) != v:
                problems.append(f"{sid}: meta_studies.csv has {k} = {v:g}, extraction.json {extracted.get(k)}")
        try:
            yi, vi, _ = effect_on_scale(effect, measure)
        except EffectError as e:
            problems.append(f"{sid}: {e}")
            continue
        s = studies.get(sid)
        if s is None or abs(s["yi"] - yi) > 1e-9 * max(1.0, abs(yi)) or abs(s["vi"] - vi) > 1e-12 + 1e-9 * vi:
            problems.append(f"{sid}: yi and vi in the results do not follow from the extracted statistics")
    numbers = 0
    for sid, s in by_id.items():
        sources = s.get("sources") or {}
        for path in [f"effect.{k}" for k in ex.EFFECT_NUMBERS] + list(ex.STUDY_NUMBERS):
            value = ex._num(ex._get(s, path))
            if value is None:
                continue
            numbers += 1
            src = sources.get(path) or {}
            quote = str(src.get("quote") or "")
            if not ex.printed(value, quote):
                problems.append(f"{sid} {path} = {value:g} is not printed in its quote")
            elif s.get("source_text") == "abstract" and abstracts and not ex.find_quote(quote, abstracts.get(sid, "")):
                problems.append(f"{sid} {path}: the quote is not in the record's abstract")
    trace_file = ws / ex.CHECK_FILE
    if trace_file.is_file():
        rep = json.loads(trace_file.read_text(encoding="utf-8"))
        if rep.get("untraced"):
            problems.append(f"the run's extraction check left {rep['untraced']} number(s) untraced")
    else:
        problems.append(f"{ex.CHECK_FILE} is missing: the run's trace of the extracted numbers")
    if problems:
        return _fail(*problems)
    return Verdict(passed=True, stats={"studies": len(rows), "numbers_in_quotes": numbers})
