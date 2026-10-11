# Replication package: the vocabulary of fear in six works of short fiction

**Paper ID**: @@PAPER_ID@@

`build_data.py` reads table `gutenberg_texts` from `data.db` (Project Gutenberg books 41, 932, 11231, 43, 375, 1952, loaded with `e2er-data gutenberg text`) and writes the table `corpus`, `corpus_manifest.json` and `stopwords.txt`. `estimation.py` reads `corpus`, `corpus_design.json` and `stopwords.txt` and writes `estimation_results.json` and `validation_sample.json`. numpy and scikit-learn; run them with `python build_data.py` and `python estimation.py` in a folder holding `data.db` and `corpus_design.json`.

The texts are in the public domain in the USA; Project Gutenberg's licence and header were removed when they were loaded.
