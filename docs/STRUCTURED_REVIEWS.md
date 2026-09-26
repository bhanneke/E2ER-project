# Structured reviews

A portable format for what a paper claims, in which every claim can be checked
against the paper.

- Schema: [`docs/schemas/structured_review.schema.json`](schemas/structured_review.schema.json)
- Version: `e2er-structured-review/1`
- Reference implementation: `src/modules/literature/review.py`

This document specifies the format. It is written so that a tool with no
connection to e2er can produce records e2er will read, or read records e2er
produces.

## The problem

A literature search establishes that a paper exists. It returns a title, an
abstract, a DOI. It does not tell you what the paper found, so anything built on
top of it — a related-work section, a synthesis, a research agenda — is written
by someone who has read the metadata and is guessing at the content.

Extracting the content with a language model is the obvious fix, and it is
untrustworthy in the specific way that matters: a fabricated finding is fluent,
correctly formatted, in the register of the field, and indistinguishable from a
real one by reading. A corpus of extracted findings is a corpus of assertions
with no way to tell which are real, and it gets worse as it grows.

## The rule

**A claim is a statement plus the verbatim sentence it came from.**

Verification asks one question of every claim: does that sentence occur in the
source text? A claim whose quote cannot be located is *rejected*, not flagged.

This is deliberately the same discipline e2er applies to numbers. A table cell
must trace to a key in a JSON sidecar or the numbers gate blocks the paper; a
claim must trace to a sentence or it does not enter the corpus. Neither check
asks a model whether it is telling the truth, which is why neither can be
talked out of its verdict.

## The record

```json
{
  "schema_version": "e2er-structured-review/1",
  "doi": "10.1234/example.5678",
  "title": "Spot ETFs and the factor structure of bitcoin",
  "authors": ["A. Author", "B. Coauthor"],
  "year": 2024,
  "source": "openalex",
  "access_license": "cc-by",

  "key_findings": [
    {
      "text": "No detectable change in the equity loading after listing.",
      "evidence": {
        "quote": "We find no detectable change in the equity loading of bitcoin",
        "locator": "Results",
        "char_start": 1840,
        "verified": true,
        "reason": ""
      }
    }
  ],

  "extracted_at": "2026-09-16T11:02:00+00:00",
  "extractor_model": "claude-sonnet-4-5",
  "source_sha256": "9f2c…",
  "source_chars": 48213
}
```

### Fields

Nine claim-bearing fields, each optional:

| Field | Shape | Holds |
|---|---|---|
| `research_question` | claim or null | What the paper asks |
| `theoretical_framework` | claim or null | The lens it argues within |
| `hypotheses` | claim list | What it predicted |
| `methodology` | claim or null | How it identified the effect |
| `data_sources` | claim list | Where the data came from |
| `sample` | claim or null | What was observed, and how much |
| `key_findings` | claim list | What it found |
| `limitations` | claim list | What the authors concede |
| `implications` | claim or null | What follows |

`null` means the field was not extracted, **or** was extracted and rejected. It
is never evidence that the paper lacks one. A record with no `limitations` may
describe a paper with no limitations section, a paper whose limitations the
extractor missed, or a paper whose limitations the extractor invented and lost
at verification. The record does not distinguish these; the verification report
does.

Identity and provenance fields are listed in the schema. Two are load-bearing:

- **`doi`** — bare, lowercased, no `https://doi.org/` prefix. The deduplication
  key across corpora.
- **`source_sha256`** — SHA-256 of the *normalised* source text, not the raw
  text or the PDF bytes. Normalisation (below) is what lets the same PDF read by
  two different extractors fingerprint identically, which is what makes a claim
  portable between corpora.

`schema_version` is the only required field. Everything else degrades
gracefully, but a consumer that cannot tell which contract it is reading cannot
degrade safely.

## Verification

```python
from src.modules.literature.review import verify_review, drop_unverified

report = verify_review(review, source_text)   # mutates each claim's evidence
dropped = drop_unverified(review)             # removes what failed
```

`verify_review` is a pure function of `(record, source text)`. It calls no
model, needs no network, and is therefore testable without a backend and
re-runnable by anyone holding the same text. Three ways a claim fails:

