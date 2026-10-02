"""``reproduction_report.md`` must say what ``reproduction_report.json`` says.

The comparer (a model) writes two files: the JSON, which the reproduction check
recomputes number by number, and the Markdown report the researcher reads. In
the replication demonstration the Markdown said "16 targets" and "2 not
reproduced" while the JSON, and the check, had 17 and 3; nothing compared the
two. This module closes that gap in two ways:

1. **e2er writes the summary.** The counts per level and label, and the
   environment of the rerun, are rendered by code from the JSON (and the
   sandbox log) into a delimited section of the Markdown
   (:func:`render_summary`, :func:`write_summary`). The comparer does not
   write counts or installed versions; a hand-edited section no longer
   matches its rendering and fails.
2. **The prose is checked against the JSON** (:func:`markdown_problems`):
   - count tables (rows headed by a label or "Total") per level;
   - count statements in sentences that name the level ("16 level-1
     targets", "14 of 18 level-1 targets", "three targets failed at level 1");
   - the label stated for a number the Markdown names, where the row or list
     item can be matched to exactly one compared number of the JSON (by its
     target id, or by its published and reproduced values);
   - package versions: a version stated right after a package name must be
     the one the JSON's environment block, or the sandbox log, records.

Statements the parser cannot tie to a level or to one number are left alone,
so the check fails only on a contradiction it can name.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .replication import LEVELS, TARGET_LEVELS

MD_FILE = "reproduction_report.md"
JSON_FILE = "reproduction_report.json"

BEGIN = "<!-- e2er:summary begin: written by e2er from reproduction_report.json; edits here fail the check -->"
END = "<!-- e2er:summary end -->"

_LEVEL_TITLES = {1: "the package's own result files, rebuilt", 2: "the numbers printed in the paper"}

# ── what the JSON says ────────────────────────────────────────────────────────


@dataclass
class Entry:
    """One compared number of reproduction_report.json."""

    tier: int
    target_id: str
    published: float | None
    reproduced: float | None
    label: str
    result_id: str = ""
    result_level: str = ""


@dataclass
class Facts:
    entries: list[Entry] = field(default_factory=list)
    numbers: dict[int, Counter[str]] = field(default_factory=dict)
    results: dict[int, Counter[str]] = field(default_factory=dict)
    installed: dict[str, str] = field(default_factory=dict)  # the report's environment block
    log_installed: dict[str, str] = field(default_factory=dict)  # everything the sandbox installed
    declared: dict[str, str] = field(default_factory=dict)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def facts(report: dict[str, Any], log: dict[str, Any] | None = None) -> Facts:
    """The compared numbers, their labels and counts, and the versions, from the JSON (and the log)."""
    f = Facts(numbers={t: Counter() for t in TARGET_LEVELS}, results={t: Counter() for t in TARGET_LEVELS})
    for res in report.get("results") or []:
        if not isinstance(res, dict) or res.get("target_level") not in TARGET_LEVELS:
            continue
        tier = int(res["target_level"])
        level = res.get("level")
        if level in LEVELS:
            f.results[tier][level] += 1
        for comp in res.get("comparisons") or []:
            if not isinstance(comp, dict):
                continue
            label = comp.get("label") if comp.get("label") in LEVELS else level
            if level == "could_not_run":
                label = "could_not_run"
            if label not in LEVELS:
                continue
            f.numbers[tier][label] += 1
            f.entries.append(
                Entry(
                    tier,
                    str(comp.get("target_id") or ""),
                    _num(comp.get("published")),
                    _num(comp.get("reproduced")),
                    label,
                    str(res.get("id") or ""),
                    str(level or ""),
                )
            )
    env = report.get("environment")
    if isinstance(env, dict) and isinstance(env.get("installed"), dict):
        f.installed = {str(k): str(v) for k, v in env["installed"].items() if isinstance(v, str | int | float)}
    log = log or {}
    inst = (log.get("install") or {}).get("installed") if isinstance(log.get("install"), dict) else None
    if isinstance(inst, dict):
        f.log_installed = {str(k): str(v) for k, v in inst.items() if isinstance(v, str | int | float)}
    for d in log.get("declared_versions") or []:
        if isinstance(d, dict) and d.get("name") and d.get("declared"):
            f.declared[str(d["name"])] = str(d["declared"])
    return f


# ── the summary e2er writes ───────────────────────────────────────────────────


def render_summary(report: dict[str, Any], log: dict[str, Any] | None = None) -> str:
    """The summary section of reproduction_report.md, from the JSON and the sandbox log, markers included."""
    f = facts(report, log)
    log = log or {}
    lines = [
        BEGIN,
        "## Counts and environment",
        "",
        "Written by e2er from `reproduction_report.json` and `sandbox_log.json`. Each compared number is "
        "counted once, under its label; a result (one exhibit at one level) takes its worst number's label.",
        "",
    ]
    for tier in TARGET_LEVELS:
        n = f.numbers[tier]
        r = f.results[tier]
        total_n, total_r = sum(n.values()), sum(r.values())
        lines.append(f"### Level {tier}: {_LEVEL_TITLES[tier]}")
        lines.append("")
        if not total_n and not total_r:
            lines += ["No number compared at this level.", ""]
            continue
        lines += [
            f"{total_n} compared {'number' if total_n == 1 else 'numbers'} in {total_r} "
            f"{'result' if total_r == 1 else 'results'}.",
            "",
            "| Label | Numbers | Results |",
            "|---|---:|---:|",
        ]
        lines += [f"| {lv} | {n.get(lv, 0)} | {r.get(lv, 0)} |" for lv in LEVELS]
        lines += [f"| Total | {total_n} | {total_r} |", ""]
    unassessed = [u for u in report.get("unassessed") or [] if isinstance(u, dict) and u.get("target_id")]
    if unassessed:
        ids = ", ".join(f"`{u['target_id']}`" for u in unassessed[:20])
        more = f" and {len(unassessed) - 20} more" if len(unassessed) > 20 else ""
        lines += [f"Not assessed, each with its reason in `reproduction_report.json`: {ids}{more}.", ""]
    raw_env = report.get("environment")
    env: dict[str, Any] = raw_env if isinstance(raw_env, dict) else {}
    env_lines: list[str] = []
    snap = env.get("snapshot") if isinstance(env.get("snapshot"), dict) else None
    if snap and (snap.get("date") or snap.get("url")):
        env_lines.append(
            f"- Package snapshot: {snap.get('date') or '—'}" + (f" ({snap['url']})" if snap.get("url") else "")
        )
    if env.get("platform"):
        env_lines.append(f"- Platform: {env['platform']}")
    if log.get("image"):
        digest = str(log.get("image_digest") or "")
        env_lines.append(f"- Image: {log['image']}" + (f" ({digest})" if digest else ""))
    if f.installed:
        shown = ", ".join(f"{k} {v}" for k, v in f.installed.items())
        env_lines.append(f"- Installed versions of the packages the report names: {shown}")
    if f.log_installed:
        env_lines.append(
            f"- All {len(f.log_installed)} installed packages, dependencies included: "
            "`reproduction_check.json` → `environment.installed`"
        )
    if env_lines:
        lines += ["### Environment of the rerun", "", *env_lines, ""]
    lines.append(END)
    return "\n".join(lines)


_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def split_summary(text: str) -> tuple[str | None, str]:
    """(the e2er summary section or None, the rest of the text with the section removed)."""
    m = _BLOCK.search(text)
    if not m:
        return None, text
    return m.group(0), text[: m.start()] + text[m.end() :]


def with_summary(text: str, block: str) -> str:
    """The Markdown with ``block`` in place of its summary section, or before its first ``##`` heading."""
    if _BLOCK.search(text):
        return _BLOCK.sub(lambda _m: block, text, count=1)
    m = re.search(r"^## ", text, re.M)
    if m:
        return text[: m.start()] + block + "\n\n" + text[m.start() :]
    return text.rstrip("\n") + "\n\n" + block + "\n"


