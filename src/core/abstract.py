"""The abstract: written last, from the final paper, and checked before it goes into the paper.

Up to 0.17.3 the abstract writer ran beside the paper drafter, on a draft
that did not exist yet, and its ``abstract.tex`` reached only the title and
``report.html``: the compiler built the PDF from ``paper_draft.tex`` alone,
whose abstract the drafter had written. The PDF, the report and the title
could each show another abstract, and no check read any of them.

Now the abstract has a step of its own in the templates (``abstract``, after
the revision, before the paper is compiled):

* the abstract writer reads the final ``paper_draft.tex``, the headline result
  entries (the result values the paper's own text cites, ``headline_entries``)
  and what the reviewers said about the abstract (``abstract_findings.json``,
  whatever their score);
* the deterministic check below (:func:`check`) reads what it wrote. On a
  failure the writer is sent back once with the reasons; a second failure is
  recorded as a finding (``abstract_check.json``, a failed check in the
  dossier), never silently;
* the compiler puts ``abstract.tex`` into the paper (:func:`insert`): it
  replaces the draft's abstract environment, or adds one where the draft has
  none. The PDF, ``report.html`` and the study page then show one abstract.

``e2er abstract <folder>`` runs the same step on a study that is already
exported (``src/cli_abstract.py``).

The check's rules (``RULES``):

* at most ``MAX_WORDS`` words (keywords and JEL lines not counted);
* no p-values, confidence intervals ("95%", "interval"), standard errors,
  Fisher-z or test statistics;
* at most ``MAX_NUMBERS`` numbers; years, the base of a rate ("per 100,000")
  and digits that belong to a name (Gaia DR3, NUTS-2) are not counted;
* every counted number is a result: a value of the study's results files at
  the precision the abstract shows, with its sign (``unmatched``); a direction
  word next to an unsigned magnitude may carry the sign ("narrowed by 10.7" for
  -10.7), and one that contradicts it fails ("rose by 10.7"). Standard
  errors, p-values, t statistics and interval bounds are no results here, and
  a percentage matches a value times 100 only for a share or an estimate;
* no coefficient or estimate quoted as a raw number: a number next to an
  estimate word (estimate, coefficient, shift, effect, beta, slope) needs a
  plain unit (percentage points, percent, times, deaths per 100,000, Earth
  radii, ...); a signed decimal below 1 with no unit is a coefficient anywhere
  (``raw_estimates``);
* at least one sentence states a finding;
* the last sentence is not a negation and holds no "rather than";
* none of the constructions the researcher rejects: "rather than", "X, not Y",
  the mirrored "changed A; changed nothing about B", and the phrase check of
  every draft (``writing_check``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

ABSTRACT_FILE = "abstract.tex"
#: What the check found, written next to the abstract (exported to reviews/).
CHECK_FILE = "abstract_check.json"
#: What the reviewers and the self-attack said about the abstract, for the abstract step (exported to reviews/).
FINDINGS_FILE = "abstract_findings.json"

#: The amendment ``e2er abstract`` records for each file it changes (src/cli_abstract.py).
AMENDMENT_KIND = "abstract_rewritten"
AMENDMENT_REASON = (
    "abstract rewritten by e2er's abstract step after the abstract fix; the paper's text and results are unchanged"
)

#: The amendment of an abstract the researcher wrote (``e2er abstract --from-file``), checked like any other.
EDITED_KIND = "abstract_edited_by_researcher"
#: Both kinds: the abstract changed after export; verify's anchor rolls them back like redactions.
AMENDMENT_KINDS = (AMENDMENT_KIND, EDITED_KIND)
#: The only files ``e2er abstract`` changes: an abstract amendment of any other file is not one.
CHANGED_FILES = ("paper/abstract.tex", "paper/paper.tex", "paper/paper.pdf", "report.html")
#: The paper whose change ``e2er verify`` checks: everything outside the abstract stays byte for byte.
PAPER_FILE = "paper/paper.tex"

MAX_WORDS = 160
MAX_NUMBERS = 3

#: The rules, in the words the writer and the dossier read.
RULES: tuple[str, ...] = (
    f"at most {MAX_WORDS} words",
    "no p-values, confidence intervals, standard errors, Fisher-z or test statistics",
    f"at most {MAX_NUMBERS} numbers (years and the base of a rate such as 'per 100,000' do not count)",
    "every number is a value of the study's results at the precision shown",
    "no coefficient or estimate as a raw number: a number next to estimate, coefficient, shift, effect, beta or "
    "slope needs a plain unit (percentage points, percent, times, deaths per 100,000, ...); no signed decimal "
    "below 1 without a unit",
    "at least one sentence states a finding",
    "the last sentence is not a negation and has no 'rather than'",
    "no 'rather than', no 'X, not Y', no mirrored 'changed A; changed nothing about B', "
    "none of the constructions of the phrase check",
)

_ENV_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL)
_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
_KEYWORDS_RE = re.compile(r"\b(?:keywords?|key\s+words|jel(?:\s+(?:codes?|classification))?)\s*[:.]", re.IGNORECASE)


# ── reading an abstract ──────────────────────────────────────────────────────


def environment(tex: str) -> re.Match[str] | None:
    """The first ``\\begin{abstract} … \\end{abstract}`` of a LaTeX text (comments ignored for finding it)."""
    for m in _ENV_RE.finditer(tex):
        line_start = tex.rfind("\n", 0, m.start()) + 1
        if "%" not in re.sub(r"\\%", "", tex[line_start : m.start()]):
            return m
    return None


def _split_keywords(body: str) -> tuple[str, str]:
    """The abstract's text and its keywords / JEL lines (from the first such line on)."""
    stripped = _COMMENT_RE.sub("", body)
    m = _KEYWORDS_RE.search(stripped)
    if m is None:
        return body, ""
    # Cut at the line (or the \textbf{...} group) where the keywords begin, in the text with comments.
    line_start = stripped.rfind("\n", 0, m.start()) + 1
    head = stripped[line_start : m.start()]
    if re.search(r"[.!?]\s", head):  # keywords named inside a sentence: not a keywords line
        return body, ""
    marker = stripped[line_start:].strip().split("\n", 1)[0][:40]
    cut = body.find(marker) if marker else -1
    if cut < 0:
        return body, ""
    return body[:cut], body[cut:]


