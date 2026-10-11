"""Text analysis of six works of short fiction, 1820-1892: frequencies, keyness, collocations, a fear
dictionary with its validation sample, an NMF topic model with its stability across seeds.

Reads the table `corpus` of data.db, corpus_design.json and stopwords.txt; writes estimation_results.json
("result_kind": "text") and validation_sample.json. The preprocessing is the design's, applied as e2er's
checks apply it (NFC, lower case, every match of the token pattern).
"""

import json
import math
import random
import re
import sqlite3
import unicodedata
from collections import Counter

import numpy as np
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

DESIGN = json.load(open("corpus_design.json", encoding="utf-8"))
PRE = DESIGN["preprocessing"]
PATTERN = re.compile(PRE["token_pattern"])
STOP = set(open("stopwords.txt", encoding="utf-8").read().split())
ANALYSES = {a["id"]: a for a in DESIGN["analyses"]}
YEARS = [1820, 1839, 1853, 1886, 1890, 1892]


def tokens(text):
    t = unicodedata.normalize("NFC", text)
    if PRE["lowercase"]:
        t = t.lower()
    return PATTERN.findall(t)


con = sqlite3.connect("data.db")
rows = con.execute("SELECT doc_id, year, period, text FROM corpus ORDER BY year").fetchall()
docs = {r[0]: {"year": r[1], "period": r[2], "text": r[3], "tokens": tokens(r[3])} for r in rows}
GROUPS = {
    "all": sorted(docs),
    "early": sorted(d for d, v in docs.items() if v["period"] == "1820-1853"),
    "late": sorted(d for d, v in docs.items() if v["period"] == "1886-1892"),
}
for y in YEARS:
    GROUPS[f"y{y}"] = sorted(d for d, v in docs.items() if v["year"] == y)


def counts(group, n=1):
    c = Counter()
    for d in GROUPS[group]:
        t = docs[d]["tokens"]
        c.update(t if n == 1 else (" ".join(t[i : i + n]) for i in range(len(t) - n + 1)))
    return c


def size(group):
    return sum(len(docs[d]["tokens"]) for d in GROUPS[group])


def per10k(c, n):
    return round(c / n * 10000, 4)


uni = {g: counts(g) for g in GROUPS}
results = {
    "result_kind": "text",
    "corpus": {
        "n_documents": len(docs),
        "n_tokens": size("all"),
        "n_types": len(uni["all"]),
        "preprocessing": PRE,
        "documents_by_group": {g: len(GROUPS[g]) for g in ("early", "late")},
    },
    "term_frequencies": {},
    "models": {},
    "figures": ["fig_fear_by_year.pdf", "fig_keyness.pdf", "fig_topics.pdf"],
    "limits": DESIGN["limits"],
}

# Term frequencies of the design's terms, per group.
for g in ("all", "early", "late"):
    n = size(g)
    terms = ANALYSES["frequencies"]["terms"]
    results["term_frequencies"][g] = {
        "n_tokens": n,
        "terms": [
            {"term": t, "count": uni[g][t], "per_10k": per10k(uni[g][t], n),
             "documents": sum(1 for d in GROUPS[g] if t in docs[d]["tokens"])}
            for t in terms
        ],
    }

# Keyness: late against early, log-likelihood G2 (Rayson and Garside 2000) with the log ratio (Hardie 2014).
c, d = size("late"), size("early")
key_rows = []
for term in set(uni["late"]) | set(uni["early"]):
    a, b = uni["late"][term], uni["early"][term]
    spread = sum(1 for doc in GROUPS["late"] if term in docs[doc]["tokens"])
    if term in STOP or a + b < ANALYSES["keyness_late"]["min_count"] or spread < ANALYSES["keyness_late"]["min_documents"]:
        continue
    e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
    g2 = 2 * ((a * math.log(a / e1) if a else 0) + (b * math.log(b / e2) if b else 0))
    lr = math.log2(((a or 0.5) / c) / ((b or 0.5) / d))
    if a / c > b / d:
        key_rows.append({"term": term, "count_target": a, "count_reference": b, "g2": round(g2, 3),
                         "log_ratio": round(lr, 3), "p_value": float(f"{math.erfc(math.sqrt(g2 / 2)):.4g}"),
                         "more_in": "late", "documents_target": spread})
