# Analysis plan (text)

`run_estimation.py` reads table `corpus` from `data.db`, `corpus_design.json` and `stopwords.txt`, and writes `estimation_results.json` (`"result_kind": "text"`) and `validation_sample.json`:

1. Tokens: the design's preprocessing (NFC, lower case, every match of the token pattern), stop words removed only from term lists and models.
2. Frequencies of eight terms per period, per 10,000 tokens, with the number of works each occurs in.
3. Keyness, later against earlier: G2 and log ratio for words with at least 10 occurrences that occur in at least 2 of the 3 later works; the 15 with the highest G2.
4. Collocations: adjacent pairs of content words occurring at least 5 times, PMI.
5. The fear dictionary of the design: hits per period and per work; a random sample of 20 hits (seed 20261011) with their passages for the text validator.
6. NMF on TF-IDF of 1,000-token segments (73 segments), k from 3, 4, 5 chosen by the stability of the top 10 terms across seeds 1, 2, 3; topic shares by period.

numpy and scikit-learn; no web access.