# ── reading the prose ─────────────────────────────────────────────────────────

_DASH_MINUS = re.compile(r"(?<![\w.])[–−](?=\.?\d)")
_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?(?![\w.]*\d)")
_LEVEL = re.compile(r"\blevel[\s_-]*(1|2|one|two)\b", re.I)
_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_N = r"(?:\d+|" + "|".join(_WORDS) + r")"


def _int(tok: str) -> int:
    return int(tok) if tok.isdigit() else _WORDS[tok.lower()]


def _tier(tok: str) -> int:
    return 1 if tok.lower() in ("1", "one") else 2


def _plain(text: str) -> str:
    """Lower case, markup and underscores gone, one space between words."""
    t = re.sub(r"[*`]", "", text).replace("_", " ").replace("-", " ").lower()
    return re.sub(r"\s+", " ", t).strip(" :.;,")


_CELL_LABELS = {
    "reproduced": "reproduced",
    "reproduced exactly": "reproduced",
    "exactly reproduced": "reproduced",
    "reproduced minor": "reproduced_minor",
    "reproduced with minor differences": "reproduced_minor",
    "reproduced with minor difference": "reproduced_minor",
    "reproduced with a minor difference": "reproduced_minor",
    "minor differences": "reproduced_minor",
    "minor difference": "reproduced_minor",
    "not reproduced": "not_reproduced",
    "could not run": "could_not_run",
    "could not be run": "could_not_run",
}


