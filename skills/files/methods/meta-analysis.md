# Systematic review and meta-analysis: protocol, search, screening, extraction, synthesis

A systematic review answers a question from all the studies that meet criteria
fixed in advance; a meta-analysis pools their effects. Read by the protocol
designer, the study screener, the study extractor and the review writer of the
`systematic-review` template, and by the reviewers. The template follows the
PRISMA 2020 statement (Page et al. 2021, `page2021prisma`). The results schema
is `data/metaanalysis-results-schema`.

What is code and what is judgement:

| Step | Who | What |
|---|---|---|
| protocol | protocol designer | `review_protocol.json`, `review_protocol.md` |
| search | e2er | runs the protocol's searches on OpenAlex (and Crossref when named), `records.json`, `search_log.json`, `search_counts.md` |
| protocol review | researcher | approves or edits the protocol, seeing the counts |
| screening | study screener | `screening.json`, `screening.md` |
| screening check | e2er | every record decided, every exclusion with a criterion and a reason; `screening_sample.md` |
| screening review | researcher | reads the unsure records and a sample of exclusions |
| full texts | e2er | open-access PDFs to `fulltext/<id>.txt`, page by page; `fulltext_log.json` |
| extraction | study extractor | `extraction.json`, `extraction.md` |
| extraction check | e2er | every extracted number read back from its page and quote |
| synthesis | e2er | `run_estimation.py`, `estimation_results.json`, figures, tables, references |
| draft | review writer | `paper_draft.tex` |

## 1. The protocol (`review_protocol.json`, the protocol designer)

Write it before any record is seen. It decides what the review can find.

```json
{
  "question": "How strongly is grit associated with academic achievement in university students?",
  "framework": "PECO",
  "elements": {
    "population": "university or college students",
    "exposure": "grit (Grit-O or Grit-S scale)",
    "comparison": "lower grit (a correlation)",
    "outcome": "academic achievement: grade point average or course grades"
  },
  "eligibility": {
    "include": [
      {"id": "I1", "criterion": "quantitative empirical study of university or college students"},
      {"id": "I2", "criterion": "grit measured with the Grit-O or Grit-S scale (total score)"},
      {"id": "I3", "criterion": "reports the Pearson correlation of grit with GPA or grades and the sample size"}
    ],
    "exclude": [
      {"id": "E1", "criterion": "review, meta-analysis, editorial, protocol or conference abstract"},
      {"id": "E2", "criterion": "school pupils, not university students"},
      {"id": "E3", "criterion": "the same sample as another included study (keep the larger report)"}
    ]
  },
  "databases": ["openalex"],
  "searches": [
    {"name": "main", "query": "grit AND (\"academic achievement\" OR \"academic performance\" OR GPA OR \"grade point average\") AND (university OR college OR undergraduate)",
     "search_in": "title_abstract", "from_year": 2007, "to_year": 2025, "types": ["article"], "open_access_only": true}
  ],
  "outcome": {"name": "academic achievement", "description": "GPA or course grades, as reported"},
  "effect_measure": "r",
  "effect_direction": "positive r: students with more grit have higher grades",
  "synthesis": {"tau2_method": "REML", "min_studies": 3, "ci_level": 0.95},
  "risk_of_bias": {
    "tool": "JBI checklist for analytical cross-sectional studies (adapted)",
    "domains": ["sample", "exposure measurement", "outcome measurement", "confounding", "statistical analysis"],
    "levels": ["low", "some concerns", "high", "unclear"]
  }
}
```

- **Question**: one sentence; its parts in the framework that fits (PICO for
  interventions, PECO for exposures, SPIDER or other for qualitative or
  mixed questions).
- **Criteria**: each with an id (I1, I2, ... for inclusion, E1, E2, ... for
  exclusion) and in words a screener can apply to a title and an abstract.
  Name the design, the population, the exposure or intervention, the outcome,
  the statistic a study must report to be pooled, the years and the language.
- **Searches**: concept blocks of synonyms joined by OR, the blocks joined by
  AND, phrases in double quotes, no commas (OpenAlex reads a comma as the end
  of the filter). `search_in` is `title_abstract` (default), `title` or `all`;
  `types` default `["article"]`; `open_access_only` restricts the search to
  open-access works, which makes the full texts available and is a limit of
  the review to state. Size each search with
  `e2er-fieldmap count --query '<query>' --from <year> --to <year> --types article`
  (one OpenAlex request each); aim at 50 to 400 records in all. The search
  step refuses more than its `max_records` (default 600).
- **Databases**: `openalex` (the search is exhaustive within OpenAlex);
  `crossref` adds only the records Crossref ranks as most relevant (no Boolean
  search), which the search log states.
