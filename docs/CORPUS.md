# The corpus

A local library of what papers *claim*, where every claim carries the sentence
it came from and has been checked against it.

The format is specified in [STRUCTURED_REVIEWS.md](STRUCTURED_REVIEWS.md). This
document is about the thing that stores it.

## Why a library rather than a search

The pipeline's literature stage is per-paper and disposable. It searches, writes
thirty BibTeX entries, and throws the work away; run it again next month on a
neighbouring question and it does the same work again, no better for having done
it before. Worse, thirty BibTeX entries tell a drafter that papers exist — not
what any of them found — so the related-work section is written by something
that has read the metadata and is guessing at the content.

The corpus is the opposite: one SQLite file, outside any workspace, that
accumulates. `e2er corpus refresh` re-runs your standing topics, skips
everything already covered, and extracts only what is new. Run it weekly and
coverage builds instead of resetting.

## Getting started

```bash
e2er corpus add "10.1257/aer.20201397"      # one paper by DOI
e2er corpus add ~/papers/smith2024.pdf      # one paper you already have
e2er corpus add --search "stablecoin runs"  # the top hits for a query

e2er corpus topics add "crypto ETF approval"
e2er corpus topics add "tokenized real-world assets"
e2er corpus refresh                         # run every topic; extract what is new

e2er corpus search "null effects of listing"
e2er corpus stats
e2er corpus export ./corpus-export
```

`--json` on any command gives machine-readable output.

## What `add` actually does

1. **Resolve** the target to papers — a DOI lookup, a local file, or a search
   across the configured providers. Providers are interleaved round-robin, so
   no single one can fill the whole limit: left to take the first N hits,
   OpenAlex returned five records whose "open access" URLs were all publisher
   landing pages, and arXiv — which serves real PDFs — was never reached.
2. **Skip** anything already covered, *before* downloading or calling a model.
   This is what makes `refresh` affordable to run on a schedule. Coverage is
   checked by DOI where there is one and by title and year where there is not,
   because arXiv assigns no DOIs and a DOI-only check re-extracted every
   preprint on every refresh, forever.
3. **Acquire the full text**: your local copy first, then a known PDF URL, then
   the open-access resolver chain (Unpaywall → OpenAlex → Crossref → Semantic
   Scholar).
4. **Extract** a structured review — one tool-less model call, chunked if the
   paper is long.
5. **Verify** every claim's quote against the full text, with one coached retry
   for the ones that failed.
6. **Store** what survived. Claims that did not are dropped; the record of them
   is kept.

Steps 3 and 4 fail often and boringly — a paywall, a dead link, a scanned image,
a model that produced nothing checkable. None of them stop the run. Each is
counted and reported at the end:

```
stored 7, skipped 12 already covered, 4 without full text, 1 with nothing checkable.
```

Expect a substantial share of "without full text". Much of the published
literature is not open access, and OA resolvers frequently return a landing page
or a paywall interstitial at a URL ending in `.pdf`. Those are identified and
named rather than mis-reported as scanned documents:

```
  ✗      An Introduction to Decentralized Finance (DeFi)
         no full text: not a PDF (got an HTML page — probably a landing page or paywall)
```

If you have the PDF yourself, `e2er corpus add path/to/paper.pdf` skips the
whole problem — a local copy is tried before anything is downloaded.

## Where it lives

`~/.e2er/corpus.db` by default. `CORPUS_DB` moves it — to an external drive, a
synced folder, or a throwaway file for an experiment.

It is deliberately **not** inside a paper's workspace. A library that resets per
project is not a library.

> Not to be confused with `LOCAL_DATA_DIR`, which points at folders of your own
> files (data, PDFs, `.bib`). That is input. This is what was extracted from it.

## Search finds claims, not papers

```
$ e2er corpus search "did listing change the factor structure"

Spot ETFs and the factor structure of bitcoin (2024)
  [key_findings] No detectable change in the equity loading after listing.
  "We find no detectable change in the equity loading of bitcoin"
  — Results
  10.1234/example.5678
```