def _cell_label(text: str) -> str | None:
    return _CELL_LABELS.get(_plain(text))


def _heading_label(text: str) -> str | None:
    """The one label a heading names ("Not Reproduced — Details"), or None."""
    t = _plain(text)
    found = set()
    for pat, lab in (
        (r"could not (be )?run", "could_not_run"),
        (r"not reproduced", "not_reproduced"),
        (r"reproduced (with (a )?)?minor( differences?)?|minor differences?", "reproduced_minor"),
    ):
        if re.search(pat, t):
            found.add(lab)
            t = re.sub(pat, " ", t)
    if re.search(r"\breproduced\b", t):
        found.add("reproduced")
    return found.pop() if len(found) == 1 else None


def _tiers_in(text: str) -> set[int]:
    return {_tier(m.group(1)) for m in _LEVEL.finditer(text)}


@dataclass
class Record:
    """A table row or a list item (with its continuation lines) of the prose."""

    text: str
    cells: list[str] | None
    tier: int | None
    heading_label: str | None
    line: str
    block: int = -1  # the section (heading or bold title line) the record belongs to


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    tier: int | None
    lead: str


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_rule(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", line.strip()))


@dataclass
class Block:
    """A section of the prose: a heading or a line that is bold as a whole ("**Table 5: …**")."""

    title: str
    tier: int | None


_BOLD_TITLE = re.compile(r"^\*\*([^*]+)\*\*\s*$")


def _parse(
    text: str, only_tier: int | None
) -> tuple[list[Table], list[Record], list[tuple[str, int | None]], list[Block]]:
    """Tables, records (rows and list items), prose sentences with their level, and the sections."""
    lines = _DASH_MINUS.sub("-", text).splitlines()
    tables: list[Table] = []
    records: list[Record] = []
    prose: list[tuple[str, int | None]] = []
    blocks: list[Block] = []
    heads: list[tuple[int, int | None, str | None]] = []  # (depth, tier, label)
    last_text = ""
    i = 0

    def open_block(title: str) -> None:
        tier, _ = ctx()
        own = _tiers_in(title)
        blocks.append(Block(title, next(iter(own)) if len(own) == 1 else (tier or only_tier)))

    def ctx() -> tuple[int | None, str | None]:
        tier = next((t for _, t, _ in reversed(heads) if t is not None), None)
        label = heads[-1][2] if heads else None
        return tier, label

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        h = re.match(r"^(#{1,6})\s+(.*)", s)
        if h:
            depth = len(h.group(1))
            while heads and heads[-1][0] >= depth:
                heads.pop()
            tiers = _tiers_in(h.group(2))
            heads.append((depth, tiers.pop() if len(tiers) == 1 else None, _heading_label(h.group(2))))
            prose.append((h.group(2), ctx()[0] or only_tier))
            open_block(h.group(2))
            last_text = h.group(2)
            i += 1
            continue
        if _BOLD_TITLE.match(s):
            open_block(_BOLD_TITLE.match(s).group(1))  # type: ignore[union-attr]
            prose.append((_BOLD_TITLE.match(s).group(1), ctx()[0] or only_tier))  # type: ignore[union-attr]
            last_text = s
            i += 1
            continue
        if s.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            rows = [_cells(b) for b in block if not _is_rule(b)]
            has_header = len(block) > 1 and _is_rule(block[1])
            header = rows[0] if has_header else []
            body = rows[1:] if has_header else rows
            lead_tiers = _tiers_in(last_text)
            tier, label = ctx()
            if len(lead_tiers) == 1:
                tier = next(iter(lead_tiers))
            tables.append(Table(header, body, tier if tier is not None else only_tier, last_text))
            for raw, cells in zip([b for b in block if not _is_rule(b)][1 if has_header else 0 :], body, strict=False):
                row_tiers = _tiers_in(raw)
                records.append(
                    Record(
                        raw,
                        cells,
                        (next(iter(row_tiers)) if len(row_tiers) == 1 else tier) or only_tier,
                        label,
                        raw.strip(),
                        len(blocks) - 1,
                    )
                )
            continue
        item = re.match(r"^(\s*)(?:[-*+]|\d+[.)])\s+", line)
        if item:
            indent = len(item.group(1))
            j = i + 1
            while j < len(lines) and lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) > indent:
                j += 1
            chunk = "\n".join(lines[i:j])
            tier, label = ctx()
            own = _tiers_in(chunk)
            records.append(
                Record(
                    chunk,
                    None,
                    (next(iter(own)) if len(own) == 1 else tier) or only_tier,
                    label,
                    s,
                    len(blocks) - 1,
                )
            )
        if s:
            prose.append((re.sub(r"^(?:[-*+>]|\d+[.)])\s+", "", s), ctx()[0] or only_tier))
            last_text = s
        i += 1
    sentences = [(x, t) for p, t in prose for x in re.split(r"(?<=[.;!?])\s+", p) if x.strip()]
    return tables, records, sentences, blocks


