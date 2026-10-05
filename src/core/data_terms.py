"""Data a study loaded under a source's own terms, and what publishing it requires.

A connector whose source sets terms of use (the Global Macro Database,
``e2er-data gmd``, and Yahoo Finance, ``e2er-data yfinance``) records every
load in ``data/data_sources.json`` and, for a table, in
``data/data_dictionary.json``. ``e2er publish`` reads both:

- the description (``e2er.json``) names the source, its terms and its citation
  on every data file that holds the source's data, public or private;
- the dossier lists each load with its terms and citation;
- publishing the data with the study (``--data public``, also a ``--zenodo``
  deposit) needs the researcher's confirmation: ``--accept-data-terms gmd``,
  or a yes at the prompt in a terminal;
- a Zenodo deposit of the data states the terms in its description and takes
  the licence that matches them; for a source no Zenodo licence fits (Yahoo
  Finance, personal use only) e2er refuses the data deposit;
- readers on e2er.org see a link to the source instead of a request button.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceTerms:
    """The terms of one source, as e2er states them when the study is published."""

    connector: str
    name: str
    short: str
    terms_url: str
    #: The terms in plain words, one line each, shown before the researcher confirms.
    plain: tuple[str, ...]
    #: Zenodo's licence id that does not contradict the terms (applies to the whole data deposit);
    #: None: no Zenodo licence fits, so e2er does not deposit the data on Zenodo.
    zenodo_licence: str | None
    #: The BibTeX key the paper must cite; None when the source publishes no citation format.
    cite_key: str | None
    #: The source's own citation; empty when it publishes none.
    citation: str
    licence: str
    #: What the terms do, after "whose terms" (publish's reader note) and after "its terms" (the finish page).
    limit: str = "do not allow passing them on outside the study's replication package"
    limit_finish: str = "do not allow passing the data on outside the study's replication package"
    #: How the confirmation ends: "Publish the GMD data with the study under these terms?"
    confirm: str = "under these terms"
    #: A line the refusal of --data public adds, when the terms rule out more than e2er can check.
    warn: str = ""
    #: "the " before the name in a sentence ("the Global Macro Database"), "" for a name used bare.
    article: str = "the "
    #: Why no Zenodo licence fits (when ``zenodo_licence`` is None).
    no_zenodo_why: str = ""

    @property
    def the_short(self) -> str:
        return f"{self.article}{self.short}"


def _gmd() -> SourceTerms:
    from ..modules.data import gmd_provider as gmd

    return SourceTerms(
        connector=gmd.SOURCE,
        name=gmd.DATASET,
        short="GMD",
        terms_url=gmd.TERMS_URL,
        plain=gmd.TERMS_PLAIN,
        zenodo_licence="other-nc",
        cite_key=gmd.CITE_KEY,
        citation=gmd.CITATION,
        licence=gmd.LICENCE,
    )


def _yahoo() -> SourceTerms:
    from ..modules.data.load_record import YFINANCE

    return SourceTerms(
        connector=YFINANCE.connector,
        name="Yahoo Finance",
        short="Yahoo Finance",
        terms_url=YFINANCE.terms_url,
        # Verbatim from the load record's terms summary, one sentence per line.
        plain=tuple(
            s.strip() if s.strip().endswith(".") else s.strip() + "." for s in YFINANCE.terms_summary.split(". ")
        ),
        zenodo_licence=None,
        no_zenodo_why=(
            "Yahoo's terms allow personal use only, and a Zenodo deposit republishes the data for anyone to reuse"
        ),
        cite_key=None,
        citation="",
        licence=YFINANCE.licence,
        limit="allow personal use only",
        limit_finish="allow personal use only",
        confirm="although Yahoo's terms allow personal use only",
        warn="Yahoo's terms allow personal use only.",
        article="",
    )


def known() -> dict[str, SourceTerms]:
    """The sources with terms e2er knows, by connector name."""
    return {t.connector: t for t in (_gmd(), _yahoo())}


@dataclass
class Use:
    """One source with terms that the study used: the releases and the bundle files holding its data."""

    terms: SourceTerms
    versions: list[str]
    files: list[str]

    @property
    def label(self) -> str:
        rel = ", ".join(self.versions)
        t = self.terms
        name = t.name if t.name == t.short else f"{t.name} ({t.short})"
        return name + (f", release {rel}" if rel else "")

    @property
    def the_label(self) -> str:
        return f"{self.terms.article}{self.label}"

    @property
    def the_name(self) -> str:
        """The source as the reader note names it: "the Global Macro Database (GMD)", "Yahoo Finance"."""
        t = self.terms
        return t.article + (t.name if t.name == t.short else f"{t.name} ({t.short})")


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def uses(bundle: Path) -> list[Use]:
    """The sources with terms whose data the bundle holds (from data_sources.json and data_dictionary.json)."""
    bundle = Path(bundle)
    terms = known()
    found: dict[str, Use] = {}

    def add(connector: Any, version: Any, rel: str | None) -> None:
        if not isinstance(connector, str) or connector not in terms:
            return
        use = found.setdefault(connector, Use(terms[connector], [], []))
        if isinstance(version, str) and version and version not in use.versions:
            use.versions.append(version)
        if rel and (bundle / rel).is_file() and rel not in use.files:
            use.files.append(rel)

    sources = _read(bundle / "data" / "data_sources.json")
    loads = sources.get("loads") if isinstance(sources, dict) else None
    for load in loads if isinstance(loads, list) else []:
        if not isinstance(load, dict):
            continue
        rel = None
        if load.get("table"):
            rel = "data/data.db"
        elif isinstance(load.get("saved_to"), str):
            rel = load["saved_to"]
        add(load.get("connector"), load.get("version"), rel)
    dictionary = _read(bundle / "data" / "data_dictionary.json")
    tables = dictionary.get("tables") if isinstance(dictionary, dict) else None
    for t in tables if isinstance(tables, list) else []:
        if isinstance(t, dict):
            add(t.get("source"), t.get("version"), "data/data.db")
    for use in found.values():
        # The record of the loads names the source too, when no data file could be matched.
        if not use.files:
            for rel in ("data/data_sources.json", "data/data_dictionary.json"):
                if (bundle / rel).is_file():
                    use.files.append(rel)
                    break
    return list(found.values())


def statement(use: Use) -> str:
    """The sentence the description carries on each data file holding the source's data."""
    return f"Holds data from {use.the_label}, used under its terms. {use.terms.licence}"


