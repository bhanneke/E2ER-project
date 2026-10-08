"""Where the field map's method comes from, as data.

The methods literature is cited in every field review the template writes
(``METHOD_REFERENCES`` go into the study's ``literature.bib``). The workflow
itself follows a practitioner article (``WORKFLOW_SOURCE``); it is credited
the same way in the template file, the skill, the README, the changelog and
the catalogue data for e2er.org (``credits.json`` at the repository root).

Each reference below was checked against Crossref or arXiv on 2026-10-08.
Crossref lists the second author of Hummon and Doreian (1989) as "Dereian";
the article itself and the journal's site spell the name Doreian.
"""

from __future__ import annotations

from typing import Any

#: The article the workflow follows. Found: shared by Björn Hanneke on 2026-10-08.
WORKFLOW_SOURCE: dict[str, Any] = {
    "creator": "Michal Hron",
    "creator_kind": "external",
    "role": "conceptualization",
    "relation": "based_on",
    "title": "Map a research field with Claude: main path analysis, step by step",
    "publisher": "LinkedIn Pulse",
    "published": "2026-10-08",
    "url": "https://www.linkedin.com/pulse/map-research-field-claude-main-path-analysis-step-michal-hron-jm2ge/",
    "accessed": "2026-10-08",
    "found_via": "shared by Björn Hanneke",
}

#: The author's own published implementation, linked as related work (not used, not copied).
RELATED_WORK: list[dict[str, Any]] = [
    {
        "creator": "Michal Hron",
        "title": "scopus-plus-mcp (Scopus MCP server with a main-path skill)",
        "url": "https://github.com/michalhron/scopus-plus-mcp",
        "licence": "MIT",
        "relation": "related_work",
        "note": "Hron's implementation on Scopus; e2er's is independent, written from the methods literature, "
        "and uses OpenAlex.",
    }
]

#: Verified bibliographic entries of the methods (BibTeX), keyed by cite key.
METHOD_REFERENCES: dict[str, dict[str, str]] = {
    "hummon1989connectivity": {
        "type": "article",
        "author": "Hummon, Norman P. and Doreian, Patrick",
        "title": "Connectivity in a citation network: The development of {DNA} theory",
        "journal": "Social Networks",
        "year": "1989",
        "volume": "11",
        "number": "1",
        "pages": "39--63",
        "doi": "10.1016/0378-8733(89)90017-8",
    },
    "batagelj2003efficient": {
        "type": "misc",
        "author": "Batagelj, Vladimir",
        "title": "Efficient algorithms for citation network analysis",
        "year": "2003",
        "howpublished": "arXiv preprint cs/0309023",
        "eprint": "cs/0309023",
        "archiveprefix": "arXiv",
        "doi": "10.48550/arXiv.cs/0309023",
    },
    "liu2012integrated": {
        "type": "article",
        "author": "Liu, John S. and Lu, Louis Y. Y.",
        "title": "An integrated approach for main path analysis: Development of the {H}irsch index as an example",
        "journal": "Journal of the American Society for Information Science and Technology",
        "year": "2012",
        "volume": "63",
        "number": "3",
        "pages": "528--542",
        "doi": "10.1002/asi.21692",
    },
}

#: What the article contributed and what e2er wrote, in plain words (shown in the template and the catalogue).
ADOPTED = (
    "The six-step workflow: a boundary of search terms and journals, the internal citation network with "
    "completeness checks, SPC weights, the main path with key routes, robustness across alternative journal "
    "sets, and a map with topic lanes named as questions; and the pitfalls the article lists."
)
OWN = (
    "The code (OpenAlex retrieval, network, SPC, main paths, key routes, cycle handling, robustness, exports, "
    "map), the template's steps and researcher stops, the specialists' instructions, and the field review "
    "whose numbers e2er checks."
)
STATEMENT = (
    "The workflow follows Michal Hron's article \"Map a research field with Claude: main path analysis, step by "
    'step" (LinkedIn Pulse, 8 October 2026); this implementation is independent and uses OpenAlex.'
)


def bibtex(key: str, entry: dict[str, str]) -> str:
    fields = [f"  {k} = {{{v}}}" for k, v in entry.items() if k != "type"]
    return f"@{entry['type']}{{{key},\n" + ",\n".join(fields) + "\n}\n"


def method_bibtex() -> str:
    return "\n".join(bibtex(k, v) for k, v in METHOD_REFERENCES.items())