# ── the checks ────────────────────────────────────────────────────────────────


def _counts(f: Facts, tier: int | None, basis: str) -> dict[str, int]:
    src = f.numbers if basis == "numbers" else f.results
    tiers = [tier] if tier is not None else list(TARGET_LEVELS)
    c: Counter[str] = Counter()
    for t in tiers:
        c.update(src[t])
    out = {lv: c.get(lv, 0) for lv in LEVELS}
    out["total"] = sum(c.values())
    return out


def _where(tier: int | None) -> str:
    return f"level-{tier} " if tier is not None else ""


def _quote(text: str, limit: int = 90) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    return f'"{t[:limit]}{"…" if len(t) > limit else ""}"'


def _table_problems(tables: list[Table], f: Facts) -> list[str]:
    out: list[str] = []
    for tab in tables:
        labelled: list[tuple[list[str], str]] = []
        for r in tab.rows:
            lab = (_cell_label(r[0]) or ("total" if _plain(r[0]) in ("total", "all") else None)) if r else None
            if lab:
                labelled.append((r, lab))
        if len(labelled) < 2:
            continue
        width = max(len(r) for r, _ in labelled)
        for col in range(1, width):
            claimed: dict[str, int] = {}
            for r, lab in labelled:
                m = re.match(r"^\**\s*(\d+)\b", r[col]) if col < len(r) else None
                if m:
                    claimed[lab] = int(m.group(1))
            if not claimed:
                continue
            head = _plain(tab.header[col]) if col < len(tab.header) else ""
            if re.search(r"result|exhibit|table", head):
                bases = ["results"]
            elif re.search(r"number|target|value|estimate|comparison", head):
                bases = ["numbers"]
            else:
                bases = ["numbers", "results"]
            if any(all(_counts(f, tab.tier, b)[k] == v for k, v in claimed.items()) for b in bases):
                continue
            want = _counts(f, tab.tier, bases[0])
            noun = "results" if bases[0] == "results" else "compared numbers"
            for k, v in claimed.items():
                if want[k] != v:
                    what = "in total" if k == "total" else k
                    lead = _quote(tab.lead or " | ".join(tab.header))
                    out.append(
                        f"{MD_FILE}'s {_where(tab.tier)}table ({lead}) says {v} {what}, "
                        f"{JSON_FILE} has {want[k]} ({noun})"
                    )
    return out


_EXCLUDE_BEFORE = re.compile(
    r"(?:\b(?:level|table|figure|fig|column|col|panel|row|exhibit|step|model|spec|specification|section|page|"
    r"appendix|equation|eq|version|stage|phase)\b|[-_#])\s*$",
    re.I,
)
_COUNT = re.compile(
    r"(?<![\w.-])(?P<n>" + _N + r")(?:\s+of\s+(?:the\s+|all\s+)?(?P<m>" + _N + r"))?\s+"
    r"(?P<mid>(?:(?:compared|level[\s_-]*(?:1|2|one|two)|reproduced|assessed)\s+)*)"
    r"(?P<noun>numbers?|targets?|values?)\b",
    re.I,
)
_LABEL_COUNT = re.compile(
    r"(?<![\w.-])(?P<n>" + _N + r")\s+(?P<lab>reproduced_minor|not_reproduced|could_not_run|"
    r"reproduced with (?:a )?minor differences?|not reproduced|could not (?:be )?run|reproduced)\b",
    re.I,
)

#: A count's meaning from the words around it: the set of counts it may equal.
_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    ("could_not_run", re.compile(r"could not (?:be )?run|could_not_run|failed to run|did not run", re.I)),
    ("not_reproduced", re.compile(r"not[ _]reproduced|failed|\bfail|did not reproduce|were not reproduced", re.I)),
    ("reproduced_minor", re.compile(r"\bminor", re.I)),
    ("exact", re.compile(r"\bexact(?:ly)?\b|at full precision", re.I)),
    ("differ", re.compile(r"differ|diverg|deviat|mismatch", re.I)),
    ("matched", re.compile(r"\bmatch|\bagree|\breproduced\b|\bequal", re.I)),
    ("total", re.compile(r"\bacross\b|\bin total\b|\boverall\b|\bin all\b|\bcompared\b|\bassessed\b", re.I)),
]


