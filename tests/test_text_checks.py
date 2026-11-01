"""The text-analysis template's checks, one refusal at a time (src/core/pipeline/text_checks.py).

A study folder with a tiny corpus of four documents is built correctly by
``_study``; each test changes one thing and expects the check's rule letter
in the reasons.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

import pytest

from src.core.pipeline import text_checks as tc

ROOT = Path(__file__).resolve().parents[1]

DOCS = {
    "d1": (1850, "early", "The ghost walked. The house was dark, and fear filled the house at night."),
    "d2": (1855, "early", "Old house, old door. She felt no fear; terror came later, by the door."),
    "d3": (1890, "late", "The door opened. Fear and terror and horror! He said nothing; she said: don’t."),
    "d4": (1895, "late", "He said the garden was quiet. She said the garden was green and the door was shut."),
}
PATTERN = "[a-z]+(?:['’][a-z]+)?"
STOP = ["the", "and", "was", "a", "at", "by", "no", "he", "she"]


def _tokens(text: str) -> list[str]:
    return tc.Preprocessing(PATTERN, True).tokens(text)


def _design() -> dict[str, Any]:
    return {
        "question": "Does fear vocabulary differ between early and late documents?",
        "corpus": {
            "description": "four test documents",
            "selection": "written for the test",
            "sampling": "purposive",
            "n_documents_planned": 4,
            "table": "corpus",
            "id_column": "doc_id",
            "text_column": "text",
        },
        "metadata": {
            "year": {"description": "year", "source": "invented for the test"},
            "period": {"description": "early or late", "source": "derived from year"},
        },
        "preprocessing": {
            "token_pattern": PATTERN,
            "lowercase": True,
            "stopwords": {"file": "stopwords.txt", "source": "a test list"},
            "lemmatisation": "none",
            "ngrams": [1, 2],
        },
        "groups": {"early": {"column": "period", "value": "early"}, "late": {"column": "period", "value": "late"}},
        "analyses": [
            {"id": "freq", "method": "term_frequency", "terms": ["fear", "door"]},
            {"id": "key", "method": "keyness", "target": "late", "reference": "early"},
            {"id": "pairs", "method": "collocation", "measure": "pmi", "window": 1},
            {
                "id": "fear_words",
                "method": "dictionary",
                "dictionary": {"terms": ["fear", "terror*", "horror*"], "source": "test"},
            },
            {"id": "topics", "method": "topic_model", "algorithm": "nmf", "k_candidates": [2, 3], "seeds": [1, 2, 3]},
        ],
        "limits": {"sampling_bias": "four invented documents"},
    }


def _g2(a: int, b: int, c: int, d: int) -> float:
    return tc.log_likelihood(a, b, c, d)


def _study(ws: Path) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "data.db").unlink(missing_ok=True)
    (ws / "stopwords.txt").write_text("\n".join(STOP) + "\n", encoding="utf-8", newline="\n")
    design = _design()
    (ws / tc.DESIGN_FILE).write_text(json.dumps(design), encoding="utf-8", newline="\n")
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE corpus (doc_id TEXT, year INTEGER, period TEXT, text TEXT)")
    con.executemany("INSERT INTO corpus VALUES (?, ?, ?, ?)", [(k, y, p, t) for k, (y, p, t) in DOCS.items()])
    con.commit()
    con.close()
    toks = {k: _tokens(t) for k, (_y, _p, t) in DOCS.items()}
    lengths = sorted(len(v) for v in toks.values())
    stats = {
        "n_documents": 4,
        "n_tokens": sum(lengths),
        "n_types": len({w for v in toks.values() for w in v}),
        "length": {
            "min": lengths[0],
            "p25": round(tc.quantile(lengths, 0.25), 2),
            "median": round(tc.quantile(lengths, 0.5), 2),
            "p75": round(tc.quantile(lengths, 0.75), 2),
            "max": lengths[-1],
            "mean": round(sum(lengths) / 4, 2),
        },
    }
    manifest = {
        "documents": [
            {
                "doc_id": k,
                "source": "test",
                "licence": "CC0",
                "sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(),
                "n_tokens": len(toks[k]),
            }
            for k, (_y, _p, t) in DOCS.items()
        ],
        "corpus": stats,
    }
    (ws / tc.MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8", newline="\n")

    def count(term: str, ids: list[str]) -> int:
        n = len(term.split())
        return sum(sum(1 for i in range(len(toks[d]) - n + 1) if " ".join(toks[d][i : i + n]) == term) for d in ids)

    early, late = ["d1", "d2"], ["d3", "d4"]
    n_e, n_l = len(toks["d1"]) + len(toks["d2"]), len(toks["d3"]) + len(toks["d4"])
    a, b = count("said", late), count("said", early)
    j = count("old house", early + late)
    runs = [
        {
            "seed": 1,
            "topics": [["house", "fear", "door", "night", "dark"], ["said", "garden", "green", "quiet", "shut"]],
        },
        {
            "seed": 2,
            "topics": [["said", "garden", "green", "quiet", "shut"], ["house", "fear", "door", "night", "dark"]],
        },
        {"seed": 3, "topics": [["house", "fear", "door", "old", "dark"], ["said", "garden", "green", "quiet", "shut"]]},
    ]
    stability = tc.topic_stability([r["topics"] for r in runs])
    hits = {
        g: sum(count(t, ids) for t in ("fear", "terror", "horror")) for g, ids in (("early", early), ("late", late))
    }
    results = {
        "result_kind": "text",
        "corpus": {
            **{k: stats[k] for k in ("n_documents", "n_tokens", "n_types")},
            "preprocessing": design["preprocessing"],
        },
        "term_frequencies": {
            "all": {
                "n_tokens": n_e + n_l,
                "terms": [
                    {
                        "term": "fear",
                        "count": count("fear", early + late),
                        "per_10k": round(count("fear", early + late) / (n_e + n_l) * 1e4, 4),
                        "documents": 3,
                    },
                    {"term": "old house", "count": j},
                ],
            },
            "late": {"n_tokens": n_l, "terms": [{"term": "door", "count": count("door", late)}]},
        },
        "models": {
            "key": {
                "method": "keyness",
                "target": "late",
                "reference": "early",
                "outputs": {
                    "terms": [
                        {
                            "term": "said",
                            "count_target": a,
                            "count_reference": b,
                            "g2": round(_g2(a, b, n_l, n_e), 3),
                            "log_ratio": round(tc.log_ratio(a, b, n_l, n_e), 3),
                            "p_value": float(f"{tc.chi2_1_p(_g2(a, b, n_l, n_e)):.4g}"),
                            "more_in": "late",
                            "documents_target": 2,
                        }
                    ]
                },
            },
            "pairs": {
                "method": "collocation",
                "group": "all",
                "window": 1,
                "outputs": {
                    "pairs": [
                        {
                            "w1": "old",
                            "w2": "house",
                            "count": j,
                            "pmi": round(
                                math.log2(
                                    j * (n_e + n_l) / (count("old", early + late) * count("house", early + late))
                                ),
                                3,
                            ),
                        }
                    ]
                },
            },
            "fear_words": {
                "method": "dictionary",
                "analysis": "fear_words",
                "dictionary": design["analyses"][3]["dictionary"],
                "outputs": {
                    "by_group": [
                        {
                            "group": "early",
                            "hits": hits["early"],
                            "n_tokens": n_e,
                            "per_10k": round(hits["early"] / n_e * 1e4, 4),
                        },
                        {"group": "late", "hits": hits["late"], "n_tokens": n_l},
                    ]
                },
                "validation": {"precision": 0.75},
            },
            "topics": {
                "method": "topic_model",
                "algorithm": "nmf",
                "k": 2,
                "seed": 1,
                "k_selection": [
                    {"k": 2, "metric": "stability", "value": 0.9},
                    {"k": 3, "metric": "stability", "value": 0.6},
                ],
                "stability": {"top_n": 5, "runs": runs, "mean_best_match_jaccard": round(stability or 0, 4)},
                "outputs": {
                    "topics": [
                        {
                            "id": 0,
                            "top_terms": runs[0]["topics"][0],
                            "example_documents": [{"doc_id": "d1"}, {"doc_id": "d2"}],
                        },
                        {
                            "id": 1,
                            "top_terms": runs[0]["topics"][1],
                            "example_documents": [{"doc_id": "d4"}, {"doc_id": "d3"}],
                        },
                    ],
                    "prevalence": [
                        {"group": "early", "topic": 0, "share": 0.8},
                        {"group": "early", "topic": 1, "share": 0.2},
                        {"group": "late", "topic": 0, "share": 0.3},
                        {"group": "late", "topic": 1, "share": 0.7},
                    ],
                },
            },
        },
        "limits": {"sampling_bias": "four invented documents"},
    }
    (ws / tc.RESULTS_FILE).write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8", newline="\n")
    figures = {
        "figures": [
            {"filename": "fig_key.pdf", "figure_type": "bar", "source": {"results": "models.key.outputs.terms"}},
            {
                "filename": "fig_topics.pdf",
                "figure_type": "multi_panel",
                "panels": [{"figure_type": "bar", "source": {"results": "models.topics.outputs.prevalence"}}],
            },
        ]
    }
    (ws / "figure_spec.json").write_text(json.dumps(figures), encoding="utf-8", newline="\n")
    sample = {
        "fear_words": {
            "seed": 7,
            "n_hits_total": hits["early"] + hits["late"],
            "items": [
                {"doc_id": "d1", "term": "fear", "quote": "The house was dark, and fear filled the house"},
                {"doc_id": "d2", "term": "fear", "quote": "She felt no fear; terror came later"},
                {"doc_id": "d2", "term": "terror", "quote": "no fear; terror came later, by the door."},
                {"doc_id": "d3", "term": "horror", "quote": "Fear and terror and horror!"},
            ],
        }
    }
    (ws / tc.SAMPLE_FILE).write_text(json.dumps(sample), encoding="utf-8", newline="\n")
    judged = copy.deepcopy(sample)["fear_words"]
    for i, it in enumerate(judged["items"]):
        it["correct"] = i != 1
        it["reason"] = "negated: she felt no fear" if i == 1 else "fear in the scene"
    judged["precision"] = 0.75
    (ws / tc.VALIDATION_FILE).write_text(json.dumps({"fear_words": judged}), encoding="utf-8", newline="\n")
    return ws


def _edit(ws: Path, name: str, change) -> None:
    doc = json.loads((ws / name).read_text(encoding="utf-8"))
    change(doc)
    (ws / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8", newline="\n")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return _study(tmp_path / "study")


def _all(ws: Path) -> list[tc.Verdict]:
    return [
        tc.check_corpus_design(ws),
        tc.check_corpus(ws),
        tc.check_text_results(ws, min_seeds=3, min_examples=2),
        tc.check_text_validation(ws, min_validation_items=4),
    ]


def _reasons(v: tc.Verdict) -> str:
    return " | ".join(v.reasons)


def test_a_correct_study_passes_every_check(ws: Path):
    verdicts = _all(ws)
    assert all(v.passed for v in verdicts), [v.reasons for v in verdicts]
    check = json.loads((ws / tc.CORPUS_CHECK_FILE).read_text(encoding="utf-8"))
    assert check["n_documents"] == 4 and set(check["files_sha256"]) == {"stopwords.txt"}
    assert json.loads((ws / tc.VALIDATION_CHECK_FILE).read_text(encoding="utf-8"))["measures"]["fear_words"] == {
        "n_items": 4,
        "n_correct": 3,
        "precision": 0.75,
    }


# ── the statistics ─────────────────────────────────────────────────────────


def test_log_likelihood_and_log_ratio_follow_the_textbook_formulas():
    # Rayson and Garside (2000): a = 30 in 10,000 tokens against b = 10 in 20,000.
    e1, e2 = 10_000 * 40 / 30_000, 20_000 * 40 / 30_000
    want = 2 * (30 * math.log(30 / e1) + 10 * math.log(10 / e2))
    assert tc.log_likelihood(30, 10, 10_000, 20_000) == pytest.approx(want)
    assert tc.log_likelihood(0, 10, 10_000, 20_000) == pytest.approx(2 * 10 * math.log(10 / (20_000 * 10 / 30_000)))
    assert tc.log_ratio(30, 10, 10_000, 20_000) == pytest.approx(math.log2(6))
    assert tc.log_ratio(0, 10, 10_000, 20_000) == pytest.approx(math.log2((0.5 / 10_000) / (10 / 20_000)))
    assert tc.chi2_1_p(3.841459) == pytest.approx(0.05, abs=1e-5)


def test_topic_stability_is_one_for_the_same_topics_in_another_order_and_falls_with_change():
    a = [["x", "y"], ["u", "v"]]
    assert tc.topic_stability([a, list(reversed(a))]) == 1.0
    assert tc.topic_stability([a, [["x", "z"], ["u", "v"]]]) == pytest.approx((1 / 3 + 1) / 2)
    assert tc.topic_stability([a]) is None


def test_the_tokeniser_normalises_lowers_and_keeps_apostrophes():
    pre = tc.Preprocessing(PATTERN, True, lemmas=(("doors", "door"),), max_ngram=2)
    assert pre.tokens("Doors don’t OPEN") == ["door", "don’t", "open"]
    assert pre.is_token("old house") and not pre.is_token("Old") and not pre.is_token("a b c")
    assert not tc.Preprocessing(PATTERN, True, max_ngram=1).is_token("old house")


# ── corpus_design (a)-(f) ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (lambda d: d.pop("question"), "(a) question"),
        (lambda d: d["corpus"].pop("sampling"), "(a) corpus.sampling"),
        (lambda d: d.pop("limits"), "(a) limits.sampling_bias"),
        (lambda d: d["corpus"].pop("text_column"), "(b)"),
        (lambda d: d["metadata"]["year"].pop("source"), "(c) metadata.year"),
        (lambda d: d["preprocessing"].update(token_pattern="([a-z]+)"), "capturing groups"),
        (lambda d: d["preprocessing"].update(token_pattern="[a-z]*"), "matches the empty string"),
        (lambda d: d["preprocessing"].update(token_pattern="[a-z"), "not a valid regular expression"),
        (lambda d: d["preprocessing"].update(lowercase="yes"), "lowercase must be true or false"),
        (lambda d: d["preprocessing"].update(stopwords="nltk"), "stopwords must be"),
        (lambda d: d["preprocessing"]["stopwords"].pop("source"), "stopwords needs its source"),
        (lambda d: d["preprocessing"].update(lemmatisation="spacy"), "lemmatisation must be"),
        (lambda d: d["preprocessing"].update(ngrams=[1, 5]), "ngrams must be"),
        (lambda d: d["groups"].update(late={"column": "period"}), "(e) groups.late"),
        (lambda d: d["groups"].update(late={"column": "genre", "value": "x"}), "which metadata does not declare"),
        (lambda d: d["analyses"].append({"id": "x", "method": "embeddings"}), "is not one e2er checks"),
        (lambda d: d["analyses"][1].update(reference="middle"), "keyness needs reference"),
        (lambda d: d["analyses"][3].pop("dictionary"), "needs its dictionary in the design"),
        (lambda d: d["analyses"][3]["dictionary"].pop("source"), "dictionary needs its source"),
        (lambda d: d["analyses"][4].update(algorithm="bertopic"), "algorithm must be lda or nmf"),
        (lambda d: d["analyses"][4].update(k_candidates=[4]), "k_candidates must list"),
        (lambda d: d["analyses"][4].update(seeds=[1, 1, 2]), "seeds must list at least 3"),
        (
            lambda d: d["analyses"].append({"id": "s", "method": "sentiment", "lexicon": {"citation": "x"}}),
            "lexicon must give its entries by category",
        ),
    ],
)
def test_the_design_check_refuses(ws: Path, change, rule: str):
    _edit(ws, tc.DESIGN_FILE, change)
    v = tc.check_corpus_design(ws)
    assert not v.passed and rule in _reasons(v), v.reasons


def test_the_design_check_lets_the_corpus_build_write_the_stop_words_later(ws: Path):
    (ws / "stopwords.txt").unlink()
    assert tc.check_corpus_design(ws).passed
    v = tc.check_corpus(ws)
    assert not v.passed and "stopwords.txt is missing" in _reasons(v)
    (ws / "data").mkdir()
    (ws / "data" / "stopwords.txt").write_text("the\n", encoding="utf-8", newline="\n")
    assert "there is data/stopwords.txt: paths in corpus_design.json are relative to the study folder" in _reasons(
        tc.check_corpus(ws)
    )


# ── corpus (g)-(j) ─────────────────────────────────────────────────────────


def test_the_corpus_check_refuses_a_document_without_source_or_licence(ws: Path):
    _edit(ws, tc.MANIFEST_FILE, lambda m: (m["documents"][0].pop("source"), m["documents"][1].update(licence="")))
    r = _reasons(tc.check_corpus(ws))
    assert "(g) documents without a source" in r and "d1" in r and "(g) documents without a licence" in r


def test_the_corpus_check_refuses_documents_with_the_same_text(ws: Path):
    con = sqlite3.connect(ws / "data.db")
    con.execute("UPDATE corpus SET text = (SELECT text FROM corpus WHERE doc_id = 'd1') WHERE doc_id = 'd2'")
    con.commit()
    con.close()
    r = _reasons(tc.check_corpus(ws))
    assert "(g) documents with the same text: d1, d2" in r and "(h) the SHA-256" in r


def test_the_corpus_check_recounts_tokens_and_statistics(ws: Path):
    _edit(ws, tc.MANIFEST_FILE, lambda m: (m["documents"][2].update(n_tokens=99), m["corpus"].update(n_types=3)))
    r = _reasons(tc.check_corpus(ws))
    assert "(h) token counts differ" in r and "d3 (99 stated" in r and "(i) corpus.n_types: 3 stated" in r


def test_the_corpus_check_refuses_a_table_document_missing_from_the_manifest(ws: Path):
    _edit(ws, tc.MANIFEST_FILE, lambda m: m["documents"].pop())
    assert "(g) documents of the corpus table missing from corpus_manifest.json: d4" in _reasons(tc.check_corpus(ws))


def test_the_corpus_check_wants_every_metadata_value_or_a_reason(ws: Path):
    con = sqlite3.connect(ws / "data.db")
    con.execute("UPDATE corpus SET year = NULL WHERE doc_id = 'd4'")
    con.commit()
    con.close()
    assert "(j) documents without year: d4" in _reasons(tc.check_corpus(ws))
    _edit(ws, tc.DESIGN_FILE, lambda d: d["metadata"]["year"].update(missing="date unknown"))
    v = tc.check_corpus(ws)
    assert v.passed and any("without year: date unknown" in n for n in v.notes)
    _edit(ws, tc.DESIGN_FILE, lambda d: d["metadata"].update(genre={"source": "x"}))
    assert "(j) metadata.genre is not a column" in _reasons(tc.check_corpus(ws))


# ── text_results (k)-(q) ───────────────────────────────────────────────────


def _results_reasons(ws: Path) -> str:
    assert tc.check_corpus(ws).passed
    return _reasons(tc.check_text_results(ws))


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (lambda r: r["corpus"]["preprocessing"].update(lowercase=False), "(k) the preprocessing the results state"),
        (lambda r: r["corpus"].update(n_tokens=5), "(k) corpus.n_tokens: 5 in the results"),
        (lambda r: r["term_frequencies"]["all"]["terms"][0].update(count=99), "(l) term_frequencies.all"),
        (lambda r: r["term_frequencies"]["all"]["terms"][0].update(per_10k=1.0), "per_10k (1.0 stated"),
        (lambda r: r["term_frequencies"]["all"]["terms"][0].update(documents=1), "fear in 1 documents stated, 3"),
        (lambda r: r["term_frequencies"]["late"].update(n_tokens=1), "(l) term_frequencies.late.n_tokens: 1 stated"),
        (lambda r: r["term_frequencies"]["all"]["terms"].append({"term": "Fear", "count": 0}), "is not a token"),
        (lambda r: r["term_frequencies"]["all"]["terms"].append({"term": "a b c", "count": 0}), "more than 2 word"),
        (lambda r: r["term_frequencies"].update(middle={"terms": [{"term": "x", "count": 0}]}), "group 'middle'"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(g2=99.0), "(m) models.key: said: G2 99.0"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(log_ratio=0.1), "log ratio 0.1 stated"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(p_value=0.5), "p 0.5 stated"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(more_in="early"), "more_in early"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(count_target=9), "counts 9/"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(documents_target=1), "target documents"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].update(term="the"), "is a stop word"),
        (lambda r: r["models"]["key"]["outputs"]["terms"][0].pop("log_ratio"), "report an effect size"),
        (lambda r: r["models"]["key"].update(reference="late", target="early"), "are not the design's"),
        (lambda r: r["models"]["pairs"]["outputs"]["pairs"][0].update(count=7), "(n) models.pairs: old house"),
        (lambda r: r["models"]["pairs"]["outputs"]["pairs"][0].update(pmi=0.5), "PMI 0.5 stated"),
        (
            lambda r: r["models"]["fear_words"]["dictionary"]["terms"].append("ghost*"),
            "the dictionary is not the one corpus_design.json froze",
        ),
        (lambda r: r["models"]["fear_words"]["outputs"]["by_group"][0].update(hits=1), "(o) models.fear_words"),
        (
            lambda r: (
                r["models"]["fear_words"].pop("analysis") and r["models"].update(fw2=r["models"].pop("fear_words"))
            ),
            "no analysis of corpus_design.json",
        ),
        (lambda r: r["models"]["topics"].pop("seed"), "(p) models.topics.seed"),
        (
            lambda r: r["models"]["topics"].update(k_selection=[{"k": 2, "metric": "x", "value": 1}]),
            "k_selection must give",
        ),
        (lambda r: r["models"]["topics"]["stability"]["runs"].pop(), "under at least 3"),
        (
            lambda r: r["models"]["topics"]["stability"].update(mean_best_match_jaccard=0.99),
            "mean_best_match_jaccard: 0.99",
        ),
        (lambda r: r["models"]["topics"]["outputs"]["topics"][0].update(top_terms=["house"]), "at least 5 top terms"),
        (
            lambda r: r["models"]["topics"]["outputs"]["topics"][0]["example_documents"].pop(),
            "at least 2 example documents",
        ),
        (
            lambda r: r["models"]["topics"]["outputs"]["topics"][0]["example_documents"][0].update(doc_id="d9"),
            "'d9', not in the corpus",
        ),
        (lambda r: r["models"]["topics"]["outputs"]["prevalence"][0].update(share=0.5), "add up to 0.700"),
        (
            lambda r: r["models"]["topics"]["outputs"]["topics"][1].update(
                top_terms=["said", "garden", "green", "quiet", "open"]
            ),
            "not those of the stability run",
        ),
        (lambda r: r["models"].pop("pairs"), "(f) the design declares collocation"),
        (lambda r: r.pop("limits"), "(q) limits.sampling_bias"),
    ],
)
def test_the_results_check_refuses(ws: Path, change, rule: str):
    _edit(ws, tc.RESULTS_FILE, change)
    r = _results_reasons(ws)
    assert rule in r, r


def test_a_word_list_changed_after_the_corpus_check_stops_the_results_and_the_validation(ws: Path):
    assert tc.check_corpus(ws).passed
    (ws / "stopwords.txt").write_text("the\n", encoding="utf-8", newline="\n")
    assert "(k) stopwords.txt changed after the corpus check froze it" in _reasons(tc.check_text_results(ws))
    assert "(r) stopwords.txt changed" in _reasons(tc.check_text_validation(ws))


def test_unstable_topics_pass_with_a_note(ws: Path):
    def unstable(r: dict) -> None:
        runs = r["models"]["topics"]["stability"]["runs"]
        runs[1]["topics"] = [["a", "b", "c", "d", "e"], ["f", "g", "h", "i", "j"]]
        runs[2]["topics"] = [["k", "l", "m", "n", "o"], ["p", "q", "r", "s", "t"]]
        r["models"]["topics"]["stability"]["mean_best_match_jaccard"] = round(
            tc.topic_stability([x["topics"] for x in runs]) or 0, 4
        )

    _edit(ws, tc.RESULTS_FILE, unstable)
    assert tc.check_corpus(ws).passed
    v = tc.check_text_results(ws)
    assert v.passed and any("change much between seeds" in n for n in v.notes), (v.reasons, v.notes)


# ── text_validation (r)-(u) ────────────────────────────────────────────────


def _validation(ws: Path, **kw: Any) -> str:
    assert tc.check_corpus(ws).passed
    return _reasons(tc.check_text_validation(ws, min_validation_items=kw.get("n", 4)))


def test_the_validation_check_wants_a_large_enough_seeded_sample(ws: Path):
    assert "(r) the sample of fear_words has 4 items; it needs at least 5" in _validation(ws, n=5)
    _edit(ws, tc.SAMPLE_FILE, lambda s: s["fear_words"].pop("seed"))
    assert "(r) validation_sample.json.fear_words.seed" in _validation(ws)
    (ws / tc.SAMPLE_FILE).unlink()
    assert "(r) validation_sample.json has no sample for fear_words" in _validation(ws)


def test_the_validation_check_finds_every_quote_in_its_document_with_its_term(ws: Path):
    _edit(ws, tc.SAMPLE_FILE, lambda s: s["fear_words"]["items"][0].update(quote="the house was full of fear"))
    _edit(ws, tc.VALIDATION_FILE, lambda s: s["fear_words"]["items"][0].update(quote="the house was full of fear"))
    assert "(s) fear_words: passages not found verbatim in their document: item 0 (d1)" in _validation(ws)
    _study(ws)
    _edit(ws, tc.SAMPLE_FILE, lambda s: s["fear_words"]["items"][3].update(term="fear", quote="and terror and horror!"))
    assert "(s) fear_words: passages without a hit" in _validation(ws)


def test_the_validation_check_wants_every_item_judged_and_nothing_else(ws: Path):
    _edit(ws, tc.VALIDATION_FILE, lambda s: s["fear_words"]["items"].pop())
    assert "(t) fear_words: 1 item(s) of the sample are not judged" in _validation(ws)
    _study(ws)
    _edit(ws, tc.VALIDATION_FILE, lambda s: s["fear_words"]["items"][0].update(quote="The ghost walked."))
    assert "judgements of passages that are not in the sample" in _validation(ws)
    _study(ws)
    _edit(ws, tc.VALIDATION_FILE, lambda s: s["fear_words"]["items"][1].update(reason=""))
    assert "(t) fear_words: items judged wrong need a reason: d2" in _validation(ws)
    _study(ws)
    _edit(ws, tc.VALIDATION_FILE, lambda s: s["fear_words"]["items"][1].update(correct="no"))
    assert "every judgement needs correct: true or false" in _validation(ws)


def test_the_validation_check_recomputes_the_precision(ws: Path):
    _edit(ws, tc.VALIDATION_FILE, lambda s: s["fear_words"].update(precision=1.0))
    assert "(u) text_validation.json.fear_words.precision: 1.0 stated; 3 of 4 judged right is 0.7500" in _validation(ws)
    _study(ws)
    _edit(ws, tc.RESULTS_FILE, lambda r: r["models"]["fear_words"]["validation"].update(precision=0.9))
    assert "(u) models.fear_words.validation.precision: 0.9 stated" in _validation(ws)


def test_a_study_without_a_dictionary_has_nothing_to_validate(ws: Path):
    _edit(ws, tc.RESULTS_FILE, lambda r: r["models"].pop("fear_words"))
    v = tc.check_text_validation(ws)
    assert v.passed and v.stats == {"measures": 0}


# ── the template ───────────────────────────────────────────────────────────


def test_the_template_loads_with_its_checks_panel_and_credits():
    from src.core.pipeline.spec import find_spec, load_spec

    spec = find_spec("text-analysis")
    assert spec.results == "text" and not spec.causal and spec.base_skill == "base/researcher"
    gates = [(s.check, s.after, s.on_fail) for s in spec.steps if s.kind == "gate"]
    assert gates[:4] == [
        ("corpus_design", ("data_architect",), "retry"),
        ("corpus", ("data_analyst",), "retry"),
        ("text_results", ("econometrics_specialist",), "retry"),
        ("text_validation", ("econometrics_specialist", "text_validator"), "retry"),
    ]
    assert [g[0] for g in gates[4:]] == ["estimation", "figure_data"]
    assert sorted(spec.panel()) == sorted(
        ["methods_reviewer", "data_reviewer", "plausibility_reviewer", "writing_reviewer", "technical_reviewer"]
    )
    raw = tomllib.loads((ROOT / "pipelines" / "text-analysis.toml").read_text(encoding="utf-8"))
    credit = raw["credit"]
    urls = " ".join(c["url"] for c in credit)
    for doi in ("10.3115/1117729.1117730", "10.1093/pan/mps028", "10.1257/jel.20181020", "10.1038/44565"):
        assert doi in urls
    assert "aclanthology.org/J93-1003" in urls and "jmlr.org/papers/v3/blei03a" in urls
    doc = json.loads((ROOT / "credits.json").read_text(encoding="utf-8"))
    assert doc["parts"]["template:text-analysis"] == credit
    assert load_spec(ROOT / "pipelines" / "text-analysis.toml").credit == tuple(credit)


def test_the_text_validator_is_a_registered_specialist_and_the_strategist_is_told_when_to_dispatch_it():
    from src.core.labels import SPECIALISTS, STEPS, TEMPLATES
    from src.core.pipeline.components import activate, deactivate
    from src.core.pipeline.spec import find_spec
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_NEEDS, SPECIALIST_SIDECAR_ARTIFACTS
    from src.core.strategist.context import template_context

    assert SPECIALIST_ARTIFACTS["text_validator"] == "text_validation.md"
    assert SPECIALIST_SIDECAR_ARTIFACTS["text_validator"] == ["text_validation.json"]
    assert "text_validator" in SPECIALIST_NEEDS["paper_drafter"]
    assert SPECIALIST_NEEDS["text_validator"] == ("econometrics_specialist",)
    assert SPECIALISTS["text_validator"] and TEMPLATES["text-analysis"]
    for step in ("corpus_design_gate", "corpus_gate", "text_results_gate", "text_validation_gate"):
        assert step in STEPS
    token = activate(copy.copy(find_spec("text-analysis")))
    try:
        text = template_context()
    finally:
        deactivate(token)
    assert "Dispatch data_architect before econometrics_specialist" in text
    assert "Dispatch text_validator after econometrics_specialist and before paper_drafter" in text
    assert "Dispatch econometrics_specialist before econometrics_specialist" not in text


def test_the_text_kind_traces_numbers_to_the_checks_reports():
    from src.core.pipeline.result_kinds import get

    assert {"corpus_check.json", "text_validation.json"} <= set(get("text").number_sources)


def test_sample_rows_of_a_corpus_table_show_the_start_of_a_text_not_the_whole_book(tmp_path: Path):
    """The live run's analysis prompt carried 20 novels in full through the table catalogue's sample rows."""
    from src.core.strategist.context import _list_data_tables
    from src.db.paper_data_db import list_tables_catalog_sync

    con = sqlite3.connect(tmp_path / "data.db")
    con.execute("CREATE TABLE corpus (doc_id TEXT, text TEXT)")
    con.execute("INSERT INTO corpus VALUES ('pg1', ?)", ("word " * 100_000,))
    con.commit()
    con.close()
    cell = list_tables_catalog_sync(tmp_path)[0]["samples"][0][1]
    assert cell.endswith("(500,000 characters)") and len(cell) < 300
    assert len(_list_data_tables(tmp_path)) < 1000


def test_the_results_check_wants_a_figure_of_the_key_terms_and_the_topics(ws: Path):
    _edit(ws, "figure_spec.json", lambda f: f["figures"][1]["panels"][0]["source"].update(results="corpus"))
    r = _results_reasons(ws)
    assert "(v) no figure shows models.topics (topic shares)" in r and "models.key" not in r.split("(v)")[1]


def test_identical_topics_under_every_seed_of_an_nndsvd_start_pass_with_a_note(ws: Path):
    def same(r: dict) -> None:
        t = r["models"]["topics"]
        for run in t["stability"]["runs"]:
            run["topics"] = t["stability"]["runs"][0]["topics"]
        t["stability"]["mean_best_match_jaccard"] = 1.0
        t["init"] = "nndsvda"

    _edit(ws, tc.RESULTS_FILE, same)
    assert tc.check_corpus(ws).passed
    v = tc.check_text_results(ws)
    assert v.passed and any("ignores the seed" in n for n in v.notes), (v.reasons, v.notes)


def test_a_rerun_of_the_analysis_runs_the_checks_of_its_results_again(tmp_path: Path):
    """The live run was rerun from its iterative step; its results check had passed before and would not
    have run again on the new results."""
    from src.core.pipeline.researcher import apply_rerun
    from src.core.pipeline.spec import find_spec
    from src.core.pipeline.state import PipelineState

    spec = find_spec("text-analysis")
    done = ["corpus_design_gate", "corpus_gate", "text_results_gate", "text_validation_gate", "initial", "iterative"]
    state = PipelineState(paper_id="p", mode="iterative", completed_stages=[*done, "review"])
    state.metadata["retried_text_results_gate"] = True
    apply_rerun(tmp_path, state, spec, "iterative", "Add the figures.")
    assert "text_results_gate" not in state.completed_stages and "text_validation_gate" not in state.completed_stages
    assert "corpus_gate" in state.completed_stages and "retried_text_results_gate" not in state.metadata
    state = PipelineState(paper_id="p", mode="iterative", completed_stages=[*done, "review"])
    apply_rerun(tmp_path, state, spec, "review", "Score again.")
    assert "text_results_gate" in state.completed_stages


def test_an_nmf_start_that_ignores_the_seed_is_noted_and_listed_for_the_draft_check(ws: Path):
    """Whatever the stability, NMF from nndsvd(a) cannot differ between seeds: a note, and the model is
    listed in text_check.json so the draft may not claim stability across seeds."""

    def nmf(init: str):
        def change(r: dict) -> None:
            r["models"]["topics"]["algorithm"] = "nmf"
            r["models"]["topics"]["init"] = init

        return change

    _edit(ws, tc.RESULTS_FILE, nmf("nndsvd"))
    v = tc.check_text_results(ws)
    assert v.passed and any("may not claim stability across seeds" in n for n in v.notes), (v.reasons, v.notes)
    assert json.loads((ws / tc.RESULTS_CHECK_FILE).read_text(encoding="utf-8"))["seed_independent_models"] == ["topics"]
    _edit(ws, tc.RESULTS_FILE, nmf("random"))
    v = tc.check_text_results(ws)
    assert v.passed and not any("ignores the seed" in n for n in v.notes)
    assert "seed_independent_models" not in json.loads((ws / tc.RESULTS_CHECK_FILE).read_text(encoding="utf-8"))
