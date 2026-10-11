"""Build the corpus: one row per work in table `corpus`, corpus_manifest.json, stopwords.txt, summary statistics.

Reads table gutenberg_texts (loaded with `e2er-data gutenberg text --ids 41,932,11231,43,375,1952`)
and corpus_design.json. The preprocessing is the design's, applied as e2er's corpus check applies it.
"""

import hashlib
import json
import re
import sqlite3
import unicodedata

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

DESIGN = json.load(open("corpus_design.json", encoding="utf-8"))
PRE = DESIGN["preprocessing"]
PATTERN = re.compile(PRE["token_pattern"])

# Year of first publication, entered by hand (corpus_design.json metadata.year names the sources).
YEARS = {41: 1820, 932: 1839, 11231: 1853, 43: 1886, 375: 1890, 1952: 1892}
LICENCE = "public domain in the USA; Project Gutenberg's licence and header removed (e2er-data gutenberg)"


def tokens(text):
    t = unicodedata.normalize("NFC", text)
    if PRE["lowercase"]:
        t = t.lower()
    return PATTERN.findall(t)


def quantile(values, q):
    pos = (len(values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


with open("stopwords.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(sorted(ENGLISH_STOP_WORDS)) + "\n")

con = sqlite3.connect("data.db")
books = con.execute("SELECT id, title, authors, text FROM gutenberg_texts ORDER BY id").fetchall()
rows, docs = [], []
for book_id, title, authors, text in books:
    year = YEARS[book_id]
    author = (authors or "").split(";")[0].strip()
    period = "1820-1853" if year <= 1853 else "1886-1892"
    doc_id = f"pg{book_id}"
    rows.append((doc_id, title, author, year, period, text))
    docs.append(
        {
            "doc_id": doc_id,
            "title": title,
            "author": author,
            "year": year,
            "period": period,
            "source": f"Project Gutenberg ebook {book_id}, plain text from the mirror gutenberg.pglaf.org",
            "licence": LICENCE,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "n_tokens": len(tokens(text)),
        }
    )
con.execute("DROP TABLE IF EXISTS corpus")
con.execute("CREATE TABLE corpus (doc_id TEXT, title TEXT, author TEXT, year INTEGER, period TEXT, text TEXT)")
con.executemany("INSERT INTO corpus VALUES (?, ?, ?, ?, ?, ?)", rows)
con.commit()

lengths = sorted(d["n_tokens"] for d in docs)
types = set()
for _doc_id, _t, _a, _y, _p, text in rows:
    types.update(tokens(text))
stats = {
    "n_documents": len(docs),
    "n_tokens": sum(lengths),
    "n_types": len(types),
    "length": {
        "min": lengths[0],
        "p25": round(quantile(lengths, 0.25), 2),
        "median": round(quantile(lengths, 0.5), 2),
        "p75": round(quantile(lengths, 0.75), 2),
        "max": lengths[-1],
        "mean": round(sum(lengths) / len(lengths), 2),
    },
}
json.dump({"documents": docs, "corpus": stats}, open("corpus_manifest.json", "w", encoding="utf-8"), indent=2)

by_period = {}
for d in docs:
    by_period.setdefault(d["period"], []).append(d["n_tokens"])
summary = {
    "n_observations": len(docs),
    "n_units": len(docs),
    "time_coverage": {"start_year": min(YEARS.values()), "end_year": max(YEARS.values())},
    "outcome": {"variable": "tokens per document", "unit": "tokens", "n": len(docs),
                "mean": stats["length"]["mean"], "min": lengths[0], "median": stats["length"]["median"],
                "max": lengths[-1]},
    "groups": {p: {"documents": len(v), "tokens": sum(v)} for p, v in sorted(by_period.items())},
    "missing": {"year": 0},
    "sample_flow": [{"step": "Project Gutenberg books loaded", "rows": len(books), "dropped": 0}],
}
json.dump(summary, open("summary_statistics.json", "w", encoding="utf-8"), indent=2)
print(json.dumps(stats))