def body(abstract_tex: str) -> str:
    """The abstract's own text (LaTeX, comments kept): the environment's content without keywords / JEL lines."""
    m = environment(abstract_tex)
    inner = m.group(1) if m else abstract_tex
    text, _keywords = _split_keywords(inner)
    return text.strip()


_SIMPLE_COMMANDS = re.compile(r"\\(?:noindent|medskip|smallskip|bigskip|par|centering|small|footnotesize|normalsize)\b")
_TEXT_COMMANDS = re.compile(r"\\(?:textbf|textit|emph|text|textrm|mathrm|textsc|textsf|underline|mbox)\s*\{([^{}]*)\}")


def plain(tex: str) -> str:
    """LaTeX prose as a reader sees it: comments, commands and maths markup removed (for counting and the report)."""
    text = _COMMENT_RE.sub("", tex)
    for _ in range(3):
        text = _TEXT_COMMANDS.sub(r"\1", text)
    text = _SIMPLE_COMMANDS.sub(" ", text)
    replacements = (
        ("---", "\u2014"),
        ("--", "\u2013"),
        ("``", "\u201c"),
        ("''", "\u201d"),
        ("\\%", "%"),
        ("\\&", "&"),
        ("\\_", "_"),
        ("\\$", "$"),
        ("\\,", " "),
        ("\\;", " "),
        ("\\ ", " "),
        ("~", " "),
        ("^\\circ", "\u00b0"),
        ("^{\\circ}", "\u00b0"),
        ("\\times", "\u00d7"),
        ("\\approx", "\u2248"),
        ("\\leq", "\u2264"),
        ("\\geq", "\u2265"),
        ("\\\\", " "),
    )
    for a, b in replacements:
        text = text.replace(a, b)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = text.replace("$", "").replace("{", "").replace("}", "")
    return " ".join(text.split())


def words(abstract_tex: str) -> int:
    """Words of the abstract's text (keywords and JEL lines, comments and LaTeX commands not counted)."""
    return len([w for w in plain(body(abstract_tex)).split() if re.search(r"[A-Za-z0-9]", w)])


def sentences(text: str) -> list[str]:
    """The sentences of plain text (a full stop, ? or ! followed by a space and a capital or a digit)."""
    parts = re.split(r"(?<=[.!?])[\u201d\"')]?\s+(?=[A-Z0-9\u201c\"(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def readable(abstract_tex: str) -> str:
    """The abstract as plain text, for report.html and the study page (keywords left out)."""
    return plain(body(abstract_tex))


# ── the check ────────────────────────────────────────────────────────────────

#: Statistics an abstract does not report (name, pattern on the comment-free LaTeX).
_STATISTICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "a p-value",
        re.compile(r"\bp\s*[-\u2010\u2011]?\s*values?\b|(?<![A-Za-z\\])p\s*(?:<|>|=|\\leq?|\\geq?|\\le|\\ge)"),
    ),
    ("a confidence interval", re.compile(r"(?i:\b(?:confidence|credible|prediction)\s+intervals?\b)|\bCIs?\b")),
    ("an interval", re.compile(r"\bintervals?\b", re.IGNORECASE)),
    ("a 95% level", re.compile(r"\b95\s*(?:\\%|%|\s*per\s?cent)", re.IGNORECASE)),
    ("a standard error", re.compile(r"(?i:\bstandard\s+errors?\b|\bs\.\s?e\.)|\bSEs?\b")),
    ("Fisher-z", re.compile(r"\bfisher\b|\bz[-\s]?transform\w*", re.IGNORECASE)),
    (
        "a test statistic",
        re.compile(
            r"\btest\s+statistics?\b|\b[tzF][-\s]?stat(?:istic)?s?\b|\bchi[-\s]?squared?\b|\\chi|\u03c7"
            r"|(?<![A-Za-z\\])(?:t|z|F)\s*(?:\(\s*\d+\s*\))?\s*=",
            re.IGNORECASE,
        ),
    ),
)

#: A sentence that states what the study found: a verb of change or comparison, a magnitude word.
_FINDING_RE = re.compile(
    r"\b(?:find|finds|found|show|shows|showed|shown|reveal\w*|rise|rises|rose|risen|fall|falls|fell|fallen|"
    r"increase[sd]?|decrease[sd]?|decline[sd]?|grow|grows|grew|grown|raise[sd]?|reduce[sd]?|lower(?:s|ed)?|"
    r"higher|larger|smaller|greater|fewer|more|less|twice|thrice|times|half|double[sd]?|halve[sd]?|"
    r"account(?:s|ed)?\s+for|explain(?:s|ed)?|exceed(?:s|ed)?|differ(?:s|ed)?|concentrat\w+|dominat\w+|"
    r"outperform\w*|beat|beats|correlat\w+|associated|cluster\w*|peak\w*|share|shares|majority|most|"
    r"remain(?:s|ed)?|stable|unchanged|persist\w*|consist(?:s|ed)?\s+of|median|average|averages|percent)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(?:no|not|nor|never|none|nothing|neither|cannot)\b|n[\u2019']t\b", re.IGNORECASE)
