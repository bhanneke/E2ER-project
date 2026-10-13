# Data summary

| Table | Source | Rows |
|-------|--------|------|
| `gutenberg_texts` | `e2er-data gutenberg text --ids 41,932,11231,43,375,1952` | 6 |
| `corpus` | `build_data.py` from `gutenberg_texts` | 6 |

The texts are Project Gutenberg's plain-text editions as of 2026-10-11, with the header, footer and licence removed by the connector. `build_data.py` adds the year of first publication (entered by hand; the sources are in `corpus_design.json`), the period and the token counts, writes `corpus_manifest.json` (source, licence and SHA-256 of each text) and `stopwords.txt` (scikit-learn's 318 English stop words).

The corpus has 6 documents and 69,870 tokens (8,691 types). The works differ in length from 3,782 tokens (Owl Creek Bridge) to 25,787 (Jekyll and Hyde); the earlier period has 34,128 tokens, the later 35,742.
