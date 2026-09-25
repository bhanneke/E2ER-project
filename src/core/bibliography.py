"""Which bibliography file a paper asks for, and whether a compile found it.

The pipeline writes ``literature.bib`` and the export ships it as
``refs.bib``; a paper that still says ``\\bibliography{literature}`` compiles
fine in the run's workspace but not from the exported bundle, where BibTeX
finds no database and every citation turns into "?". These helpers keep the
paper, the bundle and the compiled PDF consistent.
"""

from __future__ import annotations

import re
from pathlib import Path

_BIBLIOGRAPHY = re.compile(r"\\bibliography\{([^}]*)\}")


def bibliography_names(tex: str) -> list[str]:
    """Database names from ``\\bibliography{a,b}`` (without ``.bib``)."""
    names: list[str] = []
    for group in _BIBLIOGRAPHY.findall(tex):
        names += [n.strip().removesuffix(".bib") for n in group.split(",") if n.strip()]
    return names


def point_bibliography(tex: str, paper_dir: Path, shipped: str = "refs") -> str:
    """Point ``\\bibliography`` at the file the bundle ships when the named one is missing."""
    names = bibliography_names(tex)
    if not names or all((paper_dir / f"{n}.bib").is_file() for n in names):
        return tex
    if not (paper_dir / f"{shipped}.bib").is_file():
        return tex
    return _BIBLIOGRAPHY.sub(lambda _: f"\\bibliography{{{shipped}}}", tex, count=1)


def unresolved_citations(work_dir: Path, stem: str = "paper") -> list[str]:
    """Keys cited in ``<stem>.aux`` that the generated ``<stem>.bbl`` does not contain."""
    aux, bbl = work_dir / f"{stem}.aux", work_dir / f"{stem}.bbl"
    if not aux.is_file():
        return []
    cited = {
        k.strip() for c in re.findall(r"\\citation\{([^}]*)\}", aux.read_text(errors="replace")) for k in c.split(",")
    }
    cited.discard("*")
    have = (
        set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]*)\}", bbl.read_text(errors="replace")))
        if bbl.is_file()
        else set()
    )
    return sorted(cited - have)


_FIELD = re.compile(r"^(\s*)(\w+)(\s*=\s*\{)(.*)(\},?\s*)$")
_RAW_FIELDS = {"url", "doi", "eprint", "file"}


def tex_escape(value: str) -> str:
    """Escape the characters that stop LaTeX in bibliography text: & % #."""
    return re.sub(r"(?<!\\)([&%#])", r"\\\1", value)


def escape_bib(text: str) -> str:
    """Escape & % # in the text fields of a .bib file (URLs and DOIs stay raw)."""
    out = []
    for line in text.split("\n"):
        m = _FIELD.match(line)
        if m and m.group(2).lower() not in _RAW_FIELDS:
            line = m.group(1) + m.group(2) + m.group(3) + tex_escape(m.group(4)) + m.group(5)
        out.append(line)
    return "\n".join(out)
