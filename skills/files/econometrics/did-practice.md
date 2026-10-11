# Difference-in-differences in practice: design, modern estimators, pre-trends, sensitivity

For the `policy-evaluation` template. Read `econometrics/did` for the basic
equation; this skill says what the template's checks require and how to meet
them with the estimators the recent literature recommends (Roth, Sant'Anna,
Bilinski and Poe 2023 survey it).

## 1. The design file: `did_design.json` (identification strategist)

```json
{
  "outcome":   {"table": "panel", "column": "under5_mortality", "label": "Under-5 mortality per 1,000 live births"},
  "panel":     {"table": "panel", "unit": "iso3", "time": "year"},
  "treatment": {"table": "adoption", "unit": "iso3", "first_treated": "first_year",
                "description": "first full calendar year the policy was in force", "source": "where the dates come from"},
  "comparison_group": "never_treated",
  "estimator": "callaway_santanna",
  "anticipation": 0,
  "event_window": [-5, 5],
  "reference_period": -1,
  "cluster": "iso3"
}
```

- `panel`: the data.db table with one row per unit and period, its unit and
  time columns. `outcome.column` is in it (or in `outcome.table`).
- `treatment.first_treated`: each unit's first treated period on the panel's
  time axis; empty, 0 or NULL for a unit never treated. Units absent from the
  treatment table count as never treated. Put the treatment dates in data.db
  as their own table (from a documented source: a law's date of entry into
  force, an official list), never typed into the estimation script. The
  never-treated units leave the column empty, so the data dictionary declares
  it with `"min_non_null": 0` (the data contract otherwise asks 90% filled).
- `comparison_group`: `never_treated` or `not_yet_treated`.
- `estimator`: `callaway_santanna`, `sun_abraham`,
  `de_chaisemartin_dhaultfoeuille`, `borusyak_jaravel_spiess`,
  `gardner_two_stage`, `stacked`, `wooldridge_etwfe`, or `twfe`.

