"""Programmatic artifact-to-table verification — anti-hallucination gate.

Compares numeric values in `paper_draft.tex` LaTeX tables against
authoritative JSON files produced by the data_analyst and
econometrics_specialist. Deterministic, no LLM calls. Ported from
v1 (E2ER/src/pipeline/verify_numbers.py) and adapted to the v3
workspace layout (flat workspace dir, no artifacts/stage/run_*/).

Failure mode this catches: live test paper a6182f08 on v0.4.5 had
the paper_drafter claim "log realized variance falls by 0.41
($t=-3.9$)" — numbers the analyst's pipeline cannot produce from
the 14 CSVs that actually landed. The technical reviewer caught
this with score=3 (HARD_REJECT) but only after 6 reviewers had
already run. This module runs BEFORE reviewers and rejects the
draft at the audit gate if it cites numbers that don't match the
source JSON.

Contract (declared in the paper_drafter + analyst prompts):
- data_analyst writes `summary_statistics.json` at workspace root
  with summary stats over the assembled dataset.
- econometrics_specialist writes `estimation_results.json` (point
  estimates, standard errors, t-stats, p-values, sample sizes) and,
  if robustness checks were run, `robustness_results.json`.
- paper_drafter MAY ONLY cite numbers that appear in these files.

Fallback (per v0.5.0 design): if no source JSON files are found in
the workspace, log a warning and skip the audit. Old papers that
predate the contract don't get blocked, and the analyst has not
been retrained yet for new papers. Once the analyst reliably
produces the JSON files, the gate becomes effective.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Mismatch:
    """A numeric value in the draft that doesn't match any source."""

    draft_value: str
    source_key: str
    source_value: str
    table_context: str  # which table / row / column
    severity: str  # critical | major | minor


@dataclass
class MatchedCell:
    """A table cell whose value DID trace to a source JSON key. Recorded so the
    provenance manifest can emit a per-cell derivation edge (draft → source)."""

    draft_value: str
    source_key: str
    table_context: str


@dataclass
class VerificationReport:
    """Result of programmatic number verification."""

    passed: bool = True
    total_values_in_tables: int = 0
    matched: int = 0
    mismatched: int = 0
    unverifiable: int = 0
    coverage: float = 1.0
    mismatches: list[Mismatch] = field(default_factory=list)
    # Cells that traced (draft value ↔ source key) — provenance, not gating.
    matched_cells: list[MatchedCell] = field(default_factory=list)
    source_files_found: list[str] = field(default_factory=list)
    source_files_missing: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    # PR-2: prose-number checking ("text = table number"). Deliberately
    # NON-GATING — prose mismatches live in their own list and never become
    # `critical`, so they never reject a paper (prose has many incidental
    # numbers — years, section refs, %s — and we won't reintroduce false
    # positives). They're an informational signal for reviewers / a human.
    #
    # `prose_total` counts only CHECKABLE numbers — see `_is_checkable_prose`.
    # It is the honest denominator: matched + mismatched + unverifiable.
    prose_total: int = 0
    prose_matched: int = 0
    prose_mismatched: int = 0
    # Checkable, but traceable to no source value. Could be a legitimately
    # derived quantity or a fabrication — the check cannot tell, so this is
    # reported separately and never counted as a mismatch.
    prose_unverifiable: int = 0
    # Numbers dropped before checking because they are not empirical claims
    # (LaTeX markup, years/dates, single-significant-digit magnitudes).
    prose_excluded: int = 0
    prose_mismatches: list[Mismatch] = field(default_factory=list)
    # PR-2: key-resolution feedback. Unresolved table_spec references (after
    # the renderer's order-insensitive normalization), with the available keys
    # so the drafter can correct them. Surfaced from table_render_report.json.
    table_spec_unresolved: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # `conclusive` is a property, so asdict() misses it — and the saved
        # JSON is what reviewers and the experiment harvester read.
        return {**asdict(self), "conclusive": self.conclusive}

    @property
    def critical_mismatches(self) -> list[Mismatch]:
        # Only TABLE mismatches gate the pipeline; prose is informational.
        return [m for m in self.mismatches if m.severity == "critical"]

    @property
    def conclusive(self) -> bool:
        """Did the check reach a verdict on anything at all?

        `passed` is a gating decision and stays True when there was nothing to
        gate on. Whether the run has evidential value is a separate question,
        and a caller must be able to tell the two apart — otherwise a draft
        with no inline tables reads exactly like a clean one.
        """
        return (self.total_values_in_tables + self.prose_total) > 0