_RATHER_RE = re.compile(r"\brather\s+than\b", re.IGNORECASE)
#: "patterns in the catalogue, not in the planet population": a positive claim, then its negated twin.
_COMMA_NOT_RE = re.compile(
    r"(?<!\bor),\s+(?:and\s+)?not\s+(?!only\b|least\b|just\b|merely\b|simply\b|even\b|yet\b|always\b|all\b|every\b)",
    re.IGNORECASE,
)
#: "changed A; changed nothing about B": the verb of the first clause repeated with a negation.
_MIRROR_RE = re.compile(
    r"\b([a-z]{4,})\b[^.;:!?]{1,120}[;,]\s+(?:(?:it|they|this|that|which|and|but|the\s+\w+)\s+)?"
    r"(?:(?:did|does|do|has|have|had|was|were|is|are)\s+)?\1\s+(?:nothing|none|no|not|never)\b",
    re.IGNORECASE,
)
_MIRROR_STOP = frozenset({"that", "this", "with", "from", "were", "have", "been", "their", "there", "which", "what"})
#: Digits that are part of a name: NUTS-2, COVID-19, Gaia DR3 (the number regex already skips DR3).
_NAME_DIGITS_RE = re.compile(r"[A-Za-z][-\u2010\u2011]$")
#: The number of a name written with a space: the S&P 500, the FTSE 100, NUTS 2.
_INDEX_NAME_RE = re.compile(r"(?<![A-Za-z])[A-Z][A-Z&\\]*[A-Z]\s+$")
#: A number that defines the sample, part of the question: "magnitude 5 and larger", "at least 30 years",
#: "within 3 degrees of the cluster centre".
_SAMPLE_BOUND_BEFORE_RE = re.compile(
    r"(?:\bat\s+(?:least|most)|\bmagnitudes?|\bover|\bunder|\babove|\bbelow|\bwithin|\binside|\bup\s+to)"
    r"\s*[\$\{(]*\s*$",
    re.I,
)
_SAMPLE_BOUND_AFTER_RE = re.compile(
    r"^[\$\})]*\s*(?:\+|\\?plus\b|and\s+(?:larger|above|higher|over|greater|older|bigger))", re.I
)


@dataclass
class AbstractCheck:
    """What the check found in one abstract."""

    passed: bool
    words: int
    numbers: list[str] = field(default_factory=list)
    #: Counted numbers that are no value of the results (at the precision shown).
    unmatched: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    #: Whether the results files were there to compare the numbers with.
    compared: bool = True

    def feedback(self) -> str:
        """The problems as one instruction for the abstract writer."""
        listed = "; ".join(f"({i}) {p}" for i, p in enumerate(self.problems, 1))
        return (
            f"The abstract check failed on {len(self.problems)} point(s): {listed}. Rewrite abstract.tex so that "
            "every rule holds: " + "; ".join(RULES) + ". Keep what the paper found; change only what the check names."
        )

    def detail(self) -> str:
        if self.passed:
            return f"{self.words} words, {len(self.numbers)} number(s), every number a result"
        return "; ".join(self.problems)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def counted_numbers(text_tex: str) -> list[tuple[str, float, bool]]:
    """The numbers the check counts in the abstract's text: (as written, value, is a percentage).

    Reuses the number check's reading of prose (``verify_numbers``): years, the
    base of a rate, confidence levels and period labels are not numbers here
    either, nor are the digits of a name (NUTS-2, COVID-19).
    """
    from .pipeline import verify_numbers as vn

    out: list[tuple[str, float, bool]] = []
    prose = vn._strip_latex_machinery(text_tex)
    for pn in vn._extract_prose_numbers(text_tex):
        value = vn._parse_number(pn.num_str)
        if value is None or pn.constant:
            continue
        if vn._YEAR_RE.fullmatch(pn.num_str.strip().lstrip("-")):
            continue
        if _is_name_digit(prose, pn.num_str) or _is_sample_bound(prose, pn.num_str):
            continue
        out.append((pn.num_str, value, pn.is_percent))
    return out


#: Words that make a number next to them an estimate: "the estimated shift is -0.0181".
_ESTIMATE_WORD_RE = re.compile(
    r"\b(?:estimates?|estimated|coefficients?|shifts?|shifted|effects?|beta|elasticit(?:y|ies)|slopes?|parameters?)\b"
    r"|\\beta\b|\u03b2",
    re.IGNORECASE,
)
#: A plain unit after a number: the magnitude in terms people use (percentage points, percent, times, deaths ...).
_PLAIN_UNIT_RE = re.compile(
    r"^[\s~$}]*(?:\\[,;: ]\s*)*(?:\\?%|per\s?cent\b|percentage\s+points?\b|(?:\w+\s+)?points?\b|times\b|-?fold\b"
    r"|degrees?\b|\u00b0|\^\s*\{?\\circ|earth\s+radi|radii\b|deaths?\b|days?\b|years?\b|months?\b|weeks?\b"
    r"|hours?\b|minutes?\b|km\b|kilomet|met(?:re|er)s?\b|kg\b|tonnes?\b|countries\b|regions\b|planets\b|stars\b"
    r"|events\b|earthquakes\b|novels\b|words\b|hits\b|people\b|persons\b|children\b|pupils\b|firms\b"
    r"|households\b|trades\b|per\s+(?:[\d{]|capita|year|decade|month|week|day|hour|person|inhabitant|head|km)|(?:us\s+)?dollars?\b|euros?\b|\\\$)",
    re.IGNORECASE,
)