Also write `identification_spec.json` as usual. For the robust estimators
declare no fixed effects they do not absorb (`"fixed_effects": []` for
Callaway–Sant'Anna; `["unit", "time"]` for Sun–Abraham or two-way FE), and
`"cluster_level"` = the unit.

### What the design check (`did_design`) stops on

- the outcome, panel or timing columns are not in data.db;
- no comparison group (no never-treated unit for `never_treated`; one single
  treatment date and no never-treated unit for `not_yet_treated`);
- **staggered timing with `twfe`**. When units start treatment in different
  periods, the two-way FE estimate is a weighted average of all 2x2
  comparisons, including "forbidden" ones that use already-treated units as
  controls; with effects that change over time or differ across cohorts the
  weights can be negative and the estimate can have the wrong sign
  (Goodman-Bacon 2021; de Chaisemartin and D'Haultfœuille 2020). Use a robust
  estimator. With one treatment date, two-way FE is the textbook DiD and is fine;
- no cohort with at least 2 (the template's `min_pre_periods`) periods before
  its treatment.

It writes the cohorts, the treated, never-treated and always-treated units and
the pre-periods per cohort to `did_design_check.json`. Read it before
estimating.

## 2. Estimating (econometrics specialist)

e2er's interpreter has numpy, pandas, scipy and statsmodels; there is no
`csdid`/`did` package. Callaway and Sant'Anna's estimator without covariates is
short to write and the safest default:

1. For each cohort g (units first treated in g) and period t, the group-time
   effect ATT(g,t) = [mean Y(g, t) - mean Y(g, b)] - [mean Y(C, t) - mean Y(C, b)],
   with the base period b = g - 1 - anticipation for t >= g ("long
   differences"), and C the comparison units: never treated, or not yet treated
   by max(t, b) (units with g' > max(t, b), excluding g). Use only units
   observed in both periods (balanced pairs).
2. Event-time effects: theta(e) = sum over g of w_g ATT(g, g + e), weights
   proportional to cohort size among cohorts observed at e.
   Pre-periods (e < 0): use the same formula with b = t - 1 (short
   differences, the "varying base" of the R package) or b = g - 1 (universal
   base); say which. Period -1 is the reference (0 by construction under the
   universal base).
3. The overall ATT: the average of theta(e) over e >= 0, or the cohort-size
   weighted average of ATT(g, t) over t >= g; say which.
4. Standard errors: bootstrap by resampling units (clusters) with replacement,
   at least 999 draws, `numpy.random.default_rng(<seed>)` with the seed in the
   script; the SE is the standard deviation of the draws. Confidence intervals
   = estimate ± 1.96 SE (pointwise), and say they are pointwise.

Sun and Abraham (2021): regress Y on unit and period FE plus cohort ×
relative-period dummies (never-treated or last-treated cohort as control,
period -1 excluded), then average the cohort coefficients by event time with
cohort shares as weights; cluster by unit (statsmodels OLS with
`cov_type="cluster"`).

### The results: what `did_results` checks

`estimation_results.json`:

```json
{
  "main": {"specification": "Callaway-Sant'Anna ATT, never-treated comparison",
           "estimator": "callaway_santanna", "hypothesis": "H1",
           "n_observations": 1820, "n_clusters": 91, "cluster_level": "iso3", "fixed_effects": [],
           "coefficients": {"att": {"estimate": -4.1, "se": 1.2, "t_stat": -3.42, "p_value": 0.0009, "df": 90,
                                     "ci_lower": -6.5, "ci_upper": -1.7}}},
  "event_study": {"reference_period": -1, "estimator": "callaway_santanna", "base": "varying",
                  "periods": [{"relative_period": -4, "estimate": 0.3, "se": 0.9, "ci_lower": -1.5, "ci_upper": 2.1},
                              {"relative_period": -3, "...": "..."},
                              {"relative_period": -2, "...": "..."},
                              {"relative_period": 0, "...": "..."}]},
  "pre_trends": {"test": "Wald test that the pre-treatment event-time effects are jointly zero (bootstrap covariance)",
                 "statistic": 2.8, "df": 3, "p_value": 0.42, "n_pre_periods": 3},
  "placebo": {"fake_date_minus_3": {"description": "treatment moved 3 years earlier, post-treatment years dropped",
                                    "estimate": 0.4, "se": 0.8, "p_value": 0.62}},
  "sensitivity": {"not_yet_treated": {"method": "comparison group: not yet treated", "estimate": -3.8, "se": 1.3},
                  "honest_did_rm": {"method": "Rambachan-Roth relative magnitudes", "mbar": 1.0,
                                    "ci_lower": -7.9, "ci_upper": -0.2}}
}
```

The check stops the run when

- `event_study.periods` has fewer than 2 pre-treatment periods besides the
  reference period, or none at or after treatment;
- `pre_trends` is missing, its `n_pre_periods` disagrees with the path, or it
  **rejects at 0.05** and no sensitivity analysis for violations of parallel
  trends is reported (an entry whose name or `method` says Rambachan–Roth,
  honest DiD, relative magnitudes or smoothness). A failed pre-test is the
  data contradicting the design: change the design (comparison group,
  sample) or bound the violation and draw conclusions from the bound;
- neither `placebo` nor `sensitivity` is reported;
- `main.estimator` is missing, differs from the design, or is `twfe` on
  staggered timing.

The joint test: theta_pre = the vector of pre-period estimates, V its
covariance from the bootstrap draws (`numpy.cov` of the draws), W =
theta' V^-1 theta, p = `scipy.stats.chi2.sf(W, k)`. Not rejecting is not
evidence of parallel trends: pre-tests have low power and conditioning on
passing them distorts inference (Roth 2022). Say so, and report a sensitivity
analysis whatever the test says.

Relative-magnitudes bound (Rambachan and Roth 2023), a conservative form you
can compute: M = the largest absolute change between consecutive
pre-period estimates; for a chosen Mbar, the post-period effect is identified
up to ± Mbar·M per period since treatment; report the interval
[theta - Mbar·M·(e+1) - 1.96 SE, theta + Mbar·M·(e+1) + 1.96 SE] for Mbar
= 0.5, 1, 2, and the "breakdown" Mbar at which the interval first contains 0.
Name it as this conservative version, not as the paper's exact procedure.

The event-study plot is drawn from `event_study` by e2er
(`fig_event_study.pdf`, added to `figure_spec.json` when no event-study
figure is there; one that is there must show the same numbers).

Placebos that fit a policy evaluation: the treatment date moved k periods
earlier on pre-treatment data only; an outcome the policy cannot affect; the
never-treated units given fake dates. Sensitivity: the other comparison
group, anticipation of one period, dropping one cohort at a time, the
Rambachan–Roth bound.

## 3. Writing it up

State the treatment dates and their source, the cohorts and how many units
each has, the comparison group, the estimator and why (staggered timing), the
aggregation, the inference (clusters, bootstrap draws) and what the
pre-trends test and the sensitivity analysis show. Every number comes from
`estimation_results.json`. Do not call a non-rejected pre-trends test evidence
that parallel trends hold.