# JSON filenames that the analyst + econometrics specialist must produce.
# Look at workspace root (v3 layout). Order: by stage of production.
_SOURCE_JSON_FILES = (
    "summary_statistics.json",
    "estimation_results.json",
    "robustness_results.json",
    "figure_spec.json",
)

# Regex to extract content of \begin{tabular}...\end{tabular}
_TABULAR_RE = re.compile(
    r"\\begin\{tabular\}.*?\n(.*?)\\end\{tabular\}",
    re.DOTALL,
)

# Regex to extract numbers from table cells. Matches:
#   - plain numbers: 0.45, -1.23, 1234, 0.001
#   - numbers in math mode: $0.45$, $-1.23$
#   - standard errors in parens: (0.02), ($0.02$)
#   - numbers with significance stars: 0.45***, 0.45**
#   - percentages: 52\%
_NUMBER_RE = re.compile(
    r"(?<![a-zA-Z])"  # not preceded by a letter
    r"[\$\(]*"  # optional $ or (
    r"(-?\d+(?:,\d{3})*"  # integer part with optional thousands separators
    r"(?:\.\d+)?)"  # optional decimal part
    r"[\$\)]*"  # optional $ or )
    r"(?:\*{1,3})?"  # optional significance stars
    r"(?:\\%)?",  # optional \%
)


# Date patterns to strip from a cell BEFORE number extraction.
# Surfaced by the v0.6.1 live run on paper f79b7cd9: a cell
# containing "2021-03-01" was parsed as the bare number 2021,
# which then false-positive-mismatched against the source JSON
# under `price_anchors_usd_close.2021-03-01.WETH` ("source value:
# 1573.89" vs "draft value: 2021"). The mismatch was a parser
# bug, not a hallucination — the year was part of the date, not
# a numeric claim.
#
# We strip three common date forms:
#   - ISO: YYYY-MM-DD or YYYY-MM
#   - slash: YYYY/MM/DD or YYYY/MM
#   - US: MM/DD/YYYY
# Bare years like "2021" outside a date context still get
# extracted — they may legitimately be a count or a year referenced
# in the paper's text.
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{4}-\d{1,2}(?:-\d{1,2})?\b"),
    re.compile(r"\b\d{4}/\d{1,2}(?:/\d{1,2})?\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
)


def _normalize_cell(cell: str) -> str:
    """Pre-process a tabular cell before running ``_NUMBER_RE``.

    Two fixes, both surfaced by the v0.6.1 live run:

    1. LaTeX thousands separator ``1{,}573.89`` (the brace-protected
       form that's safe inside math mode) was being split into the
       two numbers 1 and 573.89. We replace ``{,}`` with ``,`` so
       the existing thousands-separator branch of ``_NUMBER_RE``
       picks it up as a single 1,573.89.
    2. Date strings (``2021-03-01``, ``03/01/2021``, ``2021/03``)
       inside column headers were extracting the year as a numeric
       claim, generating false-positive mismatches. We strip date
       substrings entirely before number extraction.
    """
    # LaTeX brace-protected thousands separator → standard comma.
    # Done first so subsequent date stripping sees a clean number.
    cell = cell.replace("{,}", ",")
    for pattern in _DATE_PATTERNS:
        cell = pattern.sub("", cell)
    return cell


