"""The phrase check: constructions the researcher rejects in a draft, with the sentences that carry them.

A live run kept "Against this background" in its draft although the
researcher had told the writer not to use it. An instruction is a request; this
check is a gate. It reads the prose of a draft (``paper_draft.tex``,
``abstract.tex``) and names every sentence that uses one of the constructions
below, so the writer is sent back with the exact sentences to rewrite.

The list comes from the researcher's writing guidance (the ``writing`` skill's
personal style and his feedback on generated prose). Every pattern is chosen
to have few false positives; a construction that cannot be detected reliably
from the text alone (a triad of adjectives used for rhythm) is not checked.

Quotations (``\\begin{quote}``, ````…''``, ``"…"``, ``\\enquote{…}``), citations,
comments, maths, tables, verbatim text and the bibliography are left out: a
quoted source may say what it says.

Used by the output contract of the draft writers (``contract_check``) and as a
non-blocking note in ``e2er verify``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: (name, pattern, what to do instead). Matched case-insensitively against the prose.
_PHRASES: tuple[tuple[str, str, str], ...] = (
    (
        "Against this background",
        r"\bagainst\s+(?:this|that|the)\s+(?:background|backdrop)\b",
        "pivot to the contribution directly (for instance: To keep these quantities apart, we propose ...)",
    ),
    (
        "rather than",
        r"\brather\s+than\b",
        "state the positive claim and stop",
    ),
    (
        "not only X but also Y",
        r"\bnot\s+(?:only|just|merely|simply)\b[^.;:!?]{1,80}?\bbut\b",
        "state each point in its own sentence",
    ),
    (
        "not X but Y",
        # "not significant but positive", "is not a test, but a check". A negated
        # action followed by a comma ("we do not observe X, but we infer Y") is a
        # concession, not this construction, and is left alone.
        r"(?<!\bdo\s)(?<!\bdoes\s)(?<!\bdid\s)(?<!\bcan\s)(?<!\bcould\s)(?<!\bwould\s)(?<!\bshould\s)"
        r"(?<!\bwill\s)(?<!\bmay\s)(?<!\bmight\s)(?<!\bmust\s)"
        r"\bnot\s+(?!only\b|just\b|merely\b|simply\b)(?:[^.;:!?,]{1,60}?\s+but\b|[^.;:!?,]{1,45},\s*but\b)",
        "state the positive claim and stop",
    ),
    (
        "It is important to note",
        r"\bit\s+is\s+(?:important|worth)\s+(?:to\s+note|noting)\b|\bit\s+should\s+be\s+noted\b",
        "make the point directly",
    ),
    (
        "In this section, we",
        r"\bin\s+this\s+section,?\s+we\b",
        "lead with the substance of the section",
    ),
    ("delve", r"\bdelv(?:e|es|ed|ing)\b", "say what the paper examines"),
    ("a testament to", r"\ba\s+testament\s+to\b", "state the evidence"),
    (
        "plays a crucial role",
        r"\b(?:play|plays|played|playing)\s+a\s+(?:crucial|pivotal|vital)\s+role\b",
        "say what it does and how much",
    ),
    (
        "navigate the complexities",
        r"\bnavigat(?:e|es|ed|ing)\s+the\s+complexit(?:y|ies)\b",
        "name the difficulty",
    ),
)
_COMPILED = tuple((name, re.compile(rx, re.IGNORECASE), fix) for name, rx, fix in _PHRASES)

#: Em-dashes allowed on one page of prose (about 500 words); more is a chain.
EM_DASHES_PER_PAGE = 2
_WORDS_PER_PAGE = 500
_EM_DASH_RE = re.compile(r"\u2014|(?<!-)---(?!-)")

#: Constructions the check names, in the order of the list above (for documentation and tests).
PHRASES: tuple[str, ...] = tuple(name for name, _rx, _fix in _PHRASES) + ("em-dash chain",)

_DROP_ENVS = (
    "quote",
    "quotation",
    "verbatim",
    "lstlisting",
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "eqnarray",
    "eqnarray*",
    "displaymath",
    "math",
    "table",
    "table*",
    "tabular",
    "tabular*",
    "figure",
    "figure*",
    "thebibliography",
    "comment",
)
# Commands whose argument is not the writer's prose: citations, references, labels, files, addresses.
_ARG_COMMANDS = (
    r"\\(?:[a-zA-Z]*cite[a-zA-Z]*\*?|ref|eqref|autoref|cref|Cref|pageref|label|input|include|url|"
    r"bibliography|bibliographystyle|includegraphics|enquote|texttt|verb)"
    r"(?:\[[^\]]*\]){0,2}\{[^{}]*\}"
)


def _strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", tex)


def _blank(m: re.Match[str]) -> str:
    """The match replaced by spaces of the same length (newlines kept), so offsets stay valid."""
    return re.sub(r"[^\n]", " ", m.group(0))


def prose(tex: str) -> str:
    """The prose of a LaTeX text, with everything that is not the writer's own words blanked out.

    Blanked, not removed: offsets into the result are offsets into the
    comment-free source, so a sentence can be quoted as the writer wrote it.
    """
    text = _strip_comments(tex)
    for env in _DROP_ENVS:
        e = re.escape(env)
        text = re.sub(rf"\\begin\{{{e}\}}.*?\\end\{{{e}\}}", _blank, text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)", _blank, text, flags=re.DOTALL)
    text = re.sub(r"(?<!\\)\$[^$]*?(?<!\\)\$", _blank, text)
    text = re.sub(_ARG_COMMANDS, _blank, text)
    text = re.sub(r"``.*?''", _blank, text, flags=re.DOTALL)  # ``a quotation''
    text = re.sub(r"\u201c.*?\u201d", _blank, text, flags=re.DOTALL)  # "a quotation"
    text = re.sub(r'(?<![\w\\])".{1,400}?"', _blank, text, flags=re.DOTALL)
    return text


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence around ``text[start:end]``, whitespace collapsed, at most 300 characters."""
    # A sentence ends at its punctuation, a blank line, or a LaTeX command on a line of its own.
    left = max(text.rfind(c, 0, start) for c in (". ", "? ", "! ", "\n\n", ".\n", "}\n"))
    left = 0 if left < 0 else left + 1
    rights = [i for i in (text.find(c, end) for c in (". ", "? ", "! ", "\n\n", ".\n", "\n\\")) if i != -1]
    right = min(rights) + 1 if rights else len(text)
    s = " ".join(text[left:right].split())
    return s if len(s) <= 300 else s[:297] + "..."