key_rows.sort(key=lambda r: (-r["g2"], r["term"]))
results["models"]["keyness_late"] = {
    "method": "keyness",
    "target": "late",
    "reference": "early",
    "min_count": ANALYSES["keyness_late"]["min_count"],
    "min_documents": ANALYSES["keyness_late"]["min_documents"],
    "threshold": "G2 > 15.13 (p < 0.0001), for the many terms tested",
    "outputs": {"terms": key_rows[: ANALYSES["keyness_late"]["top"]],
                "n_terms_more_in_target": len(key_rows)},
}

# Collocations: adjacent pairs of content words, PMI, at least 5 occurrences.
bi = counts("all", 2)
n_all = size("all")
pairs = []
for pair, j in bi.items():
    w1, w2 = pair.split(" ")
    if j < ANALYSES["pairs"]["min_count"] or w1 in STOP or w2 in STOP:
        continue
    pmi = math.log2(j * n_all / (uni["all"][w1] * uni["all"][w2]))
    pairs.append({"w1": w1, "w2": w2, "count": j, "pmi": round(pmi, 3)})
pairs.sort(key=lambda p: (-p["pmi"], p["w1"], p["w2"]))
results["models"]["pairs"] = {
    "method": "collocation", "group": "all", "window": 1, "measure": "pmi", "min_count": 5,
    "outputs": {"pairs": pairs[: ANALYSES["pairs"]["top"]]},
}

# The fear dictionary: hits per group, and a validation sample of hits with their passages.
entries = ANALYSES["fear_words"]["dictionary"]["terms"]
exact = {e for e in entries if not e.endswith("*")}
prefixes = tuple(e[:-1] for e in entries if e.endswith("*"))


def is_hit(tok):
    return tok in exact or tok.startswith(prefixes)


by_group = []
for g in ["all", "early", "late"] + [f"y{y}" for y in YEARS]:
    n = size(g)
    hits = sum(v for t, v in uni[g].items() if is_hit(t))
    row = {"group": g, "hits": hits, "n_tokens": n, "per_10k": per10k(hits, n)}
    if g.startswith("y"):
        row["year"] = int(g[1:])
    by_group.append(row)

all_hits = []
for doc_id in sorted(docs):
    norm = unicodedata.normalize("NFC", docs[doc_id]["text"])
    low = norm.lower()
    assert len(low) == len(norm)
    for m in PATTERN.finditer(low):
        if is_hit(m.group(0)):
            all_hits.append((doc_id, m.group(0), m.start(), m.end()))
SEED = 20261011
sample = random.Random(SEED).sample(all_hits, min(ANALYSES["fear_words"]["validation_items"], len(all_hits)))
items = []
for doc_id, term, s, e in sorted(sample, key=lambda h: (h[0], h[2])):
    norm = unicodedata.normalize("NFC", docs[doc_id]["text"])
    lo, hi = max(0, s - 120), min(len(norm), e + 120)
    items.append({"doc_id": doc_id, "term": term, "quote": " ".join(norm[lo:hi].split())})
