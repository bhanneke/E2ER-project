"""LaTeX preamble and assembly helpers.

Drafter specialists are instructed to write only the body content of the
paper (sections, tables, figures, abstract). The compiler wraps that body
in a standard preamble + bibliography block before invoking pdflatex.

This keeps the model's output focused on prose and makes the document
class, packages, and bibliography style consistent across all papers.
"""

from __future__ import annotations

import re
from pathlib import Path

# Static preamble. `xcolor` is loaded BEFORE hyperref so the `blue!50!black`
# link colours resolve (hyperref's bundled `color` doesn't understand xcolor's
# mixing syntax). `graphicspath` searches both the workspace root (where the
# figure renderer writes `fig_*.pdf`) and a `figures/` subdir (the mirror the
# compiler makes), so `\includegraphics{fig_x.pdf}` AND
# `\includegraphics{figures/fig_x.pdf}` both resolve. fancyhdr gives every page
# a running header (running title + "Produced by E2ER").
PREAMBLE = r"""\documentclass[11pt]{article}

\usepackage[margin=1in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath, amssymb, amsthm}
\usepackage{booktabs}
\usepackage{xcolor}
\usepackage{graphicx}
\graphicspath{{./}{figures/}}
\usepackage{hyperref}
\usepackage{natbib}
\usepackage{setspace}
\usepackage{fancyhdr}

\onehalfspacing

\hypersetup{
  colorlinks=true,
  linkcolor=blue!50!black,
  citecolor=blue!50!black,
  urlcolor=blue!50!black,
}
"""

POSTAMBLE = r"""
\bibliographystyle{plainnat}
\bibliography{refs}

\end{document}
"""

_DEFAULT_AUTHOR = "Produced by the E2ER pipeline"


def looks_like_full_document(body: str) -> bool:
    """Return True when the drafter wrote a complete document already."""
    return r"\documentclass" in body or r"\begin{document}" in body


def _extract_braced(body: str, cmd: str) -> tuple[str | None, str]:
    """Pull a ``\\cmd{...}`` (balanced braces, possibly multi-line) out of the
    body. Returns (content, body_without_it); (None, body) if absent."""
    m = re.search(r"\\" + cmd + r"\s*\{", body)
    if not m:
        return None, body
    open_brace = m.end() - 1
    depth = 0
    for i in range(open_brace, len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                content = body[open_brace + 1 : i]
                return content, body[: m.start()] + body[i + 1 :]
    return None, body  # unbalanced — leave it alone


def _running_title(title: str) -> str:
    """A short, single-line running title for the page header."""
    flat = " ".join(title.split())
    # Drop LaTeX line breaks / thanks footnotes that don't belong in a header.
    flat = flat.replace("\\\\", " ").replace("\\thanks", " ")
    flat = re.sub(r"\s+", " ", flat).strip()
    return flat if len(flat) <= 70 else flat[:67].rstrip() + "..."


def _fancy_header(running_title: str) -> str:
    """fancyhdr config: running title (left) + 'Produced by E2ER' (right) on
    every page, including the title page. Page number in the footer."""
    return (
        "\\pagestyle{fancy}\n"
        "\\fancyhf{}\n"
        f"\\fancyhead[L]{{\\footnotesize\\itshape {running_title}}}\n"
        "\\fancyhead[R]{\\footnotesize Produced by E2ER}\n"
        "\\fancyfoot[C]{\\thepage}\n"
        "\\renewcommand{\\headrulewidth}{0.4pt}\n"
        # \maketitle forces \thispagestyle{plain} on page 1 — redefine plain so
        # the running header shows there too.
        "\\fancypagestyle{plain}{%\n"
        "  \\fancyhf{}%\n"
        f"  \\fancyhead[L]{{\\footnotesize\\itshape {running_title}}}%\n"
        "  \\fancyhead[R]{\\footnotesize Produced by E2ER}%\n"
        "  \\fancyfoot[C]{\\thepage}%\n"
        "  \\renewcommand{\\headrulewidth}{0.4pt}%\n"
        "}\n"
    )


def assemble_document(body: str) -> str:
    """Wrap a body fragment with the standard preamble + title block + running
    header + bibliography postamble.

    If the body is already a full document (has \\documentclass), return it
    unchanged so we don't double-wrap.

    Title handling: the drafter often writes ``\\title{}``/``\\author{}``/
    ``\\date{}`` INSIDE the body, after where ``\\maketitle`` would run — which
    made \\maketitle emit an empty title over just the date. We hoist those into
    the preamble (before \\begin{document}) and emit \\maketitle ourselves, so
    the title renders correctly.
    """
    if looks_like_full_document(body):
        return body

    title, body = _extract_braced(body, "title")
    author, body = _extract_braced(body, "author")
    date, body = _extract_braced(body, "date")
    body = re.sub(r"\\maketitle\b", "", body)  # we emit \maketitle ourselves

    title = title.strip() if title else "Untitled Paper"
    author = author.strip() if author else _DEFAULT_AUTHOR
    date_tex = date.strip() if date is not None else r"\today"

    head = (
        PREAMBLE
        + f"\n\\title{{{title}}}\n\\author{{{author}}}\n\\date{{{date_tex}}}\n"
        + _fancy_header(_running_title(title))
    )
    return head + "\n\\begin{document}\n\\maketitle\n\n" + body.strip() + POSTAMBLE


def assemble_refs_bib(workspace: Path) -> Path | None:
    """Assemble refs.bib from any BibTeX sources available in the workspace.

    Sources in priority order (later overrides earlier on duplicate keys):
      1. literature.bib  — written by the LiteratureToolHandler.save_bibtex tool
      2. user_refs.bib   — researcher-supplied bibliography (if present)

    The merged file is written to refs.bib. Returns its path, or None when
    no bibliography sources exist.
    """
    sources = [workspace / "literature.bib", workspace / "user_refs.bib"]
    sources = [p for p in sources if p.exists() and p.stat().st_size > 0]
    if not sources:
        return None

    seen_keys: set[str] = set()
    merged: list[str] = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for entry in _split_entries(text):
            key = _entry_key(entry)
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            merged.append(entry.strip())

    refs_path = workspace / "refs.bib"
    refs_path.write_text("\n\n".join(merged) + "\n", encoding="utf-8")
    return refs_path


def _split_entries(text: str) -> list[str]:
    """Split a .bib file into individual @-entries (string-level, no parser)."""
    out: list[str] = []
    cur: list[str] = []
    depth = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if depth == 0 and stripped.startswith("@") and "{" in stripped:
            if cur:
                out.append("".join(cur))
                cur = []
            depth = 1
            cur.append(line)
            depth = line.count("{") - line.count("}")
        elif depth > 0:
            cur.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                out.append("".join(cur))
                cur = []
                depth = 0
    if cur:
        out.append("".join(cur))
    return [e for e in out if e.strip().startswith("@")]


def _entry_key(entry: str) -> str | None:
    if "{" not in entry:
        return None
    head = entry.split("{", 1)[1]
    if "," not in head:
        return None
    return head.split(",", 1)[0].strip()