@dataclass(frozen=True)
class Hit:
    """One construction found in the prose: which, the sentence, and what to do instead."""

    phrase: str
    sentence: str
    fix: str

    def line(self) -> str:
        return f'"{self.phrase}" in: {self.sentence} ({self.fix})'


def find(tex: str) -> list[Hit]:
    """Every banned construction in the prose of ``tex``, in the order they occur."""
    source = _strip_comments(tex)
    text = prose(tex)
    found: list[tuple[int, Hit]] = []
    for name, rx, fix in _COMPILED:
        for m in rx.finditer(text):
            found.append((m.start(), Hit(name, _sentence(source, m.start(), m.end()), fix)))
    found.sort(key=lambda p: p[0])
    hits = [h for _pos, h in found]
    hits += _em_dash_chains(source, text)
    return hits


def _em_dash_chains(source: str, text: str) -> list[Hit]:
    """Pages of prose (500 words) with more than two em-dashes: one hit per page, naming its em-dash sentences."""
    words = [m.start() for m in re.finditer(r"\S+", text)]
    if not words:
        return []
    out: list[Hit] = []
    for first in range(0, len(words), _WORDS_PER_PAGE):
        start = words[first]
        last = first + _WORDS_PER_PAGE
        end = words[last] if last < len(words) else len(text)
        dashes = [m for m in _EM_DASH_RE.finditer(text, start, end)]
        if len(dashes) <= EM_DASHES_PER_PAGE:
            continue
        sentences: list[str] = []
        for m in dashes:
            s = _sentence(source, m.start(), m.end())
            if s not in sentences:
                sentences.append(s)
        out.append(
            Hit(
                "em-dash chain",
                f"{len(dashes)} em-dashes on one page: " + " | ".join(sentences),
                f"at most {EM_DASHES_PER_PAGE} per page; use a comma, a semicolon or parentheses",
            )
        )
    return out


def find_in_file(path: Path) -> list[Hit]:
    try:
        return find(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def feedback(hits: list[Hit], limit: int = 12) -> str:
    """The hits as one line for the writer: each sentence to rewrite and how."""
    shown = "; ".join(h.line() for h in hits[:limit])
    more = f"; and {len(hits) - limit} more" if len(hits) > limit else ""
    return (
        f"{len(hits)} construction(s) the researcher does not accept in a paper: {shown}{more}. "
        "Rewrite each of these sentences without the construction; keep its content"
    )