def _allowed(cls: str, c: dict[str, int]) -> set[int]:
    rep, minor, notr, cnr, tot = (
        c["reproduced"],
        c["reproduced_minor"],
        c["not_reproduced"],
        c["could_not_run"],
        c["total"],
    )
    return {
        "total": {tot},
        "exact": {rep},
        "matched": {rep, rep + minor},
        "reproduced_minor": {minor},
        "not_reproduced": {notr, notr + cnr},
        "could_not_run": {cnr},
        "differ": {notr, minor, minor + notr, tot - rep},
    }[cls]


def _classify(*texts: str) -> str | None:
    for text in texts:
        for cls, pat in _CLASSES:
            if pat.search(text):
                return cls
    return None


def _plausible(c: dict[str, int]) -> set[int]:
    """Every count a sentence can truthfully state about these numbers, whatever it calls them."""
    rep, minor, notr, cnr, tot = (
        c["reproduced"],
        c["reproduced_minor"],
        c["not_reproduced"],
        c["could_not_run"],
        c["total"],
    )
    return {rep, minor, notr, cnr, rep + minor, notr + cnr, minor + notr, minor + notr + cnr, tot}


def _sentence_problems(sentences: list[tuple[str, int | None]], f: Facts) -> list[str]:
    out: list[str] = []
    for sent, context in sentences:
        tiers = _tiers_in(sent)
        for m in _COUNT.finditer(sent):
            if _EXCLUDE_BEFORE.search(sent[: m.start()]):
                continue
            own = _tiers_in(m.group("mid"))
            scope = own or tiers
            if len(scope) > 1:
                continue
            # A sentence that names no level is about the level of its section
            # (or the only level with numbers): "12 of 17 numbers" under
            # "## Level 1" is a level-1 count.
            tier = next(iter(scope)) if scope else context
            if tier is None and not m.group("m"):
                continue
            c = _counts(f, tier, "numbers")
            after = re.split(r"[,;:()—]", sent[m.end() :], maxsplit=1)[0]
            before = sent[: m.start()]
            claims: list[tuple[int, str]] = []
            if m.group("m"):
                # "N of M numbers": M is a total, and N one of the counts there are.
                claims.append((_int(m.group("m")), "total"))
                cls = _classify(m.group("mid") + after, before)
                n = _int(m.group("n"))
                if cls and cls != "total":
                    claims.append((n, cls))
                elif n not in _plausible(c) or n > c["total"]:
                    out.append(
                        f"{MD_FILE} says {n} of {_int(m.group('m'))} {_where(tier)}numbers ({_quote(sent)}), "
                        f"which is none of the counts in {JSON_FILE}"
                    )
            else:
                total_cue = before.rstrip().endswith("(") or re.search(
                    r"\b(?:all|total of|compares|compared|comprises)\s*$", before, re.I
                )
                cls = "total" if total_cue else _classify(m.group("mid") + after, before)
                if cls:
                    claims.append((_int(m.group("n")), cls))
            for value, cls in claims:
                if value not in _allowed(cls, c):
                    out.append(_count_message(value, cls, tier, c, sent))
        for m in _LABEL_COUNT.finditer(sent):
            if len(tiers) > 1 or _EXCLUDE_BEFORE.search(sent[: m.start()]):
                continue
            tier = next(iter(tiers)) if tiers else context
            if tier is None:
                continue
            c = _counts(f, tier, "numbers")
            lab = m.group("lab").lower()
            cls = (
                "reproduced_minor"
                if "minor" in lab
                else "not_reproduced"
                if lab.startswith("not")
                else "could_not_run"
                if lab.startswith("could")
                else "matched"
            )
            if lab == "reproduced" and re.match(r"\s+with\b", sent[m.end() :]):
                continue
            value = _int(m.group("n"))
            if value not in _allowed(cls, c):
                out.append(_count_message(value, cls, tier, c, sent))
    return out


def _count_message(value: int, cls: str, tier: int | None, c: dict[str, int], sent: str) -> str:
    if cls == "total":
        return f"{MD_FILE} says {value} {_where(tier)}numbers ({_quote(sent)}), {JSON_FILE} has {c['total']}"
    names = {
        "exact": "reproduced",
        "matched": "reproduced (exactly or with a minor difference)",
        "differ": "differing",
    }
    want = {
        "exact": f"{c['reproduced']} reproduced",
        "matched": f"{c['reproduced']} reproduced and {c['reproduced_minor']} reproduced_minor",
        "differ": f"{c['reproduced_minor']} reproduced_minor and {c['not_reproduced']} not_reproduced",
        "reproduced_minor": f"{c['reproduced_minor']} reproduced_minor",
        "not_reproduced": f"{c['not_reproduced']} not_reproduced"
        + (f" and {c['could_not_run']} could_not_run" if c["could_not_run"] else ""),
        "could_not_run": f"{c['could_not_run']} could_not_run",
    }[cls]
    return (
        f"{MD_FILE} says {value} {names.get(cls, cls)} {_where(tier)}numbers ({_quote(sent)}), {JSON_FILE} has {want}"
    )