def raw_estimates(text_tex: str) -> list[tuple[str, str]]:
    """Numbers quoted as raw estimates (coefficients): (as written, its neighbourhood).

    A number next to an estimate word (estimate, coefficient, shift, effect, beta, slope ...)
    is a raw estimate unless a plain unit follows it (percentage points, percent, times,
    deaths per 100,000, Earth radii, ...). A signed decimal below 1 with no unit is one
    wherever it stands ("-0.0181").
    """
    from .pipeline import verify_numbers as vn

    prose = vn._strip_latex_machinery(text_tex)
    out: list[tuple[str, str]] = []
    for num_str, value, is_percent in counted_numbers(text_tex):
        if is_percent:
            continue
        for m in _spots(prose, num_str.lstrip("+-")):
            start = m.start()
            head = prose[max(0, start - 90) : start]
            cut = max(head.rfind(". "), head.rfind("? "), head.rfind("! "))
            before = head[cut + 1 :] if cut >= 0 else head
            after = prose[m.end() : m.end() + 40]
            if _PLAIN_UNIT_RE.match(after):
                continue
            signed = num_str.startswith(("-", "+")) or bool(re.search(r"[-\u2212+]\s*\$?\s*$", before))
            if _ESTIMATE_WORD_RE.search(before) or (signed and abs(value) < 1 and value != int(value)):
                near = " ".join(prose[max(0, start - 40) : m.end() + 30].split())
                out.append((num_str, near))
                break
    return out


def _spots(prose: str, num_str: str) -> list[re.Match[str]]:
    return list(re.finditer(rf"(?<![\d.,]){re.escape(num_str)}(?![\d])", prose))


def _is_sample_bound(prose: str, num_str: str) -> bool:
    """Does ``num_str`` only define the sample ("magnitude 5 and larger", "at least 30 years")?

    "or larger" does not make a bound: "could detect an increase of 0.148 or larger" states a result.
    """
    spots = _spots(prose, num_str)
    return bool(spots) and all(
        _SAMPLE_BOUND_BEFORE_RE.search(prose[max(0, m.start() - 20) : m.start()])
        or _SAMPLE_BOUND_AFTER_RE.match(prose[m.end() : m.end() + 20])
        for m in spots
    )


def _is_name_digit(prose: str, num_str: str) -> bool:
    """Is every occurrence of ``num_str`` in the prose glued to a name by a hyphen (NUTS-2, COVID-19)?"""
    spots = [m.start() for m in _spots(prose, num_str)]
    whole = re.fullmatch(r"\d+", num_str) is not None
    return bool(spots) and all(
        _NAME_DIGITS_RE.search(prose[max(0, s - 2) : s]) or (whole and _INDEX_NAME_RE.search(prose[max(0, s - 12) : s]))
        for s in spots
    )


#: Words that carry a magnitude's sign: "the gap narrowed by 10.7 points" states -10.7 (2026-10-25 live test).
_DOWN_RE = re.compile(
    r"\b(?:fell|fall(?:s|ing|en)?|declin(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|narrow(?:s|ed|ing)?|drop(?:s|ped|ping)?"
    r"|lower|reduc(?:e|es|ed|ing|tion)|shr(?:ank|unk|inks?|inking))\b",
    re.IGNORECASE,
)
_UP_RE = re.compile(
    r"\b(?:rose|ris(?:e|es|en|ing)|increas(?:e|es|ed|ing)|widen(?:s|ed|ing)?|higher|gr(?:ew|ows?|own|owing))\b",
    re.IGNORECASE,
)
#: What ends the stretch of prose a direction word may stand in: a clause or sentence boundary.
_CLAUSE_END_RE = re.compile(r"[,;:.!?()]")
#: How many words next to a number may carry its direction ("fell by 10.7", "10.7 percentage points lower").
_DIRECTION_WORDS = 4


def direction(prose: str, num_str: str) -> int:
    """The sign a direction word next to the number gives it: -1 (fell, declined, narrowed, lower ...),
    +1 (rose, increased, widened, higher ...), 0 for none or both.

    Only the few words right before the number and right after it count, and only in its own clause:
    "fell from 17.7 to 8.5" is not read as a fall of 8.5 here, because a level matches as it stands.
    """
    signs: set[int] = set()
    for m in _spots(prose, num_str):
        before = prose[max(0, m.start() - 80) : m.start()]
        cut = max((c.end() for c in _CLAUSE_END_RE.finditer(before)), default=0)
        before = " ".join(before[cut:].split()[-_DIRECTION_WORDS:])
        after = prose[m.end() : m.end() + 80]
        stop = _CLAUSE_END_RE.search(after)
        after = " ".join(after[: stop.start() if stop else len(after)].split()[:_DIRECTION_WORDS])
        near = f"{before} {after}"
        down, up = bool(_DOWN_RE.search(near)), bool(_UP_RE.search(near))
        if down != up:
            signs.add(-1 if down else 1)
        else:
            signs.add(0)
    return signs.pop() if len(signs) == 1 else 0


def source_values(workspace: Path) -> dict[str, float]:
    """Every numeric value of the study's results files (those the number check reads), by dotted key."""
    from .pipeline import verify_numbers as vn

    values: dict[str, float] = {}
    for name, path in vn._find_source_jsons(workspace).items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key, v in vn._flatten_json(data).items():
            values[f"{name}#{key}"] = v
    return values