def _flatten_json(obj: Any, prefix: str = "") -> dict[str, float]:
    """Recursively extract all numeric values from a JSON object.

    Returns a dict mapping dotted key paths to float values.
    """
    result: dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            result.update(_flatten_json(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}[{i}]"
            result.update(_flatten_json(v, key))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if not (math.isnan(obj) or math.isinf(obj)):
            result[prefix] = float(obj)
    return result


def _parse_number(s: str) -> float | None:
    """Parse a number string, stripping commas and whitespace."""
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _values_match(draft_val: float, source_val: float, tolerance: float = 0.005) -> bool:
    """Check if two values match within tolerance.

    Rules:
    - Signs must match (zero is sign-agnostic)
    - Integer values >= 10 must be exact
    - Decimals: |draft - source| <= tolerance * max(1, |source|)
    """
    if (draft_val > 0) != (source_val > 0) and draft_val != 0 and source_val != 0:
        return False
    if source_val == int(source_val) and abs(source_val) >= 10:
        return draft_val == source_val
    scale = max(1.0, abs(source_val))
    return abs(draft_val - source_val) <= tolerance * scale


def _extract_table_numbers(tex_content: str) -> list[tuple[str, str]]:
    """Extract all numbers from LaTeX tabular environments.

    Returns list of (number_string, table_context) tuples.
    """
    results: list[tuple[str, str]] = []

    # Strip non-data rule commands before splitting into rows. `cmidrule`
    # carries a numeric range arg (\cmidrule(lr){2-3}) that must not be read
    # as data; include it alongside the other booktabs/array rules.
    rule_re = re.compile(
        r"\\(?:hline|midrule|toprule|bottomrule"
        r"|cline\{[^}]*\}"
        r"|cmidrule(?:\([^)]*\))?(?:\{[^}]*\})?"
        r"|addlinespace(?:\[[^\]]*\])?)\s*"
    )

    for i, match in enumerate(_TABULAR_RE.finditer(tex_content)):
        table_body = match.group(1)
        table_label = f"Table {i + 1}"

        start = max(0, match.start() - 200)
        preamble = tex_content[start : match.start()]
        label_match = re.search(r"\\label\{([^}]+)\}", preamble)
        if label_match:
            table_label = label_match.group(1)
        caption_match = re.search(r"\\caption\{([^}]{1,60})", preamble)
        if caption_match:
            table_label += f" ({caption_match.group(1)}...)"

        table_body = rule_re.sub("", table_body)
        rows = table_body.split("\\\\")
        for row_idx, row in enumerate(rows):
            row = row.strip()
            if not row:
                continue
            # Skip structural rows that span columns with \multicolumn:
            # column-group headers and panel labels (e.g.
            # "\multicolumn{6}{l}{Panel B: Post-2008}"). Extracting from them
            # reads the span count ("6"), a label year ("2008"), or a window
            # length ("120") as if it were a data value — the false-positive
            # class that rejected correct papers (M5 re-run 92626bf8). Data
            # rows are plain `label & value & value`; they never use
            # \multicolumn.
            if "\\multicolumn" in row:
                continue
            cells = row.split("&")
            for cell_idx, cell in enumerate(cells):
                cell = _normalize_cell(cell.strip())
                for num_match in _NUMBER_RE.finditer(cell):
                    num_str = num_match.group(1)
                    parsed = _parse_number(num_str)
                    if parsed is not None and parsed != 0:
                        context = f"{table_label}, row {row_idx + 1}, col {cell_idx + 1}"
                        results.append((num_str, context))

    return results


# Environments / commands stripped before extracting PROSE numbers, so we
# don't double-count table cells or read \input paths, labels, refs, or cite
# keys as numeric claims.
_STRIP_FOR_PROSE: tuple[re.Pattern[str], ...] = (
    re.compile(r"\\begin\{tabular\}.*?\\end\{tabular\}", re.DOTALL),
    re.compile(r"\\input\{[^}]*\}"),
    re.compile(r"\\(?:label|ref|eqref|cref|cite[a-z]*)\{[^}]*\}"),
    # The bibliography is other people's titles, not this paper's claims.
    # "\newblock Bitcoin ETFs attract \$4.6 billion in first month" was read
    # as a claim about a mean high-volatility duration of 4.2 days.
    re.compile(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.DOTALL),
)

# LaTeX commands whose numeric arguments are typesetting parameters, not
# empirical claims. Every one of these produced a "fabrication" in the
# 2026-08-05 validation cell: `\documentclass[12pt]` was reported as the
# number 12 mismatching a VIX mean of 16.82.
_MARKUP_COMMANDS = (
    "documentclass",
    "usepackage",
    "geometry",
    "setlength",
    "addtolength",
    "setcounter",
    "renewcommand",
    "newcommand",
    "definecolor",
    "includegraphics",
    "hspace",
    "vspace",
    "fontsize",
    "resizebox",
    "scalebox",
    "adjustbox",
    "raisebox",
    "rule",
    "captionsetup",
    "titlespacing",
    "arraystretch",
)
_MARKUP_RE = re.compile(
    r"\\(?:" + "|".join(_MARKUP_COMMANDS) + r")\b(?:\s*\[[^\]]*\])*(?:\s*\{[^{}]*\})*",
)
# Row-spacing arguments on a line break: `\\[6pt]`.
_ROW_SPACING_RE = re.compile(r"\\\\\s*\[[^\]]*\]")
# `\begin{document}` splits typesetting setup from authored text. Only used
# when present — the unit tests (and fragments) have no preamble at all.
_BEGIN_DOC_RE = re.compile(r"\\begin\{document\}")

# A bare four-digit year is a date reference, not a measurement. Dates in
# ISO/slash form are stripped wholesale by `_DATE_PATTERNS` first.
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# Source-key path components too generic to establish that a prose number
# refers to a particular quantity. Without this, `summary_statistics.json.*`
# would associate every key with any sentence containing "summary".
_GENERIC_KEY_TOKENS = frozenset(
    {
        "json",
        "summary",
        "statistics",
        "stats",
        "results",
        "result",
        "estimation",
        "robustness",
        "figure",
        "spec",
        "data",
        "main",
        "value",
        "values",
        "all",
        "overall",
        "table",
        "row",
        "col",
        "and",
        "the",
        "for",
    }
)
_KEY_TOKEN_SPLIT = re.compile(r"[^A-Za-z]+")

# Source keys carry no units, so a percentage in the prose cannot be compared
# to a bare source number: "annualized volatility 59\%" is not a claim about
# `n_high_vol_episodes = 52`, and "a 95\% confidence interval" is not a claim
# about anything. Percent-marked numbers are only checkable against keys that
# name a rate.
_RATE_KEY_TOKENS = frozenset(
    {"pct", "percent", "percentage", "rate", "share", "ratio", "prob", "probability", "pval", "pvalue"}
)

# How much text either side of a prose number counts as its neighbourhood
# when looking for a source-key token. Roughly one clause — wide enough for
# "the VIX averages 19.2", narrow enough that the paper's general vocabulary
# ("ETF", "volatility") doesn't associate every number with every key.
_ASSOC_WINDOW = 40
_WORD_RE = re.compile(r"[a-z]+")

# A number carrying a unit refers to a quantity measured in that unit. The
# source JSON carries no units, so such a claim is only checkable against a
# key that names the same one — "extends 2.6 years" is not a statement about
# `mean_high_vol_duration = 4.2` (days), and "\$4.6 billion" is not a
# statement about anything in these files.
_UNIT_WORDS = frozenset(
    {
        "year",
        "month",
        "week",
        "day",
        "hour",
        "minute",
        "second",
        "billion",
        "million",
        "trillion",
        "thousand",
        "basis",
        "bp",
        "bps",
        "lag",
        "obs",
        "observation",
    }
)
_UNIT_AFTER_RE = re.compile(r"^[\s~,]*(?:\\[,;:! ])?\s*([A-Za-z]+)")
_CURRENCY_BEFORE_RE = re.compile(r"(?:\\\$|[$€£])\s*$")
# `$\delta_{21} = 0.14$`, `$p_{11} = 0.94$` — the number's referent is the
# symbol on the left, not any English word nearby. Unless a source key names
# that symbol, the claim cannot be checked.
_SYMBOL_ASSIGN_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\\([A-Za-z]+)(?:_\{?\w+\}?)?\s*=\s*[$\\(]*$"),
    re.compile(r"(?:^|[\s$({])([A-Za-z]+)_\{?\w+\}?\s*=\s*[$\\(]*$"),
)


def _significant_digits(num_str: str) -> int:
    """Count significant digits in a number as the draft displays it.

    ``4`` → 1, ``4.2`` → 2, ``0.0136`` → 3. A single significant digit
    carries too little information to verify against anything: "over \\$4
    billion" sits within 50% of any source value in [2, 6].
    """
    s = num_str.replace(",", "").strip().lstrip("+-").lstrip("0")
    s = s.replace(".", "").lstrip("0")
    return len(s)


def _key_tokens(source_key: str) -> frozenset[str]:
    """Distinctive words in a flattened source key, for association."""
    toks = {t.lower() for t in _KEY_TOKEN_SPLIT.split(source_key) if len(t) >= 3}
    return frozenset(toks - _GENERIC_KEY_TOKENS)


def _window_words(window: str) -> frozenset[str]:
    """Whole words in a number's neighbourhood, plus de-pluralised forms.

    Whole words, not substrings: matching "pre" inside "rep*re*sents" once
    associated a GARCH parameter with an Ethereum volatility mean.
    """
    words = set(_WORD_RE.findall(window))
    return frozenset(words | {w[:-1] for w in words if w.endswith("s") and len(w) > 3})


def _strip_latex_machinery(tex_content: str) -> str:
    """Remove typesetting parameters so they never read as numeric claims."""
    doc = _BEGIN_DOC_RE.search(tex_content)
    prose = tex_content[doc.end() :] if doc else tex_content
    for pat in _STRIP_FOR_PROSE:
        prose = pat.sub(" ", prose)
    prose = _MARKUP_RE.sub(" ", prose)
    prose = _ROW_SPACING_RE.sub(" ", prose)
    for pat in _DATE_PATTERNS:
        prose = pat.sub(" ", prose)
    return prose


@dataclass
class _ProseNumber:
    """A number found in authored text, with what we need to judge it."""

    num_str: str
    context: str  # short, for the report
    words: frozenset[str]  # neighbouring words, for association
    is_percent: bool
    unit: str | None = None  # "years", "billion", currency…
    symbol: str | None = None  # LaTeX symbol it is assigned to


def _unit_after(prose: str, end: int) -> str | None:
    m = _UNIT_AFTER_RE.match(prose[end : end + 24])
    if not m:
        return None
    word = m.group(1).lower().rstrip("s")
    return word if word in _UNIT_WORDS else None


def _symbol_before(before: str) -> str | None:
    for pat in _SYMBOL_ASSIGN_RES:
        m = pat.search(before)
        if m:
            return m.group(1).lower()
    return None


def _extract_prose_numbers(tex_content: str) -> list[_ProseNumber]:
    """Extract numbers from PROSE — everything outside tabular environments."""
    prose = _strip_latex_machinery(tex_content)
    results: list[_ProseNumber] = []
    for m in _NUMBER_RE.finditer(prose):
        num_str = m.group(1)
        parsed = _parse_number(num_str)
        if parsed is None or parsed == 0:
            continue
        s = max(0, m.start() - 30)
        e = min(len(prose), m.end() + 20)
        ctx = " ".join(prose[s:e].split())
        ws = max(0, m.start() - _ASSOC_WINDOW)
        we = min(len(prose), m.end() + _ASSOC_WINDOW)
        before = prose[ws : m.start()]
        unit = _unit_after(prose, m.end())
        if unit is None and _CURRENCY_BEFORE_RE.search(before):
            unit = "currency"
        results.append(
            _ProseNumber(
                num_str=num_str,
                context=f"prose: …{ctx}…",
                words=_window_words(" ".join(prose[ws:we].split()).lower()),
                is_percent=m.group(0).rstrip().endswith("%"),
                unit=unit,
                symbol=_symbol_before(before),
            )
        )
    return results


def _is_checkable_prose(num_str: str) -> bool:
    """Is this prose number an empirical claim we could verify at all?

    Excludes years (date references, not measurements) and single-significant
    -digit magnitudes, which are within 50% of far too many source values to
    say anything about.
    """
    if _YEAR_RE.fullmatch(num_str.strip()):
        return False
    return _significant_digits(num_str) >= 2


def _check_prose(
    report: VerificationReport,
    tex_content: str,
    all_source_values: dict[str, float],
    tolerance: float,
) -> None:
    """Non-gating prose check ("text = table number").

    A prose number is a *mismatch* only when the surrounding sentence names
    the source quantity it is close to. Numeric proximity alone establishes
    nothing: with a few dozen source values spread across orders of
    magnitude, almost every number in a paper sits within 50% of one of
    them. Flagging on proximity alone made 79% of the flags in the
    2026-08-05 validation cell artifacts — a title's "2024" paired against a
    sample count of 1677, "\\$4 billion" against a duration mean of 4.2 —
    with 119 of 284 flags resolving to a single source key.

    Numbers we cannot tie to a source key are counted as
    ``prose_unverifiable``, never as mismatches: they may be legitimately
    derived quantities, and the check has no way to tell.
    """
    tokens_by_key = {key: _key_tokens(key) for key in all_source_values}
    for pn in _extract_prose_numbers(tex_content):
        draft_val = _parse_number(pn.num_str)
        if draft_val is None:
            continue
        if not _is_checkable_prose(pn.num_str):
            report.prose_excluded += 1
            continue
        report.prose_total += 1

        if any(_values_match(draft_val, sv, tolerance) for sv in all_source_values.values()):
            report.prose_matched += 1
            continue

        # Only source values whose key is named nearby are candidates.
        closest_key, closest_dist = "", float("inf")
        for key, sv in all_source_values.items():
            tokens = tokens_by_key[key]
            if not (tokens & pn.words):
                continue
            if pn.is_percent and not (tokens & _RATE_KEY_TOKENS):
                continue
            if pn.unit and pn.unit not in tokens:
                continue
            if pn.symbol and pn.symbol not in tokens:
                continue
            dist = abs(draft_val - sv)
            if dist < closest_dist:
                closest_dist, closest_key = dist, key

        if closest_key and closest_dist < abs(draft_val) * 0.5:
            sv = all_source_values[closest_key]
            report.prose_mismatched += 1
            report.prose_mismatches.append(
                Mismatch(
                    draft_value=pn.num_str,
                    source_key=closest_key,
                    source_value=str(sv),
                    table_context=pn.context,
                    severity="major",  # never critical — prose is non-gating
                )
            )
        else:
            report.prose_unverifiable += 1


def _read_table_spec_feedback(workspace: Path) -> list[dict[str, Any]]:
    """Surface unresolved ``table_spec`` references (after the renderer's
    order-insensitive normalization) from ``table_render_report.json``,
    annotated with the available spec keys so the drafter can correct them.
    """
    path = workspace / "table_render_report.json"
    if not path.is_file():
        return []
    try:
        rep = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    unresolved = rep.get("unresolved") or []
    if not unresolved:
        return []
    available_specs: list[str] = []
    for fn in ("estimation_results.json", "robustness_results.json"):
        fp = workspace / fn
        if not fp.is_file():
            continue
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(d, dict):
            available_specs.extend(k for k in d if not k.startswith("_"))
    seen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for u in unresolved:
        key = (u.get("kind"), u.get("ref"))
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, Any] = {"kind": u.get("kind"), "ref": u.get("ref")}
        if u.get("kind") == "spec_key":
            entry["available_spec_keys"] = sorted(set(available_specs))
        out.append(entry)
    return out