The row is a claim, not a paper, because "who found null effects for ETF
listings" is the question a researcher actually has and a bibliography cannot
answer it. `--field key_findings` restricts to one part of the review;
`--field` is repeatable.

Search is FTS5 with bm25 ranking where SQLite provides it and a ranked `LIKE`
fallback where it does not. Query text is tokenised and quoted before it reaches
`MATCH`, because raw user input is not a legal FTS5 expression — `null effects
(ETF)` is a syntax error — and terms are OR-ed rather than AND-ed so that typing
a whole question still finds something.

## What `stats` measures

Beyond size and coverage, `stats` reports something about the extractor rather
than the literature:

```
  extraction
    first-pass claims proposed  412
    rejected (quote not found)   47
    fabrication rate           11.4%

    rejection rate by field
      limitations              24.0%
      theoretical_framework    18.2%
      key_findings              4.1%
```

That is how often a model supplied a quote that was not in the paper **after
being told the quotes would be checked** — fabrication under the least
favourable conditions for fabricating.

Two things make the number trustworthy:

- It is taken from the **first pass only**. The coached retry repairs some
  failures, so the stored corpus verifies clean and cannot be used to measure
  the model. The first attempt is recorded separately for exactly this reason.
- With nothing measured it reports *nothing measured yet*, not `0.0%`. A corpus
  imported from elsewhere carries no measurement, and reporting zero would
  assert that the model never fabricated.

**Read the by-field breakdown before the headline.** On the first real corpus —
eighteen open-access papers, 539 first-pass claims — six were rejected, and
re-downloading each paper showed **four of the six were true quotes** that failed
on PDF artefacts: hyphenated line breaks that arrived as hyphen+space, and an
`fi` ligature. Only two were genuine fabrications. The reported rate was 1.1%;
the real one was about 0.4%.

So a rejection rate is a statement about the verifier until the verifier has
been checked against the same papers. If yours looks high, re-read a sample of
the rejected quotes against their sources before concluding anything about the
model. The normaliser was corrected as a result, and the four artefact cases are
regression tests.

The other prediction that did not survive contact with data: `limitations` was
expected to be the most-invented field, being diffuse and easy to reconstruct.
It produced 92 claims and zero rejections.

## Export

```bash
e2er corpus export ./corpus-export
```

Writes `index.json` plus one JSON file per paper, each validating against the
published schema. This is the portable form — a corpus locked inside a SQLite
file this project happens to write is not infrastructure anyone else can use.

## Storage

| Table | Holds |
|---|---|
| `corpus_papers` | Identity and metadata, one row per paper |
| `corpus_reviews` | The review as JSON, plus the extraction record |
| `corpus_claims` | One row per claim — denormalised, because search hits claims |
| `claims_fts` | FTS5 index over claim text and quotes |
| `corpus_topics` | Standing interests that `refresh` re-runs |

Identity is the DOI where there is one, then the SHA-256 of the normalised
source text, then title and year as a last resort. Title collisions across
preprint and published versions are a merge someone should make deliberately,
not one the database makes silently.

Papers also carry a weaker `title_key` used *only* for the coverage check, since
the canonical key for a DOI-less paper is the hash of its full text and that is
not knowable until after the download and the model call the check exists to
avoid. A false match there costs one paper not re-read; a false miss costs a
download and a model call on every refresh.

Re-extracting a paper **replaces** its claims wholesale rather than merging.
Merging would leave claims from a superseded reading of the paper sitting beside
the current ones, attributed to a paper that no longer supports them.

## The guarantee

`add_review` refuses a review containing an unverified claim. Not a warning — a
refusal. The invariant holds at the door, so nothing reading the corpus has to
re-check:

> If a claim is in this database, its quote was found in the paper it is
> attributed to.