#: Result keys an abstract never quotes (the rules forbid test statistics): their values are not results here.
_STATISTIC_LEAF = re.compile(
    r"^(?:se|std_?err(?:or)?|standard_error|p|p_?val(?:ue)?|pvalue|t|t_?stat(?:istic)?|t_?value|z|z_?stat|"
    r"ci|ci_.*|.*_ci|conf(?:idence)?_?int(?:erval)?.*|lower|upper|lo|hi)$",
    re.IGNORECASE,
)
#: Result keys whose value is a share or an estimate: only these may be quoted as a percentage (x 100).
_SHARE_TOKENS = frozenset(
    {"share", "shares", "proportion", "fraction", "frac", "prop", "estimate", "est", "coef", "coefficient", "beta",
     "effect", "att", "ate", "rate", "pct", "percent", "percentage"}
)  # fmt: skip


def _leaf(key: str) -> str:
    """The last name of a dotted result key (``estimation_results.json#main.x.estimate`` → ``estimate``)."""
    tail = key.split("#", 1)[-1]
    if tail.endswith("#key"):
        return ""  # a key that is itself a number (a grid point, a year): no name
    tail = re.sub(r"\[\d+\]", "", tail)
    return tail.rsplit(".", 1)[-1]


def _is_statistic(key: str) -> bool:
    return bool(_STATISTIC_LEAF.match(_leaf(key)))


def _is_share(key: str) -> bool:
    return bool(_SHARE_TOKENS & set(re.split(r"[_\W]+", _leaf(key).lower())))


def _is_result(num_str: str, value: float, is_percent: bool, sources: dict[str, float]) -> bool:
    """Is the abstract's number a value of the results at the precision shown? Signs count (no absolute values);
    standard errors, p-values, t statistics and interval bounds are left out; a percentage is a share or an
    estimate times 100."""
    from .pipeline import verify_numbers as vn

    for key, sv in sources.items():
        if _is_statistic(key):
            continue
        if vn._values_match(value, sv) or vn._matches_rounded(num_str, sv):
            return True
        if is_percent and -1 <= sv <= 1 and _is_share(key) and vn._matches_rounded(num_str, sv * 100):
            return True
    return False


def check(
    abstract_tex: str,
    *,
    sources: dict[str, float] | None = None,
    design: set[float] | frozenset[float] = frozenset(),
    economics: bool = True,
) -> AbstractCheck:
    """The deterministic check of an abstract (see the module docstring for the rules).

    ``sources`` are the results' values (:func:`source_values`); None skips the
    comparison (and says so). ``design`` holds the study's design settings,
    which a number may repeat without being a result.
    """
    from . import writing_check as wc

    problems: list[str] = []
    if environment(abstract_tex) is None:
        problems.append("abstract.tex has no \\begin{abstract} ... \\end{abstract}")
    text_tex = body(abstract_tex)
    clean = _COMMENT_RE.sub("", text_tex)
    text = plain(text_tex)
    n_words = len([w for w in text.split() if re.search(r"[A-Za-z0-9]", w)])
    if n_words == 0:
        problems.append("the abstract is empty")
    elif n_words > MAX_WORDS:
        problems.append(f"{n_words} words, more than {MAX_WORDS}: cut it to the question, the design and the finding")

    reported: list[tuple[int, int]] = []
    for name, rx in _STATISTICS:
        m = rx.search(clean)
        if m is None or any(a <= m.start() < b for a, b in reported):
            continue  # "confidence interval" is one problem, not two
        reported.append((m.start(), m.end()))
        near = " ".join(clean[max(0, m.start() - 30) : m.end() + 30].split())
        problems.append(f"it reports {name} ({near!r}); say what the result means in plain words")

    nums = counted_numbers(text_tex)
    shown = [n for n, _v, _p in nums]
    if len(nums) > MAX_NUMBERS:
        problems.append(
            f"{len(nums)} numbers ({', '.join(shown)}), more than {MAX_NUMBERS}: keep the one to three headline "
            "magnitudes and say the rest in words"
        )
    unmatched: list[str] = []
    contradicted: list[str] = []
    if sources is not None:
        from .pipeline import verify_numbers as vn

        prose = vn._strip_latex_machinery(text_tex)
        for num_str, value, is_percent in nums:
            if _is_result(num_str, value, is_percent, sources) or value in design:
                continue
            # An unsigned magnitude whose sign a direction word carries: "narrowed by 10.7" for -10.7.
            negative = (
                value > 0 and not num_str.startswith("+") and _is_result(f"-{num_str}", -value, is_percent, sources)
            )
            sign = direction(prose, num_str) if negative else 0
            if sign < 0:
                continue
            if sign > 0:
                contradicted.append(num_str)
            else:
                unmatched.append(num_str)
        if unmatched:
            problems.append(
                f"{', '.join(unmatched)} {'is' if len(unmatched) == 1 else 'are'} no value of the study's results "
                "at the precision shown: state only numbers the results files hold, each with its % src: line"
            )
        for num_str in contradicted:
            problems.append(
                f"{num_str} is said to rise, but the result is -{num_str}: say that it fell (declined, narrowed) "
                "by that much, or give the sign"
            )
        unmatched += contradicted

    for num_str, near in raw_estimates(text_tex):
        problems.append(
            f"{num_str} is quoted as a raw estimate ({near!r}): give the magnitude in a plain unit "
            '(percentage points, percent, times, deaths per 100,000, ...) or in words ("under two correlation points")'
        )

    found = sentences(text)
    if found and not any(_FINDING_RE.search(s) for s in found):
        problems.append("no sentence states what the study found")
    if found:
        last = found[-1]
        if _RATHER_RE.search(last):
            problems.append(f"the last sentence has 'rather than': {last!r}")
        elif _NEGATION_RE.search(last):
            problems.append(f"the last sentence is a negation: {last!r}; end on what the study shows")

    seen: set[str] = set()
    for s in found:
        if _RATHER_RE.search(s) and "rather than" not in seen:
            seen.add("rather than")
            problems.append(f"'rather than' in: {s!r}")
        if _COMMA_NOT_RE.search(s):
            problems.append(f"'X, not Y' in: {s!r}; state the positive claim and stop")
        m = _MIRROR_RE.search(s)
        if m and m.group(1).lower() not in _MIRROR_STOP:
            problems.append(f"a mirrored construction ('{m.group(1)} ...; {m.group(1)} nothing/no ...') in: {s!r}")
    for hit in wc.find(text_tex):
        if hit.phrase == "rather than":
            continue  # named above, once per sentence
        problems.append(hit.line())
    if not economics:
        problems += [h.line() for h in wc.jel_lines(abstract_tex)]

    return AbstractCheck(
        passed=not problems,
        words=n_words,
        numbers=shown,
        unmatched=unmatched,
        problems=problems,
        compared=sources is not None,
    )


