"""A SYNTHETIC systematic review for the meta-analysis tests: protocol, OpenAlex answers, PDFs, decisions.

Nothing here is a real study. Twelve invented records on grit and grades:
eight primary studies with a correlation (seven with an open-access PDF, one
read from its abstract), a meta-analysis and a study of pupils (excluded on
title and abstract), a record without an abstract (unsure, then excluded on
its full text), and one record found by both searches (a duplicate). The
PDFs are drawn with matplotlib, so pypdf reads their text as it would a
journal's.
"""

from __future__ import annotations

import io
import json
import urllib.parse
from pathlib import Path
from typing import Any

PROTOCOL: dict[str, Any] = {
    "question": "How strongly is grit associated with grades in university students (synthetic test data)?",
    "framework": "PECO",
    "elements": {
        "population": "university students",
        "exposure": "grit (Grit-S)",
        "comparison": "lower grit",
        "outcome": "grade point average",
    },
    "eligibility": {
        "include": [
            {"id": "I1", "criterion": "quantitative study of university students"},
            {"id": "I2", "criterion": "grit measured with the Grit-S scale"},
            {"id": "I3", "criterion": "reports the correlation of grit with GPA and the sample size"},
        ],
        "exclude": [
            {"id": "E1", "criterion": "review or meta-analysis"},
            {"id": "E2", "criterion": "same sample as another included study"},
        ],
    },
    "databases": ["openalex"],
    "searches": [
        {"name": "main", "query": 'grit AND (GPA OR "grade point average")', "from_year": 2010, "to_year": 2024},
        {"name": "grades", "query": 'grit AND "course grades"', "from_year": 2010, "to_year": 2024},
    ],
    "outcome": {"name": "grade point average", "description": "GPA as reported"},
    "effect_measure": "r",
    "effect_direction": "positive r: more grit, higher GPA",
    "synthesis": {"tau2_method": "REML", "min_studies": 3, "ci_level": 0.95},
    "risk_of_bias": {
        "tool": "JBI checklist for analytical cross-sectional studies (adapted)",
        "domains": ["sample", "measurement", "confounding"],
        "levels": ["low", "some concerns", "high", "unclear"],
    },
}

#: id -> (author, year, r printed, n, full text?)
STUDIES: dict[str, tuple[str, int, str, int, bool]] = {
    "W101": ("Arendt", 2015, ".31", 412, True),
    "W102": ("Bauer", 2016, ".18", 250, True),
    "W103": ("Castro", 2017, ".25", 180, True),
    "W104": ("Dahl", 2018, ".08", 520, True),
    "W105": ("Ekström", 2019, ".40", 95, True),
    "W106": ("Fischer", 2020, ".22", 310, True),
    "W107": ("Garcia", 2021, ".12", 640, True),
    "W108": ("Huang", 2022, ".35", 120, False),
}
OTHERS: dict[str, dict[str, Any]] = {
    "W109": {
        "author": "Ito",
        "year": 2020,
        "title": "Grit and achievement: a meta-analysis (synthetic)",
        "abstract": "We pool 40 studies of grit and GPA in a meta-analysis.",
    },
    "W110": {
        "author": "Jansen",
        "year": 2019,
        "title": "Grit and grades in secondary school pupils (synthetic)",
        "abstract": "A survey of 300 high-school pupils on grit and GPA.",
    },
    "W111": {"author": "Kowalski", "year": 2023, "title": "Grit, GPA and persistence (synthetic)", "abstract": ""},
}


def _title(sid: str) -> str:
    a, y, *_ = STUDIES[sid]
    return f"Grit and grade point average among university students: study {sid} (synthetic)"


def abstract(sid: str) -> str:
    a, y, r, n, has_pdf = STUDIES[sid]
    if not has_pdf:
        return (
            f"We surveyed {n} undergraduate students with the Grit-S scale. Grit was associated with GPA "
            f"(r = {r}, n = {n}). Synthetic abstract for e2er's tests."
        )
    return f"A survey of university students on grit (Grit-S) and GPA. Synthetic abstract for e2er's tests ({sid})."


def pages(sid: str) -> list[str]:
    if sid == "W111":
        return [
            "Grit, GPA and persistence (synthetic)\nMethods. We surveyed 210 university students with the Grit-S.",
            "Results. Grit predicted persistence in a logistic regression;\nthe correlation with GPA is not reported.",
        ]
    a, y, r, n, _ = STUDIES[sid]
    return [
        f"{_title(sid)}\n{a} ({y}). Synthetic test document.\nMethods. The final sample comprised {n} students\n"
        "from one university, who completed the Grit-S.",
        f"Results. Grit was positively correlated with GPA (r = {r}, p < .01).\nTable 2 Grit {r}** .12",
    ]


