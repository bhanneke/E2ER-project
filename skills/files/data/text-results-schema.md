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

## Tables

`"path": "term_frequencies.all.terms", "key_field": "term"` in a `records`
table gives one row per term (see the table-spec skill).