def check_workspace(workspace: Path, *, economics: bool | None = None) -> AbstractCheck:
    """The check of ``abstract.tex`` in a run's workspace, against the workspace's results files."""
    from .pipeline import verify_numbers as vn
    from .pipeline.result_kinds import active_economics

    path = workspace / ABSTRACT_FILE
    if not path.is_file():
        return AbstractCheck(passed=False, words=0, problems=["the abstract writer wrote no abstract.tex"])
    tex = path.read_text(encoding="utf-8", errors="replace")
    sources = source_values(workspace)
    return check(
        tex,
        sources=sources if sources else None,
        design=vn.design_constants(workspace),
        economics=active_economics() if economics is None else economics,
    )


# ── putting it into the paper ────────────────────────────────────────────────


def block(abstract_tex: str) -> str:
    """What goes into the paper: the abstract environment and the keywords / JEL lines that follow it."""
    m = environment(abstract_tex)
    if m is None:
        inner = re.sub(r"\\(?:title|author|date)\s*\{[^{}]*\}|\\maketitle\b", "", abstract_tex).strip()
        return "\\begin{abstract}\n" + inner + "\n\\end{abstract}"
    env = m.group(0)
    rest = abstract_tex[m.end() :].strip()
    if rest and _KEYWORDS_RE.search(_COMMENT_RE.sub("", rest)):
        return env + "\n\n" + rest
    # Only the source comments may follow the environment (``% src:`` lines).
    comments = "\n".join(line for line in rest.splitlines() if line.strip().startswith("%"))
    return env + ("\n" + comments if comments else "")


def has_keywords(tex: str) -> bool:
    return bool(_KEYWORDS_RE.search(_COMMENT_RE.sub("", tex)))


def _drop_following_keywords(tail: str) -> str:
    """The text after the draft's abstract without a keywords / JEL paragraph right at its start."""
    m = re.match(r"(\s*(?:\\(?:medskip|smallskip|bigskip|vspace\{[^}]*\})\s*)*)", tail)
    start = m.end() if m else 0
    para_end = tail.find("\n\n", start)
    para = tail[start : para_end if para_end >= 0 else len(tail)]
    if para.strip() and _KEYWORDS_RE.search(_COMMENT_RE.sub("", para)) and len(para) < 600:
        return "\n" + tail[para_end if para_end >= 0 else len(tail) :]
    return tail


def insert(paper_tex: str, abstract_tex: str) -> str:
    """``paper_tex`` with the abstract of ``abstract_tex``: in place of its abstract, else where one belongs.

    Where one belongs: after ``\\maketitle``, else before the first
    ``\\section``, else after ``\\begin{document}``, else at the start. A
    keywords line that followed the draft's own abstract goes when the new
    abstract brings its own.
    """
    blk = block(abstract_tex)
    m = environment(paper_tex)
    if m is not None:
        tail = paper_tex[m.end() :]
        if has_keywords(blk):
            tail = _drop_following_keywords(tail)
        return paper_tex[: m.start()] + blk + tail
    for rx, after in ((r"\\maketitle\b[^\n]*\n?", True), (r"\\section\*?\{", False), (r"\\begin\{document\}\n?", True)):
        found = re.search(rx, paper_tex)
        if found:
            at = found.end() if after else found.start()
            return paper_tex[:at] + "\n" + blk + "\n\n" + paper_tex[at:]
    return blk + "\n\n" + paper_tex


_TITLE_RE = re.compile(r"\\title\s*\{")


def title_command(tex: str) -> str | None:
    """The ``\\title{...}`` command of a LaTeX text (balanced braces), or None."""
    from .renderer.templates import _extract_braced

    m = _TITLE_RE.search(_COMMENT_RE.sub("", tex))
    if m is None:
        return None
    content, _rest = _extract_braced(_COMMENT_RE.sub("", tex), "title")
    return None if content is None else "\\title{" + content.strip() + "}"


def with_title(abstract_tex: str, title: str | None) -> str:
    """``abstract_tex`` with ``title`` (a ``\\title{...}`` command) on its first line, unless it has one.

    The study's title is read from abstract.tex (research_object), as it was when the
    abstract writer wrote it; the paper's own title keeps it the paper's.
    """
    if not title or title_command(abstract_tex) is not None:
        return abstract_tex
    return title + "\n\n" + abstract_tex.lstrip()


def insert_into_file(paper: Path, abstract: Path) -> bool:
    """Put ``abstract`` into ``paper`` (both LaTeX files); True when the paper changed."""
    if not paper.is_file() or not abstract.is_file():
        return False
    before = paper.read_text(encoding="utf-8")
    after = insert(before, abstract.read_text(encoding="utf-8"))
    if after == before:
        return False
    paper.write_text(after, encoding="utf-8", newline="\n")
    return True


# ── the record of a change to the paper (e2er abstract) and its check ───────