def _find_source_jsons(workspace: Path) -> dict[str, Path]:
    """Locate authoritative JSON files at the workspace root.

    Returns dict mapping descriptive name to file path. Missing files
    are not included; the caller decides whether the absence is fatal.
    """
    found: dict[str, Path] = {}
    for fn in _SOURCE_JSON_FILES:
        fp = workspace / fn
        if fp.is_file():
            found[fn] = fp
    return found


def verify(
    draft_path: Path,
    workspace: Path,
    tolerance: float = 0.005,
) -> VerificationReport:
    """Run programmatic verification of draft table values against source JSON.

    Args:
        draft_path: Path to paper_draft.tex
        workspace: Paper workspace dir (contains source JSON files)
        tolerance: Relative numeric tolerance for matching (default 0.5%)

    Returns:
        VerificationReport. `passed=True` iff no critical or major
        mismatches. Skipped runs (no source files found) also report
        `passed=True` with `skipped_reason` set — the caller can decide
        whether to gate on this.
    """
    report = VerificationReport()

    if not draft_path.is_file():
        report.skipped_reason = f"draft not found at {draft_path}"
        logger.warning("verify_numbers: %s", report.skipped_reason)
        return report

    tex_content = draft_path.read_text(encoding="utf-8", errors="replace")

    # PR-2: key-resolution feedback is independent of numeric content — surface
    # it before any of the source-JSON early returns below.
    report.table_spec_unresolved = _read_table_spec_feedback(workspace)

    source_jsons = _find_source_jsons(workspace)
    report.source_files_found = sorted(str(p) for p in source_jsons.values())
    report.source_files_missing = sorted(fn for fn in _SOURCE_JSON_FILES if fn not in source_jsons)

    if not source_jsons:
        # No JSON contract output from analyst/econometrics. Skip the
        # audit per the v0.5.0 design (warn + pass). Once specialists
        # are retrained to produce these files, the gate activates
        # automatically.
        report.skipped_reason = "no source JSON files found in workspace; expected one of: " + ", ".join(
            _SOURCE_JSON_FILES
        )
        logger.warning("verify_numbers: %s", report.skipped_reason)
        return report

    all_source_values: dict[str, float] = {}
    for name, path in source_jsons.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            flat = _flatten_json(data, prefix=name)
            all_source_values.update(flat)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("verify_numbers: failed to parse %s: %s", path, e)

    if not all_source_values:
        report.skipped_reason = "source JSON files were empty or unparseable"
        logger.warning("verify_numbers: %s", report.skipped_reason)
        return report

    table_numbers = _extract_table_numbers(tex_content)
    report.total_values_in_tables = len(table_numbers)

    if not table_numbers:
        logger.info("verify_numbers: no numbers in inline tables; checking prose only")

    for num_str, context in table_numbers:
        draft_val = _parse_number(num_str)
        if draft_val is None:
            report.unverifiable += 1
            continue

        best_match: str | None = None
        for key, source_val in all_source_values.items():
            if _values_match(draft_val, source_val, tolerance):
                best_match = key
                break

        if best_match is not None:
            report.matched += 1
            report.matched_cells.append(MatchedCell(draft_value=num_str, source_key=best_match, table_context=context))
            continue

        # No exact match — find closest source value to decide severity.
        closest_key = ""
        closest_dist = float("inf")
        for key, source_val in all_source_values.items():
            dist = abs(draft_val - source_val)
            if dist < closest_dist:
                closest_dist = dist
                closest_key = key

        if closest_dist < abs(draft_val) * 0.5 and closest_key:
            # Close but not matching — likely transcription error.
            source_val = all_source_values[closest_key]
            rel_err = abs(draft_val - source_val) / max(1, abs(source_val))
            severity = "critical" if rel_err > 0.1 else "major"
            report.mismatched += 1
            report.mismatches.append(
                Mismatch(
                    draft_value=num_str,
                    source_key=closest_key,
                    source_value=str(source_val),
                    table_context=context,
                    severity=severity,
                )
            )
        else:
            # No close match — could be a derived quantity or from a
            # different source. Count as unverifiable, not a mismatch.
            report.unverifiable += 1

    checked = report.matched + report.mismatched
    total = report.total_values_in_tables
    # Coverage over zero table values is 0.0, not 1.0. Reporting a vacuous
    # 1.0 made "the draft has no inline tables" indistinguishable from
    # "every cell traced to a source" — the reading that let run ab95fcba
    # record perfect coverage over nothing.
    report.coverage = checked / total if total > 0 else 0.0
    report.passed = report.mismatched == 0 or all(m.severity == "minor" for m in report.mismatches)

    # PR-2: prose-number check (non-gating; never critical). The key-resolution
    # feedback was already surfaced near the top (independent of numeric content).
    _check_prose(report, tex_content, all_source_values, tolerance)

    if not report.conclusive:
        report.skipped_reason = "draft contains no table values and no checkable prose numbers; nothing was verified"
        logger.warning("verify_numbers: %s", report.skipped_reason)

    return report


def verify_and_save(
    draft_path: Path,
    workspace: Path,
) -> VerificationReport:
    """Run verification and persist the report at
    `<workspace>/number_verification.json` for reviewer specialists
    and the dashboard."""
    report = verify(draft_path, workspace)
    output_path = workspace / "number_verification.json"
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(
        "verify_numbers: matched=%d mismatched=%d unverifiable=%d total=%d passed=%s",
        report.matched,
        report.mismatched,
        report.unverifiable,
        report.total_values_in_tables,
        report.passed,
    )
    return report