def _tokens(text: str) -> list[tuple[float, int, str]]:
    out = []
    for m in _NUMBER.finditer(text):
        tok = m.group(0)
        try:
            v = float(tok)
        except ValueError:
            continue
        mant = tok.lower().split("e")[0]
        d = len(mant.split(".", 1)[1]) if "." in mant else 0
        out.append((v, 99 if "e" in tok.lower() else d, tok))
    return out


def _same(tok: tuple[float, int, str], value: float | None) -> bool:
    if value is None:
        return False
    x, d, _ = tok
    if d == 99:
        return math.isclose(x, value, rel_tol=1e-9, abs_tol=1e-15)
    if x == value:
        return True
    return d >= 2 and abs(x - value) <= 0.5 * 10 ** (-d) + 1e-12 * max(1.0, abs(value))


_LABEL_WORDS = (
    r"reproduced with (?:a )?minor differences?|reproduced_minor|not_reproduced|not reproduced|"
    r"could_not_run|could not (?:be )?run|reproduced(?: exactly)?"
)
# A label as a verdict: followed by a mark ("reproduced ✓", "not_reproduced ✗") or,
# in parentheses, written as the protocol's own label ("(not_reproduced)").
# "+0.0347 (reproduced)" names the reproduced value, not a label.
_MARKED_LABEL = re.compile(
    r"(?:\(\s*(?:[^()]*?,\s*)?(?P<lab>reproduced_minor|not_reproduced|could_not_run)\s*\))"
    r"|(?:(?<![\w])(?P<lab2>" + _LABEL_WORDS + r")\s*[✓✗⚠])",
    re.I,
)


def _record_label(rec: Record) -> str | None:
    found: set[str] = set()
    if rec.cells is not None:
        found = {lab for c in rec.cells if (lab := _cell_label(c))}
    else:
        # **x** or `x` names a label; "**Reproduced:** 0.035" is a field name, not a label
        for m in re.finditer(r"\*\*([^*]+)\*\*(?!\s*:)|`([^`]+)`(?!\s*:)", rec.text):
            inner = m.group(1) or m.group(2)
            lab = None if inner.rstrip().endswith(":") else _cell_label(inner)
            if lab:
                found.add(lab)
        for m in re.finditer(r"\b(?:status|label|level|outcome|verdict)\s*[:=]\s*\**`?([A-Za-z_ ]+)", rec.text, re.I):
            for n in range(len(m.group(1).split()), 0, -1):
                lab = _cell_label(" ".join(m.group(1).split()[:n]))
                if lab:
                    found.add(lab)
                    break
        # "(reproduced ✓)", "(relative diff 1.9e-18, reproduced ✓)", "not_reproduced ✗"
        for m in _MARKED_LABEL.finditer(rec.text):
            lab = _cell_label(m.group("lab") or m.group("lab2"))
            if lab:
                found.add(lab)
    if len(found) == 1:
        return found.pop()
    if not found:
        return rec.heading_label
    return None


def _match(rec: Record, f: Facts) -> Entry | None:
    pool = [e for e in f.entries if rec.tier is None or e.tier == rec.tier]
    by_id = [
        e for e in pool if e.target_id and re.search(r"(?<![\w])" + re.escape(e.target_id) + r"(?![\w])", rec.text)
    ]
    if len(by_id) == 1:
        return by_id[0]
    if by_id:
        return None
    toks = _tokens(rec.text)
    hits = []
    for e in pool:
        pub = [i for i, t in enumerate(toks) if _same(t, e.published)]
        if not pub:
            continue
        if e.reproduced is None:
            continue
        rep = [i for i, t in enumerate(toks) if _same(t, e.reproduced)]
        if any(i != j for i in pub for j in rep):
            hits.append(e)
    return hits[0] if len(hits) == 1 else None


def _label_problems(records: list[Record], f: Facts) -> list[str]:
    out: list[str] = []
    for rec in records:
        label = _record_label(rec)
        if label is None:
            continue
        e = _match(rec, f)
        if e is None or e.label == label:
            continue
        rep = "none" if e.reproduced is None else f"{e.reproduced:.15g}"
        out.append(
            f"{MD_FILE} labels {e.target_id} (published {e.published:.15g}, reproduced {rep}) {label!r}, "
            f"{JSON_FILE} labels it {e.label!r}"
        )
    return out


_SIGNED = r"([-+]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?)"
_PUBLISHED = re.compile(r"\bpublished\b\s*(?:value\s*)?[:=]?\s*\**\s*" + _SIGNED, re.I)
_REPRODUCED = re.compile(r"\breproduced\b\s*(?:value\s*)?[:=]?\s*\**\s*" + _SIGNED, re.I)


