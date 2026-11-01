"""The template's method sources in the study's bibliography.

Every template names the methods literature it follows (``[[credit]]`` with
``relation = "cites"``: a verified DOI or address each). At the start of a run
those entries are added to the study's ``literature.bib`` as BibTeX, tagged
``e2er_source = {template}``, so the writers can cite the methods the study
used. The citation check verifies them like every other reference, and the
dossier lists them as method sources. Nothing forces a paper to cite them all:
a writer cites the ones whose method the study used.

Keys are stable: the credit's ``cite_key`` when it gives one, else surname,
year and the first word of the title (``dunning1993accurate``). An entry whose
key is already in the file (the researcher's paper, a web hit, or a template
module's own fuller entry, e.g. the systematic review's) is left as it is.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

#: The ``e2er_source`` tag of a template's method source (labels.REFERENCE_SOURCES).
TEMPLATE_SOURCE = "template"

_TYPES = {"article": "article", "book": "book"}
_STOP = {"a", "an", "the", "on", "of", "and", "for", "in", "to", "with", "how", "use"}
#: "Computational Linguistics 19(1), 61-74": journal, volume, number, pages.
_JOURNAL_RE = re.compile(
    r"^(?P<journal>.*?\D)\s+(?P<volume>\d+)(?:\((?P<number>[^)]+)\))?,\s*(?P<pages>[\w.]+(?:-[\w.]+)?)$"
)
_DOI_RE = re.compile(r"^https://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def creators(text: str) -> list[str]:
    """ "A, B and C" -> ["A", "B", "C"]; "... and others" stays BibTeX's "others"."""
    parts = [p.strip() for p in re.split(r",\s*|\s+and\s+", str(text or "")) if p.strip()]
    return parts


def year_of(credit: dict[str, Any]) -> str:
    raw = str(credit.get("published") or credit.get("year") or "").strip()
    return raw[:4] if re.match(r"^\d{4}", raw) else ""


def cite_key(credit: dict[str, Any]) -> str:
    """The credit's own ``cite_key``, else surname + year + first word of the title."""
    own = str(credit.get("cite_key") or "").strip()
    if own:
        return own
    names = creators(str(credit.get("creator") or ""))
    last = re.sub(r"[^a-z]", "", _ascii(names[0].split()[-1] if names else "anon").lower()) or "anon"
    words = [w for w in re.findall(r"[a-z]+", _ascii(str(credit.get("title") or "")).lower()) if w not in _STOP]
    return f"{last}{year_of(credit) or 'nd'}{words[0] if words else 'work'}"


def doi_of(credit: dict[str, Any]) -> str:
    m = _DOI_RE.match(str(credit.get("url") or "").strip())
    return m.group(1) if m else ""


def _braced(value: str) -> str:
    from .bibliography import tex_escape

    return tex_escape(" ".join(str(value).split()))


def bibtex(credit: dict[str, Any], template: str) -> tuple[str, str]:
    """(key, BibTeX entry) of one credit, tagged as a method source of ``template``."""
    key = cite_key(credit)
    known = _known_entries().get(key)
    fields: list[tuple[str, str]]
    if known is not None:
        # The template's own module keeps a fuller verified entry under this key (volume, pages, …).
        etype = known["type"]
        fields = [(k, v) for k, v in known.items() if k != "type"]
    else:
        kind = str(credit.get("kind") or "").lower()
        etype = _TYPES.get(kind, "misc")
        names = creators(str(credit.get("creator") or ""))
        fields = [
            ("author", " and ".join(_braced(n) for n in names)),
            ("title", "{" + _braced(str(credit.get("title") or "")) + "}"),
        ]
        year = year_of(credit)
        if year:
            fields.append(("year", year))
        publisher = str(credit.get("publisher") or "").strip()
        if publisher:
            m = _JOURNAL_RE.match(publisher) if etype == "article" else None
            if m:
                fields.append(("journal", _braced(m.group("journal").rstrip(","))))
                fields.append(("volume", m.group("volume")))
                if m.group("number"):
                    fields.append(("number", m.group("number")))
                fields.append(("pages", m.group("pages").replace("-", "--")))
            elif etype == "article":
                fields.append(("journal", _braced(publisher)))
            elif etype == "book":
                fields.append(("publisher", _braced(publisher)))
            else:
                fields.append(("howpublished", _braced(publisher)))
        doi = doi_of(credit)
        if doi:
            fields.append(("doi", doi))
        fields.append(("url", str(credit.get("url") or "")))
    fields.append(("e2er_source", TEMPLATE_SOURCE))
    fields.append(("e2er_template", template))
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if str(v).strip())
    return key, f"@{etype}{{{key},\n{body}\n}}"


def _known_entries() -> dict[str, dict[str, str]]:
    """Fuller entries the template modules keep under the same keys (field map, systematic review)."""
    from ..modules.fieldmap.credit import METHOD_REFERENCES as FIELDMAP
    from ..modules.metaanalysis.credit import METHOD_REFERENCES as META

    return {**FIELDMAP, **META}


def method_credits(spec: Any) -> list[dict[str, Any]]:
    """The template's credits a paper can cite: relation ``cites``."""
    return [dict(c) for c in getattr(spec, "credit", ()) or () if str(c.get("relation") or "") == "cites"]


_KEY_RE = re.compile(r"^@\w+\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)


def add_method_sources(workspace: Path, spec: Any) -> list[str]:
    """Add the template's method sources to ``literature.bib`` (once each); returns the keys added.

    An entry whose key the file already has is kept as it is. Never raises: a
    study without these entries still runs, its writers just cannot cite them.
    """
    credits = method_credits(spec)
    if not credits:
        return []
    bib = Path(workspace) / "literature.bib"
    try:
        text = bib.read_text(encoding="utf-8") if bib.is_file() else ""
        have = set(_KEY_RE.findall(text))
        added: list[str] = []
        entries: list[str] = []
        for credit in credits:
            key, entry = bibtex(credit, str(getattr(spec, "name", "") or ""))
            if key in have:
                continue
            have.add(key)
            added.append(key)
            entries.append(entry)
        if entries:
            bib.write_text(
                (text.rstrip() + "\n\n" if text.strip() else "") + "\n\n".join(entries) + "\n", "utf-8", newline="\n"
            )
        return added
    except OSError as e:
        logger.warning("the template's method sources could not be added to literature.bib: %s", e)
        return []
