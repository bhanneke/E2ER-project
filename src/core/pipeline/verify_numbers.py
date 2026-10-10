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
    # The results tables the renderer wrote for this paper (from
    # table_render_report.json), and those of them the draft never \input-s.
    # A paper whose rendered tables reach no table cell of the check has not
    # been checked, whatever the prose coverage: see `tables_untraced`.
    rendered_tables: list[str] = field(default_factory=list)
    rendered_tables_not_in_draft: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # `conclusive` is a property, so asdict() misses it — and the saved
        # JSON is what reviewers and the experiment harvester read.
        return {
            **asdict(self),
            "conclusive": self.conclusive,
            "tables_untraced": self.tables_untraced,
            "untraced_reason": self.untraced_reason,
        }

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

    @property
    def tables_conclusive(self) -> bool:
        """Did the TABLE channel reach a verdict on anything?

        Deliberately separate from `conclusive`, which ORs the two channels and
        therefore returns True for a run with rich prose coverage and no table
        coverage at all — the precise case it was written to catch. Table cells
        are where the anti-fabrication claim lives; prose coverage is not a
        substitute for them, and must not stand in for them in a report.
        """
        return self.total_values_in_tables > 0

    @property
    def tables_untraced(self) -> bool:
        """The renderer wrote results tables, and the check traced no cell of any.

        The case the 2026-10-10 Haiku run passed through: the draft ``\\input``-ed
        none of its two rendered tables, the table channel checked nothing, the
        prose channel checked 87 numbers, and the gate reported a pass. A check
        that ran on none of the paper's tables has not passed; the run's gate
        stops on this, and ``e2er verify`` fails it.
        """
        return bool(self.rendered_tables) and not self.tables_conclusive

    @property
    def untraced_reason(self) -> str:
        """Why no table cell was checked, in plain words; empty when cells were."""
        if not self.tables_untraced:
            return ""
        rendered = ", ".join(self.rendered_tables)
        missing = self.rendered_tables_not_in_draft
        if missing and len(missing) == len(self.rendered_tables):
            inputs = ", ".join(f"\\input{{tables/{name}}}" for name in missing)
            return (
                f"the paper includes none of its {len(missing)} rendered results table(s) ({rendered}), so the number "
                f"check compared no table cell with the results files; the paper needs {inputs} where each "
                "table belongs"
            )
        if missing:
            return (
                f"the number check found no number in the rendered results tables the paper includes, and the "
                f"paper leaves out {', '.join(missing)}; no table cell was compared with the results files"
            )
        if self.skipped_reason and self.skipped_reason != _NOTHING_VERIFIED:
            return f"no table cell of the rendered results tables ({rendered}) was checked: {self.skipped_reason}"
        return (
            f"the rendered results tables ({rendered}) are in the paper but hold no number the check can read "
            "(every cell is empty or ---), so no table cell was compared with the results files"
        )


_NOTHING_VERIFIED = "draft contains no table values and no checkable prose numbers; nothing was verified"

