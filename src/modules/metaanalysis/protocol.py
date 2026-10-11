"""The review protocol (``review_protocol.json``): what the protocol designer writes and the steps read.

The protocol fixes, before any record is screened, the question, the
eligibility criteria (each with an id the screening and extraction cite), the
searches, the outcome, the effect measure, the synthesis and the risk-of-bias
tool. Its schema is in the skill ``methods/meta-analysis``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .stats import MEASURES, TAU2_METHODS

PROTOCOL_FILE = "review_protocol.json"
FRAMEWORKS = ("PICO", "PECO", "PICOS", "SPIDER", "PEO", "other")
DATABASES = ("openalex", "crossref")
SEARCH_IN = ("title_abstract", "title", "all")
_CRITERION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,15}$")
#: The fewest studies a protocol may set for pooling (two studies give no heterogeneity estimate worth stating).
MIN_POOLING_FLOOR = 2


class ProtocolError(ValueError):
    """A protocol the steps cannot use."""


def _str(v: Any) -> str:
    return str(v).strip() if isinstance(v, str) else ""


def protocol_problems(raw: Any) -> list[str]:
    """Everything wrong with a parsed protocol, as sentences (empty when usable)."""
    if not isinstance(raw, dict):
        return [f"{PROTOCOL_FILE} must be a JSON object"]
    p: list[str] = []
    if not _str(raw.get("question")):
        p.append("`question` is missing: the review question in one sentence")
    if raw.get("framework") not in FRAMEWORKS:
        p.append(f"`framework` must be one of {', '.join(FRAMEWORKS)}")
    elements = raw.get("elements")
    if not isinstance(elements, dict) or not any(_str(v) for v in elements.values()):
        p.append("`elements` must name the parts of the question (e.g. population, exposure, comparison, outcome)")

    elig = raw.get("eligibility")
    ids: set[str] = set()
    if not isinstance(elig, dict):
        p.append("`eligibility` must hold `include` and `exclude` criteria lists")
    else:
        for side in ("include", "exclude"):
            items = elig.get(side)
            if not isinstance(items, list) or not items:
                p.append(f"`eligibility.{side}` must list at least one criterion")
                continue
            for i, c in enumerate(items):
                cid = _str((c or {}).get("id")) if isinstance(c, dict) else ""
                if not _CRITERION_ID.match(cid) or not _str((c or {}).get("criterion")):
                    p.append(f"`eligibility.{side}[{i}]` needs an `id` (e.g. I1, E2) and the `criterion` in words")
                    continue
                if cid in ids:
                    p.append(f"criterion id {cid} is used twice")
                ids.add(cid)

    dbs = raw.get("databases") or ["openalex"]
    if not isinstance(dbs, list) or not dbs or any(d not in DATABASES for d in dbs):
        p.append(f"`databases` must list one or more of {', '.join(DATABASES)}")
    searches = raw.get("searches")
    if not isinstance(searches, list) or not searches:
        p.append("`searches` must list at least one search (name, query)")
    else:
        names: set[str] = set()
        for i, s in enumerate(searches):
            if not isinstance(s, dict):
                p.append(f"`searches[{i}]` must be an object")
                continue
            name, query = _str(s.get("name")), _str(s.get("query"))
            if not name or not all(ch.isalnum() or ch in "-_" for ch in name):
                p.append(f"`searches[{i}].name` must be letters, digits, - or _")
            elif name in names:
                p.append(f"search name {name} is used twice")
            names.add(name)
            if not query:
                p.append(f"`searches[{i}].query` is missing")
            elif "," in query:
                p.append(f"`searches[{i}].query` may not contain commas; join terms with OR or AND")
            if s.get("search_in", "title_abstract") not in SEARCH_IN:
                p.append(f"`searches[{i}].search_in` must be one of {', '.join(SEARCH_IN)}")
            for key in ("from_year", "to_year"):
                y = s.get(key)
                if y is not None and (isinstance(y, bool) or not isinstance(y, int) or not 1800 <= y <= 2100):
                    p.append(f"`searches[{i}].{key}` must be a year")
    outcome = raw.get("outcome")
    if not isinstance(outcome, dict) or not _str(outcome.get("name")):
        p.append("`outcome` must name the outcome (`name`) and how it is measured (`description`)")
    if raw.get("effect_measure") not in MEASURES:
        p.append(f"`effect_measure` must be one of {', '.join(MEASURES)}")
    if not _str(raw.get("effect_direction")):
        p.append("`effect_direction` must say what a positive effect means")
    syn = raw.get("synthesis") or {}
    if not isinstance(syn, dict):
        p.append("`synthesis` must be an object")
    else:
        if syn.get("tau2_method", "REML") not in TAU2_METHODS:
            p.append(f"`synthesis.tau2_method` must be one of {', '.join(TAU2_METHODS)}")
        ms = syn.get("min_studies", 3)
        if isinstance(ms, bool) or not isinstance(ms, int) or ms < MIN_POOLING_FLOOR:
            p.append(f"`synthesis.min_studies` must be a whole number of at least {MIN_POOLING_FLOOR}")
        lvl = syn.get("ci_level", 0.95)
        if isinstance(lvl, bool) or not isinstance(lvl, int | float) or not 0.5 <= float(lvl) < 1:
            p.append("`synthesis.ci_level` must be a share such as 0.95")
    rob = raw.get("risk_of_bias")
    if not isinstance(rob, dict) or not _str(rob.get("tool")):
        p.append("`risk_of_bias` must name the `tool` (e.g. RoB 2, ROBINS-I, Newcastle-Ottawa, JBI) and its `domains`")
    else:
        doms = rob.get("domains")
        if not isinstance(doms, list) or not doms or not all(_str(d) for d in doms):
            p.append("`risk_of_bias.domains` must list the domains judged for every study")
        levels = rob.get("levels", ["low", "some concerns", "high", "unclear"])
        if not isinstance(levels, list) or len(levels) < 2 or not all(_str(x) for x in levels):
            p.append("`risk_of_bias.levels` must list at least two judgements (default: low, some concerns, high)")
    return p


def load_protocol(ws: Path) -> dict[str, Any]:
    """The workspace's protocol, checked; raises ProtocolError with every problem."""
    path = Path(ws) / PROTOCOL_FILE
    if not path.is_file():
        raise ProtocolError(f"{PROTOCOL_FILE} is missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ProtocolError(f"{PROTOCOL_FILE} is not valid JSON: {e}") from e
    problems = protocol_problems(raw)
    if problems:
        raise ProtocolError("; ".join(problems))
    return raw


def criterion_ids(protocol: dict[str, Any]) -> dict[str, str]:
    """Every criterion id -> 'include' or 'exclude'."""
    out: dict[str, str] = {}
    for side in ("include", "exclude"):
        for c in (protocol.get("eligibility") or {}).get(side) or []:
            if isinstance(c, dict) and _str(c.get("id")):
                out[_str(c["id"])] = side
    return out


def synthesis_settings(protocol: dict[str, Any]) -> dict[str, Any]:
    syn = protocol.get("synthesis") or {}
    return {
        "tau2_method": syn.get("tau2_method", "REML"),
        "min_studies": int(syn.get("min_studies", 3)),
        "ci_level": float(syn.get("ci_level", 0.95)),
    }


def rob_levels(protocol: dict[str, Any]) -> list[str]:
    rob = protocol.get("risk_of_bias") or {}
    return [str(x).strip().lower() for x in rob.get("levels", ["low", "some concerns", "high", "unclear"])]
