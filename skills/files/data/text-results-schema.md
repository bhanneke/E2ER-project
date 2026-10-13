# `estimation_results.json` for a text study — the results schema

## Purpose

A text study counts and models language in a corpus: how many documents,
tokens and distinct words; which terms are frequent, overall and by group
(period, author, genre); and what a text model (keyness, topics, sentiment
lexicon, embeddings) finds. Its template declares `results = "text"`; a
deterministic check (`src/core/pipeline/result_kinds.py`) holds
`estimation_results.json` to this schema, and the number check traces the
paper's numbers to it.

Write the file from `run_estimation.py` (run it with `e2er-run`), and record
how the text was tokenised and cleaned (lower-casing, stop words,
lemmatisation, front and back matter removed) in `corpus`.

## Shape

```json
{
  "result_kind": "text",
  "corpus": {"n_documents": 120, "n_tokens": 9876543, "n_types": 98765,
             "tokenizer": "lower-cased word tokens, Unicode letters only", "stopwords": "none removed"},
  "term_frequencies": {
    "all": {"n_tokens": 9876543,
            "terms": [{"term": "the", "count": 612345, "per_10k": 619.99}, {"term": "whale", "count": 1234, "per_10k": 1.25}]},
    "1850s": {"n_tokens": 1200000, "terms": [{"term": "whale", "count": 900, "per_10k": 7.5}]}
  },
  "models": {
    "keyness_1850_vs_1900": {"method": "log-likelihood keyness", "reference": "1900s",
                             "outputs": {"terms": [{"term": "whale", "g2": 812.4, "direction": "more in 1850s"}]}}
  }
}
```

## Required, and what the check verifies

- `"result_kind": "text"` at the top.
- `corpus`: whole `n_documents`, `n_tokens` and `n_types` (each > 0), with
  `n_types <= n_tokens`.
- `term_frequencies`: one list per corpus or group, each term with its whole
  `count`; a `per_10k` must equal count / n_tokens x 10,000 (the group's
  `n_tokens`, else the corpus's), and the counts of a list cannot exceed its
  tokens.
- `models`: each with its `method` and non-empty `outputs`.

Frequencies of different groups are comparable only per token (per 10,000),
never as raw counts. A keyness or topic result describes the corpus; say what
it does not show (cause, intent, reception).

## In the `text-analysis` template

The template's checks (`src/core/pipeline/text_checks.py`, skill
`methods/text-analysis`) recount the results from the corpus and the
preprocessing recorded in `corpus_design.json`, so the results also state:

```json
{
  "result_kind": "text",
  "corpus": {"n_documents": 6, "n_tokens": 101234, "n_types": 9876,
             "preprocessing": {"token_pattern": "[a-z]+(?:'[a-z]+)?", "lowercase": true,
                               "stopwords": {"file": "stopwords.txt", "source": "..."},
                               "lemmatisation": "none", "ngrams": [1, 2]}},
  "term_frequencies": {
    "all":   {"n_tokens": 101234, "terms": [{"term": "fear", "count": 61, "per_10k": 6.0257}]},
    "early": {"n_tokens": 48211,  "terms": [{"term": "fear", "count": 22, "per_10k": 4.5633}]}
  },
  "models": {
    "keyness_late": {"method": "keyness", "target": "late", "reference": "early",
                     "outputs": {"terms": [{"term": "door", "count_target": 120, "count_reference": 31,
                                            "g2": 48.2, "log_ratio": 1.86, "p_value": 1.2e-12, "more_in": "late"}]}},
    "pairs": {"method": "collocation", "group": "all", "window": 1, "min_count": 5,
              "outputs": {"pairs": [{"w1": "old", "w2": "man", "count": 40, "pmi": 5.1}]}},
    "fear_words": {"method": "dictionary", "analysis": "fear_words",
                   "dictionary": {"terms": ["fear", "afraid", "terror*"], "source": "..."},
                   "outputs": {"by_group": [{"group": "early", "hits": 80, "n_tokens": 48211, "per_10k": 16.5937}]},
                   "validation": {"file": "text_validation.json", "precision": 0.85}},
    "topics": {"method": "topic_model", "algorithm": "nmf", "k": 4, "seed": 1, "segment_tokens": 1000,
               "k_selection": [{"k": 3, "metric": "reconstruction error", "value": 41.2},
                               {"k": 4, "metric": "reconstruction error", "value": 39.8}],
               "stability": {"top_n": 10, "runs": [{"seed": 1, "topics": [["house", "door", "..."]]}],
                             "mean_best_match_jaccard": 0.71},
               "outputs": {"topics": [{"id": 0, "top_terms": ["house", "door", "room", "night", "window"],
                                       "example_documents": [{"doc_id": "pg932", "segment": 3, "weight": 0.41}]}],
                           "prevalence": [{"group": "early", "topic": 0, "share": 0.31}]}},
    "fear_over_time": {"method": "diachronic",
                       "outputs": {"series": [{"group": "early", "term": "fear", "count": 22, "per_10k": 4.5633}]}}
  },
  "figures": ["fig_keyness.pdf"],
  "limits": {"sampling_bias": "Six canonical works; what survived and was digitised."}
}
```

- `corpus.preprocessing` exactly as in the design; the corpus figures as
  the corpus check computed them (`corpus_check.json`).
- Groups (`term_frequencies` keys, keyness `target`/`reference`, `group`
  fields) are `all` or the groups the design defines.
- Every term a possible token of the recorded preprocessing; no stop word in
  key-term lists or topics when stop words are removed.
- `models.<id>.method`: `keyness`, `collocation`, `dictionary`, `sentiment`
  (lexicon categories, `category` in `by_group`), `topic_model`, `diachronic`;
  a dictionary or sentiment model names its design analysis in `analysis`.
- `limits.sampling_bias`.

## Tables

`"path": "term_frequencies.all.terms", "key_field": "term"` in a `records`
table gives one row per term (see the table-spec skill).
