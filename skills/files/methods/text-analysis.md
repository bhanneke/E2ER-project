# Text analysis: a corpus you can trace, counts anyone can redo

A text study counts and models language in a corpus: which words are frequent,
which are key in one part of the corpus against another, which words keep
company, how often the words of a dictionary occur, which topics a topic model
finds, and how all of this changes over time. Read by the data architect, the
data analyst, the analysis specialist, the text validator, the drafter and the
reviewers of the `text-analysis` template. The results schema is
`data/text-results-schema`.

Grimmer and Stewart (2013) give the four rules this template is built on: all
quantitative models of language are wrong, but some are useful; they augment
reading, they do not replace it; there is no best method for every corpus;
and every method must be validated on the corpus at hand. Counting words is
mechanical, so e2er recounts: four checks recompute what the study reports
from the corpus and the recorded preprocessing (`src/core/pipeline/text_checks.py`).

The order of the work:

1. **Corpus design** (data architect): `corpus_design.json`, checked by
   `corpus_design`; the researcher reads it before the corpus is built.
2. **Corpus building** (data analyst): the texts loaded, the corpus table
   and `corpus_manifest.json` written by `build_data.py`; checked by `corpus`.
3. **Analysis** (analysis specialist): `run_estimation.py` writes
   `estimation_results.json` and, for a dictionary or sentiment measure, the
   validation sample `validation_sample.json`; checked by `text_results`.
4. **Validation** (text validator): every sampled passage judged in
   `text_validation.json`; checked by `text_validation`.
5. Figures, draft, review panel, number check, citation check.

## 1. The corpus design (`corpus_design.json`, the data architect)

```json
{
  "question": "How did the vocabulary of fear change in English short fiction between 1820 and 1892?",
  "corpus": {
    "description": "Six English-language short stories and novellas; one document is one work.",
    "selection": "Project Gutenberg books 41, 932, 11231, 43, 375, 1952, chosen by the researcher as well-known works of their decades",
    "sampling": "purposive, not random: canonical works that survived and were digitised",
    "n_documents_planned": 6,
    "table": "corpus", "id_column": "doc_id", "text_column": "text"
  },
  "metadata": {
    "year":   {"description": "year of first publication", "source": "the work's first edition as stated in its Wikipedia article (entered by hand)"},
    "author": {"description": "author as in the catalogue", "source": "Gutendex catalogue"},
    "period": {"description": "1820-1859 or 1860-1899", "source": "derived from year"}
  },
  "preprocessing": {
    "token_pattern": "[a-z]+(?:['’][a-z]+)?",
    "lowercase": true,
    "stopwords": {"file": "stopwords.txt", "source": "scikit-learn 1.9 ENGLISH_STOP_WORDS (318 words)"},
    "lemmatisation": "none",
    "ngrams": [1, 2],
    "front_matter": "Gutenberg header and licence removed by the connector; title pages and contents lines kept"
  },
  "groups": {
    "early": {"column": "period", "value": "1820-1859"},
    "late":  {"column": "period", "value": "1860-1899"}
  },
  "analyses": [
    {"id": "frequencies", "method": "term_frequency", "terms": ["fear", "terror", "horror", "dread"], "by": ["early", "late"]},
    {"id": "keyness_late", "method": "keyness", "target": "late", "reference": "early", "statistic": "log-likelihood G2", "effect_size": "log ratio"},
    {"id": "fear_words", "method": "dictionary",
     "dictionary": {"name": "fear vocabulary", "terms": ["fear", "afraid", "terror*", "horror*", "dread*"],
                    "source": "written for this study: words for fear and its expression, not a published dictionary"}},
    {"id": "topics", "method": "topic_model", "algorithm": "nmf", "k_candidates": [3, 4, 5], "seeds": [1, 2, 3],
     "segment_tokens": 1000, "selection": "reconstruction error and reading the top terms"}
  ],
  "limits": {"sampling_bias": "Six canonical works by English-language authors; what survived, was digitised and is out of U.S. copyright. Nothing here describes fiction of the period in general."}
}
```

What `corpus_design` requires (it sends the data architect back once, then
stops the run):

- `question`; `corpus.description` (what one document is), `corpus.selection`
  (the rule, the catalogue query or the list) and `corpus.sampling` (complete
  population, random with its seed, purposive, convenience);
  `limits.sampling_bias`: whom and what the corpus over- and under-represents.
- `corpus.table`, `id_column`, `text_column`: where the corpus will be in data.db.
- Every metadata field with its `source`. Publication years are not in
  Project Gutenberg's catalogue (only the authors' birth and death years):
  say where each year comes from, and never guess one. A field that cannot be
  filled for some documents carries `"missing": "why"`.
