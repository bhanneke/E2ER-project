"""The extraction: full-text decisions, effect sizes, study characteristics and risk of bias, each number traced.

``extraction.json`` (the study extractor), one entry per record that passed
screening::

    {"studies": [
      {"id": "W123", "decision": "include", "source_text": "full text",
       "label": "Smith 2019", "year": 2019,
       "characteristics": {"design": "cross-sectional", "country": "Spain", "population": "..."},
       "n_total": 412,
       "effect": {"value": 0.31, "n": 412},
       "sources": {"effect.value": {"page": 6, "quote": "grit correlated with GPA (r = .31, p < .001)"},
                   "effect.n": {"page": 4, "quote": "A total of 412 students took part"},
                   "n_total": {"page": 4, "quote": "A total of 412 students took part"}},
       "risk_of_bias": {"domains": {"selection": "low", "measurement": "some concerns"},
                        "overall": "some concerns", "support": "..."}},
      {"id": "W456", "decision": "exclude", "criteria": ["E3"], "reason": "no correlation reported"}
    ]}

The check (``trace``) reads every extracted number back from the text it
cites: the quote must be in the study's full text (``fulltext/<id>.txt``, on
the page given, or anywhere in it with a note) or, for a study read from its
abstract, in the abstract; and the number must be printed in the quote. A
number without a source, a quote the text does not contain, or a quote
without the number stops the run.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from ..literature.review import _match_form, normalize
from .fulltext import LOG_FILE as FULLTEXT_LOG
from .fulltext import read_pages
from .protocol import ProtocolError, load_protocol, rob_levels
from .screening import _criteria, decisions_problems, load_records, to_full_text
from .stats import EffectError, effect_on_scale

EXTRACTION_FILE = "extraction.json"
CHECK_FILE = "extraction_check.json"
CHECK_MD = "extraction_check.md"
STUDIES_CSV = "meta_studies.csv"
ROB_CSV = "risk_of_bias.csv"
PRISMA_FILE = "prisma_counts.json"

#: Extracted numbers that must each cite the passage they were read from.
EFFECT_NUMBERS = ("value", "se", "ci_lower", "ci_upper", "n", "n1", "n2", "mean1", "sd1", "mean2", "sd2")
STUDY_NUMBERS = ("n_total",)
#: A quote shorter than this is no evidence of where a number came from.
MIN_QUOTE_CHARS = 8
CSV_COLUMNS = ("id", "label", "year", "measure", *EFFECT_NUMBERS, "ci_level", "rob_overall")

_NUMBER = re.compile(r"(?<![\w.])[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?(?![\w])")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def numbers_in(text: str) -> list[float]:
    """Every number printed in a passage (unicode minus, thousands separators, leading-dot decimals)."""
    out = []
    t = text.replace("−", "-").replace("–", "-").replace(" ", "").replace(" ", " ")
    for m in _NUMBER.finditer(t):
        s = m.group(0)
        if not s or s in ("-", "+") or not any(ch.isdigit() for ch in s):
            continue
        try:
            out.append(float(s.replace(",", "")))
        except ValueError:
            continue
    return out


def printed(value: float, text: str) -> bool:
    """Is ``value`` one of the numbers printed in ``text`` (a printed -.31 is -0.31; .31 is 0.31)?"""
    for x in numbers_in(text):
        if abs(x - value) <= 1e-9 * max(1.0, abs(value)):
            return True
    return False


def find_quote(quote: str, text: str) -> bool:
    q = normalize(quote).lower()
    hay = normalize(text)
    if q and q in hay.lower():
        return True
    sq, _ = _match_form(q)
    sh, _ = _match_form(hay)
    return bool(sq) and sq in sh


def _get(study: dict[str, Any], path: str) -> Any:
    cur: Any = study
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def load_extraction(ws: Path) -> dict[str, Any]:
    path = Path(ws) / EXTRACTION_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{EXTRACTION_FILE} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def _fulltext_log(ws: Path) -> dict[str, Any]:
    path = Path(ws) / FULLTEXT_LOG
    return json.loads(path.read_text(encoding="utf-8")).get("records", {}) if path.is_file() else {}


def structure_problems(ws: Path) -> list[str]:
    """Schema, coverage, decisions, effects and risk of bias of extraction.json (not the tracing)."""
    ws = Path(ws)
    try:
        protocol = load_protocol(ws)
        records = load_records(ws)
        raw = load_extraction(ws)
        candidates = to_full_text(ws)
    except (ProtocolError, FileNotFoundError, ValueError, KeyError) as e:
        return [str(e)]
    problems, by_id = decisions_problems(raw, candidates, protocol, what=EXTRACTION_FILE, key="studies")
    measure = protocol["effect_measure"]
    domains = [str(d) for d in protocol["risk_of_bias"]["domains"]]
    levels = rob_levels(protocol)
    log = _fulltext_log(ws)
    abstracts = {r["id"]: r.get("abstract") or "" for r in records}
    for sid, s in by_id.items():
        decision = s.get("decision")
        if decision == "unsure":
            problems.append(f"{sid}: after the full text a study is included or excluded, not unsure")
            continue
        src = s.get("source_text")
        if src not in ("full text", "abstract"):
            problems.append(f"{sid}: `source_text` must be 'full text' or 'abstract'")
        elif src == "full text" and (log.get(sid) or {}).get("status") != "ok":
            problems.append(f"{sid}: says it was read from the full text, but fulltext_log.json has none for it")
        elif src == "abstract" and not abstracts.get(sid):
            problems.append(f"{sid}: says it was read from the abstract, but the record has no abstract")
        if decision != "include":
            continue
        if not str(s.get("label") or "").strip():
            problems.append(f"{sid}: an included study needs a `label` (e.g. 'Smith 2019')")
        effect = s.get("effect")
        if effect is None:
            if not str(s.get("no_effect_reason") or "").strip():
                problems.append(
                    f"{sid}: an included study needs an `effect`, or `no_effect_reason` saying why it reports none "
                    "that can be pooled (it is then described, not pooled)"
                )
        elif not isinstance(effect, dict):
            problems.append(f"{sid}: `effect` must be an object")
        else:
            try:
                effect_on_scale(effect, measure)
            except EffectError as e:
                problems.append(f"{sid}: the effect cannot be used as a {measure}: {e}")
        rob = s.get("risk_of_bias")
        if not isinstance(rob, dict) or not isinstance(rob.get("domains"), dict):
            problems.append(f"{sid}: `risk_of_bias` needs `domains` (each protocol domain judged) and `overall`")
            continue
        judged = {str(k): str(v).strip().lower() for k, v in rob["domains"].items()}
        missing = [d for d in domains if d not in judged]
        if missing:
            problems.append(f"{sid}: risk of bias not judged for {', '.join(missing)}")
        bad = sorted({v for v in [*judged.values(), str(rob.get("overall") or "").strip().lower()] if v not in levels})
        if bad:
            problems.append(f"{sid}: risk-of-bias judgement(s) {', '.join(bad)} not among {', '.join(levels)}")
    return problems


def trace(ws: Path) -> dict[str, Any]:
    """Every extracted number read back from the passage it cites. Returns the trace report."""
    ws = Path(ws)
    raw = load_extraction(ws)
    records = {r["id"]: r for r in load_records(ws)}
    log = _fulltext_log(ws)
    rows: list[dict[str, Any]] = []
    for s in raw.get("studies") or []:
        if not isinstance(s, dict) or s.get("decision") != "include":
            continue
        sid = str(s.get("id"))
        sources: dict[str, Any] = s["sources"] if isinstance(s.get("sources"), dict) else {}
        paths = [f"effect.{k}" for k in EFFECT_NUMBERS if _num(_get(s, f"effect.{k}")) is not None]
        paths += [k for k in STUDY_NUMBERS if _num(s.get(k)) is not None]
        pages: dict[int, str] = {}
        if s.get("source_text") == "full text" and (log.get(sid) or {}).get("status") == "ok":
            tf = ws / log[sid]["text_file"]
            pages = read_pages(tf) if tf.is_file() else {}
        abstract = (records.get(sid) or {}).get("abstract") or ""
        for path in paths:
            value = float(_get(s, path))
            row: dict[str, Any] = {"study": sid, "field": path, "value": value, "status": "traced", "note": ""}
            src = sources.get(path)
            if not isinstance(src, dict) or not str(src.get("quote") or "").strip():
                row.update(status="no source", note="no page and quote given")
                rows.append(row)
                continue
            quote = str(src["quote"])
            row["quote"] = quote
            row["page"] = src.get("page")
            if len(normalize(quote)) < MIN_QUOTE_CHARS:
                row.update(status="quote too short", note=f"a quote of at least {MIN_QUOTE_CHARS} characters")
            elif not printed(value, quote):
                row.update(status="number not in quote", note=f"{value:g} is not printed in the quote")
            elif s.get("source_text") == "abstract" or src.get("page") in ("abstract", 0, None) and not pages:
                if not find_quote(quote, abstract):
                    row.update(status="quote not found", note="not in the record's abstract")
                else:
                    row["where"] = "abstract"
            elif not pages:
                row.update(status="no source text", note="no full text in fulltext/ to check against")
            else:
                page = src.get("page")
                if isinstance(page, int) and page in pages and find_quote(quote, pages[page]):
                    row["where"] = f"page {page}"
                else:
                    hit = next((p for p, t in sorted(pages.items()) if find_quote(quote, t)), None)
                    if hit is None:
                        # A quote across a page break.
                        joined = " ".join(t for _, t in sorted(pages.items()))
                        if find_quote(quote, joined):
                            row.update(where="across pages", note="the quote runs across a page break")
                        else:
                            row.update(status="quote not found", note="not in the full text")
                    else:
                        row.update(where=f"page {hit}", note=f"found on page {hit}, not on page {page}")
            rows.append(row)
    failed = [r for r in rows if r["status"] != "traced"]
    return {
        "numbers": len(rows),
        "traced": len(rows) - len(failed),
        "untraced": len(failed),
        "rows": rows,
    }


def trace_problems(report: dict[str, Any]) -> list[str]:
    failed = [r for r in report["rows"] if r["status"] != "traced"]
    if not failed:
        return []
    shown = "; ".join(f"{r['study']} {r['field']} = {r['value']:g}: {r['status']} ({r['note']})" for r in failed[:8])
    return [f"{len(failed)} of {report['numbers']} extracted number(s) do not trace to their source: {shown}"]


def included(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in raw.get("studies") or [] if isinstance(s, dict) and s.get("decision") == "include"]


def studies_csv(raw: dict[str, Any], measure: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for s in included(raw):
        e = s.get("effect")
        if not isinstance(e, dict):
            continue
        rob = s.get("risk_of_bias") or {}
        w.writerow(
            [
                s["id"],
                s.get("label", ""),
                s.get("year") or "",
                measure,
                *[("" if _num(e.get(k)) is None else repr(float(e[k]))) for k in EFFECT_NUMBERS],
                repr(float(e["ci_level"])) if _num(e.get("ci_level")) is not None else "",
                str(rob.get("overall") or ""),
            ]
        )
    return buf.getvalue()


def rob_csv(raw: dict[str, Any], domains: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "label", *domains, "overall"])
    for s in included(raw):
        rob = s.get("risk_of_bias") or {}
        d = rob.get("domains") or {}
        w.writerow([s["id"], s.get("label", ""), *[d.get(x, "") for x in domains], rob.get("overall", "")])
    return buf.getvalue()


def prisma_counts(ws: Path, raw: dict[str, Any]) -> dict[str, Any]:
    """The PRISMA 2020 flow counts, from the search log, the screening, the full-text log and the extraction."""
    ws = Path(ws)
    log = json.loads((ws / "search_log.json").read_text(encoding="utf-8"))
    from .screening import screened

    decisions = screened(ws)
    ft = json.loads((ws / FULLTEXT_LOG).read_text(encoding="utf-8")) if (ws / FULLTEXT_LOG).is_file() else {}
    ft_records = ft.get("records", {})
    studies = [s for s in raw.get("studies") or [] if isinstance(s, dict)]
    reasons: dict[str, int] = {}
    for s in studies:
        if s.get("decision") == "exclude":
            for c in _criteria(s) or ["(no criterion)"]:
                reasons[c] = reasons.get(c, 0) + 1
    screen_reasons: dict[str, int] = {}
    for d in decisions.values():
        if d.get("decision") == "exclude":
            for c in _criteria(d) or ["(no criterion)"]:
                screen_reasons[c] = screen_reasons.get(c, 0) + 1
    inc = included(raw)
    pooled = [s for s in inc if isinstance(s.get("effect"), dict)]
    sought = sum(1 for d in decisions.values() if d.get("decision") in ("include", "unsure"))
    not_retrieved = sum(1 for v in ft_records.values() if v.get("status") != "ok")
    return {
        "identified": {
            "by_database": log.get("identified_by_database", {}),
            "total": log["identified"],
        },
        "duplicates_removed": log["duplicates_removed"],
        "screened": log["records"],
        "excluded_on_title_abstract": sum(1 for d in decisions.values() if d.get("decision") == "exclude"),
        "excluded_on_title_abstract_by_criterion": dict(sorted(screen_reasons.items())),
        "sought_for_full_text": sought,
        "full_text_not_retrieved": not_retrieved,
        "assessed_on_full_text": sought - not_retrieved,
        "assessed_on_abstract_only": sum(
            1
            for s in studies
            if s.get("source_text") == "abstract" and (ft_records.get(s.get("id")) or {}).get("status") != "ok"
        ),
        "excluded_at_eligibility": sum(1 for s in studies if s.get("decision") == "exclude"),
        "excluded_at_eligibility_by_criterion": dict(sorted(reasons.items())),
        "included_in_review": len(inc),
        "included_in_meta_analysis": len(pooled),
    }