| Reason | Meaning |
|---|---|
| `no quote given` | The claim was asserted without evidence. |
| `quote too short to be evidence (N chars)` | Under `MIN_QUOTE_CHARS` (24). |
| `quote does not appear in the source text` | The paper does not say it. |

The length floor is not a style preference. `"We find"` occurs in essentially
every empirical paper written and would verify against text it never came from,
which would make verification worse than useless — it would launder
fabrications.

### Normalisation

Both the quote and the source are normalised before matching:

- Whitespace collapsed to single spaces
- Soft hyphens removed; hyphenated line breaks rejoined (`load-\ning` → `loading`)
- Non-breaking spaces and smart quotes folded to ASCII

Nothing else. Case is ignored at match time. Word order, punctuation and
wording are *not* normalised, because those are what distinguish a quote from a
paraphrase.

This latitude is exactly the set of things that PDF text extraction does to a
sentence without the paper having said anything different. Widening it further
would start accepting paraphrases; narrowing it would reject true quotes over
line breaks. A checker that rejects true quotes earns a reputation for crying
wolf and gets switched off, which is the failure mode that matters most here.

### Passed is not conclusive

```python
report.passed       # rejected == 0
report.conclusive   # total > 0
```

An extraction that produced nothing passes vacuously. Reported as a single
boolean it would read exactly like an extraction that checked twenty claims and
cleared them all. e2er's numbers gate reported precisely that for months, so
the two are separate here from the start.

**A record is trustworthy only when `passed and conclusive`.**

## Producing records

Any tool may produce these. The obligations are:

1. **Quotes are verbatim spans of the text you extracted from.** Not tidied, not
   corrected, not assembled from two sentences.
2. **Stamp the source.** `source_sha256` over normalised text, `source_chars`,
   `extractor_model`, `extracted_at`. A claim that cannot be tied to the text it
   came from cannot be re-checked by anyone else.
3. **Verify before storing, and drop what fails.** Publishing unverified claims
   in this format is the one thing the format exists to prevent.
4. **Keep the rejections.** They are evidence about the extractor, not the
   paper — see below.

e2er writes records that validate against the schema. It *reads* records that
do not: `review_from_dict()` tolerates missing fields and older versions, so a
corpus outlives its schema. Strict on write, tolerant on read.

## Why keep the rejections

The rejections are the only part of this that measures something.

When an extractor is told that its quotes will be checked mechanically, and it
supplies a quote that is not in the paper, that is a fabrication produced under
the least favourable possible conditions for fabricating. The rate at which it
happens — overall, per field, per model — is a number about language models that
is not otherwise easy to obtain, and it falls out of running the format at all.

The first measurement did not go the way this document originally predicted. It
said findings would be quotable and limitations diffuse and therefore invented
more often. Across eighteen open-access papers, `limitations` produced 92 claims
and **zero** rejections, while the rejections that did occur fell in
`key_findings`, `data_sources` and `methodology`.

The more important result was about the checker rather than the model. Of six
rejections, four were true verbatim quotes that failed on PDF artefacts —
hyphenated line breaks that became hyphen+space, and an `fi` ligature. Only two
were genuine, giving 2/539 ≈ 0.4% rather than the 1.1% first reported. The
normaliser was corrected; see `_match_form` in `review.py`.

The lesson generalises: a verification rate is a statement about the verifier
until the verifier has been checked against the same evidence. Report the
false-rejection rate alongside it, or report neither.

So `verification.rejections` retains each failure after the claim itself is
dropped, and a consumer may ignore it entirely — the record is complete without
it.

## Validating a record

```bash
pip install jsonschema
python -c "
import json, jsonschema
schema = json.load(open('docs/schemas/structured_review.schema.json'))
record = json.load(open('review.json'))
jsonschema.validate(record, schema)
print('valid')
"
```

`tests/test_review_schema.py` runs this against what the reference
implementation emits, including a guard that fails when a field is added to the
dataclass and not to the schema. The schema is checked against the code on every
push, not maintained by hand alongside it.