- `preprocessing`:
  - `token_pattern`: a regular expression whose every match is a token, with
    no capturing groups (write `(?:...)`) and no empty match.
    `[a-z]+(?:['’][a-z]+)?` keeps words with an apostrophe (don't, o'clock;
    Project Gutenberg's texts often use the typographic ’) in a lower-cased
    study; `[^\W\d_]+` is any run of letters in any script.
  - `lowercase`: true or false.
  - `stopwords`: `"none"`, or a word list in the study folder (one word per
    line) with its `source`. Name the file here; the data analyst's build
    script writes it from code (e.g.
    `sorted(sklearn.feature_extraction.text.ENGLISH_STOP_WORDS)`, 318 words),
    so the list used is the list recorded. The corpus check freezes every
    word list the design names with its SHA-256; a list changed afterwards
    stops the run.
  - `lemmatisation`: `"none"`, or a CSV `word,lemma` in the study folder with
    its `source`. e2er applies the table, so whatever made the lemmas is
    recorded as its output. No model downloads.
  - `ngrams`: `[1, n]`, n from 1 to 3.
- `groups`: each defined by a metadata column and `value`/`values` (or
  `from`/`to` for numbers), or by a list of `documents`. `all` is every
  document and needs no definition.
- `analyses`, each with an `id` and a `method`:
  - `term_frequency`, `diachronic`: the terms and groups (periods).
  - `keyness`: `target` and `reference` groups.
  - `collocation`: the `measure` (`pmi` or `log-likelihood`), `window` (1 for
    adjacent pairs, which e2er recounts), the node words if any.
  - `dictionary`: the `dictionary` with its `terms` (or a `file`) and its
    `source`. The dictionary is frozen here: the results must use exactly
    this list. An entry ending in `*` matches every token it begins
    (`terror*`: terror, terrors, terrorise).
  - `sentiment`: the `lexicon` with `categories` (e.g. `{"positive": [...],
    "negative": [...]}`) or a `term,category` CSV, and its `citation`
    (authors, year, where published). Use a published lexicon only when its
    file is in the study folder under its licence; never type one from memory.
  - `topic_model`: `algorithm` `lda` or `nmf`, at least two `k_candidates`, at
    least three `seeds`, and `segment_tokens` when documents are cut into
    segments (topic models need many documents; a few books give few).

Write `data_dictionary.json` with the tables the data analyst loads (e.g. the
`e2er-data gutenberg text` table). The corpus table is derived from them by
the build script: name it in `corpus_design.json`, not in the dictionary.

## 2. Building the corpus (the data analyst)

Load the texts:

- Project Gutenberg: `e2er-data gutenberg books ...` to find books (at most
  320 catalogue rows), then `e2er-data gutenberg text --ids 41,932,... --table
  gutenberg_texts` (at most 20 books per load). The connector removes
  Project Gutenberg's header, footer and licence and records the SHA-256 of
  each downloaded file and what it cut.
- The researcher's files: `.csv` and `.jsonl` files in the data folder are
  imported into data.db (a text column per row). Plain `.txt` files are not:
  read them from `data/` in the build script, one document per file.

Then write `build_data.py` and run it with `e2er-run build_data.py`. It
reads the loaded texts, adds the metadata the design declares, and writes:

- the corpus table (`corpus.table` of the design): one row per document with
  the id column, the text column and every metadata column;
- `corpus_manifest.json`: one entry per document and the corpus statistics,
  computed with the recorded preprocessing;
- `summary_statistics.json` (documents, tokens, the length distribution) and
  `data_summary.md`.

```python
import hashlib, json, re, sqlite3, unicodedata

DESIGN = json.load(open("corpus_design.json", encoding="utf-8"))
PRE = DESIGN["preprocessing"]
PATTERN = re.compile(PRE["token_pattern"])
LEMMAS = {}  # {word: lemma} from the lemma CSV when lemmatisation is declared

def tokens(text):
    """e2er's preprocessing, exactly: NFC, lower-casing if declared, every match of the pattern, lemmas."""
    t = unicodedata.normalize("NFC", text)
    if PRE["lowercase"]:
        t = t.lower()
    return [LEMMAS.get(w, w) for w in PATTERN.findall(t)]

def quantile(sorted_values, q):  # linear interpolation, as numpy's default
    pos = (len(sorted_values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)

# ... build rows = [{"doc_id": ..., "text": ..., "year": ..., ...}] and write the corpus table ...
docs = []
for r in rows:
    toks = tokens(r["text"])
    docs.append({"doc_id": r["doc_id"], "source": "Project Gutenberg ebook 41 (gutenberg.pglaf.org mirror)",
                 "licence": "public domain in the USA; Project Gutenberg licence removed",
                 "sha256": hashlib.sha256(r["text"].encode("utf-8")).hexdigest(),
                 "n_tokens": len(toks), "title": r["title"], "year": r["year"]})
```

Counts are of every token; stop words only leave term lists and models. The
corpus statistics: `n_documents`, `n_tokens`, `n_types` (distinct tokens) and
`length` (`min`, `p25`, `median`, `p75`, `max`, `mean` of tokens per
document, two decimals). The manifest:

```json
{"documents": [{"doc_id": "pg41", "source": "...", "licence": "...", "sha256": "...", "n_tokens": 11873, "year": 1820}],
 "corpus": {"n_documents": 6, "n_tokens": 101234, "n_types": 9876,
            "length": {"min": 3712, "p25": 7041.5, "median": 11873.0, "p75": 22610.25, "max": 25871, "mean": 16872.33}}}
```

What `corpus` requires (it sends the data analyst back once, then stops):
every document has a source and a licence, ids are unique, no two documents
have the same text, each SHA-256 is that of the text in the corpus table
(UTF-8), each token count and the corpus statistics are e2er's, and every
declared metadata field is a column with a value in every document (or the
design says why it is missing). It writes `corpus_check.json`.

Remove what is not the work where it matters (tables of contents, editors'
introductions, transcribers' notes) in the build script, and say so in the
design's `front_matter`; the hash is of the text as analysed.

## 3. The analysis (`run_estimation.py`)

Reuse `tokens()` from the build script unchanged. numpy, scipy and
scikit-learn are installed; nothing is downloaded. Every random step has its
seed in the results.

**Frequencies.** Counts per group and per 10,000 tokens of the group
(`count / n_tokens * 10000`). Compare groups only per 10,000 tokens, and
report a term's dispersion (in how many documents it occurs) when one
document could carry the count.

**Keyness** (Dunning 1993; Rayson and Garside 2000). For a term with `a`
occurrences in the target's `c` tokens and `b` in the reference's `d`:

```python
E1, E2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
G2 = 2 * ((a * log(a / E1) if a else 0) + (b * log(b / E2) if b else 0))
log_ratio = log2(((a or 0.5) / c) / ((b or 0.5) / d))   # Hardie 2014; a zero count taken as 0.5
p_value = erfc(sqrt(G2 / 2))                              # chi-squared, 1 degree of freedom
```

G2 says how sure, the log ratio how big; report both, and `more_in` (the
group where the relative frequency is higher). With hundreds of terms tested,
G2 of 3.84 (p < 0.05) means little: use a stricter threshold (15.13 for p <
0.0001, or Bonferroni) and say which. Leave stop words out of key-term lists.

**Collocations.** Adjacent pairs (`window` 1): the pair's count and PMI =
log2(count(w1 w2) * N / (count(w1) * count(w2))), N the group's tokens.
PMI favours rare pairs: set a minimum count (e.g. 5) and report it.

**Dictionary and sentiment measures.** Hits per group (tokens matching an
entry; `x*` matches tokens beginning with x), per 10,000 tokens. Then draw
the validation sample in the same script, with a seed:

```python
import random
rng = random.Random(20261011)
hits = [...]  # every (doc_id, token index, term) where a token matches the dictionary
sample = rng.sample(hits, min(30, len(hits)))
# quote: the passage around the hit, cut from the document's text itself (about 200 characters,
# never edited), so the validator reads the word in its context.
json.dump({"fear_words": {"seed": 20261011, "n_hits_total": len(hits),
                          "items": [{"doc_id": d, "term": t, "quote": passage} for d, t, passage in ...]}},
          open("validation_sample.json", "w"), indent=2)
```

At least 20 items (the template's setting), or every hit when there are
fewer. A quote must appear verbatim in its document and contain the term as
a token. Do not judge the items yourself: the text validator does.

**Topic models** (Blei, Ng and Jordan 2003 for LDA; Lee and Seung 1999 for
NMF). `sklearn.decomposition.NMF(n_components=k, init="nndsvda",
random_state=seed, max_iter=500)` on a TF-IDF matrix, or
`LatentDirichletAllocation(n_components=k, random_state=seed)` on counts,
both with the recorded stop words removed (`CountVectorizer(vocabulary=...)`
or a `tokenizer` that calls `tokens()` and drops stop words; set
`lowercase=False, token_pattern=None` so scikit-learn does not tokenise
again). Then:

- **k**: fit every candidate k and report a metric for each in `k_selection`
  (NMF reconstruction error, LDA perplexity on held-out segments, or a
  coherence score you compute), and choose k by the metric and by reading
  the topics. Say how you chose.
- **Stability**: fit the chosen k with every seed of the design; for each run
  list the top terms (`top_n`, e.g. 10) of each topic; e2er recomputes the
  mean best-match Jaccard overlap of the top terms between every pair of runs
  (for runs i and j: the mean over i's topics of the best overlap with one of
  j's topics, the same from j to i, averaged; then the mean over pairs).
  Below 0.5 the topics depend on the seed: say so; do not interpret them.
- Per topic: at least 5 `top_terms` and at least 2 `example_documents`
  (document ids, with `segment` when documents were cut into segments of
  `segment_tokens` tokens: segment s is tokens `s*size` to `(s+1)*size - 1`),
  the documents or segments with the highest weight. Read them before
  naming a topic; a label is an interpretation, and the paper says so.
- `prevalence`: per group, the mean topic share; the shares of a group add
  up to 1.

**Diachronic change.** Frequencies per period group (`models.<id>.method =
"diachronic"`, `outputs.series`: group, term, count, per_10k), a figure of
frequency over time, and keyness between periods. Periods with few documents
make noisy estimates; give the documents per period.

## 4. The validation (`text_validation.json`, the text validator)

For every dictionary and sentiment measure, read every item of
`validation_sample.json` and judge whether the word, in that passage, means
what the measure assumes (a "fear" word expressing fear, not "for fear of
spoiling the cake"; a "positive" word meant positively, not ironically or
negated). Write:

```json
{"fear_words": {"items": [{"doc_id": "pg932", "term": "terror", "quote": "...",
                           "correct": true, "reason": "the narrator's terror at the house"},
                          {"doc_id": "pg41", "term": "dread", "quote": "...",
                           "correct": false, "reason": "'dread' as an adjective of rank: 'dread sovereign'"}],
                "precision": 0.85, "n_checked": 20, "n_correct": 17}}
```

Copy `doc_id`, `term` and `quote` exactly from the sample. Every item judged
wrong needs its reason; give one for every item. The precision is the share
judged right. Write `text_validation.md`: how you judged, the patterns of the
wrong hits (word senses, negation, quotation), and what they mean for the
measure. Precision below about 0.7 means the dictionary measures something
else in part; the paper must say so.

What `text_validation` requires: a sample with its seed and enough items for
every measure; every quote verbatim in its document and containing its term;
every item judged, nothing judged that is not in the sample, a reason for
every wrong item; the precision equal to the share judged right (also where
the results state it).

## 5. The results, figures and the paper

`estimation_results.json` follows `data/text-results-schema`; state
`corpus.preprocessing` exactly as in the design and `limits.sampling_bias`.
`text_results` recounts every term frequency, keyness score, collocation,
dictionary hit and topic-stability figure, and stops the run on a difference.

Figures (`figure_spec.json`, each with a `source` in the results):
frequency over time (`time_series` from `models.<id>.outputs.series` or the
term frequencies of the period groups), key terms (`bar` of log ratio or G2
from `models.<id>.outputs.terms`), topic prevalence by group (`bar` per group
or `multi_panel`).

Writing: report counts per 10,000 tokens with the group sizes; give G2 with
the effect size; give topics as their top terms and example passages with
the label marked as yours; give a dictionary measure with its precision.
Claim nothing beyond the corpus: a selection of digitised, out-of-copyright
books describes those books, not a period's literature, its readers or its
authors' intentions. Say what a count does not show (meaning, reception,
cause).

## Sources

- Dunning (1993), log-likelihood for rare events: https://aclanthology.org/J93-1003/
- Rayson and Garside (2000), corpus comparison: https://doi.org/10.3115/1117729.1117730
- Hardie (2014), log ratio: https://cass.lancs.ac.uk/log-ratio-an-informal-introduction/
- Blei, Ng and Jordan (2003), LDA: https://jmlr.org/papers/v3/blei03a.html
- Lee and Seung (1999), NMF: https://doi.org/10.1038/44565
- Grimmer and Stewart (2013), text as data: https://doi.org/10.1093/pan/mps028
- Gentzkow, Kelly and Taddy (2019), text as data in economics: https://doi.org/10.1257/jel.20181020
- Church and Hanks (1990), PMI: https://aclanthology.org/J90-1003/
- Greene, O'Callaghan and Cunningham (2014), topic stability: https://doi.org/10.1007/978-3-662-44848-9_32
- Hutto and Gilbert (2014), VADER (a sentiment lexicon for social media text): https://doi.org/10.1609/icwsm.v8i1.14550