# JSON filenames that the analyst + econometrics specialist must produce.
# Look at workspace root (v3 layout). Order: by stage of production.
_SOURCE_JSON_FILES = (
    "summary_statistics.json",
    "estimation_results.json",
    "robustness_results.json",
    "figure_spec.json",
    # The field map's results (src/modules/fieldmap/workflow.py), written by code.
    "field_map_results.json",
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
    # A minus sign right after a digit or a dash is a range dash: the upper
    # bound of "0.12--0.15" or "5-10" is positive.
    r"((?:(?<![\d-])-)?\d+(?:,\d{3})*"  # integer part with optional thousands separators
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


# Period labels: a span of years, a quarter, a decade, a fiscal year, a month
# and year. Stripped from table cells and prose BEFORE number extraction, like
# the dates above. The 2026-10-10 live runs (mortgage pass-through study) stopped
# at the number check on rows labelled "2004--06", "2015--18", "2022--23": read
# as numbers they gave 2004 and -06, and -06 "mismatched" an ADF statistic.
_YEAR = r"(?:1[89]|20)\d{2}"
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
# A hyphen joins the years directly; an en or em dash may stand between spaces.
_DASH = r"(?:-|\s*(?:-{2,3}|–|—|\\text(?:en|em)dash(?:\{\})?)\s*)"
# 2004--06, 2007–2009, 2000-2007, 1998--02. The end must not come before the
# start and the span is at most 50 years (checked in `_strip_year_span`): "2019
# -12" or a number pair such as "1999-1850" stays as numbers.
_YEAR_SPAN_RE = re.compile(rf"(?<![\d.,])({_YEAR}){_DASH}(\d{{4}}|\d{{2}})(?!\d|[.,]\d)")
_PERIOD_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Quarter, half, month index: 2022Q3, 2022:Q3, 2022-Q3, 2022H1, 2004m6, 2004:06.
    re.compile(rf"(?<![\d.,]){_YEAR}\s*[:\-]?\s*[QqHh][1-4](?!\d)"),
    re.compile(rf"(?<![\d.,]){_YEAR}(?:[Mm]|:)(?:1[0-2]|0?[1-9])(?![\d.])"),
    re.compile(rf"\b[QH][1-4]\s*[:\-/~]?\s*{_YEAR}(?!\d)"),
    # Decades: 1990s, '90s.
    re.compile(r"(?<![\d.,])(?:1[89]|20)\d0s\b"),
    re.compile(r"(?:'|’)\d0s\b"),
    # Fiscal years: FY2019, FY 2019, FY19, FY'19.
    re.compile(rf"\bFY\s*'?(?:{_YEAR}|\d{{2}})(?!\d)"),
    # Month and year: Jan 2020, March 15, 2020, Mar.~2020.
    re.compile(rf"\b{_MONTH}\.?(?:\s|~)*(?:\d{{1,2}},?(?:\s|~)*)?{_YEAR}(?!\d)"),
)


def _strip_year_span(m: re.Match[str]) -> str:
    start, end = m.group(1), m.group(2)
    end_year = int(end) if len(end) == 4 else int(start[:2] + end)
    if len(end) == 2 and end_year < int(start):
        end_year += 100  # 1998--02
    return " " if 0 < end_year - int(start) <= 50 else m.group(0)


def _strip_periods(text: str) -> str:
    """Remove period labels (spans of years, quarters, decades, fiscal years, months)."""
    text = _YEAR_SPAN_RE.sub(_strip_year_span, text)
    for pattern in _PERIOD_PATTERNS:
        text = pattern.sub(" ", text)
    return text


_SCRIPT_RE = re.compile(r"[\^_](?:\{[^{}]*\}|[A-Za-z0-9])")


#: A word of at least two letters: the first cell of a row that has one is the
#: row's label, not a value (a bare number or a year there is still checked).
_LABEL_WORD_RE = re.compile(r"[A-Za-z]{2,}")


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
    cell = _strip_periods(cell)
    for pattern in _DATE_PATTERNS:
        cell = pattern.sub("", cell)
    # Superscripts and subscripts are notation, not values: the 2 of $R^2$, the
    # 1 of $\beta_1$ (read as table values, they "mismatched" a nearby estimate).
    cell = _SCRIPT_RE.sub("", cell)
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


def _decimals(num_str: str) -> int:
    """Digits after the decimal point as the draft shows the number (``1,234.50`` → 2)."""
    s = num_str.replace(",", "")
    return len(s.split(".", 1)[1]) if "." in s else 0


def _matches_rounded(num_str: str, source_val: float) -> bool:
    """The draft's number is the source value rounded to the decimals it shows.

    ``-1.059`` matches -1.05912 (3 decimals: ±0.0005); ``0.017`` does not match
    0.0123, although the relative tolerance (±0.005 for any value below 1)
    let it through. Ties and binary representation get a hair of slack.
    """
    draft_val = _parse_number(num_str)
    if draft_val is None:
        return False
    half = 0.5 * 10 ** (-_decimals(num_str))
    return abs(draft_val - source_val) <= half * (1 + 1e-9) + 1e-12 * max(1.0, abs(source_val))


