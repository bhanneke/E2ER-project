"""Title and abstract screening: the screener's decisions, checked, and the sample the researcher reads.

``screening.json`` (the study screener)::

    {"decisions": [
        {"id": "W123", "decision": "include" | "exclude" | "unsure",
         "criteria": ["E2"], "reason": "a review, not a primary study"}
    ]}

Every record of ``records.json`` has exactly one decision; an exclusion names
at least one criterion of the protocol (an exclusion criterion it meets, or an
inclusion criterion it fails) and gives the reason in words. Records judged
``unsure`` go on to the full-text assessment with the included ones.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from .protocol import criterion_ids
from .search import RECORDS_FILE

SCREENING_FILE = "screening.json"
CHECK_FILE = "screening_check.json"
SAMPLE_MD = "screening_sample.md"
DECISIONS = ("include", "exclude", "unsure")


def load_records(ws: Path) -> list[dict[str, Any]]:
    path = Path(ws) / RECORDS_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{RECORDS_FILE} is missing: the search has not run")
    return json.loads(path.read_text(encoding="utf-8"))["records"]


def _criteria(d: dict[str, Any]) -> list[str]:
    raw = d.get("criteria", d.get("criterion"))
    if isinstance(raw, str):
        raw = [raw]
    return [str(c).strip() for c in raw or [] if str(c).strip()]


def decisions_problems(
    raw: Any, record_ids: list[str], protocol: dict[str, Any], *, what: str = SCREENING_FILE, key: str = "decisions"
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Problems of a decisions file against the records it must cover; and the decisions by id."""
    if not isinstance(raw, dict) or not isinstance(raw.get(key), list):
        return [f"{what} must be an object with a `{key}` list"], {}
    known = set(record_ids)
    crit = criterion_ids(protocol)
    problems: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    dup: list[str] = []
    unknown: list[str] = []
    no_reason: list[str] = []
    bad_crit: list[str] = []
    bad_decision: list[str] = []
    for d in raw[key]:
        if not isinstance(d, dict):
            problems.append(f"every entry of `{key}` must be an object")
            continue
        rid = str(d.get("id") or "").strip()
        if rid not in known:
            unknown.append(rid or "(no id)")
            continue
        if rid in by_id:
            dup.append(rid)
            continue
        by_id[rid] = d
        decision = d.get("decision")
        if decision not in DECISIONS:
            bad_decision.append(rid)
            continue
        if decision == "exclude":
            cs = _criteria(d)
            if not cs or not str(d.get("reason") or "").strip():
                no_reason.append(rid)
            elif any(c not in crit for c in cs):
                bad_crit.append(f"{rid} ({', '.join(c for c in cs if c not in crit)})")
    missing = [r for r in record_ids if r not in by_id]
    if missing:
        problems.append(f"{len(missing)} record(s) have no decision: {', '.join(missing[:10])}")
    if unknown:
        problems.append(f"{len(unknown)} decision(s) name no record of the search: {', '.join(unknown[:10])}")
    if dup:
        problems.append(f"record(s) decided twice: {', '.join(dup[:10])}")
    if bad_decision:
        problems.append(f"decision must be include, exclude or unsure: {', '.join(bad_decision[:10])}")
    if no_reason:
        problems.append(
            f"{len(no_reason)} exclusion(s) without a criterion id and a reason: {', '.join(no_reason[:10])}"
        )
    if bad_crit:
        problems.append(
            f"exclusion(s) citing criteria the protocol does not define ({', '.join(sorted(crit))} are defined): "
            + ", ".join(bad_crit[:10])
        )
    return problems, by_id


def screening_problems(ws: Path) -> list[str]:
    """What is wrong with screening.json (empty when every record is decided with its reasons)."""
    from .protocol import ProtocolError, load_protocol

    ws = Path(ws)
    try:
        protocol = load_protocol(ws)
        records = load_records(ws)
    except (ProtocolError, FileNotFoundError, ValueError, KeyError) as e:
        return [str(e)]
    path = ws / SCREENING_FILE
    if not path.is_file():
        return [f"{SCREENING_FILE} is missing"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{SCREENING_FILE} is not valid JSON: {e}"]
    problems, _ = decisions_problems(raw, [r["id"] for r in records], protocol)
    return problems


def screened(ws: Path) -> dict[str, dict[str, Any]]:
    """The screening decisions by record id (the file is assumed checked)."""
    raw = json.loads((Path(ws) / SCREENING_FILE).read_text(encoding="utf-8"))
    return {str(d["id"]): d for d in raw["decisions"] if isinstance(d, dict) and d.get("id")}


def to_full_text(ws: Path) -> list[str]:
    """Records that go on to the full-text assessment (included or unsure), in record order."""
    decisions = screened(ws)
    return [
        r["id"] for r in load_records(ws) if (decisions.get(r["id"]) or {}).get("decision") in ("include", "unsure")
    ]


def sample(records: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], size: int) -> dict[str, list[str]]:
    """The records the researcher reads: every inclusion and unsure one, and a seeded sample of exclusions."""
    excluded = [r["id"] for r in records if decisions[r["id"]]["decision"] == "exclude"]
    seed = int(hashlib.sha256("|".join(r["id"] for r in records).encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    picked = sorted(rng.sample(excluded, min(size, len(excluded)))) if excluded else []
    return {
        "include": [r["id"] for r in records if decisions[r["id"]]["decision"] == "include"],
        "unsure": [r["id"] for r in records if decisions[r["id"]]["decision"] == "unsure"],
        "exclude_sample": picked,
        "seed": [str(seed)],
    }


def sample_md(records: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], picked: dict[str, list[str]]) -> str:
    by_id = {r["id"]: r for r in records}
    counts = {k: sum(1 for d in decisions.values() if d.get("decision") == k) for k in DECISIONS}
    out = [
        "# Screening: what to check",
        "",
        f"{len(records)} records screened on title and abstract: {counts['include']} included, "
        f"{counts['unsure']} unsure (both go on to the full text), {counts['exclude']} excluded.",
        "",
        "Read the unsure records and the sample of exclusions below. To change a decision, edit "
        "`screening.json` (decision, criteria, reason) and approve; the check runs again.",
    ]

    def block(title: str, ids: list[str]) -> None:
        out.extend(["", f"## {title} ({len(ids)})"])
        for rid in ids:
            r, d = by_id[rid], decisions[rid]
            crit = ", ".join(_criteria(d))
            out.append(f"\n### {rid}: {r.get('title') or '(no title)'} ({r.get('year') or 'n.d.'})")
            out.append(f"Decision: **{d['decision']}**" + (f" ({crit})" if crit else "") + f". {d.get('reason') or ''}")
            abstract = (r.get("abstract") or "").strip()
            out.append(f"> {abstract[:900]}{'...' if len(abstract) > 900 else ''}" if abstract else "> (no abstract)")

    block("Unsure", picked["unsure"])
    block("Sample of exclusions", picked["exclude_sample"])
    block("Included", picked["include"])
    return "\n".join(out) + "\n"