def block_span(tex: str) -> tuple[int, int] | None:
    """Where the paper's abstract is: its environment, the comment lines right after it (``% src:``) and a
    keywords / JEL paragraph that follows it (the part :func:`insert` replaces). None without one."""
    m = environment(tex)
    if m is None:
        return None
    pos = m.end()
    while True:
        c = re.match(r"[ \t]*\n[ \t]*%[^\n]*", tex[pos:])
        if c is None:
            break
        pos += c.end()
    tail = tex[pos:]
    dropped = _drop_following_keywords(tail)
    if dropped != tail:
        pos = len(tex) - (len(dropped) - 1)
    return m.start(), pos


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def paper_change(before: bytes, after: bytes) -> dict[str, Any]:
    """The record of the paper's change (``abstract_before`` of the amendment): where the bytes differ, the text
    that stood there before, how long the new text is, and the fingerprint of the abstract before.

    With it, ``e2er verify`` rebuilds the paper as it was (:func:`paper_problem`); the old text was
    published with the paper, so recording it reveals nothing.
    """
    n = min(len(before), len(after))
    p = 0
    while p < n and before[p] == after[p]:
        p += 1
    s = 0
    while s < n - p and before[len(before) - 1 - s] == after[len(after) - 1 - s]:
        s += 1
    # Whole characters: the cut never falls inside a UTF-8 sequence.
    while 0 < p < len(before) and before[p] & 0xC0 == 0x80:
        p -= 1
    while s > 0 and before[len(before) - s] & 0xC0 == 0x80:
        s -= 1
    old = before.decode("utf-8", errors="replace")
    span = block_span(old)
    return {
        "offset": p,
        "text": before[p : len(before) - s].decode("utf-8"),
        "length_after": len(after) - p - s,
        "sha256": _sha(old[span[0] : span[1]].encode("utf-8")) if span else None,
    }


def _outside(tex: str) -> tuple[str, str] | None:
    span = block_span(tex)
    if span is None:
        return None
    return tex[: span[0]].rstrip(), tex[span[1] :].lstrip()


def paper_problem(entry: dict[str, Any], now: bytes | None) -> tuple[str | None, bytes | None]:
    """Check an abstract amendment of paper/paper.tex against the paper as it is now: (why not, or None; the
    paper as it was before the amendment, rebuilt from the record, or None).

    The paper rebuilt with the recorded old text must have the fingerprint the amendment names, and
    everything outside the abstract (its environment, its ``% src:`` lines and keywords paragraph, the
    blank lines around it) must be byte for byte the same before and after. A record without
    ``abstract_before`` (e2er before this check) cannot be checked.
    """
    path = entry.get("path")
    rec = entry.get("abstract_before")
    if not isinstance(rec, dict):
        why = f"{path}: the abstract amendment does not record the text it replaced, so the change cannot be checked"
        return why, None
    off, text, length = rec.get("offset"), rec.get("text"), rec.get("length_after")
    if not (
        isinstance(off, int)
        and not isinstance(off, bool)
        and off >= 0
        and isinstance(text, str)
        and isinstance(length, int)
        and not isinstance(length, bool)
        and length >= 0
    ):
        return f"{path}: the abstract amendment's record is incomplete", None
    if now is None:
        return f"{path} is missing", None
    if off + length > len(now):
        return f"{path}: the abstract amendment's record does not fit the file", None
    before = now[:off] + text.encode("utf-8") + now[off + length :]
    if _sha(before) != entry.get("sha256_before"):
        return f"{path}: rebuilt with the recorded old abstract, the paper is not the one before the amendment", None
    try:
        old, new = before.decode("utf-8"), now.decode("utf-8")
    except UnicodeDecodeError:
        return f"{path} is not UTF-8 text", None
    old_span, new_out = block_span(old), _outside(new)
    if new_out is None:
        return f"{path}: the paper has no abstract after the abstract amendment", None
    if old_span is None:
        # The abstract was added where none was: the old paper is the new one without it.
        head, tail = new_out
        ok = old.startswith(head) and old.endswith(tail) and not old[len(head) : len(old) - len(tail)].strip()
        sha_ok = rec.get("sha256") is None
    else:
        ok = _outside(old) == new_out
        sha_ok = rec.get("sha256") == _sha(old[old_span[0] : old_span[1]].encode("utf-8"))
    if not ok:
        return f"{path}: the abstract amendment changed the paper outside its abstract", None
    if not sha_ok:
        return f"{path}: the recorded fingerprint of the old abstract is not the old paper's abstract", None
    return None, before


# ── what the abstract writer reads ───────────────────────────────────────────

_SRC_RE = re.compile(r"%\s*src:\s*([^\n]+)")