def annotate(manifest: dict[str, Any], found: list[Use]) -> None:
    """Name the source, its terms and its citation on the data files of the description that hold its data.

    The site's format (research-object 0.1) lets a ``data`` entry carry more
    than path, sha256 and bytes; these keys travel with the description.
    """
    for use in found:
        for entry in manifest.get("data") or []:
            if entry.get("path") in use.files:
                entry["source"] = use.label
                entry["terms"] = statement(use)
                if use.terms.citation:
                    entry["citation"] = use.terms.citation


def missing_confirmation(found: list[Use], accepted: list[str] | None) -> list[Use]:
    accepted_set = {a.strip().lower() for a in accepted or []}
    return [u for u in found if u.terms.connector not in accepted_set]


def unknown_names(accepted: list[str] | None) -> list[str]:
    names = known()
    return [a for a in accepted or [] if a.strip().lower() not in names]


def terms_text(use: Use) -> str:
    """The terms in plain words, for the terminal."""
    lines = [f"The study uses data from {use.the_label}. Its terms:"]
    lines += [f"  - {p}" for p in use.terms.plain]
    if use.terms.citation:
        lines.append(f"  Citation: {use.terms.citation}")
    lines.append(f"  Full terms: {use.terms.terms_url}")
    return "\n".join(lines)


def refusal(missing: list[Use]) -> str:
    names = ", ".join(u.terms.connector for u in missing)
    lines = []
    for u in missing:
        lines.append(
            f"error: the study uses {u.label} data. Publishing them with the study (--data public) "
            f"needs your confirmation of the {u.terms.short} terms: {u.terms.terms_url}"
            + (f"\n  {u.terms.warn}" if u.terms.warn else "")
        )
    lines.append("  Nothing was written or sent.")
    lines.append(f"  To confirm, add --accept-data-terms {names}; to keep the data here, use --data private.")
    return "\n".join(lines)


def deposit_text(found: list[Use]) -> str:
    """The paragraph a Zenodo data deposit carries for each source with terms."""
    parts = []
    for u in found:
        parts.append(
            f"This deposit holds data from {u.the_label}, published with the study as part of its "
            f"replication package and labelled as {u.terms.short} data. {u.terms.licence} "
            f"Cite: {u.terms.citation} Full terms: {u.terms.terms_url}."
        )
    return " ".join(parts)


def bibliography_lacks(bundle: Path, found: list[Use]) -> list[Use]:
    """The sources whose citation the paper's references (paper/refs.bib) do not have."""
    refs = Path(bundle) / "paper" / "refs.bib"
    try:
        text = refs.read_text(encoding="utf-8") if refs.is_file() else ""
    except OSError:
        text = ""
    return [u for u in found if u.terms.cite_key and f"{{{u.terms.cite_key}," not in text.replace(" ", "")]


def no_zenodo(found: list[Use]) -> list[Use]:
    """The sources whose data e2er does not deposit on Zenodo (no Zenodo licence fits their terms)."""
    return [u for u in found if u.terms.zenodo_licence is None]


def zenodo_refusal(refused: list[Use]) -> str:
    lines = [
        f"error: e2er does not deposit {u.terms.the_short} data on Zenodo: {u.terms.no_zenodo_why}." for u in refused
    ]
    lines.append("  Nothing was written or sent.")
    lines.append(
        "  To deposit the code alone, use --data private; to publish the data with the study, "
        "give --data-url and leave out --zenodo."
    )
    return "\n".join(lines)