#: A LaTeX comment: an unescaped % to the end of its line (``\\%`` is a percent sign).
_LATEX_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")

_FULL_RULE_RE = re.compile(r"\\(?:hline|midrule|toprule|bottomrule)(?![A-Za-z])")


def _header_rows(table_body: str, rule_re: re.Pattern[str]) -> int:
    """How many rows (counted by ``\\\\``) at the top of a tabular are its column headers.

    The headers end at the first full rule (``\\midrule`` or ``\\hline``) that
    follows a row with content and has rows after it: the column-header row and
    any header rows above it. A rule at the very top (``\\toprule``, a first
    ``\\hline``) comes before the headers; partial rules (``\\cmidrule``,
    ``\\cline``) sit between header rows and end nothing. A table whose only rule
    after its rows closes it (``\\bottomrule``, a last ``\\hline``) has no
    header rows set apart, so every row is read. Up to 0.13.7 the headers were
    everything above the first ``\\midrule``: a table ruled with ``\\hline``
    and a ``\\midrule`` lower down lost its data rows above it.
    """

    def has_content(text: str) -> bool:
        return any(chunk.strip() for chunk in rule_re.sub("", text).split("\\\\"))

    for m in _FULL_RULE_RE.finditer(table_body):
        before, after = table_body[: m.start()], table_body[m.end() :]
        if not has_content(before):
            continue
        return before.count("\\\\") if has_content(after) else 0
    return 0


def _extract_table_numbers(tex_content: str, *, zeros: bool = False) -> list[tuple[str, str]]:
    """Extract all numbers from LaTeX tabular environments.

    Returns list of (number_string, table_context) tuples. ``zeros`` keeps
    cells such as ``0.000`` (a value with decimals), which the run's gate skips.
    """
    results: list[tuple[str, str]] = []
    # LaTeX comments are not cells. A model annotating its rows with
    # "% src: ...by_period.pre_tightening_2015_2021.n" (DeepSeek V4 Pro, 2026-10-10)
    # had that line read into the next row's first cell, as the numbers 15021
    # and 22023, and `e2er verify` failed the study.
    tex_content = _LATEX_COMMENT_RE.sub("", tex_content)

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

        # The rows above the first \midrule are the column headers: labels such
        # as "Scaled, day 15 or earlier" or "120-day window", not results. Read
        # as values they "mismatched" the nearest number in the results (live
        # run 2026-10-04: all three critical mismatches were header cells, and
        # the run stopped on a correct paper).
        header_rows = _header_rows(table_body, rule_re)
        table_body = rule_re.sub("", table_body)
        rows = table_body.split("\\\\")
        for row_idx, row in enumerate(rows):
            row = row.strip()
            if not row or row_idx < header_rows:
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
                if cell_idx == 0 and len(cells) > 1 and _LABEL_WORD_RE.search(re.sub(r"\\[A-Za-z]+", "", cell)):
                    # The row label ("Surprise (25 bp)", "Placebo, 20 days
                    # before"): a number in it names the row, it is no result.
                    continue
                for num_match in _NUMBER_RE.finditer(cell):
                    num_str = num_match.group(1)
                    parsed = _parse_number(num_str)
                    if parsed is not None and (parsed != 0 or (zeros and "." in num_str)):
                        context = f"{table_label}, row {row_idx + 1}, col {cell_idx + 1}"
                        results.append((num_str, context))

    return results


# Environments / commands stripped before extracting PROSE numbers, so we
# don't double-count table cells or read \input paths, labels, refs, or cite
# keys as numeric claims.
_STRIP_FOR_PROSE: tuple[re.Pattern[str], ...] = (
    # Source notes are not claims: "<!-- src: ...2015_2021 -->" and "% src: ..." comments.
    re.compile(r"<!--.*?-->", re.DOTALL),
    _LATEX_COMMENT_RE,
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
    prose = _strip_periods(prose)
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


def rendered_tables(workspace: Path) -> list[str]:
    """The results tables the renderer wrote for this paper, by file name.

    Read from ``table_render_report.json``, which the renderer writes on every
    render; a stale ``tables/*.tex`` from an earlier table_spec is not one of
    them. Empty when nothing was rendered or the report is unreadable.
    """
    path = workspace / "table_render_report.json"
    try:
        rep = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rendered = rep.get("rendered") if isinstance(rep, dict) else None
    if not isinstance(rendered, list):
        return []
    return sorted({str(r) for r in rendered if isinstance(r, str) and r})


def _strip_tex_comments(tex: str) -> str:
    """Drop LaTeX comments: a commented-out ``\\input`` includes nothing."""
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in tex.splitlines())