json.dump({"fear_words": {"seed": SEED, "n_hits_total": len(all_hits), "items": items}},
          open("validation_sample.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
results["models"]["fear_words"] = {
    "method": "dictionary",
    "analysis": "fear_words",
    "dictionary": ANALYSES["fear_words"]["dictionary"],
    "outputs": {"by_group": by_group, "n_hits_total": len(all_hits)},
    "validation": {"file": "text_validation.json", "sample": "validation_sample.json", "seed": SEED,
                   "n_items": len(items)},
}

# Diachronic: the design's terms per year (one work per year).
series = []
for y in YEARS:
    g = f"y{y}"
    for t in ANALYSES["fear_over_time"]["terms"]:
        series.append({"group": g, "year": y, "term": t, "count": uni[g][t], "per_10k": per10k(uni[g][t], size(g))})
results["models"]["fear_over_time"] = {"method": "diachronic", "outputs": {"series": series}}

# Topics: NMF on TF-IDF of 1000-token segments, stop words removed; k chosen by stability across seeds.
SEG = ANALYSES["topics"]["segment_tokens"]
TOP = ANALYSES["topics"]["top_n"]
segments, seg_ids = [], []
for doc_id in sorted(docs):
    t = docs[doc_id]["tokens"]
    for s in range(math.ceil(len(t) / SEG)):
        segments.append([w for w in t[s * SEG : (s + 1) * SEG] if w not in STOP])
        seg_ids.append((doc_id, s))
vec = TfidfVectorizer(analyzer=lambda x: x, min_df=2)
X = vec.fit_transform(segments)
vocab = np.array(vec.get_feature_names_out())


def fit(k, seed):
    model = NMF(n_components=k, init="random", random_state=seed, max_iter=2000)
    W = model.fit_transform(X)
    tops = [[str(w) for w in vocab[np.argsort(-row, kind="stable")[:TOP]]] for row in model.components_]
    return model, W, tops


def jaccard(a, b):
    return len(set(a) & set(b)) / len(set(a) | set(b))


def stability(runs):
    vals = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            a, b = runs[i], runs[j]
            ab = sum(max(jaccard(t, u) for u in b) for t in a) / len(a)
            ba = sum(max(jaccard(u, t) for t in a) for u in b) / len(b)
            vals.append((ab + ba) / 2)
    return sum(vals) / len(vals)


seeds = ANALYSES["topics"]["seeds"]
fits = {k: {s: fit(k, s) for s in seeds} for k in ANALYSES["topics"]["k_candidates"]}
k_sel = [{"k": k, "metric": "mean best-match Jaccard of the top 10 terms across seeds 1-3",
          "value": round(stability([fits[k][s][2] for s in seeds]), 4),
          "reconstruction_error_seed_1": round(float(fits[k][seeds[0]][0].reconstruction_err_), 4)}
         for k in sorted(fits)]
best = max(k_sel, key=lambda r: (r["value"], -r["k"]))["k"]
model, W, tops = fits[best][seeds[0]]
shares = W / np.where(W.sum(axis=1, keepdims=True) > 0, W.sum(axis=1, keepdims=True), 1)
topics = []
for i in range(best):
    order = np.argsort(-W[:, i], kind="stable")[:2]
    topics.append({"id": i, "top_terms": tops[i],
                   "example_documents": [{"doc_id": seg_ids[j][0], "segment": seg_ids[j][1],
                                          "weight": round(float(W[j, i]), 4)} for j in order]})
prevalence = []
for g in ("early", "late"):
    rows_g = [j for j, (doc_id, _s) in enumerate(seg_ids) if doc_id in GROUPS[g] and W[j].sum() > 0]
    mean = shares[rows_g].mean(axis=0)
    mean = mean / mean.sum()
    vals = [round(float(x), 4) for x in mean]
    vals[-1] = round(1 - sum(vals[:-1]), 4)
    for i in range(best):
        prevalence.append({"group": g, "topic": i, "label": f"{g} T{i}", "share": vals[i]})
results["models"]["topics"] = {
    "method": "topic_model",
    "algorithm": "nmf",
    "k": best,
    "seed": seeds[0],
    "segment_tokens": SEG,
    "n_segments": len(segments),
    "features": "TF-IDF of tokens without stop words, in at least 2 segments",
    "k_selection": k_sel,
    "stability": {"top_n": TOP, "runs": [{"seed": s, "topics": fits[best][s][2]} for s in seeds],
                  "mean_best_match_jaccard": round(stability([fits[best][s][2] for s in seeds]), 4)},
    "outputs": {"topics": topics, "prevalence": prevalence},
}

json.dump(results, open("estimation_results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(json.dumps({"k": best, "k_selection": k_sel, "hits": len(all_hits)}))
