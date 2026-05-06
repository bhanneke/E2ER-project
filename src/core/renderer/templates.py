"""LaTeX preamble and assembly helpers.

Drafter specialists are instructed to write only the body content of the
paper (sections, tables, figures, abstract). The compiler wraps that body
in a standard preamble + bibliography block before invoking pdflatex.

This keeps the model's output focused on prose and makes the document
class, packages, and bibliography style consistent across all papers.
"""
from __future__ import annotations

from pathlib import Path

PREAMBLE = r"""\documentclass[11pt]{article}

\usepackage[margin=1in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath, amssymb, amsthm}
\usepackage{booktabs}
\usepackage{graphicx}
\usepackage{hyperref}
\usepackage{natbib}
\usepackage{setspace}

\onehalfspacing

\hypersetup{
  colorlinks=true,
  linkcolor=blue!50!black,
  citecolor=blue!50!black,
  urlcolor=blue!50!black,
}

% Allow specialists to define their own \title{}, \author{}, and \date{}
% in the body. If absent, the assembly fallback below provides defaults.
"""

DEFAULT_TITLE = r"""
\title{Untitled Paper}
\author{E2ER pipeline}
\date{\today}
"""

POSTAMBLE = r"""
\bibliographystyle{plainnat}
\bibliography{refs}

\end{document}
"""


def looks_like_full_document(body: str) -> bool:
    """Return True when the drafter wrote a complete document already."""
    return r"\documentclass" in body or r"\begin{document}" in body


def assemble_document(body: str) -> str:
    """Wrap a body fragment with the standard preamble + bibliography postamble.

    If the body is already a full document (has \\documentclass), return it
    unchanged so we don't double-wrap during the transition period while
    drafter skills are updated.
    """
    if looks_like_full_document(body):
        return body

    head = PREAMBLE
    if r"\title{" not in body:
        head += DEFAULT_TITLE

    # Whatever the drafter wrote becomes the body. Wrap with begin/end document.
    return (
        head
        + "\n\\begin{document}\n"
        + ("\\maketitle\n\n" if r"\maketitle" not in body else "")
        + body.strip()
        + POSTAMBLE
    )


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