- **Effect measure**: `SMD` (Hedges' g), `MD`, `RD`, `OR`, `RR`, `HR`
  (pooled on the log scale), `logOR`, `logRR`, `logHR`, `r` (pooled as
  Fisher's z) or `generic` (any effect with its standard error). One measure
  per review; say what a positive value means.
- **Synthesis**: `tau2_method` REML (default; Viechtbauer 2005) or DL
  (DerSimonian and Laird 1986); `min_studies`, the fewest studies with a
  poolable effect for a meta-analysis (default 3; below it the review is a
  narrative synthesis, plainly); `ci_level` (default 0.95).
- **Risk of bias**: the tool that fits the designs: RoB 2 for randomised
  trials (Sterne et al. 2019), ROBINS-I for non-randomised studies of
  interventions, Newcastle-Ottawa or the JBI checklists for observational
  studies, or a named custom set. List its domains and the judgements allowed
  (`levels`).

`review_protocol.md`: the same for the researcher, with the reason for each
criterion and the counts the searches gave.

## 2. Screening (`screening.json`, the study screener)

One decision per record of `records.json` (id, title, abstract, year,
journal), none for anything else:

```json
{"decisions": [
  {"id": "W2101234567", "decision": "include"},
  {"id": "W2909876543", "decision": "exclude", "criteria": ["E1"], "reason": "a meta-analysis of grit studies"},
  {"id": "W3001112223", "decision": "exclude", "criteria": ["I1"], "reason": "the sample is high-school pupils"},
  {"id": "W3104445556", "decision": "unsure", "reason": "no abstract; the title fits"}
]}
```

- Exclude only what the title and abstract show to be ineligible, and name the
  criterion it meets (E...) or fails (I...) and what shows it.
- Decide `unsure` when the record does not show it: no abstract, or a
  statistic that may be in the full text. Unsure records go to the full text
  with the included ones; a review loses studies by excluding too early, not
  by reading one full text too many.
- Decide from the record, never from what you remember of a paper.
- `screening.md`: the counts, the criteria used most, the hard cases.

The researcher then reads every unsure record and a sample of the exclusions
(`screening_sample.md`) and corrects decisions in `screening.json`.

## 3. Eligibility and extraction (`extraction.json`, the study extractor)

One entry for every record screened `include` or `unsure`. The full texts are
`fulltext/<id>.txt` with `=== page N ===` lines; `fulltext_log.json` says which
records have one; the rest are assessed on the abstract in `records.json`.

```json
{"studies": [
  {"id": "W2101234567", "decision": "include", "source_text": "full text",
   "label": "Smith 2019", "year": 2019,
   "characteristics": {"design": "cross-sectional survey", "country": "Spain",
                       "population": "first-year undergraduates", "grit_scale": "Grit-S", "outcome_measure": "GPA"},
   "n_total": 412,
   "effect": {"value": 0.31, "n": 412},
   "sources": {
     "effect.value": {"page": 6, "quote": "Grit was positively correlated with GPA (r = .31, p < .001)"},
     "effect.n": {"page": 4, "quote": "The final sample comprised 412 students"},
     "n_total": {"page": 4, "quote": "The final sample comprised 412 students"}
   },
   "risk_of_bias": {"domains": {"sample": "some concerns", "exposure measurement": "low",
                                "outcome measurement": "low", "confounding": "high",
                                "statistical analysis": "low"},
                    "overall": "high", "support": "convenience sample of one course (p. 4); no adjustment (p. 6)"}},
  {"id": "W3104445556", "decision": "exclude", "source_text": "full text", "criteria": ["I3"],
   "reason": "reports only a regression of GPA on grit and conscientiousness, no correlation"}
]}
```

- `decision` is `include` or `exclude`; a full-text exclusion names its
  criteria and the reason, like a screening exclusion.
- `source_text`: `full text` when `fulltext_log.json` has one, else `abstract`;
  `title` when the record has neither, and then the study can only be excluded
  (the criterion that says the report could not be obtained, if the protocol
  has one). A PDF the researcher saves as `data/fulltext/<id>.pdf` is read at
  the next start.
- `effect` holds what the study **prints**, in the protocol's measure:
  `value` with `se`, or with `ci_lower` and `ci_upper` (`ci_level` when not
  95%); for a correlation `value` and `n`; for an SMD either the printed
  `value` with `se`, a CI or `n1` and `n2`, or the group statistics `mean1`,
  `sd1`, `n1`, `mean2`, `sd2`, `n2` (group 1 is the intervention or exposed
  group) from which e2er computes Hedges' g. Ratios are written as printed
  (OR 1.8, not its logarithm); a printed SE of a ratio is the SE of its log.
  Never compute, convert or round a number yourself: e2er does the arithmetic.
- `sources`: for every number in `effect` and for `n_total`, the page of
  `fulltext/<id>.txt` (or `"abstract"`) and a verbatim quote of at least 8
  characters from it that contains the number. Copy the quote character for
  character from the text file, including how the number is printed (`.31`,
  `−0.12`, `1,204`). e2er finds the quote on that page (or elsewhere in the
  text, with a note) and the number in the quote; a quote that is not in the
  text or a number that is not in its quote stops the run. A number taken from
  a table: quote the row as it appears in the text file.
- A study that is eligible but prints nothing that can be pooled stays
  included with `"effect": null` and `no_effect_reason`; it is described, not
  pooled.
- Several effects in one study: take the one the protocol names (the total
  score, the full sample, the primary outcome, the first wave) and say in
  `extraction.md` which you chose and why. Never choose by size: taking the
  larger of two estimates biases the pooled effect upwards.
- A statistic of another kind than the protocol names (a Spearman rho where it
  asks for a Pearson r, a correlation between weekly measures within persons)
  is not the same effect: include it only when the protocol allows it, and say
  in `characteristics` which statistic it is. Two reports of one sample: keep one (criterion E3
  or its like).
- `risk_of_bias`: every domain of the protocol judged with one of its
  `levels`, an `overall` judgement, and `support` naming the pages it rests on.
- `extraction.md`: what was extracted, every judgement call, and the studies
  you were unsure about.

## 4. Synthesis (e2er's code)

`run_estimation.py` is written by e2er (its source is
`src/modules/metaanalysis/stats.py`) and reads `meta_studies.csv`. Nothing to
write here; what it computes, so that the draft reports it correctly:

- each study's effect on the analysis scale (`yi`) and its sampling variance
  (`vi`): log ratios, Fisher's z for correlations, Hedges' g from group
  statistics; a printed SE as printed, else from the CI;
- the random-effects estimate with tau^2 by REML or DL, its normal confidence
  interval, z and p; Cochran's Q; I^2 = tau^2 / (tau^2 + s^2), the share of the
  variation that is heterogeneity (Higgins and Thompson 2002); H^2;
- the prediction interval, t on k - 2 degrees of freedom (Riley, Higgins and
  Deeks 2011): where the effect of a new study is expected to lie. With high
  heterogeneity it is wide; report it beside the confidence interval;
- the common-effect estimate, for comparison only;
- Egger's regression test (Egger et al. 1997) and trim and fill (Duval and
  Tweedie 2000, estimator L0). With fewer than ten studies both have little
  power; say so, and never read a non-significant Egger test as evidence of no
  publication bias;
- leave-one-out estimates;
- below `min_studies`, no pooling: `narrative_only` is true and the review
  describes the studies one by one.

## 5. The review (`paper_draft.tex`, the review writer)

Follow the PRISMA 2020 items: title (systematic review and meta-analysis),
structured abstract, rationale and objective, eligibility criteria,
information sources and search (databases, queries as sent, dates), selection
(one screener, a model, with the researcher's review of a sample), data
collection (extraction by a model, every number checked against the text by
e2er), effect measure, synthesis methods, risk of bias, results (flow,
characteristics, risk of bias, syntheses, heterogeneity, small-study checks,
sensitivity), discussion with limitations, registration (the pre-registration
when it was made).

- Include `\input{tables/meta_flow.tex}`, `\input{tables/meta_studies.tex}`,
  `\input{tables/meta_results.tex}` (only when pooled) and the figures
  `fig_prisma.pdf`, `fig_forest.pdf`, `fig_funnel.pdf` (the last two only when
  pooled). Write no table yourself.
- Every number from `estimation_results.json` (the flow counts are under
  `prisma`). Report the pooled estimate on the scale the studies use (`r`, an
  odds ratio) with its CI, beside tau^2, I^2 and the prediction interval.
- Cite every included study (`meta_references.json` gives the keys) and the
  methods: page2021prisma, viechtbauer2005bias (REML) or dersimonian1986meta
  (DL), higgins2002quantifying, riley2011interpretation, egger1997bias,
  duval2000trim, viechtbauer2010conducting.
- Limits to state: the databases searched (one or two open indexes, not
  MEDLINE, Embase, PsycINFO or Web of Science), open access only when the
  protocol said so, full texts not available, one screener (a model) without a
  second independent screener, extraction by a model, the power of the
  small-study tests.

## Pitfalls

- A search that is too narrow misses studies; one that is too wide cannot be
  screened. Size it with counts before the run searches.
- Two reports of one sample counted twice inflate precision.
- Mixing measures (r with standardised betas, change scores with final values)
  pools things that are not the same; the protocol fixes one.
- I^2 is a share, not an amount: a small tau^2 can have a high I^2 when the
  studies are large. Report tau^2 and the prediction interval with it.
- A funnel plot with few studies says little; asymmetry can come from
  heterogeneity, not only from publication bias.