def included_tables(tex_content: str) -> set[str]:
    """File names of the tables a draft ``\\input``-s (``tables/main`` → ``main.tex``)."""
    names: set[str] = set()
    for ref in _INPUT_RE.findall(_strip_tex_comments(tex_content)):
        name = Path(ref.strip()).name
        names.add(name if name.endswith(".tex") else f"{name}.tex")
    return names


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


_INPUT_RE = re.compile(r"\\input\{([^}]+)\}")


def _expand_inputs(tex_content: str, base_dir: Path, _depth: int = 0) -> str:
    """Inline ``\\input{...}`` targets so tables in their own files are scanned.

    The renderer writes one .tex per table and the draft includes each with
    ``\\input{tables/<name>.tex}``. Reading only the draft means the scanner
    sees no tabular environment at all, and the gate then reports a pass having
    traced zero cells — which is indistinguishable, in the report, from a pass
    that checked every number.

    Depth-bounded against include cycles. A missing or unreadable target is
    left as the literal directive rather than failing the gate: a bundle that
    cannot be fully resolved should still be checked as far as it goes, and
    the unresolved table shows up as absent coverage.
    """
    if _depth >= 4:
        return tex_content

    def _inline(match: re.Match[str]) -> str:
        ref = match.group(1).strip()
        for candidate in (base_dir / ref, base_dir / f"{ref}.tex"):
            if candidate.is_file():
                try:
                    nested = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return match.group(0)
                return _expand_inputs(nested, candidate.parent, _depth + 1)
        return match.group(0)

    return _INPUT_RE.sub(_inline, tex_content)


def verify(
    draft_path: Path,
    workspace: Path,
    tolerance: float = 0.005,
    *,
    rounding: bool = False,
) -> VerificationReport:
    """Run programmatic verification of draft table values against source JSON.

    Args:
        draft_path: Path to paper_draft.tex
        workspace: Paper workspace dir (contains source JSON files)
        tolerance: Relative numeric tolerance for matching (default 0.5%)
        rounding: ``e2er verify``'s rule: a table cell matches only a source
            value that, rounded to the decimals the cell shows, is the cell
            (zeros with decimals included). Every other cell is a critical
            mismatch, whatever its distance; the caller fails on any.

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

    raw_draft = draft_path.read_text(encoding="utf-8", errors="replace")
    tex_content = _expand_inputs(raw_draft, draft_path.parent)

    # PR-2: key-resolution feedback is independent of numeric content — surface
    # it before any of the source-JSON early returns below.
    report.table_spec_unresolved = _read_table_spec_feedback(workspace)
    # Likewise which rendered tables the draft includes: a paper with rendered
    # tables and no traced cell must not read as a pass, however it got there.
    report.rendered_tables = rendered_tables(workspace)
    included = included_tables(raw_draft)
    report.rendered_tables_not_in_draft = [t for t in report.rendered_tables if t not in included]

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

    table_numbers = _extract_table_numbers(tex_content, zeros=rounding)
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
            ok = _matches_rounded(num_str, source_val) if rounding else _values_match(draft_val, source_val, tolerance)
            if ok:
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

        if rounding and closest_key:
            report.mismatched += 1
            report.mismatches.append(
                Mismatch(
                    draft_value=num_str,
                    source_key=closest_key,
                    source_value=str(all_source_values[closest_key]),
                    table_context=context,
                    severity="critical",
                )
            )
        elif closest_dist < abs(draft_val) * 0.5 and closest_key:
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
        report.skipped_reason = _NOTHING_VERIFIED
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