def _resolve(data: Any, path: str) -> Any:
    cur = data
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("[") or (part.isdigit() and isinstance(cur, list)):
            idx = int(part.strip("[]"))
            if not isinstance(cur, list) or idx >= len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def headline_entries(paper_tex: str, workspace: Path, limit: int = 60) -> list[str]:
    """The result values the paper's own text cites (its ``% src:`` notes), each as ``file#key = value``.

    The abstract reports a headline the paper states; these are the values the
    paper states, read from the results files. Without such notes: the
    scalar entries of the main results file, up to ``limit``.
    """
    cache: dict[str, Any] = {}

    def load(name: str) -> Any:
        if name not in cache:
            try:
                cache[name] = json.loads((workspace / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache[name] = None
        return cache[name]

    out: list[str] = []
    seen: set[str] = set()
    for m in _SRC_RE.finditer(paper_tex):
        current_file = ""
        for raw in m.group(1).split(","):
            ref = raw.strip().rstrip(".;")
            if not ref:
                continue
            if "#" in ref:
                current_file, key = ref.split("#", 1)
                current_file = current_file.strip().split("/")[-1]
            else:
                key = ref
            if not current_file or key in ("", "key"):
                continue
            entry = f"{current_file}#{key.strip()}"
            if entry in seen:
                continue
            seen.add(entry)
            value = _resolve(load(current_file), key.strip())
            if value is None or isinstance(value, dict | list):
                continue
            out.append(f"{entry} = {json.dumps(value)}")
            if len(out) >= limit:
                return out
    if out:
        return out
    from .pipeline import verify_numbers as vn

    for name, path in vn._find_source_jsons(workspace).items():
        data = load(path.name)
        for key, value in vn._flatten_json(data).items():
            if key.endswith("#key"):
                continue
            out.append(f"{name}#{key} = {json.dumps(value)}")
            if len(out) >= limit:
                return out
    return out


def findings_block(workspace: Path) -> str:
    """What the reviewers and the self-attack said about the abstract (``abstract_findings.json``), for the writer."""
    try:
        doc = json.loads((workspace / FINDINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    items = [f for f in doc.get("findings") or [] if isinstance(f, dict) and f.get("problem")]
    if not items:
        return ""
    lines = [f"- ({f.get('source_detail') or f.get('source')}) {str(f['problem'])[:700]}" for f in items[:12]]
    return "## What the reviewers said about the abstract (address each point)\n" + "\n".join(lines)


ABSTRACT_FOCUS = (
    "Write the abstract of the finished paper into `abstract.tex`: one \\begin{abstract} ... \\end{abstract} "
    "environment and nothing else around it (no \\title, no \\documentclass), with the keywords (and, in an "
    "economics paper only, the JEL codes) on lines inside the environment after the text. The paper is final: "
    "it is below, as the revision left it, with the headline result values it cites. Follow your "
    "writing/abstract skill: the question, the design and the data, the finding in plain words with one to "
    "three headline magnitudes in plain units, each number followed by its own `% src: <file>#<key>` line, "
    "and what the finding means. Every statement must be one the paper makes and every number a value of the "
    "results. The paper's own abstract, if it has one, is not your template: write from the paper's results. "
    "A check reads the abstract after you: " + "; ".join(RULES) + "."
)


def work_context(workspace: Path, paper_id: str, *, max_paper_chars: int = 60000) -> str:
    """The abstract writer's context: the study, the final paper, the headline entries, the reviewers' points."""
    from .strategist.context import build_tier0_context

    paper_path = workspace / "paper_draft.tex"
    paper = paper_path.read_text(encoding="utf-8", errors="replace") if paper_path.is_file() else ""
    cut = len(paper) > max_paper_chars
    parts = [build_tier0_context(workspace, paper_id)]
    parts.append(
        "## The final paper (paper_draft.tex)"
        + (f" (first {max_paper_chars} characters; read the file for the rest)" if cut else "")
        + "\n```latex\n"
        + paper[:max_paper_chars]
        + "\n```"
    )
    entries = headline_entries(paper, workspace)
    if entries:
        parts.append(
            "## Headline result entries (the values the paper cites, from the results files)\n"
            + "\n".join(f"- {e}" for e in entries)
        )
    points = findings_block(workspace)
    if points:
        parts.append(points)
    return "\n\n".join(parts)


# ── the step ────────────────────────────────────────────────────────────────


@dataclass
class AbstractOutcome:
    """How the abstract step ended."""

    passed: bool
    attempts: int
    check: AbstractCheck
    #: Each attempt's check, oldest first.
    history: list[dict[str, Any]] = field(default_factory=list)

    def record(self) -> dict[str, Any]:
        """``abstract_check.json``: the verdict, the rules and every attempt's problems."""
        return {
            "passed": self.passed,
            "attempts": self.attempts,
            "rules": list(RULES),
            "words": self.check.words,
            "numbers": self.check.numbers,
            "unmatched": self.check.unmatched,
            "problems": self.check.problems,
            "history": self.history,
            **(
                {}
                if self.passed
                else {
                    "finding": "The abstract failed its check after one resend; the paper carries it as written, "
                    "and the problems above are open."
                }
            ),
        }


Execute = Callable[[str], Awaitable[bool]]


async def write_abstract(
    workspace: Path,
    execute: Execute,
    *,
    resend: bool = True,
    economics: bool | None = None,
) -> AbstractOutcome:
    """The abstract step: the writer once, the check, at most one resend with the reasons.

    ``execute(focus)`` runs the abstract writer once with that work-order focus
    (the caller supplies the backend and the context) and returns whether the
    call succeeded. ``resend=False`` (a regime that does not enforce the check)
    records the verdict without sending the writer back. Writes
    ``abstract_check.json``; never raises on a failed check.
    """
    history: list[dict[str, Any]] = []
    focus = ABSTRACT_FOCUS
    result: AbstractCheck | None = None
    attempts = 0
    for attempt in (1, 2):
        attempts = attempt
        ok = await execute(focus)
        result = check_workspace(workspace, economics=economics)
        if not ok and not (workspace / ABSTRACT_FILE).is_file():
            result.problems.insert(0, "the abstract writer's call failed")
        history.append({"attempt": attempt, "passed": result.passed, "problems": list(result.problems)})
        if result.passed or not resend or attempt == 2:
            break
        focus = ABSTRACT_FOCUS + "\n\n## Sent back by the abstract check\n" + result.feedback()
    assert result is not None
    outcome = AbstractOutcome(passed=result.passed, attempts=attempts, check=result, history=history)
    try:
        (workspace / CHECK_FILE).write_text(
            json.dumps(outcome.record(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
    except OSError as e:
        logger.warning("could not write %s: %s", CHECK_FILE, e)
    return outcome
