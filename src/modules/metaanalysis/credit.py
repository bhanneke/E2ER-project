"""The methods the systematic-review template uses, as verified bibliographic entries.

Each DOI was checked on Crossref on 2026-10-11. The synthesis step adds these
entries to the study's ``literature.bib``, so the review can cite the methods
it reports (PRISMA 2020, the tau^2 estimators, I^2, the prediction interval,
Egger's test, trim and fill).
"""

from __future__ import annotations

from typing import Any

METHOD_REFERENCES: dict[str, dict[str, str]] = {
    "page2021prisma": {
        "type": "article",
        "author": "Page, Matthew J. and McKenzie, Joanne E. and Bossuyt, Patrick M. and Boutron, Isabelle and "
        "Hoffmann, Tammy C. and Mulrow, Cynthia D. and others",
        "title": "The {PRISMA} 2020 statement: an updated guideline for reporting systematic reviews",
        "journal": "BMJ",
        "year": "2021",
        "volume": "372",
        "pages": "n71",
        "doi": "10.1136/bmj.n71",
    },
    "dersimonian1986meta": {
        "type": "article",
        "author": "DerSimonian, Rebecca and Laird, Nan",
        "title": "Meta-analysis in clinical trials",
        "journal": "Controlled Clinical Trials",
        "year": "1986",
        "volume": "7",
        "number": "3",
        "pages": "177--188",
        "doi": "10.1016/0197-2456(86)90046-2",
    },
    "higgins2002quantifying": {
        "type": "article",
        "author": "Higgins, Julian P. T. and Thompson, Simon G.",
        "title": "Quantifying heterogeneity in a meta-analysis",
        "journal": "Statistics in Medicine",
        "year": "2002",
        "volume": "21",
        "number": "11",
        "pages": "1539--1558",
        "doi": "10.1002/sim.1186",
    },
    "egger1997bias": {
        "type": "article",
        "author": "Egger, Matthias and Davey Smith, George and Schneider, Martin and Minder, Christoph",
        "title": "Bias in meta-analysis detected by a simple, graphical test",
        "journal": "BMJ",
        "year": "1997",
        "volume": "315",
        "number": "7109",
        "pages": "629--634",
        "doi": "10.1136/bmj.315.7109.629",
    },
    "duval2000trim": {
        "type": "article",
        "author": "Duval, Sue and Tweedie, Richard",
        "title": "Trim and fill: A simple funnel-plot-based method of testing and adjusting for publication bias "
        "in meta-analysis",
        "journal": "Biometrics",
        "year": "2000",
        "volume": "56",
        "number": "2",
        "pages": "455--463",
        "doi": "10.1111/j.0006-341X.2000.00455.x",
    },
    "viechtbauer2010conducting": {
        "type": "article",
        "author": "Viechtbauer, Wolfgang",
        "title": "Conducting meta-analyses in {R} with the metafor package",
        "journal": "Journal of Statistical Software",
        "year": "2010",
        "volume": "36",
        "number": "3",
        "pages": "1--48",
        "doi": "10.18637/jss.v036.i03",
    },
    "viechtbauer2005bias": {
        "type": "article",
        "author": "Viechtbauer, Wolfgang",
        "title": "Bias and efficiency of meta-analytic variance estimators in the random-effects model",
        "journal": "Journal of Educational and Behavioral Statistics",
        "year": "2005",
        "volume": "30",
        "number": "3",
        "pages": "261--293",
        "doi": "10.3102/10769986030003261",
    },
    "riley2011interpretation": {
        "type": "article",
        "author": "Riley, Richard D. and Higgins, Julian P. T. and Deeks, Jonathan J.",
        "title": "Interpretation of random effects meta-analyses",
        "journal": "BMJ",
        "year": "2011",
        "volume": "342",
        "pages": "d549",
        "doi": "10.1136/bmj.d549",
    },
}


def bibtex(key: str, entry: dict[str, Any]) -> str:
    fields = [f"  {k} = {{{v}}}" for k, v in entry.items() if k != "type" and str(v).strip()]
    return f"@{entry['type']}{{{key},\n" + ",\n".join(fields) + "\n}\n"