def _block_entries(block: Block, recs: list[Record], f: Facts) -> list[Entry]:
    """The compared numbers a section is about: by result or target id, by "Table N", or by published values."""
    pool = [e for e in f.entries if block.tier is None or e.tier == block.tier]
    text = block.title + "\n" + "\n".join(r.text for r in recs)
    by_id = [
        e
        for e in pool
        if any(i and re.search(r"(?<![\w])" + re.escape(i) + r"(?![\w])", text) for i in (e.result_id, e.target_id))
    ]
    if by_id:
        return by_id
    m = re.search(r"\b(?:table|exhibit|figure)\s+(\d+)\b", block.title, re.I)
    if m:
        hits = sorted(
            {e.result_id for e in pool if re.match(rf"(?:table|exhibit|figure)_?{m.group(1)}(?:_|$)", e.result_id)}
        )
        if len(hits) == 1:
            return [e for e in pool if e.result_id == hits[0]]
    published = [
        e for e in pool for r in recs for t in _PUBLISHED.finditer(r.text) if _same(_tokens(t.group(1))[0], e.published)
    ]
    results = {e.result_id for e in published}
    if len(results) == 1:
        return [e for e in pool if e.result_id in results]
    return []


def _block_problems(records: list[Record], blocks: list[Block], f: Facts) -> list[str]:
    """Per section: the published and reproduced numbers it states, and the labels next to them, are the JSON's.

    A section is matched to a result of the JSON by a result or target id, by
    its "Table N" title (``table_N_…``), or by the published values it states.
    A list item that states a published value names that compared number; its
    reproduced value and any label next to it must be the JSON's. A list item
    with a label and no published value ("- Label: not_reproduced ✗") speaks
    for the section: for its only compared number, or for its result.
    """
    out: list[str] = []
    for b, block in enumerate(blocks):
        recs = [r for r in records if r.block == b and r.cells is None]
        if not recs:
            continue
        entries = _block_entries(block, recs, f)
        if not entries:
            continue
        for rec in recs:
            # A label the item states itself (not one it inherits from its heading); one
            # the per-record check already compared (by target id or values) is not repeated.
            label = _record_label(rec)
            if label == rec.heading_label or _match(rec, f) is not None:
                label = None
            pubs = [_tokens(m.group(1))[0] for m in _PUBLISHED.finditer(rec.text)]
            reps = [_tokens(m.group(1))[0] for m in _REPRODUCED.finditer(rec.text)]
            if pubs:
                hits = [e for e in entries if any(_same(t, e.published) for t in pubs)]
                if len({id(e) for e in hits}) != 1:
                    if not hits and len(entries) == 1:
                        e = entries[0]
                        out.append(
                            f"{MD_FILE} gives {_quote(block.title, 40)} the published value {pubs[0][2]}, "
                            f"{JSON_FILE} has {e.published:.15g} ({e.target_id})"
                        )
                    continue
                e = hits[0]
                for t in reps:
                    if not _same(t, e.reproduced):
                        rep = "none" if e.reproduced is None else f"{e.reproduced:.15g}"
                        out.append(
                            f"{MD_FILE} says {e.target_id} (published {e.published:.15g}) reproduced {t[2]}, "
                            f"{JSON_FILE} has {rep}"
                        )
                if label and label != e.label:
                    out.append(f"{MD_FILE} labels {e.target_id} {label!r}, {JSON_FILE} labels it {e.label!r}")
            elif label:
                results = {e.result_id for e in entries}
                if len(entries) == 1 and label != entries[0].label:
                    e = entries[0]
                    out.append(
                        f"{MD_FILE} labels {e.target_id} ({_quote(block.title, 40)}) {label!r}, "
                        f"{JSON_FILE} labels it {e.label!r}"
                    )
                elif len(entries) > 1 and len(results) == 1 and label != entries[0].result_level:
                    out.append(
                        f"{MD_FILE} labels the result {entries[0].result_id} ({_quote(block.title, 40)}) {label!r}, "
                        f"{JSON_FILE} labels it {entries[0].result_level!r}"
                    )
    return out


_ALL_CLAIM = re.compile(
    r"\b(?:all|every|each)\b[^.;:]*?\b(?:reproduc\w*|replicat\w*|match\w*|agree\w*|equal\w*)\b"
    r"|\bfully reproducible\b|\breproduc\w* (?:exactly|fully|completely|in full)\b",
    re.I,
)
_ALL_EXCEPT = re.compile(
    r"\b(?:not|n't|no|none|never|except|but|apart from|other than|unless|fail\w*|diverg\w*|differ\w*|"
    r"mixed|most|some|partly|partially)\b",
    re.I,
)