def pdf_bytes(sid: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    with matplotlib.rc_context({"pdf.fonttype": 42}):
        buf = io.BytesIO()
        with PdfPages(buf, metadata={"CreationDate": None, "ModDate": None}) as pdf:
            for text in pages(sid):
                fig = plt.figure(figsize=(8.27, 11.69))
                y = 0.9
                for line in text.split("\n"):
                    fig.text(0.08, y, line, fontsize=10)
                    y -= 0.03
                pdf.savefig(fig)
                plt.close(fig)
    return buf.getvalue()


def _inverted(text: str) -> dict[str, list[int]] | None:
    if not text:
        return None
    inv: dict[str, list[int]] = {}
    for i, w in enumerate(text.split()):
        inv.setdefault(w, []).append(i)
    return inv


def pdf_url(sid: str) -> str:
    return f"https://oa.example.org/{sid}.pdf"


def work(sid: str) -> dict[str, Any]:
    if sid in STUDIES:
        a, y, _, _, has_pdf = STUDIES[sid]
        title, abs_ = _title(sid), abstract(sid)
    else:
        o = OTHERS[sid]
        a, y, title, abs_, has_pdf = o["author"], o["year"], o["title"], o["abstract"], sid == "W111"
    return {
        "id": f"https://openalex.org/{sid}",
        "doi": f"https://doi.org/10.9999/synthetic.{sid.lower()}",
        "title": title,
        "publication_year": y,
        "publication_date": f"{y}-03-01",
        "type": "article",
        "primary_location": {"source": {"id": "https://openalex.org/S1", "display_name": "Journal of Synthetic Data"}},
        "authorships": [{"author": {"display_name": f"Alex {a}"}}],
        "abstract_inverted_index": _inverted(abs_),
        "open_access": {
            "is_oa": has_pdf,
            "oa_status": "gold" if has_pdf else "closed",
            "oa_url": pdf_url(sid) if has_pdf else None,
        },
        "best_oa_location": {"pdf_url": pdf_url(sid), "license": "cc-by"} if has_pdf else None,
        "biblio": {"volume": "1", "issue": "1", "first_page": "1", "last_page": "2"},
        "language": "en",
    }


MAIN = ["W101", "W102", "W103", "W104", "W105", "W106", "W108", "W109", "W110", "W111"]
GRADES = ["W103", "W107"]  # W103 is found by both searches


class FakeOpenAlex:
    """Serves the two searches, cursor-paged; records every request."""

    def __init__(self, page: int = 4) -> None:
        self.page = page
        self.calls: list[str] = []

    def works_for(self, flt: str) -> list[dict[str, Any]]:
        ids = GRADES if "course grades" in flt else MAIN
        return [work(i) for i in ids]

    def __call__(self, url: str, headers: dict[str, str]) -> str:
        self.calls.append(url)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        works = self.works_for(q.get("filter", ""))
        if q.get("per-page") == "1":
            return json.dumps({"meta": {"count": len(works)}, "results": works[:1]})
        start = 0 if q.get("cursor") == "*" else int(q["cursor"])
        chunk = works[start : start + self.page]
        nxt = str(start + self.page) if start + self.page < len(works) else None
        return json.dumps({"meta": {"count": len(works), "next_cursor": nxt}, "results": chunk})


def fake_pdf(url: str) -> bytes:
    sid = url.rsplit("/", 1)[-1].removesuffix(".pdf")
    if sid not in STUDIES and sid != "W111":
        raise RuntimeError("404")
    return pdf_bytes(sid)


# ── the specialists' files ──────────────────────────────────────────────────


def screening() -> dict[str, Any]:
    d = [{"id": s, "decision": "include"} for s in STUDIES]
    d += [
        {"id": "W109", "decision": "exclude", "criteria": ["E1"], "reason": "a meta-analysis, not a primary study"},
        {"id": "W110", "decision": "exclude", "criteria": ["I1"], "reason": "high-school pupils"},
        {"id": "W111", "decision": "unsure", "reason": "no abstract"},
    ]
    return {"decisions": d}


def extraction() -> dict[str, Any]:
    out = []
    for sid, (a, y, r, n, has_pdf) in STUDIES.items():
        if has_pdf:
            sources = {
                "effect.value": {"page": 2, "quote": f"positively correlated with GPA (r = {r}, p < .01)"},
                "effect.n": {"page": 1, "quote": f"The final sample comprised {n} students"},
                "n_total": {"page": 1, "quote": f"The final sample comprised {n} students"},
            }
        else:
            q = f"Grit was associated with GPA (r = {r}, n = {n})"
            sources = {k: {"page": "abstract", "quote": q} for k in ("effect.value", "effect.n", "n_total")}
        out.append(
            {
                "id": sid,
                "decision": "include",
                "source_text": "full text" if has_pdf else "abstract",
                "label": f"{a} {y}",
                "year": y,
                "characteristics": {"design": "cross-sectional", "population": "undergraduates"},
                "n_total": n,
                "effect": {"value": float(r), "n": n},
                "sources": sources,
                "risk_of_bias": {
                    "domains": {"sample": "some concerns", "measurement": "low", "confounding": "high"},
                    "overall": "high",
                    "support": "convenience sample (p. 1); no adjustment (p. 2)",
                },
            }
        )
    out.append(
        {
            "id": "W111",
            "decision": "exclude",
            "source_text": "full text",
            "criteria": ["I3"],
            "reason": "reports a logistic regression on persistence; the correlation with GPA is not reported",
        }
    )
    return {"studies": out}


def write_protocol(ws: Path) -> None:
    (ws / "review_protocol.json").write_text(json.dumps(PROTOCOL, indent=2), encoding="utf-8")
