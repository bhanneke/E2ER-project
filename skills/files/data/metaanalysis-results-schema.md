# `estimation_results.json` for a meta-analysis — the results schema

## Purpose

A systematic review with a meta-analysis reports the flow of records, the
included studies' effects and the pooled estimate with its heterogeneity. Its
template declares `results = "metaanalysis"`. In the `systematic-review` template
the file is written by e2er's own `run_estimation.py` (source:
`src/modules/metaanalysis/stats.py`) from the checked extraction; nobody
writes it by hand. A deterministic check (`src/core/pipeline/result_kinds.py`)
holds it to this schema, recomputes the pooled estimate and tau^2 from the
studies, and the number check traces the review's numbers to it.

## Shape

```json
{
  "result_kind": "metaanalysis",
  "question": "How strongly is grit associated with academic achievement in university students?",
  "outcome": "academic achievement",
  "effect_measure": "r",
  "analysis_scale": "Fisher's z",
  "effect_direction": "positive r: more grit, higher grades",
  "model": {"type": "random effects", "tau2_method": "REML", "ci_level": 0.95, "min_studies": 3},
  "k": 3,
  "studies": [
    {"id": "W2101234567", "label": "Smith 2019", "year": 2019, "n": 412,
     "yi": 0.320545, "vi": 0.0024449877750611247, "se": 0.049446817643414874,
     "ci_lower": 0.223631, "ci_upper": 0.417459, "estimate_reported_scale": 0.31,
     "ci_lower_reported_scale": 0.219977, "ci_upper_reported_scale": 0.394788,
     "computed": "Fisher's z of r, variance 1/(n - 3)", "risk_of_bias": "high", "weight_percent": 34.0164},
    {"id": "W2209876543", "label": "Lopez 2021", "year": 2021, "n": 250,
     "yi": 0.181983, "vi": 0.004048582995951417, "se": 0.06362847629757777,
     "ci_lower": 0.057273, "ci_upper": 0.306692, "estimate_reported_scale": 0.18,
     "ci_lower_reported_scale": 0.057211, "ci_upper_reported_scale": 0.297425,
     "computed": "Fisher's z of r, variance 1/(n - 3)", "risk_of_bias": "some concerns", "weight_percent": 30.7945},
    {"id": "W3001112223", "label": "Chen 2022", "year": 2022, "n": 520,
     "yi": 0.080171, "vi": 0.0019342359767891683, "se": 0.04397994971335425,
     "ci_lower": -0.006028, "ci_upper": 0.16637, "estimate_reported_scale": 0.08,
     "ci_lower_reported_scale": -0.006028, "ci_upper_reported_scale": 0.164852,
     "computed": "Fisher's z of r, variance 1/(n - 3)", "risk_of_bias": "low", "weight_percent": 35.189}
  ],
  "narrative_only": false,
  "pooled": {"estimate": 0.19329016440531988, "se": 0.07220612191537185, "z": 2.676922112391839,
             "p_value": 0.00743019054784975, "ci_lower": 0.05176876598788274, "ci_upper": 0.33481156282275704,
             "estimate_reported_scale": 0.1909, "ci_lower_reported_scale": 0.0517, "ci_upper_reported_scale": 0.3228},
  "heterogeneity": {"tau2": 0.012882093217840049, "tau": 0.11349930932759039, "tau2_method": "REML",
                    "tau2_converged": true, "i2": 82.85933571527548, "h2": 5.834079609686908,
                    "q": 13.197743918320288, "q_df": 2, "q_p_value": 0.0013619034540949518},
  "prediction_interval": {"lower": -1.515957321689982, "upper": 1.9025376505006215, "df": 1,
                          "lower_reported_scale": -0.9083, "upper_reported_scale": 0.9563},
  "fixed_effect": {"estimate": 0.18542294373401538, "se": 0.029197858123689188,
                   "ci_lower": 0.12819619338587435, "ci_upper": 0.24264969408215642},
  "small_study_effects": {
    "egger": {"intercept": 4.409040568518025, "se": 13.580320750353728, "t": 0.32466394936976595, "df": 1,
              "p_value": 0.8001472772701117, "slope": -0.03513288720181688, "low_power": true},
    "trim_and_fill": {"k0": 0, "side": "left", "estimator": "L0", "estimate": 0.19329016440531988,
                      "se": 0.07220612191537185, "ci_lower": 0.05176876598788274, "ci_upper": 0.33481156282275704,
                      "filled": [], "filled_se": []}
  },
  "leave_one_out": [{"omitted": "W2101234567", "estimate": 0.13, "ci_lower": 0.03, "ci_upper": 0.23,
                     "tau2": 0.004, "i2": 59.0}],
  "prisma": {"identified": {"by_database": {"openalex": 214}, "total": 214}, "duplicates_removed": 0,
             "screened": 214, "excluded_on_title_abstract": 190,
             "excluded_on_title_abstract_by_criterion": {"E1": 40, "I1": 100, "I3": 50},
             "sought_for_full_text": 24, "full_text_not_retrieved": 2, "assessed_on_full_text": 22,
             "assessed_on_abstract_only": 2, "excluded_at_eligibility": 21,
             "excluded_at_eligibility_by_criterion": {"I3": 18, "E2": 3},
             "included_in_review": 3, "included_in_meta_analysis": 3},
  "figures": ["fig_forest.pdf", "fig_funnel.pdf", "fig_prisma.pdf"]
}
```

With three studies the prediction interval is wide (one degree of freedom)
and Egger's test has almost no power; the numbers above are real output of
the code for three invented studies.

## Required, and what the check verifies

- `"result_kind": "metaanalysis"`, an `effect_measure` e2er knows, and
  `model` with `tau2_method` (REML or DL), `ci_level` and `min_studies`.
- `k` equals the number of `studies`; each study has `yi`, `vi` > 0,
  `se` = sqrt(`vi`) and `yi` inside its confidence interval.
- `prisma`: whole counts that add up: identified - duplicates = screened;
  screened - excluded on title and abstract = sought for full text; sought =
  excluded at eligibility + included in the review; included in the
  meta-analysis = `k`.
- Below `min_studies`: `narrative_only` true, `pooled` null and a
  `narrative_reason`. At or above it: `pooled` (estimate inside its CI, p that
  follows from z), `heterogeneity` (tau^2 >= 0, I^2 between 0 and 100,
  `q_df` = k - 1), weights that add up to 100, a `prediction_interval`
  containing the CI when k >= 3, and `small_study_effects.egger` (or its
  `skipped` reason) with p following from t. The pooled estimate and tau^2
  are recomputed from the studies' `yi` and `vi` and must agree.
- `figures` lists `fig_prisma.pdf`, and `fig_forest.pdf` and
  `fig_funnel.pdf` when the studies are pooled.

## Tables

The synthesis writes `tables/meta_flow.tex`, `tables/meta_studies.tex` and
(when pooled) `tables/meta_results.tex` from this file; the draft includes
them with `\input`. Every cell is a value of this file, rounded.