def _overall_problems(sentences: list[tuple[str, int | None]], f: Facts) -> list[str]:
    """A sentence claiming that everything reproduced, while the JSON has numbers that did not."""
    out: list[str] = []
    for sent, context in sentences:
        if not _ALL_CLAIM.search(sent) or _ALL_EXCEPT.search(sent):
            continue
        tiers = _tiers_in(sent) or ({context} if context else set())
        c = _counts(f, next(iter(tiers)) if len(tiers) == 1 else None, "numbers")
        bad = c["not_reproduced"] + c["could_not_run"]
        exact = re.search(r"\bexact|\bfull precision|\bidentical", sent, re.I)
        if bad or (exact and c["reproduced_minor"]):
            out.append(
                f"{MD_FILE} says everything reproduced ({_quote(sent)}), {JSON_FILE} has "
                f"{c['not_reproduced']} not_reproduced, {c['could_not_run']} could_not_run and "
                f"{c['reproduced_minor']} reproduced_minor"
            )
    return out


_VERSION = r"v?(\d+(?:\.\d+)+(?:[-.]\w+)*)"


def _version_problems(text: str, f: Facts) -> list[str]:
    known = {**f.log_installed, **f.installed}
    if not known:
        return []
    names = sorted(known, key=len, reverse=True)
    any_name = re.compile(r"(?<![\w.])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])")
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        hits = list(any_name.finditer(line))
        for k, m in enumerate(hits):
            name = m.group(1)
            nxt = re.match(r"[\s:=*`|(,]*(?:version\s*)?" + _VERSION, line[m.end() :], re.I)
            if not nxt:
                continue
            stated = nxt.group(1)
            want = known[name]
            if stated == want:
                continue
            end = hits[k + 1].start() if k + 1 < len(hits) else len(line)
            segment = line[m.end() : end]
            if re.search(r"(?<![\w.])" + re.escape(want) + r"(?![\w.]*\d)", segment):
                continue  # "declared 0.12.0, installed 0.14.2"
            if f.declared.get(name) == stated and re.search(
                r"declar|document|pinned|requir|DESCRIPTION|README", line, re.I
            ):
                continue
            if (name, stated) in seen:
                continue
            seen.add((name, stated))
            source = f"{JSON_FILE} (environment.installed)" if name in f.installed else "sandbox_log.json"
            out.append(f"{MD_FILE} says {name} {stated}, {source} has {name} {want}")
    return out


def _says_nothing(rest: str) -> bool:
    """No account of the results beyond the summary e2er writes: only headings, the disclaimer, blank lines."""
    for line in rest.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">") or re.fullmatch(r"[-*_]{3,}", s):
            continue
        if re.search(r"[A-Za-z]{3}", s):
            return False
    return True


def markdown_problems(
    text: str,
    report: dict[str, Any],
    log: dict[str, Any] | None = None,
    *,
    check_summary: bool = True,
    require_summary: bool = False,
) -> list[str]:
    """Every statement of reproduction_report.md that contradicts reproduction_report.json.

    ``check_summary``: the e2er summary section, when present, must be exactly
    what :func:`render_summary` writes from these files (off for the
    comparer's contract check, which runs before e2er writes the section).
    ``require_summary``: the section must be there, and the report must say
    more than it (the reproduction check and ``e2er verify``, which run after
    e2er wrote it).
    """
    out: list[str] = []
    if not text.strip():
        return [f"{MD_FILE} is empty"]
    block, rest = split_summary(text)
    if require_summary and block is None:
        out.append(
            f"{MD_FILE} has no summary section written by e2er (it was removed, or the report was replaced after "
            "the reproduction check)"
        )
    if require_summary and _says_nothing(rest):
        out.append(f"{MD_FILE} says nothing beyond the counts e2er writes: the account of the results is missing")
    if check_summary and block is not None and block != render_summary(report, log):
        out.append(
            f"the summary section of {MD_FILE} is not what e2er writes from {JSON_FILE}: it was edited, or the "
            "JSON changed after it was written"
        )
    f = facts(report, log)
    with_numbers = [t for t in TARGET_LEVELS if f.numbers[t]]
    only = with_numbers[0] if len(with_numbers) == 1 else None
    tables, records, sentences, blocks = _parse(rest, only)
    out += _table_problems(tables, f)
    out += _sentence_problems(sentences, f)
    out += _label_problems(records, f)
    out += _block_problems(records, blocks, f)
    out += _overall_problems(sentences, f)
    out += _version_problems(rest, f)
    # one statement can surface through two routes (a list item is also a sentence)
    return list(dict.fromkeys(out))


__all__ = [
    "BEGIN",
    "END",
    "MD_FILE",
    "facts",
    "markdown_problems",
    "render_summary",
    "split_summary",
    "with_summary",
]
